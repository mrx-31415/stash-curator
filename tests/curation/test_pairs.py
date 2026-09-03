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

from curator.curation import (
    ORTHOGONAL_CANDIDATE_MULTIPLIER,
    CurationContext,
    _group_clean_scenes,
    _orthogonal_pairs,
    _pair_score,
    _pair_unlabeled,
    create_pair_round,
    curation_context,
    pair_verdict,
    submit_impact_correction,
    submit_picks,
)
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
    # Unlabeled contrast cells: L&T = {s1, s7}, L&!T = {s2}. s21 is excluded
    # from L&!T by group-cell hygiene. The per-round scene cap is 1, so the two
    # candidates share s2 and only the higher-scoring pair is served.
    assert len(pairs_a) == 1
    pair_scenes = set()
    for pair in pairs_a:
        pair_scenes.add(pair["scene_a"]["scene_id"])
        pair_scenes.add(pair["scene_b"]["scene_id"])
    assert "s21" not in pair_scenes
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
    # Normalized probabilities are each pair's share of the full candidate-pool
    # score; the scene cap excluded the second candidate (it shares s2), so the
    # selected set carries only the top pair's share, not all of it.
    assert sum(p["selection_probability"] for p in pairs_a) <= 1.0


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
    assert all(count <= 1 for count in uses.values())
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


def test_orthogonal_candidates_are_over_generated_for_score_based_selection(
    sidecar: Path, tmp_path: Path
) -> None:
    """_orthogonal_pairs must generate more candidates than the round needs,
    so create_pair_round's _pair_score ranking has real choices to pick from.
    Returning exactly `budget` pairs (the old behavior) left that ranking
    nothing to choose between, since every generated pair used each scene
    exactly once and so always passed the per-scene cap — the sort by
    coverage decided everything, and the score-based selection was a no-op."""
    conn = _fresh_selection(sidecar, tmp_path)
    context = curation_context(conn)
    budget = 4
    unlabeled = _pair_unlabeled(context, frozenset())
    candidates = _orthogonal_pairs(context, budget, frozenset())
    expected_pairs = min(len(unlabeled), ORTHOGONAL_CANDIDATE_MULTIPLIER * budget) // 2
    assert len(candidates) == expected_pairs
    assert len(candidates) > budget
    # create_pair_round still hands back at most `budget` pairs: the wider
    # candidate set is consumed by scoring/ranking, not exposed to the caller.
    round_data = create_pair_round(conn, "orthogonal", budget)
    assert 0 < len(round_data["pairs"]) <= budget  # type: ignore[arg-type]


def test_pair_score_coverage_favors_few_rare_over_many_common() -> None:
    """Coverage is the mean rarity over the symmetric difference, not the sum.
    A pair differing on one very rare tag (rarity 0.5) must outrank a pair
    differing on five only-moderately-rare tags (rarity 0.2 each, summing to
    1.0) — the old sum-based coverage would have preferred the many-tag pair
    (1.0 > 0.5); summing rewarded "differs on everything", which spread a
    single comparison's +-1 signal thin across all of it."""
    context = CurationContext(
        labels=frozenset(),
        scene_ids=frozenset({"rare-a", "rare-b", "many-a", "many-b"}),
        scene_tags={
            "rare-a": frozenset({"t-rare"}),
            "rare-b": frozenset(),
            "many-a": frozenset({"t1", "t2", "t3", "t4", "t5"}),
            "many-b": frozenset(),
        },
        scene_performers={},
        performer_counts={},
        performer_name={},
        studio={},
        scene_title={},
        scene_date={},
        scene_details={},
        tag_cat={},
        tag_name={},
        counts={"t-rare": 4, "t1": 25, "t2": 25, "t3": 25, "t4": 25, "t5": 25},
        appeal={"rare-a": 0.6, "rare-b": 0.35, "many-a": 0.6, "many-b": 0.35},
        blocked_scenes=frozenset(),
        metadata_wrong=frozenset(),
        interactive=frozenset({"t-rare", "t1", "t2", "t3", "t4", "t5"}),
    )
    rare_score, _, _ = _pair_score(context, "rare-a", "rare-b", "orthogonal")
    many_score, _, _ = _pair_score(context, "many-a", "many-b", "orthogonal")
    assert rare_score == pytest.approx(0.5)
    assert many_score == pytest.approx(0.2)
    assert rare_score > many_score


def test_pair_score_conflict_prefers_discriminable_moderate_gap() -> None:
    """Conflict is a discriminability curve, not 1/(1+|predA-predB|).

    The old term was maximal at a near-tie, where a human pick is a coin flip
    and the learned +-1 label is noise. The curve peaks at a moderate gap the
    user can reliably adjudicate and down-weights both exact ties (uninformative
    coin flips) and very large gaps (foregone conclusions). Coverage and fit are
    held identical here so the ordering isolates conflict."""
    context = CurationContext(
        labels=frozenset(),
        scene_ids=frozenset({"tie-a", "tie-b", "mod-a", "mod-b", "big-a", "big-b"}),
        scene_tags={
            "tie-a": frozenset({"t-rar"}),
            "tie-b": frozenset(),
            "mod-a": frozenset({"t-rar"}),
            "mod-b": frozenset(),
            "big-a": frozenset({"t-rar"}),
            "big-b": frozenset(),
        },
        scene_performers={},
        performer_counts={},
        performer_name={},
        studio={},
        scene_title={},
        scene_date={},
        scene_details={},
        tag_cat={},
        tag_name={},
        counts={"t-rar": 4},
        appeal={
            "tie-a": 0.40,
            "tie-b": 0.39,  # near-tie: gap 0.01
            "mod-a": 0.50,
            "mod-b": 0.25,  # moderate: gap 0.25 (the peak)
            "big-a": 0.90,
            "big-b": -0.60,  # foregone: gap 1.50
        },
        blocked_scenes=frozenset(),
        metadata_wrong=frozenset(),
        interactive=frozenset({"t-rar"}),
    )
    tie, _, _ = _pair_score(context, "tie-a", "tie-b", "orthogonal")
    moderate, _, _ = _pair_score(context, "mod-a", "mod-b", "orthogonal")
    big, _, _ = _pair_score(context, "big-a", "big-b", "orthogonal")
    # Identical coverage (one rare tag differing) and fit (orthogonal), so the
    # ordering is driven purely by conflict. The moderate gap outranks both the
    # near-tie and the foregone conclusion.
    assert moderate > tie
    assert moderate > big
    assert tie > 0  # exact ties score zero only at gap == 0; near-ties still score


def test_submit_picks_writes_labels(sidecar: Path, tmp_path: Path) -> None:
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


def test_submit_picks_flag_writes_metadata_wrong(sidecar: Path, tmp_path: Path) -> None:
    conn = _fresh_selection(sidecar, tmp_path)
    round_data = create_pair_round(conn, "orthogonal", 4)
    round_id = str(round_data["round_id"])
    pair = round_data["pairs"][0]  # type: ignore[union-attr]
    pair_id = pair["pair_id"]
    scene_a = pair["scene_a"]["scene_id"]
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
    # The flagged pair produces no winner/loser labels.
    assert (
        conn.execute(
            "SELECT count(*) FROM feedback WHERE feedback_type LIKE 'curation_pair_%'"
        ).fetchone()[0]
        == labels_before
    )
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
    neutral label, and the row is answered with no winner."""
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


def test_submit_impact_correction_writes_supersedes_and_validates(
    sidecar: Path, tmp_path: Path
) -> None:
    """An impact correction records a direct scene signal and marks the model
    dirty; re-correcting the same scene supersedes the earlier row rather than
    stacking a second signal, and the op validates its inputs."""
    conn = _fresh_selection(sidecar, tmp_path)

    def generation() -> int:
        row = conn.execute(
            "SELECT requested_generation FROM model_update_state WHERE singleton=1"
        ).fetchone()
        return int(row["requested_generation"])

    before = generation()
    result = submit_impact_correction(conn, "s1", "up")
    assert result["schema_version"] == 2
    assert result["scene_id"] == "s1"
    assert result["direction"] == "up"
    assert generation() == before + 1
    rows = conn.execute(
        "SELECT value, reversed_by_id FROM feedback WHERE feedback_type='impact_correction'"
    ).fetchall()
    assert [(r["value"], r["reversed_by_id"]) for r in rows] == [("1", None)]

    # Re-correcting supersedes: the earlier row is reversed so the model sees
    # only the latest direction, not the sum of both.
    submit_impact_correction(conn, "s1", "down")
    rows = conn.execute(
        "SELECT value, reversed_by_id FROM feedback WHERE feedback_type='impact_correction'"
        " ORDER BY occurred_at_ms, rowid"
    ).fetchall()
    assert [(r["value"], r["reversed_by_id"] is not None) for r in rows] == [
        ("1", True),
        ("-1", False),
    ]

    with pytest.raises(ValueError, match="scene_id is required"):
        submit_impact_correction(conn, "", "up")
    with pytest.raises(ValueError, match="direction must be 'up' or 'down'"):
        submit_impact_correction(conn, "s1", "sideways")
    with pytest.raises(ValueError, match="unknown scene"):
        submit_impact_correction(conn, "no-such-scene", "up")


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


def test_group_clean_scenes(sidecar: Path, tmp_path: Path) -> None:
    """The hygiene helper: 3+ performer scenes are excluded from the 'without
    tag' pool for group tags, and kept for non-group tags."""
    conn = _fresh_selection(sidecar, tmp_path)
    context = curation_context(conn)
    scenes = ["s2", "s21", "s7"]
    # For the group tag t2 (Group Makeup in the fixture taxonomy), the
    # 3-performer scene s21 cannot serve as a clean negative; s2/s7 have
    # fewer performers and are kept.
    cleaned = _group_clean_scenes(context, scenes, "t2")
    assert "s21" not in cleaned
    assert set(cleaned) == {"s2", "s7"}
    # Non-group tag (t3, category Acts): no exclusion.
    assert _group_clean_scenes(context, scenes, "t3") == scenes
