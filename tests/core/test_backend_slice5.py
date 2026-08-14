"""Slice-5 backend differential harness: the get_score_review read-path op.

get_score_review runs through the Go binary and plugin/backend.py on fresh
sidecar copies, and the stdout must be byte-identical once the uuid4
impression_id (per-request, never accepted in args) is normalized. The
response shape is exactly the fixed contract {items, total, page_size,
has_more, page, model_version}; items mirror a get_slate recommendation item
with lane "score_review" and final_utility = appeal. The read-path write
(the "score_review" impression rows) leaves identical sidecar state on both
implementations, and the error paths (invalid page, no published model)
match byte for byte.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR, make_sidecar, payload
from tests.core.test_backend_slice3_backups import assert_slice3_identical

MODEL_ID = "model-x"


class _StubSlice5(BaseHTTPRequestHandler):
    """Stash stub answering the settings query (empty plugin settings)."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        if "CuratorPluginSettings" in body:
            data: dict[str, object] = {"data": {"configuration": {"plugins": {}}}}
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


def make_score_review_sidecar(path: Path) -> None:
    """A migrated sidecar exercising get_score_review: a published model whose
    score rows cover the review window (s3 hard-excluded, s4 carries a
    current thumb_down — shown on the review surface, s8 has no available
    file), with a neighbor row for s1."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_scene(scene_id, title, play_count, play_duration_seconds,
                updated_at, source_hash) VALUES
                ('s1', 'Scene One', 0, 0, NULL, 'h-s1'),
                ('s2', 'Scene Two', 0, 0, NULL, 'h-s2'),
                ('s3', 'Scene Three', 0, 0, NULL, 'h-s3'),
                ('s4', 'Scene Four', 0, 0, NULL, 'h-s4'),
                ('s5', 'Scene Five', 0, 0, NULL, 'h-s5'),
                ('s6', 'Scene Six', 0, 0, NULL, 'h-s6'),
                ('s7', 'Scene Seven', 0, 0, NULL, 'h-s7'),
                ('s8', 'Scene Eight', 0, 0, NULL, 'h-s8')
            """
        )
        connection.execute(
            """
            INSERT INTO source_file(file_id, scene_id, available, source_hash) VALUES
                ('f-s1', 's1', 1, 'h-s1'), ('f-s2', 's2', 1, 'h-s2'),
                ('f-s3', 's3', 1, 'h-s3'), ('f-s4', 's4', 1, 'h-s4'),
                ('f-s5', 's5', 1, 'h-s5'), ('f-s6', 's6', 1, 'h-s6'),
                ('f-s7', 's7', 1, 'h-s7'), ('f-s8', 's8', 0, 'h-s8')
            """
        )
        connection.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms, validation_status
            ) VALUES (?, 'published', 'fv-x', '{}', 1, 'valid')
            """,
            (MODEL_ID,),
        )
        connection.execute(
            """
            INSERT INTO model_scene_score(
                model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery,
                components_json, eligibility_json
            ) VALUES
                (?, 's1', -0.9, -0.9, 0.9, -0.90, -0.45, 0.90, 0.9, 0.0,
                 '{"baseline": {"raw": 0.2, "value": 0.2}}', '{"eligible": true}'),
                (?, 's2', -0.6, -0.6, 0.8, -0.60, -0.30, 0.80, 0.8, 0.0, '{}', '{}'),
                (?, 's3', -0.4, -0.4, 0.7, -0.40, -0.20, 0.70, 0.7, 0.0, '{}', '{}'),
                (?, 's4', -0.2, -0.2, 0.6, -0.20, -0.10, 0.60, 0.6, 0.0, '{}', '{}'),
                (?, 's5', 0.0, 0.0, 0.5, 0.00, 0.00, 0.50, 0.5, 0.0, '{}', '{}'),
                (?, 's6', 0.1, 0.1, 0.5, 0.10, 0.05, 0.50, 0.5, 0.0, '{}', '{}'),
                (?, 's7', 0.3, 0.3, 0.5, 0.30, 0.15, 0.50, 0.5, 0.0, '{}', '{}'),
                (?, 's8', -0.5, -0.5, 0.7, -0.50, -0.25, 0.70, 0.7, 0.0, '{}', '{}')
            """,
            (MODEL_ID,) * 8,
        )
        connection.execute(
            """
            INSERT INTO model_scene_neighbor(
                model_id, scene_id, neighbor_scene_id, similarity, weight, outcome, rank
            ) VALUES (?, 's1', 's2', 0.45, 0.5, 0.1, 0),
                     (?, 's1', 's3', 0.30, 0.5, 0.05, 1)
            """,
            (MODEL_ID, MODEL_ID),
        )
        connection.execute(
            """
            INSERT INTO exclusion(
                exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms,
                reversed_at_ms, expires_at_ms
            ) VALUES ('ex-s3', 'scene', 's3', 'hard', 1, NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO feedback(
                feedback_id, scene_id, feedback_type, value, occurred_at_ms, payload_json
            ) VALUES ('fb-s4', 's4', 'thumb_down', NULL, 1, '{}')
            """
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def score_review_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("score-review-sidecar") / "curator.sqlite3"
    make_score_review_sidecar(path)
    return path


def assert_score_review_identical(
    binary: Path, raw: bytes, same_path: Path, *, normalize: tuple[str, ...] = ()
) -> None:
    """Run both backends on fresh sidecar copies and compare stdout with the
    tolerance comparator (structure exact, floats within rel 1e-9)."""
    assert_slice3_identical(binary, raw, same_path, normalize=normalize)


# ── get_score_review ────────────────────────────────────────────────────────


def test_score_review_default_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    # Defaults: page 1, count 20, max_appeal 0. Eligible tail is s1 (-0.9),
    # s2 (-0.6), s4 (-0.2), s5 (0.0) — s3 hard-excluded, s8 no file; s4's
    # current thumb_down does NOT exclude on the review surface.
    raw = payload("get_score_review", score_review_sidecar, stub_stash)
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_paging_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    raw = payload(
        "get_score_review", score_review_sidecar, stub_stash, page=2, count=2, max_appeal=0.0
    )
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_max_appeal_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    raw = payload(
        "get_score_review", score_review_sidecar, stub_stash, page=1, count=5, max_appeal=-0.4
    )
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_empty_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    raw = payload(
        "get_score_review", score_review_sidecar, stub_stash, page=3, count=2, max_appeal=0.0
    )
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_validation_errors_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    # page/count outside 1..500 error; zero is coerced by the Python `or`
    # fallback on both sides (see test_score_review_zero_args_coerced).
    assert_score_review_identical(
        binary,
        payload("get_score_review", score_review_sidecar, stub_stash, page=-1),
        score_review_sidecar,
    )
    assert_score_review_identical(
        binary,
        payload("get_score_review", score_review_sidecar, stub_stash, count=-1),
        score_review_sidecar,
    )
    assert_score_review_identical(
        binary,
        payload("get_score_review", score_review_sidecar, stub_stash, count=501),
        score_review_sidecar,
    )


def test_score_review_zero_args_coerced_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    """page=0 and count=0 fall back to 1 / the config page_size on both
    implementations (mirroring get_slate's arg coercion)."""
    raw = payload(
        "get_score_review", score_review_sidecar, stub_stash, page=0, count=0, max_appeal=0.0
    )
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_desc_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    # order=desc: the same window (appeal <= 0) ranked most-appealing first.
    raw = payload("get_score_review", score_review_sidecar, stub_stash, order="desc")
    assert_score_review_identical(binary, raw, score_review_sidecar, normalize=("impression_id",))


def test_score_review_invalid_order_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    # Any order other than asc/desc errors identically on both backends
    # (no impression is recorded on the error path).
    raw = payload("get_score_review", score_review_sidecar, stub_stash, order="sideways")
    assert_score_review_identical(binary, raw, score_review_sidecar)


def test_score_review_requires_model_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str
) -> None:
    bare = tmp_path / "bare.sqlite3"
    make_sidecar(bare, with_jobs=True)  # migrated, but no published model
    raw = payload("get_score_review", bare, stub_stash)
    assert_score_review_identical(binary, raw, bare)


def test_score_review_write_state_parity(
    tmp_path: Path, binary: Path, stub_stash: str, score_review_sidecar: Path
) -> None:
    """get_score_review's read-path write (the "score_review" impression
    rows) leaves identical sidecar state on both implementations; only the
    requested_at_ms timestamp and the uuid4 impression_id may differ."""
    from tests.core.test_backend_slice1 import _run_once_on_copy

    raw = payload(
        "get_score_review", score_review_sidecar, stub_stash, page=1, count=2, max_appeal=0.0
    )
    python_db = _run_once_on_copy(None, PLUGIN_DIR, raw, score_review_sidecar)
    go_db = _run_once_on_copy(binary, PLUGIN_DIR, raw, score_review_sidecar)

    def impressions(path: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
        connection = sqlite3.connect(path)
        try:
            items = sorted(
                connection.execute(
                    """
                    SELECT impression_id, scene_id, position, policy_score, reason_snapshot_json
                    FROM impression_item WHERE impression_id IN (
                        SELECT impression_id FROM impression WHERE lane='score_review'
                    ) ORDER BY impression_id, position
                    """
                ).fetchall()
            )
            rows = connection.execute(
                "SELECT impression_id, lane, model_id, config_version, request_context_json"
                " FROM impression WHERE lane='score_review'"
            ).fetchall()
            return rows, items
        finally:
            connection.close()

    python_rows, python_items = impressions(python_db)
    go_rows, go_items = impressions(go_db)
    assert {row[0] for row in python_rows} == {row[0] for row in go_rows}
    assert len(go_rows) == 1
    assert len(go_items) == 2
    for python_row, go_row in zip(sorted(python_rows), sorted(go_rows), strict=True):
        # Everything except impression_id and requested_at_ms must match.
        assert python_row[1:] == go_row[1:]
        assert go_row[1] == "score_review"
        assert go_row[2] == MODEL_ID
    assert sorted((row[1], row[2], row[3], row[4]) for row in python_items) == sorted(
        (row[1], row[2], row[3], row[4]) for row in go_items
    )
    assert {row[3] for row in go_items} == {-0.9, -0.6}  # policy_score = appeal
    assert all(row[4] == '["eligibility.lane"]' for row in go_items)
