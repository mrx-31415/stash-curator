import json
import sqlite3
from pathlib import Path

import pytest

from curator.events.repository import HistoricalEventStore
from curator.storage import MigrationRunner, connect_database


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    database = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(database).migrate(applied_at_ms=1)
    database.execute(
        """
        INSERT INTO source_scene(
            scene_id, play_count, play_duration_seconds, source_hash
        ) VALUES ('scene-1', 2, 600, 'hash-1')
        """
    )
    database.executemany(
        "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('scene-1', ?, 0)",
        ((3_600_000,), (46_800_000,)),
    )
    database.execute(
        "INSERT INTO source_o(scene_id, occurred_at_ms, ordinal) VALUES ('scene-1', ?, 0)",
        (3_601_000,),
    )
    return database


def test_historical_projection_is_idempotent_and_inspectable(
    connection: sqlite3.Connection,
) -> None:
    store = HistoricalEventStore(connection)

    first = store.rebuild()
    second = store.rebuild()

    assert first == second
    assert first.scene_count == 1
    assert first.session_count == 2
    assert first.outcome_count == 2
    assert connection.execute("SELECT count(*) FROM play_session").fetchone()[0] == 2
    events = connection.execute(
        "SELECT outcome, confidence, payload_json FROM behavior_event ORDER BY occurred_at_ms"
    ).fetchall()
    assert len(events) == 2
    assert events[0]["outcome"] == 1
    assert json.loads(events[0]["payload_json"])["primary_signal"] == "o"
    assert json.loads(events[1]["payload_json"])["primary_signal"] == "repeat"


def test_rebuild_recomputes_imputed_duration_from_preserved_source_aggregate(
    connection: sqlite3.Connection,
) -> None:
    store = HistoricalEventStore(connection)
    store.rebuild()
    connection.execute(
        "UPDATE source_scene SET play_duration_seconds = 120 WHERE scene_id = 'scene-1'"
    )

    result = store.rebuild(("scene-1",))

    assert result.session_count == 2
    active = [
        row[0]
        for row in connection.execute(
            "SELECT active_seconds FROM play_session ORDER BY started_at_ms"
        )
    ]
    assert active == [60, 60]
