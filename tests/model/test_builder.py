import json
import math
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

import curator.model.builder as builder_module
from curator.cli import run
from curator.config import DEFAULT_CONFIG
from curator.explanations import ReasonGraphStore
from curator.features import FeatureStore
from curator.interactions import InteractionStore
from curator.model import PreferenceModelBuilder, RecommendationModelStore
from curator.storage import MigrationRunner, connect_database

DAY_MS = 86_400_000
REFERENCE_MS = 200 * DAY_MS


def _database(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (
            ("good", "Familiar Scenario", "tg"),
            ("bad", "Challenging Scenario", "tb"),
            ("unusual", "Unusual Scenario", "tu"),
        ),
    )
    connection.executemany(
        """
        INSERT INTO source_studio(studio_id, name, favorite, source_hash)
        VALUES (?, ?, ?, ?)
        """,
        (("studio-1", "Studio One", 1, "st1"), ("studio-2", "Studio Two", 0, "st2")),
    )
    connection.executemany(
        """
        INSERT INTO source_performer(
            performer_id, name, favorite, hair_color, height_cm, measurements, source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ("p1", "Performer One", 1, "Black", 170, "34DD-24-36", "p1"),
            ("p2", "Performer Two", 0, "Brown", 168, "34D-25-36", "p2"),
            ("p3", "Performer Three", 0, "Black", 171, "34DD-24-36", "p3"),
        ),
    )
    scenes = (
        ("old-good", "Old Good", "studio-1", "old"),
        ("recent-good", "Recent Good", "studio-1", "recent"),
        ("unseen-good", "Unseen Good", "studio-2", "unseen"),
        ("disliked", "Disliked", "studio-2", "disliked"),
        ("unlabeled", "Unlabeled", "studio-2", "unlabeled"),
        ("unusual", "Unusual", "studio-2", "unusual"),
    )
    connection.executemany(
        """
        INSERT INTO source_scene(scene_id, title, studio_id, source_hash)
        VALUES (?, ?, ?, ?)
        """,
        scenes,
    )
    connection.executemany(
        "INSERT INTO source_file(file_id, scene_id, available, source_hash) VALUES (?, ?, 1, ?)",
        tuple((f"file-{scene[0]}", scene[0], f"file-hash-{scene[0]}") for scene in scenes),
    )
    connection.executemany(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
        (
            ("old-good", "good"),
            ("recent-good", "good"),
            ("unseen-good", "good"),
            ("disliked", "bad"),
            ("unlabeled", "good"),
            ("unusual", "unusual"),
        ),
    )
    connection.executemany(
        "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, 0)",
        (
            ("old-good", "p1"),
            ("recent-good", "p1"),
            ("unseen-good", "p3"),
            ("disliked", "p2"),
            ("unlabeled", "p3"),
            ("unusual", "p2"),
        ),
    )
    connection.executemany(
        "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, 0)",
        (
            ("old-good", REFERENCE_MS - 120 * DAY_MS),
            ("recent-good", REFERENCE_MS - DAY_MS),
            ("disliked", REFERENCE_MS - 150 * DAY_MS),
        ),
    )
    connection.executemany(
        """
        INSERT INTO behavior_event(
            event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
            provenance, payload_json
        ) VALUES (?, 'occasion_outcome', ?, ?, ?, 1, 'synthetic', ?)
        """,
        (
            ("event-old", "old-good", REFERENCE_MS - 120 * DAY_MS, 1.0, '{"primary_signal":"o"}'),
            ("event-recent", "recent-good", REFERENCE_MS - DAY_MS, 1.0, '{"primary_signal":"o"}'),
            (
                "event-disliked",
                "disliked",
                REFERENCE_MS - 150 * DAY_MS,
                -1.0,
                '{"primary_signal":"thumb_down"}',
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO feedback(
            feedback_id, scene_id, feedback_type, occurred_at_ms
        ) VALUES ('feedback-down', 'disliked', 'thumb_down', ?)
        """,
        (REFERENCE_MS - 100 * DAY_MS,),
    )
    return connection


def test_curation_rating_feeds_scene_labels(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('cur-1', 'unseen-good', 'curation_rating', '9', 1, '{}')
        """
    )
    labels = PreferenceModelBuilder(
        connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS
    )._scene_labels()
    label = labels["unseen-good"]
    assert label.signal_types == ("curation_rating",)
    assert label.outcome == pytest.approx(0.8)
    assert label.confidence == pytest.approx(1 - math.exp(-0.8))
    # A rating outside the 0..10 bounds is defensively skipped.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('cur-2', 'unusual', 'curation_rating', '42', 1, '{}')
        """
    )
    labels = PreferenceModelBuilder(
        connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS
    )._scene_labels()
    assert "unusual" not in labels


def test_impact_correction_feeds_scene_absolute_sentiment(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('ic-1', 'corrected-up', 'impact_correction', '1', 1, '{}')
        """
    )
    labels = PreferenceModelBuilder(
        connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS
    )._scene_labels()
    label = labels["corrected-up"]
    # A deliberate "this impact move is wrong" correction is direct evidence
    # about the scene's own appeal, so (unlike a pairwise comparison) it feeds
    # the absolute channel and stands in for a scene-level sentiment.
    assert label.signal_types == ("impact_correction",)
    assert label.outcome == pytest.approx(1.0)
    assert label.absolute_outcome == pytest.approx(1.0)
    assert label.confidence == pytest.approx(
        1 - math.exp(-DEFAULT_CONFIG.model.impact_correction_confidence)
    )
    # The opposite direction reads as the negative.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('ic-2', 'corrected-down', 'impact_correction', '-1', 1, '{}')
        """
    )
    labels = PreferenceModelBuilder(
        connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS
    )._scene_labels()
    assert labels["corrected-down"].outcome == pytest.approx(-1.0)
    assert labels["corrected-down"].absolute_outcome == pytest.approx(-1.0)
    # A malformed value is defensively skipped.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('ic-3', 'corrected-bad', 'impact_correction', '0.5', 2, '{}')
        """
    )
    labels = PreferenceModelBuilder(
        connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS
    )._scene_labels()
    assert "corrected-bad" not in labels


def test_soft_bound_keeps_saturated_components_comparable() -> None:
    """Two scenes whose raw signal exceeds the bound must not end up equal.

    A hard clamp mapped every strong scene to the identical value, so the
    families that saturate stopped discriminating. Appeal is ranked and
    thresholded directly (prune, sentiment review), so those ties are lost
    information rather than a display detail.
    """
    bound = 0.35
    # Below the knee the transform is exact: it only acts where a hard clamp
    # was already discarding the difference.
    for raw in (0.0, 0.1, 0.2, 0.8 * bound):
        assert builder_module._soft_bound(raw, bound) == pytest.approx(raw)
    # Above the bound it stays inside it, where a hard clamp would tie them...
    strong = builder_module._soft_bound(0.45, bound)
    stronger = builder_module._soft_bound(0.90, bound)
    assert 0.8 * bound < strong < stronger < bound
    # ...and the ordering survives, which is the whole point.
    assert stronger > strong
    # Symmetric, and the bound still holds for extreme input: the tail
    # saturates to exactly the bound (exp underflows) and never past it.
    assert builder_module._soft_bound(-0.90, bound) == pytest.approx(-stronger)
    assert abs(builder_module._soft_bound(1e6, bound)) <= bound
    # A degenerate bound cannot produce a value outside it.
    assert builder_module._soft_bound(5.0, 0.0) == pytest.approx(0.0)


def test_pairwise_affinity_skips_shared_features_and_signals_differing_ones(
    tmp_path: Path,
) -> None:
    """An implicit comparison's gradient must land only on what differed
    between the two scenes. old-good (tag good, performer p1, studio studio-1)
    and unseen-good (tag good, performer p3, studio studio-2) share tag
    'good': its affinity must be completely unaffected by the pair. performer
    p1 (winner-only) must gain support from the comparison, and performer p3
    (loser-only, absent before since neither scene carrying it had any other
    evidence) must appear with a negative affinity. Performer watch lift is
    off here: it would give p3 evidence of its own."""
    connection = _database(tmp_path / "curator.sqlite3")
    config = replace(
        DEFAULT_CONFIG, model=replace(DEFAULT_CONFIG.model, entity_watch_lift_support=0.0)
    )
    builder = PreferenceModelBuilder(connection, config, clock_ms=lambda: REFERENCE_MS)
    feature_version = builder.build().feature_version
    feature_ids = {
        str(name): str(feature_id)
        for name, feature_id in connection.execute(
            "SELECT name, feature_id FROM feature_definition"
        )
    }

    def affinities() -> dict[str, tuple[float, float]]:
        labels = builder._training_labels(builder._scene_labels())
        scene_features = FeatureStore(connection).entity_features(feature_version, "scene")
        result = builder._affinities(scene_features, labels, builder._absolute_label_mean(labels))
        return {
            name: (result[feature_id].affinity, result[feature_id].support)
            for name, feature_id in feature_ids.items()
            if feature_id in result
        }

    before = affinities()
    assert "tag:good" in before
    assert "performer:p1" in before
    assert "performer:p3" not in before

    # old-good played from position 1 beats unseen-good shown above it.
    connection.execute(
        """
        INSERT INTO impression(impression_id, requested_at_ms, lane, config_version)
        VALUES ('imp-shared', 1, 'for_you', 'builtin')
        """
    )
    connection.executemany(
        """
        INSERT INTO impression_item(impression_id, scene_id, position, policy_score,
            reason_snapshot_json) VALUES (?, ?, ?, ?, '[]')
        """,
        (("imp-shared", "unseen-good", 0, 0.1), ("imp-shared", "old-good", 1, 0.1)),
    )
    connection.execute(
        """
        INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms,
            active_seconds, provenance, confidence, impression_id, summary_json)
        VALUES ('ps-shared', 'old-good', 100, 200, 10.0, 'direct_player', 1,
                'imp-shared', '{}')
        """
    )
    after = affinities()
    assert after["tag:good"] == pytest.approx(before["tag:good"])
    assert after["performer:p1"][1] > before["performer:p1"][1]
    assert after["performer:p3"][0] < 0


def test_watch_lift_reaches_performers_and_studios(tmp_path: Path) -> None:
    """Performers and studios get lift evidence like tags: support grows for
    those on watched scenes, and one only on unwatched scenes turns negative."""
    connection = _database(tmp_path / "curator.sqlite3")
    feature_version = (
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build().feature_version
    )
    names = {
        str(feature_id): str(name)
        for feature_id, name in connection.execute(
            "SELECT feature_id, name FROM feature_definition"
        )
    }

    def affinities(entity_support: float) -> dict[str, tuple[float, float]]:
        config = replace(
            DEFAULT_CONFIG,
            model=replace(DEFAULT_CONFIG.model, entity_watch_lift_support=entity_support),
        )
        builder = PreferenceModelBuilder(connection, config, clock_ms=lambda: REFERENCE_MS)
        labels = builder._training_labels(builder._scene_labels())
        scene_features = FeatureStore(connection).entity_features(feature_version, "scene")
        result = builder._affinities(scene_features, labels, builder._absolute_label_mean(labels))
        return {
            names[feature_id]: (item.affinity, item.support) for feature_id, item in result.items()
        }

    without, with_lift = affinities(0.0), affinities(2.0)
    for name in ("performer:p1", "studio:studio-1"):
        assert with_lift[name][1] > without[name][1], name
    assert "performer:p3" not in without
    assert with_lift["performer:p3"][0] < 0
    assert with_lift["tag:good"] == pytest.approx(without["tag:good"])


def test_retired_pair_pick_feedback_is_ignored(tmp_path: Path) -> None:
    """Answered pair picks stay in feedback as history but no longer teach the
    model: they add no scene label and no pair event."""
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, DEFAULT_CONFIG, clock_ms=lambda: REFERENCE_MS)
    labels_before = builder._scene_labels()
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
            occurred_at_ms, payload_json)
        VALUES ('cpw-old', 'unlabeled', 'curation_pair_winner', '10', 1,
                '{"pair_id": "p-old", "predicted_winner": 0.1,
                  "predicted_loser": 0.3, "selection_probability": 1.0}'),
               ('cpl-old', 'disliked', 'curation_pair_loser', '0', 1,
                '{"pair_id": "p-old", "predicted_winner": 0.1,
                  "predicted_loser": 0.3, "selection_probability": 1.0}'),
               ('cpt-old', 'unusual', 'curation_pair_tie', '5', 1, '{"pair_id": "p-tie"}')
        """
    )
    labels_after = builder._scene_labels()
    assert labels_after == labels_before
    assert "unlabeled" not in labels_after
    assert builder._implicit_skip_events() == []


def test_satiation_content_dots_match_naive_recent_loop() -> None:
    reference = REFERENCE_MS
    candidate = {"shared_a": 0.8, "shared_b": 0.6, "unique_c": 0.4}
    recents = [
        ("candidate", reference, {"shared_a": 5.0}),
        ("recent-1", reference - DAY_MS, {"shared_a": 1.0, "other": 0.2}),
        ("recent-2", reference - 3 * DAY_MS, {"shared_a": 0.3, "shared_b": 0.5}),
    ]
    context = {
        "reference": reference,
        "performers": {},
        "studios": {},
        "scene_performers": {},
        "scene_studios": {},
        "not_now": {},
        "recent_by_name": {
            "shared_a": [(0, 5.0), (1, 1.0), (2, 0.3)],
            "shared_b": [(2, 0.5)],
        },
        "recent_scene_ids": ["candidate", "recent-1", "recent-2"],
        "recent_played": [reference, reference - DAY_MS, reference - 3 * DAY_MS],
        "scene_vectors": {"candidate": candidate},
    }
    builder = PreferenceModelBuilder(None)

    naive = 0.0
    for recent_scene, played_at, vector in recents:
        if recent_scene == "candidate":
            continue
        cosine = sum(value * vector.get(name, 0.0) for name, value in candidate.items())
        days = max(0.0, (reference - played_at) / DAY_MS)
        naive = max(naive, 0.04 * cosine * math.exp(-days / 7))

    result = builder._satiation("candidate", 1.0, context)
    assert result == pytest.approx(min(builder.config.model.satiation_bound, naive), rel=1e-12)


def test_classification_data_matches_full_scores_for_lane_values(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    model_id = builder.build().model_id
    store = RecommendationModelStore(connection)
    full = store.scores(model_id)
    lean = store.classification_data(model_id)
    assert set(lean) == set(full)
    for scene_id, lean_score in lean.items():
        full_score = full[scene_id]
        assert lean_score.current_fit == full_score.current_fit
        assert lean_score.confidence == full_score.confidence
        assert lean_score.metadata_confidence == full_score.metadata_confidence
        assert lean_score.recovery == full_score.recovery
        assert lean_score.direct_appeal == full_score.direct_appeal
        assert lean_score.direct_confidence == full_score.direct_confidence
        assert lean_score.appeal == full_score.appeal
        assert lean_score.eligibility == full_score.eligibility
        assert lean_score.neighbors == full_score.neighbors
        for family in (
            "content",
            "content_neighbor",
            "performer_identity",
            "performer_similarity",
            "studio",
            "structure",
        ):
            assert lean_score.components[family]["value"] == pytest.approx(
                full_score.components[family]["value"], rel=1e-12
            )
        assert (
            lean_score.components["direct"]["signals"] == full_score.components["direct"]["signals"]
        )


def test_classification_data_falls_back_for_pre_classification_artifacts(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    # The migrated core model_scene_score predates the classification_json column;
    # classification_data must fall back to the full scores read for such artifacts.
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute(
            """
            INSERT INTO model_scene_score(
                model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery,
                components_json, neighbors_json, eligibility_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "model",
                "scene",
                0.0,
                0.1,
                0.2,
                0.3,
                0.4,
                0.5,
                0.6,
                0.7,
                '{"content": {"value": 0.25}}',
                "[]",
                '{"eligible": true, "reasons": []}',
            ),
        )
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    store = RecommendationModelStore(connection)
    lean = store.classification_data("model")
    assert lean["scene"].components["content"]["value"] == 0.25
    assert lean["scene"].appeal == 0.3


def test_complete_model_is_bounded_reproducible_and_applies_cooldown(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)

    first = builder.build()
    second = builder.build()
    scores = RecommendationModelStore(connection).scores(first.model_id)

    assert second.model_id == first.model_id
    assert second.reused is True
    statements = []
    connection.set_trace_callback(statements.append)
    ReasonGraphStore(connection).ensure(first.model_id, set(scores))
    connection.set_trace_callback(None)
    assert not any(
        statement.startswith(("INSERT INTO model_scene_reason", "DELETE FROM model_scene_reason"))
        for statement in statements
    )
    assert {
        "feature_lookup",
        "feature_build",
        "similarity",
        "scoring",
        "database_writing",
        "lane_classification",
        "score_first_ordering",
        "varied_ordering",
        "reason_generation",
        "sqlite_index_creation",
        "indexing",
        "validation",
        "publication",
        "cleanup",
        "total",
    } <= set(first.stage_timings_ms)
    assert set(scores) == {
        "old-good",
        "recent-good",
        "unseen-good",
        "disliked",
        "unlabeled",
        "unusual",
    }
    assert all(-1 <= score.appeal <= 1 for score in scores.values())
    assert all(-1 <= score.current_fit <= 1 for score in scores.values())
    assert all(0 <= score.confidence <= 1 for score in scores.values())
    assert not any(
        query in " ".join(statement.split())
        for statement in statements
        for query in (
            "SELECT performer_id FROM scene_performer WHERE scene_id=",
            "SELECT studio_id FROM source_scene WHERE scene_id=",
            "SELECT occurred_at_ms FROM feedback WHERE scene_id=",
        )
    )
    assert scores["old-good"].direct_confidence == pytest.approx(0.7135, abs=0.001)
    assert scores["old-good"].current_fit > scores["recent-good"].current_fit
    assert scores["disliked"].current_fit == pytest.approx(scores["disliked"].appeal)
    assert scores["disliked"].eligibility["eligible"] is False
    exclusion_reasons = scores["disliked"].eligibility["reasons"]
    assert isinstance(exclusion_reasons, list)
    assert "current_thumb_down" in exclusion_reasons
    assert connection.execute("SELECT count(*) FROM feature_affinity").fetchone()[0] > 0
    assert connection.execute(
        "SELECT 1 FROM model_lane_order_state WHERE model_id=?", (first.model_id,)
    ).fetchone()
    assert (
        connection.execute(
            "SELECT count(*) FROM model_scene_reason WHERE model_id=?", (first.model_id,)
        ).fetchone()[0]
        == 0
    )
    assert {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT ordering FROM model_lane_order WHERE model_id=?",
            (first.model_id,),
        )
    } == {"score_first", "varied"}
    assert {
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT lane FROM model_lane_order
            WHERE model_id=? AND ordering='score_first'
            """,
            (first.model_id,),
        )
    } == {"for_you"}
    # Both orderings materialize independently for for_you; this fixture's
    # candidate pool is too small (Blind Spots, unlike the Adventure lane it
    # replaced, gates rather than admitting every eligible scene) to also
    # exercise varied actually reordering score_first here — that is covered
    # directly in tests/ranking/test_slate.py.
    varied_order = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT scene_id FROM model_lane_order
            WHERE model_id=? AND lane='for_you' AND ordering='varied'
            ORDER BY position
            """,
            (first.model_id,),
        )
    ]
    score_first_order = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT scene_id FROM model_lane_order
            WHERE model_id=? AND lane='for_you' AND ordering='score_first'
            ORDER BY position
            """,
            (first.model_id,),
        )
    ]
    assert varied_order and set(varied_order) == set(score_first_order)
    assert scores["unseen-good"].neighbors
    assert all("scene_id" in neighbor for neighbor in scores["unseen-good"].neighbors)
    assert {str(neighbor["scene_id"]) for neighbor in scores["unseen-good"].neighbors} <= {
        "old-good",
        "recent-good",
    }
    neighbor_component = scores["unseen-good"].components["content_neighbor"]
    assert isinstance(neighbor_component, dict)
    assert neighbor_component["vector_mode"] == "preference_discriminative"
    assert int(neighbor_component["discriminative_tag_count"]) > 0

    known_similarity = scores["old-good"].components["performer_similarity"]
    new_similarity = scores["unseen-good"].components["performer_similarity"]
    assert isinstance(known_similarity, dict) and isinstance(new_similarity, dict)
    known_performers = known_similarity["performers"]
    new_performers = new_similarity["performers"]
    assert isinstance(known_performers, list) and isinstance(new_performers, list)
    known_performer = known_performers[0]
    new_performer = new_performers[0]
    assert isinstance(known_performer, dict) and isinstance(new_performer, dict)
    assert float(known_performer["novelty_weight"]) < float(new_performer["novelty_weight"])

    for score in scores.values():
        for family, bound in (
            ("content", builder.config.model.content_bound),
            ("performer_identity", builder.config.model.performer_identity_bound),
            ("performer_similarity", builder.config.model.performer_similarity_bound),
            ("studio", builder.config.model.studio_bound),
            ("content_neighbor", builder.config.model.neighbor_bound),
        ):
            component = score.components[family]
            assert isinstance(component, dict)
            assert abs(float(component["value"])) <= bound


def test_direct_tag_sentiment_overrides_and_clear_restores_inference(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    baseline = builder.build()

    def affinity(model_id: str) -> tuple[float, dict[str, object]]:
        row = connection.execute(
            """
            SELECT a.affinity, a.metadata_json FROM feature_affinity a
            JOIN feature_definition d USING(feature_id)
            WHERE a.model_id=? AND d.name='tag:good'
            """,
            (model_id,),
        ).fetchone()
        return float(row[0]), json.loads(row[1])

    inferred, _ = affinity(baseline.model_id)
    store = InteractionStore(connection)
    store.submit_tag_preferences(
        [{"preference_id": "negative", "tag_id": "good", "value": -1, "occurred_at_ms": 10}]
    )
    negative = builder.build()
    negative_value, metadata = affinity(negative.model_id)
    assert negative_value < inferred
    assert metadata["declared_preference"] == -1

    store.submit_tag_preferences(
        [{"preference_id": "neutral", "tag_id": "good", "value": 0, "occurred_at_ms": 20}]
    )
    neutral = builder.build()
    assert abs(affinity(neutral.model_id)[0]) < abs(inferred)

    store.submit_tag_preferences(
        [{"preference_id": "positive", "tag_id": "good", "value": 1, "occurred_at_ms": 30}]
    )
    positive = builder.build()
    assert affinity(positive.model_id)[0] > inferred

    store.submit_tag_preferences(
        [{"preference_id": "clear", "tag_id": "good", "value": None, "occurred_at_ms": 40}]
    )
    restored = builder.build()
    assert affinity(restored.model_id)[0] == pytest.approx(inferred)


def test_unanswered_child_tags_inherit_the_nearest_answered_ancestor(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    # good > bad > unusual: "unusual" has an unanswered parent and an
    # answered grandparent.
    connection.executemany(
        "INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES (?, ?)",
        (("bad", "good"), ("unusual", "bad")),
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)

    def metadata(model_id: str) -> dict[str, dict[str, object]]:
        return {
            str(name): json.loads(raw)
            for name, raw in connection.execute(
                """
                SELECT d.name, a.metadata_json FROM feature_affinity a
                JOIN feature_definition d USING(feature_id) WHERE a.model_id=?
                """,
                (model_id,),
            )
        }

    # Without answers nothing inherits; this build also classifies the tags.
    baseline = metadata(builder.build().model_id)
    assert not any("inherited_preference" in item for item in baseline.values())
    store = InteractionStore(connection)
    store.submit_tag_preferences(
        [{"preference_id": "g", "tag_id": "good", "value": 1, "occurred_at_ms": 10}]
    )
    first = metadata(builder.build().model_id)
    assert first["tag:bad"]["inherited_preference"] == 1
    assert first["tag:unusual"]["inherited_from"] == ["good"]
    assert "inherited_preference" not in first["tag:good"]

    # The nearest answered generation wins, and an own answer replaces inheritance.
    store.submit_tag_preferences(
        [{"preference_id": "b", "tag_id": "bad", "value": -0.5, "occurred_at_ms": 20}]
    )
    second = metadata(builder.build().model_id)
    assert "inherited_preference" not in second["tag:bad"]
    assert second["tag:unusual"]["inherited_preference"] == -0.5
    assert second["tag:unusual"]["inherited_from"] == ["bad"]

    # Never answers do not propagate.
    store.submit_tag_preferences(
        [
            {
                "preference_id": "g2",
                "tag_id": "good",
                "value": None,
                "blocked": True,
                "occurred_at_ms": 30,
            },
            {"preference_id": "b2", "tag_id": "bad", "value": None, "occurred_at_ms": 30},
        ]
    )
    third = metadata(builder.build().model_id)
    assert not any("inherited_preference" in item for item in third.values())


def test_watch_lift_learns_from_what_is_chosen_for_watching(tmp_path: Path) -> None:
    """Outcome labels cannot see the choice to watch; lift compares a tag's share
    of watched scenes with its share of the library."""

    def affinities(support: float, directory: str) -> dict[str, tuple[float, float]]:
        connection = _database(tmp_path / directory / "curator.sqlite3")
        config = replace(
            DEFAULT_CONFIG, model=replace(DEFAULT_CONFIG.model, watch_lift_support=support)
        )
        model_id = (
            PreferenceModelBuilder(connection, config, clock_ms=lambda: REFERENCE_MS)
            .build()
            .model_id
        )
        return {
            str(name): (float(affinity), float(effective_support))
            for name, affinity, effective_support in connection.execute(
                """
                SELECT d.name, a.affinity, a.effective_support FROM feature_affinity a
                JOIN feature_definition d USING(feature_id) WHERE a.model_id=?
                """,
                (model_id,),
            )
        }

    (tmp_path / "off").mkdir()
    (tmp_path / "on").mkdir()
    off, on = affinities(0.0, "off"), affinities(2.0, "on")
    # "unusual" is on 1 of 6 scenes and none of the 3 watched ones: it was
    # passed over. Without lift no evidence touches it at all.
    assert "tag:unusual" not in off
    k, base = 10.0, 1 / 6
    lift = math.log(((0 + k * base) / (3 + k)) / base)
    mass = 3 * base
    pseudo = 2.0 * mass / (mass + k)
    assert on["tag:unusual"][1] == pytest.approx(pseudo)
    assert on["tag:unusual"][0] == pytest.approx(pseudo * math.tanh(lift) / (1.0 + pseudo))
    assert on["tag:unusual"][0] < 0
    # "bad" is rare in the library but was chosen for watching (then thumbed
    # down): lift raises it relative to outcomes alone.
    assert on["tag:bad"][0] > off["tag:bad"][0]


def test_direct_tag_sentiment_does_not_rewrite_behavioral_neighbors(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO scene_tag(scene_id, tag_id, provenance)
        VALUES ('unseen-good', 'unusual', 'scene')
        """
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    baseline = RecommendationModelStore(connection).scores(builder.build().model_id)["unseen-good"]

    InteractionStore(connection).submit_tag_preferences(
        [{"preference_id": "unusual", "tag_id": "unusual", "value": 1, "occurred_at_ms": 10}]
    )
    rated = RecommendationModelStore(connection).scores(builder.build().model_id)["unseen-good"]

    assert float(rated.components["content"]["value"]) > float(
        baseline.components["content"]["value"]
    )
    assert rated.components["content_neighbor"] == baseline.components["content_neighbor"]
    assert rated.neighbors == baseline.neighbors


def test_model_build_reports_stage_progress(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    progress: list[tuple[int, int]] = []

    PreferenceModelBuilder(
        connection,
        clock_ms=lambda: REFERENCE_MS,
        progress=lambda processed, total: progress.append((processed, total)),
    ).build()

    assert {
        (250, 1_000),
        (300, 1_000),
        (350, 1_000),
        (780, 1_000),
        (850, 1_000),
        (940, 1_000),
        (980, 1_000),
        (1_000, 1_000),
    } <= set(progress)
    assert [processed for processed, _ in progress] == sorted(
        processed for processed, _ in progress
    )
    assert progress[-1] == (1_000, 1_000)


def test_wrong_metadata_is_not_reused_but_direct_scene_evidence_remains(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms)
        VALUES ('metadata', 'old-good', 'metadata_wrong', ?)
        """,
        (REFERENCE_MS,),
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    labels = builder._scene_labels()

    assert "old-good" in labels
    assert "old-good" not in builder._training_labels(labels)

    result = builder.build()
    assert connection.execute(
        "SELECT 1 FROM direct_scene_state WHERE model_id=? AND scene_id='old-good'",
        (result.model_id,),
    ).fetchone()


def test_feedback_for_a_scene_deleted_from_stash_does_not_crash_the_build(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    # feedback carries no foreign key to source_scene, so it can still reference a scene
    # deleted from Stash after the feedback was given (kept as user-facing history) — unlike
    # behavior_event and play_session, which cascade out with the scene.
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms)
        VALUES ('orphaned', 'removed-scene', 'thumb_up', ?)
        """,
        (REFERENCE_MS,),
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    labels = builder._scene_labels()
    assert "removed-scene" in labels

    result = builder.build()

    assert not connection.execute(
        "SELECT 1 FROM direct_scene_state WHERE model_id=? AND scene_id='removed-scene'",
        (result.model_id,),
    ).fetchone()


def test_failed_rebuild_cannot_replace_published_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    published = builder.build()
    connection.execute(
        """
        INSERT INTO behavior_event(
            event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
            provenance, payload_json
        ) VALUES ('new-event', 'occasion_outcome', 'unlabeled', ?, 0.5, 1,
                  'synthetic', '{"primary_signal":"view"}')
        """,
        (REFERENCE_MS,),
    )

    def fail_scores(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic model failure")

    monkeypatch.setattr(PreferenceModelBuilder, "_scores", fail_scores)
    with pytest.raises(RuntimeError, match="synthetic model failure"):
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    current = RecommendationModelStore(connection).current_model_id()
    assert current == published.model_id
    statuses = [
        row[0]
        for row in connection.execute("SELECT status FROM model_version ORDER BY created_at_ms")
    ]
    assert "published" in statuses
    assert "failed" in statuses


def test_failed_lane_order_build_cannot_replace_published_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    published = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    connection.execute(
        """
        INSERT INTO behavior_event(
            event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
            provenance, payload_json
        ) VALUES ('new-order-event', 'occasion_outcome', 'unlabeled', ?, 0.4, 1,
                  'synthetic', '{"primary_signal":"view"}')
        """,
        (REFERENCE_MS,),
    )
    monkeypatch.setattr(
        "curator.ranking.SlateBuilder.materialize",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic order failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic order failure"):
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    assert RecommendationModelStore(connection).current_model_id() == published.model_id


def test_all_positive_cold_start_learns_relative_lift_without_saturating(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("DELETE FROM feedback")
    connection.execute(
        """
        UPDATE behavior_event SET outcome=0.2, confidence=0.45,
          payload_json='{"primary_signal":"view"}'
        WHERE scene_id='disliked'
        """
    )

    built = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    scores = RecommendationModelStore(connection).scores(built.model_id)
    affinities = [
        float(row[0])
        for row in connection.execute(
            "SELECT affinity FROM feature_affinity WHERE model_id=?", (built.model_id,)
        )
    ]

    assert min(affinities) < 0 < max(affinities)
    assert all(score.appeal < 0.999 for score in scores.values())
    assert all(score.confidence < 0.95 for score in scores.values())
    assert all(
        abs(float(score.components["content_neighbor"]["value"]))
        < DEFAULT_CONFIG.model.neighbor_bound
        for score in scores.values()
        if isinstance(score.components["content_neighbor"], dict)
    )


def test_model_build_refreshes_feature_version_after_feature_config_change(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    first = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    changed_feature = replace(DEFAULT_CONFIG.feature, marker_weight=0.25)
    changed_config = replace(DEFAULT_CONFIG, feature=changed_feature)

    second = PreferenceModelBuilder(
        connection, changed_config, clock_ms=lambda: REFERENCE_MS
    ).build()

    assert second.feature_version != first.feature_version
    assert second.model_id != first.model_id


def test_model_build_version_invalidates_published_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    first = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    monkeypatch.setattr(
        builder_module, "MODEL_BUILD_VERSION", builder_module.MODEL_BUILD_VERSION + 1
    )

    second = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    assert second.reused is False
    assert second.model_id != first.model_id


def test_scoring_fingerprint_invalidates_published_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An algorithm change with unchanged data and config must rebuild.

    Before the fingerprint reached the digest this returned reused=True and
    served the previous algorithm's artifact.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    first = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    monkeypatch.setattr(builder_module, "SCORING_FINGERPRINT", "0000000000000000")

    second = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    assert second.reused is False
    assert second.model_id != first.model_id
    assert second.feature_version == first.feature_version


def test_implicit_skip_events_emit_virtual_pairs(tmp_path: Path) -> None:
    """Issue #146 Channel A: a play at position P in an impression makes every
    earlier-position card a loser and the played card the winner. Confidence
    uses the stored policy_score gap (contradiction > 0, confirmation ~ 0) with
    the implicit base."""
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO impression(impression_id, requested_at_ms, lane, config_version)
        VALUES ('imp-1', 1, 'for_you', 'builtin')
        """
    )
    connection.executemany(
        """
        INSERT INTO impression_item(impression_id, scene_id, position, policy_score,
            reason_snapshot_json) VALUES (?, ?, ?, ?, '[]')
        """,
        (
            ("imp-1", "old-good", 0, 0.9),
            ("imp-1", "recent-good", 1, 0.8),
            ("imp-1", "unseen-good", 2, 0.3),
            ("imp-1", "disliked", 3, 0.5),
        ),
    )
    # Play 'unseen-good' (position 2) with observed playback, linked to imp-1.
    connection.execute(
        """
        INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms,
            active_seconds, provenance, confidence, impression_id, summary_json)
        VALUES ('ps-1', 'unseen-good', 100, 200, 10.0, 'direct_player', 1, 'imp-1', '{}')
        """
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    events = builder._implicit_skip_events()
    # Winner at position 2 -> positions 0 and 1 are losers; position 3 is after.
    assert sorted((e.winner_scene, e.loser_scene) for e in events) == [
        ("unseen-good", "old-good"),
        ("unseen-good", "recent-good"),
    ]
    by_loser = {e.loser_scene: e.confidence for e in events}
    # old-good scored 0.9 vs winner 0.3 -> surprise 0.6; recent-good 0.8 -> 0.5.
    assert by_loser["old-good"] == pytest.approx(
        DEFAULT_CONFIG.model.implicit_skip_confidence
        * (1 + DEFAULT_CONFIG.model.implicit_skip_surprise_bonus * 0.6)
    )
    assert by_loser["recent-good"] == pytest.approx(
        DEFAULT_CONFIG.model.implicit_skip_confidence
        * (1 + DEFAULT_CONFIG.model.implicit_skip_surprise_bonus * 0.5)
    )
    # Implicit signal never outranks explicit feedback.
    assert DEFAULT_CONFIG.model.implicit_skip_confidence < (
        DEFAULT_CONFIG.model.curation_rating_confidence
    )


def test_implicit_skip_confirmation_adds_no_surprise(tmp_path: Path) -> None:
    """A confirmation (winner scored higher than the loser) yields surprise 0,
    so the confidence is just the implicit base — no surprise bonus."""
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO impression(impression_id, requested_at_ms, lane, config_version)
        VALUES ('imp-1', 1, 'for_you', 'builtin')
        """
    )
    connection.executemany(
        """
        INSERT INTO impression_item(impression_id, scene_id, position, policy_score,
            reason_snapshot_json) VALUES (?, ?, ?, ?, '[]')
        """,
        (
            ("imp-1", "old-good", 0, 0.3),
            ("imp-1", "unseen-good", 1, 0.9),
        ),
    )
    connection.execute(
        """
        INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms,
            active_seconds, provenance, confidence, impression_id, summary_json)
        VALUES ('ps-1', 'unseen-good', 100, 200, 10.0, 'direct_player', 1, 'imp-1', '{}')
        """
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    events = builder._implicit_skip_events()
    assert len(events) == 1
    # winner 0.9 > loser 0.3 -> surprise = max(0, 0.3 - 0.9) = 0.
    assert events[0].confidence == pytest.approx(DEFAULT_CONFIG.model.implicit_skip_confidence)


def test_implicit_skip_raw_click_never_emits_pairs(tmp_path: Path) -> None:
    """A raw click (no observed playback, no thumb_up) never emits implicit
    skip pairs; only played (observed) or thumbed scenes trigger them."""
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO impression(impression_id, requested_at_ms, lane, config_version)
        VALUES ('imp-1', 1, 'for_you', 'builtin')
        """
    )
    connection.executemany(
        """
        INSERT INTO impression_item(impression_id, scene_id, position, policy_score,
            reason_snapshot_json) VALUES (?, ?, ?, ?, '[]')
        """,
        (
            ("imp-1", "old-good", 0, 0.9),
            ("imp-1", "unseen-good", 1, 0.8),
        ),
    )
    # A session with no observed playback is just a click — no signal.
    connection.execute(
        """
        INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms,
            active_seconds, provenance, confidence, impression_id, summary_json)
        VALUES ('ps-1', 'unseen-good', 100, 101, 0.0, 'direct_player', 1, 'imp-1',
                '{"played_ranges": [], "maximum_position_seconds": 0, "start_position_seconds": 0}')
        """
    )
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    assert builder._implicit_skip_events() == []


def test_playback_change_reuses_features_but_rebuilds_model(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    first = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    connection.execute(
        "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, 0)",
        ("unseen-good", REFERENCE_MS - 2 * DAY_MS),
    )

    second = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    assert second.feature_version == first.feature_version
    assert second.model_id != first.model_id


def test_build_model_cli_publishes_complete_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "curator.sqlite3"
    connection = _database(database)
    connection.close()

    assert run(["--db", str(database), "build-model", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scene_count"] == 6
    assert payload["labeled_scene_count"] == 3
    assert payload["model_id"].startswith("model-")
