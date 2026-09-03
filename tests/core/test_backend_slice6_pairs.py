"""Slice-6 backend differential harness: the pairwise picks ops.

get_curation_picks, submit_curation_picks, and get_curation_pair_verdict run
through the Go binary and plugin/backend.py on fresh sidecar copies; stdout
must be byte-identical per the tolerance policy (structure exact, floats
within rel 1e-9). round_id and pair_id are generated per run (uuid4) and
normalized away before comparison.

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
from tests.core.curation_fixtures import make_slice5_sidecar
from tests.core.test_backend import payload
from tests.core.test_backend_slice3_backups import assert_slice3_identical

ROUND_TAG = "round-tag"
ROUND_PERF = "round-perf"
ROUND_ORTH = "round-orth"
ROUND_STUDIO = "round-studio"


class _StubSlice6(BaseHTTPRequestHandler):
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
    server = HTTPServer(("127.0.0.1", 0), _StubSlice6)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_slice6_sidecar(path: Path) -> None:
    """The curation sidecar plus performers and fixture pick rounds."""
    make_slice5_sidecar(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_performer(performer_id, name, source_hash, updated_at)
            VALUES ('p1', 'Performer One', 'ph-1', '2026-01-01T00:00:00Z'),
                   ('p2', 'Performer Two', 'ph-2', '2026-01-01T00:00:00Z'),
                   ('p3', 'Performer Three', 'ph-3', '2026-01-01T00:00:00Z'),
                   ('p4', 'Performer Four', 'ph-4', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO scene_performer(scene_id, performer_id, position) VALUES
                ('s1', 'p1', 0), ('s1', 'p2', 1),
                ('s2', 'p3', 0),
                ('s3', 'p2', 0),
                ('s4', 'p1', 0),
                ('s7', 'p3', 0),
                ('s8', 'p1', 0), ('s8', 'p2', 1)
            """
        )
        # s21: 3 performers, tagged lesbian (t1) but NOT threesome (t2). A
        # 3-performer scene is likely an untagged threesome, so it must be
        # excluded from the L&!T cell (cell hygiene).
        connection.execute(
            "INSERT INTO source_scene(scene_id, studio_id, title, updated_at, source_hash) "
            "VALUES ('s21', NULL, 'Twenty One', '2026-01-01T00:00:00Z', 'h21')"
        )
        connection.execute("INSERT INTO scene_tag(scene_id, tag_id) VALUES ('s21', 't1')")
        connection.execute(
            "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES "
            "('s21', 'p2', 0), ('s21', 'p3', 1), ('s21', 'p4', 2)"
        )
        # Tag-dimension round: pairs across the contrast cells (t1 lesbian,
        # t2 threesome). s1/s7 are L&T, s2 is L&!T, s4 is !L&T.
        connection.execute(
            """
            INSERT INTO curation_pair(pair_id, round_id, scene_a, scene_b, dimension,
                selection_probability, status, winner, occurred_at_ms, payload_json)
            VALUES
                ('pt1', ?, 's1', 's2', 'tag', 0.4, 'answered', 'a', 1,
                 '{"dimension": "tag", "predicted_a": 0.3, "predicted_b": 0.1,
                   "base_tag_id": "t1", "context_tag_id": "t2"}'),
                ('pt2', ?, 's7', 's2', 'tag', 0.3, 'answered', 'b', 1,
                 '{"dimension": "tag", "predicted_a": 0.2, "predicted_b": 0.0,
                   "base_tag_id": "t1", "context_tag_id": "t2"}'),
                ('pt3', ?, 's1', 's4', 'tag', 0.3, 'answered', 'a', 1,
                 '{"dimension": "tag", "predicted_a": 0.3, "predicted_b": 0.2,
                   "base_tag_id": "t1", "context_tag_id": "t2"}'),
                ('po1', ?, 's1', 's2', 'tag', 0.5, 'open', NULL, NULL,
                 '{"dimension": "tag", "predicted_a": 0.3, "predicted_b": 0.1,
                   "base_tag_id": "t1", "context_tag_id": "t2"}')
            """,
            (ROUND_TAG,) * 4,
        )
        # Performer-dimension round (performer_id p1) and an open round for
        # submit tests.
        connection.execute(
            """
            INSERT INTO curation_pair(pair_id, round_id, scene_a, scene_b, dimension,
                selection_probability, status, winner, occurred_at_ms, payload_json)
            VALUES
                ('pp1', ?, 's1', 's2', 'performer', 0.5, 'answered', 'a', 1,
                 '{"dimension": "performer", "predicted_a": 0.3, "predicted_b": 0.1,
                   "performer_id": "p1"}'),
                ('pp2', ?, 's3', 's1', 'performer', 0.5, 'answered', 'b', 1,
                 '{"dimension": "performer", "predicted_a": 0.0, "predicted_b": 0.3,
                   "performer_id": "p1"}'),
                ('ps1', ?, 's1', 's4', 'performer', 0.4, 'open', NULL, NULL, '{}')
            """,
            (ROUND_PERF,) * 3,
        )
        # Orthogonal round.
        connection.execute(
            """
            INSERT INTO curation_pair(pair_id, round_id, scene_a, scene_b, dimension,
                selection_probability, status, winner, occurred_at_ms, payload_json)
            VALUES
                ('px1', ?, 's1', 's2', 'orthogonal', 0.5, 'answered', 'a', 1,
                 '{"dimension": "orthogonal", "predicted_a": 0.3, "predicted_b": 0.1}'),
                ('px2', ?, 's7', 's8', 'orthogonal', 0.5, 'answered', 'b', 1,
                 '{"dimension": "orthogonal", "predicted_a": 0.2, "predicted_b": 0.1}')
            """,
            (ROUND_ORTH,) * 2,
        )
        # Studio round.
        connection.execute(
            """
            INSERT INTO curation_pair(pair_id, round_id, scene_a, scene_b, dimension,
                selection_probability, status, winner, occurred_at_ms, payload_json)
            VALUES
                ('pu1', ?, 's1', 's2', 'studio', 0.5, 'answered', 'a', 1,
                 '{"dimension": "studio", "predicted_a": 0.3, "predicted_b": 0.1}'),
                ('pu2', ?, 's3', 's4', 'studio', 0.5, 'answered', 'b', 1,
                 '{"dimension": "studio", "predicted_a": 0.0, "predicted_b": 0.2}')
            """,
            (ROUND_STUDIO,) * 2,
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def slice6_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("slice6-sidecar") / "curator.sqlite3"
    make_slice6_sidecar(path)
    return path


def assert_slice6_identical(
    binary: Path, raw: bytes, same_path: Path, *, normalize: tuple[str, ...] = ()
) -> None:
    assert_slice3_identical(binary, raw, same_path, normalize=normalize)


# ── get_curation_picks ───────────────────────────────────────────────────────


def _fresh_selection_sidecar(slice6_sidecar: Path, tmp_path: Path) -> Path:
    """A copy with the fixture rounds removed, so selection pools are clean."""
    copy = tmp_path / "curator.sqlite3"
    copy.write_bytes(slice6_sidecar.read_bytes())
    connection = sqlite3.connect(copy)
    try:
        connection.execute("DELETE FROM curation_pair")
        connection.commit()
    finally:
        connection.close()
    return copy


def test_curation_picks_tag_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path, tmp_path: Path
) -> None:
    sidecar = _fresh_selection_sidecar(slice6_sidecar, tmp_path)
    raw = payload(
        "get_curation_picks",
        sidecar,
        stub_stash,
        dimension="tag",
        budget=4,
        base_tag_id="t1",
        context_tag_id="t2",
    )
    assert_slice6_identical(binary, raw, sidecar, normalize=("round_id", "pair_id"))


def test_curation_picks_dimensions_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path, tmp_path: Path
) -> None:
    sidecar = _fresh_selection_sidecar(slice6_sidecar, tmp_path)
    for extra in (
        {"dimension": "performer", "budget": 4, "performer_id": "p1"},
        {"dimension": "studio", "budget": 4},
        {"dimension": "orthogonal", "budget": 4},
        {"dimension": "tag", "budget": 4},
    ):
        raw = payload("get_curation_picks", sidecar, stub_stash, **extra)
        assert_slice6_identical(binary, raw, sidecar, normalize=("round_id", "pair_id"))


def test_curation_picks_error_paths(binary: Path, stub_stash: str, slice6_sidecar: Path) -> None:
    for extra in (
        {"dimension": "nope", "budget": 4},
        {"dimension": "tag", "budget": 3},
        {"dimension": "tag", "budget": 21},
        {"dimension": "tag", "base_tag_id": "t9", "context_tag_id": "t2", "budget": 4},
        {"dimension": "performer", "performer_id": "p9", "budget": 4},
    ):
        raw = payload("get_curation_picks", slice6_sidecar, stub_stash, **extra)
        assert_slice6_identical(binary, raw, slice6_sidecar)


# ── submit_curation_picks ────────────────────────────────────────────────────


def test_submit_curation_picks_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    raw = payload(
        "submit_curation_picks",
        slice6_sidecar,
        stub_stash,
        round_id=ROUND_TAG,
        picks=[
            {"pair_id": "po1", "winner": "a"},
            {"pair_id": "pt1", "winner": "skip"},
            {"pair_id": "pt2", "winner": "flag", "scene": "b"},
        ],
    )
    assert_slice6_identical(binary, raw, slice6_sidecar)


def test_submit_curation_picks_tie_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    """A tie answers the pair with no winner and writes neutral labels for both
    scenes; ELO stays untouched. ps1 is the open pair of the performer round."""
    raw = payload(
        "submit_curation_picks",
        slice6_sidecar,
        stub_stash,
        round_id=ROUND_PERF,
        picks=[{"pair_id": "ps1", "winner": "tie"}],
    )
    assert_slice6_identical(binary, raw, slice6_sidecar)


def test_submit_curation_picks_error_paths(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    cases = [
        ("nope", [{"pair_id": "po1", "winner": "a"}]),
        (ROUND_TAG, [{"pair_id": "px9", "winner": "a"}]),
        (ROUND_TAG, [{"pair_id": "po1", "winner": "a"}, {"pair_id": "po1", "winner": "b"}]),
        (ROUND_TAG, [{"pair_id": "pt1", "winner": "a"}]),  # already answered
        (ROUND_TAG, [{"pair_id": "po1", "winner": "x"}]),
        (ROUND_TAG, [{"pair_id": "po1", "winner": "flag"}]),  # flag needs a scene
        (ROUND_TAG, []),
    ]
    for round_id, picks in cases:
        raw = payload(
            "submit_curation_picks",
            slice6_sidecar,
            stub_stash,
            round_id=round_id,
            picks=picks,
        )
        assert_slice6_identical(binary, raw, slice6_sidecar)


def test_submit_impact_correction_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    """The correction op writes a direct scene signal (and supersedes an
    earlier correction) identically in both backends, and validates its inputs
    with matching error messages."""
    for scene_id, direction in (("s5", "up"), ("s5", "down"), ("", "up"), ("s5", "sideways")):
        raw = payload(
            "submit_impact_correction",
            slice6_sidecar,
            stub_stash,
            scene_id=scene_id,
            direction=direction,
        )
        assert_slice6_identical(binary, raw, slice6_sidecar)


# ── get_curation_pair_verdict ────────────────────────────────────────────────


# ── get_curation_pair_verdict ────────────────────────────────────────────────


def test_curation_pair_verdict_dimensions_byte_identical(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    for round_id in (ROUND_TAG, ROUND_PERF, ROUND_ORTH, ROUND_STUDIO):
        raw = payload("get_curation_pair_verdict", slice6_sidecar, stub_stash, round_id=round_id)
        assert_slice6_identical(binary, raw, slice6_sidecar)


def test_curation_pair_verdict_error_paths(
    binary: Path, stub_stash: str, slice6_sidecar: Path
) -> None:
    for round_id in ("nope", ""):
        raw = payload("get_curation_pair_verdict", slice6_sidecar, stub_stash, round_id=round_id)
        assert_slice6_identical(binary, raw, slice6_sidecar)


# ── model build with pair labels ─────────────────────────────────────────────


def test_model_build_with_pair_labels_identical(binary: Path, tmp_path: Path) -> None:
    """The pair winner/loser labels (outcome +1/-1, surprise/IPS confidence)
    must produce the same model digest and artifact in both implementations."""
    from tests.core.compare import artifact_tolerant_diff
    from tests.core.test_backend_slice3_featurebuild import make_feature_sidecar
    from tests.core.test_backend_slice3_modelbuild import _run_go_build, _run_python_build

    path = tmp_path / "curator.sqlite3"
    make_feature_sidecar(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                occurred_at_ms, payload_json)
            VALUES ('cpw-1', 'unseen-good', 'curation_pair_winner', '10', 1,
                    '{"pair_id": "p1", "round_id": "r1", "dimension": "tag",
                      "predicted_winner": 0.1, "predicted_loser": 0.3,
                      "selection_probability": 0.4}'),
                   ('cpl-1', 'unlabeled', 'curation_pair_loser', '0', 1,
                    '{"pair_id": "p1", "round_id": "r1", "dimension": "tag",
                      "predicted_winner": 0.1, "predicted_loser": 0.3,
                      "selection_probability": 0.4}')
            """
        )
        connection.commit()
    finally:
        connection.close()
    py_id, py_artifact = _run_python_build(path)
    go_id, go_artifact = _run_go_build(binary, path)
    assert py_id == go_id
    assert artifact_tolerant_diff(go_artifact, py_artifact) == ""
