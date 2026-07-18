import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from curator.cli import run
from curator.config import DEFAULT_CONFIG
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
            ("p2", "Performer Two", 0, "Blonde", 168, "34D-25-36", "p2"),
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


def test_complete_model_is_bounded_reproducible_and_applies_cooldown(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)

    first = builder.build()
    second = builder.build()
    scores = RecommendationModelStore(connection).scores(first.model_id)

    assert second.model_id == first.model_id
    assert second.reused is True
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
    assert scores["old-good"].direct_confidence == pytest.approx(0.7135, abs=0.001)
    assert scores["old-good"].current_fit > scores["recent-good"].current_fit
    assert scores["disliked"].current_fit == pytest.approx(scores["disliked"].appeal)
    assert scores["disliked"].eligibility["eligible"] is False
    exclusion_reasons = scores["disliked"].eligibility["reasons"]
    assert isinstance(exclusion_reasons, list)
    assert "current_thumb_down" in exclusion_reasons
    assert connection.execute("SELECT count(*) FROM feature_affinity").fetchone()[0] > 0
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
