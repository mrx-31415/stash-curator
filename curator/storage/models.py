"""Atomic model-version lifecycle."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from curator.storage.database import StorageError, transaction


@dataclass(frozen=True)
class ModelVersion:
    """Persisted model build metadata."""

    model_id: str
    status: str
    feature_version: str
    config_json: str
    sync_watermark: str | None
    created_at_ms: int
    published_at_ms: int | None


def _row_to_model(row: sqlite3.Row) -> ModelVersion:
    return ModelVersion(
        model_id=str(row["model_id"]),
        status=str(row["status"]),
        feature_version=str(row["feature_version"]),
        config_json=str(row["config_json"]),
        sync_watermark=str(row["sync_watermark"]) if row["sync_watermark"] is not None else None,
        created_at_ms=int(row["created_at_ms"]),
        published_at_ms=(
            int(row["published_at_ms"]) if row["published_at_ms"] is not None else None
        ),
    )


class ModelStore:
    """Create and atomically publish immutable model versions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def start_build(
        self,
        *,
        model_id: str | None = None,
        feature_version: str,
        config: object,
        sync_watermark: str | None,
        created_at_ms: int,
    ) -> ModelVersion:
        model_id = model_id or uuid4().hex
        config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO model_version(
                    model_id, status, feature_version, config_json,
                    sync_watermark, created_at_ms
                ) VALUES (?, 'building', ?, ?, ?, ?)
                """,
                (model_id, feature_version, config_json, sync_watermark, created_at_ms),
            )
        return self.get(model_id)

    def get(self, model_id: str) -> ModelVersion:
        row = self.connection.execute(
            "SELECT * FROM model_version WHERE model_id = ?", (model_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"unknown model version: {model_id}")
        return _row_to_model(row)

    def current(self) -> ModelVersion | None:
        row = self.connection.execute(
            "SELECT * FROM model_version WHERE status = 'published'"
        ).fetchone()
        return _row_to_model(row) if row is not None else None

    def publish(self, model_id: str, *, published_at_ms: int) -> ModelVersion:
        """Publish a completed build and supersede the previous model atomically."""
        with transaction(self.connection):
            row = self.connection.execute(
                "SELECT status FROM model_version WHERE model_id = ?", (model_id,)
            ).fetchone()
            if row is None:
                raise StorageError(f"unknown model version: {model_id}")
            if row["status"] != "building":
                raise StorageError(f"model is not publishable from status {row['status']}")

            self.connection.execute(
                "UPDATE model_version SET status = 'superseded' WHERE status = 'published'"
            )
            self.connection.execute(
                """
                UPDATE model_version
                SET status = 'published', published_at_ms = ?
                WHERE model_id = ?
                """,
                (published_at_ms, model_id),
            )
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value)
                VALUES ('current_model_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (model_id,),
            )
        return self.get(model_id)

    def fail(self, model_id: str) -> ModelVersion:
        with transaction(self.connection):
            cursor = self.connection.execute(
                """
                UPDATE model_version SET status = 'failed'
                WHERE model_id = ? AND status = 'building'
                """,
                (model_id,),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"model is not a building model: {model_id}")
        return self.get(model_id)
