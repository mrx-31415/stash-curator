"""Preference-aware local scene and performer similarity."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, replace

from curator.config import DEFAULT_CONFIG
from curator.features import FeatureStore, performer_similarity
from curator.model import RecommendationModelStore
from curator.profiling import record_duration
from curator.taxonomy import equivalent_tag_names


@dataclass(frozen=True)
class SimilarityResult:
    entity_id: str
    similarity: float
    appeal: float
    rank_score: float
    relationships: tuple[str, ...]
    details: dict[str, object]


class SimilarityService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        started = time.perf_counter()
        self.connection = connection
        model = RecommendationModelStore(connection)
        model_id = model.current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        self.model_id = model_id
        row = connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (self.model_id,)
        ).fetchone()
        self.feature_version = str(row[0])
        self.appeals = {
            str(row["scene_id"]): float(row["appeal"])
            for row in connection.execute(
                """
                SELECT scene_id, max(appeal) AS appeal FROM model_scene_lane
                WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id
                """,
                (self.model_id,),
            )
        }
        if not self.appeals:
            self.appeals = {
                str(row["scene_id"]): float(row["appeal"])
                for row in connection.execute(
                    """
                    SELECT scene_id, appeal FROM model_scene_score
                    WHERE model_id=? AND json_extract(eligibility_json, '$.eligible')=1
                    """,
                    (self.model_id,),
                )
            }
        self.timings_ms = {"initialization": round((time.perf_counter() - started) * 1000)}
        record_duration("python", "similarity.initialization", self.timings_ms["initialization"])

    def scenes(
        self,
        scene_id: str,
        count: int = 20,
        gender: str = "",
        *,
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_ids: tuple[str, ...] = (),
        studio_ids: tuple[str, ...] = (),
        favorite_only: bool = False,
        minimum_similarity: float = 0.18,
    ) -> tuple[SimilarityResult, ...]:
        if (
            self.connection.execute(
                "SELECT 1 FROM model_scene_score WHERE model_id=? AND scene_id=?",
                (self.model_id, scene_id),
            ).fetchone()
            is None
        ):
            raise ValueError(f"unknown scene: {scene_id}")
        features = FeatureStore(self.connection)
        started = time.perf_counter()
        candidate_ids = set(self.appeals)
        target_content = features.scene_content_vectors(self.feature_version, [scene_id]).get(
            scene_id, {}
        )
        content_overlaps = features.scene_content_overlaps(self.feature_version, scene_id)
        self.timings_ms["content"] = round((time.perf_counter() - started) * 1000)
        record_duration("python", "similarity.content", self.timings_ms["content"])
        started = time.perf_counter()
        performers = self._scene_performers()
        genders = self._performer_genders()
        target_performers = performers.get(scene_id, set())
        profiles = features.performer_profiles(self.feature_version)
        self.timings_ms["profiles"] = round((time.perf_counter() - started) * 1000)
        record_duration("python", "similarity.profiles", self.timings_ms["profiles"])
        started = time.perf_counter()
        weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
        performer_scores: dict[str, float] = {}
        for target_id in target_performers:
            target = profiles.get(target_id)
            if target is None:
                continue
            for other_id, profile in profiles.items():
                performer_scores[other_id] = max(
                    performer_scores.get(other_id, 0),
                    performer_similarity(target, profile, weights).similarity,
                )
        self.timings_ms["performer_similarity"] = round((time.perf_counter() - started) * 1000)
        record_duration(
            "python", "similarity.performer_similarity", self.timings_ms["performer_similarity"]
        )
        started = time.perf_counter()
        target_studio = self._studios().get(scene_id)
        studios = self._studios()
        target_structure = min(1.0, max(0, len(target_performers) - 1) / 3)
        names = {
            f"tag:{row['tag_id']}": str(row["name"])
            for row in self.connection.execute("SELECT tag_id, name FROM source_tag")
        }
        included = equivalent_tag_names(self.connection, include_tags)
        excluded = equivalent_tag_names(self.connection, exclude_tags)
        filter_names = set().union(*included, *excluded)
        scene_tags = self._scene_tags(filter_names) if filter_names else {}
        favorites = (
            {
                str(row[0])
                for row in self.connection.execute(
                    "SELECT performer_id FROM source_performer WHERE favorite=1"
                )
            }
            if favorite_only
            else set()
        )
        results: list[SimilarityResult] = []
        for candidate_id in candidate_ids:
            candidate_appeal = self.appeals[candidate_id]
            if candidate_id == scene_id:
                continue
            candidate_performers = performers.get(candidate_id, set())
            if gender and not any(genders.get(value) == gender for value in candidate_performers):
                continue
            same = target_performers & candidate_performers
            profile_value = max(
                (performer_scores.get(value, 0) for value in candidate_performers), default=0
            )
            performer_value = 1.0 if same else profile_value
            candidate_tags = scene_tags.get(candidate_id, set())
            if any(not group & candidate_tags for group in included):
                continue
            if any(group & candidate_tags for group in excluded):
                continue
            if favorite_only and not favorites & candidate_performers:
                continue
            if performer_ids and not set(performer_ids) <= candidate_performers:
                continue
            if studio_ids and studios.get(candidate_id) not in studio_ids:
                continue
            content_value = content_overlaps.get(candidate_id, 0.0)
            structure = 1 - abs(
                target_structure - min(1.0, max(0, len(candidate_performers) - 1) / 3)
            )
            same_studio = bool(target_studio and studios.get(candidate_id) == target_studio)
            similarity = (
                0.5 * content_value
                + 0.3 * performer_value
                + 0.1 * structure
                + 0.1 * float(same_studio)
            )
            if similarity < minimum_similarity:
                continue
            relationships: list[str] = []
            if same:
                relationships.append("same_performer")
            elif profile_value >= 0.65:
                relationships.append("similar_performer")
            if content_value > 0:
                relationships.append("shared_content")
            if structure >= 0.8:
                relationships.append("similar_structure")
            if same_studio:
                relationships.append("same_studio")
            appeal = (candidate_appeal + 1) / 2
            results.append(
                SimilarityResult(
                    candidate_id,
                    similarity,
                    appeal,
                    0.7 * similarity + 0.3 * appeal,
                    tuple(relationships),
                    {
                        "content": content_value,
                        "performer": performer_value,
                        "structure": structure,
                        "studio": float(same_studio),
                        "shared_tags": [],
                        "shared_performer_ids": sorted(same),
                    },
                )
            )
        ranked = sorted(results, key=lambda item: (-item.rank_score, item.entity_id))
        selected = self._diverse_scenes(ranked, performers, count)
        self.timings_ms["ranking"] = round((time.perf_counter() - started) * 1000)
        record_duration("python", "similarity.filter_and_rank", self.timings_ms["ranking"])
        started = time.perf_counter()
        selected_content = features.scene_content_vectors(
            self.feature_version, [item.entity_id for item in selected]
        )
        result = tuple(
            replace(
                item,
                details={
                    **item.details,
                    "shared_tags": [
                        names.get(key, key.removeprefix("tag:"))
                        for key in sorted(
                            set(target_content) & set(selected_content.get(item.entity_id, {})),
                            key=lambda key: (
                                -target_content[key] * selected_content[item.entity_id][key]
                            ),
                        )[:5]
                    ],
                },
            )
            for item in selected
        )
        self.timings_ms["details"] = round((time.perf_counter() - started) * 1000)
        record_duration("python", "similarity.details", self.timings_ms["details"])
        self.timings_ms["total"] = sum(self.timings_ms.values())
        return result

    def performers(
        self, performer_id: str, count: int = 20, gender: str = ""
    ) -> tuple[SimilarityResult, ...]:
        features = FeatureStore(self.connection)
        matches = features.similar_performers(
            self.feature_version,
            performer_id,
            count=10_000,
            block_weights=dict(DEFAULT_CONFIG.feature.performer_block_weights),
        )
        if (
            not matches
            and self.connection.execute(
                "SELECT 1 FROM source_performer WHERE performer_id=?", (performer_id,)
            ).fetchone()
            is None
        ):
            raise ValueError(f"unknown performer: {performer_id}")
        scene_performers = self._scene_performers()
        scenes_by_performer: dict[str, list[float]] = {}
        for scene_id, performer_ids in scene_performers.items():
            appeal = self.appeals.get(scene_id)
            if appeal is None:
                continue
            for candidate_id in performer_ids:
                scenes_by_performer.setdefault(candidate_id, []).append((appeal + 1) / 2)
        results = []
        genders = self._performer_genders()
        for candidate_id, match in matches:
            if gender and genders.get(candidate_id) != gender:
                continue
            values = sorted(scenes_by_performer.get(candidate_id, ()), reverse=True)[:5]
            appeal = sum(values) / len(values) if values else 0.5
            results.append(
                SimilarityResult(
                    candidate_id,
                    match.similarity,
                    appeal,
                    0.7 * match.similarity + 0.3 * appeal,
                    ("similar_performer",),
                    {
                        "blocks": match.block_similarities,
                        "block_weights": match.block_weights,
                    },
                )
            )
        return tuple(sorted(results, key=lambda item: (-item.rank_score, item.entity_id))[:count])

    def _performer_genders(self) -> dict[str, str]:
        return {
            str(row["performer_id"]): str(row["gender"] or "")
            for row in self.connection.execute("SELECT performer_id, gender FROM source_performer")
        }

    def _scene_performers(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"
        ):
            result.setdefault(str(row["scene_id"]), set()).add(str(row["performer_id"]))
        return result

    def _scene_tags(self, names: set[str]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in self.connection.execute(
            f"""
            SELECT st.scene_id, t.name FROM scene_tag st
            JOIN source_tag t USING(tag_id) WHERE lower(t.name) IN
            ({",".join("?" for _ in names)})
            """,
            sorted(names),
        ):
            result.setdefault(str(row["scene_id"]), set()).add(str(row["name"]).casefold())
        return result

    def _studios(self) -> dict[str, str]:
        return {
            str(row["scene_id"]): str(row["studio_id"])
            for row in self.connection.execute(
                "SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL"
            )
        }

    @staticmethod
    def _diverse_scenes(
        ranked: list[SimilarityResult], performers: dict[str, set[str]], count: int
    ) -> tuple[SimilarityResult, ...]:
        selected: list[SimilarityResult] = []
        remaining = ranked[:]
        while remaining and len(selected) < count:
            previous = performers.get(selected[-1].entity_id, set()) if selected else set()
            index = next(
                (
                    i
                    for i, item in enumerate(remaining)
                    if not previous & performers.get(item.entity_id, set())
                ),
                0,
            )
            selected.append(remaining.pop(index))
        return tuple(selected)
