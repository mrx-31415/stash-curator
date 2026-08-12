"""Greedy deterministic slate selection with hard and soft variety rules."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from heapq import heappop, heappush
from typing import Any

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.events.contracts import OBSERVED_PLAYBACK_SQL
from curator.features import FeatureStore
from curator.model import RecommendationModelStore
from curator.model.boundaries import scene_eligibility
from curator.model.curves import scene_recovery
from curator.profiling import record_duration
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
QUERIED_SCORE_FIRST_LANES = frozenset({"best_bets", "revisit", "discover"})
SCORE_FIRST_RANKING_JSON = json.dumps(
    {
        "penalties": {
            "performer": 0.0,
            "studio": 0.0,
            "content": 0.0,
            "history": 0.0,
            "live_cooldown": 0.0,
        },
        "bonuses": {"uncovered_content": 0.0},
    },
    separators=(",", ":"),
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
        *,
        diversity_enabled: bool = True,
    ) -> None:
        self.connection = connection
        self.config = config
        self.diversity_enabled = diversity_enabled
        self._cached_model_id: str | None = None
        self._cached_source_lanes: frozenset[str] = frozenset()
        self._cached_candidates: tuple[_Candidate, ...] = ()
        self._cached_vectors: dict[str, dict[str, float]] = {}
        self._pair_similarities: dict[tuple[str, str], float] = {}
        self._history_similarities: dict[str, float] = {}
        self._live_fit: dict[str, float] = {}
        self._live_cooldown: dict[str, float] = {}
        self.materialize_timings_ms: dict[str, int] = {}

    def prepare(self, model_id: str, *, slate_size: int = 60) -> dict[str, int]:
        policy = LanePolicy(self.connection, self.config)
        prepared: list[_Candidate] = []
        counts: dict[str, int] = {}
        for lane in LANES:
            classifications = policy.load(model_id, lanes={lane})
            candidates = self._candidates(model_id, classifications)
            prepared.extend(candidates)
            counts[lane] = len(candidates)
        with transaction(self.connection):
            self.connection.execute(
                "DELETE FROM model_lane_candidate_cache WHERE model_id=?", (model_id,)
            )
            self.connection.execute("DELETE FROM application_meta WHERE key LIKE 'slate:%'")
        self._save_prepared_candidates(model_id, set(LANES), tuple(prepared))
        for lane in (*LANES, "for_you"):
            self.recommend(lane, slate_size)
        return counts

    def materialize(
        self,
        model_id: str,
        *,
        force: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, int]:
        if (
            not force
            and self.connection.execute(
                "SELECT 1 FROM model_lane_order_state WHERE model_id=?", (model_id,)
            ).fetchone()
        ):
            result = {
                str(row["lane"]): int(row["candidate_count"])
                for row in self.connection.execute(
                    """
                    SELECT lane, count(*) AS candidate_count FROM model_scene_lane
                    WHERE model_id=? GROUP BY lane
                    """,
                    (model_id,),
                )
            }
            if progress:
                progress(1, 1)
            return result
        classifications = LanePolicy(self.connection, self.config).load(model_id)
        candidates = self._candidates(model_id, classifications)
        counts = {
            lane: sum(candidate.classification.lane == lane for candidate in candidates)
            for lane in LANES
        }
        with transaction(self.connection):
            self.connection.execute(
                "DELETE FROM model_lane_order_state WHERE model_id=?", (model_id,)
            )
            self.connection.execute("DELETE FROM model_lane_order WHERE model_id=?", (model_id,))
        completed = 0
        total = len(LANES) + 3
        timings = {"score_first_ordering": 0, "varied_ordering": 0}
        for lane in (*LANES, "for_you"):
            lane_candidates = tuple(
                candidate
                for candidate in candidates
                if lane == "for_you" or candidate.classification.lane == lane
            )
            orderings = [("varied", True)]
            if lane not in QUERIED_SCORE_FIRST_LANES:
                orderings.insert(0, ("score_first", False))
            for ordering, varied in orderings:
                ordering_started = time.perf_counter()
                ordered = self._build_order(lane, lane_candidates, varied=varied)
                with transaction(self.connection):
                    self.connection.executemany(
                        """
                        INSERT INTO model_lane_order(
                            model_id, lane, ordering, position, scene_id,
                            source_lane, utility, ranking_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            (
                                model_id,
                                lane,
                                ordering,
                                position,
                                candidate.classification.scene_id,
                                candidate.classification.lane,
                                utility,
                                json.dumps(
                                    {"penalties": penalties, "bonuses": bonuses},
                                    separators=(",", ":"),
                                ),
                            )
                            for position, (candidate, utility, penalties, bonuses) in enumerate(
                                ordered
                            )
                        ),
                    )
                timings[f"{ordering}_ordering"] += round(
                    (time.perf_counter() - ordering_started) * 1000
                )
                completed += 1
                if progress:
                    progress(completed, total)
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO model_lane_order_state(model_id, created_at_ms) VALUES (?, ?)
                """,
                (model_id, time.time_ns() // 1_000_000),
            )
        self.materialize_timings_ms = timings
        for name, duration in timings.items():
            record_duration("python", f"ranking.{name}", duration)
        return counts

    def _build_order(
        self, lane: str, candidates: tuple[_Candidate, ...], *, varied: bool
    ) -> list[tuple[_Candidate, float, dict[str, float], dict[str, float]]]:
        by_key = {
            (candidate.classification.scene_id, candidate.classification.lane): candidate
            for candidate in candidates
        }
        utilities = {
            key: candidate.classification.lane_value
            + (self.config.ranking.uncovered_content_bonus if varied and candidate.content else 0.0)
            for key, candidate in by_key.items()
        }
        versions = dict.fromkeys(by_key, 0)
        heaps: dict[tuple[str, str], list[tuple[float, str, str, int]]] = defaultdict(list)

        def selectors(candidate: _Candidate) -> tuple[tuple[str, str], ...]:
            result = [("all", "")]
            if lane == "for_you":
                result.append(("lane", candidate.classification.lane))
            elif lane == "adventure" and candidate.classification.subtype:
                result.append(("subtype", candidate.classification.subtype))
            return tuple(result)

        def push(key: tuple[str, str]) -> None:
            candidate = by_key[key]
            entry = (
                -utilities[key],
                candidate.classification.scene_id,
                candidate.classification.lane,
                versions[key],
            )
            for selector in selectors(candidate):
                heappush(heaps[selector], entry)

        for key in by_key:
            push(key)

        selected_scene_ids: set[str] = set()
        seen_performers: set[str] = set()
        seen_studios: set[str] = set()
        covered_features: set[str] = set()
        performer_penalized: set[tuple[str, str]] = set()
        studio_penalized: set[tuple[str, str]] = set()
        covered_share = dict.fromkeys(by_key, 0.0)
        content_totals = {
            key: sum(abs(value) for value in candidate.content.values())
            for key, candidate in by_key.items()
        }
        performer_index: dict[str, set[tuple[str, str]]] = defaultdict(set)
        studio_index: dict[str, set[tuple[str, str]]] = defaultdict(set)
        feature_index: dict[str, list[tuple[tuple[str, str], float]]] = defaultdict(list)
        if varied:
            for key, candidate in by_key.items():
                for performer in candidate.performers:
                    performer_index[performer].add(key)
                if candidate.studio_group:
                    studio_index[candidate.studio_group].add(key)
                total = content_totals[key]
                if total:
                    for feature, value in candidate.content.items():
                        feature_index[feature].append((key, abs(value) / total))

        def pop(
            selector: tuple[str, str],
            previous: _Candidate | None,
            *,
            allow_adjacent: bool = False,
        ) -> _Candidate | None:
            deferred: list[tuple[float, str, str, int]] = []
            heap = heaps[selector]
            chosen = None
            while heap:
                entry = heappop(heap)
                key = (entry[1], entry[2])
                if (
                    key not in by_key
                    or entry[3] != versions[key]
                    or by_key[key].classification.scene_id in selected_scene_ids
                ):
                    continue
                candidate = by_key[key]
                if (
                    varied
                    and previous
                    and not allow_adjacent
                    and not self.config.ranking.adjacent_shared_performers
                    and set(candidate.performers) & set(previous.performers)
                ):
                    deferred.append(entry)
                    continue
                chosen = candidate
                break
            for entry in deferred:
                heappush(heap, entry)
            return chosen

        ordered: list[tuple[_Candidate, float, dict[str, float], dict[str, float]]] = []
        previous: _Candidate | None = None
        scene_count = len({candidate.classification.scene_id for candidate in candidates})
        while len(selected_scene_ids) < scene_count:
            target_lane, target_subtype = self._target(lane, len(ordered), 0)
            wanted = (
                ("subtype", target_subtype)
                if lane == "adventure" and target_subtype
                else ("lane", target_lane)
                if lane == "for_you"
                else ("all", "")
            )
            chosen = pop(wanted, previous) or pop(("all", ""), previous)
            if chosen is None:
                chosen = pop(("all", ""), previous, allow_adjacent=True)
            if chosen is None:
                break
            key = (chosen.classification.scene_id, chosen.classification.lane)
            penalties = {
                "performer": (
                    self.config.ranking.performer_repeat_penalty
                    if key in performer_penalized
                    else 0.0
                ),
                "studio": (self.config.ranking.studio_penalty if key in studio_penalized else 0.0),
                "content": (
                    self.config.ranking.content_penalty * covered_share[key] if varied else 0.0
                ),
                "history": 0.0,
                "live_cooldown": 0.0,
            }
            bonuses = {
                "uncovered_content": (
                    self.config.ranking.uncovered_content_bonus * (1 - covered_share[key])
                    if varied and chosen.content
                    else 0.0
                )
            }
            ordered.append((chosen, utilities[key], penalties, bonuses))
            selected_scene_ids.add(chosen.classification.scene_id)
            previous = chosen
            if not varied:
                continue
            changed: set[tuple[str, str]] = set()
            for performer in set(chosen.performers) - seen_performers:
                seen_performers.add(performer)
                for affected in performer_index[performer] - performer_penalized:
                    performer_penalized.add(affected)
                    utilities[affected] -= self.config.ranking.performer_repeat_penalty
                    changed.add(affected)
            if chosen.studio_group and chosen.studio_group not in seen_studios:
                seen_studios.add(chosen.studio_group)
                for affected in studio_index[chosen.studio_group] - studio_penalized:
                    studio_penalized.add(affected)
                    utilities[affected] -= self.config.ranking.studio_penalty
                    changed.add(affected)
            for feature in set(chosen.content) - covered_features:
                covered_features.add(feature)
                for affected, share in feature_index[feature]:
                    covered_share[affected] += share
                    utilities[affected] -= (
                        self.config.ranking.content_penalty
                        + self.config.ranking.uncovered_content_bonus
                    ) * share
                    changed.add(affected)
            for affected in changed:
                if by_key[affected].classification.scene_id in selected_scene_ids:
                    continue
                versions[affected] += 1
                push(affected)
        return ordered

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
        if exploration == 0:
            materialized = self._load_materialized_slate(model_id, lane, count)
            if materialized is not None:
                return materialized
        prepared_slate = None
        if exploration == 0:
            prepared_slate = self._load_prepared_slate(model_id, lane, count)
            if prepared_slate is not None and len(prepared_slate.items) >= count:
                return prepared_slate
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
                classifications = policy.load(model_id, lanes=source_lanes)
                if not classifications:
                    policy.classify(model_id)
                    classifications = policy.load(model_id, lanes=source_lanes)
            timings["classifications"] = round((time.perf_counter() - started) * 1000)
            record_duration("python", "ranking.classifications", timings["classifications"])
            stage_started = time.perf_counter()
            self._cached_model_id = model_id
            self._cached_source_lanes = source_lane_key
            self._cached_candidates = prepared or tuple(self._candidates(model_id, classifications))
            if not prepared:
                self._save_prepared_candidates(model_id, source_lanes, self._cached_candidates)
            timings["candidates"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "ranking.candidates", timings["candidates"])
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
        record_duration("python", "ranking.eligibility", timings["eligibility"])
        stage_started = time.perf_counter()
        candidate_lookup = {
            (item.classification.scene_id, item.classification.lane): item for item in candidates
        }
        prefix_items = tuple(
            item
            for item in (prepared_slate.items if prepared_slate else ())
            if (item.scene_id, item.source_lane) in candidate_lookup
        )
        selected = [candidate_lookup[(item.scene_id, item.source_lane)] for item in prefix_items]
        selected_utilities: list[tuple[float, dict[str, float], dict[str, float]]] = []
        diagnostics: list[str] = []
        history = self._history_context(model_id) if self.diversity_enabled else (set(), set(), ())
        self._pair_similarities.clear()
        self._history_similarities = (
            {
                candidate.classification.scene_id: max(
                    (self._cosine(candidate.content, vector) for vector in history[2]), default=0.0
                )
                for candidate in candidates
            }
            if self.diversity_enabled
            else {}
        )
        timings["history"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "ranking.history", timings["history"])
        stage_started = time.perf_counter()
        selected_scene_ids = {candidate.classification.scene_id for candidate in selected}
        seen_performers = {
            performer for candidate in selected for performer in candidate.performers
        }
        seen_studios = {candidate.studio_group for candidate in selected if candidate.studio_group}
        covered_content = {name for candidate in selected for name in candidate.content}
        content_similarities = (
            {
                candidate.classification.scene_id: max(
                    (self._candidate_similarity(candidate, previous) for previous in selected),
                    default=0.0,
                )
                for candidate in candidates
            }
            if self.diversity_enabled
            else {}
        )
        for position in range(len(selected), count):
            target_lane, target_subtype = self._target(lane, position, exploration)
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
                utility = self._utility(
                    candidate,
                    selected[-1] if selected else None,
                    history,
                    seen_performers,
                    seen_studios,
                    covered_content,
                    content_similarities.get(candidate.classification.scene_id, 0.0),
                )
                if utility is None:
                    continue
                ranked.append((utility[0], candidate.classification.scene_id, candidate, utility))
            if not ranked and self.config.ranking.relax_adjacent_when_exhausted:
                diagnostics.append(f"position {position}: relaxed adjacent performer constraint")
                for candidate in pool:
                    utility = self._utility(
                        candidate,
                        selected[-1] if selected else None,
                        history,
                        seen_performers,
                        seen_studios,
                        covered_content,
                        content_similarities.get(candidate.classification.scene_id, 0.0),
                        relax_adjacent=True,
                    )
                    if utility:
                        ranked.append(
                            (utility[0], candidate.classification.scene_id, candidate, utility)
                        )
            if not ranked:
                diagnostics.append(f"position {position}: candidate pool exhausted")
                break
            _, _, chosen, utility = min(ranked, key=lambda item: (-item[0], item[1]))
            selected.append(chosen)
            selected_scene_ids.add(chosen.classification.scene_id)
            selected_utilities.append(utility)
            if self.diversity_enabled:
                seen_performers.update(chosen.performers)
                if chosen.studio_group:
                    seen_studios.add(chosen.studio_group)
                covered_content.update(chosen.content)
                for candidate in remaining:
                    scene_id = candidate.classification.scene_id
                    if scene_id in selected_scene_ids:
                        continue
                    content_similarities[scene_id] = max(
                        content_similarities[scene_id],
                        self._candidate_similarity(candidate, chosen),
                    )

        timings["selection"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "ranking.selection", timings["selection"])
        stage_started = time.perf_counter()
        new_selected = selected[len(prefix_items) :]
        scores = RecommendationModelStore(self.connection).scores(
            model_id, {candidate.classification.scene_id for candidate in new_selected}
        )
        items = list(prefix_items)
        selected_items = zip(new_selected, selected_utilities, strict=True)
        for position, (chosen, utility) in enumerate(selected_items, start=len(prefix_items)):
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
        record_duration("python", "ranking.items", timings["items"])
        timings["total"] = round((time.perf_counter() - started) * 1000)
        slate = Slate(model_id, lane, tuple(items), tuple(diagnostics), timings)
        if exploration == 0:
            self._save_prepared_slate(slate)
        return slate

    def _load_materialized_slate(self, model_id: str, lane: str, count: int) -> Slate | None:
        started = time.perf_counter()
        if not self.connection.execute(
            "SELECT 1 FROM model_lane_order_state WHERE model_id=?", (model_id,)
        ).fetchone():
            return None
        ordering = "varied" if self.diversity_enabled else "score_first"
        query_score_first = not self.diversity_enabled and lane in QUERIED_SCORE_FIRST_LANES
        now_ms = time.time_ns() // 1_000_000
        direct_plays, unrecovered_direct_plays = self._direct_play_filters(now_ms)
        selected_rows: list[sqlite3.Row] = []
        offset = 0
        chunk_size = max(100, count)
        while len(selected_rows) < count:
            if query_score_first:
                rows = self.connection.execute(
                    """
                    SELECT 0 AS position, scene_id, lane AS source_lane,
                           lane_value AS utility, ? AS ranking_json
                    FROM model_scene_lane
                    WHERE model_id=? AND lane=?
                    ORDER BY lane_value DESC, scene_id
                    LIMIT ? OFFSET ?
                    """,
                    (SCORE_FIRST_RANKING_JSON, model_id, lane, chunk_size, offset),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    """
                    SELECT position, scene_id, source_lane, utility, ranking_json
                    FROM model_lane_order
                    WHERE model_id=? AND lane=? AND ordering=?
                    ORDER BY position LIMIT ? OFFSET ?
                    """,
                    (model_id, lane, ordering, chunk_size, offset),
                ).fetchall()
            if not rows:
                break
            offset += len(rows)
            scene_ids = {str(row["scene_id"]) for row in rows}
            eligibility = scene_eligibility(
                self.connection, now_ms, self.config, scene_ids=scene_ids
            )
            selected_rows.extend(
                row
                for row in rows
                if self._materialized_row_is_eligible(
                    row, eligibility, direct_plays, unrecovered_direct_plays
                )
            )
            if len(rows) < chunk_size:
                break
        selected_rows = selected_rows[:count]
        scene_ids = {str(row["scene_id"]) for row in selected_rows}
        scores = RecommendationModelStore(self.connection).scores(model_id, scene_ids)
        classifications: dict[tuple[str, str], LaneClassification] = {}
        if scene_ids:
            placeholders = ",".join("?" for _ in scene_ids)
            for row in self.connection.execute(
                f"""
                SELECT scene_id, lane, subtype, lane_value, qualification_json
                FROM model_scene_lane
                WHERE model_id=? AND scene_id IN ({placeholders})
                """,
                (model_id, *scene_ids),
            ):
                classification = LaneClassification(
                    str(row["scene_id"]),
                    str(row["lane"]),
                    str(row["subtype"]) if row["subtype"] else None,
                    float(row["lane_value"]),
                    json.loads(str(row["qualification_json"])),
                )
                classifications[(classification.scene_id, classification.lane)] = classification
        self._live_fit, self._live_cooldown = self._live_current_fit(model_id, direct_plays, now_ms)
        items = []
        for position, row in enumerate(selected_rows):
            scene_id = str(row["scene_id"])
            source_lane = str(row["source_lane"])
            classification = classifications[(scene_id, source_lane)]
            score = scores[scene_id]
            ranking = json.loads(str(row["ranking_json"]))
            penalties = {
                str(name): float(value)
                for name, value in dict(ranking.get("penalties", {})).items()
            }
            penalties["live_cooldown"] = self._live_cooldown.get(scene_id, 0.0)
            bonuses = {
                str(name): float(value) for name, value in dict(ranking.get("bonuses", {})).items()
            }
            reasons = ["eligibility.lane"]
            reasons.extend(
                f"diversity.{name}"
                for name, value in penalties.items()
                if name != "live_cooldown" and value > 0
            )
            items.append(
                RecommendationItem(
                    scene_id,
                    lane,
                    source_lane,
                    classification.subtype,
                    position,
                    score.appeal,
                    self._live_fit.get(scene_id, score.current_fit),
                    score.confidence,
                    classification.lane_value,
                    float(row["utility"]) - penalties["live_cooldown"],
                    penalties,
                    bonuses,
                    score.components,
                    score.neighbors,
                    score.eligibility,
                    classification.qualification,
                    tuple(reasons),
                )
            )
        elapsed = round((time.perf_counter() - started) * 1_000)
        record_duration("python", "ranking.materialized", elapsed)
        return Slate(
            model_id,
            lane,
            tuple(items),
            (),
            {"materialized": 1, "selection": elapsed, "total": elapsed},
        )

    def available_count(
        self,
        model_id: str | None,
        lane: str,
        *,
        exclude_scene_ids: set[str] | None = None,
    ) -> int | None:
        """Count a materialized lane without hydrating recommendation items.

        The lane spans the whole library, but the eligibility inputs (feedback, exclusions,
        pruning, blocked tags, file availability) change rarely, so the per-lane count is
        cached under a fingerprint of those inputs and only recomputed when they change.
        Slate items are still eligibility-checked per request; only the pagination total is
        reused. Plays are deliberately not part of the fingerprint: they change constantly
        and only shift best-bets/revisit totals by a few.
        """
        started = time.perf_counter()
        if model_id is None:
            return None
        if not self.connection.execute(
            "SELECT 1 FROM model_lane_order_state WHERE model_id=?", (model_id,)
        ).fetchone():
            return None
        ordering = "varied" if self.diversity_enabled else "score_first"
        query_score_first = not self.diversity_enabled and lane in QUERIED_SCORE_FIRST_LANES
        excluded = exclude_scene_ids or set()
        fingerprint = self._eligibility_fingerprint()
        cache_key = f"eligibility_count:{model_id}:{lane}:{ordering}"
        row = self.connection.execute(
            "SELECT value FROM application_meta WHERE key=?", (cache_key,)
        ).fetchone()
        if row is not None:
            payload = json.loads(str(row[0]))
            if payload.get("fingerprint") == fingerprint:
                total = int(payload["count"]) - self._excluded_eligible_count(excluded)
                elapsed = round((time.perf_counter() - started) * 1_000)
                record_duration("python", "ranking.available_count", elapsed)
                return max(0, total)
        if query_score_first:
            rows = self.connection.execute(
                """
                SELECT scene_id, lane AS source_lane
                FROM model_scene_lane
                WHERE model_id=? AND lane=?
                """,
                (model_id, lane),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT scene_id, source_lane
                FROM model_lane_order
                WHERE model_id=? AND lane=? AND ordering=?
                """,
                (model_id, lane, ordering),
            ).fetchall()
        scene_ids = {str(row["scene_id"]) for row in rows}
        now_ms = time.time_ns() // 1_000_000
        eligibility = scene_eligibility(self.connection, now_ms, self.config, scene_ids=scene_ids)
        direct_plays, unrecovered_direct_plays = self._direct_play_filters(now_ms)
        total = sum(
            self._materialized_row_is_eligible(
                row, eligibility, direct_plays, unrecovered_direct_plays
            )
            for row in rows
        )
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    cache_key,
                    json.dumps({"fingerprint": fingerprint, "count": total}, separators=(",", ":")),
                ),
            )
        total -= self._excluded_eligible_count(excluded)
        elapsed = round((time.perf_counter() - started) * 1_000)
        record_duration("python", "ranking.available_count", elapsed)
        return max(0, total)

    def _eligibility_fingerprint(self) -> str:
        """Cheap digest of the eligibility inputs that change between model rebuilds."""
        digest = hashlib.sha256()
        for label, sql in (
            (
                "feedback",
                "SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM feedback"
                " WHERE reversed_by_id IS NULL",
            ),
            (
                "exclusion",
                "SELECT count(*), coalesce(max(created_at_ms), 0) FROM exclusion"
                " WHERE reversed_at_ms IS NULL",
            ),
            (
                "pruning",
                "SELECT count(*), coalesce(max(updated_at_ms), 0) FROM pruning_candidate",
            ),
            (
                "blocked_tags",
                "SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM direct_tag_preference"
                " WHERE blocked=1",
            ),
            (
                "blocked_terms",
                "SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM direct_term_preference"
                " WHERE blocked=1",
            ),
            ("files", "SELECT count(*), 0 FROM source_file WHERE available=1"),
        ):
            row = self.connection.execute(sql).fetchone()
            digest.update(f"{label}:{row[0]}:{row[1]}".encode())
        return digest.hexdigest()

    def _excluded_eligible_count(self, excluded: set[str]) -> int:
        """Eligible scenes among this request's per-lane exclusions."""
        if not excluded:
            return 0
        eligibility = scene_eligibility(
            self.connection, time.time_ns() // 1_000_000, self.config, scene_ids=excluded
        )
        return sum(1 for scene_id in excluded if eligibility.get(scene_id, {}).get("eligible"))

    def score_review_available_count(self, model_id: str, max_appeal: float = 0.0) -> int:
        """Count eligible scenes at the bottom of the appeal distribution
        (appeal <= max_appeal) without hydrating items, applying the same
        live eligibility as the slate path."""
        scene_ids = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT scene_id FROM model_scene_score
                WHERE model_id=? AND appeal <= ?
                """,
                (model_id, max_appeal),
            )
        }
        eligibility = scene_eligibility(
            self.connection, time.time_ns() // 1_000_000, self.config, scene_ids=scene_ids
        )
        return sum(1 for scene_id in scene_ids if eligibility.get(scene_id, {}).get("eligible"))

    def score_review(self, model_id: str, count: int, *, max_appeal: float = 0.0) -> Slate:
        """The bottom of the appeal distribution: model_scene_score rows
        ordered by appeal ASC (tie-break scene_id), filtered appeal <=
        max_appeal, the same live eligibility applied as the slate path,
        hydrated into recommendation items with score-first semantics
        (final_utility = appeal, the score-first zero penalties/bonuses, lane
        "score_review")."""
        if model_id is None:
            raise RuntimeError("no published model; run build-model first")
        started = time.perf_counter()
        now_ms = time.time_ns() // 1_000_000
        selected_rows: list[sqlite3.Row] = []
        offset = 0
        chunk_size = max(100, count)
        while len(selected_rows) < count:
            rows = self.connection.execute(
                """
                SELECT scene_id FROM model_scene_score
                WHERE model_id=? AND appeal <= ?
                ORDER BY appeal ASC, scene_id
                LIMIT ? OFFSET ?
                """,
                (model_id, max_appeal, chunk_size, offset),
            ).fetchall()
            if not rows:
                break
            offset += len(rows)
            scene_ids = {str(row["scene_id"]) for row in rows}
            eligibility = scene_eligibility(
                self.connection, now_ms, self.config, scene_ids=scene_ids
            )
            selected_rows.extend(
                row for row in rows if eligibility.get(str(row["scene_id"]), {}).get("eligible")
            )
            if len(rows) < chunk_size:
                break
        selected_rows = selected_rows[:count]
        scene_ids = {str(row["scene_id"]) for row in selected_rows}
        scores = RecommendationModelStore(self.connection).scores(model_id, scene_ids)
        penalties = json.loads(SCORE_FIRST_RANKING_JSON)["penalties"]
        penalties["live_cooldown"] = 0.0
        bonuses = json.loads(SCORE_FIRST_RANKING_JSON)["bonuses"]
        items = []
        for position, row in enumerate(selected_rows):
            scene_id = str(row["scene_id"])
            score = scores[scene_id]
            items.append(
                RecommendationItem(
                    scene_id,
                    "score_review",
                    "score_review",
                    None,
                    position,
                    score.appeal,
                    score.current_fit,
                    score.confidence,
                    score.appeal,
                    score.appeal,
                    dict(penalties),
                    dict(bonuses),
                    score.components,
                    score.neighbors,
                    score.eligibility,
                    {},
                    ("eligibility.lane",),
                )
            )
        elapsed = round((time.perf_counter() - started) * 1_000)
        record_duration("python", "ranking.score_review", elapsed)
        return Slate(
            model_id,
            "score_review",
            tuple(items),
            (),
            {"materialized": 1, "selection": elapsed, "total": elapsed},
        )

    def _direct_play_filters(self, now_ms: int) -> tuple[dict[str, int], set[str]]:
        direct_plays = {
            str(row["scene_id"]): int(row["last_played"])
            for row in self.connection.execute(
                f"""
                SELECT scene_id, max(ended_at_ms) AS last_played FROM play_session
                WHERE provenance='direct_player' AND {OBSERVED_PLAYBACK_SQL} GROUP BY scene_id
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
        return direct_plays, unrecovered_direct_plays

    @staticmethod
    def _materialized_row_is_eligible(
        row: sqlite3.Row,
        eligibility: dict[str, dict[str, object]],
        direct_plays: dict[str, int],
        unrecovered_direct_plays: set[str],
    ) -> bool:
        scene_id = str(row["scene_id"])
        source_lane = str(row["source_lane"])
        return (
            bool(eligibility.get(scene_id, {}).get("eligible", False))
            and not (source_lane == "best_bets" and scene_id in direct_plays)
            and not (source_lane == "revisit" and scene_id in unrecovered_direct_plays)
        )

    def _save_prepared_slate(self, slate: Slate) -> None:
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    self._slate_key(slate.model_id, slate.lane),
                    json.dumps(
                        {
                            "created_at_ms": time.time_ns() // 1_000_000,
                            "items": [asdict(item) for item in slate.items],
                        },
                        separators=(",", ":"),
                    ),
                ),
            )

    def _load_prepared_slate(self, model_id: str, lane: str, count: int) -> Slate | None:
        started = time.perf_counter()
        row = self.connection.execute(
            "SELECT value FROM application_meta WHERE key=?",
            (self._slate_key(model_id, lane),),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        created_at_ms = int(payload["created_at_ms"])
        if time.time_ns() // 1_000_000 - created_at_ms > 3_600_000:
            return None
        items = tuple(self._recommendation_item(item) for item in payload["items"])
        if not items:
            return Slate(model_id, lane, (), (), {"precomputed": 1, "total": 0})
        scene_ids = {item.scene_id for item in items}
        eligibility = scene_eligibility(
            self.connection,
            time.time_ns() // 1_000_000,
            self.config,
            scene_ids=scene_ids,
        )
        placeholders = ",".join("?" for _ in scene_ids)
        changed = {
            str(row[0])
            for row in self.connection.execute(
                f"""
                SELECT scene_id FROM play_session
                WHERE ended_at_ms>=? AND scene_id IN ({placeholders})
                AND (provenance<>'direct_player' OR {OBSERVED_PLAYBACK_SQL})
                """,
                (created_at_ms, *scene_ids),
            )
        }
        selected = tuple(
            replace(item, position=position)
            for position, item in enumerate(
                item
                for item in items
                if item.scene_id not in changed
                and bool(eligibility.get(item.scene_id, {}).get("eligible", False))
            )
        )[:count]
        elapsed = round((time.perf_counter() - started) * 1_000)
        return Slate(model_id, lane, selected, (), {"precomputed": 1, "total": elapsed})

    @staticmethod
    def _recommendation_item(payload: dict[str, Any]) -> RecommendationItem:
        return RecommendationItem(
            scene_id=str(payload["scene_id"]),
            lane=str(payload["lane"]),
            source_lane=str(payload["source_lane"]),
            subtype=str(payload["subtype"]) if payload.get("subtype") else None,
            position=int(payload["position"]),
            appeal=float(payload["appeal"]),
            current_fit=float(payload["current_fit"]),
            confidence=float(payload["confidence"]),
            lane_value=float(payload["lane_value"]),
            final_utility=float(payload["final_utility"]),
            penalties={str(k): float(v) for k, v in dict(payload["penalties"]).items()},
            bonuses={str(k): float(v) for k, v in dict(payload["bonuses"]).items()},
            components=dict(payload["components"]),
            neighbors=tuple(dict(item) for item in payload["neighbors"]),
            eligibility=dict(payload["eligibility"]),
            qualification=dict(payload["qualification"]),
            reason_ids=tuple(map(str, payload["reason_ids"])),
        )

    def _load_prepared(self, model_id: str, lanes: set[str]) -> tuple[_Candidate, ...]:
        placeholders = ",".join("?" for _ in lanes)
        rows = self.connection.execute(
            f"""
            SELECT lane, candidates_json, candidate_count FROM model_lane_candidate_cache
            WHERE model_id=? AND lane IN ({placeholders})
            """,
            (model_id, *lanes),
        ).fetchall()
        if {str(row["lane"]) for row in rows} != lanes:
            return ()
        expected = {
            str(row["lane"]): int(row["candidate_count"])
            for row in self.connection.execute(
                f"""
                SELECT lane, count(*) AS candidate_count FROM model_scene_lane
                WHERE model_id=? AND lane IN ({placeholders}) GROUP BY lane
                """,
                (model_id, *lanes),
            )
        }
        if any(int(row["candidate_count"]) != expected.get(str(row["lane"]), 0) for row in rows):
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

    def _save_prepared_candidates(
        self, model_id: str, lanes: set[str], candidates: tuple[_Candidate, ...]
    ) -> None:
        rows = []
        for lane in lanes:
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
                if item.classification.lane == lane
            ]
            rows.append(
                (
                    model_id,
                    lane,
                    json.dumps(payload, separators=(",", ":")),
                    len(payload),
                    time.time_ns() // 1_000_000,
                )
            )
        with transaction(self.connection):
            self.connection.executemany(
                """
                INSERT INTO model_lane_candidate_cache(
                    model_id, lane, candidates_json, candidate_count, created_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(model_id, lane) DO UPDATE SET
                    candidates_json=excluded.candidates_json,
                    candidate_count=excluded.candidate_count,
                    created_at_ms=excluded.created_at_ms
                """,
                rows,
            )

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
        previous: _Candidate | None,
        history: tuple[set[str], set[str], tuple[dict[str, float], ...]],
        seen_performers: set[str],
        seen_studios: set[str],
        covered_content: set[str],
        content_similarity: float,
        *,
        relax_adjacent: bool = False,
    ) -> tuple[float, dict[str, float], dict[str, float]] | None:
        if (
            self.diversity_enabled
            and previous
            and not self.config.ranking.adjacent_shared_performers
            and not relax_adjacent
            and set(candidate.performers) & set(previous.performers)
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
        uncovered_share = 0.0
        if self.diversity_enabled:
            if set(candidate.performers) & seen_performers:
                penalties["performer"] = self.config.ranking.performer_repeat_penalty
            if candidate.studio_group and candidate.studio_group in seen_studios:
                penalties["studio"] = self.config.ranking.studio_penalty
            penalties["content"] = self.config.ranking.content_penalty * content_similarity
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
            uncovered_share = (
                len(set(candidate.content) - covered_content) / len(candidate.content)
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

    def _slate_key(self, model_id: str, lane: str) -> str:
        suffix = "" if self.diversity_enabled else ":unshuffled"
        return f"slate:{model_id}:{lane}{suffix}"

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
