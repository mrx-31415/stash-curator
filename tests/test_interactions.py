from pathlib import Path

from curator.interactions import InteractionStore
from curator.model import PreferenceModelBuilder
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
