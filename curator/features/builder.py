"""Deterministic, versioned feature snapshot construction."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.features.measurements import (
    augmentation_category,
    parse_measurements,
    presence_category,
)
from curator.features.tag_roles import TagRole, TagRoleResolver, TagRoleResult
from curator.storage import transaction


class FeatureBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureBuildResult:
    feature_version: str
    scene_count: int
    performer_count: int
    feature_count: int
    reused: bool


@dataclass(frozen=True)
class _Feature:
    entity_type: str
    entity_id: str
    family: str
    name: str
    value: float
    confidence: float
    metadata: dict[str, object]


class FeatureBuilder:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: CuratorConfig = DEFAULT_CONFIG,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.connection = connection
        self.config = config
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def build(self) -> FeatureBuildResult:
        source_fingerprint = self._source_fingerprint()
        version_hash = hashlib.sha256(
            f"{source_fingerprint}\0{self.config.feature_json()}".encode()
        ).hexdigest()
        feature_version = f"fv-{version_hash[:20]}"
        existing = self.connection.execute(
            "SELECT status FROM feature_build WHERE feature_version = ?", (feature_version,)
        ).fetchone()
        if existing and existing["status"] == "published":
            return self._result(feature_version, reused=True)
        now = self.clock_ms()
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO feature_build(
                    feature_version, status, config_json, source_fingerprint, created_at_ms
                ) VALUES (?, 'building', ?, ?, ?)
                ON CONFLICT(feature_version) DO UPDATE SET status='building', error=NULL
                """,
                (feature_version, self.config.feature_json(), source_fingerprint, now),
            )
        try:
            roles = self._resolve_tag_roles()
            scene_features = self._scene_features(roles)
            performer_features = self._performer_features(scene_features)
            if self._source_fingerprint() != source_fingerprint:
                raise FeatureBuildError("source cache changed during feature construction")
            all_features = (*scene_features, *performer_features)
            self._publish(feature_version, source_fingerprint, roles, all_features)
            return self._result(feature_version, reused=False)
        except Exception as error:
            with transaction(self.connection):
                self.connection.execute(
                    "UPDATE feature_build SET status='failed', error=? WHERE feature_version=?",
                    (str(error)[:2000], feature_version),
                )
            raise

    def _result(self, feature_version: str, *, reused: bool) -> FeatureBuildResult:
        scene_count = self.connection.execute(
            """
            SELECT count(DISTINCT entity_id) FROM entity_feature
            WHERE feature_version = ? AND entity_type = 'scene'
            """,
            (feature_version,),
        ).fetchone()[0]
        performer_count = self.connection.execute(
            """
            SELECT count(DISTINCT entity_id) FROM entity_feature
            WHERE feature_version = ? AND entity_type = 'performer'
            """,
            (feature_version,),
        ).fetchone()[0]
        feature_count = self.connection.execute(
            "SELECT count(*) FROM feature_definition WHERE feature_version = ?",
            (feature_version,),
        ).fetchone()[0]
        return FeatureBuildResult(
            feature_version, int(scene_count), int(performer_count), int(feature_count), reused
        )

    def _source_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for table, id_column in (
            ("source_tag", "tag_id"),
            ("source_studio", "studio_id"),
            ("source_performer", "performer_id"),
            ("source_scene", "scene_id"),
        ):
            rows = self.connection.execute(
                f"SELECT {id_column}, source_hash FROM {table} ORDER BY {id_column}"
            )
            for row in rows:
                digest.update(f"{table}\0{row[0]}\0{row[1]}\n".encode())
        return digest.hexdigest()

    def _resolve_tag_roles(self) -> dict[str, TagRoleResult]:
        resolver = TagRoleResolver(self.config.feature)
        return {
            str(row["tag_id"]): resolver.resolve(str(row["tag_id"]), row["name"])
            for row in self.connection.execute(
                "SELECT tag_id, name FROM source_tag ORDER BY tag_id"
            )
        }

    def _scene_features(self, roles: dict[str, TagRoleResult]) -> tuple[_Feature, ...]:
        scene_ids = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT scene_id FROM source_scene ORDER BY scene_id"
            )
        ]
        direct: dict[str, set[str]] = defaultdict(set)
        for row in self.connection.execute(
            """
            SELECT scene_id, tag_id FROM scene_tag
            WHERE provenance='scene' ORDER BY scene_id, tag_id
            """
        ):
            if (
                roles.get(str(row["tag_id"]), TagRoleResult(TagRole.IGNORED, "missing")).role
                is TagRole.CONTENT
            ):
                direct[str(row["scene_id"])].add(str(row["tag_id"]))
        marker: dict[str, set[str]] = defaultdict(set)
        marker_rows = self.connection.execute(
            """
            SELECT sm.scene_id, sm.primary_tag_id AS tag_id FROM scene_marker sm
            WHERE sm.primary_tag_id IS NOT NULL
            UNION
            SELECT sm.scene_id, mt.tag_id FROM scene_marker sm
            JOIN marker_tag mt ON mt.marker_id = sm.marker_id
            ORDER BY scene_id, tag_id
            """
        )
        for row in marker_rows:
            tag_id = str(row["tag_id"])
            if roles.get(tag_id, TagRoleResult(TagRole.IGNORED, "missing")).role is TagRole.CONTENT:
                marker[str(row["scene_id"])].add(tag_id)
        parents: dict[str, set[str]] = defaultdict(set)
        for row in self.connection.execute(
            "SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id"
        ):
            parent = str(row["parent_tag_id"])
            if roles.get(parent, TagRoleResult(TagRole.IGNORED, "missing")).role is TagRole.CONTENT:
                parents[str(row["tag_id"])].add(parent)

        base_vectors: dict[str, dict[str, float]] = {}
        for scene_id in scene_ids:
            values: dict[str, float] = {}
            for tag_id in direct[scene_id]:
                values[tag_id] = 1.0
                for parent in parents[tag_id]:
                    values[parent] = max(values.get(parent, 0.0), self.config.feature.parent_weight)
            for tag_id in marker[scene_id]:
                values[tag_id] = max(values.get(tag_id, 0.0), self.config.feature.marker_weight)
                for parent in parents[tag_id]:
                    values[parent] = max(
                        values.get(parent, 0.0),
                        self.config.feature.marker_weight * self.config.feature.parent_weight,
                    )
            base_vectors[scene_id] = values
        document_frequency: dict[str, int] = defaultdict(int)
        for values in base_vectors.values():
            for tag_id in values:
                document_frequency[tag_id] += 1
        tag_names = {
            str(row["tag_id"]): str(row["name"] or "")
            for row in self.connection.execute("SELECT tag_id, name FROM source_tag")
        }
        features: list[_Feature] = []
        total = max(1, len(scene_ids))
        for scene_id in scene_ids:
            weighted: dict[str, float] = {}
            for tag_id, base in base_vectors[scene_id].items():
                frequency = document_frequency[tag_id]
                rarity = min(
                    self.config.feature.idf_cap,
                    1 + self.config.feature.idf_strength * math.log((total + 1) / (frequency + 1)),
                )
                shrinkage = frequency / (frequency + self.config.feature.one_off_prior)
                weighted[tag_id] = base * rarity * shrinkage
            norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
            for tag_id in sorted(weighted):
                features.append(
                    _Feature(
                        "scene",
                        scene_id,
                        "content",
                        f"tag:{tag_id}",
                        weighted[tag_id] / norm,
                        min(1.0, document_frequency[tag_id] / 3),
                        {
                            "tag_id": tag_id,
                            "tag_name": tag_names.get(tag_id, ""),
                            "document_frequency": document_frequency[tag_id],
                            "role_reason": roles[tag_id].reason,
                        },
                    )
                )
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"
        ):
            features.append(
                _Feature(
                    "scene",
                    str(row["scene_id"]),
                    "performer_identity",
                    f"performer:{row['performer_id']}",
                    1.0,
                    1.0,
                    {"performer_id": str(row["performer_id"])},
                )
            )
        for row in self.connection.execute(
            """
            SELECT scene_id, studio_id FROM source_scene
            WHERE studio_id IS NOT NULL ORDER BY scene_id
            """
        ):
            features.append(
                _Feature(
                    "scene",
                    str(row["scene_id"]),
                    "studio",
                    f"studio:{row['studio_id']}",
                    1.0,
                    1.0,
                    {"studio_id": str(row["studio_id"])},
                )
            )
        for row in self.connection.execute(
            """
            SELECT scene_id, count(*) AS performer_count FROM scene_performer
            GROUP BY scene_id HAVING count(*) > 1 ORDER BY scene_id
            """
        ):
            features.append(
                _Feature(
                    "scene",
                    str(row["scene_id"]),
                    "structure",
                    "multiple_performers",
                    min(1.0, (int(row["performer_count"]) - 1) / 3),
                    1.0,
                    {"performer_count": int(row["performer_count"])},
                )
            )
        return tuple(features)

    def _performer_features(self, scene_features: tuple[_Feature, ...]) -> tuple[_Feature, ...]:
        content_by_scene: dict[str, list[_Feature]] = defaultdict(list)
        for feature in scene_features:
            if feature.entity_type == "scene" and feature.family == "content":
                content_by_scene[feature.entity_id].append(feature)
        scenes_by_performer: dict[str, list[str]] = defaultdict(list)
        for row in self.connection.execute(
            "SELECT performer_id, scene_id FROM scene_performer ORDER BY performer_id, scene_id"
        ):
            scenes_by_performer[str(row["performer_id"])].append(str(row["scene_id"]))
        features: list[_Feature] = []
        for performer_id, scene_ids in scenes_by_performer.items():
            aggregate: dict[str, float] = defaultdict(float)
            for scene_id in scene_ids:
                for feature in content_by_scene[scene_id]:
                    aggregate[feature.name] += feature.value
            norm = math.sqrt(sum(value * value for value in aggregate.values())) or 1.0
            for name in sorted(aggregate):
                features.append(
                    _Feature(
                        "performer",
                        performer_id,
                        "profile:content",
                        name,
                        aggregate[name] / norm,
                        min(1.0, len(scene_ids) / 5),
                        {"scene_count": len(scene_ids)},
                    )
                )

        ages: dict[str, list[float]] = defaultdict(list)
        age_rows = self.connection.execute(
            """
            SELECT sp.performer_id, p.birthdate, s.scene_date
            FROM scene_performer sp JOIN source_performer p ON p.performer_id=sp.performer_id
            JOIN source_scene s ON s.scene_id=sp.scene_id
            WHERE p.birthdate IS NOT NULL AND s.scene_date IS NOT NULL
            ORDER BY sp.performer_id, s.scene_id
            """
        )
        for row in age_rows:
            try:
                born = date.fromisoformat(str(row["birthdate"]))
                recorded = date.fromisoformat(str(row["scene_date"]))
            except ValueError:
                continue
            age = (recorded - born).days / 365.2425
            if 18 <= age <= 100:
                ages[str(row["performer_id"])].append(age)

        fallback_augmented: set[str] = set()
        fallback_rows = self.connection.execute(
            """
            SELECT sp.performer_id, count(DISTINCT sp.scene_id) AS support
            FROM scene_performer sp JOIN scene_tag st ON st.scene_id=sp.scene_id
            JOIN source_tag t ON t.tag_id=st.tag_id
            WHERE lower(t.name) LIKE '%augmentation%' OR lower(t.name) LIKE '%fake tits%'
            GROUP BY sp.performer_id HAVING count(DISTINCT sp.scene_id) >= 2
            """
        )
        fallback_augmented.update(str(row["performer_id"]) for row in fallback_rows)
        performer_rows = self.connection.execute(
            """
            SELECT performer_id, ethnicity, country, eye_color, hair_color, height_cm,
                   weight_kg, measurements, augmentation, tattoos, piercings
            FROM source_performer ORDER BY performer_id
            """
        )
        for row in performer_rows:
            performer_id = str(row["performer_id"])
            measurements = parse_measurements(row["measurements"])
            numeric: dict[str, tuple[float, float]] = {}
            if row["weight_kg"] is not None:
                numeric["weight_kg"] = (float(row["weight_kg"]), 1.0)
            if measurements:
                numeric.update(
                    {
                        "band_inches": (measurements.band_inches, measurements.confidence),
                        "waist_inches": (measurements.waist_inches, measurements.confidence),
                        "hip_inches": (measurements.hip_inches, measurements.confidence),
                        "waist_to_hip": (measurements.waist_to_hip, measurements.confidence),
                    }
                )
                if measurements.cup_index is not None:
                    numeric["cup_index"] = (measurements.cup_index, measurements.confidence)
            for name, (value, confidence) in sorted(numeric.items()):
                features.append(
                    _Feature(
                        "performer",
                        performer_id,
                        "profile:measurements",
                        name,
                        value,
                        confidence,
                        {},
                    )
                )
            if row["height_cm"] is not None:
                features.append(
                    _Feature(
                        "performer",
                        performer_id,
                        "profile:height",
                        "height_cm",
                        float(row["height_cm"]),
                        1.0,
                        {},
                    )
                )
            if ages[performer_id]:
                features.append(
                    _Feature(
                        "performer",
                        performer_id,
                        "profile:age",
                        "age_recording",
                        sum(ages[performer_id]) / len(ages[performer_id]),
                        min(1.0, len(ages[performer_id]) / 3),
                        {"sample_size": len(ages[performer_id])},
                    )
                )
            categories = (
                ("hair", "hair", row["hair_color"], 0.65),
                ("ethnicity", "ethnicity", row["ethnicity"], 0.9),
                ("eyes", "eye", row["eye_color"], 0.9),
            )
            for block, prefix, raw, confidence in categories:
                if raw and str(raw).strip():
                    name = f"{prefix}:{str(raw).strip().casefold()}"
                    features.append(
                        _Feature(
                            "performer",
                            performer_id,
                            f"profile:{block}",
                            name,
                            1.0,
                            confidence,
                            {"display": str(raw).strip()},
                        )
                    )
            for block, raw in (("tattoos", row["tattoos"]), ("piercings", row["piercings"])):
                category = presence_category(raw)
                if category:
                    features.append(
                        _Feature(
                            "performer", performer_id, f"profile:{block}", category, 1.0, 0.8, {}
                        )
                    )
            augmentation = augmentation_category(row["augmentation"])
            confidence = 1.0
            provenance = "performer_metadata"
            if augmentation is None and performer_id in fallback_augmented:
                augmentation = "augmented"
                confidence = 0.55
                provenance = "repeated_scene_tags"
            if augmentation:
                features.append(
                    _Feature(
                        "performer",
                        performer_id,
                        "profile:augmentation",
                        augmentation,
                        1.0,
                        confidence,
                        {"provenance": provenance},
                    )
                )
        return tuple(features)

    def _publish(
        self,
        feature_version: str,
        source_fingerprint: str,
        roles: dict[str, TagRoleResult],
        features: tuple[_Feature, ...],
    ) -> None:
        config_version = f"cfg-{self.config.feature_fingerprint()[:20]}"
        definitions: dict[tuple[str, str, str], tuple[str, dict[str, object]]] = {}
        for feature in features:
            key = (feature.entity_type, feature.family, feature.name)
            definitions.setdefault(key, (self._feature_id(feature_version, *key), feature.metadata))
        with transaction(self.connection):
            self.connection.execute(
                "DELETE FROM feature_definition WHERE feature_version = ?", (feature_version,)
            )
            self.connection.execute(
                "DELETE FROM tag_role WHERE config_version = ?", (config_version,)
            )
            self.connection.executemany(
                """
                INSERT INTO tag_role(tag_id, config_version, role, resolution_reason)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (tag_id, config_version, result.role.value, result.reason)
                    for tag_id, result in sorted(roles.items())
                ),
            )
            self.connection.executemany(
                """
                INSERT INTO feature_definition(
                    feature_id, feature_version, family, name, provenance, metadata_json
                ) VALUES (?, ?, ?, ?, 'feature_builder', ?)
                """,
                (
                    (
                        feature_id,
                        feature_version,
                        family,
                        name,
                        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                    )
                    for (entity_type, family, name), (feature_id, metadata) in sorted(
                        definitions.items()
                    )
                ),
            )
            self.connection.executemany(
                """
                INSERT INTO entity_feature(
                    feature_version, entity_type, entity_id, feature_id, value, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        feature_version,
                        feature.entity_type,
                        feature.entity_id,
                        definitions[(feature.entity_type, feature.family, feature.name)][0],
                        feature.value,
                        feature.confidence,
                    )
                    for feature in sorted(
                        features,
                        key=lambda item: (item.entity_type, item.entity_id, item.family, item.name),
                    )
                ),
            )
            self.connection.execute(
                "UPDATE feature_build SET status='superseded' WHERE status='published'"
            )
            self.connection.execute(
                """
                UPDATE feature_build SET status='published', source_fingerprint=?,
                    published_at_ms=?, error=NULL WHERE feature_version=?
                """,
                (source_fingerprint, self.clock_ms(), feature_version),
            )

    @staticmethod
    def _feature_id(feature_version: str, entity_type: str, family: str, name: str) -> str:
        digest = hashlib.sha256(f"{entity_type}\0{family}\0{name}".encode()).hexdigest()[:24]
        return f"{feature_version}-{digest}"
