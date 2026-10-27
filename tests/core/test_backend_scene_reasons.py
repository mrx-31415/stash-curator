"""Why these? ops: differential Go/Python coverage plus queue semantics.

get_scene_reason_candidates and submit_scene_reasons run through the Go binary
and plugin/backend.py on fresh copies of a synthetic sidecar; output and the
mutated sidecar state must match. Synthetic sidecars only.
"""

from __future__ import annotations

import sqlite3
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.core import core_binary
from curator.storage import connect_database
from tests.core.test_backend import payload
from tests.core.test_backend_slice3_backups import assert_slice3_identical
from tests.core.test_backend_slice3_writes import _StubWrites, make_writes_sidecar


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


@pytest.fixture(scope="module")
def reasons_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Scores s1 -0.30, s2 -0.10, s3 0.20; s1 and s3 have been played."""
    path = tmp_path_factory.mktemp("scene-reasons") / "curator.sqlite3"
    make_writes_sidecar(path)
    connection = sqlite3.connect(path)
    try:
        connection.executemany(
            "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, 0)",
            [("s1", 10), ("s3", 20)],
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _candidates(sidecar: Path, mode: str, **kwargs: object) -> list[str]:
    connection = connect_database(sidecar, attach_artifacts=False)
    try:
        result = CuratorAPI(connection).scene_reason_candidates(mode, **kwargs)
    finally:
        connection.close()
    return [str(item["scene_id"]) for item in result["items"]]


@pytest.mark.parametrize(
    "args",
    [
        {"mode": "hits"},
        {"mode": "misses", "limit": 2},
        {"mode": "hits", "exclude_scene_ids": ["s3"]},
        {"mode": "sideways"},
        {"mode": "hits", "limit": 51},
        {"mode": "hits", "exclude_scene_ids": "s3"},
    ],
)
def test_scene_reason_candidates_match(
    binary: Path, stub_stash: str, reasons_sidecar: Path, args: dict[str, object]
) -> None:
    raw = payload("get_scene_reason_candidates", reasons_sidecar, stub_stash, **args)
    assert_slice3_identical(binary, raw, reasons_sidecar)


def test_scene_reason_candidates_rank_played_hits_and_all_misses(reasons_sidecar: Path) -> None:
    assert _candidates(reasons_sidecar, "hits") == ["s3", "s1"]
    assert _candidates(reasons_sidecar, "misses") == ["s1", "s2", "s3"]
    assert _candidates(reasons_sidecar, "misses", exclude_scene_ids={"s1"}) == ["s2", "s3"]


VALID_ANSWERS = [
    {
        "answer_id": "a1",
        "scene_id": "s3",
        "polarity": 1,
        "reasons": [
            {"subject_type": "tag", "subject_id": "t1"},
            {"subject_type": "missing_tag", "subject_id": "t2"},
            {"subject_type": "scene", "subject_id": "ignored"},
        ],
        "occurred_at_ms": 100,
    },
    {
        "answer_id": "a2",
        "scene_id": "s1",
        "polarity": -1,
        "flipped": True,
        "reasons": [],
        "occurred_at_ms": 200,
    },
]


def test_submit_scene_reasons_match(binary: Path, stub_stash: str, reasons_sidecar: Path) -> None:
    raw = payload("submit_scene_reasons", reasons_sidecar, stub_stash, entries=VALID_ANSWERS)
    assert_slice3_identical(binary, raw, reasons_sidecar)


def _answer(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "answer_id": "bad",
        "scene_id": "s2",
        "polarity": 1,
        "reasons": [{"subject_type": "performer", "subject_id": "p1"}],
        "occurred_at_ms": 5,
    }
    return {**base, **changes}


@pytest.mark.parametrize(
    "entries",
    [
        "not-a-list",
        [_answer(answer_id="")],
        [_answer(polarity=0)],
        [_answer(polarity=True)],
        [_answer(polarity=1.0)],
        [_answer(reasons="tag")],
        [_answer(reasons=[{"subject_type": "tag"}] * 21)],
        [_answer(reasons=["tag"])],
        [_answer(reasons=[{"subject_type": "mood", "subject_id": "x"}])],
        [_answer(reasons=[{"subject_type": "tag", "subject_id": ""}])],
        [_answer(reasons=[])],
        [_answer(scene_id="missing")],
    ],
)
def test_submit_scene_reasons_errors_match(
    binary: Path, stub_stash: str, reasons_sidecar: Path, entries: object
) -> None:
    raw = payload("submit_scene_reasons", reasons_sidecar, stub_stash, entries=entries)
    assert_slice3_identical(binary, raw, reasons_sidecar)


def test_answered_scenes_leave_the_queue_and_retries_are_ignored(tmp_path: Path) -> None:
    sidecar = tmp_path / "curator.sqlite3"
    make_writes_sidecar(sidecar)
    connection = connect_database(sidecar, attach_artifacts=False)
    try:
        connection.execute(
            "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s3', 1, 0)"
        )
        connection.commit()
        api = CuratorAPI(connection)
        generation = connection.execute(
            "SELECT requested_generation FROM model_update_state"
        ).fetchone()[0]
        assert api.submit_scene_reasons(VALID_ANSWERS)["accepted"] == 2
        assert api.submit_scene_reasons(VALID_ANSWERS)["accepted"] == 0
        assert (
            connection.execute("SELECT requested_generation FROM model_update_state").fetchone()[0]
            == generation + 1
        )
        rows = connection.execute(
            "SELECT answer_id, subject_type, subject_id FROM scene_reason ORDER BY 1, 2"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("a1", "missing_tag", "t2"),
            ("a1", "scene", ""),
            ("a1", "tag", "t1"),
        ]
        assert api.scene_reason_candidates("hits")["items"] == []
        assert [item["scene_id"] for item in api.scene_reason_candidates("misses")["items"]] == [
            "s2"
        ]
    finally:
        connection.close()
