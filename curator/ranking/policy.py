"""Inspectable qualification policies for the four source lanes."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import cast

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.events.contracts import OBSERVED_PLAYBACK_SQL
from curator.features import FeatureStore
from curator.model import ModelSceneScore, RecommendationModelStore
from curator.model.curves import entity_dormancy
from curator.storage import transaction

LANES = ("best_bets", "revisit", "stretch", "blind_spots", "dormant")


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

    def classify(
        self,
        model_id: str,
        *,
        progress: Callable[[int, int], None] | None = None,
        now_ms: int | None = None,
    ) -> tuple[LaneClassification, ...]:
        if now_ms is None:
            now_ms = time.time_ns() // 1_000_000
        scores = RecommendationModelStore(self.connection).classification_data(model_id)
        eligible_scores = {
            scene_id: score
            for scene_id, score in scores.items()
            if bool(score.eligibility.get("eligible", False))
        }
        played_scene_ids = self._played_scene_ids()
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
        blind_spot_context = self._blind_spot_context(model_id, set(eligible_scores))
        dormant_context = self._dormant_context(model_id, set(eligible_scores), now_ms)
        classifications: list[LaneClassification] = []
        stretch_raw: dict[str, dict[str, object]] = {}
        total = len(eligible_scores)
        for position, (scene_id, score) in enumerate(sorted(eligible_scores.items()), 1):
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
            best_bet = (
                score.current_fit >= self.config.ranking.best_bet_fit
                and score.confidence >= self.config.ranking.best_bet_confidence
                and score.metadata_confidence >= self.config.ranking.best_bet_metadata_confidence
                and relevance >= self.config.ranking.best_bet_relevance
                and (corroborated or direct_reliable)
                and scene_id not in played_scene_ids
            )
            if best_bet:
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
                and {"o", "thumb_up", "repeat", "scene_rating", "curation_rating"}
                & set(map(str, signals))
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
            stretch_contributors = score.components.get("stretch_contributors")
            stretch_positive = (
                stretch_contributors.get("positive", [])
                if isinstance(stretch_contributors, dict)
                else []
            )
            stretch_negative = (
                stretch_contributors.get("negative", [])
                if isinstance(stretch_contributors, dict)
                else []
            )
            anchors = [
                item
                for item in stretch_positive
                if _number(item.get("affinity")) >= self.config.ranking.stretch_anchor_affinity
                and _number(item.get("confidence")) >= self.config.ranking.stretch_anchor_confidence
            ]
            tested_negative = [
                item
                for item in stretch_negative
                if _number(item.get("affinity")) <= -self.config.ranking.stretch_anchor_affinity
                and _number(item.get("confidence")) >= self.config.ranking.stretch_anchor_confidence
            ]
            untested = [
                item
                for item in stretch_positive + stretch_negative
                if _number(item.get("effective_support"))
                < self.config.ranking.stretch_untested_support
            ]
            challenges = [(item, "tested_negative") for item in tested_negative] + [
                (item, "untested") for item in untested
            ]
            if (
                not best_bet
                and score.direct_confidence < self.config.ranking.revisit_direct_confidence
                and anchors
                and challenges
                and score.current_fit >= self.config.ranking.stretch_fit_floor
            ):
                challenged_item, challenge_kind = max(
                    challenges,
                    key=lambda pair: (
                        abs(_number(pair[0].get("value"))),
                        str(pair[0].get("feature_id")),
                    ),
                )
                challenge_distance = (
                    abs(_number(challenged_item.get("affinity")))
                    * _number(challenged_item.get("confidence"))
                    if challenge_kind == "tested_negative"
                    else 1 - _number(challenged_item.get("confidence"))
                )
                stretch_raw[scene_id] = {
                    "anchor_features": anchors,
                    "challenged_feature": challenged_item,
                    "challenge_kind": challenge_kind,
                    "anchor_strength": sum(_number(item.get("value")) for item in anchors),
                    "challenge_distance": challenge_distance,
                }
            context = blind_spot_context.get(
                scene_id, {"dark_facets": [], "content_feature_count": 0}
            )
            dark_facets = cast(list[dict[str, object]], context["dark_facets"])
            facet_types = {str(item["facet_type"]) for item in dark_facets}
            if (
                scene_id not in played_scene_ids
                and cast(int, context["content_feature_count"])
                >= self.config.ranking.dark_min_features
                and len(facet_types) >= self.config.ranking.dark_min_facet_types
            ):
                max_darkness = max(_number(item["darkness"]) for item in dark_facets)
                blind_spot_value = (
                    max_darkness
                    * (1 + self.config.ranking.dark_corroboration_bonus * (len(facet_types) - 1))
                    * score.metadata_confidence
                    * (1 + max(0.0, score.appeal))
                )
                subtype = (
                    "never_played"
                    if all(int(cast(int, item["played_count"])) == 0 for item in dark_facets)
                    else "under_played"
                )
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "blind_spots",
                        subtype,
                        blind_spot_value,
                        {
                            "dark_facets": sorted(
                                dark_facets,
                                key=lambda item: (-_number(item["darkness"]), str(item["id"])),
                            ),
                            "corroborating_types": len(facet_types),
                        },
                    )
                )
            dormant_candidate = dormant_context.get(scene_id)
            if scene_id not in played_scene_ids and dormant_candidate is not None:
                classifications.append(
                    LaneClassification(
                        scene_id,
                        "dormant",
                        str(dormant_candidate["entity_type"]),
                        _number(dormant_candidate["positive_strength"]) * fit_ranks[scene_id],
                        {
                            "dormant_entity": {
                                "type": dormant_candidate["entity_type"],
                                "id": dormant_candidate["entity_id"],
                                "name": dormant_candidate["name"],
                            },
                            "days_since_played": round(
                                _number(dormant_candidate["days_since_played"])
                            ),
                            "positive_strength": _number(dormant_candidate["positive_strength"]),
                            "supporting_plays": dormant_candidate["supporting_plays"],
                            "dormancy": _number(dormant_candidate["dormancy"]),
                        },
                    )
                )
            if progress and (position == total or position % 250 == 0):
                progress(position, max(1, total))
        if progress and not total:
            progress(1, 1)
        # Stretch's lane_value needs a global percentile pass, so it is assembled
        # after the per-scene loop: anchor_strength is normalized across every
        # qualifying scene, while challenge_distance is normalized separately
        # within each challenge kind (tested_negative vs untested), since the two
        # kinds use incomparable distance formulas. See
        # docs/workpackage-lane-redesign.md defect 1.
        anchor_percentiles = _percentiles(
            {scene_id: _number(raw["anchor_strength"]) for scene_id, raw in stretch_raw.items()}
        )
        challenge_percentiles: dict[str, float] = {}
        for kind in ("tested_negative", "untested"):
            challenge_percentiles.update(
                _percentiles(
                    {
                        scene_id: _number(raw["challenge_distance"])
                        for scene_id, raw in stretch_raw.items()
                        if raw["challenge_kind"] == kind
                    }
                )
            )
        for scene_id, raw in stretch_raw.items():
            challenged_item = cast(dict[str, object], raw["challenged_feature"])
            classifications.append(
                LaneClassification(
                    scene_id,
                    "stretch",
                    cast(str, raw["challenge_kind"]),
                    anchor_percentiles[scene_id] * challenge_percentiles[scene_id],
                    {
                        "anchor_features": [
                            {
                                "feature_id": item["feature_id"],
                                "name": item["name"],
                                "value": _number(item.get("value")),
                            }
                            for item in cast(list[dict[str, object]], raw["anchor_features"])
                        ],
                        "challenged_feature": {
                            "feature_id": challenged_item["feature_id"],
                            "name": challenged_item["name"],
                            "facet_type": challenged_item["facet_type"],
                            "affinity": _number(challenged_item.get("affinity")),
                            "confidence": _number(challenged_item.get("confidence")),
                        },
                        "challenge_kind": raw["challenge_kind"],
                        "anchor_strength": _number(raw["anchor_strength"]),
                        "challenge_distance": _number(raw["challenge_distance"]),
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
        selected_lanes: tuple[str | None, ...] = tuple(lanes) if lanes else (None,)
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

    def _played_scene_ids(self) -> set[str]:
        """Scenes the user has watched, from Stash history and from Curator's own player.

        Stash only reports a play once its own threshold is met and a sync has run since, so
        classification would otherwise keep offering back scenes watched in this session.
        """
        return {
            str(row[0])
            for row in self.connection.execute(
                f"""
                SELECT DISTINCT scene_id FROM source_play
                UNION
                SELECT DISTINCT scene_id FROM play_session
                WHERE provenance<>'direct_player' OR {OBSERVED_PLAYBACK_SQL}
                """
            )
        }

    def _blind_spot_context(
        self, model_id: str, scene_ids: set[str]
    ) -> dict[str, dict[str, object]]:
        """Per-scene dark-facet data for Blind Spots: which studio/confirmed-tag
        facets are underexplored relative to the library's overall play rate,
        and how many of the scene's facet types corroborate each other.

        Darkness uses a Beta-posterior shrink toward the library base rate
        (alpha = dark_prior_strength) rather than an unregularized mean, so a
        facet with few scenes does not get an unbounded darkness score just
        because none of its handful of scenes happen to be played yet. See
        docs/workpackage-lane-redesign.md ("Blind Spots").
        """
        feature_row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        features_by_scene = FeatureStore(self.connection).entity_features(
            str(feature_row[0]), "scene"
        )
        played = self._played_scene_ids()

        content_feature_count = {
            scene_id: sum(1 for feature in features if feature.family == "content")
            for scene_id, features in features_by_scene.items()
        }

        # Tag facets: content features confirmed against the StashDB taxonomy
        # (see "Tag confirmation" — role_reason must resolve via stashdb_*, not
        # the content_default fallback). Studio facets: source_scene.studio_id,
        # one authoritative FK per scene.
        tag_scenes: dict[str, set[str]] = defaultdict(set)
        tag_names: dict[str, str] = {}
        for scene_id, features in features_by_scene.items():
            for feature in features:
                if feature.family != "content":
                    continue
                metadata = feature.metadata
                reason = metadata.get("role_reason")
                if metadata.get("tag_id") is None or not (
                    isinstance(reason, str) and reason.startswith("stashdb_")
                ):
                    continue
                tag_scenes[feature.feature_id].add(scene_id)
                tag_names[feature.feature_id] = str(metadata.get("tag_name") or feature.name)

        scene_studio: dict[str, str] = {}
        studio_scenes: dict[str, set[str]] = defaultdict(set)
        studio_names: dict[str, str] = {}
        for row in self.connection.execute(
            """
            SELECT s.scene_id, s.studio_id, st.name FROM source_scene s
            JOIN source_studio st ON st.studio_id = s.studio_id
            WHERE s.studio_id IS NOT NULL
            """
        ):
            scene_id, studio_id = str(row["scene_id"]), str(row["studio_id"])
            scene_studio[scene_id] = studio_id
            studio_scenes[studio_id].add(scene_id)
            studio_names[studio_id] = str(row["name"] or "")

        total_scenes = max(1, len(features_by_scene))
        played_scenes = len(played & set(features_by_scene))
        base_rate = played_scenes / total_scenes
        alpha = self.config.ranking.dark_prior_strength

        def darkness_of(scenes: set[str]) -> tuple[float, int, int]:
            library_count = len(scenes)
            played_count = len(scenes & played)
            if base_rate <= 0:
                return 0.0, library_count, played_count
            rate = (played_count + alpha * base_rate) / (library_count + alpha)
            return max(0.0, min(1.0, 1 - rate / base_rate)), library_count, played_count

        def dark_facets_of(pool: dict[str, set[str]]) -> dict[str, tuple[float, int, int]]:
            result: dict[str, tuple[float, int, int]] = {}
            for facet_id, scenes in pool.items():
                darkness, library_count, played_count = darkness_of(scenes)
                if (
                    darkness >= self.config.ranking.dark_threshold
                    and self.config.ranking.dark_min_library
                    <= library_count
                    <= self.config.ranking.dark_max_library
                ):
                    result[facet_id] = (darkness, library_count, played_count)
            return result

        dark_tags = dark_facets_of(tag_scenes)
        dark_studios = dark_facets_of(studio_scenes)

        result: dict[str, dict[str, object]] = {}
        for scene_id in scene_ids:
            dark_facets: list[dict[str, object]] = []
            for feature in features_by_scene.get(scene_id, ()):
                if feature.family != "content" or feature.feature_id not in dark_tags:
                    continue
                darkness, library_count, played_count = dark_tags[feature.feature_id]
                dark_facets.append(
                    {
                        "facet_type": "tag",
                        "id": feature.feature_id,
                        "name": tag_names[feature.feature_id],
                        "library_count": library_count,
                        "played_count": played_count,
                        "darkness": darkness,
                    }
                )
            scene_studio_id = scene_studio.get(scene_id)
            if scene_studio_id is not None and scene_studio_id in dark_studios:
                darkness, library_count, played_count = dark_studios[scene_studio_id]
                dark_facets.append(
                    {
                        "facet_type": "studio",
                        "id": scene_studio_id,
                        "name": studio_names[scene_studio_id],
                        "library_count": library_count,
                        "played_count": played_count,
                        "darkness": darkness,
                    }
                )
            result[scene_id] = {
                "dark_facets": dark_facets,
                "content_feature_count": content_feature_count.get(scene_id, 0),
            }
        return result

    def _dormant_context(
        self, model_id: str, scene_ids: set[str], now_ms: int
    ) -> dict[str, dict[str, object]]:
        """Per-scene strongest qualifying dormant entity: a performer, studio,
        or confirmed tag the user used to watch a lot of, hasn't touched in a
        while, and whose scenes model_entity_dormancy shows a real positive
        history for (not just a stray play). "Now" is evaluated live, not
        frozen at build — see docs/workpackage-lane-redesign.md ("Dormant",
        "Evaluated at slate time, not frozen at build").
        """
        dormancy_rows = {
            (str(row["entity_type"]), str(row["entity_id"])): row
            for row in self.connection.execute(
                """
                SELECT entity_type, entity_id, last_played_at_ms, positive_strength,
                       play_count, distinct_scene_count
                FROM model_entity_dormancy WHERE model_id=?
                """,
                (model_id,),
            )
        }
        if not dormancy_rows:
            return {}
        scene_entities: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in self.connection.execute("SELECT scene_id, performer_id FROM scene_performer"):
            scene_entities[str(row["scene_id"])].append(("performer", str(row["performer_id"])))
        for row in self.connection.execute(
            "SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL"
        ):
            scene_entities[str(row["scene_id"])].append(("studio", str(row["studio_id"])))
        for row in self.connection.execute("SELECT scene_id, tag_id FROM scene_tag"):
            scene_entities[str(row["scene_id"])].append(("tag", str(row["tag_id"])))

        names: dict[str, dict[str, str]] = {
            "performer": {
                str(row["performer_id"]): str(row["name"] or "")
                for row in self.connection.execute(
                    "SELECT performer_id, name FROM source_performer"
                )
            },
            "studio": {
                str(row["studio_id"]): str(row["name"] or "")
                for row in self.connection.execute("SELECT studio_id, name FROM source_studio")
            },
            "tag": {
                str(row["tag_id"]): str(row["name"] or "")
                for row in self.connection.execute("SELECT tag_id, name FROM source_tag")
            },
        }

        result: dict[str, dict[str, object]] = {}
        for scene_id in scene_ids:
            best: dict[str, object] | None = None
            for entity_type, entity_id in scene_entities.get(scene_id, ()):
                row = dormancy_rows.get((entity_type, entity_id))
                if row is None:
                    continue
                play_count = int(row["play_count"])
                distinct_scene_count = int(row["distinct_scene_count"])
                positive_strength = _number(row["positive_strength"])
                if (
                    play_count < self.config.ranking.dormant_min_plays
                    or distinct_scene_count < self.config.ranking.dormant_min_scenes
                    or positive_strength < self.config.ranking.dormant_min_positive
                ):
                    continue
                days_since_played = max(0.0, (now_ms - int(row["last_played_at_ms"])) / 86_400_000)
                dormancy = entity_dormancy(days_since_played, config=self.config.model)
                if dormancy < self.config.ranking.dormant_floor:
                    continue
                if (
                    best is None
                    or positive_strength > _number(best["positive_strength"])
                    or (
                        positive_strength == _number(best["positive_strength"])
                        and entity_id < str(best["entity_id"])
                    )
                ):
                    best = {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "name": names[entity_type].get(entity_id) or entity_id,
                        "days_since_played": days_since_played,
                        "positive_strength": positive_strength,
                        "supporting_plays": play_count,
                        "dormancy": dormancy,
                    }
            if best is not None:
                result[scene_id] = best
        return result

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
