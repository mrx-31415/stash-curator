"""A qualified, unpicked view should cool a scene without removing it."""

import sqlite3
from types import SimpleNamespace

from curator.api import _draw_slate

DAY_MS = 86_400_000
NOW_MS = 100 * DAY_MS


def test_weighted_draw_cools_unpicked_views_and_recovers() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE play_session (scene_id TEXT, impression_id TEXT);
        CREATE TABLE feedback (scene_id TEXT, impression_id TEXT,
            feedback_type TEXT, reversed_by_id TEXT);
        CREATE TABLE recommendation_history (scene_id TEXT, impression_id TEXT,
            lane TEXT, shown_at_ms INTEGER);
        """
    )
    items = tuple(
        SimpleNamespace(scene_id=f"scene-{index}", source_lane="best_bets") for index in range(100)
    )

    def appearances(at_ms: int) -> int:
        return sum(
            items[0] in _draw_slate(connection, "best_bets", items, str(seed), at_ms, 20, 3)[:20]
            for seed in range(100)
        )

    baseline = appearances(NOW_MS)
    assert baseline > sum(
        items[-1] in _draw_slate(connection, "best_bets", items, str(seed), NOW_MS, 20, 3)[:20]
        for seed in range(100)
    )
    connection.execute(
        "INSERT INTO recommendation_history VALUES (?, ?, ?, ?)",
        ("scene-0", "view-1", "best_bets", NOW_MS - DAY_MS),
    )
    assert appearances(NOW_MS) < baseline
    assert appearances(NOW_MS + 4 * DAY_MS) == baseline
    connection.execute("INSERT INTO play_session VALUES (?, ?)", ("scene-0", "view-1"))
    assert appearances(NOW_MS) == baseline
