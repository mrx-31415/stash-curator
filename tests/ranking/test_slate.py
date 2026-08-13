import json
import sqlite3
from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.cli import run
from curator.ranking import LanePolicy, SlateBuilder
from curator.storage import MigrationRunner, connect_database


def _component(value: float, **extra: object) -> dict[str, object]:
    return {"raw": value, "value": value, **extra}


def _score(
    connection: sqlite3.Connection,
    scene_id: str,
    *,
    fit: float,
    appeal: float,
    confidence: float,
    metadata: float,
    direct: float = 0.0,
    direct_confidence: float = 0.0,
    recovery: float = 1.0,
    content: float = 0.0,
    neighbor: float = 0.0,
    studio: float = 0.0,
    structure: float = 0.0,
    signals: tuple[str, ...] = (),
    eligible: bool = True,
    neighbors: tuple[dict[str, object], ...] = (),
) -> None:
    components = {
        "baseline": _component(0),
        "content": _component(content),
        "content_neighbor": _component(neighbor),
        "performer_identity": _component(0),
        "performer_similarity": _component(0),
        "studio": _component(studio),
        "structure": _component(structure),
        "direct": {
            "value": direct,
            "confidence": direct_confidence,
            "signals": list(signals),
        },
        "fit": {"recovery": recovery, "cooldown": 0, "satiation": 0, "not_now": 0},
    }
    connection.execute(
        """
        INSERT INTO model_scene_score(
            model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
            appeal, current_fit, confidence, metadata_confidence, recovery,
            components_json, eligibility_json
        ) VALUES ('model', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scene_id,
            appeal,
            direct,
            direct_confidence,
            appeal,
            fit,
            confidence,
            metadata,
            recovery,
            json.dumps(components),
            json.dumps({"eligible": eligible, "reasons": [] if eligible else ["excluded"]}),
        ),
    )
    connection.executemany(
        """
        INSERT INTO model_scene_neighbor(
            model_id, scene_id, rank, neighbor_scene_id, similarity, weight, outcome
        ) VALUES ('model', ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                scene_id,
                rank,
                item["scene_id"],
                item["similarity"],
                item["weight"],
                item["outcome"],
            )
            for rank, item in enumerate(neighbors)
        ),
    )


def _database(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint,
            created_at_ms, published_at_ms
        ) VALUES ('features', 'published', '{}', 'source', 1, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms, published_at_ms
        ) VALUES ('model', 'published', 'features', '{}', 1, 1)
        """
    )
    connection.executemany(
        "INSERT INTO source_studio(studio_id, name, source_hash) VALUES (?, ?, ?)",
        (("st1", "Studio One", "st1"), ("st2", "Studio Two", "st2")),
    )
    scene_specs = (
        ("a-best", "p1", "st1", "x"),
        ("b-best", "p1", "st1", "x"),
        ("c-best", "p2", "st1", "x"),
        ("d-revisit", "p3", "st2", "y"),
        ("e-frontier", "p4", "st2", "y"),
        ("f-stretch", "p5", "st2", "z"),
        ("g-combination", "p6", "st2", "z"),
        ("h-probe", "p8", "st2", "q"),
        ("i-island", "p9", "st2", "q"),
        ("j-anchor", "p10", "st2", "y"),
        ("k-anchor", "p11", "st2", "z"),
        ("l-varied", "p13", "st2", "q"),
        ("x-excluded", "p12", "st2", "q"),
    )
    for scene_id, performer, studio, content in scene_specs:
        connection.execute(
            """
            INSERT OR IGNORE INTO source_performer(performer_id, name, source_hash)
            VALUES (?, ?, ?)
            """,
            (performer, performer, performer),
        )
        connection.execute(
            "INSERT INTO source_scene(scene_id, title, studio_id, source_hash) VALUES (?, ?, ?, ?)",
            (scene_id, scene_id, studio, scene_id),
        )
        connection.execute(
            """
            INSERT INTO source_file(file_id, scene_id, available, source_hash)
            VALUES (?, ?, 1, ?)
            """,
            (f"file-{scene_id}", scene_id, f"file-{scene_id}"),
        )
        connection.execute(
            "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, 0)",
            (scene_id, performer),
        )
        feature_id = f"feature-{content}"
        connection.execute(
            """
            INSERT OR IGNORE INTO feature_definition(
                feature_id, feature_version, family, name, provenance
            ) VALUES (?, 'features', 'content', ?, 'synthetic')
            """,
            (feature_id, f"tag:{content}"),
        )
        connection.execute(
            """
            INSERT INTO entity_feature(
                feature_version, entity_type, entity_id, feature_id, value, confidence
            ) VALUES ('features', 'scene', ?, ?, 1, 1)
            """,
            (scene_id, feature_id),
        )
    _score(
        connection,
        "a-best",
        fit=0.80,
        appeal=0.75,
        confidence=0.9,
        metadata=0.8,
        content=0.20,
        neighbor=0.10,
    )
    _score(
        connection,
        "b-best",
        fit=0.79,
        appeal=0.74,
        confidence=0.9,
        metadata=0.8,
        content=0.20,
        neighbor=0.10,
    )
    _score(
        connection,
        "c-best",
        fit=0.70,
        appeal=0.68,
        confidence=0.9,
        metadata=0.8,
        content=0.20,
        neighbor=0.10,
    )
    _score(
        connection,
        "d-revisit",
        fit=0.15,
        appeal=0.80,
        confidence=0.9,
        metadata=0.8,
        direct=0.9,
        direct_confidence=0.8,
        recovery=0.9,
        content=0.1,
        signals=("o",),
    )
    connection.execute(
        "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('d-revisit', 1, 0)"
    )
    _score(
        connection, "e-frontier", fit=0.12, appeal=0.15, confidence=0.3, metadata=0.5, content=0.12
    )
    _score(
        connection,
        "f-stretch",
        fit=0.12,
        appeal=0.15,
        confidence=0.5,
        metadata=0.6,
        content=0.12,
        studio=-0.05,
    )
    _score(
        connection,
        "g-combination",
        fit=0.05,
        appeal=0.08,
        confidence=0.3,
        metadata=0.6,
        content=0.04,
        structure=0.03,
    )
    _score(connection, "h-probe", fit=0.0, appeal=0.0, confidence=0.6, metadata=0.6)
    _score(connection, "i-island", fit=0.0, appeal=0.0, confidence=0.1, metadata=0.6)
    _score(connection, "j-anchor", fit=0.08, appeal=0.1, confidence=0.2, metadata=0.5, content=0.10)
    _score(connection, "k-anchor", fit=0.07, appeal=0.1, confidence=0.2, metadata=0.5, content=0.09)
    _score(
        connection,
        "l-varied",
        fit=0.68,
        appeal=0.66,
        confidence=0.9,
        metadata=0.8,
        content=0.20,
        neighbor=0.10,
    )
    _score(
        connection,
        "x-excluded",
        fit=0.9,
        appeal=0.9,
        confidence=0.9,
        metadata=0.9,
        content=0.2,
        eligible=False,
    )
    return connection


def test_lane_policy_assigns_expected_subtypes_and_excludes_hard_failures(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    progress: list[tuple[int, int]] = []
    classifications = LanePolicy(connection).classify(
        "model", progress=lambda processed, total: progress.append((processed, total))
    )
    lookup = {(item.scene_id, item.lane): item for item in classifications}

    assert ("a-best", "best_bets") in lookup
    assert ("a-best", "discover") not in lookup
    assert ("d-revisit", "revisit") in lookup
    assert lookup[("e-frontier", "discover")].subtype == "frontier"
    assert lookup[("f-stretch", "discover")].subtype == "stretch"
    assert lookup[("g-combination", "adventure")].subtype == "structured_combination_challenge"
    assert lookup[("f-stretch", "adventure")].subtype == "model_disagreement"
    assert lookup[("i-island", "adventure")].subtype == "under_covered_island"
    assert lookup[("h-probe", "adventure")].subtype == "under_covered_island"
    assert lookup[("j-anchor", "adventure")].subtype == "anchored_model_gap"
    assert not any(item.scene_id == "x-excluded" for item in classifications)
    assert connection.execute(
        "SELECT count(*) FROM model_scene_lane WHERE model_id='model'"
    ).fetchone()[0] == len(classifications)
    assert {
        (item.scene_id, item.lane): item for item in LanePolicy(connection).load("model")
    } == lookup
    assert progress[-1][0] == progress[-1][1]


def test_materialize_reports_each_lane_ordering(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    progress: list[tuple[int, int]] = []

    builder = SlateBuilder(connection)
    counts = builder.materialize(
        "model",
        force=True,
        progress=lambda processed, total: progress.append((processed, total)),
    )

    assert set(counts) == {"best_bets", "revisit", "discover", "adventure"}
    assert progress == [(position, 7) for position in range(1, 8)]
    assert set(builder.materialize_timings_ms) == {
        "score_first_ordering",
        "varied_ordering",
    }
    assert {
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT lane FROM model_lane_order
            WHERE model_id='model' AND ordering='score_first'
            """
        )
    } == {"adventure", "for_you"}


def test_queried_score_first_lanes_match_full_materialized_order(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    classifications = LanePolicy(connection).classify("model")
    builder = SlateBuilder(connection, diversity_enabled=False)
    candidates = builder._candidates("model", classifications)
    expected = {
        lane: [
            candidate.classification.scene_id
            for candidate, *_rest in builder._build_order(
                lane,
                tuple(
                    candidate for candidate in candidates if candidate.classification.lane == lane
                ),
                varied=False,
            )
        ]
        for lane in ("best_bets", "revisit", "discover")
    }

    builder.materialize("model", force=True)

    for lane, scene_ids in expected.items():
        slate = builder._load_materialized_slate("model", lane, len(scene_ids))
        assert slate is not None
        assert [item.scene_id for item in slate.items] == scene_ids


def test_available_count_matches_live_materialized_slate(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    for diversity_enabled in (True, False):
        builder = SlateBuilder(connection, diversity_enabled=diversity_enabled)
        builder.materialize("model", force=True)
        for lane in ("for_you", "best_bets", "revisit", "discover", "adventure"):
            slate = builder._load_materialized_slate("model", lane, 100)
            assert slate is not None
            assert builder.available_count("model", lane) == len(slate.items)
            excluded = {slate.items[0].scene_id} if slate.items else set()
            assert builder.available_count("model", lane, exclude_scene_ids=excluded) == len(
                [item for item in slate.items if item.scene_id not in excluded]
            )


def test_new_slate_builder_reuses_persisted_lane_classifications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    monkeypatch.setattr(
        LanePolicy,
        "classify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reclassified")),
    )

    builder = SlateBuilder(connection)
    assert builder.recommend("best_bets", 1).items
    assert connection.execute("SELECT count(*) FROM model_lane_candidate_cache").fetchone()[0] == 1
    assert connection.execute(
        "SELECT 1 FROM application_meta WHERE key='slate:model:best_bets'"
    ).fetchone()


def test_longer_slate_extends_the_saved_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    first = SlateBuilder(connection).recommend("best_bets", 2)
    builder = SlateBuilder(connection)
    positions = []
    target = builder._target

    def counted_target(lane: str, position: int, exploration: float):
        positions.append(position)
        return target(lane, position, exploration)

    monkeypatch.setattr(builder, "_target", counted_target)
    extended = builder.recommend("best_bets", 4)

    assert extended.items[:2] == first.items
    assert positions == [2, 3]


def test_prepared_lane_candidates_avoid_rehydrating_model_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    counts = SlateBuilder(connection).prepare("model")
    assert set(counts) == {"best_bets", "revisit", "discover", "adventure"}

    monkeypatch.setattr(
        SlateBuilder,
        "_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rehydrated")),
    )
    slate = SlateBuilder(connection).recommend("best_bets", 1)
    assert slate.items
    assert slate.timings_ms["precomputed"] == 1


def test_qualified_impressions_do_not_consume_prepared_slate(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    builder = SlateBuilder(connection)
    builder.prepare("model")
    first = builder.recommend("best_bets", 1)
    scene_id = first.items[0].scene_id
    connection.execute(
        """
        INSERT INTO recommendation_history(history_id, scene_id, lane, shown_at_ms)
        VALUES ('shown', ?, 'best_bets', 9999999999999)
        """,
        (scene_id,),
    )

    assert builder.recommend("best_bets", 1).items[0].scene_id == scene_id


def test_best_bets_excludes_viewed_scenes_while_revisit_requires_them(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('a-best', 2, 0)"
    )

    classifications = LanePolicy(connection).classify("model")

    assert not any(
        item.scene_id == "a-best" and item.lane == "best_bets" for item in classifications
    )
    assert any(item.scene_id == "d-revisit" and item.lane == "revisit" for item in classifications)


def test_direct_play_updates_prebuilt_lanes_without_rebuilding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = SlateBuilder(connection)
    now_ms = 100 * 86_400_000
    monkeypatch.setattr("curator.ranking.slate.time.time_ns", lambda: now_ms * 1_000_000)
    builder.prepare("model")
    assert builder.recommend("best_bets", 1).items[0].scene_id == "a-best"
    assert any(item.scene_id == "d-revisit" for item in builder.recommend("revisit", 5).items)
    connection.executemany(
        """
        INSERT INTO play_session(
            session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
            provenance, confidence, summary_json
        ) VALUES (?, ?, ?, ?, 1, 'direct_player', 1, '{}')
        """,
        (
            ("direct-best", "a-best", now_ms - 1_000, now_ms),
            ("direct-revisit", "d-revisit", now_ms - 1_000, now_ms),
        ),
    )

    assert builder.recommend("best_bets", 1).items[0].scene_id != "a-best"
    assert not any(item.scene_id == "d-revisit" for item in builder.recommend("revisit", 5).items)


_UNOBSERVED_SUMMARY = (
    '{"played_ranges":[],"start_position_seconds":0.0,"maximum_position_seconds":0.0}'
)


def _play_session(
    connection: sqlite3.Connection,
    session_id: str,
    scene_id: str,
    ended_at_ms: int,
    *,
    active_seconds: float,
    summary_json: str,
) -> None:
    connection.execute(
        """
        INSERT INTO play_session(
            session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
            provenance, confidence, summary_json
        ) VALUES (?, ?, ?, ?, ?, 'direct_player', 1, ?)
        """,
        (
            session_id,
            scene_id,
            max(0, ended_at_ms - 1_000),
            ended_at_ms,
            active_seconds,
            summary_json,
        ),
    )


def test_session_without_observed_playback_does_not_suppress_best_bets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = SlateBuilder(connection)
    now_ms = 100 * 86_400_000
    monkeypatch.setattr("curator.ranking.slate.time.time_ns", lambda: now_ms * 1_000_000)
    builder.prepare("model")
    _play_session(
        connection,
        "opened-only",
        "a-best",
        now_ms,
        active_seconds=0.0,
        summary_json=_UNOBSERVED_SUMMARY,
    )

    assert builder.recommend("best_bets", 1).items[0].scene_id == "a-best"

    _play_session(
        connection,
        "watched",
        "a-best",
        now_ms,
        active_seconds=0.0,
        summary_json='{"played_ranges":[],"start_position_seconds":0.0,'
        '"maximum_position_seconds":42.0}',
    )

    assert builder.recommend("best_bets", 1).items[0].scene_id != "a-best"


def test_lane_classification_uses_plays_captured_since_the_last_sync(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    _play_session(
        connection,
        "watched",
        "a-best",
        2,
        active_seconds=120.0,
        summary_json=_UNOBSERVED_SUMMARY,
    )
    _play_session(
        connection,
        "opened-only",
        "b-best",
        2,
        active_seconds=0.0,
        summary_json=_UNOBSERVED_SUMMARY,
    )

    lanes = {(item.scene_id, item.lane) for item in LanePolicy(connection).classify("model")}

    assert ("a-best", "best_bets") not in lanes
    assert ("b-best", "best_bets") in lanes


def test_greedy_slate_enforces_adjacency_and_soft_penalties_only_reorder(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = SlateBuilder(connection)
    compared_pairs: list[tuple[str, str]] = []
    similarity = builder._candidate_similarity

    def counted_similarity(left, right):  # type: ignore[no-untyped-def]
        compared_pairs.append(
            tuple(sorted((left.classification.scene_id, right.classification.scene_id)))
        )
        return similarity(left, right)

    builder._candidate_similarity = counted_similarity  # type: ignore[method-assign]
    slate = builder.recommend("best_bets", 4)

    assert [item.scene_id for item in slate.items] == [
        "a-best",
        "l-varied",
        "c-best",
        "b-best",
    ]
    assert slate.items[1].lane_value < slate.items[2].lane_value
    assert slate.items[1].penalties["studio"] == 0
    assert slate.items[1].penalties["content"] == 0
    assert slate.items[2].penalties["studio"] > 0
    assert slate.items[2].penalties["content"] > 0
    assert all(item.final_utility <= item.lane_value + 0.03 for item in slate.items)
    assert all(item.eligibility["eligible"] is True for item in slate.items)
    assert len(compared_pairs) == len(set(compared_pairs))


def test_diversity_can_be_disabled_without_reusing_diverse_slate(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    diverse = SlateBuilder(connection).recommend("best_bets", 4)
    score_first = SlateBuilder(connection, diversity_enabled=False).recommend("best_bets", 4)

    assert [item.scene_id for item in diverse.items[:2]] == ["a-best", "l-varied"]
    assert [item.scene_id for item in score_first.items[:2]] == ["a-best", "b-best"]
    assert all(
        not any(item.penalties[name] for name in ("performer", "studio", "content", "history"))
        and item.bonuses["uncovered_content"] == 0
        for item in score_first.items
    )


def test_slate_loads_all_lane_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    limits: list[int | None] = []
    load = LanePolicy.load

    def counted_load(self, model_id, *, lanes=None, limit_per_lane=None):  # type: ignore[no-untyped-def]
        limits.append(limit_per_lane)
        return load(self, model_id, lanes=lanes, limit_per_lane=limit_per_lane)

    monkeypatch.setattr(LanePolicy, "load", counted_load)

    SlateBuilder(connection).recommend("best_bets", 2)

    assert limits == [None]


def test_slate_applies_feedback_added_after_model_publication(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = SlateBuilder(connection)
    assert builder.recommend("best_bets", 1).items[0].scene_id == "a-best"
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms)
        VALUES ('late-feedback', 'a-best', 'thumb_down', 2)
        """
    )

    assert builder.recommend("best_bets", 1).items[0].scene_id != "a-best"


def test_not_now_expires_without_rebuilding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    now_ms = 100 * 86_400_000
    monkeypatch.setattr("curator.ranking.slate.time.time_ns", lambda: now_ms * 1_000_000)
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms)
        VALUES ('not-now', 'a-best', 'not_now', ?)
        """,
        (now_ms,),
    )
    builder = SlateBuilder(connection)

    assert builder.recommend("best_bets", 1).items[0].scene_id != "a-best"
    now_ms += 31 * 86_400_000
    assert builder.recommend("best_bets", 1).items[0].scene_id == "a-best"


def test_adventure_gradient_and_for_you_mixture_are_deterministic(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    adventure = SlateBuilder(connection).recommend("adventure", 5)
    assert [item.subtype for item in adventure.items] == [
        "anchored_model_gap",
        "model_disagreement",
        "structured_combination_challenge",
        "under_covered_island",
        "pure_probe",
    ]

    for_you = SlateBuilder(connection).recommend("for_you", 5)
    assert [item.source_lane for item in for_you.items] == [
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "discover",
    ]
    assert len({item.scene_id for item in for_you.items}) == len(for_you.items)

    familiar = SlateBuilder(connection).recommend("for_you", 5, exploration=-1)
    balanced = SlateBuilder(connection).recommend("for_you", 5, exploration=0.5)
    adventurous = SlateBuilder(connection).recommend("for_you", 5, exploration=1)
    assert balanced.items
    assert [item.source_lane for item in familiar.items] == [
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "discover",
    ]
    assert [item.source_lane for item in adventurous.items] == [
        "best_bets",
        "best_bets",
        "revisit",
        "discover",
        "best_bets",
    ]


def test_recommend_cli_returns_full_score_decomposition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "curator.sqlite3"
    connection = _database(database)
    connection.close()
    assert (
        run(["--db", str(database), "recommend", "--lane", "discover", "--count", "2", "--json"])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["lane"] == "discover"
    assert len(payload["items"]) == 2
    assert {
        "appeal",
        "current_fit",
        "lane_value",
        "final_utility",
        "penalties",
        "bonuses",
        "components",
        "neighbors",
        "eligibility",
        "qualification",
        "reason_ids",
    } <= set(payload["items"][0])
    assert "content" in payload["items"][0]["components"]


def test_available_count_cache_is_keyed_by_eligibility_inputs(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    builder = SlateBuilder(connection)
    builder.materialize("model", force=True)

    first = builder.available_count("model", "best_bets")
    assert first is not None and first > 0
    # Repeat calls reuse the cached count.
    assert builder.available_count("model", "best_bets") == first

    # New feedback changes the eligibility fingerprint and invalidates the cache: the
    # just-disliked best-bets scene stops counting.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value, occurred_at_ms)
        VALUES ('fb-1', 'a-best', 'thumb_down', '-1', 2)
        """
    )
    connection.commit()
    assert builder.available_count("model", "best_bets") == first - 1


def test_available_count_batched_blocked_tag_probe_excludes_scenes(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    builder = SlateBuilder(connection)
    builder.materialize("model", force=True)

    first = builder.available_count("model", "best_bets")
    assert first is not None and first > 0

    connection.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('blocked-tag', 'Blocked', 'b')"
    )
    connection.execute(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES ("
        "'a-best', 'blocked-tag', 'scene')"
    )
    connection.execute(
        """
        INSERT INTO direct_tag_preference_history(
            preference_id, tag_id, value, occurred_at_ms
        ) VALUES ('pref-1', 'blocked-tag', 0, 3)
        """
    )
    connection.execute(
        """
        INSERT INTO direct_tag_preference(tag_id, preference_id, value, occurred_at_ms, blocked)
        VALUES ('blocked-tag', 'pref-1', 0, 3, 1)
        """
    )
    connection.commit()
    assert builder.available_count("model", "best_bets") == first - 1


def test_available_count_blocked_term_probe_excludes_scenes(tmp_path: Path) -> None:
    """Blocking a description term hard-excludes every scene whose built
    entity_feature rows carry it — the term->scene mapping comes from the
    published model's desc features, not a scene_tag join."""
    connection = _database(tmp_path / "curator.sqlite3")
    LanePolicy(connection).classify("model")
    builder = SlateBuilder(connection)
    builder.materialize("model", force=True)

    first = builder.available_count("model", "best_bets")
    assert first is not None and first > 0

    connection.execute(
        """
        INSERT INTO feature_definition(
            feature_id, feature_version, family, name, provenance, metadata_json
        ) VALUES ('fd-term', 'features', 'content', 'desc:anal', 'seed',
                  '{"document_frequency": 3}')
        """
    )
    connection.execute(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES ('features', 'scene', 'a-best', 'fd-term', 0.8, 1.0)
        """
    )
    connection.execute(
        """
        INSERT INTO direct_term_preference_history(
            preference_id, term, value, occurred_at_ms, blocked
        ) VALUES ('pref-term', 'anal', 0, 3, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO direct_term_preference(
            term, preference_id, value, occurred_at_ms, blocked
        ) VALUES ('anal', 'pref-term', 0, 3, 1)
        """
    )
    connection.commit()
    assert builder.available_count("model", "best_bets") == first - 1


def test_available_count_probes_are_batched_not_per_scene(tmp_path: Path) -> None:
    """A large lane must not run one blocked-tag probe per scene.

    The N+1 this guards against made For You take 20-58s per load on a 24k-scene
    library (measured via profiling traces). The assertion is on query shape, not
    wall-clock time, so it cannot flake on a loaded machine.
    """
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    scene_count = 5_000
    connection.executemany(
        "INSERT INTO source_scene(scene_id, title, source_hash) VALUES (?, ?, ?)",
        ((f"s{i}", f"Scene {i}", f"s{i}") for i in range(scene_count)),
    )
    connection.executemany(
        "INSERT INTO source_file(file_id, scene_id, available, source_hash) VALUES (?, ?, 1, ?)",
        ((f"f{i}", f"s{i}", f"s{i}") for i in range(scene_count)),
    )
    connection.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('blocked-tag', 'Blocked', 'b')"
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms, published_at_ms
        ) VALUES ('model', 'published', 'features', '{}', 1, 1)
        """
    )
    connection.executemany(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, 'blocked-tag', 'scene')",
        ((f"s{i}",) for i in range(0, scene_count, 4)),
    )
    connection.execute(
        """
        INSERT INTO direct_tag_preference_history(preference_id, tag_id, value, occurred_at_ms)
        VALUES ('pref-1', 'blocked-tag', 0, 3)
        """
    )
    connection.execute(
        """
        INSERT INTO direct_tag_preference(tag_id, preference_id, value, occurred_at_ms, blocked)
        VALUES ('blocked-tag', 'pref-1', 0, 3, 1)
        """
    )
    connection.execute(
        "INSERT INTO model_lane_order_state(model_id, created_at_ms) VALUES ('model', 1)"
    )
    connection.executemany(
        """
        INSERT INTO model_lane_order(
            model_id, lane, ordering, position, scene_id, source_lane, utility, ranking_json
        ) VALUES ('model', 'best_bets', 'varied', ?, ?, 'best_bets', 0.5, '{}')
        """,
        ((i, f"s{i}") for i in range(scene_count)),
    )
    connection.commit()

    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    builder = SlateBuilder(connection)
    total = builder.available_count("model", "best_bets")

    assert total == scene_count * 3 // 4
    probes = [
        statement
        for statement in statements
        if statement.lstrip().startswith("SELECT DISTINCT scene_id FROM scene_tag")
    ]
    assert len(probes) <= scene_count // 500 + 5, (
        "blocked-tag eligibility must be a batched probe, not one query per scene"
    )
    assert not [
        statement
        for statement in statements
        if statement.lstrip().startswith("SELECT 1 FROM scene_tag")
    ], "per-scene blocked-tag probes are a regression"

    # The fingerprint cache makes repeat calls skip the eligibility probes entirely.
    statements.clear()
    assert builder.available_count("model", "best_bets") == total
    assert not [statement for statement in statements if "FROM scene_tag" in statement]


# ── get_score_review (score-first read path) ────────────────────────────────


def _set_appeal(connection: sqlite3.Connection, scene_id: str, appeal: float) -> None:
    """Pin a scene's appeal (and its general/direct mirrors) so the review
    window is deterministic."""
    connection.execute(
        """
        UPDATE model_scene_score SET appeal=?, general_appeal=?, direct_appeal=?
        WHERE model_id='model' AND scene_id=?
        """,
        (appeal, appeal, appeal, scene_id),
    )


def _score_review_db(path: Path) -> sqlite3.Connection:
    """A sidecar whose appeals cover the review window: x-excluded at the
    bottom (built eligibility_json says ineligible — live eligibility is what
    gates the review), then a-best/b-best/c-best/d-revisit/e-frontier."""
    connection = _database(path)
    _set_appeal(connection, "x-excluded", -0.9)
    _set_appeal(connection, "a-best", -0.8)
    _set_appeal(connection, "b-best", -0.5)
    _set_appeal(connection, "c-best", -0.2)
    _set_appeal(connection, "d-revisit", 0.0)
    _set_appeal(connection, "e-frontier", 0.4)
    _set_appeal(connection, "f-stretch", 0.3)
    _set_appeal(connection, "g-combination", 0.2)
    _set_appeal(connection, "h-probe", 0.1)
    _set_appeal(connection, "i-island", 0.05)
    connection.commit()
    return connection


def test_score_review_orders_by_appeal_ascending(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    result = CuratorAPI(connection).get_score_review(page=1, count=20, max_appeal=0.0)
    scene_ids = [item["scene_id"] for item in result["items"]]
    assert scene_ids == ["x-excluded", "a-best", "b-best", "c-best", "d-revisit"]
    assert result["total"] == 5
    assert result["page_size"] == 20
    assert result["page"] == 1
    assert result["has_more"] is False
    assert result["model_version"] == "model"
    assert set(result) == {"items", "total", "page_size", "has_more", "page", "model_version"}
    # The built eligibility_json flag does not gate the review — live
    # eligibility does (the slate path behaves the same way).
    assert result["items"][0]["scene_id"] == "x-excluded"
    assert result["items"][0]["eligibility"] == {"eligible": False, "reasons": ["excluded"]}
    # Positions are page-relative to the full distribution.
    assert [item["position"] for item in result["items"]] == [0, 1, 2, 3, 4]


def test_score_review_items_mirror_slate_shape(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    result = CuratorAPI(connection).get_score_review(page=1, count=20, max_appeal=0.0)
    item = result["items"][1]  # a-best at -0.8
    assert item["scene_id"] == "a-best"
    assert item["lane"] == "score_review"
    assert item["source_lane"] == "score_review"
    assert item["subtype"] is None
    assert item["final_utility"] == item["appeal"] == -0.8
    assert item["lane_value"] == -0.8
    assert item["current_fit"] == pytest.approx(0.80)
    assert item["confidence"] == 0.9
    assert item["penalties"] == {
        "performer": 0.0,
        "studio": 0.0,
        "content": 0.0,
        "history": 0.0,
        "live_cooldown": 0.0,
    }
    assert item["bonuses"] == {"uncovered_content": 0.0}
    assert item["components"]["content"]["value"] == pytest.approx(0.20)
    assert item["reason_ids"] == ("eligibility.lane",)
    assert item["qualification"] == {}
    assert isinstance(item["impression_id"], str) and item["impression_id"]
    assert set(item) == {
        "scene_id",
        "lane",
        "source_lane",
        "subtype",
        "position",
        "appeal",
        "current_fit",
        "confidence",
        "lane_value",
        "final_utility",
        "penalties",
        "bonuses",
        "components",
        "neighbors",
        "eligibility",
        "qualification",
        "reason_ids",
        "impression_id",
    }


def test_score_review_max_appeal_cap(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)
    result = api.get_score_review(page=1, count=20, max_appeal=-0.4)
    assert [item["scene_id"] for item in result["items"]] == ["x-excluded", "a-best", "b-best"]
    assert result["total"] == 3
    # A cap below the whole window yields an empty page.
    result = api.get_score_review(page=1, count=20, max_appeal=-1.0)
    assert result["items"] == []
    assert result["total"] == 0
    assert result["has_more"] is False


def test_score_review_paging_math(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)
    first = api.get_score_review(page=1, count=2, max_appeal=0.0)
    assert [item["scene_id"] for item in first["items"]] == ["x-excluded", "a-best"]
    assert first["has_more"] is True
    assert [item["position"] for item in first["items"]] == [0, 1]
    second = api.get_score_review(page=2, count=2, max_appeal=0.0)
    assert [item["scene_id"] for item in second["items"]] == ["b-best", "c-best"]
    assert second["has_more"] is True
    assert [item["position"] for item in second["items"]] == [2, 3]
    third = api.get_score_review(page=3, count=2, max_appeal=0.0)
    assert [item["scene_id"] for item in third["items"]] == ["d-revisit"]
    assert third["has_more"] is False
    assert [item["position"] for item in third["items"]] == [4]


def test_score_review_applies_live_eligibility(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO exclusion(exclusion_id, entity_type, entity_id, exclusion_type,
            created_at_ms, reversed_at_ms, expires_at_ms)
        VALUES ('ex-c', 'scene', 'c-best', 'hard', 1, NULL, NULL)
        """
    )
    connection.execute(
        """
        INSERT INTO feedback(
            feedback_id, scene_id, feedback_type, value, occurred_at_ms, payload_json
        ) VALUES ('fb-b', 'b-best', 'thumb_down', NULL, 1, '{}')
        """
    )
    connection.commit()
    result = CuratorAPI(connection).get_score_review(page=1, count=20, max_appeal=0.0)
    # c-best hard-excluded stays out; b-best's current thumb_down does NOT
    # exclude on the review surface.
    assert [item["scene_id"] for item in result["items"]] == [
        "x-excluded",
        "a-best",
        "b-best",
        "d-revisit",
    ]
    assert result["total"] == 4


def test_score_review_thumb_down_does_not_exclude(tmp_path: Path) -> None:
    """The review surface drops the current_thumb_down reason: scenes the
    user disliked are exactly what the bottom-of-distribution review must
    show. Other reasons (file_unavailable, hard exclusion) still exclude."""
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    for scene_id in ("a-best", "x-excluded"):
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                                 occurred_at_ms, payload_json)
            VALUES (?, ?, 'thumb_down', NULL, 1, '{}')
            """,
            (f"fb-{scene_id}", scene_id),
        )
    connection.commit()
    result = CuratorAPI(connection).get_score_review(page=1, count=20, max_appeal=0.0)
    scene_ids = [item["scene_id"] for item in result["items"]]
    # a-best (thumb_down only) stays; x-excluded (thumb_down on top of a
    # built ineligible row) stays out.
    assert scene_ids == ["x-excluded", "a-best", "b-best", "c-best", "d-revisit"]
    assert result["total"] == 5
    builder = SlateBuilder(connection)
    assert builder.score_review_available_count("model", 0.0) == 5


def test_score_review_orders_descending(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    result = CuratorAPI(connection).get_score_review(page=1, count=20, max_appeal=0.0, order="desc")
    scene_ids = [item["scene_id"] for item in result["items"]]
    assert scene_ids == ["d-revisit", "c-best", "b-best", "a-best", "x-excluded"]
    assert result["total"] == 5
    assert [item["position"] for item in result["items"]] == [0, 1, 2, 3, 4]
    # The builder mirror exposes the same direction.
    builder = SlateBuilder(connection)
    assert (
        builder.score_review("model", 3, max_appeal=0.0, order="desc").items[0].scene_id
        == "d-revisit"
    )
    with pytest.raises(ValueError, match="invalid score review order"):
        CuratorAPI(connection).get_score_review(order="sideways")


def test_score_review_records_impression_like_get_slate(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    result = CuratorAPI(connection).get_score_review(
        page=2, count=2, max_appeal=0.0, now_ms=1_700_000_000_000
    )
    impression_id = result["items"][0]["impression_id"]
    lane, model_id, config_version = connection.execute(
        "SELECT lane, model_id, config_version FROM impression WHERE impression_id=?",
        (impression_id,),
    ).fetchone()
    assert (lane, model_id, config_version) == ("score_review", "model", "builtin")
    rows = connection.execute(
        """
        SELECT scene_id, position, policy_score, reason_snapshot_json
        FROM impression_item WHERE impression_id=? ORDER BY position
        """,
        (impression_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("b-best", 2, -0.5, '["eligibility.lane"]'),
        ("c-best", 3, -0.2, '["eligibility.lane"]'),
    ]
    # A fresh request records a distinct impression (uuid4 per request).
    second = CuratorAPI(connection).get_score_review(page=1, count=2, max_appeal=0.0)
    assert second["items"][0]["impression_id"] != impression_id


def test_score_review_validation_and_model_required(tmp_path: Path) -> None:
    connection = _score_review_db(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)
    for page, count in ((0, 20), (1, 0), (1, 501)):
        with pytest.raises(ValueError, match="invalid score review page"):
            api.get_score_review(page=page, count=count)
    # The SlateBuilder mirror exposes the same count/eligibility semantics.
    builder = SlateBuilder(connection)
    assert builder.score_review_available_count("model", 0.0) == 5
    assert builder.score_review_available_count("model", -0.4) == 3
    assert builder.score_review("model", 2, max_appeal=0.0).items[0].scene_id == "x-excluded"
    assert builder.score_review("model", 2, max_appeal=0.0).items[1].final_utility == -0.8
    # No published model errors with the slate path's exact message.
    bare = connect_database(tmp_path / "bare.sqlite3")
    MigrationRunner(bare).migrate(applied_at_ms=1)
    with pytest.raises(RuntimeError, match="no published model; run build-model first"):
        CuratorAPI(bare).get_score_review()
