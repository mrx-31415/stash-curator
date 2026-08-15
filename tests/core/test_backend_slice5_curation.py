"""Slice-5 backend differential harness: the curation-loop ops.

get_curation_batch, submit_curation_ratings, get_curation_verdict, and
get_tag_context_candidates run through the Go binary and plugin/backend.py
on fresh sidecar copies; stdout must be byte-identical per the tolerance
policy (structure exact, floats within rel 1e-9). batch_id is generated per
run (uuid4) and normalized away before comparison.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator.core import core_binary
from tests.core.test_backend import make_sidecar, payload
from tests.core.test_backend_slice3_backups import assert_slice3_identical

FEATURE_VERSION = "fv-x"
MODEL_ID = "model-m1"
BATCH_X = "batch-x"  # open, for submit tests
BATCH_V = "batch-v"  # rated hypothesis batch, for verdict tests
BATCH_E = "batch-e"  # rated explore batch, for verdict tests


class _StubSlice5(BaseHTTPRequestHandler):
    """Stash stub answering the settings query (empty plugin settings)."""

    plugin_settings: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        if "CuratorPluginSettings" in body:
            data: dict[str, object] = {"data": {"configuration": {"plugins": {}}}}
            if self.plugin_settings:
                data = {
                    "data": {"configuration": {"plugins": {"stash-curator": self.plugin_settings}}}
                }
        else:
            data = {"errors": [{"message": f"no stub for {body[:80]}"}]}
        payload_bytes = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload_bytes)))
        self.end_headers()
        self.wfile.write(payload_bytes)

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
    server = HTTPServer(("127.0.0.1", 0), _StubSlice5)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_slice5_sidecar(path: Path) -> None:
    """A migrated sidecar exercising every curation op: taxonomy-matched tags,
    a published model with scores, a labeled scene, a blocked tag, and three
    fixture batches (open, rated-hypothesis, rated-explore)."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_studio(studio_id, name, source_hash) VALUES
                ('st1', 'Studio A', 'a'), ('st2', 'Studio B', 'b'),
                ('st3', 'Studio C', 'c')
            """
        )
        connection.execute(
            """
            INSERT INTO source_scene(scene_id, studio_id, title, updated_at, source_hash)
            VALUES
                ('s1', 'st1', 'One', '2026-01-01T00:00:00Z', 'h1'),
                ('s2', 'st2', 'Two', '2026-01-01T00:00:00Z', 'h2'),
                ('s3', 'st3', 'Three', '2026-01-01T00:00:00Z', 'h3'),
                ('s4', 'st1', 'Four', '2026-01-01T00:00:00Z', 'h4'),
                ('s5', 'st2', 'Five', '2026-01-01T00:00:00Z', 'h5'),
                ('s6', 'st3', 'Six', '2026-01-01T00:00:00Z', 'h6'),
                ('s7', 'st1', 'Seven', '2026-01-01T00:00:00Z', 'h7'),
                ('s8', 'st2', 'Eight', '2026-01-01T00:00:00Z', 'h8'),
                ('s9', NULL, 'Nine', '2026-01-01T00:00:00Z', 'h9'),
                ('s10', NULL, 'Ten', '2026-01-01T00:00:00Z', 'h10'),
                ('s11', NULL, 'Eleven', '2026-01-01T00:00:00Z', 'h11'),
                ('s12', NULL, 'Twelve', '2026-01-01T00:00:00Z', 'h12'),
                ('s13', NULL, 'Thirteen', '2026-01-01T00:00:00Z', 'h13'),
                ('s14', NULL, 'Fourteen', '2026-01-01T00:00:00Z', 'h14'),
                ('s15', NULL, 'Fifteen', '2026-01-01T00:00:00Z', 'h15'),
                ('s16', NULL, 'Sixteen', '2026-01-01T00:00:00Z', 'h16'),
                ('s17', NULL, 'Seventeen', '2026-01-01T00:00:00Z', 'h17'),
                ('s18', NULL, 'Eighteen', '2026-01-01T00:00:00Z', 'h18'),
                ('s19', NULL, 'Nineteen', '2026-01-01T00:00:00Z', 'h19'),
                ('s20', NULL, 'Twenty', '2026-01-01T00:00:00Z', 'h20')
            """
        )
        connection.execute(
            """
            INSERT INTO source_tag(tag_id, name, source_hash) VALUES
                ('t1', 'lesbian', 'a'), ('t2', 'threesome', 'b'),
                ('t3', 'anal', 'c'), ('t4', 'red hair', 'd'),
                ('t6', 'never', 'f')
            """
        )
        connection.execute(
            """
            INSERT INTO taxonomy_snapshot(snapshot_id, endpoint, fetched_at_ms,
                category_count, tag_count)
            VALUES ('tax-1', 'https://stashdb.org/graphql', 1, 3, 4)
            """
        )
        connection.execute(
            """
            INSERT INTO taxonomy_category(snapshot_id, category_id, name, group_name)
            VALUES
                ('tax-1', 'cat-act', 'Acts', 'ACTION'),
                ('tax-1', 'cat-grp', 'Group Makeup', 'SCENE'),
                ('tax-1', 'cat-hair', 'Hair Color', 'PEOPLE')
            """
        )
        connection.execute(
            """
            INSERT INTO tag_taxonomy_match(local_tag_id, snapshot_id, external_tag_id,
                external_category_id, match_method, confidence, ambiguity_count)
            VALUES
                ('t1', 'tax-1', 'e1', 'cat-grp', 'stable_id', 1, 0),
                ('t2', 'tax-1', 'e2', 'cat-grp', 'stable_id', 1, 0),
                ('t3', 'tax-1', 'e3', 'cat-act', 'stable_id', 1, 0),
                ('t4', 'tax-1', 'e4', 'cat-hair', 'stable_id', 1, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO scene_tag(scene_id, tag_id) VALUES
                ('s1', 't1'), ('s1', 't2'),
                ('s2', 't1'), ('s2', 't3'),
                ('s3', 't1'),
                ('s4', 't2'),
                ('s5', 't3'), ('s5', 't6'),
                ('s7', 't1'), ('s7', 't2'),
                ('s8', 't2'), ('s8', 't3')
            """
        )
        connection.execute(
            "INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', 'tax-1')"
        )
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                occurred_at_ms, payload_json)
            VALUES ('fb-1', 's3', 'thumb_up', NULL, 1, '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference_history(preference_id, tag_id, value,
                occurred_at_ms, blocked)
            VALUES ('pref-1', 't6', -1.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference(tag_id, preference_id, value,
                occurred_at_ms, blocked)
            VALUES ('t6', 'pref-1', -1.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO model_version(model_id, status, feature_version, config_json,
                created_at_ms, validation_status)
            VALUES (?, 'published', ?, '{}', 1, 'valid')
            """,
            (MODEL_ID, FEATURE_VERSION),
        )
        connection.execute(
            """
            INSERT INTO model_scene_score(model_id, scene_id, general_appeal,
                direct_appeal, direct_confidence, appeal, current_fit, confidence,
                metadata_confidence, recovery, components_json, eligibility_json)
            VALUES
                (?, 's1', 0.30, 0.0, 0.0, 0.30, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's2', -0.10, 0.0, 0.0, -0.10, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's3', 0.00, 0.0, 0.0, 0.00, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's4', 0.20, 0.0, 0.0, 0.20, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's5', 0.10, 0.0, 0.0, 0.10, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's6', 0.05, 0.0, 0.0, 0.05, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's7', -0.20, 0.0, 0.0, -0.20, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's8', 0.15, 0.0, 0.0, 0.15, 0.0, 0.5, 0.5, 1.0, '{}', '{}')
            """,
            (MODEL_ID,) * 8,
        )
        # Open batch for submit tests: s1 already rated.
        connection.execute(
            """
            INSERT INTO curation_batch(batch_id, mode, base_tag_id, context_tag_id,
                budget, status, created_at_ms, payload_json)
            VALUES (?, 'hypothesis', 't1', 't2', 20, 'open', 1, '{}')
            """,
            (BATCH_X,),
        )
        connection.execute(
            """
            INSERT INTO curation_batch_item(batch_id, scene_id, cell, anchor, rated)
            VALUES
                (?, 's1', 'L&T', 0, 1),
                (?, 's2', 'L&!T', 0, 0),
                (?, 's4', '!L&T', 0, 0),
                (?, 's6', 'anchor', 1, 0)
            """,
            (BATCH_X,) * 4,
        )
        # Rated hypothesis batch for verdict tests.
        connection.execute(
            """
            INSERT INTO curation_batch(batch_id, mode, base_tag_id, context_tag_id,
                budget, status, created_at_ms, payload_json)
            VALUES (?, 'hypothesis', 't1', 't2', 20, 'rated', 1, '{}')
            """,
            (BATCH_V,),
        )
        connection.execute(
            """
            INSERT INTO curation_batch_item(batch_id, scene_id, cell, anchor, rated)
            VALUES
                (?, 's1', 'L&T', 0, 1),
                (?, 's2', 'L&!T', 0, 1)
            """,
            (BATCH_V,) * 2,
        )
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                occurred_at_ms, payload_json)
            VALUES
                ('fb-v1', 's1', 'curation_rating', '8', 1,
                 '{"batch_id": "batch-v", "cell": "L&T"}'),
                ('fb-v2', 's2', 'curation_rating', '2', 1,
                 '{"batch_id": "batch-v", "cell": "L&!T"}'),
                ('fb-o1', 's7', 'curation_rating', '3', 1,
                 '{"batch_id": "other", "cell": "L&T"}')
            """
        )
        # Rated explore batch: tags t1/t2/t3 appear twice across the ratings.
        connection.execute(
            """
            INSERT INTO curation_batch(batch_id, mode, base_tag_id, context_tag_id,
                budget, status, created_at_ms, payload_json)
            VALUES (?, 'explore', NULL, NULL, 10, 'rated', 1, '{}')
            """,
            (BATCH_E,),
        )
        connection.execute(
            """
            INSERT INTO curation_batch_item(batch_id, scene_id, cell, anchor, rated)
            VALUES
                (?, 's1', 'explore', 0, 1),
                (?, 's7', 'explore', 0, 1),
                (?, 's2', 'explore', 0, 1)
            """,
            (BATCH_E,) * 3,
        )
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                occurred_at_ms, payload_json)
            VALUES
                ('fb-e1', 's1', 'curation_rating', '8', 1,
                 '{"batch_id": "batch-e", "cell": "explore"}'),
                ('fb-e2', 's7', 'curation_rating', '7', 1,
                 '{"batch_id": "batch-e", "cell": "explore"}'),
                ('fb-e3', 's2', 'curation_rating', '2', 1,
                 '{"batch_id": "batch-e", "cell": "explore"}')
            """
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def slice5_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("slice5-sidecar") / "curator.sqlite3"
    make_slice5_sidecar(path)
    return path


def assert_slice5_identical(
    binary: Path, raw: bytes, same_path: Path, *, normalize: tuple[str, ...] = ()
) -> None:
    """Run both backends on fresh sidecar copies and compare stdout with the
    tolerance comparator (structure exact, floats within rel 1e-9)."""
    assert_slice3_identical(binary, raw, same_path, normalize=normalize)


# ── get_curation_batch ───────────────────────────────────────────────────────


def test_curation_batch_hypothesis_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload(
        "get_curation_batch",
        slice5_sidecar,
        stub_stash,
        mode="hypothesis",
        base_tag_id="t1",
        context_tag_id="t2",
        budget=20,
    )
    assert_slice5_identical(binary, raw, slice5_sidecar, normalize=("batch_id",))


def test_curation_batch_explore_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload(
        "get_curation_batch",
        slice5_sidecar,
        stub_stash,
        mode="explore",
        budget=10,
    )
    assert_slice5_identical(binary, raw, slice5_sidecar, normalize=("batch_id",))


def test_curation_batch_error_paths(binary: Path, stub_stash: str, slice5_sidecar: Path) -> None:
    for extra in (
        {"mode": "nope", "budget": 20},
        {"mode": "hypothesis", "base_tag_id": "t1", "context_tag_id": "t2", "budget": -5},
        {"mode": "hypothesis", "base_tag_id": "t1", "context_tag_id": "t2", "budget": 41},
        {"mode": "hypothesis", "base_tag_id": "t1", "budget": 20},
        {"mode": "hypothesis", "base_tag_id": "t1", "context_tag_id": "t9", "budget": 20},
        {"mode": "hypothesis", "base_tag_id": "t2", "context_tag_id": "t2", "budget": 20},
    ):
        raw = payload("get_curation_batch", slice5_sidecar, stub_stash, **extra)
        assert_slice5_identical(binary, raw, slice5_sidecar)


def test_curation_batch_small_budget_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload("get_curation_batch", slice5_sidecar, stub_stash, mode="explore", budget=7)
    assert_slice5_identical(binary, raw, slice5_sidecar, normalize=("batch_id",))


def test_curation_batch_zero_budget_defaults_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    # budget=0 is falsy, so the wire contract defaults it to 20 in both backends.
    raw = payload(
        "get_curation_batch",
        slice5_sidecar,
        stub_stash,
        mode="explore",
        budget=0,
    )
    assert_slice5_identical(binary, raw, slice5_sidecar, normalize=("batch_id",))


# ── submit_curation_ratings ──────────────────────────────────────────────────


def test_submit_curation_ratings_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload(
        "submit_curation_ratings",
        slice5_sidecar,
        stub_stash,
        batch_id=BATCH_X,
        ratings=[
            {"scene_id": "s2", "value": 8, "reason": None},
            {"scene_id": "s4", "value": 2, "reason": "contradicts_hypothesis"},
            {"scene_id": "s6", "value": 5, "reason": "not_now"},
        ],
    )
    assert_slice5_identical(binary, raw, slice5_sidecar)


def test_submit_curation_ratings_error_paths(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    cases = [
        ("nope", [{"scene_id": "s2", "value": 5, "reason": None}]),
        (BATCH_V, [{"scene_id": "s2", "value": 5, "reason": None}]),  # not open
        (BATCH_X, [{"scene_id": "s9", "value": 5, "reason": None}]),  # not in batch
        (BATCH_X, [{"scene_id": "s1", "value": 5, "reason": None}]),  # already rated
        (
            BATCH_X,
            [
                {"scene_id": "s2", "value": 5, "reason": None},
                {"scene_id": "s2", "value": 6, "reason": None},
            ],
        ),  # duplicate
        (BATCH_X, [{"scene_id": "s2", "value": 7.5, "reason": None}]),  # not integer
        (BATCH_X, [{"scene_id": "s2", "value": 11, "reason": None}]),  # out of range
        (BATCH_X, [{"scene_id": "s2", "value": -1, "reason": None}]),  # out of range
        (BATCH_X, [{"scene_id": "s2", "value": 5, "reason": "oops"}]),  # bad reason
        (BATCH_X, []),  # empty
    ]
    for batch_id, ratings in cases:
        raw = payload(
            "submit_curation_ratings",
            slice5_sidecar,
            stub_stash,
            batch_id=batch_id,
            ratings=ratings,
        )
        assert_slice5_identical(binary, raw, slice5_sidecar)


def test_submit_curation_ratings_not_a_list(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload(
        "submit_curation_ratings",
        slice5_sidecar,
        stub_stash,
        batch_id=BATCH_X,
        ratings={"scene_id": "s2", "value": 5},
    )
    assert_slice5_identical(binary, raw, slice5_sidecar)


# ── get_curation_verdict ─────────────────────────────────────────────────────


def test_curation_verdict_hypothesis_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload("get_curation_verdict", slice5_sidecar, stub_stash, batch_id=BATCH_V)
    assert_slice5_identical(binary, raw, slice5_sidecar)


def test_curation_verdict_explore_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload("get_curation_verdict", slice5_sidecar, stub_stash, batch_id=BATCH_E)
    assert_slice5_identical(binary, raw, slice5_sidecar)


def test_curation_verdict_error_paths(binary: Path, stub_stash: str, slice5_sidecar: Path) -> None:
    for batch_id in ("nope", ""):
        raw = payload("get_curation_verdict", slice5_sidecar, stub_stash, batch_id=batch_id)
        assert_slice5_identical(binary, raw, slice5_sidecar)


# ── get_tag_context_candidates ───────────────────────────────────────────────


def test_tag_context_candidates_byte_identical(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    raw = payload(
        "get_tag_context_candidates",
        slice5_sidecar,
        stub_stash,
        tag_id="t1",
        min_support=1,
    )
    assert_slice5_identical(binary, raw, slice5_sidecar)


def test_tag_context_candidates_error_paths(
    binary: Path, stub_stash: str, slice5_sidecar: Path
) -> None:
    for extra in ({"tag_id": ""}, {"tag_id": "t9"}, {"tag_id": "t1", "min_support": 0}):
        raw = payload("get_tag_context_candidates", slice5_sidecar, stub_stash, **extra)
        assert_slice5_identical(binary, raw, slice5_sidecar)
