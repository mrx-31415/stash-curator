"""Greedy deterministic slate selection with hard and soft variety rules."""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.features import FeatureStore
from curator.model import ModelSceneScore, RecommendationModelStore
from curator.model.boundaries import scene_eligibility
from curator.ranking.policy import LaneClassification, LanePolicy

FAMILIAR_PATTERN = (
    "best_bets",
    "best_bets",
    "revisit",
    "best_bets",
    "discover",
    "best_bets",
    "best_bets",
    "revisit",
    "best_bets",
    "best_bets",
)
ADVENTUROUS_PATTERN = (
    "best_bets",
    "best_bets",
    "revisit",
    "discover",
    "best_bets",
    "discover",
    "adventure",
    "best_bets",
    "discover",
    "adventure",
)


@dataclass(frozen=True)
class _Candidate:
    classification: LaneClassification
    performers: tuple[str, ...]
    studio_group: str | None
    content: dict[str, float]


@dataclass(frozen=True)
class RecommendationItem:
    scene_id: str
    lane: str
    source_lane: str
    subtype: str | None
    position: int
    appeal: float
    current_fit: float
    confidence: float
    lane_value: float
    final_utility: float
    penalties: dict[str, float]
    bonuses: dict[str, float]
    components: dict[str, object]
    neighbors: tuple[dict[str, object], ...]
    eligibility: dict[str, object]
    qualification: dict[str, object]
    reason_ids: tuple[str, ...]


@dataclass(frozen=True)
class Slate:
    model_id: str
    lane: str
    items: tuple[RecommendationItem, ...]
    diagnostics: tuple[str, ...]


class SlateBuilder:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: CuratorConfig = DEFAULT_CONFIG,
    ) -> None:
        self.connection = connection
        self.config = config
        self._cached_model_id: str | None = None
        self._cached_candidates: tuple[_Candidate, ...] = ()
        self._cached_scores: dict[str, ModelSceneScore] = {}

    def recommend(self, lane: str, count: int, *, exploration: int = 0) -> Slate:
        if lane not in {"for_you", "best_bets", "revisit", "discover", "adventure"}:
            raise ValueError(f"unknown lane: {lane}")
        if count < 1:
            raise ValueError("count must be positive")
        if exploration not in {-1, 0, 1}:
            raise ValueError("exploration must be -1, 0, or 1")
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model; run build-model first")
        if model_id != self._cached_model_id:
            policy = LanePolicy(self.connection, self.config)
            classifications = policy.load(model_id) or policy.classify(model_id)
            self._cached_model_id = model_id
            self._cached_candidates = tuple(self._candidates(model_id, classifications))
            self._cached_scores = RecommendationModelStore(self.connection).scores(model_id)
        live_eligibility = scene_eligibility(
            self.connection, time.time_ns() // 1_000_000, self.config
        )
        candidates = tuple(
            candidate
            for candidate in self._cached_candidates
            if bool(
                live_eligibility.get(candidate.classification.scene_id, {}).get("eligible", False)
            )
        )
        scores = self._cached_scores
        selected: list[_Candidate] = []
        items: list[RecommendationItem] = []
        diagnostics: list[str] = []
        history = self._history_context(model_id)
        for position in range(count):
            target_lane, target_subtype = self._target(lane, position, exploration)
            selected_scene_ids = {candidate.classification.scene_id for candidate in selected}
            remaining = [
                candidate
                for candidate in candidates
                if candidate.classification.scene_id not in selected_scene_ids
            ]
            preferred = [
                candidate
                for candidate in remaining
                if candidate.classification.lane == target_lane
                and (target_subtype is None or candidate.classification.subtype == target_subtype)
            ]
            pool = preferred or (
                [
                    candidate
                    for candidate in remaining
                    if candidate.classification.lane == target_lane
                ]
                or remaining
            )
            ranked = []
            for candidate in pool:
                utility = self._utility(candidate, selected, history)
                if utility is None:
                    continue
                ranked.append((utility[0], candidate.classification.scene_id, candidate, utility))
            if not ranked and self.config.ranking.relax_adjacent_when_exhausted:
                diagnostics.append(f"position {position}: relaxed adjacent performer constraint")
                for candidate in pool:
                    utility = self._utility(candidate, selected, history, relax_adjacent=True)
                    if utility:
                        ranked.append(
                            (utility[0], candidate.classification.scene_id, candidate, utility)
                        )
            if not ranked:
                diagnostics.append(f"position {position}: candidate pool exhausted")
                break
            _, _, chosen, utility = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
            selected.append(chosen)
            score = scores[chosen.classification.scene_id]
            final_lane = lane
            reasons = ["eligibility.lane"]
            reasons.extend(f"diversity.{name}" for name, value in utility[1].items() if value > 0)
            items.append(
                RecommendationItem(
                    chosen.classification.scene_id,
                    final_lane,
                    chosen.classification.lane,
                    chosen.classification.subtype,
                    position,
                    score.appeal,
                    score.current_fit,
                    score.confidence,
                    chosen.classification.lane_value,
                    utility[0],
                    utility[1],
                    utility[2],
                    score.components,
                    score.neighbors,
                    score.eligibility,
                    chosen.classification.qualification,
                    tuple(reasons),
                )
            )
        return Slate(model_id, lane, tuple(items), tuple(diagnostics))

    def _target(self, lane: str, position: int, exploration: int) -> tuple[str, str | None]:
        if lane == "for_you":
            pattern = (
                FAMILIAR_PATTERN
                if exploration < 0
                else ADVENTUROUS_PATTERN
                if exploration > 0
                else self.config.ranking.for_you_pattern
            )
            return pattern[position % len(pattern)], None
        if lane == "adventure":
            subtypes = (
                "anchored_model_gap",
                "model_disagreement",
                "structured_combination_challenge",
                "under_covered_island",
                "pure_probe",
            )
            return lane, subtypes[position] if position < len(subtypes) else None
        return lane, None

    def _candidates(
        self, model_id: str, classifications: tuple[LaneClassification, ...]
    ) -> list[_Candidate]:
        feature_row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        vectors = FeatureStore(self.connection).scene_content_vectors(str(feature_row[0]))
        performers: dict[str, list[str]] = {}
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, position"
        ):
            performers.setdefault(str(row["scene_id"]), []).append(str(row["performer_id"]))
        studios = {
            str(row["scene_id"]): (
                str(row["parent_studio_id"] or row["studio_id"]) if row["studio_id"] else None
            )
            for row in self.connection.execute(
                """
                SELECT s.scene_id, s.studio_id, st.parent_studio_id
                FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
                """
            )
        }
        return [
            _Candidate(
                classification,
                tuple(performers.get(classification.scene_id, ())),
                studios.get(classification.scene_id),
                vectors.get(classification.scene_id, {}),
            )
            for classification in classifications
        ]

    def _utility(
        self,
        candidate: _Candidate,
        selected: list[_Candidate],
        history: tuple[set[str], set[str], tuple[dict[str, float], ...]],
        *,
        relax_adjacent: bool = False,
    ) -> tuple[float, dict[str, float], dict[str, float]] | None:
        if (
            selected
            and not self.config.ranking.adjacent_shared_performers
            and not relax_adjacent
            and set(candidate.performers) & set(selected[-1].performers)
        ):
            return None
        penalties = {"performer": 0.0, "studio": 0.0, "content": 0.0, "history": 0.0}
        for previous in selected:
            if set(candidate.performers) & set(previous.performers):
                penalties["performer"] = max(
                    penalties["performer"], self.config.ranking.performer_repeat_penalty
                )
            if candidate.studio_group and candidate.studio_group == previous.studio_group:
                penalties["studio"] = max(penalties["studio"], self.config.ranking.studio_penalty)
            penalties["content"] = max(
                penalties["content"],
                self.config.ranking.content_penalty
                * self._cosine(candidate.content, previous.content),
            )
        history_performers, history_studios, history_vectors = history
        if set(candidate.performers) & history_performers:
            penalties["history"] += self.config.ranking.history_performer_penalty
        if candidate.studio_group and candidate.studio_group in history_studios:
            penalties["history"] += self.config.ranking.history_studio_penalty
        if history_vectors:
            penalties["history"] += self.config.ranking.history_content_penalty * max(
                self._cosine(candidate.content, vector) for vector in history_vectors
            )
        covered = {name for previous in selected for name in previous.content}
        uncovered_share = (
            len(set(candidate.content) - covered) / len(candidate.content)
            if candidate.content
            else 0.0
        )
        bonuses = {
            "uncovered_content": self.config.ranking.uncovered_content_bonus * uncovered_share
        }
        final = (
            candidate.classification.lane_value + sum(bonuses.values()) - sum(penalties.values())
        )
        return final, penalties, bonuses

    def _history_context(
        self, model_id: str
    ) -> tuple[set[str], set[str], tuple[dict[str, float], ...]]:
        rows = self.connection.execute(
            """
            SELECT scene_id FROM recommendation_history
            ORDER BY shown_at_ms DESC LIMIT ?
            """,
            (self.config.ranking.history_size,),
        ).fetchall()
        scene_ids = [str(row[0]) for row in rows]
        if not scene_ids:
            return set(), set(), ()
        placeholders = ",".join("?" for _ in scene_ids)
        performers = {
            str(row[0])
            for row in self.connection.execute(
                f"SELECT performer_id FROM scene_performer WHERE scene_id IN ({placeholders})",
                scene_ids,
            )
        }
        studios = {
            str(row[0])
            for row in self.connection.execute(
                f"""
                SELECT COALESCE(st.parent_studio_id, s.studio_id)
                FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
                WHERE s.scene_id IN ({placeholders}) AND s.studio_id IS NOT NULL
                """,
                scene_ids,
            )
        }
        feature_row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        vectors = FeatureStore(self.connection).scene_content_vectors(str(feature_row[0]))
        return (
            performers,
            studios,
            tuple(vectors[scene_id] for scene_id in scene_ids if scene_id in vectors),
        )

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(name, 0.0) for name, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
