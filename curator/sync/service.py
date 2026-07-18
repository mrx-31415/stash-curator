"""Resumable initial, incremental, and full synchronization orchestration."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from curator.graphql.adapters import SourceEntity, adapt_page
from curator.graphql.operations import CAPABILITIES, ENTITY_OPERATIONS, EntityOperation
from curator.sync.repository import SyncRepository


class QueryClient(Protocol):
    def execute(
        self, document: str, variables: Mapping[str, object] | None = None
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class Capabilities:
    server_version: str


@dataclass(frozen=True)
class SyncResult:
    run_id: str
    mode: str
    server_version: str
    resumed: bool
    entity_counts: dict[str, int]
    scene_ids: tuple[str, ...]


def probe_capabilities(client: QueryClient) -> Capabilities:
    """Verify connectivity and the minimum version response shape."""
    data = client.execute(CAPABILITIES)
    version = data.get("version")
    if not isinstance(version, Mapping) or not isinstance(version.get("version"), str):
        raise RuntimeError("Stash did not return a compatible version response")
    requirements = {
        "queryType": {"findTags", "findStudios", "findPerformers", "findScenes"},
        "sceneType": {
            "id",
            "updated_at",
            "play_count",
            "play_duration",
            "play_history",
            "o_history",
            "files",
            "scene_markers",
            "tags",
            "performers",
        },
        "performerType": {"id", "updated_at", "favorite", "weight", "fake_tits"},
        "tagType": {"id", "updated_at", "stash_ids"},
    }
    for type_key, required_fields in requirements.items():
        type_data = data.get(type_key)
        if not isinstance(type_data, Mapping) or not isinstance(type_data.get("fields"), list):
            raise RuntimeError(f"Stash capability probe is missing {type_key}")
        available = {
            field["name"]
            for field in type_data["fields"]
            if isinstance(field, Mapping) and isinstance(field.get("name"), str)
        }
        missing = sorted(required_fields - available)
        if missing:
            raise RuntimeError(f"Stash {type_key} is missing required fields: {missing}")
    return Capabilities(server_version=version["version"])


class SyncService:
    """Synchronize normalized Stash facts without touching published models."""

    def __init__(
        self,
        client: QueryClient,
        repository: SyncRepository,
        *,
        page_size: int = 250,
        clock_ms: Callable[[], int] | None = None,
        id_factory: Callable[[], str] | None = None,
        progress: Callable[[str, int, int, int, int], None] | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.client = client
        self.repository = repository
        self.page_size = page_size
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self.progress = progress

    def sync(self, *, full: bool = False) -> SyncResult:
        mode = "full" if full else "incremental"
        capabilities = probe_capabilities(self.client)
        existing = self.repository.resumable_run(mode)
        resumed = existing is not None
        if existing is None:
            run_id = self.id_factory()
            self.repository.start_run(run_id, mode, capabilities.server_version, self.clock_ms())
        else:
            run_id = str(existing["run_id"])
            self.repository.resume_run(run_id)

        counts: dict[str, int] = {}
        scene_ids: set[str] = set()
        current_entity: str | None = None
        try:
            for position, operation in enumerate(ENTITY_OPERATIONS):
                current_entity = operation.entity_type
                count, ids = self._sync_entity(
                    run_id,
                    operation,
                    full=full,
                    position=position,
                    entity_count=len(ENTITY_OPERATIONS),
                )
                counts[current_entity] = count
                if current_entity == "scene":
                    scene_ids.update(ids)
            current_entity = None
            if full:
                self.repository.reconcile(run_id)
            self.repository.finish_run(run_id, self.clock_ms())
        except Exception as error:
            self.repository.fail_run(run_id, current_entity, str(error), self.clock_ms())
            raise
        return SyncResult(
            run_id, mode, capabilities.server_version, resumed, counts, tuple(sorted(scene_ids))
        )

    def _sync_entity(
        self,
        run_id: str,
        operation: EntityOperation,
        *,
        full: bool,
        position: int,
        entity_count: int,
    ) -> tuple[int, tuple[str, ...]]:
        page = self.repository.prepare_entity(run_id, operation.entity_type, self.clock_ms())
        if page is None:
            if self.progress:
                self.progress(operation.entity_type, 1, 1, position, entity_count)
            return 0, ()
        baseline, _ = self.repository.cursor_watermarks(operation.entity_type)
        processed = 0
        ids: list[str] = []
        sort = "id" if full else "updated_at"
        direction = "ASC" if full else "DESC"
        while True:
            data = self.client.execute(
                operation.document,
                {"page": page, "perPage": self.page_size, "sort": sort, "direction": direction},
            )
            adapted = adapt_page(data, root_key=operation.root_key, items_key=operation.items_key)
            timestamps = tuple(
                timestamp
                for timestamp in (self._updated_at(item) for item in adapted.items)
                if timestamp
            )
            self.repository.save_page(
                run_id,
                operation.entity_type,
                adapted.items,
                next_page=page + 1,
                page_high_watermark=max(timestamps, default=None),
                now_ms=self.clock_ms(),
                record_seen=full,
            )
            processed += len(adapted.items)
            ids.extend(item.id for item in adapted.items)
            if self.progress:
                self.progress(
                    operation.entity_type,
                    min(processed, adapted.total),
                    adapted.total,
                    position,
                    entity_count,
                )
            reached_watermark = bool(
                not full and baseline and timestamps and min(timestamps) <= baseline
            )
            exhausted = not adapted.items or page * self.page_size >= adapted.total
            if reached_watermark or exhausted:
                self.repository.complete_entity(run_id, operation.entity_type, self.clock_ms())
                return processed, tuple(ids)
            page += 1

    @staticmethod
    def _updated_at(item: SourceEntity) -> str | None:
        return item.updated_at
