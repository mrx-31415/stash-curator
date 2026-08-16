"""Slice-1 backend differential harness: model-seeded read-path ops.

The Slice-1 ops (get_slate, replace_item, get_similar, get_explanation,
get_recommendation_history, get_shortlist, get_feedback_history,
get_taste_profile, get_diagnostics) read a *published model* through the
attached artifact views, so a plain migrated sidecar is not enough: the
sidecar is seeded by building a real model with the Python builder on the
synthetic corpus from tests/model/test_builder.py, then interaction rows are
added deterministically. Every test runs plugin/backend.py and the built
curator-core binary against identical fresh sidecar copies and asserts the
outputs are byte-identical per the run-varying-fields contract from
docs/handover-go-backend-slice1.md (fixed impression_id in args; timing
fields compared structurally). These tests skip when the binary is not
built; `scripts/verify core` builds it and runs this suite.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from curator.model import PreferenceModelBuilder
from tests.core.compare import assert_equivalent
from tests.core.test_backend import PLUGIN_DIR, _StubStash, _with_db_path, payload, run_backend
from tests.model.test_builder import REFERENCE_MS, _database

DAY_MS = 86_400_000


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubStash)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_model_sidecar(path: Path) -> None:
    """A synthetic sidecar with a published model (real builder output) and
    deterministic interaction rows for the read-path ops."""
    connection = _database(path)
    try:
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        connection.executemany(
            """
            INSERT INTO impression(
                impression_id, requested_at_ms, lane, model_id, config_version,
                request_context_json
            ) VALUES (?, ?, 'for_you', 'model-seed', 'builtin', '{}')
            """,
            [(f"imp-hist-{i}", REFERENCE_MS - (50 - i) * DAY_MS) for i in range(3)],
        )
        connection.executemany(
            """
            INSERT INTO impression_item(
                impression_id, scene_id, position, policy_score, reason_snapshot_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("imp-hist-0", "old-good", 0, 0.5, '["eligibility.lane"]'),
                ("imp-hist-1", "recent-good", 0, 0.6, '["eligibility.lane"]'),
                ("imp-hist-2", "unseen-good", 0, 0.4, '["eligibility.lane"]'),
            ],
        )
        connection.executemany(
            """
            INSERT INTO recommendation_history(history_id, scene_id, impression_id,
                lane, shown_at_ms) VALUES (?, ?, ?, 'for_you', ?)
            """,
            [
                ("imp-hist-0:old-good", "old-good", "imp-hist-0", REFERENCE_MS - 50 * DAY_MS),
                ("imp-hist-1:recent-good", "recent-good", "imp-hist-1", REFERENCE_MS - 25 * DAY_MS),
                ("imp-hist-2:unseen-good", "unseen-good", "imp-hist-2", REFERENCE_MS - 8 * DAY_MS),
            ],
        )
        connection.executemany(
            """
            INSERT INTO feedback(
                feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                impression_id, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("fb-1", "old-good", "thumb_up", 1.0, REFERENCE_MS - 30 * DAY_MS, None, "{}"),
                ("fb-2", "recent-good", "thumb_up", 1.0, REFERENCE_MS - 20 * DAY_MS, None, "{}"),
                ("fb-3", "disliked", "not_now", None, REFERENCE_MS - 10 * DAY_MS, None, "{}"),
                (
                    "fb-4",
                    "unseen-good",
                    "reversal",
                    None,
                    REFERENCE_MS - 5 * DAY_MS,
                    None,
                    '{"replaces_feedback_id":"fb-1"}',
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO external_shortlist(
                entity_type, external_id, score, sources_json, payload_json, added_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "scene",
                    "stashdb-1",
                    0.92,
                    '["stashdb"]',
                    '{"title":"External One","date":"2020-01-01"}',
                    REFERENCE_MS - 40 * DAY_MS,
                ),
                (
                    "scene",
                    "stashdb-2",
                    0.71,
                    '["stashdb","manual"]',
                    '{"title":"External Two"}',
                    REFERENCE_MS - 15 * DAY_MS,
                ),
                (
                    "performer",
                    "stashdb-perf-1",
                    0.65,
                    '["stashdb"]',
                    '{"name":"Performer X"}',
                    REFERENCE_MS - 3 * DAY_MS,
                ),
            ],
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


@pytest.fixture(scope="module")
def model_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("model-sidecar") / "curator.sqlite3"
    make_model_sidecar(path)
    return path


def assert_slice1_identical(
    binary: Path,
    plugin_dir: Path,
    raw: bytes,
    same_path: Path,
    *,
    timing_fields: tuple[str, ...] = (),
    normalize: tuple[str, ...] = (),
) -> None:
    """Run both backends on fresh copies of the model sidecar and assert the
    outputs are byte-identical once the run-varying fields are handled:
    timing fields are compared structurally (key set + non-negative ints,
    values may differ) and the listed fields are dropped (uuid4 fields like
    replace_item's impression_id)."""
    run_dir = same_path.parent / f"{same_path.stem}-backend-run"
    run_db = run_dir / same_path.name
    derived_src = same_path.parent / f"{same_path.stem}-derived"
    outputs: list = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(same_path, run_db)
        derived_dst = run_dir / f"{run_db.stem}-derived"
        if derived_src.is_dir():
            shutil.copytree(derived_src, derived_dst)
        try:
            result = run_backend(runner, plugin_dir, _with_db_path(raw, run_db))
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        outputs.append(result)
    python_result, go_result = outputs
    assert go_result.returncode == python_result.returncode
    py_out = json.loads(python_result.stdout)
    go_out = json.loads(go_result.stdout)
    if python_result.returncode != 0:
        assert_equivalent(py_out, go_out)
        return
    assert set(py_out) == {"output"} and set(go_out) == {"output"}
    a, b = py_out["output"], go_out["output"]
    for field in timing_fields:
        if isinstance(a[field], dict):
            assert set(a[field]) == set(b[field])
            for value in (*a[field].values(), *b[field].values()):
                assert isinstance(value, int) and value >= 0
        else:
            assert isinstance(a[field], int) and isinstance(b[field], int)
            assert a[field] >= 0 and b[field] >= 0
        a.pop(field)
        b.pop(field)
    for field in normalize:
        _strip_key(a, field)
        _strip_key(b, field)
    assert_equivalent(a, b)


def _strip_key(value: object, key: str) -> None:
    """Remove every key named `key` at any depth (uuid4 fields that vary
    between runs)."""
    if isinstance(value, dict):
        value.pop(key, None)
        for item in value.values():
            _strip_key(item, key)
    elif isinstance(value, list):
        for item in value:
            _strip_key(item, key)


# ── byte-identical Slice-1 ops on a builder-seeded sidecar ──────────────────


def test_get_slate_byte_identical(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload(
        "get_slate",
        model_sidecar,
        stub_stash,
        lane="for_you",
        count=5,
        page=1,
        impression_id="fixed-impression-slate",
    )
    assert_slice1_identical(
        binary,
        PLUGIN_DIR,
        raw,
        same_path=model_sidecar,
        timing_fields=("timings_ms", "ranking_timings_ms"),
    )


def test_get_slate_page_exclusions_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_slate",
        model_sidecar,
        stub_stash,
        lane="best_bets",
        count=3,
        page=2,
        exclude_scene_ids=["unseen-good"],
        impression_id="fixed-impression-slate-2",
    )
    assert_slice1_identical(
        binary,
        PLUGIN_DIR,
        raw,
        same_path=model_sidecar,
        timing_fields=("timings_ms", "ranking_timings_ms"),
    )


def test_get_slate_performer_and_tag_filters_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_slate",
        model_sidecar,
        stub_stash,
        lane="for_you",
        count=5,
        page=1,
        performer_ids=["p1"],
        include_tags=["Familiar Scenario"],
        impression_id="fixed-impression-slate-filters",
    )
    assert_slice1_identical(
        binary,
        PLUGIN_DIR,
        raw,
        same_path=model_sidecar,
        timing_fields=("timings_ms", "ranking_timings_ms"),
    )


def test_get_slate_studio_and_gender_filters_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_slate",
        model_sidecar,
        stub_stash,
        lane="for_you",
        count=5,
        page=1,
        studio_ids=["studio-2"],
        exclude_tags=["nonexistent-tag"],
        gender="FEMALE",
        impression_id="fixed-impression-slate-filters-2",
    )
    assert_slice1_identical(
        binary,
        PLUGIN_DIR,
        raw,
        same_path=model_sidecar,
        timing_fields=("timings_ms", "ranking_timings_ms"),
    )


def test_replace_item_byte_identical(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload(
        "replace_item", model_sidecar, stub_stash, lane="for_you", exclude_scene_ids=["old-good"]
    )
    # replace_item never accepts an impression_id, so it is uuid4 on both
    # sides; the rest of the output must match byte for byte.
    assert_slice1_identical(
        binary,
        PLUGIN_DIR,
        raw,
        same_path=model_sidecar,
        timing_fields=("timings_ms", "ranking_timings_ms"),
        normalize=("impression_id",),
    )


def test_get_similar_scene_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_similar",
        model_sidecar,
        stub_stash,
        entity_type="scene",
        entity_id="recent-good",
        count=5,
        page=1,
        impression_id="fixed-impression-similar",
    )
    assert_slice1_identical(
        binary, PLUGIN_DIR, raw, same_path=model_sidecar, timing_fields=("timings_ms",)
    )


def test_get_similar_scene_filters_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_similar",
        model_sidecar,
        stub_stash,
        entity_type="scene",
        entity_id="old-good",
        count=3,
        page=1,
        include_tags=["Familiar Scenario"],
        favorite_only=True,
        impression_id="fixed-impression-similar-2",
    )
    assert_slice1_identical(
        binary, PLUGIN_DIR, raw, same_path=model_sidecar, timing_fields=("timings_ms",)
    )


def test_get_similar_performer_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_similar",
        model_sidecar,
        stub_stash,
        entity_type="performer",
        entity_id="p1",
        count=5,
        page=1,
    )
    assert_slice1_identical(
        binary, PLUGIN_DIR, raw, same_path=model_sidecar, timing_fields=("timings_ms",)
    )


def test_get_similar_performer_gender_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_similar",
        model_sidecar,
        stub_stash,
        entity_type="performer",
        entity_id="p2",
        count=3,
        page=1,
        gender="FEMALE",
    )
    assert_slice1_identical(
        binary, PLUGIN_DIR, raw, same_path=model_sidecar, timing_fields=("timings_ms",)
    )


def test_get_explanation_byte_identical(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("get_explanation", model_sidecar, stub_stash, scene_id="recent-good")
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_explanation_disliked_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_explanation", model_sidecar, stub_stash, scene_id="disliked")
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_recommendation_history_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_recommendation_history", model_sidecar, stub_stash, page=1, page_size=10)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_shortlist_byte_identical(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("get_shortlist", model_sidecar, stub_stash, page=1, page_size=10)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_feedback_history_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_feedback_history", model_sidecar, stub_stash, page=1, page_size=10)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_taste_profile_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_taste_profile", model_sidecar, stub_stash)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)


def test_get_diagnostics_byte_identical(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("get_diagnostics", model_sidecar, stub_stash)
    assert_slice1_identical(
        binary, PLUGIN_DIR, raw, same_path=model_sidecar, timing_fields=("generated_at_ms",)
    )


# ── read-path write parity ──────────────────────────────────────────────────


def _run_once_on_copy(binary: Path, plugin_dir: Path, raw: bytes, same_path: Path) -> Path:
    """Run the backend once on a fresh copy and return the copy's path."""
    run_dir = same_path.parent / f"{same_path.stem}-write-run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir()
    run_db = run_dir / same_path.name
    shutil.copy2(same_path, run_db)
    derived_src = same_path.parent / f"{same_path.stem}-derived"
    if derived_src.is_dir():
        shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
    result = run_backend(binary, plugin_dir, _with_db_path(raw, run_db))
    assert result.returncode == 0, result.stdout
    return run_db


def _interaction_state(path: Path, prefix: str) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        cache = sorted(
            connection.execute(
                "SELECT key, value FROM application_meta WHERE key LIKE 'eligibility_count:%'"
            ).fetchall()
        )
        impressions = sorted(
            connection.execute(
                """
                SELECT impression_id, lane, model_id, config_version, request_context_json
                FROM impression WHERE impression_id LIKE ?
                """,
                (f"{prefix}%",),
            ).fetchall()
        )
        items = sorted(
            connection.execute(
                """
                SELECT impression_id, scene_id, position, policy_score, reason_snapshot_json
                FROM impression_item WHERE impression_id LIKE ? ORDER BY impression_id, position
                """,
                (f"{prefix}%",),
            ).fetchall()
        )
        return {"cache": cache, "impressions": impressions, "items": items}
    finally:
        connection.close()


def test_get_slate_write_state_parity(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """get_slate's read-path writes (eligibility-count cache + impression
    rows) leave identical sidecar state on both implementations; only the
    requested_at_ms timestamp may differ."""
    raw = payload(
        "get_slate",
        model_sidecar,
        stub_stash,
        lane="for_you",
        count=5,
        page=1,
        impression_id="state-impression",
    )
    python_db = _run_once_on_copy(None, PLUGIN_DIR, raw, model_sidecar)
    go_db = _run_once_on_copy(binary, PLUGIN_DIR, raw, model_sidecar)
    python_state = _interaction_state(python_db, "state-")
    go_state = _interaction_state(go_db, "state-")
    assert python_state["cache"] == go_state["cache"]
    assert python_state["items"] == go_state["items"]
    python_impressions = {row[0]: row for row in python_state["impressions"]}
    go_impressions = {row[0]: row for row in go_state["impressions"]}
    assert set(python_impressions) == set(go_impressions) == {"state-impression"}
    for impression_id, python_row in python_impressions.items():
        go_row = go_impressions[impression_id]
        assert python_row[1:] == go_row[1:]  # everything except requested_at_ms


def test_get_similar_write_state_parity(model_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """get_similar (scene) records a ranked impression with the same state on
    both implementations (the busy_timeout=100 juggling is connection-scoped
    and leaves the same rows)."""
    raw = payload(
        "get_similar",
        model_sidecar,
        stub_stash,
        entity_type="scene",
        entity_id="recent-good",
        count=5,
        page=1,
        impression_id="state-similar",
    )
    python_db = _run_once_on_copy(None, PLUGIN_DIR, raw, model_sidecar)
    go_db = _run_once_on_copy(binary, PLUGIN_DIR, raw, model_sidecar)
    python_state = _interaction_state(python_db, "state-")
    go_state = _interaction_state(go_db, "state-")
    assert python_state["cache"] == go_state["cache"] == []
    assert python_state["items"] == go_state["items"]
    python_impressions = {row[0]: row for row in python_state["impressions"]}
    go_impressions = {row[0]: row for row in go_state["impressions"]}
    assert set(python_impressions) == set(go_impressions) == {"state-similar"}
    for impression_id, python_row in python_impressions.items():
        go_row = go_impressions[impression_id]
        assert python_row[1:] == go_row[1:]
        assert python_row[1] == "similar"


# ── profiling parity for the Slice-1 ops ─────────────────────────────────────


@pytest.mark.parametrize(
    "operation,args",
    [
        ("get_slate", {"lane": "for_you", "count": 3, "impression_id": "trace-impression"}),
        ("get_similar", {"entity_type": "scene", "entity_id": "recent-good", "count": 3}),
        ("get_diagnostics", {}),
    ],
)
def test_slice1_profiling_trace_parity(
    model_sidecar: Path,
    binary: Path,
    stub_stash: str,
    operation: str,
    args: dict[str, object],
) -> None:
    """Every Slice-1 op records a profile_trace row when profilingEnabled is
    on, with the same shape on both implementations: root plugin event, a
    stash span for the settings fetch, sqlite spans, and a consistent
    span_count."""
    _StubStash.plugin_settings = {"profilingEnabled": True}
    try:
        sidecar = model_sidecar
        raw = payload(operation, sidecar, stub_stash, **args)
        rows: dict[str, tuple] = {}
        for runner in (None, binary):
            run_dir = sidecar.parent / f"{sidecar.stem}-trace-{runner is None}"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / sidecar.name
            shutil.copy2(sidecar, run_db)
            derived_src = sidecar.parent / f"{sidecar.stem}-derived"
            if derived_src.is_dir():
                shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            result = run_backend(runner, PLUGIN_DIR, _with_db_path(raw, run_db))
            assert result.returncode == 0, result.stdout
            connection = sqlite3.connect(run_db)
            try:
                row = connection.execute(
                    """
                    SELECT trace_id, kind, operation, started_at_ms, duration_us,
                           status, span_count, truncated, trace_json
                    FROM profile_trace
                    """
                ).fetchone()
            finally:
                connection.close()
            rows["python" if runner is None else "go"] = row
    finally:
        _StubStash.plugin_settings = {}
    python_row, go_row = rows["python"], rows["go"]
    assert python_row is not None and go_row is not None
    for row in (python_row, go_row):
        trace_id, kind, operation_name, _, duration_us, status, span_count, truncated, _ = row
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", trace_id
        )
        assert kind == "operation" and operation_name == operation
        assert status == "ok" and truncated == 0
        assert duration_us >= 0 and span_count > 0
    python_json = json.loads(python_row[8])
    go_json = json.loads(go_row[8])
    assert python_json["displayTimeUnit"] == go_json["displayTimeUnit"] == "ms"
    for events in (python_json["traceEvents"], go_json["traceEvents"]):
        root = events[0]
        assert root["name"] == operation and root["cat"] == "plugin"
        assert root["ph"] == "X" and root["pid"] == 1 and root["tid"] == 0
        assert root["args"] == {"status": "ok", "kind": "operation"}
        assert any(e["cat"] == "stash" and e["name"] == "CuratorPluginSettings" for e in events)
        assert any(e["cat"] == "sqlite" for e in events)
        for event in events:
            assert {"name", "cat", "ph", "ts", "dur", "pid", "tid"} <= set(event)
