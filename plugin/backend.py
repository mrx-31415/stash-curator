#!/usr/bin/env python3
"""Stash raw-plugin transport for Curator operations and tasks."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4
from venv import create as create_venv

PLUGIN_DIR = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.resolve()

_code_version_cache: str | None = None


def _installed_code_version() -> str:
    """Hash of the installed backend sources, so frontend caches can bust on update.

    The plugin frontend caches similarity results in the browser session; a
    stale entry can outlive a plugin update because the page may stay open. The
    runtime version is release-please managed and does not move between local
    installs, so stamp the cache key with a content hash of the installed
    python sources instead: any code change changes the hash deterministically.
    """
    global _code_version_cache
    if _code_version_cache is not None:
        return _code_version_cache
    package_roots = {path.resolve() for path in (PLUGIN_DIR, PLUGIN_DIR.parent)}
    files = sorted(
        {
            path.resolve()
            for root in package_roots
            for path in (root / "curator").rglob("*.py")
            if path.is_file()
        }
        | {path.resolve() for path in PLUGIN_DIR.glob("*.py") if path.is_file()}
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.read_bytes())
    _code_version_cache = digest.hexdigest()[:16]
    return _code_version_cache


# Optional dependencies (numpy) installed by the "Install optional dependencies"
# task into a versioned venv kept beside the plugin. The venv lives on the plugin
# volume, so it survives plugin updates and container recreations; the pure-Python
# fallbacks keep every path working when it is absent.
_venv_site_packages = (
    PLUGIN_DIR
    / "venv"
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
if _venv_site_packages.is_dir():
    sys.path.insert(0, str(_venv_site_packages))
for package_root in (PLUGIN_DIR, PLUGIN_DIR.parent):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from curator import __version__  # noqa: E402
from curator.api import CuratorAPI  # noqa: E402
from curator.events import HistoricalEventStore  # noqa: E402
from curator.expand import (  # noqa: E402
    PERFORMER_HUNT_LIMIT,
    STASHDB,
    ExpandService,
    normalize_phash,
)
from curator.graphql import GraphQLClient  # noqa: E402
from curator.model import ModelUpdateCoordinator, RecommendationModelStore  # noqa: E402
from curator.profiling import (  # noqa: E402
    begin_trace,
    clear_traces,
    end_trace,
    get_trace,
    list_traces,
    save_trace,
    span,
)
from curator.ranking import LanePolicy, SlateBuilder  # noqa: E402
from curator.storage import (  # noqa: E402
    MigrationRunner,
    backup_database,
    compact_legacy_generations,
    compaction_status,
    connect_database,
    generation_diagnostics,
    transaction,
)
from curator.sync import SyncService  # noqa: E402
from curator.sync.repository import SyncRepository  # noqa: E402
from curator.whisparr import WhisparrClient  # noqa: E402

SCHEMA_VERSION = 1
RUNTIME_QUERY = """
query CuratorPluginRuntime {
  version { version }
  jobQueue { id status description progress startTime }
  configuration { general { stashBoxes { endpoint api_key } } }
}
"""
SETTINGS_QUERY = """
query CuratorPluginSettings {
  configuration { plugins(include: ["stash-curator"]) }
}
"""
STASHBOX_QUERY = """
query CuratorStashBoxes {
  configuration { general { stashBoxes { endpoint api_key name } } }
}
"""
EXTERNAL_LINKS_QUERY = """
query CuratorExternalLinks($page: Int!, $perPage: Int!) {
  scenes: findScenes(
    scene_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) {
    count
    scenes {
      id stash_ids { endpoint stash_id }
      files { fingerprints { type value } }
    }
  }
  performers: findPerformers(
    performer_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count performers { id stash_ids { endpoint stash_id } } }
  studios: findStudios(
    studio_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count studios { id stash_ids { endpoint stash_id } } }
}
"""
EXTERNAL_LINKS_STATE_QUERY = """
query CuratorExternalLinksState {
  scenes: findScenes(
    scene_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count scenes { updated_at } }
  performers: findPerformers(
    performer_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count performers { updated_at } }
  studios: findStudios(
    studio_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count studios { updated_at } }
}
"""
FIND_PRUNE_TAG = """
query CuratorFindPruneTag($name: String!) {
  findTags(filter: {q: $name, per_page: 20}) { tags { id name } }
}
"""
CREATE_PRUNE_TAG = """
mutation CuratorCreatePruneTag($input: TagCreateInput!) {
  tagCreate(input: $input) { id name }
}
"""
UPDATE_PRUNE_TAG = """
mutation CuratorUpdatePruneTag($input: BulkSceneUpdateInput!) {
  bulkSceneUpdate(input: $input) { id }
}
"""


def _log(level: str, message: str) -> None:
    print(f"\x01{level}\x02{message}", file=sys.stderr, flush=True)


def _progress(value: float) -> None:
    _log("p", f"{max(0.0, min(value, 1.0)):.4f}")


def _mapped_progress(start: float, end: float) -> Callable[[int, int], None]:
    return lambda processed, total: _progress(
        start + (end - start) * min(processed / max(1, total), 1.0)
    )


def _stash_connection(payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
    server = payload.get("server_connection") or {}
    host = server.get("Host") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    scheme = server.get("Scheme") or "http"
    port = int(server.get("Port") or 9999)
    headers: dict[str, str] = {}
    cookie = server.get("SessionCookie") or {}
    if cookie.get("Name") and cookie.get("Value"):
        headers["Cookie"] = f"{cookie['Name']}={cookie['Value']}"
    return f"{scheme}://{host}:{port}", headers


def _client(payload: dict[str, Any]) -> GraphQLClient:
    stash_url, headers = _stash_connection(payload)
    return GraphQLClient(stash_url, headers=headers)


def _stashdb(payload: dict[str, Any]) -> GraphQLClient:
    boxes = _client(payload).execute(STASHBOX_QUERY)["configuration"]["general"]["stashBoxes"]
    box = next(
        (
            item
            for item in boxes
            if str(item.get("endpoint") or "").rstrip("/").casefold()
            == STASHDB.rstrip("/").casefold()
        ),
        None,
    )
    if box is None or not box.get("api_key"):
        raise RuntimeError("configure StashDB with an API key in Stash settings")
    return GraphQLClient(
        str(box["endpoint"]), api_key=str(box["api_key"]), profile_category="stashdb"
    )


EXTERNAL_LINKS_CACHE_KEY = "external_links"


def _external_links_state(payload: dict[str, Any]) -> str:
    """Cheap description of the linked library, so the full scan can be skipped."""
    data = _client(payload).execute(EXTERNAL_LINKS_STATE_QUERY)
    return json.dumps(
        {
            kind: [
                int(data[kind]["count"]),
                str((data[kind][kind][:1] or [{}])[0].get("updated_at") or ""),
            ]
            for kind in ("scenes", "performers", "studios")
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _cached_external_links(
    connection: sqlite3.Connection, state: str
) -> dict[str, dict[str, str]] | None:
    row = connection.execute(
        "SELECT value FROM application_meta WHERE key=?", (EXTERNAL_LINKS_CACHE_KEY,)
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    if payload.get("state") != state:
        return None
    links = payload.get("links")
    return links if isinstance(links, dict) else None


def _external_links(
    payload: dict[str, Any],
    connection: sqlite3.Connection | None = None,
    *,
    refresh: bool = False,
) -> dict[str, dict[str, str]]:
    """Map local entities to their StashDB ids, reusing the last scan while Stash is unchanged.

    Rebuilding this walks every linked scene for its fingerprints, which dominates the cost of
    the operations that need it, so it is kept until Stash reports a different library.
    """
    state = _external_links_state(payload) if connection is not None else ""
    if connection is not None and not refresh:
        cached = _cached_external_links(connection, state)
        if cached is not None:
            return cached
    result: dict[str, dict[str, str]] = {
        "scenes": {},
        "scene_ids": {},
        "scene_phashes": {},
        "performers": {},
        "studios": {},
    }
    page = 1
    while True:
        data = _client(payload).execute(EXTERNAL_LINKS_QUERY, {"page": page, "perPage": 500})
        more = False
        for kind in ("scenes", "performers", "studios"):
            collection = data[kind]
            for row in collection[kind]:
                external = next(
                    (
                        str(item["stash_id"])
                        for item in row.get("stash_ids", [])
                        if str(item.get("endpoint") or "").rstrip("/").casefold()
                        == STASHDB.rstrip("/").casefold()
                    ),
                    None,
                )
                if external:
                    result[kind][str(row["id"])] = external
                    if kind == "scenes":
                        result["scene_ids"][external] = str(row["id"])
                if kind == "scenes":
                    for file in row.get("files", []):
                        for fingerprint in file.get("fingerprints", []):
                            if str(fingerprint.get("type") or "").casefold() == "phash":
                                value = normalize_phash(fingerprint.get("value"))
                                if value:
                                    result["scene_phashes"].setdefault(value, str(row["id"]))
            more |= page * 500 < int(collection["count"])
        if not more:
            break
        page += 1
    if connection is not None:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    EXTERNAL_LINKS_CACHE_KEY,
                    json.dumps({"state": state, "links": result}, separators=(",", ":")),
                ),
            )
    return result


def _settings(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _client(payload).execute(SETTINGS_QUERY)
        configuration = result.get("configuration") or {}
        plugins = configuration.get("plugins") or {}
        settings = plugins.get("stash-curator") or {}
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("filter values must be a list of at most 50 strings")
    if not all(isinstance(item, str) and len(item) <= 100 for item in value):
        raise ValueError("filter values must be strings up to 100 characters")
    return tuple(value)


def _database_path(payload: dict[str, Any], settings: dict[str, Any] | None = None) -> Path:
    configured = str((payload.get("args") or {}).get("database_path") or "").strip()
    if not configured:
        configured = str((settings or {}).get("databasePath") or "").strip()
    return Path(configured).expanduser() if configured else PLUGIN_DIR / "data" / "curator.sqlite3"


BACKUP_NAME = re.compile(r"curator-(?:before-restore-)?(?P<created>\d+)\.sqlite3\.backup")


def _backup_directory(payload: dict[str, Any], settings: dict[str, Any]) -> Path:
    configured = str(settings.get("backupPath") or "").strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else _database_path(payload, settings).expanduser().resolve().parent
    )


def _list_backups(payload: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, object]]:
    directory = _backup_directory(payload, settings)
    if not directory.is_dir():
        return []
    items = []
    for path in directory.iterdir():
        match = BACKUP_NAME.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            items.append(
                {
                    "id": path.name,
                    "created_at_ms": int(match.group("created")),
                    "size_bytes": path.stat().st_size,
                    "path": str(path.resolve()),
                }
            )
    return sorted(items, key=lambda item: int(str(item["created_at_ms"])), reverse=True)


def _validate_backup(path: Path) -> None:
    connection = connect_database(path, readonly=True, attach_artifacts=False)
    try:
        if str(connection.execute("PRAGMA quick_check").fetchone()[0]) != "ok":
            raise ValueError("backup failed SQLite integrity validation")
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        ).fetchone():
            raise ValueError("backup is not a Curator database")
        MigrationRunner(connection).status()
    except Exception as error:
        raise ValueError(f"incompatible Curator backup: {error}") from error
    finally:
        connection.close()


def _backup_control(
    payload: dict[str, Any], operation: str, settings: dict[str, Any]
) -> dict[str, object]:
    args = payload.get("args") or {}
    database = _database_path(payload, settings).expanduser().resolve()
    directory = _backup_directory(payload, settings)
    if operation == "list_backups":
        return {
            "schema_version": SCHEMA_VERSION,
            "backup_directory": str(directory),
            "items": _list_backups(payload, settings),
        }
    connection = _open(payload, settings)
    try:
        if connection.execute("SELECT 1 FROM curator_job WHERE state='running' LIMIT 1").fetchone():
            raise RuntimeError("cannot change backups while a Curator job is running")
        now_ms = time.time_ns() // 1_000_000
        if operation == "create_backup":
            backup = backup_database(
                connection,
                directory / f"curator-{now_ms}.sqlite3.backup",
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "backup_path": str(backup),
                "items": _list_backups(payload, settings),
            }
        backup_id = str(args.get("backup_id") or "")
        match = BACKUP_NAME.fullmatch(backup_id)
        backup = directory / backup_id
        if (
            not match
            or backup.parent.resolve() != directory
            or not backup.is_file()
            or backup.is_symlink()
        ):
            raise ValueError("select a recognized Curator backup")
        if operation == "delete_backup":
            if str(args.get("confirmation") or "") != f"DELETE {backup_id}":
                raise ValueError("deletion requires explicit confirmation")
            _validate_backup(backup)
            backup.unlink()
            return {
                "schema_version": SCHEMA_VERSION,
                "deleted": backup_id,
                "items": _list_backups(payload, settings),
            }
        if str(args.get("confirmation") or "") != f"RESTORE {backup_id}":
            raise ValueError("restore requires explicit confirmation")
        _validate_backup(backup)
        safety = backup_database(
            connection,
            directory / f"curator-before-restore-{now_ms}.sqlite3.backup",
        )
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    source = connect_database(backup, readonly=True, attach_artifacts=False)
    try:
        backup_database(source, database, overwrite=True)
    finally:
        source.close()
    restored = connect_database(database, attach_artifacts=False)
    try:
        MigrationRunner(restored).migrate(applied_at_ms=now_ms)
        with transaction(restored):
            restored.execute(
                """
                UPDATE model_version SET status='superseded',
                    validation_status='restore_invalidated'
                WHERE status='published'
                """
            )
            restored.execute(
                """
                UPDATE feature_build SET status='superseded',
                    validation_status='restore_invalidated'
                WHERE status='published'
                """
            )
            restored.execute("DELETE FROM application_meta WHERE key='current_model_id'")
    finally:
        restored.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "restored_from": str(backup.resolve()),
        "safety_backup": str(safety),
        "recommendations_need_rebuilding": True,
    }


def _apply_plugin_settings(connection: Any, settings: dict[str, Any]) -> None:
    mapping = {
        "pageSize": ("page_size", int),
        "syncPageSize": ("sync_page_size", int),
        "modelUpdateEventThreshold": ("model_update_event_threshold", int),
        "modelUpdateMaxWaitMinutes": ("model_update_max_wait_minutes", float),
        "modelUpdateMinIntervalMinutes": ("model_update_min_interval_minutes", float),
        "pruneTagName": ("prune_tag_name", str),
        "expandHorizonDays": ("expand_horizon_days", int),
        "expandGender": ("expand_gender", str),
        "expandWildcard": ("expand_wildcard", bool),
    }
    overrides = {
        key: convert(settings[source])
        for source, (key, convert) in mapping.items()
        if settings.get(source) not in (None, "")
    }
    if "diversityDisabled" in settings:
        overrides["diversity_enabled"] = not bool(settings["diversityDisabled"])
    if not overrides:
        return
    row = connection.execute("SELECT config_json FROM curator_config WHERE singleton=1").fetchone()
    current = json.loads(str(row[0]))
    merged = {**current, **overrides}
    effective = CuratorAPI(connection).config()["config"]
    assert isinstance(effective, dict)
    CuratorAPI._validate_config({**effective, **overrides})
    if merged == current:
        return
    with transaction(connection):
        connection.execute(
            "UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1",
            (
                json.dumps(merged, sort_keys=True, separators=(",", ":")),
                time.time_ns() // 1_000_000,
            ),
        )


def _open(  # type: ignore[no-untyped-def]
    payload: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    attach_artifacts: bool = True,
):
    connection = connect_database(
        _database_path(payload, settings), attach_artifacts=attach_artifacts
    )
    MigrationRunner(connection).migrate(applied_at_ms=time.time_ns() // 1_000_000)
    _apply_plugin_settings(connection, settings or {})
    return connection


def _health(payload: dict[str, Any]) -> dict[str, object]:
    settings = _settings(payload)
    stash = _client(payload).execute(RUNTIME_QUERY)
    task_names = {
        "Sync and build recommendations",
        "Full sync and build recommendations",
        "Rebuild recommendation model",
        "Apply recent Curator feedback",
        "Prepare recommendation pages",
        "Backup Curator data",
        "Compact legacy Curator data",
        "Vacuum compacted Curator data",
        "Refresh Expand cache",
        "Install optional dependencies",
    }
    active_jobs = [
        job
        for job in (stash.get("jobQueue") or [])
        if any(name in str(job.get("description") or "") for name in task_names)
        and str(job.get("status") or "").casefold() in {"waiting", "running"}
    ]
    active_job = active_jobs[0] if active_jobs else None
    connection = _open(payload, settings)
    try:
        now_ms = time.time_ns() // 1_000_000
        if active_job is None:
            interrupted = connection.execute(
                "SELECT 1 FROM curator_job WHERE state='running' AND started_at_ms<? LIMIT 1",
                (now_ms - 120_000,),
            ).fetchone()
            if interrupted:
                with transaction(connection):
                    connection.execute(
                        """
                    UPDATE curator_job SET state='failed', finished_at_ms=?,
                        error='interrupted before task completion'
                    WHERE state='running' AND started_at_ms<?
                    """,
                        (now_ms, now_ms - 120_000),
                    )
        migration = MigrationRunner(connection).status()
        current = connection.execute(
            "SELECT model_id FROM model_version WHERE status='published'"
        ).fetchone()
        config = CuratorAPI(connection).config()["config"]
        assert isinstance(config, dict)
        last_sync = connection.execute(
            """
            SELECT finished_at_ms FROM curator_job
            WHERE job_type IN ('sync-build', 'full-sync-build') AND state='complete'
            ORDER BY finished_at_ms DESC LIMIT 1
            """
        ).fetchone()
        model_rebuilding = connection.execute(
            """
            SELECT 1 FROM curator_job
            WHERE state='running' AND started_at_ms>? AND job_type IN (
                'build', 'update-model', 'sync-build', 'full-sync-build'
            ) LIMIT 1
            """,
            (time.time_ns() // 1_000_000 - 6 * 3_600_000,),
        ).fetchone()
        model_update = ModelUpdateCoordinator(
            connection, debounce_ms=int(config["debounce_ms"])
        ).status()
        model_update_ready = model_update.ready(
            now_ms,
            event_threshold=int(config["model_update_event_threshold"]),
            max_wait_ms=round(float(config["model_update_max_wait_minutes"]) * 60_000),
            min_interval_ms=round(float(config["model_update_min_interval_minutes"]) * 60_000),
        )
        capture = {
            "direct_playback_sessions": connection.execute(
                "SELECT count(*) FROM play_session WHERE provenance='direct_player'"
            ).fetchone()[0],
            "direct_behavior_events": connection.execute(
                "SELECT count(*) FROM behavior_event WHERE provenance='direct_player'"
            ).fetchone()[0],
            "qualified_impressions": connection.execute(
                "SELECT count(*) FROM impression_item WHERE qualified_at_ms IS NOT NULL"
            ).fetchone()[0],
            "last_playback_at_ms": connection.execute(
                "SELECT max(ended_at_ms) FROM play_session WHERE provenance='direct_player'"
            ).fetchone()[0],
        }
    finally:
        connection.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "curator_version": __version__,
        "stash_version": stash["version"]["version"],
        "database": str(_database_path(payload, settings)),
        "database_schema": migration.current_version,
        "database_schema_latest": migration.latest_version,
        "sidecar_ready": not migration.pending_versions,
        "model_id": str(current[0]) if current else None,
        "ready": current is not None,
        "sync_ready": last_sync is not None,
        "stashdb_available": any(
            str(box.get("endpoint") or "").rstrip("/").casefold() == STASHDB.rstrip("/").casefold()
            and bool(box.get("api_key"))
            for box in stash["configuration"]["general"]["stashBoxes"]
        ),
        "capture": capture,
        "model_pending": model_update.pending,
        "model_pending_events": model_update.pending_count,
        "model_update_ready": model_update_ready,
        "model_rebuilding": model_rebuilding is not None and active_job is not None,
        "active_job": active_job,
        "active_jobs": active_jobs,
        "last_sync_at_ms": int(last_sync[0]) if last_sync else None,
    }


def _round_trip(payload: dict[str, Any]) -> dict[str, object]:
    connection = _open(payload)
    try:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES ('plugin_round_trips', '1')
                ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1
                """
            )
        count = int(
            connection.execute(
                "SELECT value FROM application_meta WHERE key='plugin_round_trips'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "round_trips": count,
        "synthetic_slate": [{"scene_id": "runtime-proof", "lane": "for_you", "position": 0}],
    }


def _api(payload: dict[str, Any], operation: str, settings: dict[str, Any]) -> dict[str, object]:
    connection = _open(payload, settings)
    args = payload.get("args") or {}
    try:
        api = CuratorAPI(connection)
        if operation == "get_slate":
            config = api.config()["config"]
            excluded = args.get("exclude_scene_ids", [])
            if not isinstance(excluded, list):
                raise ValueError("exclude_scene_ids must be a list")
            count = int(
                args.get("count")
                or (config.get("page_size", 20) if isinstance(config, dict) else 20)
            )
            return api.get_slate(
                str(args.get("lane") or "for_you"),
                count,
                page=int(args.get("page") or 1),
                impression_id=str(args["impression_id"]) if args.get("impression_id") else None,
                context=args.get("context") if isinstance(args.get("context"), dict) else None,
                exclude_scene_ids={str(value) for value in excluded},
                exploration=float(args.get("exploration") or 0),
            )
        if operation == "replace_item":
            excluded = args.get("exclude_scene_ids")
            if not isinstance(excluded, list):
                raise ValueError("exclude_scene_ids must be a list")
            return api.get_slate(
                str(args.get("lane") or "for_you"),
                1,
                context={"replacement": True},
                exclude_scene_ids={str(value) for value in excluded},
                exploration=float(args.get("exploration") or 0),
            )
        if operation == "get_explanation":
            return api.explanation(str(args.get("scene_id") or ""))
        if operation == "get_recommendation_history":
            return api.recommendation_history(
                int(args.get("page") or 1),
                int(args.get("page_size") or 20),
                lane=str(args["lane"]) if args.get("lane") else None,
            )
        if operation == "get_expand":
            config = api.config()["config"]
            assert isinstance(config, dict)
            return api.expand(
                str(args.get("entity_type") or "scene"),
                page=int(args.get("page") or 1),
                sort=str(args.get("sort") or "match"),
                performer_id=str(args["performer_id"]) if args.get("performer_id") else None,
                favorite_only=bool(args.get("favorite_only")),
                gender=str(args.get("gender", config["expand_gender"])),
                include_tags=_string_list(args.get("include_tags")),
                exclude_tags=_string_list(args.get("exclude_tags")),
                performer_query=str(args.get("performer_query") or ""),
                studio_query=str(args.get("studio_query") or ""),
                performer_names=_string_list(args.get("performer_names")),
                studio_names=_string_list(args.get("studio_names")),
                hide_phash_matches=bool(args.get("hide_phash_matches", True)),
                minimum_score=(
                    float(args["minimum_score"]) if args.get("minimum_score") is not None else -1
                ),
                count=int(args.get("count") or config["page_size"]),
            )
        if operation == "get_performer_hunt":
            return ExpandService(connection).performer_hunt(
                _stashdb(payload),
                _external_links(payload, connection),
                str(args.get("performer_id") or ""),
                limit=PERFORMER_HUNT_LIMIT,
                include_tags=_string_list(args.get("include_tags")),
                exclude_tags=_string_list(args.get("exclude_tags")),
            )
        if operation == "get_shortlist":
            config = api.config()["config"]
            assert isinstance(config, dict)
            return api.expand_shortlist(
                page=int(args.get("page") or 1),
                page_size=int(args.get("page_size") or config["page_size"]),
            )
        if operation == "get_external_similar":
            config = api.config()["config"]
            assert isinstance(config, dict)
            return ExpandService(connection).targeted_similar(
                _stashdb(payload),
                _external_links(payload, connection),
                str(args.get("entity_type") or ""),
                str(args.get("entity_id") or ""),
                count=100,
                gender=str(args.get("gender", config["expand_gender"])),
                include_tags=_string_list(args.get("include_tags")),
                exclude_tags=_string_list(args.get("exclude_tags")),
                performer_names=_string_list(args.get("performer_names")),
                studio_names=_string_list(args.get("studio_names")),
                favorite_only=bool(args.get("favorite_only", False)),
                include_owned=bool(args.get("include_owned", False)),
                hide_phash_matches=bool(args.get("hide_phash_matches", True)),
                minimum_similarity=(
                    float(args["minimum_similarity"])
                    if args.get("minimum_similarity") is not None
                    else 0.15
                ),
            )
        if operation == "update_shortlist":
            entity_type = str(args.get("entity_type") or "")
            external_id = str(args.get("external_id") or "")
            selected = bool(args.get("selected"))
            api.update_shortlist(entity_type, external_id, selected)
            return {
                "schema_version": SCHEMA_VERSION,
                "entity_type": entity_type,
                "external_id": external_id,
                "selected": selected,
            }
        if operation == "send_whisparr":
            external_id = str(args.get("external_id") or "")
            row = connection.execute(
                """
                SELECT payload_json FROM external_shortlist
                WHERE entity_type='scene' AND external_id=?
                UNION ALL
                SELECT payload_json FROM external_entity
                WHERE entity_type='scene' AND external_id=? LIMIT 1
                """,
                (external_id, external_id),
            ).fetchone()
            if row is None:
                raise ValueError("scene is not in Expand")
            payload_json = json.loads(str(row[0]))
            url = str(settings.get("whisparrUrl") or "").strip()
            key = str(settings.get("whisparrApiKey") or "").strip()
            root = str(settings.get("whisparrRootFolder") or "").strip()
            profile = int(settings.get("whisparrQualityProfileId") or 0)
            return WhisparrClient(url, key).send_scene(
                external_id,
                str(payload_json.get("title") or "Added by Stash Curator"),
                root,
                profile,
                search=bool(settings.get("whisparrSearchImmediately", True)),
            )
        if operation == "submit_feedback":
            entries = args.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            return api.submit_feedback(entries)
        if operation == "get_feedback_history":
            return api.feedback_history(
                int(args.get("page") or 1),
                int(args.get("page_size") or 20),
            )
        if operation == "correct_feedback":
            return api.correct_feedback(
                str(args.get("feedback_id") or ""),
                str(args.get("correction_id") or ""),
                str(args["feedback_type"]) if args.get("feedback_type") else None,
            )
        if operation == "submit_tag_preferences":
            entries = args.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            return api.submit_tag_preferences(entries)
        if operation == "get_taste_profile":
            return api.taste_profile()
        if operation == "get_tag_sentiment_follow_up":
            return api.tag_sentiment_follow_up(
                str(args.get("scene_id") or ""),
                min(3, int(args.get("limit") or 3)),
            )
        if operation == "get_external_tag_choices":
            tags = args.get("tags")
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            return api.external_tag_choices(tags)
        if operation == "submit_events":
            entries = args.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            return api.submit_events(entries)
        if operation == "get_pruning_queue":
            return api.pruning_queue()
        if operation == "get_prune_candidates":
            config = api.config()["config"]
            assert isinstance(config, dict)
            return api.prune_candidates(
                str(args.get("view") or "candidates"),
                aggressiveness=float(args.get("aggressiveness") or 0),
                page=int(args.get("page") or 1),
                page_size=int(args.get("page_size") or 20),
                tag_name=str(config["prune_tag_name"]),
            )
        if operation == "dismiss_prune_candidate":
            scene_id = str(args.get("scene_id") or "")
            api.dismiss_prune_candidate(scene_id)
            return {"schema_version": SCHEMA_VERSION, "scene_id": scene_id, "dismissed": True}
        if operation == "set_prune_tag":
            scene_ids = args.get("scene_ids")
            if not isinstance(scene_ids, list) or not 1 <= len(scene_ids) <= 100:
                raise ValueError("scene_ids must contain 1 to 100 scenes")
            scene_ids = list(dict.fromkeys(str(value) for value in scene_ids))
            config = api.config()["config"]
            assert isinstance(config, dict)
            tag_name = str(config["prune_tag_name"])
            client = _client(payload)
            found = client.execute(FIND_PRUNE_TAG, {"name": tag_name})["findTags"]["tags"]
            tag = next(
                (
                    item
                    for item in found
                    if str(item.get("name", "")).casefold() == tag_name.casefold()
                ),
                None,
            )
            if tag is None:
                tag = client.mutate(CREATE_PRUNE_TAG, {"input": {"name": tag_name}})["tagCreate"]
            tagged = bool(args.get("tagged"))
            client.mutate(
                UPDATE_PRUNE_TAG,
                {
                    "input": {
                        "ids": scene_ids,
                        "tag_ids": {
                            "ids": [str(tag["id"])],
                            "mode": "ADD" if tagged else "REMOVE",
                        },
                    }
                },
            )
            api.record_prune_tags(scene_ids, tagged, str(tag["id"]), tag_name)
            return {
                "schema_version": SCHEMA_VERSION,
                "scene_ids": scene_ids,
                "tagged": tagged,
                "tag_id": str(tag["id"]),
                "tag_name": tag_name,
            }
        if operation == "update_pruning":
            return api.update_pruning(str(args.get("scene_id") or ""), str(args.get("state") or ""))
        if operation == "get_exclusions":
            return api.exclusions()
        if operation == "reverse_exclusion":
            return api.reverse_exclusion(str(args.get("scene_id") or ""))
        if operation == "get_config":
            result = api.config()
            result["code_version"] = _installed_code_version()
            result["whisparr_enabled"] = bool(
                str(settings.get("whisparrUrl") or "").strip()
                and str(settings.get("whisparrApiKey") or "").strip()
            )
            return result
        if operation == "update_config":
            values = args.get("values")
            if not isinstance(values, dict):
                raise ValueError("values must be an object")
            return api.update_config(values)
        if operation == "get_job_status":
            return _job_status(connection)
        if operation == "get_diagnostics":
            return _diagnostics(connection)
        if operation == "list_profiles":
            return {
                "schema_version": SCHEMA_VERSION,
                "enabled": bool(settings.get("profilingEnabled", False)),
                "items": list_traces(connection, int(args.get("limit") or 50)),
            }
        if operation == "get_profile":
            return {
                "schema_version": SCHEMA_VERSION,
                **get_trace(connection, str(args.get("trace_id") or "")),
            }
        if operation == "clear_profiles":
            if str(args.get("confirmation") or "") != "CLEAR":
                raise ValueError("clearing profiles requires confirmation")
            return {
                "schema_version": SCHEMA_VERSION,
                "deleted": clear_traces(connection),
            }
        if operation == "get_inspector_entity":
            return api.inspector(
                str(args.get("entity_type") or ""), str(args.get("entity_id") or "")
            )
        if operation == "get_similar":
            config = api.config()["config"]
            assert isinstance(config, dict)
            excluded = args.get("exclude_scene_ids", [])
            if not isinstance(excluded, list):
                raise ValueError("exclude_scene_ids must be a list")
            return api.similar(
                str(args.get("entity_type") or ""),
                str(args.get("entity_id") or ""),
                int(args.get("count") or config["page_size"]),
                page=int(args.get("page") or 1),
                impression_id=(str(args["impression_id"]) if args.get("impression_id") else None),
                gender=str(args.get("gender") or ""),
                include_tags=_string_list(args.get("include_tags")),
                exclude_tags=_string_list(args.get("exclude_tags")),
                performer_ids=_string_list(args.get("performer_ids")),
                studio_ids=_string_list(args.get("studio_ids")),
                favorite_only=bool(args.get("favorite_only", False)),
                minimum_similarity=(
                    float(args["minimum_similarity"])
                    if args.get("minimum_similarity") is not None
                    else 0.18
                ),
                exclude_scene_ids={str(value) for value in excluded},
            )
        raise ValueError(f"unknown Curator API operation: {operation}")
    finally:
        connection.close()


def _job_status(connection: Any) -> dict[str, object]:
    rows = connection.execute("SELECT * FROM curator_job ORDER BY started_at_ms DESC LIMIT 10")
    jobs = [
        {
            "job_id": str(row["job_id"]),
            "job_type": str(row["job_type"]),
            "state": str(row["state"]),
            "started_at_ms": int(row["started_at_ms"]),
            "finished_at_ms": int(row["finished_at_ms"]) if row["finished_at_ms"] else None,
            "summary": json.loads(row["summary_json"]),
            "error": str(row["error"]) if row["error"] else None,
        }
        for row in rows
    ]
    return {"schema_version": SCHEMA_VERSION, "jobs": jobs}


DIAGNOSTIC_JOB_TYPES = {
    "sync-build",
    "full-sync-build",
    "build",
    "update-model",
    "prepare",
    "backup",
    "compact",
    "vacuum",
    "expand-refresh",
}


def _diagnostics(connection: Any) -> dict[str, object]:
    migration = MigrationRunner(connection).status()
    model = connection.execute(
        "SELECT 1 FROM model_version WHERE status='published' LIMIT 1"
    ).fetchone()
    sync = connection.execute(
        """
        SELECT 1 FROM curator_job
        WHERE job_type IN ('sync-build', 'full-sync-build') AND state='complete' LIMIT 1
        """
    ).fetchone()
    model_update = connection.execute(
        """
        SELECT requested_generation, published_generation, last_duration_ms
        FROM model_update_state WHERE singleton=1
        """
    ).fetchone()
    rows = [
        row
        for row in connection.execute(
            """
            SELECT job_type, state, started_at_ms, finished_at_ms
            FROM curator_job ORDER BY started_at_ms DESC LIMIT 50
            """
        )
        if str(row["job_type"]) in DIAGNOSTIC_JOB_TYPES
    ]
    recent_jobs = [
        {
            "job_type": str(row["job_type"]),
            "outcome": str(row["state"]),
            "started_at_ms": int(row["started_at_ms"]),
            "finished_at_ms": (
                int(row["finished_at_ms"]) if row["finished_at_ms"] is not None else None
            ),
            "duration_ms": (
                int(row["finished_at_ms"]) - int(row["started_at_ms"])
                if row["finished_at_ms"] is not None
                else None
            ),
        }
        for row in rows[:10]
    ]
    durations: dict[str, list[int]] = {}
    for row in rows:
        if row["finished_at_ms"] is not None:
            durations.setdefault(str(row["job_type"]), []).append(
                int(row["finished_at_ms"]) - int(row["started_at_ms"])
            )
    return {
        "report_version": 1,
        "generated_at_ms": time.time_ns() // 1_000_000,
        "curator_version": __version__,
        "api_schema_version": SCHEMA_VERSION,
        "migration": {
            "current_version": migration.current_version,
            "latest_version": migration.latest_version,
            "pending_count": len(migration.pending_versions),
        },
        "readiness": {
            "sidecar": not migration.pending_versions,
            "library_sync": sync is not None,
            "recommendation_model": model is not None,
            "model_update_pending": (
                int(model_update["requested_generation"])
                > int(model_update["published_generation"])
            ),
        },
        "generations": generation_diagnostics(connection),
        "compaction": compaction_status(connection),
        "recent_jobs": recent_jobs,
        "timing_ms": {
            "last_model_update": (
                int(model_update["last_duration_ms"])
                if model_update["last_duration_ms"] is not None
                else None
            ),
            "jobs": [
                {
                    "job_type": job_type,
                    "count": len(values),
                    "average": round(sum(values) / len(values)),
                    "maximum": max(values),
                }
                for job_type, values in sorted(durations.items())
            ],
        },
    }


def _classify_lanes(
    connection: Any,
    model_id: str,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    count = int(
        connection.execute(
            "SELECT count(*) FROM model_scene_lane WHERE model_id=?", (model_id,)
        ).fetchone()[0]
    )
    if count:
        if progress:
            progress(1, 1)
        return count
    return len(LanePolicy(connection).classify(model_id, progress=progress))


def _prepare_lanes(
    connection: Any,
    model_id: str,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    return SlateBuilder(connection).materialize(model_id, progress=progress)


def _run_task_body(
    payload: dict[str, Any], mode: str, settings: dict[str, Any]
) -> dict[str, object]:
    connection = _open(payload, settings)
    job_id = str(uuid4())
    started_at_ms = time.time_ns() // 1_000_000
    stale_before = time.time_ns() // 1_000_000 - 6 * 3_600_000
    with transaction(connection):
        connection.execute(
            """
            UPDATE curator_job SET state='failed', finished_at_ms=?, error='interrupted'
            WHERE state='running' AND started_at_ms<=?
            """,
            (time.time_ns() // 1_000_000, stale_before),
        )
        existing = connection.execute(
            """
            SELECT job_id, job_type FROM curator_job WHERE state='running'
            AND started_at_ms>? ORDER BY started_at_ms DESC LIMIT 1
            """,
            (stale_before,),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                UPDATE model_update_state SET last_error='interrupted before task completion'
                WHERE last_started_at_ms IS NOT NULL
                AND last_started_at_ms>COALESCE(last_finished_at_ms, -1)
                AND last_error IS NULL
                """
            )
            connection.execute(
                """
                INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
                VALUES (?, ?, 'running', ?)
                """,
                (job_id, mode, started_at_ms),
            )
    if existing is not None:
        connection.close()
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": str(existing["job_id"]),
            "already_running": True,
            "job_type": str(existing["job_type"]),
        }
    if mode in {"compact", "vacuum"}:
        connection.close()
        connection = _open(payload, settings, attach_artifacts=False)
    _log("i", f"Stash Curator {mode} started")
    _progress(0.01)
    try:
        if mode in {"sync-build", "full-sync-build"}:
            sidecar_config = CuratorAPI(connection).config()["config"]
            assert isinstance(sidecar_config, dict)
            logged_milestones: dict[str, int] = {}

            def report_sync(
                entity: str, processed: int, total: int, position: int, entity_count: int
            ) -> None:
                fraction = 1.0 if total == 0 else min(processed / total, 1.0)
                _progress(0.03 + 0.52 * ((position + fraction) / entity_count))
                milestone = int(fraction * 10)
                if milestone > logged_milestones.get(entity, -1):
                    logged_milestones[entity] = milestone
                    _log("i", f"Synchronizing {entity}s: {processed}/{total}")

            _log("i", "Synchronizing Stash metadata")
            with span("python", "task.sync"):
                synced = SyncService(
                    _client(payload),
                    SyncRepository(connection),
                    page_size=int(sidecar_config["sync_page_size"]),
                    progress=report_sync,
                ).sync(full=mode == "full-sync-build")
            with span("python", "task.reconcile_prune"):
                prune_changed = CuratorAPI(connection).reconcile_prune_tag(
                    str(sidecar_config["prune_tag_name"])
                )
            _progress(0.58)
            _log("i", "Rebuilding historical preference signals")
            with span("python", "task.historical_events"):
                historical = HistoricalEventStore(connection).rebuild(
                    None if mode == "full-sync-build" or synced.resumed else synced.scene_ids,
                    progress=_mapped_progress(0.58, 0.68),
                )
            _progress(0.68)
            coordinator = ModelUpdateCoordinator(connection)
            for entity, removed in sorted(synced.deleted_entity_counts.items()):
                _log("i", f"Removed {removed} {entity}s deleted from Stash")
            source_changed = (
                mode == "full-sync-build"
                or synced.resumed
                or any(synced.changed_entity_counts.values())
                or any(synced.deleted_entity_counts.values())
                or prune_changed
            )
            current_model_id = RecommendationModelStore(connection).current_model_id()
            if source_changed or current_model_id is None:
                coordinator.request("source_sync")
            if source_changed or coordinator.status().pending or current_model_id is None:
                _log("i", "Building the recommendation model")
                with span("python", "task.model_build"):
                    model = coordinator.drain(
                        force=True,
                        max_builds=1,
                        progress=_mapped_progress(0.68, 0.95),
                    )[0]
                model_id = model.model_id
                stage_timings_ms = model.stage_timings_ms
            else:
                _progress(0.95)
                _log("i", "No Stash changes; keeping the current recommendation model")
                model_id = current_model_id
                stage_timings_ms = {}
            _progress(0.95)
            _log("i", "Organizing scenes into recommendation lanes")
            with span("python", "task.lane_classification"):
                lane_count = _classify_lanes(
                    connection,
                    model_id,
                    progress=_mapped_progress(0.95, 0.97),
                )
            _progress(0.97)
            _log("i", "Preparing recommendation pages")
            with span("python", "task.prepare_pages"):
                lane_caches = _prepare_lanes(
                    connection, model_id, progress=_mapped_progress(0.97, 0.99)
                )
            _progress(0.99)
            _log("i", f"Recommendation model ready: {model_id}")
            summary: dict[str, object] = {
                "sync_run_id": synced.run_id,
                "entity_counts": synced.entity_counts,
                "changed_entity_counts": synced.changed_entity_counts,
                "historical_scenes": historical.scene_count,
                "model_id": model_id,
                "lane_classifications": lane_count,
                "lane_candidate_caches": lane_caches,
                "stage_timings_ms": stage_timings_ms,
            }
        elif mode in {"build", "update-model"}:
            _progress(0.1)
            _log("i", "Building the recommendation model")
            model_milestone = -1

            def report_model(processed: int, total: int) -> None:
                nonlocal model_milestone
                fraction = 1.0 if total == 0 else min(processed / total, 1.0)
                _progress(0.03 + 0.92 * fraction)
                milestone = int(fraction * 10)
                if milestone > model_milestone:
                    model_milestone = milestone
                    _log("i", f"Building recommendation model: {milestone * 10}%")

            coordinator = ModelUpdateCoordinator(connection)
            if mode == "build":
                coordinator.request("manual_build")
            with span("python", "task.model_build"):
                models = coordinator.drain(force=True, max_builds=1, progress=report_model)
            if not models:
                summary = {"updated": False}
                _progress(0.98)
                _log("i", "No pending preference changes")
            else:
                model = models[-1]
                _progress(0.95)
                _log("i", "Organizing scenes into recommendation lanes")
                with span("python", "task.lane_classification"):
                    lane_count = _classify_lanes(
                        connection, model.model_id, progress=_mapped_progress(0.95, 0.97)
                    )
                _progress(0.97)
                _log("i", "Preparing recommendation pages")
                with span("python", "task.prepare_pages"):
                    lane_caches = _prepare_lanes(
                        connection, model.model_id, progress=_mapped_progress(0.97, 0.99)
                    )
                _progress(0.99)
                summary = {
                    "updated": True,
                    "model_id": model.model_id,
                    "lane_classifications": lane_count,
                    "lane_candidate_caches": lane_caches,
                    "stage_timings_ms": model.stage_timings_ms,
                }
        elif mode == "prepare":
            _progress(0.05)
            prepared_model_id = RecommendationModelStore(connection).current_model_id()
            if prepared_model_id is None:
                raise RuntimeError("no published model; build recommendations first")
            _log("i", "Preparing recommendation pages")
            with span("python", "task.prepare_pages"):
                lane_caches = _prepare_lanes(
                    connection, prepared_model_id, progress=_mapped_progress(0.05, 0.99)
                )
            _progress(0.99)
            summary = {"model_id": prepared_model_id, "lane_candidate_caches": lane_caches}
        elif mode == "backup":
            _progress(0.05)
            destination = (
                _backup_directory(payload, settings) / f"curator-{started_at_ms}.sqlite3.backup"
            )
            with span("python", "task.backup"):
                backup_database(connection, destination, progress=_mapped_progress(0.05, 0.95))
            _progress(0.98)
            summary = {"backup": str(destination)}
        elif mode == "compact":
            _progress(0.1)
            _log("i", "Validating generation artifacts")
            with span("python", "task.compact"):
                summary = compact_legacy_generations(
                    connection, progress=_mapped_progress(0.10, 0.95)
                )
            _progress(0.98)
        elif mode == "vacuum":
            if compaction_status(connection)["status"] != "complete":
                raise RuntimeError("compact legacy Curator data before vacuuming")
            _progress(0.05)
            database = _database_path(payload, settings).expanduser().resolve()
            before = database.stat().st_size
            _log("i", "Vacuuming compacted Curator data")
            with span("python", "task.vacuum"):
                _progress(0.10)
                connection.execute("VACUUM")
                _progress(0.94)
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _progress(0.98)
            summary = {
                "bytes_before": before,
                "bytes_after": database.stat().st_size,
            }
        elif mode == "expand-refresh":
            _progress(0.05)
            config = CuratorAPI(connection).config()["config"]
            assert isinstance(config, dict)
            _log("i", "Collecting bounded StashDB candidates")
            with span("python", "task.expand_refresh"):
                summary = ExpandService(connection).refresh(
                    _stashdb(payload),
                    # The refresh task is the escape hatch when Stash under-reports a change.
                    _external_links(payload, connection, refresh=True),
                    horizon_days=int(config["expand_horizon_days"]),
                    gender=str(config["expand_gender"]),
                    wildcard=bool(config["expand_wildcard"]),
                    progress=_mapped_progress(0.05, 0.98),
                )
            _progress(0.98)
        else:
            raise ValueError(f"unknown Curator task: {mode}")
    except Exception as error:
        with transaction(connection):
            connection.execute(
                """
                UPDATE curator_job SET state='failed', finished_at_ms=?, error=?
                WHERE job_id=?
                """,
                (time.time_ns() // 1_000_000, str(error)[:2000], job_id),
            )
        _log("e", f"Stash Curator {mode} failed: {error}")
        raise
    else:
        with transaction(connection):
            connection.execute(
                """
                UPDATE curator_job SET state='complete', finished_at_ms=?, summary_json=?
                WHERE job_id=?
                """,
                (
                    time.time_ns() // 1_000_000,
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    job_id,
                ),
            )
        _log("i", f"Stash Curator {mode} completed")
        _progress(1.0)
        return {"schema_version": SCHEMA_VERSION, "job_id": job_id, **summary}
    finally:
        connection.close()


def _profiled[T](
    payload: dict[str, Any], name: str, kind: str, call: Callable[[dict[str, Any]], T]
) -> T:
    trace, token = begin_trace(name, kind)
    try:
        settings = _settings(payload)
    except BaseException as settings_failure:
        end_trace(trace, token, settings_failure)
        raise
    if not bool(settings.get("profilingEnabled", False)):
        end_trace(trace, token)
        return call(settings)

    failure: BaseException | None = None
    try:
        return call(settings)
    except BaseException as caught:
        failure = caught
        raise
    finally:
        end_trace(trace, token, failure)
        try:
            save_trace(_database_path(payload, settings), trace)
        except Exception as save_error:
            _log("w", f"Could not save Curator profile: {save_error}")


def _install_optional_deps() -> dict[str, object]:
    """Install the plugin's optional Python dependencies into a local venv.

    Mirrors the community Python Tools Installer pattern: a venv created inside the
    plugin directory persists on the plugin volume across container recreations, and
    the backend sys.path shim makes its site-packages importable. Runs without the
    sidecar database so it works on a fresh install.
    """
    venv_dir = PLUGIN_DIR / "venv"
    requirements = PLUGIN_DIR / "packages" / "curator-tools.txt"
    if not requirements.is_file():
        raise RuntimeError(f"missing optional dependency manifest: {requirements}")
    _log("i", f"Installing optional Curator dependencies from {requirements.name}")
    _progress(0.05)
    if not (venv_dir / "pyvenv.cfg").is_file():
        _log("i", f"Creating virtual environment at {venv_dir}")
        create_venv(venv_dir, with_pip=True)
    _progress(0.30)
    pip = venv_dir / "bin" / "pip"
    _log("i", "Running " + " ".join([str(pip), "install", "-r", str(requirements)]))
    completed = subprocess.run(
        [str(pip), "install", "-r", str(requirements)],
        capture_output=True,
        text=True,
        check=False,
    )
    _progress(0.95)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise RuntimeError(f"pip install failed: {detail[-1] if detail else 'unknown error'}")
    _log("i", "Optional Curator dependencies installed")
    _progress(1.0)
    return {"status": "ok", "venv": str(venv_dir), "requirements": str(requirements)}


def _run_task(payload: dict[str, Any], mode: str) -> dict[str, object]:
    if mode == "install-deps":
        return _install_optional_deps()
    return _profiled(
        payload,
        mode,
        "task",
        lambda settings: _run_task_body(payload, mode, settings),
    )


def dispatch(payload: dict[str, Any]) -> dict[str, object]:
    operation = str((payload.get("args") or {}).get("operation") or "health")
    if operation == "health":
        return _health(payload)
    if operation == "round_trip":
        return _round_trip(payload)
    if operation in {"list_backups", "create_backup", "restore_backup", "delete_backup"}:
        return _backup_control(payload, operation, _settings(payload))
    if operation == "reset":
        if str((payload.get("args") or {}).get("confirmation") or "") != "RESET":
            raise ValueError("reset requires confirmation")
        settings = _settings(payload)
        database = _database_path(payload, settings)
        connection = _open(payload, settings)
        running = connection.execute(
            "SELECT 1 FROM curator_job WHERE state='running' LIMIT 1"
        ).fetchone()
        connection.close()
        if running:
            raise RuntimeError("cannot reset Curator while a job is running")
        from curator.storage.artifacts import recognized_artifacts

        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            *recognized_artifacts(database),
        ):
            path.unlink(missing_ok=True)
        connection = _open(payload, settings)
        connection.close()
        return {"schema_version": SCHEMA_VERSION, "reset": True}
    excluded = {
        "get_job_status",
        "list_profiles",
        "get_profile",
        "clear_profiles",
    }
    if operation in excluded:
        return _api(payload, operation, _settings(payload))
    return _profiled(
        payload,
        operation,
        "operation",
        lambda profiled_settings: _api(payload, operation, profiled_settings),
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("plugin input must be an object")
        mode = sys.argv[2] if len(sys.argv) > 2 else None
        output = _run_task(payload, mode) if mode else dispatch(payload)
        print(json.dumps({"output": output}, separators=(",", ":")))
    except Exception as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
