"""Inspectable qualification policies for the four source lanes."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.features import FeatureStore
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


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    result: dict[str, float] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        percentile = ((start + end - 1) / 2) / denominator
        for scene_id, _ in ordered[start:end]:
            result[scene_id] = percentile
        start = end
    return result


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
        eligible_scores = {
            scene_id: score
            for scene_id, score in scores.items()
            if bool(score.eligibility.get("eligible", False))
        }
        played_scene_ids = {
            str(row[0])
            for row in self.connection.execute("SELECT DISTINCT scene_id FROM source_play")
        }
        content_ranks = _percentiles(
            {
                scene_id: _component_value(score, "content")
                for scene_id, score in eligible_scores.items()
            }
        )
        neighbor_ranks = _percentiles(
            {
                scene_id: _component_value(score, "content_neighbor")
                for scene_id, score in eligible_scores.items()
            }
        )
        similarity_ranks = _percentiles(
            {
                scene_id: max(
                    (_number(item.get("similarity")) for item in score.neighbors),
                    default=0.0,
                )
                for scene_id, score in eligible_scores.items()
            }
        )
        performer_ranks = _percentiles(
            {
                scene_id: _component_value(score, "performer_identity")
                + _component_value(score, "performer_similarity")
                for scene_id, score in eligible_scores.items()
            }
        )
        studio_ranks = _percentiles(
            {
                scene_id: _component_value(score, "studio")
                for scene_id, score in eligible_scores.items()
            }
        )
        fit_ranks = _percentiles(
            {scene_id: score.current_fit for scene_id, score in eligible_scores.items()}
        )
        coverage_ranks, unknown_performers, unknown_studios = self._adventure_context(
            model_id, set(eligible_scores)
        )
        classifications: list[LaneClassification] = []
        for scene_id, score in sorted(eligible_scores.items()):
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
            content_rank = content_ranks[scene_id]
            neighbor_rank = neighbor_ranks[scene_id]
            similarity_rank = similarity_ranks[scene_id]
            performer_rank = performer_ranks[scene_id]
            studio_rank = studio_ranks[scene_id]
            relevance = (
                0.32 * neighbor_rank
                + 0.10 * similarity_rank
                + 0.28 * performer_rank
                + 0.20 * content_rank
                + 0.10 * studio_rank
            ) * (0.90 + 0.10 * score.metadata_confidence)
            corroborated = (
                neighbor_rank >= self.config.ranking.best_bet_neighbor_percentile
                and max(performer_rank, content_rank)
                >= self.config.ranking.best_bet_anchor_percentile
            )
            direct_reliable = score.direct_appeal > 0.10 and score.direct_confidence >= 0.50
            if (
                score.current_fit >= self.config.ranking.best_bet_fit
                and score.confidence >= self.config.ranking.best_bet_confidence
                and score.metadata_confidence >= self.config.ranking.best_bet_metadata_confidence
                and relevance >= self.config.ranking.best_bet_relevance
                and (corroborated or direct_reliable)
                and scene_id not in played_scene_ids
            ):
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "best_bets",
                        None,
                        0.55 * relevance + 0.25 * fit_ranks[scene_id] + 0.20 * score.confidence,
                        {
                            "current_fit": score.current_fit,
                            "confidence": score.confidence,
                            "metadata_confidence": score.metadata_confidence,
                            "relevance": relevance,
                            "content_percentile": content_rank,
                            "neighbor_percentile": neighbor_rank,
                            "neighbor_similarity_percentile": similarity_rank,
                            "performer_percentile": performer_rank,
                            "studio_percentile": studio_rank,
                            "corroborated": corroborated,
                            "direct_reliable": direct_reliable,
                            "unseen": True,
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
                and scene_id in played_scene_ids
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
                score,
                positives,
                negatives,
                reusable.get("structure", 0.0),
                coverage_ranks.get(scene_id, 0.0),
            )
            distance_rank = 1 - similarity_rank
            adventure_value = (
                0.38 * coverage_ranks.get(scene_id, 0.0)
                + 0.25 * distance_rank
                + 0.17 * unknown_performers.get(scene_id, 1.0)
                + 0.08 * unknown_studios.get(scene_id, 1.0)
                + 0.12 * score.metadata_confidence
            )
            classifications.append(
                LaneClassification(
                    scene_id,
                    "adventure",
                    subtype,
                    adventure_value,
                    {
                        "positive_anchors": positives,
                        "component_disagreement": negatives,
                        "uncertainty": 1 - score.confidence,
                        "coverage_gap_percentile": coverage_ranks.get(scene_id, 0.0),
                        "content_distance_percentile": distance_rank,
                        "unknown_performer_share": unknown_performers.get(scene_id, 1.0),
                        "unknown_studio": unknown_studios.get(scene_id, 1.0),
                    },
                )
            )
        self._persist(
            model_id,
            classifications,
            {scene_id: score.appeal for scene_id, score in eligible_scores.items()},
        )
        return tuple(classifications)

    def load(
        self,
        model_id: str,
        *,
        lanes: Collection[str] | None = None,
        limit_per_lane: int | None = None,
    ) -> tuple[LaneClassification, ...]:
        if limit_per_lane is not None and limit_per_lane < 1:
            raise ValueError("limit_per_lane must be positive")
        rows: list[sqlite3.Row] = []
        selected_lanes: tuple[str | None, ...] = (
            tuple(lanes or LANES) if limit_per_lane else (None,)
        )
        for lane in selected_lanes:
            where = "model_id=?"
            parameters: list[object] = [model_id]
            if lane:
                where += " AND lane=?"
                parameters.append(lane)
            limit = ""
            if limit_per_lane:
                limit = " LIMIT ?"
                parameters.append(limit_per_lane)
            rows.extend(
                self.connection.execute(
                    f"""
                    SELECT scene_id, lane, subtype, lane_value, qualification_json
                    FROM model_scene_lane WHERE {where}
                    ORDER BY lane_value DESC, scene_id{limit}
                    """,
                    parameters,
                )
            )
        return tuple(
            LaneClassification(
                str(row["scene_id"]),
                str(row["lane"]),
                str(row["subtype"]) if row["subtype"] else None,
                float(row["lane_value"]),
                json.loads(str(row["qualification_json"])),
            )
            for row in rows
        )

    @staticmethod
    def _adventure_subtype(
        score: ModelSceneScore,
        positives: dict[str, float],
        negatives: dict[str, float],
        structure: float,
        coverage_rank: float,
    ) -> str:
        if structure > 0.015:
            return "structured_combination_challenge"
        if positives and negatives:
            return "model_disagreement"
        if positives and score.confidence < 0.45:
            return "anchored_model_gap"
        if coverage_rank >= 0.65 or (score.metadata_confidence >= 0.30 and score.confidence < 0.25):
            return "under_covered_island"
        return "pure_probe"

    def _adventure_context(
        self, model_id: str, scene_ids: set[str]
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        feature_row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        vectors = FeatureStore(self.connection).scene_content_vectors(str(feature_row[0]))
        played = {
            str(row[0])
            for row in self.connection.execute("SELECT DISTINCT scene_id FROM source_play")
        }
        library_count: dict[str, int] = {}
        played_count: dict[str, int] = {}
        for scene_id, vector in vectors.items():
            for feature in vector:
                library_count[feature] = library_count.get(feature, 0) + 1
                if scene_id in played:
                    played_count[feature] = played_count.get(feature, 0) + 1
        total_scenes = max(1, len(vectors))
        played_scenes = len(played)
        gaps: dict[str, float] = {}
        for scene_id in scene_ids:
            vector = vectors.get(scene_id, {})
            weighted_gap = 0.0
            weight = 0.0
            for feature, value in vector.items():
                expected = library_count.get(feature, 0) * played_scenes / total_scenes
                ratio = (expected + 2) / (played_count.get(feature, 0) + 2)
                weighted_gap += min(3.0, math.log1p(ratio)) * value
                weight += value
            gaps[scene_id] = weighted_gap / weight if weight else 0.0
        coverage_ranks = _percentiles(gaps)

        known_performers = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT DISTINCT sp.performer_id FROM scene_performer sp
                JOIN source_play p ON p.scene_id=sp.scene_id
                """
            )
        }
        performers: dict[str, list[str]] = {}
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, position"
        ):
            performers.setdefault(str(row["scene_id"]), []).append(str(row["performer_id"]))
        unknown_performers = {
            scene_id: (
                sum(performer not in known_performers for performer in performers.get(scene_id, ()))
                / len(performers[scene_id])
                if performers.get(scene_id)
                else 1.0
            )
            for scene_id in scene_ids
        }
        known_studios = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT DISTINCT s.studio_id FROM source_scene s
                JOIN source_play p ON p.scene_id=s.scene_id WHERE s.studio_id IS NOT NULL
                """
            )
        }
        scene_studios = {
            str(row["scene_id"]): str(row["studio_id"])
            for row in self.connection.execute(
                "SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL"
            )
        }
        unknown_studios = {
            scene_id: float(
                scene_id not in scene_studios or scene_studios[scene_id] not in known_studios
            )
            for scene_id in scene_ids
        }
        return coverage_ranks, unknown_performers, unknown_studios

    def _persist(
        self,
        model_id: str,
        classifications: list[LaneClassification],
        appeals: dict[str, float],
    ) -> None:
        with transaction(self.connection):
            self.connection.execute("DELETE FROM model_scene_lane WHERE model_id=?", (model_id,))
            self.connection.execute(
                "DELETE FROM model_lane_candidate_cache WHERE model_id=?", (model_id,)
            )
            self.connection.execute("DELETE FROM application_meta WHERE key LIKE 'slate:%'")
            self.connection.executemany(
                """
                INSERT INTO model_scene_lane(
                    model_id, scene_id, lane, subtype, lane_value, qualification_json, appeal
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        model_id,
                        item.scene_id,
                        item.lane,
                        item.subtype,
                        item.lane_value,
                        json.dumps(item.qualification, sort_keys=True, separators=(",", ":")),
                        appeals[item.scene_id],
                    )
                    for item in classifications
                ),
            )
