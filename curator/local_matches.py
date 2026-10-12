"""Local scene ownership facts, independent of recommendation model inputs."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from curator.expand import normalize_phash
from curator.graphql.client import GraphQLClient
from curator.profiling import span
from curator.storage import transaction

FIELDS = "id stash_ids { endpoint stash_id } files { fingerprints { type value } }"
PAGE_QUERY = (
    """query CuratorLocalSceneMatches($page: Int!, $perPage: Int!) {
 findScenes(filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}) {
  count scenes {"""
    + FIELDS
    + """}
 }
}"""
)
IDS_QUERY = (
    """query CuratorLocalSceneMatchesByIds($ids: [ID!]) {
 findScenes(ids: $ids, filter: {per_page: -1}) { scenes {"""
    + FIELDS
    + """} }
}"""
)


def write_scene_match(connection: sqlite3.Connection, scene: Mapping[str, Any]) -> None:
    scene_id = str(scene.get("id") or "")
    if not scene_id:
        raise RuntimeError("local scene match is missing an id")
    ids = {
        item["stash_id"]
        for item in scene.get("stash_ids", [])
        if str(item.get("endpoint") or "").rstrip("/").casefold() == "https://stashdb.org/graphql"
        and item.get("stash_id")
    }
    hashes = {
        value
        for file in scene.get("files", [])
        for item in file.get("fingerprints", [])
        if str(item.get("type") or "").casefold() == "phash"
        and (value := normalize_phash(item.get("value"))) is not None
    }
    for kind, values in (("stashdb_id", ids), ("phash", hashes)):
        wanted = json.dumps(sorted(values), separators=(",", ":"))
        connection.execute(
            "DELETE FROM local_scene_match WHERE scene_id=? AND kind=? "
            "AND value NOT IN (SELECT value FROM json_each(?))",
            (scene_id, kind, wanted),
        )
        connection.execute(
            "INSERT OR IGNORE INTO local_scene_match(scene_id,kind,value) "
            "SELECT ?, ?, value FROM json_each(?)",
            (scene_id, kind, wanted),
        )


def queue_scene_match(connection: sqlite3.Connection, scene_id: str) -> None:
    connection.execute(
        "INSERT INTO local_scene_match_pending(scene_id,revision) VALUES (?,?) "
        "ON CONFLICT(scene_id) DO UPDATE SET revision=excluded.revision",
        (scene_id, str(uuid4())),
    )


def ensure_scene_matches(connection: sqlite3.Connection, payload: Mapping[str, Any]) -> bool:
    if connection.execute(
        "SELECT value FROM application_meta WHERE key='local_scene_matches_ready'"
    ).fetchone():
        return True
    latest = connection.execute(
        "SELECT state, COALESCE(error, ''), started_at_ms FROM curator_job "
        "WHERE job_type='local-matches' ORDER BY started_at_ms DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if latest and latest[0] in {"failed", "cancelled"}:
        raise RuntimeError(
            f"Checking your library failed: {latest[1]}. Retry the Prepare local scene matches task"
        )
    now_ms = time.time_ns() // 1_000_000
    if latest and latest[0] in {"queued", "running"} and latest[2] > now_ms - 6 * 3_600_000:
        return False
    with transaction(connection):
        active = connection.execute(
            "SELECT 1 FROM curator_job WHERE job_type='local-matches' "
            "AND state IN ('queued', 'running') AND started_at_ms>? LIMIT 1",
            (now_ms - 6 * 3_600_000,),
        ).fetchone()
        if not active:
            connection.execute(
                "INSERT INTO curator_job(job_id,job_type,state,started_at_ms,"
                "queued_at_ms,payload_json) "
                "VALUES (?, 'local-matches', 'queued', ?, ?, ?)",
                (str(uuid4()), now_ms, now_ms, json.dumps(dict(payload), separators=(",", ":"))),
            )
    return False


def backfill_scene_matches(
    connection: sqlite3.Connection,
    client: GraphQLClient,
    progress: Callable[[float], None] | None = None,
) -> None:
    if not connection.execute(
        "SELECT value FROM application_meta WHERE key='local_scene_matches_ready'"
    ).fetchone():
        scenes: list[dict[str, Any]] = []
        page = 1
        with span("python", "local_matches.fetch"):
            while True:
                root = client.execute(PAGE_QUERY, {"page": page, "perPage": 1000}).get("findScenes")
                if (
                    not isinstance(root, dict)
                    or not isinstance(root.get("scenes"), list)
                    or not isinstance(root.get("count"), int)
                ):
                    raise RuntimeError("Stash did not return local scene matches")
                if not root["scenes"] and len(scenes) < root["count"]:
                    raise RuntimeError("Stash returned an incomplete local scene match page")
                scenes.extend(root["scenes"])
                if progress:
                    progress(0.05 + 0.65 * min(len(scenes) / max(root["count"], 1), 1))
                if page * 1000 >= root["count"]:
                    if len(scenes) < root["count"]:
                        raise RuntimeError("Stash returned an incomplete local scene match page")
                    break
                page += 1
        with span("python", "local_matches.index"), transaction(connection):
            if not connection.execute(
                "SELECT value FROM application_meta WHERE key='local_scene_matches_ready'"
            ).fetchone():
                connection.execute("DELETE FROM local_scene_match")
                for scene in scenes:
                    write_scene_match(connection, scene)
                connection.execute(
                    "INSERT OR IGNORE INTO application_meta(key,value) "
                    "VALUES ('local_scene_matches_ready','1')"
                )


def scene_links(connection: sqlite3.Connection, client: GraphQLClient) -> dict[str, dict[str, str]]:
    with span("python", "local_matches.load"):
        return _scene_links(connection, client)


def _scene_links(
    connection: sqlite3.Connection, client: GraphQLClient
) -> dict[str, dict[str, str]]:
    backfill_scene_matches(connection, client)
    pending = connection.execute(
        "SELECT scene_id,revision FROM local_scene_match_pending ORDER BY scene_id"
    ).fetchall()
    for start in range(0, len(pending), 200):
        batch = pending[start : start + 200]
        root = client.execute(IDS_QUERY, {"ids": [row[0] for row in batch]}).get("findScenes")
        if not isinstance(root, dict) or not isinstance(root.get("scenes"), list):
            raise RuntimeError("Stash did not return changed local scene matches")
        by_id = {}
        for scene in root["scenes"]:
            scene_id = str(scene.get("id") or "")
            if not scene_id:
                raise RuntimeError("local scene match is missing an id")
            by_id[scene_id] = scene
        with transaction(connection):
            for scene_id, revision in batch:
                current = connection.execute(
                    "SELECT revision FROM local_scene_match_pending WHERE scene_id=?", (scene_id,)
                ).fetchone()
                if not current or current[0] != revision:
                    continue
                if scene_id in by_id:
                    write_scene_match(connection, by_id[scene_id])
                else:
                    connection.execute(
                        "DELETE FROM local_scene_match WHERE scene_id=?", (scene_id,)
                    )
                connection.execute(
                    "DELETE FROM local_scene_match_pending WHERE scene_id=? AND revision=?",
                    (scene_id, revision),
                )
    links: dict[str, dict[str, str]] = {"scene_ids": {}, "scene_phashes": {}}
    for scene_id, kind, value in connection.execute(
        "SELECT scene_id,kind,value FROM local_scene_match "
        "ORDER BY CAST(scene_id AS INTEGER),scene_id,kind,value"
    ):
        links["scene_ids" if kind == "stashdb_id" else "scene_phashes"].setdefault(value, scene_id)
    return links
