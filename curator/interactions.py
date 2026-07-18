"""Idempotent impressions, feedback, and direct player-session persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from curator.events import (
    DirectSessionInput,
    PlayedRange,
    SessionOrigin,
    quick_replacement_outcome,
    viewing_outcome,
)
from curator.model import ModelUpdateCoordinator
from curator.ranking import Slate
from curator.storage import transaction

FEEDBACK_TYPES = {
    "thumb_up",
    "thumb_down",
    "not_now",
    "never_show",
    "prune",
    "metadata_wrong",
}


class InteractionStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record_impression(
        self,
        impression_id: str,
        slate: Slate,
        requested_at_ms: int,
        context: dict[str, object] | None = None,
    ) -> None:
        with transaction(self.connection):
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO impression(
                    impression_id, requested_at_ms, lane, model_id, config_version,
                    request_context_json
                ) VALUES (?, ?, ?, ?, 'builtin', ?)
                """,
                (
                    impression_id,
                    requested_at_ms,
                    slate.lane,
                    slate.model_id,
                    json.dumps(context or {}, sort_keys=True, separators=(",", ":")),
                ),
            )
            if not cursor.rowcount:
                return
            self.connection.executemany(
                """
                INSERT INTO impression_item(
                    impression_id, scene_id, position, policy_score, reason_snapshot_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        impression_id,
                        item.scene_id,
                        item.position,
                        item.final_utility,
                        json.dumps(item.reason_ids, separators=(",", ":")),
                    )
                    for item in slate.items
                ),
            )

    def qualify_impressions(self, entries: list[dict[str, Any]]) -> int:
        normalized = [self._impression_entry(entry) for entry in entries]
        inserted = 0
        with transaction(self.connection):
            for entry in normalized:
                cursor = self.connection.execute(
                    """
                    UPDATE impression_item SET qualified_at_ms=?
                    WHERE impression_id=? AND scene_id=? AND qualified_at_ms IS NULL
                    """,
                    (entry["occurred_at_ms"], entry["impression_id"], entry["scene_id"]),
                )
                if not cursor.rowcount:
                    continue
                impression = self.connection.execute(
                    "SELECT lane FROM impression WHERE impression_id=?",
                    (entry["impression_id"],),
                ).fetchone()
                assert impression is not None
                self.connection.execute(
                    """
                    INSERT INTO recommendation_history(
                        history_id, scene_id, impression_id, lane, shown_at_ms
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"{entry['impression_id']}:{entry['scene_id']}",
                        entry["scene_id"],
                        entry["impression_id"],
                        impression["lane"],
                        entry["occurred_at_ms"],
                    ),
                )
                inserted += 1
        return inserted

    def submit_feedback(self, entries: list[dict[str, Any]]) -> int:
        normalized = [self._feedback_entry(entry) for entry in entries]
        inserted = 0
        with transaction(self.connection):
            for entry in normalized:
                cursor = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO feedback(
                        feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                        impression_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["feedback_id"],
                        entry["scene_id"],
                        entry["feedback_type"],
                        entry["value"],
                        entry["occurred_at_ms"],
                        entry["impression_id"],
                        json.dumps(entry["payload"], sort_keys=True, separators=(",", ":")),
                    ),
                )
                if not cursor.rowcount:
                    continue
                inserted += 1
                self._apply_feedback(entry)
            if inserted:
                ModelUpdateCoordinator(self.connection).request("direct_feedback")
        return inserted

    def submit_sessions(self, entries: list[dict[str, Any]]) -> int:
        sessions = [self._session(entry) for entry in entries]
        inserted = 0
        with transaction(self.connection):
            for session in sessions:
                cursor = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO play_session(
                        session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
                        provenance, confidence, impression_id, summary_json
                    ) VALUES (?, ?, ?, ?, ?, 'direct_player', 1, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.scene_id,
                        session.started_at_ms,
                        session.ended_at_ms,
                        session.active_seconds,
                        session.impression_id,
                        json.dumps(asdict(session), sort_keys=True, separators=(",", ":")),
                    ),
                )
                if not cursor.rowcount:
                    continue
                inserted += 1
                outcome = viewing_outcome(session.active_seconds, session.ended_at_ms)
                if outcome is not None:
                    self._insert_signal(
                        f"{session.session_id}:view", session.scene_id, session.session_id, outcome
                    )
                self._insert_replacement(session)
            if inserted:
                ModelUpdateCoordinator(self.connection).request("session_outcome")
        return inserted

    def _apply_feedback(self, entry: dict[str, Any]) -> None:
        feedback_type = entry["feedback_type"]
        if feedback_type == "never_show":
            self.connection.execute(
                """
                INSERT INTO exclusion(
                    exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms
                ) VALUES (?, 'scene', ?, 'never_show', ?)
                ON CONFLICT(entity_type, entity_id, exclusion_type) DO UPDATE SET
                    created_at_ms=excluded.created_at_ms, reversed_at_ms=NULL, expires_at_ms=NULL
                """,
                (f"exclusion:{entry['scene_id']}", entry["scene_id"], entry["occurred_at_ms"]),
            )
        elif feedback_type == "prune":
            self.connection.execute(
                """
                INSERT INTO pruning_candidate(
                    scene_id, state, created_at_ms, updated_at_ms, reason
                ) VALUES (?, 'review', ?, ?, ?)
                ON CONFLICT(scene_id) DO UPDATE SET state='review',
                    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
                """,
                (
                    entry["scene_id"],
                    entry["occurred_at_ms"],
                    entry["occurred_at_ms"],
                    entry["value"],
                ),
            )

    def _insert_replacement(self, replacement: DirectSessionInput) -> None:
        row = self.connection.execute(
            """
            SELECT summary_json FROM play_session
            WHERE provenance='direct_player' AND session_id<>? AND ended_at_ms<=?
            ORDER BY ended_at_ms DESC LIMIT 1
            """,
            (replacement.session_id, replacement.started_at_ms),
        ).fetchone()
        if row is None:
            return
        original = self._session(json.loads(row[0]))
        positive = bool(
            self.connection.execute(
                """
                SELECT 1 FROM feedback WHERE scene_id=? AND feedback_type='thumb_up'
                AND reversed_by_id IS NULL AND occurred_at_ms BETWEEN ? AND ? LIMIT 1
                """,
                (original.scene_id, original.ended_at_ms, replacement.started_at_ms),
            ).fetchone()
        )
        signal = quick_replacement_outcome(
            original, replacement, intervening_positive_feedback=positive
        )
        if signal is not None:
            self._insert_signal(
                f"{replacement.session_id}:replacement",
                original.scene_id,
                original.session_id,
                signal,
            )

    def _insert_signal(
        self, event_id: str, scene_id: str, session_id: str | None, signal: Any
    ) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO behavior_event(
                event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
                provenance, session_id, payload_json
            ) VALUES (?, 'occasion_outcome', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                scene_id,
                signal.observed_at_ms,
                signal.value,
                signal.confidence,
                signal.provenance,
                session_id,
                json.dumps({"primary_signal": signal.signal_type}, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _impression_entry(entry: dict[str, Any]) -> dict[str, Any]:
        impression_id = str(entry.get("impression_id") or "")
        scene_id = str(entry.get("scene_id") or "")
        occurred_at_ms = int(entry.get("occurred_at_ms", -1))
        if not impression_id or not scene_id or occurred_at_ms < 0:
            raise ValueError("impression_id, scene_id, and occurred_at_ms are required")
        return {
            "impression_id": impression_id,
            "scene_id": scene_id,
            "occurred_at_ms": occurred_at_ms,
        }

    @staticmethod
    def _feedback_entry(entry: dict[str, Any]) -> dict[str, Any]:
        feedback_type = str(entry.get("feedback_type") or "")
        if feedback_type not in FEEDBACK_TYPES:
            raise ValueError(f"unknown feedback type: {feedback_type}")
        feedback_id = str(entry.get("feedback_id") or "")
        scene_id = str(entry.get("scene_id") or "")
        occurred_at_ms = int(entry.get("occurred_at_ms", -1))
        if not feedback_id or not scene_id or occurred_at_ms < 0:
            raise ValueError("feedback_id, scene_id, and occurred_at_ms are required")
        return {
            "feedback_id": feedback_id,
            "scene_id": scene_id,
            "feedback_type": feedback_type,
            "value": str(entry["value"]) if entry.get("value") is not None else None,
            "occurred_at_ms": occurred_at_ms,
            "impression_id": (str(entry["impression_id"]) if entry.get("impression_id") else None),
            "payload": entry.get("payload") if isinstance(entry.get("payload"), dict) else {},
        }

    @staticmethod
    def _session(entry: dict[str, Any]) -> DirectSessionInput:
        ranges = tuple(
            PlayedRange(float(item["start_seconds"]), float(item["end_seconds"]))
            for item in entry.get("played_ranges", [])
        )
        return DirectSessionInput(
            session_id=str(entry.get("session_id") or ""),
            scene_id=str(entry.get("scene_id") or ""),
            started_at_ms=int(entry.get("started_at_ms", -1)),
            ended_at_ms=int(entry.get("ended_at_ms", -1)),
            active_seconds=float(entry.get("active_seconds", 0)),
            origin=SessionOrigin(str(entry.get("origin") or "stash")),
            source_route=str(entry.get("source_route") or ""),
            start_position_seconds=float(entry.get("start_position_seconds", 0)),
            maximum_position_seconds=float(entry.get("maximum_position_seconds", 0)),
            final_position_seconds=float(entry.get("final_position_seconds", 0)),
            played_ranges=ranges,
            seek_destinations_seconds=tuple(
                float(value) for value in entry.get("seek_destinations_seconds", [])
            ),
            nearby_marker_ids=tuple(str(value) for value in entry.get("nearby_marker_ids", [])),
            natural_completion=bool(entry.get("natural_completion", False)),
            impression_id=str(entry["impression_id"]) if entry.get("impression_id") else None,
            lane=str(entry["lane"]) if entry.get("lane") else None,
            impression_position=(
                int(entry["impression_position"])
                if entry.get("impression_position") is not None
                else None
            ),
            model_id=str(entry["model_id"]) if entry.get("model_id") else None,
        )
