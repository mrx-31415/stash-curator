from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.model import ModelUpdateCoordinator, PreferenceModelBuilder
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


def test_sidecar_configuration_is_validated(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    api = CuratorAPI(connection)

    config = api.update_config({"page_size": 30}, now_ms=10)["config"]
    assert config["page_size"] == 30
    assert config["auto_sync_hours"] == 24
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
