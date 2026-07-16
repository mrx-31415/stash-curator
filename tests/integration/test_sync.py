from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from curator.storage import MigrationRunner, connect_database
from curator.sync import SyncService
from curator.sync.repository import SyncRepository


def _tag(identifier: str, updated: str = "2026-01-01T00:00:00Z") -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"Tag {identifier}",
        "updated_at": updated,
        "parents": [],
        "stash_ids": [
            {"endpoint": "https://stashdb.org/graphql", "stash_id": f"external-{identifier}"}
        ],
    }


def _studio(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"Studio {identifier}",
        "favorite": False,
        "rating100": None,
        "updated_at": "2026-01-01T00:00:00Z",
        "parent_studio": None,
    }


def _performer(identifier: str, tag: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": f"Performer {identifier}",
        "favorite": True,
        "rating100": 90,
        "updated_at": "2026-01-02T00:00:00Z",
        "gender": "FEMALE",
        "weight": 55,
        "fake_tits": "Natural",
        "tags": [_tag(tag)],
    }


def _scene(identifier: str, performer: str, tag: str, studio: str) -> dict[str, object]:
    return {
        "id": identifier,
        "title": f"Scene {identifier}",
        "details": "Synthetic fixture",
        "date": "2025-01-01",
        "rating100": None,
        "updated_at": f"2026-01-0{identifier}T00:00:00Z",
        "play_count": 1,
        "play_duration": 120.0,
        "play_history": ["2026-01-01T12:00:00Z"],
        "o_history": [],
        "studio": _studio(studio),
        "tags": [_tag(tag)],
        "performers": [
            {
                "id": performer,
                "name": f"Performer {performer}",
                "updated_at": "2026-01-02T00:00:00Z",
            }
        ],
        "files": [{"id": f"file-{identifier}", "duration": 300.0}],
        "scene_markers": [],
    }


class SyntheticClient:
    def __init__(
        self,
        entities: dict[str, list[dict[str, object]]],
        *,
        fail_once: tuple[str, int] | None = None,
    ) -> None:
        self.entities = entities
        self.fail_once = fail_once
        self.failed = False
        self.calls: list[tuple[str, int | None]] = []

    def execute(
        self, document: str, variables: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        if "CuratorCapabilities" in document:
            self.calls.append(("capabilities", None))
            return {
                "version": {"version": "v-test"},
                "queryType": {
                    "fields": [
                        {"name": name}
                        for name in ("findTags", "findStudios", "findPerformers", "findScenes")
                    ]
                },
                "sceneType": {
                    "fields": [
                        {"name": name}
                        for name in (
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
                        )
                    ]
                },
                "performerType": {
                    "fields": [
                        {"name": name}
                        for name in ("id", "updated_at", "favorite", "weight", "fake_tits")
                    ]
                },
                "tagType": {
                    "fields": [{"name": name} for name in ("id", "updated_at", "stash_ids")]
                },
            }
        names = {
            "CuratorTags": ("tag", "findTags", "tags"),
            "CuratorStudios": ("studio", "findStudios", "studios"),
            "CuratorPerformers": ("performer", "findPerformers", "performers"),
            "CuratorScenes": ("scene", "findScenes", "scenes"),
        }
        entity_type, root, collection = next(
            value for name, value in names.items() if name in document
        )
        assert variables is not None
        page_value = variables["page"]
        per_page_value = variables["perPage"]
        assert isinstance(page_value, int)
        assert isinstance(per_page_value, int)
        page = page_value
        per_page = per_page_value
        self.calls.append((entity_type, page))
        if self.fail_once == (entity_type, page) and not self.failed:
            self.failed = True
            raise RuntimeError("synthetic interruption")
        all_items = self.entities[entity_type]
        start = (page - 1) * per_page
        return {root: {"count": len(all_items), collection: all_items[start : start + per_page]}}


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    database = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(database).migrate(applied_at_ms=1)
    return database


def _entities() -> dict[str, list[dict[str, object]]]:
    return {
        "tag": [_tag("t1"), _tag("t2")],
        "studio": [_studio("s1")],
        "performer": [_performer("p1", "t1")],
        "scene": [_scene("1", "p1", "t1", "s1"), _scene("2", "p1", "t2", "s1")],
    }


def test_sync_deduplicates_tag_stash_ids_by_endpoint(connection: sqlite3.Connection) -> None:
    entities = _entities()
    entities["tag"][0]["stash_ids"] = [
        {"endpoint": "https://stashdb.org/graphql", "stash_id": "external-t1"},
        {"endpoint": "https://stashdb.org/graphql", "stash_id": "duplicate-t1"},
    ]
    SyncService(SyntheticClient(entities), SyncRepository(connection), page_size=2).sync()

    assert connection.execute(
        "SELECT stash_id FROM source_tag_stash_id WHERE tag_id='t1'"
    ).fetchone()[0] == "external-t1"


def test_full_sync_resumes_at_transactionally_saved_page(
    connection: sqlite3.Connection,
) -> None:
    client = SyntheticClient(_entities(), fail_once=("scene", 2))
    service = SyncService(
        client,
        SyncRepository(connection),
        page_size=1,
        clock_ms=lambda: 100,
        id_factory=lambda: "run-1",
    )

    with pytest.raises(RuntimeError, match="interruption"):
        service.sync(full=True)
    assert connection.execute("SELECT count(*) FROM source_scene").fetchone()[0] == 1
    cursor = connection.execute(
        "SELECT page_cursor, state FROM sync_cursor WHERE entity_type = 'scene'"
    ).fetchone()
    assert tuple(cursor) == ("2", "failed")

    result = service.sync(full=True)

    assert result.resumed is True
    assert result.run_id == "run-1"
    assert result.entity_counts["scene"] == 1
    assert connection.execute("SELECT count(*) FROM source_scene").fetchone()[0] == 2
    assert connection.execute("SELECT state FROM sync_run").fetchone()[0] == "complete"
    assert tuple(
        connection.execute(
            "SELECT endpoint, stash_id FROM source_tag_stash_id WHERE tag_id='t1'"
        ).fetchone()
    ) == ("https://stashdb.org/graphql", "external-t1")
    scene_calls_after_failure = [call for call in client.calls if call[0] == "scene"]
    assert scene_calls_after_failure == [("scene", 1), ("scene", 2), ("scene", 2)]


def test_full_sync_reconciles_deleted_source_entities(connection: sqlite3.Connection) -> None:
    first = SyncService(
        SyntheticClient(_entities()),
        SyncRepository(connection),
        page_size=2,
        clock_ms=lambda: 100,
        id_factory=lambda: "run-1",
    )
    first.sync(full=True)

    reduced = _entities()
    reduced["tag"] = [_tag("t2")]
    reduced["scene"] = [_scene("2", "p1", "t2", "s1")]
    second = SyncService(
        SyntheticClient(reduced),
        SyncRepository(connection),
        page_size=2,
        clock_ms=lambda: 200,
        id_factory=lambda: "run-2",
    )
    second.sync(full=True)

    scene_ids = [row[0] for row in connection.execute("SELECT scene_id FROM source_scene")]
    tag_ids = [row[0] for row in connection.execute("SELECT tag_id FROM source_tag")]
    assert scene_ids == ["2"]
    assert tag_ids == ["t2"]
    assert connection.execute("SELECT favorite FROM source_performer").fetchone()[0] == 1


def test_incremental_sync_stops_after_crossing_previous_watermark(
    connection: sqlite3.Connection,
) -> None:
    initial = SyncService(
        SyntheticClient(_entities()),
        SyncRepository(connection),
        page_size=1,
        clock_ms=lambda: 100,
        id_factory=lambda: "run-1",
    )
    initial.sync()

    updated = _entities()
    updated["tag"].insert(0, _tag("t3", "2026-02-01T00:00:00Z"))
    client = SyntheticClient(updated)
    incremental = SyncService(
        client,
        SyncRepository(connection),
        page_size=1,
        clock_ms=lambda: 200,
        id_factory=lambda: "run-2",
    )
    result = incremental.sync()

    assert result.mode == "incremental"
    assert ("tag", 1) in client.calls
    assert ("tag", 2) in client.calls
    assert ("tag", 3) not in client.calls
    assert (
        connection.execute("SELECT count(*) FROM source_tag WHERE tag_id = 't3'").fetchone()[0] == 1
    )
