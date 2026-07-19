"""Greedy deterministic slate selection with hard and soft variety rules."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from heapq import nsmallest

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.features import FeatureStore
from curator.model import RecommendationModelStore
from curator.model.boundaries import scene_eligibility
from curator.model.curves import scene_recovery
from curator.ranking.policy import LANES, LaneClassification, LanePolicy
from curator.storage import transaction

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
    timings_ms: dict[str, int] = field(default_factory=dict)


class SlateBuilder:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: CuratorConfig = DEFAULT_CONFIG,
    ) -> None:
        self.connection = connection
        self.config = config
        self._cached_model_id: str | None = None
        self._cached_source_lanes: frozenset[str] = frozenset()
        self._cached_candidates: tuple[_Candidate, ...] = ()
        self._cached_vectors: dict[str, dict[str, float]] = {}
        self._pair_similarities: dict[tuple[str, str], float] = {}
        self._history_similarities: dict[str, float] = {}
        self._live_fit: dict[str, float] = {}
        self._live_cooldown: dict[str, float] = {}

    def prepare(self, model_id: str, *, limit_per_lane: int = 500) -> dict[str, int]:
        policy = LanePolicy(self.connection, self.config)
        prepared: list[tuple[str, str, int]] = []
        for lane in LANES:
            classifications = policy.load(model_id, lanes={lane}, limit_per_lane=limit_per_lane)
            candidates = self._candidates(model_id, classifications)
            payload = [
                {
                    "scene_id": item.classification.scene_id,
                    "lane": item.classification.lane,
                    "subtype": item.classification.subtype,
                    "lane_value": item.classification.lane_value,
                    "qualification": item.classification.qualification,
                    "performers": item.performers,
                    "studio_group": item.studio_group,
                    "content": item.content,
                }
                for item in candidates
            ]
            prepared.append((lane, json.dumps(payload, separators=(",", ":")), len(payload)))
        with transaction(self.connection):
            self.connection.execute(
                "DELETE FROM model_lane_candidate_cache WHERE model_id=?", (model_id,)
            )
            self.connection.executemany(
                """
                INSERT INTO model_lane_candidate_cache(
                    model_id, lane, candidates_json, candidate_count, created_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (model_id, lane, payload, count, time.time_ns() // 1_000_000)
                    for lane, payload, count in prepared
                ),
            )
        return {lane: count for lane, _, count in prepared}

    def recommend(self, lane: str, count: int, *, exploration: float = 0) -> Slate:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        if lane not in {"for_you", "best_bets", "revisit", "discover", "adventure"}:
            raise ValueError(f"unknown lane: {lane}")
        if count < 1:
            raise ValueError("count must be positive")
        if not math.isfinite(exploration) or not -1 <= exploration <= 1:
            raise ValueError("exploration must be between -1 and 1")
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model; run build-model first")
        source_lanes = {lane}
        if lane == "for_you":
            source_lanes = set(self.config.ranking.for_you_pattern)
            if exploration:
                source_lanes.update(FAMILIAR_PATTERN if exploration < 0 else ADVENTUROUS_PATTERN)
        source_lane_key = frozenset(source_lanes)
        if model_id != self._cached_model_id or source_lane_key != self._cached_source_lanes:
            policy = LanePolicy(self.connection, self.config)
            prepared = self._load_prepared(model_id, source_lanes)
            classifications: tuple[LaneClassification, ...] = ()
            if not prepared:
                classifications = policy.load(
                    model_id,
                    lanes=source_lanes,
                    limit_per_lane=max(500, count * 20),
                ) or policy.classify(model_id)
            timings["classifications"] = round((time.perf_counter() - started) * 1000)
            stage_started = time.perf_counter()
            self._cached_model_id = model_id
            self._cached_source_lanes = source_lane_key
            self._cached_candidates = prepared or tuple(self._candidates(model_id, classifications))
            timings["candidates"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        now_ms = time.time_ns() // 1_000_000
        candidate_ids = {item.classification.scene_id for item in self._cached_candidates}
        live_eligibility = scene_eligibility(
            self.connection, now_ms, self.config, scene_ids=candidate_ids
        )
        direct_plays = {
            str(row["scene_id"]): int(row["last_played"])
            for row in self.connection.execute(
                """
                SELECT scene_id, max(ended_at_ms) AS last_played FROM play_session
                WHERE provenance='direct_player' GROUP BY scene_id
                """
            )
        }
        unrecovered_direct_plays = {
            scene_id
            for scene_id, played_at_ms in direct_plays.items()
            if scene_recovery(
                max(0.0, (now_ms - played_at_ms) / 86_400_000), config=self.config.model
            )
            < 0.10
        }
        candidates = tuple(
            candidate
            for candidate in self._cached_candidates
            if bool(
                live_eligibility.get(candidate.classification.scene_id, {}).get("eligible", False)
            )
            and not (
                candidate.classification.lane == "best_bets"
                and candidate.classification.scene_id in direct_plays
            )
            and not (
                candidate.classification.lane == "revisit"
                and candidate.classification.scene_id in unrecovered_direct_plays
            )
        )
        self._live_fit, self._live_cooldown = self._live_current_fit(model_id, direct_plays, now_ms)
        timings["eligibility"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        selected: list[_Candidate] = []
        selected_utilities: list[tuple[float, dict[str, float], dict[str, float]]] = []
        diagnostics: list[str] = []
        history = self._history_context(model_id)
        self._pair_similarities.clear()
        self._history_similarities = {
            candidate.classification.scene_id: max(
                (self._cosine(candidate.content, vector) for vector in history[2]), default=0.0
            )
            for candidate in candidates
        }
        timings["history"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
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
            # ponytail: 500 leaves broad diversity room; raise only if real slates exhaust it.
            pool = nsmallest(
                max(500, count * 20),
                pool,
                key=lambda candidate: (
                    -candidate.classification.lane_value,
                    candidate.classification.scene_id,
                ),
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
            _, _, chosen, utility = min(ranked, key=lambda item: (-item[0], item[1]))
            selected.append(chosen)
            selected_utilities.append(utility)

        timings["selection"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        scores = RecommendationModelStore(self.connection).scores(
            model_id, {candidate.classification.scene_id for candidate in selected}
        )
        items: list[RecommendationItem] = []
        selected_items = zip(selected, selected_utilities, strict=True)
        for position, (chosen, utility) in enumerate(selected_items):
            score = scores[chosen.classification.scene_id]
            reasons = ["eligibility.lane"]
            reasons.extend(f"diversity.{name}" for name, value in utility[1].items() if value > 0)
            items.append(
                RecommendationItem(
                    chosen.classification.scene_id,
                    lane,
                    chosen.classification.lane,
                    chosen.classification.subtype,
                    position,
                    score.appeal,
                    self._live_fit.get(score.scene_id, score.current_fit),
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
        timings["items"] = round((time.perf_counter() - stage_started) * 1000)
        timings["total"] = round((time.perf_counter() - started) * 1000)
        return Slate(model_id, lane, tuple(items), tuple(diagnostics), timings)

    def _load_prepared(self, model_id: str, lanes: set[str]) -> tuple[_Candidate, ...]:
        placeholders = ",".join("?" for _ in lanes)
        rows = self.connection.execute(
            f"""
            SELECT lane, candidates_json FROM model_lane_candidate_cache
            WHERE model_id=? AND lane IN ({placeholders})
            """,
            (model_id, *lanes),
        ).fetchall()
        if {str(row["lane"]) for row in rows} != lanes:
            return ()
        candidates = tuple(
            _Candidate(
                LaneClassification(
                    str(item["scene_id"]),
                    str(item["lane"]),
                    str(item["subtype"]) if item.get("subtype") else None,
                    float(item["lane_value"]),
                    dict(item["qualification"]),
                ),
                tuple(map(str, item["performers"])),
                str(item["studio_group"]) if item.get("studio_group") else None,
                {str(name): float(value) for name, value in item["content"].items()},
            )
            for row in rows
            for item in json.loads(str(row["candidates_json"]))
        )
        self._cached_vectors = {
            candidate.classification.scene_id: candidate.content for candidate in candidates
        }
        return candidates

    def _target(self, lane: str, position: int, exploration: float) -> tuple[str, str | None]:
        if lane == "for_you":
            base = self.config.ranking.for_you_pattern
            alternative = FAMILIAR_PATTERN if exploration < 0 else ADVENTUROUS_PATTERN
            mixed_slots = round(abs(exploration) * len(base))
            use_alternative = (position * 7) % len(base) < mixed_slots
            pattern = alternative if use_alternative else base
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
        scene_ids = {item.scene_id for item in classifications}
        vectors = FeatureStore(self.connection).scene_content_vectors(
            str(feature_row[0]), scene_ids
        )
        self._cached_vectors = vectors
        performers: dict[str, list[str]] = {}
        placeholders = ",".join("?" for _ in scene_ids)
        for row in self.connection.execute(
            f"""
            SELECT scene_id, performer_id FROM scene_performer
            WHERE scene_id IN ({placeholders}) ORDER BY scene_id, position
            """,
            tuple(scene_ids),
        ):
            performers.setdefault(str(row["scene_id"]), []).append(str(row["performer_id"]))
        studios = {
            str(row["scene_id"]): (
                str(row["parent_studio_id"] or row["studio_id"]) if row["studio_id"] else None
            )
            for row in self.connection.execute(
                f"""
                SELECT s.scene_id, s.studio_id, st.parent_studio_id
                FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
                WHERE s.scene_id IN ({placeholders})
                """,
                tuple(scene_ids),
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
        penalties = {
            "performer": 0.0,
            "studio": 0.0,
            "content": 0.0,
            "history": 0.0,
            "live_cooldown": 0.0,
        }
        penalties["live_cooldown"] = self._live_cooldown.get(candidate.classification.scene_id, 0.0)
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
                * self._candidate_similarity(candidate, previous),
            )
        history_performers, history_studios, history_vectors = history
        if set(candidate.performers) & history_performers:
            penalties["history"] += self.config.ranking.history_performer_penalty
        if candidate.studio_group and candidate.studio_group in history_studios:
            penalties["history"] += self.config.ranking.history_studio_penalty
        if history_vectors:
            penalties["history"] += (
                self.config.ranking.history_content_penalty
                * self._history_similarities[candidate.classification.scene_id]
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

    def _live_current_fit(
        self, model_id: str, direct_plays: dict[str, int], now_ms: int
    ) -> tuple[dict[str, float], dict[str, float]]:
        if not direct_plays:
            return {}, {}
        placeholders = ",".join("?" for _ in direct_plays)
        rows = self.connection.execute(
            f"""
            SELECT scene_id, appeal, current_fit FROM model_scene_score
            WHERE model_id=? AND scene_id IN ({placeholders})
            """,
            (model_id, *direct_plays),
        )
        result: dict[str, float] = {}
        penalties: dict[str, float] = {}
        for row in rows:
            scene_id = str(row["scene_id"])
            appeal = float(row["appeal"])
            days = max(0.0, (now_ms - direct_plays[scene_id]) / 86_400_000)
            recovery = scene_recovery(days, config=self.config.model)
            live_fit = appeal - max(0.0, appeal) * (1 - recovery)
            stored_fit = float(row["current_fit"])
            result[scene_id] = min(stored_fit, live_fit)
            penalties[scene_id] = max(0.0, stored_fit - live_fit)
        return result, penalties

    def _candidate_similarity(self, left: _Candidate, right: _Candidate) -> float:
        left_id = left.classification.scene_id
        right_id = right.classification.scene_id
        key = (left_id, right_id) if left_id <= right_id else (right_id, left_id)
        if key not in self._pair_similarities:
            self._pair_similarities[key] = self._cosine(left.content, right.content)
        return self._pair_similarities[key]

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
        return (
            performers,
            studios,
            # Content repetition is about the immediate run; performer and studio
            # repetition still use the full history window above.
            tuple(
                self._cached_vectors[scene_id]
                for scene_id in scene_ids[:10]
                if scene_id in self._cached_vectors
            ),
        )

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(name, 0.0) for name, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
