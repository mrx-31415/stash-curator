"""Materialize reconstructable historical sessions and outcomes in SQLite."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from curator.events.contracts import DEFAULT_CALIBRATION, EventCalibration, NormalizedOutcome
from curator.events.historical import (
    HistoricalO,
    HistoricalPlay,
    HistoricalReconstruction,
    reconstruct_history,
)
from curator.storage import transaction


@dataclass(frozen=True)
class HistoricalBuildResult:
    scene_count: int
    session_count: int
    outcome_count: int


class HistoricalEventStore:
    """Rebuild deterministic historical projections from preserved source facts."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        calibration: EventCalibration = DEFAULT_CALIBRATION,
    ) -> None:
        self.connection = connection
        self.calibration = calibration

    def rebuild(self, scene_ids: tuple[str, ...] | None = None) -> HistoricalBuildResult:
        with transaction(self.connection):
            scenes = self._scenes(scene_ids)
            plays = self._plays(scene_ids)
            os = self._os(scene_ids)
            reconstructions = {
                scene_id: reconstruct_history(
                    scene_id,
                    duration,
                    tuple(plays[scene_id]),
                    tuple(os[scene_id]),
                    calibration=self.calibration,
                )
                for scene_id, duration in scenes
            }
            self._delete_projection(scene_ids)
            for reconstruction in reconstructions.values():
                self._insert_reconstruction(reconstruction)
        return HistoricalBuildResult(
            scene_count=len(scenes),
            session_count=sum(len(item.sessions) for item in reconstructions.values()),
            outcome_count=sum(
                sum(session.outcome is not None for session in item.sessions)
                + len(item.standalone_outcomes)
                for item in reconstructions.values()
            ),
        )

    def _scenes(self, scene_ids: tuple[str, ...] | None) -> list[tuple[str, float]]:
        clause, parameters = self._selection(scene_ids, "scene_id")
        rows = self.connection.execute(
            f"""
            SELECT scene_id, play_duration_seconds FROM source_scene
            {clause} ORDER BY scene_id
            """,
            parameters,
        )
        return [(str(row["scene_id"]), float(row["play_duration_seconds"])) for row in rows]

    def _plays(self, scene_ids: tuple[str, ...] | None) -> dict[str, list[HistoricalPlay]]:
        clause, parameters = self._selection(scene_ids, "scene_id")
        rows = self.connection.execute(
            f"""
            SELECT scene_id, played_at_ms, ordinal FROM source_play
            {clause} ORDER BY scene_id, played_at_ms, ordinal
            """,
            parameters,
        )
        grouped: dict[str, list[HistoricalPlay]] = defaultdict(list)
        for row in rows:
            grouped[str(row["scene_id"])].append(
                HistoricalPlay(int(row["played_at_ms"]), int(row["ordinal"]))
            )
        return grouped

    def _os(self, scene_ids: tuple[str, ...] | None) -> dict[str, list[HistoricalO]]:
        clause, parameters = self._selection(scene_ids, "scene_id")
        rows = self.connection.execute(
            f"""
            SELECT scene_id, occurred_at_ms, ordinal FROM source_o
            {clause} ORDER BY scene_id, occurred_at_ms, ordinal
            """,
            parameters,
        )
        grouped: dict[str, list[HistoricalO]] = defaultdict(list)
        for row in rows:
            grouped[str(row["scene_id"])].append(
                HistoricalO(int(row["occurred_at_ms"]), int(row["ordinal"]))
            )
        return grouped

    @staticmethod
    def _selection(scene_ids: tuple[str, ...] | None, column: str) -> tuple[str, tuple[str, ...]]:
        if scene_ids is None:
            return "", ()
        if not scene_ids:
            return "WHERE 0", ()
        placeholders = ", ".join("?" for _ in scene_ids)
        return f"WHERE {column} IN ({placeholders})", scene_ids

    def _delete_projection(self, scene_ids: tuple[str, ...] | None) -> None:
        clause, parameters = self._selection(scene_ids, "scene_id")
        suffix = f" AND {clause.removeprefix('WHERE ')}" if clause else ""
        self.connection.execute(
            f"DELETE FROM behavior_event WHERE provenance = 'historical_import'{suffix}",
            parameters,
        )
        self.connection.execute(
            f"DELETE FROM play_session WHERE provenance = 'historical_imputed'{suffix}",
            parameters,
        )

    def _insert_reconstruction(self, reconstruction: HistoricalReconstruction) -> None:
        for session in reconstruction.sessions:
            summary = {
                "duration_basis": "scene_total_divided_by_play_timestamps",
                "matched_o_at_ms": (
                    session.matched_o.occurred_at_ms if session.matched_o else None
                ),
            }
            self.connection.execute(
                """
                INSERT INTO play_session(
                    session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
                    provenance, confidence, summary_json
                ) VALUES (?, ?, ?, ?, ?, 'historical_imputed', ?, ?)
                """,
                (
                    session.session_id,
                    session.scene_id,
                    session.started_at_ms,
                    session.ended_at_ms,
                    session.active_seconds,
                    session.confidence,
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                ),
            )
            if session.outcome:
                self._insert_outcome(
                    f"{session.session_id}-outcome",
                    session.scene_id,
                    session.outcome,
                    session.session_id,
                )
        for standalone in reconstruction.standalone_outcomes:
            self._insert_outcome(
                standalone.event_id,
                standalone.scene_id,
                standalone.outcome,
                None,
            )

    def _insert_outcome(
        self,
        event_id: str,
        scene_id: str,
        outcome: NormalizedOutcome,
        session_id: str | None,
    ) -> None:
        payload = json.dumps(
            {
                "primary_signal": outcome.primary_signal,
                "primary_provenance": outcome.provenance,
                "supporting_signals": list(outcome.supporting_signals),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.connection.execute(
            """
            INSERT INTO behavior_event(
                event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
                provenance, session_id, payload_json
            ) VALUES (?, 'occasion_outcome', ?, ?, ?, ?, 'historical_import', ?, ?)
            """,
            (
                event_id,
                scene_id,
                outcome.observed_at_ms,
                outcome.value,
                outcome.confidence,
                session_id,
                payload,
            ),
        )
