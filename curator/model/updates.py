"""Durable, debounced preference-model updates."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.model.builder import ModelBuildResult, PreferenceModelBuilder
from curator.storage import transaction


@dataclass(frozen=True)
class ModelUpdateStatus:
    requested_generation: int
    published_generation: int
    requested_at_ms: int | None
    last_started_at_ms: int | None
    last_finished_at_ms: int | None
    last_duration_ms: int | None
    last_cause: str | None
    last_error: str | None
    stage_timings_ms: dict[str, int]

    @property
    def pending(self) -> bool:
        return self.requested_generation > self.published_generation


class ModelUpdateCoordinator:
    """Coalesce durable update requests; a resident plugin supplies the wake-up loop."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        config: CuratorConfig = DEFAULT_CONFIG,
        *,
        debounce_ms: int = 2_000,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.connection = connection
        self.config = config
        self.debounce_ms = debounce_ms
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def request(self, cause: str) -> ModelUpdateStatus:
        """Mark the model dirty, joining the caller's transaction when one is active."""
        if not cause:
            raise ValueError("update cause must not be empty")

        def write() -> None:
            self.connection.execute(
                """
                UPDATE model_update_state SET
                    requested_generation=requested_generation+1,
                    requested_at_ms=?, last_cause=?, last_error=NULL
                WHERE singleton=1
                """,
                (self.clock_ms(), cause),
            )

        if self.connection.in_transaction:
            write()
        else:
            with transaction(self.connection):
                write()
        return self.status()

    def status(self) -> ModelUpdateStatus:
        row = self.connection.execute(
            "SELECT * FROM model_update_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise RuntimeError("model update state is not initialized; run migrations")
        return ModelUpdateStatus(
            requested_generation=int(row["requested_generation"]),
            published_generation=int(row["published_generation"]),
            requested_at_ms=(
                int(row["requested_at_ms"]) if row["requested_at_ms"] is not None else None
            ),
            last_started_at_ms=(
                int(row["last_started_at_ms"]) if row["last_started_at_ms"] is not None else None
            ),
            last_finished_at_ms=(
                int(row["last_finished_at_ms"]) if row["last_finished_at_ms"] is not None else None
            ),
            last_duration_ms=(
                int(row["last_duration_ms"]) if row["last_duration_ms"] is not None else None
            ),
            last_cause=str(row["last_cause"]) if row["last_cause"] else None,
            last_error=str(row["last_error"]) if row["last_error"] else None,
            stage_timings_ms={
                str(key): int(value)
                for key, value in json.loads(str(row["stage_timings_json"])).items()
            },
        )

    def drain(self, *, force: bool = False, max_builds: int = 2) -> tuple[ModelBuildResult, ...]:
        """Publish ready work; cap the loop so a busy producer cannot starve callers."""
        built: list[ModelBuildResult] = []
        for _ in range(max_builds):
            status = self.status()
            if not status.pending:
                break
            now = self.clock_ms()
            requested_at_ms = status.requested_at_ms if status.requested_at_ms is not None else now
            if not force and now - requested_at_ms < self.debounce_ms:
                break
            generation = status.requested_generation
            with transaction(self.connection):
                self.connection.execute(
                    """
                    UPDATE model_update_state SET last_started_at_ms=?, last_error=NULL
                    WHERE singleton=1
                    """,
                    (now,),
                )
            started = time.perf_counter()
            try:
                result = PreferenceModelBuilder(
                    self.connection, self.config, clock_ms=self.clock_ms
                ).build()
            except Exception as error:
                with transaction(self.connection):
                    self.connection.execute(
                        "UPDATE model_update_state SET last_error=? WHERE singleton=1",
                        (str(error)[:2000],),
                    )
                raise
            duration_ms = round((time.perf_counter() - started) * 1000)
            with transaction(self.connection):
                self.connection.execute(
                    """
                    UPDATE model_update_state SET published_generation=?,
                        last_finished_at_ms=?, last_duration_ms=?, last_error=NULL,
                        stage_timings_json=?
                    WHERE singleton=1
                    """,
                    (
                        generation,
                        self.clock_ms(),
                        duration_ms,
                        json.dumps(result.stage_timings_ms, sort_keys=True, separators=(",", ":")),
                    ),
                )
            built.append(result)
        return tuple(built)
