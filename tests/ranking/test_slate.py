import json
import sqlite3
from pathlib import Path

import pytest

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
            components_json, neighbors_json, eligibility_json
        ) VALUES ('model', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
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
    classifications = LanePolicy(connection).classify("model")
    lookup = {(item.scene_id, item.lane): item for item in classifications}

    assert ("a-best", "best_bets") in lookup
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

    assert SlateBuilder(connection).recommend("best_bets", 1).items


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


def test_greedy_slate_enforces_adjacency_and_soft_penalties_only_reorder(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    slate = SlateBuilder(connection).recommend("best_bets", 4)

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
