"""get_tag_questions: differential Go/Python coverage plus ranking semantics.

The sidecar extends the synthetic builder corpus with unwatched scenes so the
For You pool is large enough to rank tags by reach.
"""

from __future__ import annotations

import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.core import core_binary
from curator.model import PreferenceModelBuilder
from curator.ranking import SlateBuilder
from curator.storage import connect_database
from tests.core.test_backend import PLUGIN_DIR, _StubStash, payload, run_backend
from tests.core.test_backend_slice1 import assert_slice1_identical, make_model_sidecar
from tests.model.test_builder import REFERENCE_MS, _database

# (scene, tags): every extra scene carries "good" so it qualifies for For You.
# "wide" reaches most of the pool, "narrow" a few scenes, "single" one scene
# (below the minimum reach), "answered" carries a direct answer, and "generic"
# sits on at least 80% of the library.
EXTRA_SCENES = (
    ("q01", ("good", "wide", "generic")),
    ("q02", ("good", "wide", "generic")),
    ("q03", ("good", "wide", "narrow", "generic")),
    ("q04", ("good", "wide", "answered", "generic")),
    ("q05", ("good", "wide", "narrow", "generic")),
    ("q06", ("good", "wide", "answered", "generic")),
    ("q07", ("good", "wide", "generic")),
    ("q08", ("good", "narrow", "generic")),
    ("q09", ("good", "wide", "generic")),
    ("q10", ("good", "single", "generic")),
    ("q11", ("good", "wide", "generic")),
    ("q12", ("good", "wide", "generic")),
)
# Plus the base corpus's three good scenes, so "generic" covers 15 of 18 scenes.
GENERIC_BASE_SCENES = ("old-good", "recent-good", "unseen-good")


def make_tag_question_sidecar(path: Path) -> None:
    connection = _database(path)
    try:
        connection.executemany(
            "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
            (
                ("wide", "Wide Theme", "tw"),
                ("narrow", "Narrow Theme", "tn"),
                ("single", "Single Theme", "ts"),
                ("answered", "Answered Theme", "ta"),
                ("generic", "Generic Theme", "tgen"),
            ),
        )
        connection.executemany(
            "INSERT INTO source_scene(scene_id, title, studio_id, source_hash) VALUES (?, ?, ?, ?)",
            tuple((scene, scene.upper(), "studio-2", scene) for scene, _ in EXTRA_SCENES),
        )
        connection.executemany(
            "INSERT INTO source_file(file_id, scene_id, available, source_hash)"
            " VALUES (?, ?, 1, ?)",
            tuple((f"file-{scene}", scene, f"file-hash-{scene}") for scene, _ in EXTRA_SCENES),
        )
        connection.executemany(
            "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
            (
                *((scene, tag) for scene, tags in EXTRA_SCENES for tag in tags),
                *((scene, "generic") for scene in GENERIC_BASE_SCENES),
            ),
        )
        connection.executemany(
            "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, 0)",
            tuple(
                (scene, ("p1", "p2", "p3")[index % 3])
                for index, (scene, _) in enumerate(EXTRA_SCENES)
            ),
        )
        connection.execute(
            "INSERT INTO direct_tag_preference_history(preference_id, tag_id, value,"
            " occurred_at_ms) VALUES ('pref-answered', 'answered', 0.5, 1)"
        )
        connection.execute(
            "INSERT INTO direct_tag_preference(tag_id, preference_id, value, occurred_at_ms)"
            " VALUES ('answered', 'pref-answered', 0.5, 1)"
        )
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        connection.commit()
    finally:
        connection.close()


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


@pytest.fixture(scope="module")
def question_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("tag-questions") / "curator.sqlite3"
    make_tag_question_sidecar(path)
    return path


def _questions(path: Path, limit: int = 10) -> dict[str, object]:
    connection = connect_database(path)
    try:
        return CuratorAPI(connection).tag_questions(limit)
    finally:
        connection.close()


@pytest.mark.parametrize("limit", [1, 3, 10])
def test_tag_questions_match_across_backends(
    binary: Path, stub_stash: str, question_sidecar: Path, limit: int
) -> None:
    raw = payload("get_tag_questions", question_sidecar, stub_stash, limit=limit)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, question_sidecar)


@pytest.mark.parametrize("limit", [0, -1, 11])
def test_tag_questions_limit_errors_match(
    binary: Path, stub_stash: str, question_sidecar: Path, limit: int
) -> None:
    raw = payload("get_tag_questions", question_sidecar, stub_stash, limit=limit)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, question_sidecar)


def test_tag_questions_without_model_match(binary: Path, stub_stash: str, tmp_path: Path) -> None:
    sidecar = tmp_path / "nomodel.sqlite3"
    _database(sidecar).close()
    raw = payload("get_tag_questions", sidecar, stub_stash, limit=5)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, sidecar)
    result = run_backend(binary, PLUGIN_DIR, raw)
    assert "no published model" in result.stdout.decode()


def test_tag_questions_small_pool_matches(binary: Path, stub_stash: str, tmp_path: Path) -> None:
    sidecar = tmp_path / "small.sqlite3"
    make_model_sidecar(sidecar)
    raw = payload("get_tag_questions", sidecar, stub_stash, limit=5)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, sidecar)


def test_tag_questions_rank_by_reach_and_skip_ineligible_tags(question_sidecar: Path) -> None:
    connection = connect_database(question_sidecar)
    try:
        pool = [
            item.scene_id
            for item in SlateBuilder(connection, diversity_enabled=True)
            .recommend("for_you", 300)
            .items
        ]
    finally:
        connection.close()
    result = _questions(question_sidecar)
    assert result["pool_size"] == len(pool)
    items = result["items"]
    assert isinstance(items, list)
    names = [item["tag_id"] for item in items]
    # Answered, generic (16 of 18 scenes carry "good", 15 "generic") and
    # single-scene tags are never asked about; "wide" covers most of the pool.
    assert names[0] == "wide"
    for retired in ("answered", "generic", "good", "single"):
        assert retired not in names
    values = [float(item["value"]) for item in items]
    assert values == sorted(values, reverse=True)
    for item in items:
        assert 0 < float(item["reach"]) <= 1
        assert float(item["value"]) == pytest.approx(float(item["reach"]) * float(item["leverage"]))
        # Examples are pool scenes, highest-ranked first.
        examples = item["examples"]
        assert 2 <= len(examples) <= 3
        assert examples == sorted(examples, key=pool.index)


def test_tag_question_leverage_falls_with_support(question_sidecar: Path) -> None:
    """More learned support means an answer controls less of the blend."""
    items = _questions(question_sidecar)["items"]
    assert isinstance(items, list)
    for item in items:
        assert float(item["leverage"]) == pytest.approx(8.0 / (float(item["support"]) + 8.0))
