from pathlib import Path

import pytest

from curator.interactions import InteractionStore
from curator.model import ModelUpdateCoordinator, PreferenceModelBuilder
from curator.ranking import SlateBuilder
from tests.model.test_builder import REFERENCE_MS, _database


def test_impressions_and_feedback_are_idempotent(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    slate = SlateBuilder(connection).recommend("for_you", 3)
    store = InteractionStore(connection)
    store.record_impression("impression", slate, REFERENCE_MS)
    store.record_impression("impression", slate, REFERENCE_MS)
    scene_id = slate.items[0].scene_id
    qualified = {
        "impression_id": "impression",
        "scene_id": scene_id,
        "occurred_at_ms": REFERENCE_MS + 1_000,
    }
    assert connection.execute("SELECT count(*) FROM recommendation_history").fetchone()[0] == 0
    assert store.qualify_impressions([qualified]) == 1
    assert store.qualify_impressions([qualified]) == 0
    assert connection.execute("SELECT count(*) FROM recommendation_history").fetchone()[0] == 1
    feedback = {
        "feedback_id": "feedback",
        "scene_id": scene_id,
        "feedback_type": "thumb_up",
        "occurred_at_ms": REFERENCE_MS,
        "impression_id": "impression",
    }

    assert store.submit_feedback([feedback]) == 1
    assert store.submit_feedback([feedback]) == 0
    assert connection.execute("SELECT count(*) FROM impression").fetchone()[0] == 1
    assert (
        connection.execute("SELECT count(*) FROM feedback WHERE feedback_id='feedback'").fetchone()[
            0
        ]
        == 1
    )


def test_tag_preferences_validate_replace_clear_and_ignore_stale_retries(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    store = InteractionStore(connection)
    positive = {
        "preference_id": "positive",
        "tag_id": "good",
        "value": 1,
        "occurred_at_ms": 20,
    }
    stale = {**positive, "preference_id": "stale", "value": -1, "occurred_at_ms": 10}
    clear = {**positive, "preference_id": "clear", "value": None, "occurred_at_ms": 30}

    assert store.submit_tag_preferences([positive]) == 1
    assert store.submit_tag_preferences([positive]) == 0
    assert store.submit_tag_preferences([stale]) == 1
    assert (
        connection.execute(
            "SELECT value FROM direct_tag_preference WHERE tag_id='good'"
        ).fetchone()[0]
        == 1
    )
    assert store.submit_tag_preferences([clear]) == 1
    assert (
        connection.execute("SELECT 1 FROM direct_tag_preference WHERE tag_id='good'").fetchone()
        is None
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM direct_tag_preference_history WHERE tag_id='good'"
        ).fetchone()[0]
        == 3
    )

    with pytest.raises(ValueError, match="five-point"):
        store.submit_tag_preferences([{**positive, "preference_id": "bad", "value": 0.25}])
    with pytest.raises(ValueError, match="unsupported"):
        store.submit_tag_preferences([{**positive, "preference_id": "unknown", "tag_id": "x"}])


def test_direct_sessions_record_views_and_quick_replacement(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    store = InteractionStore(connection)
    original = {
        "session_id": "original",
        "scene_id": "old-good",
        "started_at_ms": 1_000,
        "ended_at_ms": 11_000,
        "active_seconds": 10,
        "origin": "stash",
        "source_route": "/scenes/old-good",
        "start_position_seconds": 0,
        "maximum_position_seconds": 10,
        "final_position_seconds": 10,
    }
    replacement = {
        **original,
        "session_id": "replacement",
        "scene_id": "recent-good",
        "started_at_ms": 20_000,
        "ended_at_ms": 80_000,
        "active_seconds": 60,
        "maximum_position_seconds": 60,
        "final_position_seconds": 60,
    }

    assert store.submit_sessions([original, replacement]) == 2
    assert store.submit_sessions([original, replacement]) == 0
    signals = {
        row[0]
        for row in connection.execute(
            "SELECT payload_json FROM behavior_event WHERE provenance='direct_player'"
        )
    }
    assert any('"primary_signal":"view"' in item for item in signals)
    # Stash-origin sessions do not create Curator selection-regret evidence.
    assert not any('"primary_signal":"quick_replacement"' in item for item in signals)


def test_session_without_observed_playback_records_no_view_evidence(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    store = InteractionStore(connection)
    unobserved = {
        "session_id": "opened-only",
        "scene_id": "watched-elsewhere",
        "started_at_ms": 1_000,
        "ended_at_ms": 31_000,
        "active_seconds": 0,
        "origin": "stash",
        "source_route": "/scenes/watched-elsewhere",
        "start_position_seconds": 0,
        "maximum_position_seconds": 0,
        "final_position_seconds": 0,
    }

    assert store.submit_sessions([unobserved]) == 1

    assert (
        connection.execute(
            "SELECT count(*) FROM play_session WHERE scene_id='watched-elsewhere'"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM behavior_event WHERE scene_id='watched-elsewhere'"
        ).fetchone()[0]
        == 0
    )
    # A page open that produced no evidence must not wake "Apply recent Curator
    # feedback" on the next Curator visit; otherwise plain browsing would keep
    # marking the model dirty forever.
    assert not ModelUpdateCoordinator(connection).status().pending


def test_unobserved_session_is_never_graded_as_abandoned(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    store = InteractionStore(connection)
    connection.execute(
        """
        INSERT INTO impression(impression_id, requested_at_ms, lane, model_id, config_version)
        VALUES ('impression', 1, 'best_bets', NULL, 'config')
        """
    )
    curator_choice = {
        "session_id": "curator-choice",
        "scene_id": "chosen",
        "started_at_ms": 1_000,
        "ended_at_ms": 31_000,
        "active_seconds": 0,
        "origin": "curator",
        "impression_id": "impression",
        "source_route": "/plugins/stash-curator",
        "start_position_seconds": 0,
        "maximum_position_seconds": 0,
        "final_position_seconds": 0,
    }
    replacement = {
        **curator_choice,
        "session_id": "replacement",
        "scene_id": "next-scene",
        "started_at_ms": 60_000,
        "ended_at_ms": 180_000,
        "active_seconds": 120,
        "maximum_position_seconds": 120,
        "final_position_seconds": 120,
    }

    assert store.submit_sessions([curator_choice, replacement]) == 2

    assert (
        connection.execute(
            "SELECT count(*) FROM behavior_event WHERE scene_id='chosen'"
        ).fetchone()[0]
        == 0
    )


def test_never_show_and_pruning_apply_operational_state(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    store = InteractionStore(connection)
    assert (
        store.submit_feedback(
            [
                {
                    "feedback_id": "never",
                    "scene_id": "old-good",
                    "feedback_type": "never_show",
                    "occurred_at_ms": 10,
                },
                {
                    "feedback_id": "prune",
                    "scene_id": "recent-good",
                    "feedback_type": "prune",
                    "occurred_at_ms": 11,
                    "value": "not worth keeping",
                },
            ]
        )
        == 2
    )
    assert (
        connection.execute(
            "SELECT exclusion_type FROM exclusion WHERE entity_id='old-good'"
        ).fetchone()[0]
        == "never_show"
    )
    assert (
        connection.execute(
            "SELECT state FROM pruning_candidate WHERE scene_id='recent-good'"
        ).fetchone()[0]
        == "review"
    )


def test_feedback_corrections_preserve_history_and_reconcile_state(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    store = InteractionStore(connection)
    assert (
        store.submit_feedback(
            [
                {
                    "feedback_id": "never",
                    "scene_id": "old-good",
                    "feedback_type": "never_show",
                    "occurred_at_ms": 10,
                }
            ]
        )
        == 1
    )

    store.correct_feedback("never", "replacement", "thumb_up", 20)

    rows = connection.execute(
        """
        SELECT feedback_id, feedback_type, reversed_by_id
        FROM feedback WHERE scene_id='old-good' ORDER BY occurred_at_ms
        """
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("never", "never_show", "replacement"),
        ("replacement", "thumb_up", None),
    ]
    assert (
        connection.execute(
            "SELECT reversed_at_ms FROM exclusion WHERE entity_id='old-good'"
        ).fetchone()[0]
        == 20
    )
    assert (
        connection.execute("SELECT 1 FROM pruning_candidate WHERE scene_id='old-good'").fetchone()
        is None
    )
    assert (
        connection.execute(
            "SELECT last_cause FROM model_update_state WHERE singleton=1"
        ).fetchone()[0]
        == "feedback_correction"
    )


def test_short_curator_session_followed_by_another_scene_records_replacement(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        """
        INSERT INTO impression(
            impression_id, requested_at_ms, lane, config_version, request_context_json
        ) VALUES ('impression', 1, 'for_you', 'builtin', '{}')
        """
    )
    original = {
        "session_id": "curator-original",
        "scene_id": "old-good",
        "started_at_ms": 1_000,
        "ended_at_ms": 11_000,
        "active_seconds": 10,
        "origin": "curator",
        "source_route": "/scenes/old-good",
        "start_position_seconds": 0,
        "maximum_position_seconds": 10,
        "final_position_seconds": 10,
        "impression_id": "impression",
        "lane": "for_you",
        "impression_position": 0,
    }
    replacement = {
        **original,
        "session_id": "next",
        "scene_id": "recent-good",
        "started_at_ms": 20_000,
        "ended_at_ms": 80_000,
        "active_seconds": 60,
        "origin": "stash",
        "impression_id": None,
        "lane": None,
        "impression_position": None,
    }

    InteractionStore(connection).submit_sessions([original, replacement])

    assert (
        connection.execute(
            """
        SELECT outcome FROM behavior_event
        WHERE event_id='next:replacement' AND scene_id='old-good'
        """
        ).fetchone()[0]
        == -0.25
    )
