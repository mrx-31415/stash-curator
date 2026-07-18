"""Live scene eligibility shared by model building and slate selection."""

from __future__ import annotations

import sqlite3

from curator.config import DEFAULT_CONFIG, CuratorConfig


def scene_eligibility(
    connection: sqlite3.Connection,
    reference_at_ms: int,
    config: CuratorConfig = DEFAULT_CONFIG,
    *,
    include_temporary: bool = True,
) -> dict[str, dict[str, object]]:
    latest_feedback: dict[str, str] = {}
    not_now: dict[str, int] = {}
    for row in connection.execute(
        """
        SELECT scene_id, feedback_type, occurred_at_ms FROM feedback
        WHERE reversed_by_id IS NULL
        ORDER BY scene_id, occurred_at_ms
        """
    ):
        scene_id = str(row["scene_id"])
        feedback_type = str(row["feedback_type"])
        if feedback_type in {"thumb_up", "thumb_down"}:
            latest_feedback[scene_id] = feedback_type
        elif feedback_type == "not_now":
            not_now[scene_id] = int(row["occurred_at_ms"])

    excluded = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT entity_id FROM exclusion WHERE entity_type='scene'
            AND reversed_at_ms IS NULL AND (expires_at_ms IS NULL OR expires_at_ms > ?)
            """,
            (reference_at_ms,),
        )
    }
    pruning = {
        str(row["scene_id"]): str(row["state"])
        for row in connection.execute("SELECT scene_id, state FROM pruning_candidate")
    }
    available = {
        str(row[0])
        for row in connection.execute("SELECT DISTINCT scene_id FROM source_file WHERE available=1")
    }
    not_now_ms = int(config.model.not_now_days * 86_400_000)
    result: dict[str, dict[str, object]] = {}
    for row in connection.execute("SELECT scene_id FROM source_scene ORDER BY scene_id"):
        scene_id = str(row[0])
        reasons: list[str] = []
        if scene_id not in available:
            reasons.append("file_unavailable")
        if scene_id in excluded:
            reasons.append("hard_exclusion")
        if pruning.get(scene_id) in {"review", "remove"}:
            reasons.append(f"pruning_{pruning[scene_id]}")
        if latest_feedback.get(scene_id) == "thumb_down":
            reasons.append("current_thumb_down")
        if include_temporary and reference_at_ms - not_now.get(scene_id, -not_now_ms) < not_now_ms:
            reasons.append("not_now")
        result[scene_id] = {"eligible": not reasons, "reasons": reasons}
    return result
