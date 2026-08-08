"""Resumable initial, incremental, and full synchronization orchestration."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from curator.graphql.adapters import adapt_id_page, adapt_page
from curator.graphql.operations import CAPABILITIES, ENTITY_OPERATIONS, EntityOperation
from curator.sync.repository import SyncRepository

# Id-only rows are small, and the sweep cost is dominated by per-request overhead.
SWEEP_PAGE_SIZE = 5_000


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
    changed_entity_counts: dict[str, int]
    scene_ids: tuple[str, ...]
    deleted_entity_counts: dict[str, int] = field(default_factory=dict)


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
    # last_played_at is how the play pass observes plays; Stash never bumps scene updated_at
    # for one, so without it view history would silently stop updating.
    for type_key, required_fields in {
        **requirements,
        "sceneFilterType": {"play_count", "last_played_at"},
    }.items():
        field_key = "inputFields" if type_key.endswith("FilterType") else "fields"
        type_data = data.get(type_key)
        if not isinstance(type_data, Mapping) or not isinstance(type_data.get(field_key), list):
            raise RuntimeError(f"Stash capability probe is missing {type_key}")
        available = {
            field["name"]
            for field in type_data[field_key]
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

    def sync(self, *, full: bool = False, plays_only: bool = False) -> SyncResult:
        if full and plays_only:
            raise ValueError("full and plays_only are mutually exclusive")
        if plays_only:
            # The play pass is a cheap, targeted follow-up after playback: plays never bump
            # scenes.updated_at, so the scene pass cannot observe them. It shares the
            # incremental run ledger (the mode column only allows 'incremental' and 'full'),
            # which is safe because the cursor machinery keys resumption by run_id and the
            # backend never runs two sidecar jobs at once.
            run_mode = "incremental"
            mode = "plays"
        else:
            run_mode = "full" if full else "incremental"
            mode = run_mode
        capabilities = probe_capabilities(self.client)
        existing = self.repository.resumable_run(run_mode)
        resumed = existing is not None
        if existing is None:
            run_id = self.id_factory()
            self.repository.start_run(
                run_id, run_mode, capabilities.server_version, self.clock_ms()
            )
        else:
            run_id = str(existing["run_id"])
            self.repository.resume_run(run_id)

        counts: dict[str, int] = {}
        changed_counts: dict[str, int] = {}
        deleted_counts: dict[str, int] = {}
        scene_ids: set[str] = set()
        current_entity: str | None = None
        # A full sweep walks every scene by id, so the incremental play pass adds nothing.
        operations = tuple(
            operation
            for operation in ENTITY_OPERATIONS
            if not (full and operation.incremental_only)
        )
        if plays_only:
            operations = tuple(operation for operation in operations if operation.incremental_only)
        try:
            for position, operation in enumerate(operations):
                current_entity = operation.entity_type
                count, ids = self._sync_entity(
                    run_id,
                    operation,
                    full=full,
                    position=position,
                    entity_count=len(operations),
                )
                counts[current_entity] = count
                changed_counts[current_entity] = len(ids)
                if operation.items_key == "scenes":
                    scene_ids.update(ids)
            current_entity = None
            if full:
                self.repository.reconcile(run_id)
            elif not plays_only:
                # The play pass has no id sweep (its ids_document is None), so pruning would
                # be a no-op; skip it explicitly so a later play-only pass can never grow one.
                for operation in operations:
                    current_entity = operation.entity_type
                    deleted = self._prune_deleted(operation)
                    if deleted:
                        deleted_counts[operation.entity_type] = len(deleted)
                current_entity = None
            self.repository.finish_run(run_id, self.clock_ms())
        except Exception as error:
            self.repository.fail_run(run_id, current_entity, str(error), self.clock_ms())
            raise
        return SyncResult(
            run_id,
            mode,
            capabilities.server_version,
            resumed,
            counts,
            changed_counts,
            tuple(sorted(scene_ids)),
            deleted_counts,
        )

    def _prune_deleted(self, operation: EntityOperation) -> tuple[str, ...]:
        """Drop entities Stash no longer has.

        Incremental passes only ever add: a deleted entity has no updated_at to carry it past
        the watermark, so it lingers until a full sync. Stash exposes no deletion feed, so
        the only way to see one is to compare id sets. The count probe is a single cheap
        request; the sweep behind it runs only once drift actually exists.
        """
        if operation.ids_document is None:
            return ()
        local_total = self.repository.entity_count(operation.entity_type)
        probe = self.client.execute(operation.ids_document, {"page": 1, "perPage": 0})
        remote_total = adapt_id_page(
            probe, root_key=operation.root_key, items_key=operation.items_key
        ).total
        # The passes above already applied every addition, so local can only exceed remote by
        # entities Stash has dropped.
        if local_total <= remote_total:
            return ()
        present: set[str] = set()
        page = 1
        while True:
            data = self.client.execute(
                operation.ids_document, {"page": page, "perPage": SWEEP_PAGE_SIZE}
            )
            adapted = adapt_id_page(
                data, root_key=operation.root_key, items_key=operation.items_key
            )
            present.update(adapted.ids)
            if not adapted.ids or len(present) >= adapted.total:
                break
            page += 1
        if not present:
            # An empty library is indistinguishable from a broken response; never act on it.
            return ()
        return self.repository.delete_absent(operation.entity_type, present)

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
        sort = "id" if full else operation.sort
        direction = "ASC" if full else "DESC"
        variables: dict[str, object] = (
            operation.variables_for(baseline) if operation.variables_for else {}
        )
        while True:
            data = self.client.execute(
                operation.document,
                {
                    "page": page,
                    "perPage": self.page_size,
                    "sort": sort,
                    "direction": direction,
                    **variables,
                },
            )
            adapted = adapt_page(data, root_key=operation.root_key, items_key=operation.items_key)
            timestamps = tuple(
                timestamp
                for timestamp in (operation.watermark_of(item) for item in adapted.items)
                if timestamp
            )
            changed = self.repository.save_page(
                run_id,
                operation.entity_type,
                adapted.items,
                next_page=page + 1,
                page_high_watermark=max(timestamps, default=None),
                now_ms=self.clock_ms(),
                record_seen=full,
            )
            processed += len(adapted.items)
            ids.extend(changed)
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
