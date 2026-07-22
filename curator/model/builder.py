"""Build a deterministic, bounded preference model from features and outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from itertools import batched

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.events.contracts import DEFAULT_CALIBRATION
from curator.features import FeatureBuilder, FeatureStore
from curator.features.profiles import performer_similarity
from curator.features.store import StoredFeature
from curator.model.boundaries import scene_eligibility
from curator.model.curves import blend_appeal, direct_confidence, scene_recovery
from curator.profiling import record_duration, span
from curator.storage import ModelStore, transaction
from curator.storage.retention import prune_snapshots


@dataclass(frozen=True)
class ModelBuildResult:
    model_id: str
    feature_version: str
    scene_count: int
    labeled_scene_count: int
    reused: bool
    stage_timings_ms: dict[str, int]


@dataclass(frozen=True)
class _SceneLabel:
    outcome: float
    confidence: float
    effective_evidence: float
    signal_types: tuple[str, ...]


@dataclass(frozen=True)
class _Affinity:
    feature_id: str
    affinity: float
    confidence: float
    support: float
    scene_count: int
    contexts: dict[str, int]


@dataclass(frozen=True)
class _Prior:
    value: float
    confidence: float


@dataclass(frozen=True)
class _NeighborEvidence:
    value: float
    outcome_mean: float
    lift: float
    confidence: float
    total_weight: float
    neighbors: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _Score:
    scene_id: str
    general_appeal: float
    direct_appeal: float
    direct_confidence: float
    appeal: float
    current_fit: float
    confidence: float
    metadata_confidence: float
    recovery: float
    components: dict[str, object]
    neighbors: tuple[dict[str, object], ...]
    eligibility: dict[str, object]


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


class PreferenceModelBuilder:
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

    def build(self) -> ModelBuildResult:
        started = time.perf_counter()
        stage_started = started
        timings: dict[str, int] = {}
        # FeatureBuilder is deterministic and reuses an existing version when neither
        # source data nor feature configuration changed. Always ask it for the current
        # version so a feature-only configuration change cannot silently train against
        # stale vectors.
        feature_version = (
            FeatureBuilder(self.connection, self.config, clock_ms=self.clock_ms)
            .build()
            .feature_version
        )
        self._report(0.05)
        timings["features"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "model.features", timings["features"])
        stage_started = time.perf_counter()
        reference_at_ms = (self.clock_ms() // 86_400_000) * 86_400_000
        labels = self._scene_labels()
        training_labels = self._training_labels(labels)
        self._report(0.10)
        timings["labels"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "model.labels", timings["labels"])
        evidence_fingerprint = self._evidence_fingerprint(labels)
        model_digest = hashlib.sha256(
            (
                f"{feature_version}\0{evidence_fingerprint}\0"
                f"{self.config.canonical_json()}\0{reference_at_ms}"
            ).encode()
        ).hexdigest()
        model_id = f"model-{model_digest[:20]}"
        existing = self.connection.execute(
            "SELECT status FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        if existing and existing["status"] == "published":
            self._report(1.0)
            timings["total"] = round((time.perf_counter() - started) * 1000)
            return self._result(
                model_id, feature_version, len(labels), reused=True, timings=timings
            )

        model_config_json = json.dumps(
            {"config": asdict(self.config), "reference_at_ms": reference_at_ms},
            sort_keys=True,
            separators=(",", ":"),
        )
        model_store = ModelStore(self.connection)
        if existing is None:
            model_store.start_build(
                model_id=model_id,
                feature_version=feature_version,
                config=json.loads(model_config_json),
                sync_watermark=self._sync_watermark(),
                created_at_ms=self.clock_ms(),
            )
        else:
            with transaction(self.connection):
                self.connection.execute(
                    "UPDATE model_version SET status='building' WHERE model_id=?", (model_id,)
                )
        try:
            stage_started = time.perf_counter()
            scene_features = FeatureStore(self.connection).entity_features(feature_version, "scene")
            label_mean = self._label_mean(training_labels)
            affinities = self._affinities(scene_features, training_labels, label_mean)
            self._report(0.20)
            timings["affinities"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "model.affinities", timings["affinities"])
            stage_started = time.perf_counter()
            scores = self._scores(
                feature_version,
                scene_features,
                affinities,
                labels,
                training_labels,
                label_mean,
                reference_at_ms,
            )
            timings["scores"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "model.scores", timings["scores"])
            stage_started = time.perf_counter()
            self._publish(model_id, feature_version, affinities, labels, scores)
            self._report(0.97)
            timings["publish"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "model.publish", timings["publish"])
        except Exception:
            model_store.fail(model_id)
            raise
        prune_snapshots(self.connection)
        self._report(1.0)
        timings["total"] = round((time.perf_counter() - started) * 1000)
        return self._result(model_id, feature_version, len(labels), reused=False, timings=timings)

    def _report(self, fraction: float) -> None:
        if self.progress:
            self.progress(round(fraction * 1_000), 1_000)

    def _result(
        self,
        model_id: str,
        feature_version: str,
        labeled: int,
        *,
        reused: bool,
        timings: dict[str, int],
    ) -> ModelBuildResult:
        count = int(
            self.connection.execute(
                "SELECT count(*) FROM model_scene_score WHERE model_id=?", (model_id,)
            ).fetchone()[0]
        )
        return ModelBuildResult(model_id, feature_version, count, labeled, reused, timings)

    def _scene_labels(self) -> dict[str, _SceneLabel]:
        signals: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
        for row in self.connection.execute(
            """
            SELECT scene_id, event_type, outcome, confidence, payload_json FROM behavior_event
            WHERE scene_id IS NOT NULL AND outcome IS NOT NULL ORDER BY scene_id, occurred_at_ms
            """
        ):
            payload = json.loads(row["payload_json"])
            signals[str(row["scene_id"])].append(
                (
                    float(row["outcome"]),
                    float(row["confidence"]),
                    str(payload.get("primary_signal", row["event_type"])),
                )
            )
        for row in self.connection.execute(
            """
            SELECT scene_id, feedback_type, occurred_at_ms FROM feedback
            WHERE reversed_by_id IS NULL AND feedback_type IN ('thumb_up', 'thumb_down')
            ORDER BY scene_id, occurred_at_ms
            """
        ):
            signals[str(row["scene_id"])].append(
                (
                    DEFAULT_CALIBRATION.thumb_up_value
                    if row["feedback_type"] == "thumb_up"
                    else DEFAULT_CALIBRATION.thumb_down_value,
                    DEFAULT_CALIBRATION.explicit_feedback_confidence,
                    str(row["feedback_type"]),
                )
            )
        for row in self.connection.execute(
            "SELECT scene_id, rating100 FROM source_scene WHERE rating100 IS NOT NULL"
        ):
            value = _clamp((float(row["rating100"]) - 50) / 50)
            signals[str(row["scene_id"])].append(
                (value, self.config.model.scene_rating_confidence, "scene_rating")
            )
        labels: dict[str, _SceneLabel] = {}
        for scene_id, scene_signals in signals.items():
            evidence = sum(confidence for _, confidence, _ in scene_signals)
            if evidence <= 0:
                continue
            outcome = sum(value * confidence for value, confidence, _ in scene_signals) / evidence
            labels[scene_id] = _SceneLabel(
                _clamp(outcome),
                1 - math.exp(-evidence),
                evidence,
                tuple(signal for _, _, signal in scene_signals),
            )
        return labels

    def _training_labels(self, labels: dict[str, _SceneLabel]) -> dict[str, _SceneLabel]:
        metadata_wrong = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT DISTINCT scene_id FROM feedback
                WHERE feedback_type='metadata_wrong' AND reversed_by_id IS NULL
                """
            )
        }
        return {
            scene_id: label for scene_id, label in labels.items() if scene_id not in metadata_wrong
        }

    def _evidence_fingerprint(self, labels: dict[str, _SceneLabel]) -> str:
        payload = [
            (
                scene_id,
                label.outcome,
                label.confidence,
                label.effective_evidence,
                label.signal_types,
            )
            for scene_id, label in sorted(labels.items())
        ]
        feedback_state = [
            tuple(row)
            for row in self.connection.execute(
                """
                SELECT feedback_id, scene_id, feedback_type, value, occurred_at_ms, reversed_by_id
                FROM feedback ORDER BY feedback_id
                """
            )
        ]
        exclusions = [
            tuple(row)
            for row in self.connection.execute("SELECT * FROM exclusion ORDER BY exclusion_id")
        ]
        pruning = [
            tuple(row)
            for row in self.connection.execute("SELECT * FROM pruning_candidate ORDER BY scene_id")
        ]
        return hashlib.sha256(
            json.dumps(
                {
                    "labels": payload,
                    "feedback": feedback_state,
                    "exclusions": exclusions,
                    "pruning": pruning,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _sync_watermark(self) -> str | None:
        row = self.connection.execute(
            "SELECT max(watermark) FROM sync_cursor WHERE state='complete'"
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    def _affinities(
        self,
        scene_features: dict[str, tuple[StoredFeature, ...]],
        labels: dict[str, _SceneLabel],
        label_mean: float,
    ) -> dict[str, _Affinity]:
        accumulators: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for scene_id, label in labels.items():
            for feature in scene_features.get(scene_id, ()):
                weight = label.confidence * feature.confidence * abs(feature.value)
                accumulators[feature.feature_id].append(
                    (
                        scene_id,
                        weight,
                        (label.outcome - label_mean) * math.copysign(1, feature.value),
                    )
                )
        scene_context = self._scene_contexts()
        result: dict[str, _Affinity] = {}
        for feature_id, values in accumulators.items():
            support = sum(weight for _, weight, _ in values)
            numerator = sum(weight * outcome for _, weight, outcome in values)
            affinity = numerator / (self.config.model.affinity_prior + support)
            studios = {
                scene_context[scene_id][0]
                for scene_id, _, _ in values
                if scene_context.get(scene_id, (None, ()))[0]
            }
            performers = {
                performer
                for scene_id, _, _ in values
                for performer in scene_context.get(scene_id, (None, ()))[1]
            }
            result[feature_id] = _Affinity(
                feature_id,
                _clamp(affinity),
                1 - math.exp(-support / self.config.model.affinity_confidence_scale),
                support,
                len({scene_id for scene_id, _, _ in values}),
                {"studios": len(studios), "performers": len(performers)},
            )
        return result

    @staticmethod
    def _label_mean(labels: dict[str, _SceneLabel]) -> float:
        support = sum(label.confidence for label in labels.values())
        if support <= 0:
            return 0.0
        return sum(label.outcome * label.confidence for label in labels.values()) / support

    def _scene_contexts(self) -> dict[str, tuple[str | None, tuple[str, ...]]]:
        contexts: dict[str, tuple[str | None, list[str]]] = {}
        for row in self.connection.execute(
            "SELECT scene_id, studio_id FROM source_scene ORDER BY scene_id"
        ):
            contexts[str(row["scene_id"])] = (
                str(row["studio_id"]) if row["studio_id"] else None,
                [],
            )
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"
        ):
            context = contexts[str(row["scene_id"])]
            context[1].append(str(row["performer_id"]))
        return {key: (value[0], tuple(value[1])) for key, value in contexts.items()}

    def _scores(
        self,
        feature_version: str,
        scene_features: dict[str, tuple[StoredFeature, ...]],
        affinities: dict[str, _Affinity],
        labels: dict[str, _SceneLabel],
        training_labels: dict[str, _SceneLabel],
        label_mean: float,
        reference_at_ms: int,
    ) -> tuple[_Score, ...]:
        with span("python", "model.score_vectors"):
            vectors = FeatureStore(self.connection).scene_content_vectors(feature_version)
        all_scene_ids = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT scene_id FROM source_scene ORDER BY scene_id"
            )
        ]
        with span("python", "model.score_neighbors"):
            preference_vectors, discriminative_tag_count = self._preference_content_vectors(
                vectors, scene_features, affinities
            )
            progress_total = len(preference_vectors) + len(all_scene_ids)
            neighbors = self._content_neighbors(
                preference_vectors, training_labels, label_mean, progress_total
            )
        with span("python", "model.score_performer_similarity"):
            performer_similarity_scores = self._performer_similarity_scores(
                feature_version, scene_features, affinities
            )
        baseline_support = sum(label.confidence for label in training_labels.values())
        baseline = (
            label_mean * baseline_support / (self.config.model.affinity_prior + baseline_support)
        )
        baseline = _clamp(
            baseline, -self.config.model.baseline_bound, self.config.model.baseline_bound
        )
        last_played = {
            str(row["scene_id"]): int(row["last_played"])
            for row in self.connection.execute(
                """
                SELECT scene_id, max(played_at_ms) AS last_played
                FROM source_play GROUP BY scene_id
                """
            )
        }
        recent_context = self._recent_context(reference_at_ms, vectors)
        eligibility = self._eligibility(reference_at_ms)
        performer_priors = self._performer_priors()
        studio_priors = self._studio_priors()
        scores: list[_Score] = []
        profiles = FeatureStore(self.connection).performer_profiles(feature_version)
        total_scenes = len(all_scene_ids)
        for scene_index, scene_id in enumerate(all_scene_ids, 1):
            features = scene_features.get(scene_id, ())
            components: dict[str, object] = {
                "baseline": {
                    "raw": baseline,
                    "value": baseline,
                    "training_outcome_mean": label_mean,
                    "effective_support": baseline_support,
                }
            }
            family_confidences: dict[str, float] = {}
            for family, bound in (
                ("content", self.config.model.content_bound),
                ("structure", self.config.model.structure_bound),
            ):
                contributions = []
                for feature in features:
                    if feature.family != family:
                        continue
                    affinity = affinities.get(feature.feature_id)
                    if affinity is None:
                        continue
                    value = feature.value * affinity.affinity * affinity.confidence
                    contributions.append(
                        {
                            "feature_id": feature.feature_id,
                            "name": feature.name,
                            "value": value,
                            "affinity": affinity.affinity,
                            "confidence": affinity.confidence,
                            "metadata": feature.metadata,
                        }
                    )
                raw = sum(_number(item["value"]) for item in contributions)
                contribution_mass = sum(abs(_number(item["value"])) for item in contributions)
                evidence_confidence = (
                    sum(
                        abs(_number(item["value"])) * _number(item["confidence"])
                        for item in contributions
                    )
                    / contribution_mass
                    if contribution_mass
                    else 0.0
                )
                family_confidences[family] = evidence_confidence
                components[family] = {
                    "raw": raw,
                    "value": _clamp(raw, -bound, bound),
                    "evidence_confidence": evidence_confidence,
                    "top": sorted(
                        contributions,
                        key=lambda item: (-abs(_number(item["value"])), str(item["name"])),
                    )[:5],
                }
            performer_items = [
                feature for feature in features if feature.family == "performer_identity"
            ]
            identity_values = []
            similarity_values = []
            for feature in performer_items:
                performer_id = feature.name.removeprefix("performer:")
                affinity = affinities.get(feature.feature_id)
                learned = affinity.affinity * affinity.confidence if affinity else 0.0
                prior = performer_priors.get(performer_id, _Prior(0.0, 0.0))
                identity_values.append(
                    {
                        "performer_id": performer_id,
                        "value": learned + prior.value,
                        "learned": learned,
                        "prior": prior.value,
                        "confidence": max(
                            affinity.confidence if affinity else 0.0,
                            prior.confidence,
                        ),
                    }
                )
                similarity = performer_similarity_scores.get(
                    performer_id, {"value": 0.0, "confidence": 0.0, "matches": []}
                )
                identity_confidence = max(
                    affinity.confidence if affinity else 0.0,
                    prior.confidence,
                )
                novelty_weight = max(
                    self.config.model.performer_similarity_novelty_floor,
                    1 - identity_confidence,
                )
                similarity_values.append(
                    {
                        "performer_id": performer_id,
                        **similarity,
                        "raw_value": _number(similarity.get("value")),
                        "value": _number(similarity.get("value")) * novelty_weight,
                        "confidence": _number(similarity.get("confidence")) * novelty_weight,
                        "identity_confidence": identity_confidence,
                        "novelty_weight": novelty_weight,
                    }
                )
            identity_raw = self._asymmetric([_number(item["value"]) for item in identity_values])
            similarity_raw = self._asymmetric(
                [_number(item["value"]) for item in similarity_values]
            )
            identity_confidence = max(
                (_number(item.get("confidence")) for item in identity_values), default=0.0
            )
            similarity_confidence = max(
                (_number(item.get("confidence")) for item in similarity_values), default=0.0
            )
            family_confidences["performer_identity"] = identity_confidence
            family_confidences["performer_similarity"] = similarity_confidence
            components["performer_identity"] = {
                "raw": identity_raw,
                "value": _clamp(
                    identity_raw,
                    -self.config.model.performer_identity_bound,
                    self.config.model.performer_identity_bound,
                ),
                "performers": identity_values,
                "evidence_confidence": identity_confidence,
            }
            components["performer_similarity"] = {
                "raw": similarity_raw,
                "value": _clamp(
                    similarity_raw,
                    -self.config.model.performer_similarity_bound,
                    self.config.model.performer_similarity_bound,
                ),
                "performers": similarity_values,
                "evidence_confidence": similarity_confidence,
            }
            studio_features = [feature for feature in features if feature.family == "studio"]
            studio_items = []
            for feature in studio_features:
                studio_id = feature.name.removeprefix("studio:")
                affinity = affinities.get(feature.feature_id)
                learned = affinity.affinity * affinity.confidence if affinity else 0.0
                prior = studio_priors.get(studio_id, _Prior(0.0, 0.0))
                studio_items.append(
                    {
                        "studio_id": studio_id,
                        "value": learned + prior.value,
                        "learned": learned,
                        "prior": prior.value,
                        "confidence": max(
                            affinity.confidence if affinity else 0.0,
                            prior.confidence,
                        ),
                    }
                )
            studio_raw = sum(_number(item["value"]) for item in studio_items)
            studio_confidence = max(
                (_number(item.get("confidence")) for item in studio_items), default=0.0
            )
            family_confidences["studio"] = studio_confidence
            components["studio"] = {
                "raw": studio_raw,
                "value": _clamp(
                    studio_raw, -self.config.model.studio_bound, self.config.model.studio_bound
                ),
                "studios": studio_items,
                "evidence_confidence": studio_confidence,
            }
            neighbor_data = neighbors.get(
                scene_id,
                _NeighborEvidence(0.0, label_mean, 0.0, 0.0, 0.0, ()),
            )
            family_confidences["content_neighbor"] = neighbor_data.confidence
            components["content_neighbor"] = {
                "raw": neighbor_data.value,
                "value": _clamp(
                    neighbor_data.value,
                    -self.config.model.neighbor_bound,
                    self.config.model.neighbor_bound,
                ),
                "outcome_mean": neighbor_data.outcome_mean,
                "training_outcome_mean": label_mean,
                "lift": neighbor_data.lift,
                "evidence_confidence": neighbor_data.confidence,
                "total_weight": neighbor_data.total_weight,
                "vector_mode": "preference_discriminative",
                "discriminative_tag_count": discriminative_tag_count,
            }
            component_total = sum(
                float(value["value"])
                for value in components.values()
                if isinstance(value, dict) and "value" in value
            )
            general = _clamp(component_total)
            direct = labels.get(scene_id, _SceneLabel(0.0, 0.0, 0.0, ()))
            exact_confidence = direct_confidence(
                direct.effective_evidence, config=self.config.model
            )
            appeal = blend_appeal(general, direct.outcome, exact_confidence)
            last = last_played.get(scene_id)
            recovery = self._recovery(last, reference_at_ms)
            cooldown = max(0.0, appeal) * (1 - recovery)
            satiation = self._satiation(scene_id, appeal, recent_context)
            not_now = self._not_now_penalty(scene_id, reference_at_ms, recent_context)
            current_fit = _clamp(appeal - cooldown - satiation - not_now)
            content_count = len(vectors.get(scene_id, {}))
            performer_profile_count = sum(
                str(item.get("performer_id")) in profiles for item in identity_values
            )
            metadata_confidence = 1 - math.exp(
                -(content_count + performer_profile_count + len(studio_items)) / 5
            )
            active_evidence: list[tuple[float, float]] = []
            for family, family_confidence in family_confidences.items():
                component = components.get(family)
                if not isinstance(component, dict) or family_confidence <= 0:
                    continue
                component_value = abs(_number(component.get("value")))
                if component_value >= 0.005:
                    active_evidence.append((component_value, family_confidence))
            evidence_mass = sum(value for value, _ in active_evidence)
            evidence_confidence = (
                sum(value * confidence for value, confidence in active_evidence) / evidence_mass
                if evidence_mass
                else 0.0
            )
            breadth = 1 - math.exp(-len(active_evidence) / 2)
            prediction_confidence = evidence_confidence * (0.65 + 0.35 * breadth)
            confidence = _clamp(
                exact_confidence + (1 - exact_confidence) * prediction_confidence,
                0,
                1,
            )
            components["direct"] = {
                "value": direct.outcome,
                "confidence": exact_confidence,
                "effective_evidence": direct.effective_evidence,
                "signals": list(direct.signal_types),
                "residual": _clamp(direct.outcome - general, -2, 2),
            }
            components["fit"] = {
                "cooldown": -cooldown,
                "satiation": -satiation,
                "not_now": -not_now,
                "recovery": recovery,
            }
            scores.append(
                _Score(
                    scene_id,
                    general,
                    direct.outcome,
                    exact_confidence,
                    appeal,
                    current_fit,
                    confidence,
                    metadata_confidence,
                    recovery,
                    components,
                    neighbor_data.neighbors,
                    eligibility.get(scene_id, {"eligible": False, "reasons": ["missing"]}),
                )
            )
            progress_index = len(preference_vectors) + scene_index
            if self.progress and (scene_index == total_scenes or scene_index % 250 == 0):
                self._report(0.20 + 0.70 * progress_index / max(1, progress_total))
        return tuple(scores)

    def _preference_content_vectors(
        self,
        vectors: dict[str, dict[str, float]],
        scene_features: dict[str, tuple[StoredFeature, ...]],
        affinities: dict[str, _Affinity],
    ) -> tuple[dict[str, dict[str, float]], int]:
        strengths: dict[str, float] = {}
        for features in scene_features.values():
            for feature in features:
                if feature.family != "content" or feature.name in strengths:
                    continue
                affinity = affinities.get(feature.feature_id)
                strengths[feature.name] = (
                    max(0.0, affinity.affinity) * affinity.confidence if affinity else 0.0
                )
        maximum = max(strengths.values(), default=0.0)
        generic = self.config.model.neighbor_generic_weight
        weighted: dict[str, dict[str, float]] = {}
        for scene_id, vector in vectors.items():
            values: dict[str, float] = {}
            for name, value in vector.items():
                multiplier = (
                    generic + (1 - generic) * strengths.get(name, 0.0) / maximum
                    if maximum > 0
                    else 1.0
                )
                if multiplier > 1e-9:
                    values[name] = value * multiplier
            norm = math.sqrt(sum(value * value for value in values.values())) or 1.0
            weighted[scene_id] = {name: value / norm for name, value in values.items()}
        return weighted, sum(strength > 0 for strength in strengths.values())

    def _content_neighbors(
        self,
        vectors: dict[str, dict[str, float]],
        labels: dict[str, _SceneLabel],
        label_mean: float,
        progress_total: int,
    ) -> dict[str, _NeighborEvidence]:
        inverted: dict[str, list[tuple[str, float]]] = defaultdict(list)
        vector_count = len(vectors)
        for scene_id, vector in vectors.items():
            if scene_id not in labels:
                continue
            for name, value in vector.items():
                inverted[name].append((scene_id, value))
        result: dict[str, _NeighborEvidence] = {}
        for vector_index, (scene_id, vector) in enumerate(vectors.items(), 1):
            dots: dict[str, float] = defaultdict(float)
            shared: dict[str, int] = defaultdict(int)
            for name, value in vector.items():
                for other_id, other_value in inverted.get(name, ()):
                    if other_id == scene_id:
                        continue
                    dots[other_id] += value * other_value
                    shared[other_id] += 1
            evidence = []
            for other_id, cosine in dots.items():
                overlap = 1 - math.exp(-shared[other_id] / 4)
                similarity = cosine * overlap
                if similarity < self.config.model.minimum_neighbor_similarity:
                    continue
                weight = similarity**3 * labels[other_id].confidence
                evidence.append((other_id, similarity, weight, labels[other_id].outcome))
            evidence.sort(key=lambda item: (-item[2], item[0]))
            selected = evidence[: self.config.model.neighbor_count]
            denominator = sum(item[2] for item in selected)
            outcome_mean = (
                sum(item[2] * item[3] for item in selected) / denominator if denominator else 0.0
            )
            lift = outcome_mean - label_mean if denominator else 0.0
            confidence = (
                1 - math.exp(-denominator / self.config.model.neighbor_confidence_scale)
                if denominator
                else 0.0
            )
            result[scene_id] = _NeighborEvidence(
                lift * confidence,
                outcome_mean,
                lift,
                confidence,
                denominator,
                tuple(
                    {
                        "scene_id": item[0],
                        "similarity": item[1],
                        "weight": item[2],
                        "outcome": item[3],
                    }
                    for item in selected[:5]
                ),
            )
            if self.progress and (vector_index == vector_count or vector_index % 250 == 0):
                self._report(0.20 + 0.70 * vector_index / max(1, progress_total))
        return result

    def _performer_similarity_scores(
        self,
        feature_version: str,
        scene_features: dict[str, tuple[StoredFeature, ...]],
        affinities: dict[str, _Affinity],
    ) -> dict[str, dict[str, object]]:
        identity_affinity: dict[str, tuple[float, float]] = {}
        for features in scene_features.values():
            for feature in features:
                if feature.family != "performer_identity" or feature.feature_id not in affinities:
                    continue
                affinity = affinities[feature.feature_id]
                identity_affinity[feature.name.removeprefix("performer:")] = (
                    affinity.affinity * affinity.confidence,
                    affinity.confidence,
                )
        profiles = FeatureStore(self.connection).performer_profiles(feature_version)
        weights = dict(self.config.feature.performer_block_weights)
        known = {key: profiles[key] for key in identity_affinity if key in profiles}
        matches_by_performer: dict[str, list[dict[str, object]]] = {
            performer_id: [] for performer_id in profiles
        }
        for performer_id, profile in profiles.items():
            for known_id, known_profile in known.items():
                if known_id == performer_id or (performer_id in known and known_id < performer_id):
                    continue
                similarity = performer_similarity(profile, known_profile, weights)
                if similarity.similarity <= 0:
                    continue
                matches_by_performer[performer_id].append(
                    {
                        "performer_id": known_id,
                        "similarity": similarity.similarity,
                        "affinity": identity_affinity[known_id][0],
                        "confidence": identity_affinity[known_id][1],
                        "blocks": similarity.block_similarities,
                    }
                )
                if performer_id in known:
                    matches_by_performer[known_id].append(
                        {
                            "performer_id": performer_id,
                            "similarity": similarity.similarity,
                            "affinity": identity_affinity[performer_id][0],
                            "confidence": identity_affinity[performer_id][1],
                            "blocks": similarity.block_similarities,
                        }
                    )
        result: dict[str, dict[str, object]] = {}
        for performer_id, matches in matches_by_performer.items():
            matches.sort(key=lambda item: (-_number(item["similarity"]), str(item["performer_id"])))
            selected = matches[:5]
            denominator = sum(_number(item["similarity"]) ** 3 for item in selected)
            value = (
                sum(
                    _number(item["affinity"]) * _number(item["similarity"]) ** 3
                    for item in selected
                )
                / denominator
                if denominator
                else 0.0
            )
            confidence = (
                sum(
                    _number(item["confidence"]) * _number(item["similarity"]) ** 3
                    for item in selected
                )
                / denominator
                if denominator
                else 0.0
            )
            result[performer_id] = {
                "value": value,
                "confidence": confidence,
                "matches": selected[:3],
            }
        return result

    def _performer_priors(self) -> dict[str, _Prior]:
        result: dict[str, _Prior] = {}
        for row in self.connection.execute(
            "SELECT performer_id, favorite, rating100 FROM source_performer"
        ):
            prior = self.config.model.performer_favorite_prior if row["favorite"] else 0.0
            if row["rating100"] is not None:
                prior += (
                    _clamp((float(row["rating100"]) - 50) / 50)
                    * self.config.model.performer_rating_bound
                )
            result[str(row["performer_id"])] = _Prior(
                prior,
                0.90 if row["favorite"] else 0.75 if row["rating100"] is not None else 0.0,
            )
        return result

    def _studio_priors(self) -> dict[str, _Prior]:
        return {
            str(row["studio_id"]): _Prior(self.config.model.studio_favorite_prior, 0.70)
            for row in self.connection.execute(
                "SELECT studio_id FROM source_studio WHERE favorite=1"
            )
        }

    @staticmethod
    def _asymmetric(values: list[float]) -> float:
        positives = sorted((value for value in values if value > 0), reverse=True)
        negatives = [value for value in values if value < 0]
        positive = positives[0] + 0.25 * sum(positives[1:]) if positives else 0.0
        friction = 0.25 * sum(negatives) / len(negatives) if negatives else 0.0
        return positive + friction

    def _recovery(self, last_played_ms: int | None, reference_at_ms: int) -> float:
        if last_played_ms is None:
            return 1.0
        days = max(0.0, (reference_at_ms - last_played_ms) / 86_400_000)
        return scene_recovery(days, config=self.config.model)

    def _recent_context(
        self, reference_at_ms: int, vectors: dict[str, dict[str, float]]
    ) -> dict[str, object]:
        scene_performers: dict[str, list[str]] = defaultdict(list)
        for row in self.connection.execute(
            "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"
        ):
            scene_performers[str(row["scene_id"])].append(str(row["performer_id"]))
        scene_studios = {
            str(row["scene_id"]): str(row["studio_id"])
            for row in self.connection.execute(
                "SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL"
            )
        }
        not_now = {
            str(row["scene_id"]): int(row["occurred_at_ms"])
            for row in self.connection.execute(
                """
                SELECT scene_id, max(occurred_at_ms) AS occurred_at_ms FROM feedback
                WHERE feedback_type='not_now' AND reversed_by_id IS NULL GROUP BY scene_id
                """
            )
        }
        cutoff = reference_at_ms - 30 * 86_400_000
        rows = self.connection.execute(
            """
            SELECT p.scene_id, max(p.played_at_ms) AS played_at, s.studio_id
            FROM source_play p JOIN source_scene s ON s.scene_id=p.scene_id
            WHERE p.played_at_ms >= ? GROUP BY p.scene_id ORDER BY played_at DESC LIMIT 200
            """,
            (cutoff,),
        ).fetchall()
        performers: dict[str, int] = {}
        studios: dict[str, int] = {}
        recent_vectors = []
        for row in rows:
            scene_id = str(row["scene_id"])
            played_at = int(row["played_at"])
            if row["studio_id"]:
                studios[str(row["studio_id"])] = max(
                    played_at, studios.get(str(row["studio_id"]), 0)
                )
            for performer_id in scene_performers.get(scene_id, ()):
                performers[performer_id] = max(played_at, performers.get(performer_id, 0))
            if scene_id in vectors:
                recent_vectors.append((scene_id, played_at, vectors[scene_id]))
        return {
            "reference": reference_at_ms,
            "performers": performers,
            "studios": studios,
            "scene_performers": scene_performers,
            "scene_studios": scene_studios,
            "not_now": not_now,
            "vectors": recent_vectors,
            "scene_vectors": vectors,
        }

    def _satiation(self, scene_id: str, appeal: float, context: dict[str, object]) -> float:
        if appeal <= 0:
            return 0.0
        reference_value = context["reference"]
        if not isinstance(reference_value, int):
            raise TypeError("recent-context reference must be an integer")
        reference = reference_value
        performer_times = context["performers"]
        studio_times = context["studios"]
        scene_performers = context["scene_performers"]
        scene_studios = context["scene_studios"]
        assert isinstance(performer_times, dict)
        assert isinstance(studio_times, dict)
        assert isinstance(scene_performers, dict)
        assert isinstance(scene_studios, dict)
        performer_penalty = 0.0
        for performer_id in scene_performers.get(scene_id, ()):
            timestamp = performer_times.get(str(performer_id))
            if isinstance(timestamp, int):
                days = max(0.0, (reference - timestamp) / 86_400_000)
                performer_penalty = max(performer_penalty, 0.06 * math.exp(-days / 7))
        studio_penalty = 0.0
        studio_id = scene_studios.get(scene_id)
        if isinstance(studio_id, str) and isinstance(studio_times.get(studio_id), int):
            timestamp = int(studio_times[studio_id])
            days = max(0.0, (reference - timestamp) / 86_400_000)
            studio_penalty = 0.03 * math.exp(-days / 7)
        content_penalty = 0.0
        recent_vectors = context["vectors"]
        scene_vectors = context["scene_vectors"]
        assert isinstance(recent_vectors, list)
        assert isinstance(scene_vectors, dict)
        candidate = scene_vectors.get(scene_id, {})
        if isinstance(candidate, dict) and candidate:
            for recent_scene, played_at, vector in recent_vectors:
                if recent_scene == scene_id or not isinstance(vector, dict):
                    continue
                cosine = sum(
                    float(value) * float(vector.get(name, 0.0)) for name, value in candidate.items()
                )
                days = max(0.0, (reference - int(played_at)) / 86_400_000)
                content_penalty = max(content_penalty, 0.04 * cosine * math.exp(-days / 7))
        return min(
            self.config.model.satiation_bound,
            appeal * (performer_penalty + studio_penalty + content_penalty),
        )

    def _not_now_penalty(
        self, scene_id: str, reference_at_ms: int, context: dict[str, object]
    ) -> float:
        not_now = context["not_now"]
        assert isinstance(not_now, dict)
        occurred_at_ms = not_now.get(scene_id)
        if not isinstance(occurred_at_ms, int):
            return 0.0
        age_days = max(0.0, (reference_at_ms - occurred_at_ms) / 86_400_000)
        if age_days >= self.config.model.not_now_days:
            return 0.0
        return self.config.model.not_now_penalty * (1 - age_days / self.config.model.not_now_days)

    def _eligibility(self, reference_at_ms: int) -> dict[str, dict[str, object]]:
        return scene_eligibility(
            self.connection, reference_at_ms, self.config, include_temporary=False
        )

    def _publish(
        self,
        model_id: str,
        feature_version: str,
        affinities: dict[str, _Affinity],
        labels: dict[str, _SceneLabel],
        scores: tuple[_Score, ...],
    ) -> None:
        scores_by_scene = {score.scene_id: score for score in scores}
        with transaction(self.connection):
            self.connection.execute("DELETE FROM feature_affinity WHERE model_id=?", (model_id,))
            self.connection.execute("DELETE FROM direct_scene_state WHERE model_id=?", (model_id,))
            self.connection.execute("DELETE FROM model_scene_score WHERE model_id=?", (model_id,))

        def insert_rows(sql: str, rows: Iterable[tuple[object, ...]]) -> None:
            for batch in batched(rows, 1_000):
                with transaction(self.connection):
                    self.connection.executemany(sql, batch)

        insert_rows(
            """
            INSERT INTO feature_affinity(
                model_id, feature_id, affinity, confidence, effective_support,
                distinct_scene_count, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    model_id,
                    affinity.feature_id,
                    affinity.affinity,
                    affinity.confidence,
                    affinity.support,
                    affinity.scene_count,
                    json.dumps(affinity.contexts, sort_keys=True, separators=(",", ":")),
                )
                for affinity in sorted(affinities.values(), key=lambda item: item.feature_id)
            ),
        )
        insert_rows(
            """
            INSERT INTO direct_scene_state(
                model_id, scene_id, direct_appeal, effective_evidence, confidence, residual
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    model_id,
                    scene_id,
                    label.outcome,
                    label.effective_evidence,
                    direct_confidence(label.effective_evidence, config=self.config.model),
                    _clamp(label.outcome - scores_by_scene[scene_id].general_appeal, -2, 2),
                )
                for scene_id, label in sorted(labels.items())
            ),
        )
        insert_rows(
            """
            INSERT INTO model_scene_score(
                model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery,
                components_json, neighbors_json, eligibility_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    model_id,
                    score.scene_id,
                    score.general_appeal,
                    score.direct_appeal,
                    score.direct_confidence,
                    score.appeal,
                    score.current_fit,
                    score.confidence,
                    score.metadata_confidence,
                    score.recovery,
                    json.dumps(score.components, sort_keys=True, separators=(",", ":")),
                    json.dumps(score.neighbors, sort_keys=True, separators=(",", ":")),
                    json.dumps(score.eligibility, sort_keys=True, separators=(",", ":")),
                )
                for score in scores
            ),
        )
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE model_version SET status='superseded' WHERE status='published'"
            )
            self.connection.execute(
                """
                UPDATE model_version SET status='published', published_at_ms=? WHERE model_id=?
                """,
                (self.clock_ms(), model_id),
            )
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES ('current_model_id', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (model_id,),
            )
