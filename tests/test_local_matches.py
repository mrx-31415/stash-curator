from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from curator.graphql.client import GraphQLClient
from curator.local_matches import (
    ensure_scene_matches,
    queue_scene_match,
    scene_links,
    write_scene_match,
)
from curator.storage import MigrationRunner, connect_database, transaction


def test_initialization_queues_once_and_surfaces_failure(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    assert not ensure_scene_matches(connection, {"args": {"operation": "get_expand"}})
    assert not ensure_scene_matches(connection, {"args": {"operation": "get_expand"}})
    assert connection.execute("SELECT count(*) FROM curator_job").fetchone()[0] == 1
    connection.execute("UPDATE curator_job SET state='failed',error='test failure'")
    with pytest.raises(RuntimeError, match="test failure"):
        ensure_scene_matches(connection, {})
    connection.execute(
        "INSERT INTO application_meta(key,value) VALUES ('local_scene_matches_ready','1')"
    )
    assert ensure_scene_matches(connection, {})
    connection.close()


def test_failed_backfill_preserves_index_and_retries(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    with transaction(connection):
        write_scene_match(
            connection,
            {
                "id": "old",
                "stash_ids": [
                    {"endpoint": "https://stashdb.org/graphql", "stash_id": "old-remote"}
                ],
            },
        )
    response: dict[str, Any] = {"findScenes": {"count": 1, "scenes": [{}]}}

    def transport(*args: object) -> bytes:
        return json.dumps({"data": response}).encode()

    client = GraphQLClient("http://fixture", transport=transport)
    with pytest.raises(RuntimeError, match="missing an id"):
        scene_links(connection, client)
    assert connection.execute("SELECT value FROM local_scene_match").fetchone()[0] == "old-remote"
    assert not connection.execute(
        "SELECT value FROM application_meta WHERE key='local_scene_matches_ready'"
    ).fetchone()
    response["findScenes"] = {"count": 2, "scenes": [{"id": "new"}]}
    with pytest.raises(RuntimeError, match="incomplete"):
        scene_links(connection, client)
    assert connection.execute("SELECT value FROM local_scene_match").fetchone()[0] == "old-remote"
    response["findScenes"] = {"count": 0, "scenes": []}
    assert scene_links(connection, client) == {"scene_ids": {}, "scene_phashes": {}}
    connection.close()


def test_failed_targeted_refresh_keeps_queue_and_matching_facts(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    with transaction(connection):
        connection.execute("INSERT INTO application_meta VALUES ('local_scene_matches_ready','1')")
        write_scene_match(
            connection,
            {
                "id": "1",
                "files": [{"fingerprints": [{"type": "phash", "value": "0123456789abcdef"}]}],
            },
        )
        queue_scene_match(connection, "1")

    def transport(*args: object) -> bytes:
        return json.dumps({"data": {"findScenes": None}}).encode()

    with pytest.raises(RuntimeError, match="changed local scene matches"):
        scene_links(connection, GraphQLClient("http://fixture", transport=transport))
    assert connection.execute("SELECT count(*) FROM local_scene_match_pending").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM local_scene_match").fetchone()[0] == 1
    connection.close()
