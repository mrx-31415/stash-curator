"""Read published feature snapshots without exposing SQLite rows downstream."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from curator.features.profiles import (
    PerformerProfile,
    ProfileValue,
    SimilarityResult,
    performer_similarity,
)


@dataclass(frozen=True)
class StoredFeature:
    feature_id: str
    family: str
    name: str
    value: float
    confidence: float
    metadata: dict[str, object]


class FeatureStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_version(self) -> str | None:
        row = self.connection.execute(
            "SELECT feature_version FROM feature_build WHERE status = 'published'"
        ).fetchone()
        return str(row[0]) if row else None

    def entity_features(
        self, feature_version: str, entity_type: str
    ) -> dict[str, tuple[StoredFeature, ...]]:
        rows = self.connection.execute(
            """
            SELECT ef.entity_id, ef.feature_id, fd.family, fd.name, ef.value,
                   ef.confidence, fd.metadata_json
            FROM entity_feature ef
            JOIN feature_definition fd ON fd.feature_id = ef.feature_id
            WHERE ef.feature_version = ? AND ef.entity_type = ?
            ORDER BY ef.entity_id, fd.family, fd.name
            """,
            (feature_version, entity_type),
        )
        result: dict[str, list[StoredFeature]] = {}
        for row in rows:
            result.setdefault(str(row["entity_id"]), []).append(
                StoredFeature(
                    str(row["feature_id"]),
                    str(row["family"]),
                    str(row["name"]),
                    float(row["value"]),
                    float(row["confidence"]),
                    json.loads(row["metadata_json"]),
                )
            )
        return {key: tuple(value) for key, value in result.items()}

    def scene_content_vectors(self, feature_version: str) -> dict[str, dict[str, float]]:
        vectors: dict[str, dict[str, float]] = {}
        for row in self.connection.execute(
            """
            SELECT ef.entity_id, fd.name, ef.value
            FROM entity_feature ef
            JOIN feature_definition fd ON fd.feature_id=ef.feature_id
            WHERE ef.feature_version=? AND ef.entity_type='scene' AND fd.family='content'
            ORDER BY ef.entity_id, fd.name
            """,
            (feature_version,),
        ):
            vectors.setdefault(str(row["entity_id"]), {})[str(row["name"])] = float(row["value"])
        return vectors

    def performer_profiles(self, feature_version: str) -> dict[str, PerformerProfile]:
        features = self.entity_features(feature_version, "performer")
        profiles: dict[str, PerformerProfile] = {}
        for performer_id, values in features.items():
            blocks: dict[str, dict[str, ProfileValue]] = {}
            for feature in values:
                if not feature.family.startswith("profile:"):
                    continue
                block = feature.family.removeprefix("profile:")
                blocks.setdefault(block, {})[feature.name] = ProfileValue(
                    feature.value, feature.confidence
                )
            profiles[performer_id] = PerformerProfile(performer_id, blocks)
        return profiles

    def similar_performers(
        self,
        feature_version: str,
        performer_id: str,
        *,
        count: int,
        block_weights: dict[str, float],
    ) -> tuple[tuple[str, SimilarityResult], ...]:
        profiles = self.performer_profiles(feature_version)
        target = profiles.get(performer_id)
        if target is None:
            return ()
        ranked = (
            (other_id, performer_similarity(target, profile, block_weights))
            for other_id, profile in profiles.items()
            if other_id != performer_id
        )
        return tuple(sorted(ranked, key=lambda item: (-item[1].similarity, item[0]))[:count])
