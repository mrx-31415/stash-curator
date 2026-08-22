"""Slice-3 backend differential harness: the interactive write ops.

update_shortlist, submit_feedback, correct_feedback, submit_tag_preferences,
submit_events, update_config, the prune/exclusion writes, and the
profile-trace ops run through the Go binary and plugin/backend.py on fresh
sidecar copies; stdout must be byte-identical, and the mutated sidecar state
(interaction rows, coordinator generation counters) must match table-for-
table modulo run-varying timestamps.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator.config import DEFAULT_CONFIG
from curator.core import core_binary
from tests.core.compare import assert_equivalent
from tests.core.test_backend import PLUGIN_DIR, make_sidecar, payload, run_backend
from tests.core.test_backend_slice3_backups import assert_slice3_identical

FEATURE_FP = DEFAULT_CONFIG.feature_fingerprint()[:20]
CONFIG_VERSION = f"cfg-{FEATURE_FP}"


class _StubWrites(BaseHTTPRequestHandler):
    """Stash stub answering settings and the prune-tag query/mutations."""

    tags: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        if "CuratorPluginSettings" in body:
            data = {"data": {"configuration": {"plugins": {}}}}
        elif "CuratorFindPruneTag" in body:
            data = {"data": {"findTags": {"tags": list(self.tags)}}}
        elif "CuratorCreatePruneTag" in body:
            data = {"data": {"tagCreate": {"id": "tag-created", "name": "[Prune]"}}}
        elif "CuratorUpdatePruneTag" in body:
            data = {"data": {"bulkSceneUpdate": {"id": "job-1"}}}
        else:
            data = {"errors": [{"message": f"no stub for {body[:80]}"}]}
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # silence the stub
        pass


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubWrites)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_writes_sidecar(path: Path) -> None:
    """A migrated sidecar with deterministic interaction rows for the write
    ops: scenes, tags with tag_role entries at the live config_version, an
    external entity to shortlist, a published model with scores, and existing
    pruning/feedback/exclusion/impression rows."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_scene(
                scene_id, title, play_count, play_duration_seconds, updated_at, source_hash
            ) VALUES
                ('s1', 'Scene One', 3, 600, '2026-01-01T00:00:00Z', 'h-s1'),
                ('s2', 'Scene Two', 0, 300, '2026-01-02T00:00:00Z', 'h-s2'),
                ('s3', 'Scene Three', 1, 120, '2026-01-03T00:00:00Z', 'h-s3')
            """
        )
        connection.execute(
            """
            INSERT INTO source_tag(tag_id, name, source_hash)
            VALUES ('t1', 'football', 'h1'), ('t2', 'archery', 'h2'), ('t3', 'cycling', 'h3')
            """
        )
        connection.execute(
            f"""
            INSERT INTO tag_role(config_version, tag_id, role, resolution_reason)
            VALUES ('{CONFIG_VERSION}', 't1', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't2', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't3', 'content', 'seeded')
            """
        )
        connection.execute(
            """
            INSERT INTO external_entity(
                entity_type, external_id, payload_json, score, sources_json, fetched_at_ms
            ) VALUES
                ('scene', 'cand-1', '{"title": "Candidate 1"}', 0.9, '["probe"]', 50),
                ('scene', 'cand-2', '{"title": "Candidate 2"}', 0.5, '["probe"]', 50)
            """
        )
        connection.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms, validation_status
            ) VALUES ('model-w', 'published', 'fv-w', '{}', 1, 'valid')
            """
        )
        connection.execute(
            """
            INSERT INTO model_scene_score(
                model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery, components_json
            ) VALUES
                ('model-w', 's1', -0.3, -0.3, 0.9, -0.30, 0.0, 0.90, 0.9, 0.0, '{}'),
                ('model-w', 's2', -0.1, -0.1, 0.4, -0.10, 0.0, 0.40, 0.4, 0.0, '{}'),
                ('model-w', 's3', 0.2, 0.2, 0.8, 0.20, 0.0, 0.80, 0.8, 0.0, '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO pruning_candidate(
                scene_id, state, created_at_ms, updated_at_ms, reason
            ) VALUES
                ('s2', 'review', 100, 100, 'Thumbs down'),
                ('s3', 'remove', 200, 200, 'Tagged [Prune]')
            """
        )
        connection.execute(
            """
            INSERT INTO feedback(
                feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                impression_id, payload_json
            ) VALUES
                ('fb-1', 's1', 'thumb_down', NULL, 300, 'imp-1', '{}'),
                ('fb-2', 's2', 'never_show', NULL, 400, 'imp-2', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO exclusion(
                exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms
            ) VALUES ('exclusion:s2', 'scene', 's2', 'never_show', 400)
            """
        )
        connection.execute(
            """
            INSERT INTO impression(
                impression_id, requested_at_ms, lane, model_id, config_version, request_context_json
            ) VALUES ('imp-1', 100, 'for_you', 'model-w', 'builtin', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO impression_item(
                impression_id, scene_id, position, policy_score, reason_snapshot_json
            ) VALUES ('imp-1', 's1', 0, 0.5, '[]')
            """
        )
        # A Curator-originated observed session that a later replacement can grade.
        connection.execute(
            """
            INSERT INTO play_session(
                session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
                provenance, confidence, impression_id, summary_json
            ) VALUES ('ps-1', 's1', 1000, 1010, 5.0, 'direct_player', 1, 'imp-1', ?)
            """,
            (
                json.dumps(
                    {
                        "active_seconds": 5.0,
                        "ended_at_ms": 1010,
                        "final_position_seconds": 6.0,
                        "impression_id": "imp-1",
                        "impression_position": None,
                        "lane": "for_you",
                        "maximum_position_seconds": 6.0,
                        "model_id": "model-w",
                        "natural_completion": False,
                        "nearby_marker_ids": [],
                        "origin": "curator",
                        "played_ranges": [],
                        "scene_id": "s1",
                        "seek_destinations_seconds": [],
                        "session_id": "ps-1",
                        "source_route": "curator",
                        "started_at_ms": 1000,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO profile_trace(
                trace_id, kind, operation, started_at_ms, duration_us, status,
                span_count, truncated, trace_json
            ) VALUES (
                'trace-1', 'operation', 'get_config', 500, 1000, 'ok', 2, 0,
                '{"traceEvents": [], "displayTimeUnit": "ms"}'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def writes_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("writes-sidecar") / "curator.sqlite3"
    make_writes_sidecar(path)
    return path


def _writes_payload(op: str, sidecar: Path, stash_url: str, **extra: object) -> bytes:
    return payload(op, sidecar, stash_url, **extra)


# ── update_shortlist ─────────────────────────────────────────────────────────


def test_update_shortlist_select_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_shortlist",
        writes_sidecar,
        stub_stash,
        entity_type="scene",
        external_id="cand-1",
        selected=True,
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_shortlist_deselect_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_shortlist",
        writes_sidecar,
        stub_stash,
        entity_type="scene",
        external_id="cand-1",
        selected=False,
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_shortlist_unknown_entity_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_shortlist",
        writes_sidecar,
        stub_stash,
        entity_type="scene",
        external_id="not-in-cache",
        selected=True,
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_shortlist_bad_type_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_shortlist",
        writes_sidecar,
        stub_stash,
        entity_type="studio",
        external_id="cand-1",
        selected=True,
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_shortlist_state_parity(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """The shortlist upsert leaves identical external_shortlist rows."""
    import shutil

    run_dir = writes_sidecar.parent / f"{writes_sidecar.stem}-shortlist-state"
    states: list[list[tuple[object, ...]]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / writes_sidecar.name
        shutil.copy2(writes_sidecar, run_db)
        result = run_backend(
            runner,
            PLUGIN_DIR,
            json.dumps(
                {
                    "server_connection": {
                        "Host": "127.0.0.1",
                        "Port": int(stub_stash.rsplit(":", 1)[1]),
                        "Scheme": "http",
                        "SessionCookie": {},
                    },
                    "args": {
                        "operation": "update_shortlist",
                        "database_path": str(run_db),
                        "entity_type": "scene",
                        "external_id": "cand-1",
                        "selected": True,
                    },
                },
                separators=(",", ":"),
            ).encode(),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            rows = connection.execute(
                "SELECT entity_type, external_id, payload_json, score, sources_json"
                " FROM external_shortlist ORDER BY entity_type, external_id"
            ).fetchall()
            states.append(rows)
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    assert_equivalent(states[0], states[1])


# ── feedback ─────────────────────────────────────────────────────────────────


def test_submit_feedback_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_feedback",
        writes_sidecar,
        stub_stash,
        entries=[
            {
                "feedback_id": "fb-new-1",
                "scene_id": "s1",
                "feedback_type": "thumb_up",
                "value": None,
                "occurred_at_ms": 500,
                "impression_id": "imp-1",
                "payload": {"source": "test"},
            },
            {
                "feedback_id": "fb-new-2",
                "scene_id": "s3",
                "feedback_type": "never_show",
                "value": None,
                "occurred_at_ms": 600,
                "payload": {},
            },
            {
                "feedback_id": "fb-new-3",
                "scene_id": "s2",
                "feedback_type": "prune",
                "value": "low quality",
                "occurred_at_ms": 700,
                "payload": {},
            },
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_feedback_unknown_type_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_feedback",
        writes_sidecar,
        stub_stash,
        entries=[
            {"feedback_id": "x", "scene_id": "s1", "feedback_type": "bogus", "occurred_at_ms": 1}
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_feedback_not_a_list_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("submit_feedback", writes_sidecar, stub_stash, entries="nope")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_correct_feedback_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "correct_feedback",
        writes_sidecar,
        stub_stash,
        feedback_id="fb-1",
        correction_id="fb-corr-1",
        feedback_type="thumb_up",
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_correct_feedback_reversal_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "correct_feedback",
        writes_sidecar,
        stub_stash,
        feedback_id="fb-2",
        correction_id="fb-corr-2",
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_correct_feedback_unknown_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "correct_feedback",
        writes_sidecar,
        stub_stash,
        feedback_id="missing",
        correction_id="fb-corr-3",
        feedback_type="thumb_up",
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


# ── tag preferences ──────────────────────────────────────────────────────────


def test_submit_tag_preferences_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_tag_preferences",
        writes_sidecar,
        stub_stash,
        entries=[
            {"preference_id": "pref-1", "tag_id": "t1", "value": 0.5, "occurred_at_ms": 100},
            {"preference_id": "pref-2", "tag_id": "t2", "value": -1.0, "occurred_at_ms": 200},
            {"preference_id": "pref-3", "tag_id": "t3", "value": None, "occurred_at_ms": 300},
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_tag_preferences_blocked_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_tag_preferences",
        writes_sidecar,
        stub_stash,
        entries=[
            {
                "preference_id": "pref-4",
                "tag_id": "t1",
                "value": 1.0,
                "blocked": True,
                "occurred_at_ms": 150,
            }
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_tag_preferences_bad_sentiment_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_tag_preferences",
        writes_sidecar,
        stub_stash,
        entries=[{"preference_id": "pref-5", "tag_id": "t1", "value": 0.3, "occurred_at_ms": 100}],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_tag_preferences_unknown_tag_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "submit_tag_preferences",
        writes_sidecar,
        stub_stash,
        entries=[
            {"preference_id": "pref-6", "tag_id": "t-unknown", "value": 0.5, "occurred_at_ms": 100}
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


# ── concurrency ──────────────────────────────────────────────────────────────


def test_concurrent_write_ops_never_surface_database_locked(tmp_path: Path, binary: Path) -> None:
    """Concurrent plugin processes opening the sidecar at once — the #109
    multi-tab burst (health polls, hooks, and tasks each spawn a process) —
    must never surface a SQLite busy error: the 30 s busy_timeout plus the
    Go-side retry on the extended busy codes absorbs the contention. Every
    write must land."""
    sidecar = tmp_path / "curator.sqlite3"
    make_writes_sidecar(sidecar)
    raws = [
        _writes_payload(
            "submit_tag_preferences",
            sidecar,
            "http://127.0.0.1:1",
            entries=[
                {
                    "preference_id": f"concurrent-{index}",
                    "tag_id": "t1",
                    "value": 0.5,
                    "occurred_at_ms": index,
                }
            ],
        )
        for index in range(12)
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(run_backend, binary, PLUGIN_DIR, raw) for raw in raws]
        results = [future.result() for future in futures]
    for result in results:
        assert result.returncode == 0, result.stdout + result.stderr
        assert b"locked" not in (result.stdout + result.stderr).lower()
    connection = sqlite3.connect(sidecar)
    try:
        count = connection.execute(
            "SELECT count(*) FROM direct_tag_preference_history"
            " WHERE preference_id LIKE 'concurrent-%'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 12


# ── events ───────────────────────────────────────────────────────────────────


def test_submit_events_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload(
        "submit_events",
        writes_sidecar,
        stub_stash,
        entries=[
            {
                "event_type": "qualified_impression",
                "impression_id": "imp-1",
                "scene_id": "s1",
                "occurred_at_ms": 900,
            },
            {
                "event_type": "play_session",
                "session_id": "ps-2",
                "scene_id": "s1",
                "started_at_ms": 2000,
                "ended_at_ms": 2100,
                "active_seconds": 45.0,
                "origin": "stash",
                "source_route": "",
                "start_position_seconds": 0.0,
                "maximum_position_seconds": 46.0,
                "final_position_seconds": 46.0,
                "played_ranges": [{"start_seconds": 1.0, "end_seconds": 45.0}],
                "seek_destinations_seconds": [],
                "nearby_marker_ids": [],
                "natural_completion": False,
                "impression_id_extra": None,
            },
        ],
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_submit_events_view_signal_state_parity(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """A session with observed playback writes the same behavior_event rows
    (outcome floats bit-identical, since Go uses the glibc-faithful exp)."""
    import shutil

    run_dir = writes_sidecar.parent / f"{writes_sidecar.stem}-view-state"
    states: list[list[tuple[object, ...]]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / writes_sidecar.name
        shutil.copy2(writes_sidecar, run_db)
        result = run_backend(
            runner,
            PLUGIN_DIR,
            json.dumps(
                {
                    "server_connection": {
                        "Host": "127.0.0.1",
                        "Port": int(stub_stash.rsplit(":", 1)[1]),
                        "Scheme": "http",
                        "SessionCookie": {},
                    },
                    "args": {
                        "operation": "submit_events",
                        "database_path": str(run_db),
                        "entries": [
                            {
                                "event_type": "play_session",
                                "session_id": "ps-2",
                                "scene_id": "s1",
                                "started_at_ms": 2000,
                                "ended_at_ms": 2100,
                                "active_seconds": 45.0,
                                "origin": "stash",
                                "played_ranges": [],
                                "seek_destinations_seconds": [],
                                "nearby_marker_ids": [],
                                "natural_completion": False,
                            },
                            {
                                "event_type": "play_session",
                                "session_id": "ps-3",
                                "scene_id": "s1",
                                "started_at_ms": 3000,
                                "ended_at_ms": 3010,
                                "active_seconds": 8.0,
                                "origin": "curator",
                                "impression_id": "imp-1",
                                "played_ranges": [],
                                "seek_destinations_seconds": [],
                                "nearby_marker_ids": [],
                                "natural_completion": False,
                            },
                        ],
                    },
                },
                separators=(",", ":"),
            ).encode(),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            rows = connection.execute(
                "SELECT event_id, event_type, scene_id, outcome, confidence, provenance,"
                " session_id, payload_json FROM behavior_event ORDER BY event_id"
            ).fetchall()
            states.append(rows)
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    assert_equivalent(states[0], states[1])


def test_submit_events_impression_attribution_state_parity(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """A play without a direct impression_id is attributed identically by both
    backends: the most recent same-scene impression shown within the window is
    written into play_session at write time, with the summary carrying an
    inferred marker that stays distinguishable from an observed link."""
    import shutil

    run_dir = writes_sidecar.parent / f"{writes_sidecar.stem}-attribution-state"
    states: list[list[tuple[object, ...]]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / writes_sidecar.name
        shutil.copy2(writes_sidecar, run_db)
        result = run_backend(
            runner,
            PLUGIN_DIR,
            json.dumps(
                {
                    "server_connection": {
                        "Host": "127.0.0.1",
                        "Port": int(stub_stash.rsplit(":", 1)[1]),
                        "Scheme": "http",
                        "SessionCookie": {},
                    },
                    "args": {
                        "operation": "submit_events",
                        "database_path": str(run_db),
                        "entries": [
                            {
                                # Within the window of imp-1 (requested 100) -> inferred link.
                                "event_type": "play_session",
                                "session_id": "ps-in",
                                "scene_id": "s1",
                                "started_at_ms": 2_000,
                                "ended_at_ms": 2_100,
                                "active_seconds": 45.0,
                                "origin": "stash",
                                "played_ranges": [],
                                "seek_destinations_seconds": [],
                                "nearby_marker_ids": [],
                                "natural_completion": False,
                            },
                            {
                                # After the window (100 + 30min + 1) -> no attribution.
                                "event_type": "play_session",
                                "session_id": "ps-stale",
                                "scene_id": "s1",
                                "started_at_ms": 1_800_101,
                                "ended_at_ms": 1_800_201,
                                "active_seconds": 1.0,
                                "origin": "stash",
                                "played_ranges": [],
                                "seek_destinations_seconds": [],
                                "nearby_marker_ids": [],
                                "natural_completion": False,
                            },
                            {
                                # A direct Curator-originated link stays observed.
                                "event_type": "play_session",
                                "session_id": "ps-observed",
                                "scene_id": "s1",
                                "started_at_ms": 3_000,
                                "ended_at_ms": 3_100,
                                "active_seconds": 5.0,
                                "origin": "curator",
                                "impression_id": "imp-1",
                                "played_ranges": [],
                                "seek_destinations_seconds": [],
                                "nearby_marker_ids": [],
                                "natural_completion": False,
                            },
                        ],
                    },
                },
                separators=(",", ":"),
            ).encode(),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            rows = connection.execute(
                "SELECT session_id, impression_id, provenance, summary_json"
                " FROM play_session ORDER BY session_id"
            ).fetchall()
            states.append(rows)
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    # Byte-identical rows, including the serialized summaries.
    assert states[0] == states[1]
    python = {row[0]: row for row in states[0]}
    assert python["ps-in"][1] == "imp-1"
    assert json.loads(python["ps-in"][3])["impression_provenance"] == "inferred"
    assert python["ps-stale"][1] is None
    assert json.loads(python["ps-stale"][3])["impression_provenance"] is None
    assert python["ps-observed"][1] == "imp-1"
    assert json.loads(python["ps-observed"][3])["impression_provenance"] == "observed"


# ── update_config ────────────────────────────────────────────────────────────


def test_update_config_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload(
        "update_config",
        writes_sidecar,
        stub_stash,
        values={"page_size": 40, "expand_gender": "MALE", "diversity_enabled": False},
    )
    assert_slice3_identical(binary, raw, writes_sidecar, normalize=("updated_at_ms",))


def test_update_config_unknown_key_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_config",
        writes_sidecar,
        stub_stash,
        values={"page_size": 40, "bogus_key": 1},
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_config_invalid_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_config",
        writes_sidecar,
        stub_stash,
        values={"page_size": 9999},
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


# ── pruning / exclusions ─────────────────────────────────────────────────────


def test_get_pruning_queue_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("get_pruning_queue", writes_sidecar, stub_stash)
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_prune_candidates_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "get_prune_candidates", writes_sidecar, stub_stash, view="candidates", aggressiveness=0.5
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_prune_candidates_tagged_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "get_prune_candidates", writes_sidecar, stub_stash, view="tagged", page=1, page_size=10
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_prune_candidates_suspects_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "get_prune_candidates", writes_sidecar, stub_stash, view="suspects", aggressiveness=0.9
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_prune_candidates_breadth_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "get_prune_candidates", writes_sidecar, stub_stash, view="breadth", page=1, page_size=10
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_prune_candidates_bad_view_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("get_prune_candidates", writes_sidecar, stub_stash, view="bogus")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_dismiss_prune_candidate_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("dismiss_prune_candidate", writes_sidecar, stub_stash, scene_id="s2")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_pruning_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload("update_pruning", writes_sidecar, stub_stash, scene_id="s2", state="keep")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_update_pruning_not_in_queue_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "update_pruning", writes_sidecar, stub_stash, scene_id="s1", state="remove"
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_exclusions_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload("get_exclusions", writes_sidecar, stub_stash)
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_reverse_exclusion_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("reverse_exclusion", writes_sidecar, stub_stash, scene_id="s2")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_set_prune_tag_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    _StubWrites.tags = [{"id": "tag-1", "name": "[Prune]"}]
    try:
        raw = _writes_payload(
            "set_prune_tag",
            writes_sidecar,
            stub_stash,
            scene_ids=["s1", "s2", "s2"],
            tagged=True,
        )
        assert_slice3_identical(binary, raw, writes_sidecar)
    finally:
        _StubWrites.tags = []


def test_set_prune_tag_creates_tag_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    _StubWrites.tags = []
    try:
        raw = _writes_payload(
            "set_prune_tag",
            writes_sidecar,
            stub_stash,
            scene_ids=["s1"],
            tagged=False,
        )
        assert_slice3_identical(binary, raw, writes_sidecar)
    finally:
        _StubWrites.tags = []


def test_set_prune_tag_too_many_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload(
        "set_prune_tag",
        writes_sidecar,
        stub_stash,
        scene_ids=[f"s{i}" for i in range(101)],
        tagged=True,
    )
    assert_slice3_identical(binary, raw, writes_sidecar)


# ── profile ops ──────────────────────────────────────────────────────────────


def test_list_profiles_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload("list_profiles", writes_sidecar, stub_stash)
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_profile_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload("get_profile", writes_sidecar, stub_stash, trace_id="trace-1")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_get_profile_unknown_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("get_profile", writes_sidecar, stub_stash, trace_id="trace-missing")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_clear_profiles_byte_identical(writes_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = _writes_payload("clear_profiles", writes_sidecar, stub_stash, confirmation="CLEAR")
    assert_slice3_identical(binary, raw, writes_sidecar)


def test_clear_profiles_wrong_confirmation_byte_identical(
    writes_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = _writes_payload("clear_profiles", writes_sidecar, stub_stash, confirmation="NOPE")
    assert_slice3_identical(binary, raw, writes_sidecar)
