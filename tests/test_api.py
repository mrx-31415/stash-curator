from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.model import ModelUpdateCoordinator, PreferenceModelBuilder
from curator.storage import connect_database
from tests.model.test_builder import REFERENCE_MS, _database


def test_slate_api_records_impression_and_bundles_explanations(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    result = CuratorAPI(connection).get_slate(
        "for_you", 3, impression_id="api-impression", now_ms=REFERENCE_MS
    )

    assert result["impression_id"] == "api-impression"
    assert result["config_updated_at_ms"] == 0
    assert result["model_pending"] is False
    assert result["rebuilding"] is False
    assert set(result["timings_ms"]) == {
        "model_update",
        "ranking",
        "impression",
        "explanations",
        "total",
    }
    assert len(result["items"]) == 3
    assert all(item["explanation"] for item in result["items"])
    explained = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT scene_id FROM model_scene_reason WHERE model_id=?",
            (result["model_id"],),
        )
    }
    assert explained <= {str(item["scene_id"]) for item in result["items"]}
    assert (
        connection.execute(
            "SELECT count(*) FROM impression WHERE impression_id='api-impression'"
        ).fetchone()[0]
        == 1
    )
    excluded = {item["scene_id"] for item in result["items"]}
    replacement = CuratorAPI(connection).get_slate(
        "for_you", 1, exclude_scene_ids=excluded, now_ms=REFERENCE_MS
    )
    assert replacement["items"][0]["scene_id"] not in excluded


def test_slate_api_never_builds_a_pending_model_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    ModelUpdateCoordinator(connection, clock_ms=lambda: REFERENCE_MS).request("feedback")
    monkeypatch.setattr(
        PreferenceModelBuilder,
        "build",
        lambda *_args: (_ for _ in ()).throw(AssertionError("inline model build")),
    )

    result = CuratorAPI(connection).get_slate("for_you", 1, now_ms=REFERENCE_MS)

    assert result["model_pending"] is True
    assert result["items"]


def test_scene_inspector_returns_complete_score_state(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    inspected = CuratorAPI(connection).inspector("scene", "old-good")

    assert inspected["entity_type"] == "scene"
    assert inspected["score"]["scene_id"] == "old-good"
    assert inspected["explanation"]["summary"]


def test_similar_scenes_blend_similarity_with_appeal_and_explain_relationships(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    result = CuratorAPI(connection).similar(
        "scene", "old-good", 5, impression_id="similar-impression", now_ms=REFERENCE_MS
    )

    assert result["entity_type"] == "scene"
    assert result["items"]
    assert result["items"][0]["entity_id"] != "old-good"
    assert all(
        item["rank_score"] == pytest.approx(0.7 * item["similarity"] + 0.3 * item["appeal"])
        for item in result["items"]
    )
    assert any("shared_content" in item["relationships"] for item in result["items"])
    assert all(item["label"] for item in result["items"])
    impression = connection.execute(
        "SELECT lane, request_context_json FROM impression WHERE impression_id='similar-impression'"
    ).fetchone()
    assert impression["lane"] == "similar"
    assert '"provenance":"similar"' in impression["request_context_json"]


def test_similar_performers_are_preference_aware_and_inspectable(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    result = CuratorAPI(connection).similar("performer", "p1", 2)

    assert [item["entity_id"] for item in result["items"]] == ["p3", "p2"]
    assert result["items"][0]["rank_score"] > result["items"][1]["rank_score"]
    assert result["items"][0]["details"]["blocks"]


def test_local_similarity_filters_gender(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_performer SET gender='FEMALE' WHERE performer_id='p3'")
    connection.execute("UPDATE source_performer SET gender='MALE' WHERE performer_id='p2'")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    result = CuratorAPI(connection).similar("performer", "p1", gender="FEMALE")

    assert [item["entity_id"] for item in result["items"]] == ["p3"]


def test_similar_scene_does_not_wait_for_impression_write_lock(tmp_path: Path) -> None:
    path = tmp_path / "curator.sqlite3"
    connection = _database(path)
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    locker = connect_database(path)
    locker.execute("BEGIN IMMEDIATE")
    try:
        result = CuratorAPI(connection).similar(
            "scene", "old-good", impression_id="locked-impression"
        )
    finally:
        locker.rollback()
        locker.close()

    assert result["items"]
    assert result["impression_id"] is None
    assert (
        connection.execute(
            "SELECT 1 FROM impression WHERE impression_id='locked-impression'"
        ).fetchone()
        is None
    )


def test_sidecar_configuration_is_validated(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)

    config = api.update_config({"page_size": 30}, now_ms=10)["config"]
    assert config["page_size"] == 30
    with pytest.raises(ValueError, match="page_size"):
        api.update_config({"page_size": 0})
    with pytest.raises(ValueError, match="unknown"):
        api.update_config({"mystery": True})


def test_pruning_queue_requires_an_explicit_keep_or_remove_decision(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
        VALUES ('old-good', 'review', 1, 1, 'review it')
        """
    )
    api = CuratorAPI(connection)

    assert api.pruning_queue()["items"][0]["scene_id"] == "old-good"
    assert api.update_pruning("old-good", "keep", now_ms=2)["state"] == "keep"
    assert api.pruning_queue()["items"] == []


def test_prune_candidates_are_reversible_tags_not_deletions(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    api = CuratorAPI(connection)

    candidates = api.prune_candidates("explicit")
    assert [item["scene_id"] for item in candidates["items"]] == ["disliked"]
    assert "Explicit negative feedback" in candidates["items"][0]["evidence"]
    assert api.prune_candidates("suspects", aggressiveness=0.5)["aggressiveness"] == 0.5
    with pytest.raises(ValueError, match="aggressiveness"):
        api.prune_candidates("suspects", aggressiveness=1.1)

    api.record_prune_tags(["disliked"], True, "prune-tag", "[Prune]")
    assert api.prune_candidates("tagged")["items"][0]["scene_id"] == "disliked"
    assert (
        connection.execute(
            "SELECT state FROM pruning_candidate WHERE scene_id='disliked'"
        ).fetchone()[0]
        == "remove"
    )

    api.record_prune_tags(["disliked"], False, "prune-tag", "[Prune]")
    assert api.prune_candidates("tagged")["items"] == []
    assert (
        connection.execute("SELECT 1 FROM pruning_candidate WHERE scene_id='disliked'").fetchone()
        is None
    )


def test_explicit_negative_feedback_reopens_a_dismissed_prune_suspect(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)
    api.dismiss_prune_candidate("unusual", now_ms=10)

    api.submit_feedback(
        [
            {
                "feedback_id": "later-down",
                "scene_id": "unusual",
                "feedback_type": "thumb_down",
                "occurred_at_ms": 20,
            }
        ]
    )

    row = connection.execute(
        "SELECT state, reason FROM pruning_candidate WHERE scene_id='unusual'"
    ).fetchone()
    assert tuple(row) == ("review", "Thumbs down")


def test_never_show_can_be_reversed_explicitly(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO exclusion(
            exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms
        ) VALUES ('excluded', 'scene', 'old-good', 'never_show', 1)
        """
    )
    api = CuratorAPI(connection)

    assert api.exclusions()["items"][0]["scene_id"] == "old-good"
    assert api.reverse_exclusion("old-good", now_ms=2)["reversed"] is True
    assert api.exclusions()["items"] == []
