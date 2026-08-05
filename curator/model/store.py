"""Typed reads for published recommendation-model state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass

from curator.storage.artifacts import attached_generation_id


@dataclass(frozen=True)
class ModelSceneScore:
    model_id: str
    scene_id: str
    general_appeal: float
    direct_appeal: float
    direct_confidence: float
    appeal: float
    current_fit: float
    confidence: float
    metadata_confidence: float
    recovery: float
    components: dict[str, object]
    neighbors: tuple[dict[str, object], ...]
    eligibility: dict[str, object]


class RecommendationModelStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_model_id(self) -> str | None:
        if attached := attached_generation_id(self.connection, "model"):
            return attached
        row = self.connection.execute(
            "SELECT model_id FROM model_version WHERE status='published'"
        ).fetchone()
        return str(row[0]) if row else None

    def scores(
        self, model_id: str, scene_ids: Collection[str] | None = None
    ) -> dict[str, ModelSceneScore]:
        if scene_ids is not None and not scene_ids:
            return {}
        where = "model_id=?"
        parameters: list[object] = [model_id]
        if scene_ids is not None:
            where += f" AND scene_id IN ({','.join('?' for _ in scene_ids)})"
            parameters.extend(scene_ids)
        rows = self.connection.execute(
            f"""
            SELECT model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery,
                components_json, eligibility_json
            FROM model_scene_score WHERE {where} ORDER BY scene_id
            """,
            parameters,
        )
        # Assembled in Python rather than via SQL json_object(): SQLite's JSON1 serializes
        # REAL values with only ~15 significant digits, silently losing precision on the
        # last one or two digits compared to Python's full float64 round-trip.
        neighbors_by_scene: dict[str, list[dict[str, object]]] = {}
        for row in self.connection.execute(
            f"""
            SELECT scene_id, neighbor_scene_id, similarity, weight, outcome
            FROM model_scene_neighbor WHERE {where} ORDER BY scene_id, rank
            """,
            parameters,
        ):
            neighbors_by_scene.setdefault(str(row["scene_id"]), []).append(
                {
                    "scene_id": str(row["neighbor_scene_id"]),
                    "similarity": float(row["similarity"]),
                    "weight": float(row["weight"]),
                    "outcome": float(row["outcome"]),
                }
            )
        return {
            str(row["scene_id"]): ModelSceneScore(
                model_id=str(row["model_id"]),
                scene_id=str(row["scene_id"]),
                general_appeal=float(row["general_appeal"]),
                direct_appeal=float(row["direct_appeal"]),
                direct_confidence=float(row["direct_confidence"]),
                appeal=float(row["appeal"]),
                current_fit=float(row["current_fit"]),
                confidence=float(row["confidence"]),
                metadata_confidence=float(row["metadata_confidence"]),
                recovery=float(row["recovery"]),
                components=json.loads(row["components_json"]),
                neighbors=tuple(neighbors_by_scene.get(str(row["scene_id"]), ())),
                eligibility=json.loads(row["eligibility_json"]),
            )
            for row in rows
        }
