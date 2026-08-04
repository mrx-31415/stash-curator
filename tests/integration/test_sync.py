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


def _last_play(scene: Mapping[str, object]) -> str:
    history = scene.get("play_history")
    assert isinstance(history, list)
    return max((str(item) for item in history), default="")


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
        self.variables: list[tuple[str, dict[str, object]]] = []

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
                "sceneFilterType": {
                    "inputFields": [
                        {"name": name} for name in ("play_count", "last_played_at", "updated_at")
                    ]
                },
            }
        names = {
            "CuratorTags": ("tag", "findTags", "tags"),
            "CuratorStudios": ("studio", "findStudios", "studios"),
            "CuratorPerformers": ("performer", "findPerformers", "performers"),
            "CuratorScenePlays": ("scene_play", "findScenes", "scenes"),
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
        self.variables.append((entity_type, dict(variables)))
        if self.fail_once == (entity_type, page) and not self.failed:
            self.failed = True
            raise RuntimeError("synthetic interruption")
        all_items = (
            self._played_scenes(variables.get("sceneFilter"))
            if entity_type == "scene_play"
            else self._ordered(self.entities[entity_type], variables)
        )
        start = (page - 1) * per_page
        return {root: {"count": len(all_items), collection: all_items[start : start + per_page]}}

    @staticmethod
    def _ordered(
        items: list[dict[str, object]], variables: Mapping[str, object]
    ) -> list[dict[str, object]]:
        key = str(variables["sort"])
        return sorted(
            items, key=lambda item: str(item[key]), reverse=variables["direction"] == "DESC"
        )

    def _played_scenes(self, scene_filter: object) -> list[dict[str, object]]:
        """Mimic Stash: played scenes only, newest play first, honoring last_played_at."""
        assert isinstance(scene_filter, Mapping)
        assert scene_filter["play_count"] == {"value": 0, "modifier": "GREATER_THAN"}
        played = scene_filter.get("last_played_at")
        since = str(played["value"]) if isinstance(played, Mapping) else None
        selected = [
            scene
            for scene in self.entities["scene"]
            if _last_play(scene) and (since is None or str(_last_play(scene)) > since)
        ]
        return sorted(selected, key=_last_play, reverse=True)


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

    assert (
        connection.execute("SELECT stash_id FROM source_tag_stash_id WHERE tag_id='t1'").fetchone()[
            0
        ]
        == "external-t1"
    )


def test_sync_reports_page_progress(connection: sqlite3.Connection) -> None:
    updates: list[tuple[str, int, int, int, int]] = []
    SyncService(
        SyntheticClient(_entities()),
        SyncRepository(connection),
        page_size=1,
        progress=lambda *update: updates.append(update),
    ).sync()

    assert updates[-1] == ("scene_play", 2, 2, 4, 5)
    assert ("tag", 1, 2, 0, 5) in updates


def test_incremental_sync_imports_plays_without_an_updated_at_change(
    connection: sqlite3.Connection,
) -> None:
    entities = _entities()
    client = SyntheticClient(entities)
    # One scene per page, so the updated_at pass stops at its watermark before reaching scene 1.
    service = SyncService(client, SyncRepository(connection), page_size=1)
    service.sync()

    # Stash records a play without touching scenes.updated_at.
    scene = entities["scene"][0]
    history = scene["play_history"]
    assert isinstance(history, list)
    history.append("2026-02-01T09:30:00Z")
    scene["play_count"] = 2
    client.calls.clear()

    result = service.sync()
    assert ("scene", 2) not in client.calls

    played = connection.execute(
        "SELECT played_at_ms FROM source_play WHERE scene_id='1' ORDER BY ordinal"
    ).fetchall()
    assert len(played) == 2
    assert (
        connection.execute("SELECT play_count FROM source_scene WHERE scene_id='1'").fetchone()[0]
        == 2
    )
    assert "1" in result.scene_ids
    assert result.changed_entity_counts["scene"] == 0
    assert result.changed_entity_counts["scene_play"] == 1


def test_play_pass_resumes_from_its_own_watermark(connection: sqlite3.Connection) -> None:
    client = SyntheticClient(_entities())
    service = SyncService(client, SyncRepository(connection), page_size=10)
    service.sync()
    client.variables.clear()
    service.sync()

    filters = [
        variables["sceneFilter"]
        for entity_type, variables in client.variables
        if entity_type == "scene_play"
    ]
    assert filters == [
        {
            "play_count": {"value": 0, "modifier": "GREATER_THAN"},
            "last_played_at": {"value": "2026-01-01T12:00:00Z", "modifier": "GREATER_THAN"},
        }
    ]
    assert (
        connection.execute(
            "SELECT watermark FROM sync_cursor WHERE entity_type='scene_play'"
        ).fetchone()[0]
        == "2026-01-01T12:00:00Z"
    )


def test_full_sync_skips_the_play_pass(connection: sqlite3.Connection) -> None:
    client = SyntheticClient(_entities())
    SyncService(client, SyncRepository(connection), page_size=10).sync(full=True)

    assert not [entity_type for entity_type, _ in client.calls if entity_type == "scene_play"]
    assert (
        connection.execute("SELECT count(*) FROM source_play WHERE scene_id='1'").fetchone()[0] == 1
    )


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
    assert result.changed_entity_counts["tag"] == 1
    assert result.scene_ids == ()


def test_incremental_sync_skips_unchanged_source_rows(connection: sqlite3.Connection) -> None:
    service = SyncService(SyntheticClient(_entities()), SyncRepository(connection), page_size=2)
    service.sync()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    result = service.sync()

    assert not any(result.changed_entity_counts.values())
    assert result.scene_ids == ()
    assert not any(statement.startswith("DELETE FROM source_") for statement in statements)
