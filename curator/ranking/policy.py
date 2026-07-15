"""Inspectable qualification policies for the four source lanes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.model import ModelSceneScore, RecommendationModelStore
from curator.storage import transaction

LANES = ("best_bets", "revisit", "discover", "adventure")


@dataclass(frozen=True)
class LaneClassification:
    scene_id: str
    lane: str
    subtype: str | None
    lane_value: float
    qualification: dict[str, object]


def _component_value(score: ModelSceneScore, name: str) -> float:
    component = score.components.get(name)
    if not isinstance(component, dict):
        return 0.0
    value = component.get("value", 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


class LanePolicy:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: CuratorConfig = DEFAULT_CONFIG,
    ) -> None:
        self.connection = connection
        self.config = config

    def classify(self, model_id: str) -> tuple[LaneClassification, ...]:
        scores = RecommendationModelStore(self.connection).scores(model_id)
        classifications: list[LaneClassification] = []
        for scene_id, score in sorted(scores.items()):
            if not bool(score.eligibility.get("eligible", False)):
                continue
            reusable = {
                family: _component_value(score, family)
                for family in (
                    "content",
                    "content_neighbor",
                    "performer_identity",
                    "performer_similarity",
                    "studio",
                    "structure",
                )
            }
            positives = {key: value for key, value in reusable.items() if value >= 0.025}
            negatives = {key: value for key, value in reusable.items() if value <= -0.025}
            strongest_anchor = max(positives.values(), default=0.0)
            if (
                score.current_fit >= self.config.ranking.best_bet_fit
                and score.confidence >= self.config.ranking.best_bet_confidence
                and score.metadata_confidence >= 0.15
            ):
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "best_bets",
                        None,
                        0.65 * score.current_fit + 0.20 * score.appeal + 0.15 * score.confidence,
                        {
                            "current_fit": score.current_fit,
                            "confidence": score.confidence,
                            "metadata_confidence": score.metadata_confidence,
                        },
                    )
                )
            direct = score.components.get("direct", {})
            signals = direct.get("signals", []) if isinstance(direct, dict) else []
            durable = bool(
                isinstance(signals, list)
                and {"o", "thumb_up", "repeat", "scene_rating"} & set(map(str, signals))
            )
            if (
                score.direct_appeal > 0.10
                and score.direct_confidence >= self.config.ranking.revisit_direct_confidence
                and score.recovery >= 0.10
                and durable
            ):
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "revisit",
                        None,
                        score.direct_appeal * score.direct_confidence * score.recovery
                        + 0.25 * score.current_fit,
                        {
                            "direct_appeal": score.direct_appeal,
                            "direct_confidence": score.direct_confidence,
                            "recovery": score.recovery,
                            "durable_signals": sorted(set(map(str, signals))),
                        },
                    )
                )
            if (
                score.direct_confidence < self.config.ranking.revisit_direct_confidence
                and strongest_anchor >= self.config.ranking.discover_anchor
            ):
                if len(negatives) == 1:
                    subtype = "stretch"
                elif score.confidence < 0.35 or score.metadata_confidence < 0.30:
                    subtype = "frontier"
                else:
                    subtype = "adjacent"
                challenged = min(negatives, key=lambda key: negatives[key]) if negatives else None
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "discover",
                        subtype,
                        score.current_fit + 0.12 * (1 - score.confidence) + 0.5 * strongest_anchor,
                        {
                            "positive_anchors": positives,
                            "negative_assumptions": negatives,
                            "challenged_assumption": challenged,
                            "uncertainty": 1 - score.confidence,
                        },
                    )
                )
            subtype = self._adventure_subtype(
                score, positives, negatives, reusable.get("structure", 0.0)
            )
            classifications.append(
                LaneClassification(
                    scene_id,
                    "adventure",
                    subtype,
                    0.35 * score.metadata_confidence
                    + 0.20 * max(0.0, score.appeal)
                    + 0.15 * (1 - score.confidence),
                    {
                        "positive_anchors": positives,
                        "component_disagreement": negatives,
                        "uncertainty": 1 - score.confidence,
                    },
                )
            )
        self._persist(model_id, classifications)
        return tuple(classifications)

    @staticmethod
    def _adventure_subtype(
        score: ModelSceneScore,
        positives: dict[str, float],
        negatives: dict[str, float],
        structure: float,
    ) -> str:
        if structure > 0.015:
            return "structured_combination_challenge"
        if positives and negatives:
            return "model_disagreement"
        if positives and score.confidence < 0.45:
            return "anchored_model_gap"
        if score.metadata_confidence >= 0.30 and score.confidence < 0.25:
            return "under_covered_island"
        return "pure_probe"

    def _persist(self, model_id: str, classifications: list[LaneClassification]) -> None:
        with transaction(self.connection):
            self.connection.execute("DELETE FROM model_scene_lane WHERE model_id=?", (model_id,))
            self.connection.executemany(
                """
                INSERT INTO model_scene_lane(
                    model_id, scene_id, lane, subtype, lane_value, qualification_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        model_id,
                        item.scene_id,
                        item.lane,
                        item.subtype,
                        item.lane_value,
                        json.dumps(item.qualification, sort_keys=True, separators=(",", ":")),
                    )
                    for item in classifications
                ),
            )
