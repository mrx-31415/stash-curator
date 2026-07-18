"""Typed reads for published recommendation-model state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass


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
            f"SELECT * FROM model_scene_score WHERE {where} ORDER BY scene_id",
            parameters,
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
                neighbors=tuple(json.loads(row["neighbors_json"])),
                eligibility=json.loads(row["eligibility_json"]),
            )
            for row in rows
        }
