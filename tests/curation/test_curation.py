"""Unit tests for the curation batch selection and verdict semantics.

The differential suite (test_backend_slice5_curation.py) proves Go/Python
parity; these tests pin the deterministic semantics the ops implement:
allocation, exclusions, anchors, category filtering, attribution, and
verdict math.

The shared slice5 sidecar carries curation_rating rows that are also model
labels (every rating feeds the model; the batch payload only gates verdict
attribution), so selection tests run on a clean copy with those rows removed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from curator.curation import (
    create_batch,
    curation_context,
    tag_context_candidates,
    verdict,
)
from tests.core.test_backend_slice5_curation import (
    BATCH_E,
    BATCH_V,
    BATCH_X,
    make_slice5_sidecar,
)


@pytest.fixture(scope="module")
def sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("curation-unit") / "curator.sqlite3"
    make_slice5_sidecar(path)
    return path


@pytest.fixture(scope="module")
def selection_sidecar(sidecar: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy without curation_rating rows, so no pool scene is labeled."""
    path = tmp_path_factory.mktemp("curation-selection") / "curator.sqlite3"
    path.write_bytes(sidecar.read_bytes())
    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM feedback WHERE feedback_type='curation_rating'")
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture()
def conn(selection_sidecar: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(selection_sidecar)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture()
def rated_conn(sidecar: Path) -> sqlite3.Connection:
    """The original sidecar, which carries curation_rating label rows."""
    connection = sqlite3.connect(sidecar)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def _scenes_by_cell(batch: dict[str, object]) -> dict[str, set[str]]:
    cells: dict[str, set[str]] = {}
    for item in batch["items"]:  # type: ignore[union-attr]
        assert isinstance(item, dict)
        cells.setdefault(str(item["cell"]), set()).add(str(item["scene_id"]))
    return cells


def test_hypothesis_allocation_exclusions_and_anchors(conn: sqlite3.Connection) -> None:
    batch = create_batch(conn, "hypothesis", "t1", "t2", 20)
    cells = _scenes_by_cell(batch)
    # Pools: L&T {s1,s7}, L&!T {s2} (s3 labeled -> excluded), !L&T {s4,s8},
    # !L&!T {s6} (s5 blocked -> excluded). Budget 20 -> 7/7/3 + 3 anchors, all
    # quotas exceed the pools, so every pool scene is taken exactly once.
    assert cells["L&T"] == {"s1", "s7"}
    assert cells["L&!T"] == {"s2"}
    assert cells["!L&T"] == {"s4", "s8"}
    assert len(cells["anchor"]) == 3
    assert cells["anchor"] <= {
        "s6",
        "s9",
        "s10",
        "s11",
        "s12",
        "s13",
        "s14",
        "s15",
        "s16",
        "s17",
        "s18",
        "s19",
        "s20",
    }
    assert batch["budget"] == 20
    assert batch["pool"] == {"L&T": 2, "L&!T": 1, "!L&T": 2, "!L&!T": 13}
    # The labeled and blocked scenes never appear.
    all_scenes = set().union(*cells.values())
    assert "s3" not in all_scenes
    assert "s5" not in all_scenes
    # Anchors are marked and sit in the !L&!T pool (the scale-calibration band).
    anchors = [i for i in batch["items"] if i["anchor"] is True]  # type: ignore[union-attr]
    assert len(anchors) == 3
    assert all(a["cell"] == "anchor" for a in anchors)


def test_hypothesis_round_robin_splits_studios(conn: sqlite3.Connection) -> None:
    # A large budget still cannot repeat a studio while untapped studios exist:
    # L&T = {s1(st1), s7(st1)} has one studio, so both are taken; !L&T =
    # {s4(st1), s8(st2)} gets one scene per studio in the first pass.
    batch = create_batch(conn, "hypothesis", "t1", "t2", 40)
    cells = _scenes_by_cell(batch)
    assert cells["!L&T"] == {"s4", "s8"}


def test_explore_anchors_are_disjoint_and_pool_bounded(conn: sqlite3.Connection) -> None:
    batch = create_batch(conn, "explore", None, None, 10)
    cells = _scenes_by_cell(batch)
    explore = cells.get("explore", set())
    anchors = cells.get("anchor", set())
    assert explore.isdisjoint(anchors)
    # s1 (t1,t2) + s2 (t1,t3) cover every interactive tag, so the greedy stops
    # once no scene adds new coverage; 3 anchors come from the remaining pool.
    assert explore == {"s1", "s2"}
    assert len(anchors) == 3
    assert anchors <= {
        "s4",
        "s6",
        "s7",
        "s8",
        "s9",
        "s10",
        "s11",
        "s12",
        "s13",
        "s14",
        "s15",
        "s16",
        "s17",
        "s18",
        "s19",
        "s20",
    }
    assert batch["pool"]["candidates"] == 18


def test_category_filter_excludes_appearance_tags(conn: sqlite3.Connection) -> None:
    context = curation_context(conn)
    assert context.is_interactive("t1")  # Group Makeup
    assert context.is_interactive("t2")  # Group Makeup
    assert context.is_interactive("t3")  # Acts
    assert not context.is_interactive("t4")  # Hair Color -> excluded


def test_item_tags_exclude_appearance_category(conn: sqlite3.Connection) -> None:
    # Give s6 an appearance tag (red hair, Hair Color) and confirm the batch
    # response never surfaces it in the item tag profile.
    conn.execute("INSERT INTO scene_tag(scene_id, tag_id) VALUES ('s6', 't4')")
    conn.commit()
    batch = create_batch(conn, "explore", None, None, 10)
    for item in batch["items"]:  # type: ignore[union-attr]
        assert all(str(t["tag_id"]) != "t4" for t in item["tags"])


def test_verdict_hypothesis_math_and_attribution(rated_conn: sqlite3.Connection) -> None:
    result = verdict(rated_conn, BATCH_V)
    assert result["mode"] == "hypothesis"
    cells = {str(c["cell"]): c for c in result["cells"]}  # type: ignore[union-attr]
    assert cells["L&T"]["n"] == 1
    assert cells["L&T"]["mean_outcome"] == pytest.approx(0.6)
    assert cells["L&!T"]["n"] == 1
    assert cells["L&!T"]["mean_outcome"] == pytest.approx(-0.6)
    # fb-o1 belongs to another batch and must not leak into L&T.
    assert cells["L&T"]["n"] == 1
    contrast = result["contrast"]  # type: ignore[union-attr]
    assert contrast["delta"] == pytest.approx(1.2)
    assert contrast["n_total"] == 2
    assert contrast["confirmed"] is False  # n_total < 10
    suggested = result["suggested_rule"]  # type: ignore[union-attr]
    assert suggested["base_tag_id"] == "t1"
    assert suggested["context_tag_id"] == "t2"
    assert suggested["value"] == pytest.approx(0.5)  # half_up(0.6*2)/2


def test_verdict_explore_tag_outcomes(rated_conn: sqlite3.Connection) -> None:
    result = verdict(rated_conn, BATCH_E)
    assert result["mode"] == "explore"
    summary = result["summary"]  # type: ignore[union-attr]
    assert summary["n"] == 3
    assert summary["mean_outcome"] == pytest.approx(0.4 / 3)
    # t2 (on s1, s7) has mean 0.5; t1 (on s1, s7, s2) has mean 0.4/3. Ranking
    # is by mean desc, so t2 leads; t3 has n=1 and is below the n>=2 floor.
    top = result["top_tags"]  # type: ignore[union-attr]
    assert [str(t["tag_id"]) for t in top] == ["t2", "t1"]
    assert top[0]["mean_outcome"] == pytest.approx(0.5)
    assert top[0]["category"] == "Group Makeup"
    assert all(int(t["n"]) >= 2 for t in top)


def test_candidates_without_contrast_sort_by_cooccurrence(conn: sqlite3.Connection) -> None:
    result = tag_context_candidates(conn, "t1", min_support=1)
    items = result["items"]  # type: ignore[union-attr]
    # Only s3 is labeled (thumb) -> below the contrast floor -> cooccurrence.
    assert [str(i["tag_id"]) for i in items] == ["t2", "t3"]
    assert items[0]["cooccurrence"] == 2
    assert items[0]["rate"] == pytest.approx(0.5)
    assert items[0]["contrast"] is None
    assert items[1]["cooccurrence"] == 1


def test_candidates_rank_by_contrast_when_labels_exist(sidecar: Path, tmp_path: Path) -> None:
    copy = tmp_path / "curator.sqlite3"
    copy.write_bytes(sidecar.read_bytes())
    connection = sqlite3.connect(copy)
    connection.row_factory = sqlite3.Row
    # Label s1, s2, s7 (plus the fixture's s3 and rating labels) -> 4+ labeled
    # base scenes, so the outcome-contrast ranking engages.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('c1', 's1', 'thumb_up', NULL, 1, '{}'),
               ('c2', 's2', 'thumb_down', NULL, 1, '{}'),
               ('c3', 's7', 'thumb_up', NULL, 1, '{}')
        """
    )
    connection.commit()
    # Derive the expected contrast from the merged labels (ratings and thumbs
    # both feed the model; the payload only gates verdict attribution).
    from curator.config import DEFAULT_CONFIG
    from curator.model.builder import PreferenceModelBuilder

    labels = PreferenceModelBuilder(connection, DEFAULT_CONFIG)._scene_labels()

    def mean(scenes: list[str]) -> float:
        return sum(labels[s].outcome for s in scenes) / len(scenes)

    def shrunk(with_scenes: list[str], without_scenes: list[str]) -> float:
        raw = mean(with_scenes) - mean(without_scenes)
        evidence = min(len(with_scenes), len(without_scenes))
        return raw * min(1.0, evidence / 8.0)

    result = tag_context_candidates(connection, "t1", min_support=1)
    items = result["items"]  # type: ignore[union-attr]
    t2 = next(i for i in items if i["tag_id"] == "t2")
    assert t2["labeled_n"] == 2
    assert t2["contrast"] == pytest.approx(shrunk(["s1", "s7"], ["s2", "s3"]))
    assert t2["contrast"] > 0  # threesome separates liked from disliked
    t3 = next(i for i in items if i["tag_id"] == "t3")
    assert t3["contrast"] == pytest.approx(shrunk(["s2"], ["s1", "s3", "s7"]))
    # Positive contrast ranks before null and negative candidates.
    assert [str(i["tag_id"]) for i in items] == ["t2", "t3"]
    assert items[0]["contrast"] is not None and items[0]["contrast"] > 0
    assert items[1]["contrast"] is not None and items[1]["contrast"] < 0
    connection.close()


def test_candidates_exclude_ubiquitous_and_artifact_tags(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES"
        " ('t7', 'blowjob', 'g'), ('t8', 'rare fetish', 'h'),"
        " ('t9', '[Timestamp: Synced]', 'i')"
    )
    conn.execute(
        "INSERT INTO tag_taxonomy_match(local_tag_id, snapshot_id, external_tag_id,"
        " external_category_id, match_method, confidence, ambiguity_count) VALUES"
        " ('t7', 'tax-1', 'e7', 'cat-act', 'stable_id', 1, 0),"
        " ('t8', 'tax-1', 'e8', 'cat-act', 'stable_id', 1, 0),"
        " ('t9', 'tax-1', 'e9', 'cat-act', 'stable_id', 1, 0)"
    )
    conn.execute(
        "INSERT INTO scene_tag(scene_id, tag_id) VALUES"
        " ('s1', 't7'), ('s2', 't7'), ('s4', 't7'), ('s6', 't7'), ('s7', 't7'), ('s8', 't7'),"
        " ('s1', 't8'), ('s2', 't8'),"
        " ('s1', 't9')"
    )
    conn.commit()
    result = tag_context_candidates(conn, "t1", min_support=1)
    ids = [str(i["tag_id"]) for i in result["items"]]  # type: ignore[union-attr]
    assert "t8" in ids  # library rate 2/8 = 0.25 survives
    assert "t7" not in ids  # library rate 6/8 = 0.75 is ubiquitous
    assert "t9" not in ids  # sync-artifact tag


def test_verdict_excludes_reasoned_ratings(sidecar: Path, tmp_path: Path) -> None:
    """metadata_wrong / contradicts_hypothesis ratings must not count toward
    the cell means — those scenes are not valid instances of their cell."""
    copy = tmp_path / "curator.sqlite3"
    copy.write_bytes(sidecar.read_bytes())
    connection = sqlite3.connect(copy)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('fx-1', 's2', 'contradicts_hypothesis', NULL, 1, '{}'),
               ('fx-2', 's1', 'metadata_wrong', NULL, 1, '{}')
        """
    )
    connection.commit()
    result = verdict(connection, BATCH_V)
    cells = {str(c["cell"]): c for c in result["cells"]}  # type: ignore[union-attr]
    assert cells["L&T"]["n"] == 0  # s1's rating reasoned out
    assert cells["L&!T"]["n"] == 0  # s2's rating reasoned out
    assert result["contrast"] == {}  # type: ignore[union-attr]
    assert result["suggested_rule"] is None  # type: ignore[union-attr]
    connection.close()


def test_verdict_excludes_performer_driven_ratings(sidecar: Path, tmp_path: Path) -> None:
    """Performer-driven ratings must not skew tag-level verdict means."""
    copy = tmp_path / "curator.sqlite3"
    copy.write_bytes(sidecar.read_bytes())
    connection = sqlite3.connect(copy)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('fx-3', 's2', 'performer_driven', NULL, 1, '{}')
        """
    )
    connection.commit()
    result = verdict(connection, BATCH_V)
    cells = {str(c["cell"]): c for c in result["cells"]}  # type: ignore[union-attr]
    assert cells["L&!T"]["n"] == 0  # performer-driven rating reasoned out
    assert cells["L&T"]["n"] == 1  # unaffected scene still counts
    connection.close()


def test_candidates_exclude_weak_interaction_categories(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO taxonomy_category(snapshot_id, category_id, name, group_name)"
        " VALUES ('tax-1', 'cat-clo', 'Clothing', 'PEOPLE')"
    )
    conn.execute("INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('t10', 'leather', 'j')")
    conn.execute(
        "INSERT INTO tag_taxonomy_match(local_tag_id, snapshot_id, external_tag_id,"
        " external_category_id, match_method, confidence, ambiguity_count)"
        " VALUES ('t10', 'tax-1', 'e10', 'cat-clo', 'stable_id', 1, 0)"
    )
    conn.execute("INSERT INTO scene_tag(scene_id, tag_id) VALUES ('s1', 't10'), ('s2', 't10')")
    conn.commit()
    result = tag_context_candidates(conn, "t1", min_support=1)
    ids = [str(i["tag_id"]) for i in result["items"]]  # type: ignore[union-attr]
    assert "t10" not in ids  # Clothing is not a hypothesis-worthy context
    assert "t2" in ids  # Group Makeup survives


def test_submit_validation_errors(conn: sqlite3.Connection) -> None:
    from curator.curation import submit_ratings

    with pytest.raises(ValueError, match="unknown batch"):
        submit_ratings(conn, "nope", [{"scene_id": "s2", "value": 5, "reason": None}])
    with pytest.raises(ValueError, match="batch is not open"):
        submit_ratings(conn, BATCH_V, [{"scene_id": "s2", "value": 5, "reason": None}])
    with pytest.raises(ValueError, match="scene is not in this batch"):
        submit_ratings(conn, BATCH_X, [{"scene_id": "s9", "value": 5, "reason": None}])
    with pytest.raises(ValueError, match="already rated"):
        submit_ratings(conn, BATCH_X, [{"scene_id": "s1", "value": 5, "reason": None}])
    with pytest.raises(ValueError, match="duplicate rating"):
        submit_ratings(
            conn,
            BATCH_X,
            [
                {"scene_id": "s2", "value": 5, "reason": None},
                {"scene_id": "s2", "value": 6, "reason": None},
            ],
        )
    with pytest.raises(ValueError, match="must be an integer"):
        submit_ratings(conn, BATCH_X, [{"scene_id": "s2", "value": 7.5, "reason": None}])
    with pytest.raises(ValueError, match="from 0 to 10"):
        submit_ratings(conn, BATCH_X, [{"scene_id": "s2", "value": 11, "reason": None}])
    with pytest.raises(ValueError, match="unknown rating reason"):
        submit_ratings(conn, BATCH_X, [{"scene_id": "s2", "value": 5, "reason": "oops"}])
    with pytest.raises(ValueError, match="must not be empty"):
        submit_ratings(conn, BATCH_X, [])


def test_submit_happy_path_marks_items_and_closes_batch(conn: sqlite3.Connection) -> None:
    from curator.curation import submit_ratings

    result = submit_ratings(
        conn,
        BATCH_X,
        [
            {"scene_id": "s2", "value": 8, "reason": None},
            {"scene_id": "s4", "value": 2, "reason": "contradicts_hypothesis"},
        ],
    )
    assert result["accepted"] == 2
    assert result["batch_status"] == "open"  # s6 remains unrated
    rows = conn.execute(
        "SELECT scene_id, rated FROM curation_batch_item WHERE batch_id=? ORDER BY scene_id",
        (BATCH_X,),
    ).fetchall()
    assert {str(r["scene_id"]): int(r["rated"]) for r in rows} == {
        "s1": 1,
        "s2": 1,
        "s4": 1,
        "s6": 0,
    }
    result = submit_ratings(conn, BATCH_X, [{"scene_id": "s6", "value": 5, "reason": None}])
    assert result["batch_status"] == "rated"
    status = conn.execute(
        "SELECT status FROM curation_batch WHERE batch_id=?", (BATCH_X,)
    ).fetchone()
    assert str(status["status"]) == "rated"
