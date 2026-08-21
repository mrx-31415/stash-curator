"""Deterministic, versioned feature snapshot construction."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.features.measurements import (
    augmentation_category,
    parse_measurements,
    presence_category,
)
from curator.features.tag_roles import TagRole, TagRoleResolver, TagRoleResult
from curator.profiling import record_duration, span
from curator.storage import transaction
from curator.storage.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    activate_artifact,
    artifact_path,
    create_artifact,
    create_indexes,
    database_path,
    discard_artifact,
    publish_file,
    validate_artifact,
)
from curator.taxonomy import TaxonomyIndex
from curator.taxonomy.store import CATEGORY_ROLE_FINGERPRINT

# Terms excluded from description TF-IDF because they appear in most scenes
# and do not discriminate taste, setting, or scenario.
_DESCRIPTION_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "if",
        "then",
        "else",
        "when",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "just",
        "about",
        "after",
        "also",
        "as",
        "at",
        "before",
        "between",
        "by",
        "during",
        "for",
        "from",
        "into",
        "of",
        "than",
        "to",
        "very",
        "with",
        "well",
        "get",
        "got",
        "go",
        "goes",
        "back",
        "still",
        "too",
        "way",
        "even",
        "now",
        "new",
        "see",
        "take",
        "make",
        "like",
        "come",
        "know",
        "want",
        "think",
        "really",
        "much",
        "one",
        "two",
        "who",
        "how",
        "which",
        "what",
        "where",
        "why",
        "herself",
        "himself",
        "itself",
        "themselves",
        "any",
        "anything",
        "everyone",
        "everything",
        "let",
        "scene",
        "watch",
        "enjoy",
        "don",
        "doesn",
        "isn",
        "wasn",
        "weren",
        "aren",
        "couldn",
        "wouldn",
        "shouldn",
        "haven",
        "hasn",
        "hadn",
        "https",
        "http",
        "www",
        "com",
        "org",
        "net",
    }
)
_DESCRIPTION_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")
_DESCRIPTION_MIN_DF = 5
_DESCRIPTION_MAX_DF_FRACTION = 0.70
_DESCRIPTION_MAX_TERMS_PER_SCENE = 15
# Description terms are sparse (5-15 per scene vs 10-30 tags) so they get a
# multiplier before l2 normalization in the combined content vector. Without
# this they would be drowned out by denser tag features.
_DESCRIPTION_BOOST = 3.0


class FeatureBuildError(RuntimeError):
    pass


def _fingerprint_table(
    connection: sqlite3.Connection,
    digest: Any,
    label: str,
    statement: str,
) -> None:
    """Hash one ordered source table into the fingerprint digest.

    Rows are json-encoded in batches of a thousand and hashed with a single digest
    update per batch; batching keeps the encoding collision-free (JSON escaping) while
    cutting per-row json.dumps and hashlib call overhead by roughly an order of
    magnitude on the multi-hundred-thousand-row tables.
    """
    digest.update(f"{label}\0".encode())
    batch: list[tuple[object, ...]] = []
    for row in connection.execute(statement):
        batch.append(tuple(row))
        if len(batch) == 1_000:
            digest.update(json.dumps(batch, separators=(",", ":"), ensure_ascii=False).encode())
            batch = []
    if batch:
        digest.update(json.dumps(batch, separators=(",", ":"), ensure_ascii=False).encode())
    digest.update(b"\n")


@dataclass(frozen=True)
class FeatureBuildResult:
    feature_version: str
    scene_count: int
    performer_count: int
    feature_count: int
    reused: bool
    stage_timings_ms: dict[str, int]


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
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.connection = connection
        self.config = config
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.progress = progress

    def build(self) -> FeatureBuildResult:
        started = time.perf_counter()
        source_fingerprint = self._source_fingerprint()
        self._report(0.05)
        version_hash = hashlib.sha256(
            f"{source_fingerprint}\0{self.config.feature_json()}".encode()
        ).hexdigest()
        feature_version = f"fv-{version_hash[:20]}"
        existing = self.connection.execute(
            """
            SELECT status, artifact_basename, validation_status FROM feature_build
            WHERE feature_version = ?
            """,
            (feature_version,),
        ).fetchone()
        lookup_ms = round((time.perf_counter() - started) * 1000)
        if (
            existing
            and existing["status"] == "published"
            and existing["validation_status"] == "valid"
            and existing["artifact_basename"]
            and artifact_path(
                database_path(self.connection), str(existing["artifact_basename"])
            ).is_file()
        ):
            with transaction(self.connection):
                self.connection.execute(
                    """
                    UPDATE feature_build SET reuse_count=reuse_count+1
                    WHERE feature_version=?
                    """,
                    (feature_version,),
                )
            result = self._result(
                feature_version,
                reused=True,
                timings={
                    "lookup": lookup_ms,
                    "total": round((time.perf_counter() - started) * 1000),
                },
            )
            self._report(1.0)
            return result
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
            build_started = time.perf_counter()
            with span("python", "feature.roles"):
                roles = self._resolve_tag_roles()
            self._report(0.10)
            with span("python", "feature.scene_features"):
                scene_features = self._scene_features(roles)
            self._report(0.45)
            with span("python", "feature.performer_features"):
                performer_features = self._performer_features(scene_features)
            self._report(0.60)
            if self._source_fingerprint() != source_fingerprint:
                raise FeatureBuildError("source cache changed during feature construction")
            all_features = (*scene_features, *performer_features)
            timings = {
                "lookup": lookup_ms,
                "build": round((time.perf_counter() - build_started) * 1000),
                **self._publish(feature_version, source_fingerprint, roles, all_features),
            }
            timings["total"] = round((time.perf_counter() - started) * 1000)
            result = self._result(feature_version, reused=False, timings=timings)
            self._report(1.0)
            return result
        except Exception as error:
            with transaction(self.connection):
                self.connection.execute(
                    "UPDATE feature_build SET status='failed', error=? WHERE feature_version=?",
                    (str(error)[:2000], feature_version),
                )
            raise

    def _report(self, fraction: float) -> None:
        if self.progress:
            self.progress(round(fraction * 1_000), 1_000)

    def _result(
        self, feature_version: str, *, reused: bool, timings: dict[str, int]
    ) -> FeatureBuildResult:
        row = self.connection.execute(
            """
            SELECT scene_count, performer_count, feature_count FROM feature_build
            WHERE feature_version = ?
            """,
            (feature_version,),
        ).fetchone()
        if row is None or any(
            row[key] is None for key in ("scene_count", "performer_count", "feature_count")
        ):
            raise FeatureBuildError(f"feature build counts missing for {feature_version}")
        return FeatureBuildResult(
            feature_version,
            int(row["scene_count"]),
            int(row["performer_count"]),
            int(row["feature_count"]),
            reused,
            timings,
        )

    def _source_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for label, statement in (
            ("source_tag", "SELECT tag_id, name FROM source_tag ORDER BY tag_id"),
            (
                "source_performer",
                """
                SELECT performer_id, birthdate, ethnicity, eye_color, hair_color,
                       height_cm, weight_kg, measurements, augmentation, tattoos, piercings
                FROM source_performer ORDER BY performer_id
                """,
            ),
            (
                "source_scene",
                "SELECT scene_id, scene_date, studio_id FROM source_scene ORDER BY scene_id",
            ),
            (
                "scene_performer",
                "SELECT scene_id, performer_id FROM scene_performer "
                "ORDER BY scene_id, performer_id",
            ),
            (
                "scene_tag",
                "SELECT scene_id, tag_id, provenance FROM scene_tag "
                "ORDER BY scene_id, tag_id, provenance",
            ),
            (
                "scene_marker",
                "SELECT marker_id, scene_id, primary_tag_id FROM scene_marker ORDER BY marker_id",
            ),
            (
                "marker_tag",
                "SELECT marker_id, tag_id FROM marker_tag ORDER BY marker_id, tag_id",
            ),
            (
                "tag_parent",
                "SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id",
            ),
            (
                "source_tag_stash_id",
                "SELECT tag_id, endpoint, stash_id FROM source_tag_stash_id "
                "ORDER BY tag_id, endpoint",
            ),
        ):
            _fingerprint_table(self.connection, digest, label, statement)
        row = self.connection.execute(
            "SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'"
        ).fetchone()
        digest.update(f"taxonomy_snapshot\0{row[0] if row else ''}\n".encode())
        digest.update(f"taxonomy_category_roles\0{CATEGORY_ROLE_FINGERPRINT}\n".encode())
        return digest.hexdigest()

    def _resolve_tag_roles(self) -> dict[str, TagRoleResult]:
        resolver = TagRoleResolver(self.config.feature)
        taxonomy = TaxonomyIndex(self.connection)
        return {
            str(row["tag_id"]): resolver.resolve(
                str(row["tag_id"]),
                row["name"],
                taxonomy.resolve(str(row["tag_id"]), row["name"]),
            )
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
        tag_names = {
            str(row["tag_id"]): str(row["name"] or "")
            for row in self.connection.execute("SELECT tag_id, name FROM source_tag")
        }
        # Exact-name ignore set: tags the user excluded from tag analysis. The
        # name is the only match key (no bracket heuristics); a tag matching an
        # ignored name is dropped before it can enter base_vectors, so it never
        # contributes to document frequency, the l2 norm, entity_feature rows,
        # affinity accumulation, or the Taste Profile.
        ignored_names = frozenset(self.config.feature.ignored_tags)
        ignored_tag_ids = {tag_id for tag_id, name in tag_names.items() if name in ignored_names}
        direct: dict[str, set[str]] = defaultdict(set)
        for row in self.connection.execute(
            """
            SELECT scene_id, tag_id FROM scene_tag
            WHERE provenance='scene' ORDER BY scene_id, tag_id
            """
        ):
            tag_id = str(row["tag_id"])
            if (
                roles.get(tag_id, TagRoleResult(TagRole.IGNORED, "missing")).role is TagRole.CONTENT
                and tag_id not in ignored_tag_ids
            ):
                direct[str(row["scene_id"])].add(tag_id)
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
            if (
                roles.get(tag_id, TagRoleResult(TagRole.IGNORED, "missing")).role is TagRole.CONTENT
                and tag_id not in ignored_tag_ids
            ):
                marker[str(row["scene_id"])].add(tag_id)
        parents: dict[str, set[str]] = defaultdict(set)
        for row in self.connection.execute(
            "SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id"
        ):
            parent = str(row["parent_tag_id"])
            if (
                roles.get(parent, TagRoleResult(TagRole.IGNORED, "missing")).role is TagRole.CONTENT
                and parent not in ignored_tag_ids
            ):
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
        features: list[_Feature] = []
        total = max(1, len(scene_ids))
        # Description term features: tokenize scene descriptions, compute TF-IDF
        # weights, and emit discriminating terms as content features alongside tags.
        desc_document_frequency: dict[str, int] = Counter()
        desc_by_scene: dict[str, list[str]] = {}
        for row in self.connection.execute(
            "SELECT scene_id, details FROM source_scene WHERE details IS NOT NULL AND details != ''"
        ):
            terms: list[str] = []
            seen: set[str] = set()
            for token in _DESCRIPTION_TOKEN_RE.findall(row["details"] or ""):
                token = token.lower()
                if token not in _DESCRIPTION_STOPWORDS and token not in seen:
                    seen.add(token)
                    terms.append(token)
                    desc_document_frequency[token] += 1
            if terms:
                desc_by_scene[str(row["scene_id"])] = terms
        desc_idf: dict[str, float] = {}
        for term, freq in desc_document_frequency.items():
            if freq < _DESCRIPTION_MIN_DF or freq > total * _DESCRIPTION_MAX_DF_FRACTION:
                continue
            desc_idf[term] = min(
                self.config.feature.idf_cap,
                1 + self.config.feature.idf_strength * math.log((total + 1) / (freq + 1)),
            )
        for position, scene_id in enumerate(scene_ids, 1):
            weighted: dict[str, float] = {}
            for tag_id, base in base_vectors[scene_id].items():
                frequency = document_frequency[tag_id]
                rarity = min(
                    self.config.feature.idf_cap,
                    1 + self.config.feature.idf_strength * math.log((total + 1) / (frequency + 1)),
                )
                shrinkage = frequency / (frequency + self.config.feature.one_off_prior)
                weighted[tag_id] = base * rarity * shrinkage
            # Description terms compete with tags in the same content family so
            # the l2 norm reflects the combined feature weight.
            if scene_id in desc_by_scene:
                for term in desc_by_scene[scene_id][:_DESCRIPTION_MAX_TERMS_PER_SCENE]:
                    idf = desc_idf.get(term, 0.0)
                    if idf <= 0:
                        continue
                    freq = desc_document_frequency.get(term, 1)
                    weighted[f"desc:{term}"] = (
                        _DESCRIPTION_BOOST * idf / (freq + self.config.feature.one_off_prior)
                    )
            norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
            for tag_id in sorted(t for t in weighted if not t.startswith("desc:")):
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
            for term in sorted(k for k in weighted if k.startswith("desc:")):
                frequency = desc_document_frequency.get(term.removeprefix("desc:"), 1)
                features.append(
                    _Feature(
                        "scene",
                        scene_id,
                        "content",
                        term,
                        weighted[term] / norm,
                        min(1.0, frequency / 3),
                        {"document_frequency": frequency},
                    )
                )
            if position == len(scene_ids) or position % 250 == 0:
                self._report(0.10 + 0.30 * position / max(1, len(scene_ids)))
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
        ).fetchall()
        for position, row in enumerate(performer_rows, 1):
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
            if position == len(performer_rows) or position % 250 == 0:
                self._report(0.45 + 0.15 * position / max(1, len(performer_rows)))
        return tuple(features)

    def _publish(
        self,
        feature_version: str,
        source_fingerprint: str,
        roles: dict[str, TagRoleResult],
        features: tuple[_Feature, ...],
    ) -> dict[str, int]:
        config_version = f"cfg-{self.config.feature_fingerprint()[:20]}"
        definitions: dict[tuple[str, str, str], tuple[str, dict[str, object]]] = {}
        for feature in features:
            key = (feature.entity_type, feature.family, feature.name)
            # Membership check instead of setdefault: the default argument of
            # setdefault is evaluated eagerly for every feature, wasting a sha256
            # per duplicate instead of once per definition.
            if key not in definitions:
                definitions[key] = (
                    self._feature_id(feature_version, *key),
                    feature.metadata,
                )
        scene_count = len(
            {feature.entity_id for feature in features if feature.entity_type == "scene"}
        )
        performer_count = len(
            {feature.entity_id for feature in features if feature.entity_type == "performer"}
        )
        timings: dict[str, int] = {}
        writing_started = time.perf_counter()
        artifact = None
        temporary = None
        final = None
        published = False
        artifact, temporary, final = create_artifact(self.connection, "feature", feature_version)
        try:
            with transaction(self.connection):
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
                taxonomy_rows = [
                    (tag_id, result.taxonomy)
                    for tag_id, result in sorted(roles.items())
                    if result.taxonomy is not None
                ]
                self.connection.executemany(
                    """
                    INSERT INTO tag_taxonomy_match(
                        local_tag_id, snapshot_id, external_tag_id, external_category_id,
                        match_method, confidence, ambiguity_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(local_tag_id, snapshot_id) DO UPDATE SET
                        external_tag_id=excluded.external_tag_id,
                        external_category_id=excluded.external_category_id,
                        match_method=excluded.match_method,
                        confidence=excluded.confidence,
                        ambiguity_count=excluded.ambiguity_count
                    """,
                    (
                        (
                            tag_id,
                            taxonomy.snapshot_id,
                            taxonomy.external_tag_id,
                            taxonomy.external_category_id,
                            taxonomy.method,
                            taxonomy.confidence,
                            taxonomy.ambiguity_count,
                        )
                        for tag_id, taxonomy in taxonomy_rows
                    ),
                )
            with transaction(artifact):
                artifact.executemany(
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
                artifact.executemany(
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
                            key=lambda item: (
                                item.entity_type,
                                item.entity_id,
                                item.family,
                                item.name,
                            ),
                        )
                    ),
                )
                artifact.executemany(
                    """
                    INSERT INTO scene_content_search(
                        feature_version, feature_id, scene_id, value
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        (
                            feature_version,
                            definitions[(feature.entity_type, feature.family, feature.name)][0],
                            feature.entity_id,
                            feature.value,
                        )
                        for feature in features
                        if feature.entity_type == "scene" and feature.family == "content"
                    ),
                )
            timings["database_writing"] = round((time.perf_counter() - writing_started) * 1000)
            record_duration("python", "feature.publish_write", timings["database_writing"])
            self._report(0.75)
            indexing_started = time.perf_counter()
            create_indexes(artifact, "feature")
            timings["indexing"] = round((time.perf_counter() - indexing_started) * 1000)
            record_duration("python", "feature.publish_index", timings["indexing"])
            self._report(0.85)
            validation_started = time.perf_counter()
            stored = artifact.execute(
                """
                SELECT
                    (SELECT count(DISTINCT entity_id) FROM entity_feature
                     WHERE feature_version=? AND entity_type='scene'),
                    (SELECT count(DISTINCT entity_id) FROM entity_feature
                     WHERE feature_version=? AND entity_type='performer'),
                    (SELECT count(*) FROM feature_definition WHERE feature_version=?)
                """,
                (feature_version, feature_version, feature_version),
            ).fetchone()
            expected = (scene_count, performer_count, len(definitions))
            if tuple(stored) != expected:
                raise FeatureBuildError(
                    f"feature validation failed: expected {expected}, stored {tuple(stored)}"
                )
            summary = validate_artifact(
                artifact,
                "feature",
                {
                    "scenes": scene_count,
                    "performers": performer_count,
                    "features": len(definitions),
                },
            )
            timings["validation"] = round((time.perf_counter() - validation_started) * 1000)
            self._report(0.93)
            publication_started = time.perf_counter()
            size = publish_file(artifact, temporary, final)
            artifact = None
            with transaction(self.connection):
                self.connection.execute(
                    "UPDATE feature_build SET status='superseded' WHERE status='published'"
                )
                self.connection.execute(
                    """
                    UPDATE feature_build SET status='published', source_fingerprint=?,
                        published_at_ms=?, error=NULL, scene_count=?, performer_count=?,
                        feature_count=?, artifact_basename=?, artifact_schema_version=?,
                        artifact_bytes=?, validation_status='valid',
                        validation_summary_json=?, cleanup_error=NULL
                    WHERE feature_version=?
                    """,
                    (
                        source_fingerprint,
                        self.clock_ms(),
                        scene_count,
                        performer_count,
                        len(definitions),
                        final.name,
                        ARTIFACT_SCHEMA_VERSION,
                        size,
                        json.dumps(summary, sort_keys=True, separators=(",", ":")),
                        feature_version,
                    ),
                )
            published = True
            activate_artifact(self.connection, "feature", final)
            timings["publication"] = round((time.perf_counter() - publication_started) * 1000)
            self._report(0.98)
            return timings
        finally:
            if not published:
                discard_artifact(artifact, temporary)
                if final is not None and temporary is not None and not temporary.exists():
                    final.unlink(missing_ok=True)

    @staticmethod
    def _feature_id(feature_version: str, entity_type: str, family: str, name: str) -> str:
        digest = hashlib.sha256(f"{entity_type}\0{family}\0{name}".encode()).hexdigest()[:24]
        return f"{feature_version}-{digest}"
