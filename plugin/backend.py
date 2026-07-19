#!/usr/bin/env python3
"""Stash raw-plugin transport for Curator operations and tasks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

PLUGIN_DIR = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.resolve()
for package_root in (PLUGIN_DIR, PLUGIN_DIR.parent):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from curator import __version__  # noqa: E402
from curator.api import CuratorAPI  # noqa: E402
from curator.events import HistoricalEventStore  # noqa: E402
from curator.graphql import GraphQLClient  # noqa: E402
from curator.model import ModelUpdateCoordinator, RecommendationModelStore  # noqa: E402
from curator.ranking import LanePolicy, SlateBuilder  # noqa: E402
from curator.storage import (  # noqa: E402
    MigrationRunner,
    backup_database,
    connect_database,
    transaction,
)
from curator.sync import SyncService  # noqa: E402
from curator.sync.repository import SyncRepository  # noqa: E402

SCHEMA_VERSION = 1
RUNTIME_QUERY = """
query CuratorPluginRuntime {
  version { version }
  jobQueue { id status description progress startTime }
}
"""
SETTINGS_QUERY = """
query CuratorPluginSettings {
  configuration { plugins(include: ["stash-curator"]) }
}
"""


def _log(level: str, message: str) -> None:
    print(f"\x01{level}\x02{message}", file=sys.stderr, flush=True)


def _progress(value: float) -> None:
    _log("p", f"{max(0.0, min(value, 1.0)):.4f}")


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


def _settings(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _client(payload).execute(SETTINGS_QUERY)
        configuration = result.get("configuration") or {}
        plugins = configuration.get("plugins") or {}
        settings = plugins.get("stash-curator") or {}
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def _database_path(payload: dict[str, Any], settings: dict[str, Any] | None = None) -> Path:
    configured = str((payload.get("args") or {}).get("database_path") or "").strip()
    if not configured:
        configured = str((settings or {}).get("databasePath") or "").strip()
    return Path(configured).expanduser() if configured else PLUGIN_DIR / "data" / "curator.sqlite3"


def _apply_plugin_settings(connection: Any, settings: dict[str, Any]) -> None:
    mapping = {
        "pageSize": ("page_size", int),
        "syncPageSize": ("sync_page_size", int),
        "modelUpdateEventThreshold": ("model_update_event_threshold", int),
        "modelUpdateMaxWaitMinutes": ("model_update_max_wait_minutes", float),
        "modelUpdateMinIntervalMinutes": ("model_update_min_interval_minutes", float),
    }
    overrides = {
        key: convert(settings[source])
        for source, (key, convert) in mapping.items()
        if settings.get(source) not in (None, "")
    }
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


def _open(payload: dict[str, Any], settings: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    connection = connect_database(_database_path(payload, settings))
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
    }
    active_job = next(
        (
            job
            for job in (stash.get("jobQueue") or [])
            if any(name in str(job.get("description") or "") for name in task_names)
        ),
        None,
    )
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
        "model_id": str(current[0]) if current else None,
        "ready": current is not None,
        "capture": capture,
        "model_pending": model_update.pending,
        "model_pending_events": model_update.pending_count,
        "model_update_ready": model_update_ready,
        "model_rebuilding": model_rebuilding is not None and active_job is not None,
        "active_job": active_job,
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


def _api(payload: dict[str, Any], operation: str) -> dict[str, object]:
    connection = _open(payload, _settings(payload))
    args = payload.get("args") or {}
    try:
        api = CuratorAPI(connection)
        if operation == "get_slate":
            config = api.config()["config"]
            count = int(
                args.get("count")
                or (config.get("page_size", 20) if isinstance(config, dict) else 20)
            )
            return api.get_slate(
                str(args.get("lane") or "for_you"),
                count,
                impression_id=str(args["impression_id"]) if args.get("impression_id") else None,
                context=args.get("context") if isinstance(args.get("context"), dict) else None,
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
        if operation == "submit_feedback":
            entries = args.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            return api.submit_feedback(entries)
        if operation == "submit_events":
            entries = args.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            return api.submit_events(entries)
        if operation == "get_pruning_queue":
            return api.pruning_queue()
        if operation == "update_pruning":
            return api.update_pruning(str(args.get("scene_id") or ""), str(args.get("state") or ""))
        if operation == "get_exclusions":
            return api.exclusions()
        if operation == "reverse_exclusion":
            return api.reverse_exclusion(str(args.get("scene_id") or ""))
        if operation == "get_config":
            return api.config()
        if operation == "update_config":
            values = args.get("values")
            if not isinstance(values, dict):
                raise ValueError("values must be an object")
            return api.update_config(values)
        if operation == "get_job_status":
            return _job_status(connection)
        if operation == "get_inspector_entity":
            return api.inspector(
                str(args.get("entity_type") or ""), str(args.get("entity_id") or "")
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


def _run_task(payload: dict[str, Any], mode: str) -> dict[str, object]:
    settings = _settings(payload)
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
                _progress(0.05 + 0.7 * ((position + fraction) / entity_count))
                milestone = int(fraction * 10)
                if milestone > logged_milestones.get(entity, -1):
                    logged_milestones[entity] = milestone
                    _log("i", f"Synchronizing {entity}s: {processed}/{total}")

            _log("i", "Synchronizing Stash metadata")
            synced = SyncService(
                _client(payload),
                SyncRepository(connection),
                page_size=int(sidecar_config["sync_page_size"]),
                progress=report_sync,
            ).sync(full=mode == "full-sync-build")
            _progress(0.78)
            _log("i", "Rebuilding historical preference signals")
            historical = HistoricalEventStore(connection).rebuild(
                None if mode == "full-sync-build" or synced.resumed else synced.scene_ids
            )
            _progress(0.86)
            _log("i", "Building the recommendation model")
            coordinator = ModelUpdateCoordinator(connection)
            coordinator.request("source_sync")
            model = coordinator.drain(force=True, max_builds=1)[0]
            _progress(0.94)
            _log("i", "Organizing scenes into recommendation lanes")
            lane_count = len(LanePolicy(connection).classify(model.model_id))
            _progress(0.96)
            _log("i", "Preparing fast lane caches")
            lane_caches = SlateBuilder(connection).prepare(
                model.model_id, slate_size=max(60, int(sidecar_config["page_size"]) * 3)
            )
            _progress(0.98)
            _log("i", f"Published recommendation model {model.model_id}")
            summary: dict[str, object] = {
                "sync_run_id": synced.run_id,
                "entity_counts": synced.entity_counts,
                "historical_scenes": historical.scene_count,
                "model_id": model.model_id,
                "lane_classifications": lane_count,
                "lane_candidate_caches": lane_caches,
                "stage_timings_ms": model.stage_timings_ms,
            }
        elif mode in {"build", "update-model"}:
            _progress(0.1)
            _log("i", "Building the recommendation model")
            model_milestone = -1

            def report_model(processed: int, total: int) -> None:
                nonlocal model_milestone
                fraction = 1.0 if total == 0 else min(processed / total, 1.0)
                _progress(0.12 + 0.78 * fraction)
                milestone = int(fraction * 10)
                if milestone > model_milestone:
                    model_milestone = milestone
                    _log("i", f"Scoring scenes: {processed}/{total}")

            coordinator = ModelUpdateCoordinator(connection)
            if mode == "build":
                coordinator.request("manual_build")
            models = coordinator.drain(force=True, max_builds=1, progress=report_model)
            if not models:
                summary = {"updated": False}
                _progress(0.98)
                _log("i", "No pending preference changes")
            else:
                model = models[-1]
                _progress(0.94)
                _log("i", "Organizing scenes into recommendation lanes")
                lane_count = len(LanePolicy(connection).classify(model.model_id))
                _progress(0.96)
                _log("i", "Preparing fast lane caches")
                config = CuratorAPI(connection).config()["config"]
                assert isinstance(config, dict)
                lane_caches = SlateBuilder(connection).prepare(
                    model.model_id, slate_size=max(60, int(config["page_size"]) * 3)
                )
                _progress(0.98)
                summary = {
                    "updated": True,
                    "model_id": model.model_id,
                    "lane_classifications": lane_count,
                    "lane_candidate_caches": lane_caches,
                    "stage_timings_ms": model.stage_timings_ms,
                }
        elif mode == "prepare":
            _progress(0.1)
            model_id = RecommendationModelStore(connection).current_model_id()
            if model_id is None:
                raise RuntimeError("no published model; build recommendations first")
            config = CuratorAPI(connection).config()["config"]
            assert isinstance(config, dict)
            _log("i", "Preparing recommendation pages")
            lane_caches = SlateBuilder(connection).prepare(
                model_id, slate_size=max(60, int(config["page_size"]) * 3)
            )
            _progress(0.98)
            summary = {"model_id": model_id, "lane_candidate_caches": lane_caches}
        elif mode == "backup":
            _progress(0.1)
            destination = PLUGIN_DIR / "data" / f"curator-{started_at_ms}.sqlite3.backup"
            backup_database(connection, destination)
            _progress(0.98)
            summary = {"backup": str(destination)}
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


def dispatch(payload: dict[str, Any]) -> dict[str, object]:
    operation = str((payload.get("args") or {}).get("operation") or "health")
    if operation == "health":
        return _health(payload)
    if operation == "round_trip":
        return _round_trip(payload)
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
        for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
            path.unlink(missing_ok=True)
        connection = _open(payload, settings)
        connection.close()
        return {"schema_version": SCHEMA_VERSION, "reset": True}
    return _api(payload, operation)


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
