"""Unit tests for the pairwise pick semantics.

The differential suite (test_backend_slice6_pairs.py) proves Go/Python parity;
these tests pin the deterministic behavior: candidate construction per
dimension, propensity normalization, scene cap, pick validation, ELO updates,
and the per-dimension verdicts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from curator.curation import create_pair_round, pair_verdict, submit_picks
from tests.core.test_backend_slice6_pairs import (
    ROUND_ORTH,
    ROUND_PERF,
    ROUND_STUDIO,
    ROUND_TAG,
    make_slice6_sidecar,
)


@pytest.fixture(scope="module")
def sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("pairs-unit") / "curator.sqlite3"
    make_slice6_sidecar(path)
    return path


@pytest.fixture()
def conn(sidecar: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(sidecar)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def _fresh_selection(sidecar: Path, tmp_path: Path) -> sqlite3.Connection:
    """A fresh sidecar copy with no prior rounds, so selection pools are clean."""
    copy = tmp_path / "curator.sqlite3"
    copy.write_bytes(sidecar.read_bytes())
    connection = sqlite3.connect(copy)
    connection.row_factory = sqlite3.Row
    connection.execute("DELETE FROM curation_pair")
    connection.commit()
    return connection


def test_create_round_tag_pairs_across_contrast_cells(sidecar: Path, tmp_path: Path) -> None:
    conn = _fresh_selection(sidecar, tmp_path)
    round_a = create_pair_round(conn, "tag", 4, "t1", "t2")
    pairs_a = round_a["pairs"]  # type: ignore[union-attr]
    # Unlabeled contrast cells: L&T = {s1, s7}, L&!T = {s2} -> two candidates.
    assert len(pairs_a) == 2
    assert round_a["base_tag"] == {"tag_id": "t1", "name": "lesbian"}
    assert round_a["context_tag"] == {"tag_id": "t2", "name": "threesome"}
    # Deterministic selection: the same request on fresh state repeats exactly.
    conn_b = _fresh_selection(sidecar, tmp_path)
    round_b = create_pair_round(conn_b, "tag", 4, "t1", "t2")
    pairs_b = round_b["pairs"]  # type: ignore[union-attr]
    assert [(p["scene_a"]["scene_id"], p["scene_b"]["scene_id"]) for p in pairs_a] == [
        (p["scene_a"]["scene_id"], p["scene_b"]["scene_id"]) for p in pairs_b
    ]
    assert [p["selection_probability"] for p in pairs_a] == [
        p["selection_probability"] for p in pairs_b
    ]

    # Every pair spans the contrast cells: one L&T scene, one L&!T scene.
    def cell_of(scene_id: str) -> str:
        tags = {
            str(r["tag_id"])
            for r in conn.execute("SELECT tag_id FROM scene_tag WHERE scene_id=?", (scene_id,))
        }
        has_base, has_ctx = "t1" in tags, "t2" in tags
        if has_base and has_ctx:
            return "L&T"
        if has_base:
            return "L&!T"
        if has_ctx:
            return "!L&T"
        return "neither"

    for pair in pairs_a:
        cells = {cell_of(pair["scene_a"]["scene_id"]), cell_of(pair["scene_b"]["scene_id"])}
        assert cells == {"L&T", "L&!T"}
        # Scene metadata carries performers and a description slot.
        assert "performers" in pair["scene_a"]
        assert "details" in pair["scene_a"]
    # Normalized probabilities sum to 1 over the selection.
    assert sum(p["selection_probability"] for p in pairs_a) == pytest.approx(1.0, rel=1e-9)


def test_create_round_scene_cap_and_propensity(sidecar: Path, tmp_path: Path) -> None:
    conn = _fresh_selection(sidecar, tmp_path)
    round_data = create_pair_round(conn, "performer", 4, None, None, "p1")
    pairs = round_data["pairs"]  # type: ignore[union-attr]
    assert 0 < len(pairs) <= 4
    uses = {}
    for pair in pairs:
        for side in ("scene_a", "scene_b"):
            scene_id = pair[side]["scene_id"]
            uses[scene_id] = uses.get(scene_id, 0) + 1
    assert all(count <= 2 for count in uses.values())
    assert all(0 < p["selection_probability"] <= 1 for p in pairs)
    # Every performer-dimension pair has p1 on exactly one side.
    for pair in pairs:

        def has_p1(scene_id: str) -> bool:
            return (
                conn.execute(
                    "SELECT 1 FROM scene_performer WHERE scene_id=? AND performer_id='p1'",
                    (scene_id,),
                ).fetchone()
                is not None
            )

        sides = {has_p1(pair["scene_a"]["scene_id"]), has_p1(pair["scene_b"]["scene_id"])}
        assert sides == {True, False}


def test_only_answered_pairs_retire_their_scenes(sidecar: Path, tmp_path: Path) -> None:
    """Seen-exclusion covers answered pairs only. Offering a pair used to burn
    both scenes forever, so an abandoned round — or a stream prefetching ahead
    of the user — permanently consumed scenes nobody ever judged."""

    def scenes_of(round_data: dict[str, object]) -> set[str]:
        out = set()
        for pair in round_data["pairs"]:  # type: ignore[union-attr]
            out.add(pair["scene_a"]["scene_id"])
            out.add(pair["scene_b"]["scene_id"])
        return out

    conn = _fresh_selection(sidecar, tmp_path)
    first = create_pair_round(conn, "orthogonal", 4)
    first_scenes = scenes_of(first)
    assert first_scenes
    # Nothing was answered, so the same scenes stay available.
    second = create_pair_round(conn, "orthogonal", 4)
    assert scenes_of(second) & first_scenes
    # Answering one pair retires exactly that pair's two scenes.
    answered = second["pairs"][0]  # type: ignore[union-attr]
    retired = {answered["scene_a"]["scene_id"], answered["scene_b"]["scene_id"]}
    submit_picks(conn, str(second["round_id"]), [{"pair_id": answered["pair_id"], "winner": "a"}])
    third = create_pair_round(conn, "orthogonal", 4)
    assert scenes_of(third).isdisjoint(retired)


def test_submit_picks_writes_labels_and_elo(sidecar: Path, tmp_path: Path) -> None:
    conn = _fresh_selection(sidecar, tmp_path)
    round_data = create_pair_round(conn, "orthogonal", 4)
    round_id = str(round_data["round_id"])
    pairs = round_data["pairs"]  # type: ignore[union-attr]
    result = submit_picks(
        conn,
        round_id,
        [
            {"pair_id": pairs[0]["pair_id"], "winner": "a"},
            {"pair_id": pairs[1]["pair_id"], "winner": "skip"},
        ],
    )
    assert result["accepted"] == 1
    assert result["skipped"] == 1
    assert result["round_status"] == "open"  # 2 pairs still open
    rows = conn.execute(
        "SELECT status, winner FROM curation_pair WHERE round_id=? ORDER BY pair_id",
        (round_id,),
    ).fetchall()
    statuses = [str(r["status"]) for r in rows]
    assert statuses.count("answered") == 1
    assert statuses.count("skipped") == 1
    # Winner/loser feedback rows carry the payload for Phase-2 confidence.
    labels = conn.execute(
        "SELECT feedback_type, value FROM feedback WHERE feedback_type LIKE 'curation_pair_%'"
    ).fetchall()
    assert {str(r["feedback_type"]): str(r["value"]) for r in labels} == {
        "curation_pair_winner": "10",
        "curation_pair_loser": "0",
    }
    # ELO rows written for the answered pair's scenes.
    elo = conn.execute("SELECT count(*) FROM curation_pair_elo").fetchone()[0]
    assert elo == 2


def test_submit_picks_flag_writes_metadata_wrong(sidecar: Path, tmp_path: Path) -> None:
    conn = _fresh_selection(sidecar, tmp_path)
    round_data = create_pair_round(conn, "orthogonal", 4)
    round_id = str(round_data["round_id"])
    pair = round_data["pairs"][0]  # type: ignore[union-attr]
    pair_id = pair["pair_id"]
    scene_a = pair["scene_a"]["scene_id"]
    elo_before = conn.execute("SELECT count(*) FROM curation_pair_elo").fetchone()[0]
    labels_before = conn.execute(
        "SELECT count(*) FROM feedback WHERE feedback_type LIKE 'curation_pair_%'"
    ).fetchone()[0]
    result = submit_picks(conn, round_id, [{"pair_id": pair_id, "winner": "flag", "scene": "a"}])
    assert result["accepted"] == 0
    assert result["skipped"] == 1
    row = conn.execute(
        "SELECT status, winner FROM curation_pair WHERE pair_id=?", (pair_id,)
    ).fetchone()
    assert str(row["status"]) == "skipped"
    assert (
        conn.execute(
            "SELECT count(*) FROM feedback WHERE feedback_type='metadata_wrong'"
        ).fetchone()[0]
        == 1
    )
    # The flagged pair produces no winner/loser labels and no ELO update.
    assert (
        conn.execute(
            "SELECT count(*) FROM feedback WHERE feedback_type LIKE 'curation_pair_%'"
        ).fetchone()[0]
        == labels_before
    )
    assert conn.execute("SELECT count(*) FROM curation_pair_elo").fetchone()[0] == elo_before
    # The flagged scene is the one named in the pick.
    row = conn.execute(
        "SELECT scene_id FROM feedback WHERE feedback_type='metadata_wrong'"
    ).fetchone()
    assert str(row["scene_id"]) == scene_a
    with pytest.raises(ValueError, match="requires a scene"):
        conn_two = _fresh_selection(sidecar, tmp_path)
        round_two = create_pair_round(conn_two, "orthogonal", 4)
        flag_entry = round_two["pairs"][0]["pair_id"]  # type: ignore[union-attr]
        submit_picks(
            conn_two, str(round_two["round_id"]), [{"pair_id": flag_entry, "winner": "flag"}]
        )


def test_submit_picks_tie_writes_neutral_labels(sidecar: Path, tmp_path: Path) -> None:
    """A tie is Bradley-Terry information, not a discard: both scenes get a
    neutral label, the row is answered with no winner, and ELO is untouched
    because nothing beat anything."""
    conn = _fresh_selection(sidecar, tmp_path)
    round_data = create_pair_round(conn, "orthogonal", 4)
    pair = round_data["pairs"][0]  # type: ignore[union-attr]
    result = submit_picks(
        conn, str(round_data["round_id"]), [{"pair_id": pair["pair_id"], "winner": "tie"}]
    )
    assert result["accepted"] == 1
    assert result["skipped"] == 0
    row = conn.execute(
        "SELECT status, winner FROM curation_pair WHERE pair_id=?", (pair["pair_id"],)
    ).fetchone()
    assert str(row["status"]) == "answered"
    assert row["winner"] is None
    labels = conn.execute(
        "SELECT scene_id, value FROM feedback WHERE feedback_type='curation_pair_tie'"
        " ORDER BY scene_id"
    ).fetchall()
    assert [str(r["value"]) for r in labels] == ["5", "5"]
    assert {str(r["scene_id"]) for r in labels} == {
        pair["scene_a"]["scene_id"],
        pair["scene_b"]["scene_id"],
    }
    assert conn.execute("SELECT count(*) FROM curation_pair_elo").fetchone()[0] == 0
    # No winner, so the pair contributes no win rate to the verdict.
    verdict = pair_verdict(conn, str(round_data["round_id"]))
    assert verdict["n_answered"] == 0


def test_submit_picks_marks_the_model_dirty(sidecar: Path, tmp_path: Path) -> None:
    """Picks write feedback like every other interaction, so they have to
    request a model update — otherwise the round never reaches a build and the
    impact report keeps reporting the previous build's diff."""
    conn = _fresh_selection(sidecar, tmp_path)

    def generation() -> int:
        row = conn.execute(
            "SELECT requested_generation FROM model_update_state WHERE singleton=1"
        ).fetchone()
        return int(row["requested_generation"])

    round_data = create_pair_round(conn, "orthogonal", 4)
    round_id = str(round_data["round_id"])
    pairs = round_data["pairs"]  # type: ignore[union-attr]
    # A bare skip changes nothing the model reads.
    before = generation()
    submit_picks(conn, round_id, [{"pair_id": pairs[0]["pair_id"], "winner": "skip"}])
    assert generation() == before
    # One request per pick, not per call: the pending count is weighed against
    # the update threshold, so a round has to register as many events.
    submit_picks(
        conn,
        round_id,
        [
            {"pair_id": pairs[1]["pair_id"], "winner": "a"},
            {"pair_id": pairs[2]["pair_id"], "winner": "b"},
        ],
    )
    assert generation() == before + 2
    row = conn.execute("SELECT last_cause FROM model_update_state WHERE singleton=1").fetchone()
    assert str(row["last_cause"]) == "curation_picks"
    # A flag writes metadata_wrong, which also changes the training set.
    conn.execute(
        """
        INSERT INTO curation_pair(
            pair_id, round_id, scene_a, scene_b, dimension,
            selection_probability, status, winner, occurred_at_ms, payload_json
        ) VALUES ('dirty-1', 'dirty-round', ?, ?, 'orthogonal', 0.5, 'open', NULL, NULL, '{}')
        """,
        (pairs[0]["scene_a"]["scene_id"], pairs[0]["scene_b"]["scene_id"]),
    )
    conn.commit()
    before = generation()
    submit_picks(conn, "dirty-round", [{"pair_id": "dirty-1", "winner": "flag", "scene": "a"}])
    assert generation() == before + 1


def test_pair_verdict_accumulates_across_rounds_and_shrinks(sidecar: Path, tmp_path: Path) -> None:
    """Win rates span every answered pair of the dimension, shrunk toward 0.5
    so a 2-of-2 sweep stops reading as a 100% preference."""
    conn = _fresh_selection(sidecar, tmp_path)
    first = create_pair_round(conn, "orthogonal", 4)
    first_pairs = first["pairs"]  # type: ignore[union-attr]
    submit_picks(
        conn, str(first["round_id"]), [{"pair_id": first_pairs[0]["pair_id"], "winner": "a"}]
    )
    after_first = pair_verdict(conn, str(first["round_id"]))
    assert after_first["n_answered"] == 1
    assert after_first["n_round"] == 1
    # A second round over the same scenes: generation retires every scene it has
    # already offered, so the corpus cannot produce one on its own.
    conn.execute(
        """
        INSERT INTO curation_pair(
            pair_id, round_id, scene_a, scene_b, dimension,
            selection_probability, status, winner, occurred_at_ms, payload_json
        ) VALUES ('acc-1', 'acc-round', ?, ?, 'orthogonal', 0.5, 'open', NULL, NULL, '{}')
        """,
        (first_pairs[1]["scene_a"]["scene_id"], first_pairs[1]["scene_b"]["scene_id"]),
    )
    conn.commit()
    submit_picks(conn, "acc-round", [{"pair_id": "acc-1", "winner": "b"}])
    after_second = pair_verdict(conn, "acc-round")
    # The second round answered one pair but the verdict counts both rounds.
    assert after_second["n_round"] == 1
    assert after_second["n_answered"] == 2
    # Every reported rate is strictly inside (0, 1): the prior rules out
    # "won everything it appeared in" at these sample sizes.
    rates = [float(item["win_rate"]) for item in after_second["items"]]  # type: ignore[union-attr]
    assert rates
    assert all(0.0 < rate < 1.0 for rate in rates)
    for item in after_second["items"]:  # type: ignore[union-attr]
        wins, appearances = int(item["wins"]), int(item["appearances"])
        assert item["win_rate"] == pytest.approx((wins + 2.0) / (appearances + 4.0))


def test_submit_picks_validation_errors(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown round"):
        submit_picks(conn, "nope", [{"pair_id": "x", "winner": "a"}])
    with pytest.raises(ValueError, match="pair is not in this round"):
        submit_picks(conn, ROUND_TAG, [{"pair_id": "px9", "winner": "a"}])
    with pytest.raises(ValueError, match="duplicate pick"):
        submit_picks(
            conn,
            ROUND_TAG,
            [{"pair_id": "po1", "winner": "a"}, {"pair_id": "po1", "winner": "b"}],
        )
    with pytest.raises(ValueError, match="already answered"):
        submit_picks(conn, ROUND_TAG, [{"pair_id": "pt1", "winner": "a"}])
    with pytest.raises(ValueError, match="winner must be"):
        submit_picks(conn, ROUND_TAG, [{"pair_id": "po1", "winner": "x"}])
    with pytest.raises(ValueError, match="must not be empty"):
        submit_picks(conn, ROUND_TAG, [])


def test_pair_verdict_tag_cells_and_contrast(conn: sqlite3.Connection) -> None:
    result = pair_verdict(conn, ROUND_TAG)
    assert result["dimension"] == "tag"
    assert result["n_answered"] == 3
    cells = {str(c["cell"]): int(c["wins"]) for c in result["cells"]}  # type: ignore[union-attr]
    # pt1: s1 (L&T) wins; pt2: s2 (L&!T) wins; pt3: s1 (L&T) wins.
    assert cells == {"L&T": 2, "L&!T": 1, "!L&T": 0, "neither": 0}
    contrast = result["contrast"]  # type: ignore[union-attr]
    assert contrast["delta"] == 1
    assert contrast["n"] == 3


def test_pair_verdict_performer_win_rates(conn: sqlite3.Connection) -> None:
    result = pair_verdict(conn, ROUND_PERF)
    assert result["dimension"] == "performer"
    items = {str(i["performer_id"]): i for i in result["items"]}  # type: ignore[union-attr]
    # pp1: s1 (p1,p2) beats s2 (p3); pp2: s3 (p2) loses to s1 (p1,p2).
    assert items["p1"]["wins"] == 2
    assert items["p1"]["appearances"] == 2
    assert items["p2"]["wins"] == 2
    assert items["p2"]["appearances"] == 3  # s1 x2 + s3 x1
    assert "p3" not in items  # one appearance is below the n>=2 floor


def test_pair_verdict_orthogonal_tag_win_share(conn: sqlite3.Connection) -> None:
    result = pair_verdict(conn, ROUND_ORTH)
    assert result["dimension"] == "orthogonal"
    items = {str(i["tag_id"]): i for i in result["items"]}  # type: ignore[union-attr]
    # Symmetric-difference appearances only: t1 is shared in px1 (both scenes
    # carry it) and appears once in px2; t2 appears once; t3 appears twice.
    assert set(items) == {"t3"}
    assert items["t3"]["wins"] == 1
    assert items["t3"]["appearances"] == 2
    assert items["t3"]["win_rate"] == pytest.approx(0.5)


def test_pair_verdict_studio_win_rates(conn: sqlite3.Connection) -> None:
    result = pair_verdict(conn, ROUND_STUDIO)
    assert result["dimension"] == "studio"
    items = {str(i["studio"]): i for i in result["items"]}  # type: ignore[union-attr]
    # pu1: s1 (Studio A) beats s2 (Studio B); pu2: s3 (Studio C) loses to s4 (Studio A).
    assert items["Studio A"]["wins"] == 2
    assert items["Studio A"]["appearances"] == 2  # s1 + s4
    assert "Studio B" not in items  # single appearances below the floor


def test_pair_verdict_error_paths(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown round"):
        pair_verdict(conn, "nope")
    with pytest.raises(ValueError, match="round_id is required"):
        pair_verdict(conn, "")
