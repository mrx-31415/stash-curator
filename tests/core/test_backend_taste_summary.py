"""get_taste_summary: Go/Python parity plus the summary's window semantics.

The model sidecar gains a play history after its build: an older run of
"good" scenes, a recent run of "unusual" ones, and one scene replayed after a
long gap, unwatched "bad" scenes, and Why these? answers. Synthetic sidecars
only.
"""

from __future__ import annotations

import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from curator.storage import connect_database
from curator.taste_summary import taste_summary
from tests.core.test_backend import PLUGIN_DIR, _StubStash, payload
from tests.core.test_backend_slice1 import assert_slice1_identical, make_model_sidecar
from tests.model.test_builder import DAY_MS, REFERENCE_MS

OLDER = tuple(f"x{index:02d}" for index in range(1, 7))
RECENT = tuple(f"x{index:02d}" for index in range(7, 13))
UNWATCHED = tuple(f"y{index:02d}" for index in range(1, 5))
ANCHOR_MS = REFERENCE_MS + 305 * DAY_MS


def make_taste_sidecar(path: Path) -> None:
    make_model_sidecar(path)
    connection = connect_database(path)
    try:
        with connection:
            connection.executemany(
                "INSERT INTO source_scene(scene_id, title, studio_id, source_hash)"
                " VALUES (?, ?, 'studio-2', ?)",
                tuple((scene, scene.upper(), scene) for scene in (*OLDER, *RECENT, *UNWATCHED)),
            )
            connection.executemany(
                "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
                (
                    *((scene, "good") for scene in OLDER),
                    *((scene, "unusual") for scene in RECENT),
                    *((scene, "bad") for scene in UNWATCHED),
                ),
            )
            connection.executemany(
                "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, 0)",
                (
                    *(
                        (scene, REFERENCE_MS + (10 + index) * DAY_MS)
                        for index, scene in enumerate(OLDER)
                    ),
                    *((scene, ANCHOR_MS - index * DAY_MS) for index, scene in enumerate(RECENT)),
                    # x01 again, 292 days after its first play.
                    ("x01", REFERENCE_MS + 302 * DAY_MS),
                ),
            )
            connection.executemany(
                "INSERT INTO scene_reason_answer(answer_id, scene_id, polarity, occurred_at_ms)"
                " VALUES (?, ?, ?, 1)",
                (("a1", "x07", 1), ("a2", "x02", -1), ("a3", "x08", 1)),
            )
            connection.executemany(
                "INSERT INTO scene_reason(answer_id, subject_type, subject_id) VALUES (?, ?, ?)",
                (
                    ("a1", "tag", "unusual"),
                    ("a1", "performer", "p1"),
                    ("a2", "missing_tag", "bad"),
                    ("a3", "tag", "unusual"),
                    ("a3", "scene", ""),
                ),
            )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


@pytest.fixture(scope="module")
def sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("taste-summary") / "curator.sqlite3"
    make_taste_sidecar(path)
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubStash)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_taste_summary_windows_shift_and_counts(sidecar: Path) -> None:
    connection = connect_database(sidecar)
    try:
        summary = taste_summary(connection)
    finally:
        connection.close()

    totals = summary["totals"]
    assert totals["as_of_ms"] == ANCHOR_MS
    assert totals["scenes_played"] == 15
    assert summary["windows"][-1]["end_ms"] == ANCHOR_MS
    assert summary["windows"][-1]["scenes"] == 7  # six recent scenes plus x01's return
    good = next(item for item in summary["likes"] if item["tag_id"] == "good")
    assert len(good["trend"]) == len(summary["windows"])
    assert good["trend"][-1] is not None

    assert [item["tag_id"] for item in summary["shift"]["rising"]] == ["unusual"]
    assert [item["tag_id"] for item in summary["shift"]["fading"]] == ["good"]

    assert summary["rediscovered"] == [
        {
            "scene_id": "x01",
            "plays": 2,
            "returns": 1,
            "longest_gap_ms": 292 * DAY_MS,
            "last_played_at_ms": REFERENCE_MS + 302 * DAY_MS,
            "title": "X01",
        }
    ]

    # "unusual" and "good" are each on a bigger share of watched scenes than of
    # the library; "bad" is on five library scenes and one watched one.
    apart = summary["apart"]
    assert [item["tag_id"] for item in apart["more"]] == ["unusual", "good"]
    assert [item["tag_id"] for item in apart["passed"]] == ["bad"]
    assert apart["passed"][0]["watched_share"] == 1 / 15
    assert apart["passed"][0]["library_share"] == 5 / 22

    hits = [
        (item["subject_type"], item["subject_id"], item["answers"])
        for item in summary["reasons"]["hits"]
    ]
    assert hits == [("tag", "unusual", 2), ("performer", "p1", 1)]
    assert summary["reasons"]["misses"][0]["subject_id"] == "bad"


def test_taste_summary_backends_match(sidecar: Path, stub_stash: str) -> None:
    binary = core_binary()
    if binary is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    raw = payload("get_taste_summary", sidecar, stub_stash)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, sidecar)
