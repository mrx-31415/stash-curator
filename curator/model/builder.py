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
from pathlib import Path
from typing import Any, cast

from curator import core
from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.events.contracts import DEFAULT_CALIBRATION
from curator.events.curves import (
    collapse_signals,
    o_outcome,
    repeat_outcome,
    viewing_outcome,
)
from curator.features import FeatureBuilder, FeatureStore
from curator.features.builder import _fingerprint_table
from curator.features.profiles import NUMERIC_BLOCKS, NUMERIC_SCALES
from curator.features.store import StoredFeature
from curator.model.boundaries import scene_eligibility
from curator.model.curves import blend_appeal, direct_confidence, scene_recovery
from curator.model.watchfit import DEFAULT_VIEW_CURVE, ViewCurveFit, fit_view_curve
from curator.profiling import current_trace, record_duration, span
from curator.storage import ModelStore, transaction
from curator.storage.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    activate_artifact,
    artifact_path,
    attach_build_sources,
    create_artifact,
    create_indexes,
    database_path,
    discard_artifact,
    publish_file,
    validate_artifact,
)
from curator.storage.retention import prune_snapshots

# ponytail: 0.005 removed 38% of measured seeds; make configurable only if
# library-specific timing and quality measurements justify the extra surface.
PERFORMER_SIMILARITY_AFFINITY_CUTOFF = 0.005
MODEL_BUILD_VERSION = 4
# Pairwise-pick signals train feature affinities but never stand in for a
# scene's own absolute sentiment; see _SceneLabel.
PAIR_SIGNAL_TYPES = frozenset({"curation_pair_winner", "curation_pair_loser", "curation_pair_tie"})
# Outcome per pair label: the Bradley-Terry gradient. A tie contributes 0,
# which pulls the features that differed between the two scenes toward the
# label mean rather than toward either extreme.
PAIR_SIGNAL_OUTCOMES = {
    "curation_pair_winner": 1.0,
    "curation_pair_loser": -1.0,
    "curation_pair_tie": 0.0,
}


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
    """A scene's aggregated feedback, split into two channels.

    ``outcome``/``confidence``/``effective_evidence`` cover every signal and
    drive feature-affinity learning: pairwise picks belong here, where the
    ±1 winner/loser conversion is the Bradley-Terry gradient.

    ``absolute_*`` excludes pairwise picks. A pick says "this beat that", not
    "this is a 10/10" — materializing it as absolute sentiment made a scene
    that lost one comparison against a better scene read as strongly disliked
    everywhere appeal is surfaced (Sentiment review, Prune). Ratings stay the
    absolute anchors, per docs/workpackage-pairwise-picks.md.
    """

    outcome: float
    confidence: float
    effective_evidence: float
    signal_types: tuple[str, ...]
    absolute_outcome: float = 0.0
    absolute_evidence: float = 0.0


@dataclass(frozen=True)
class _Affinity:
    feature_id: str
    affinity: float
    confidence: float
    support: float
    scene_count: int
    contexts: dict[str, object]


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
class _PairEvent:
    """One answered pick, reconstructed from its matched winner/loser feedback
    rows. ``confidence`` is the same surprise/IPS value both rows carry."""

    winner_scene: str
    loser_scene: str
    confidence: float


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


def _soft_bound(value: float, bound: float, knee: float = 0.8) -> float:
    """Bound a component without collapsing ordering at the cap.

    Exact below ``knee * bound`` — where a hard clamp was inactive anyway —
    then smoothly asymptotic to ``bound``. A hard clamp maps every strong
    scene to the identical value, so scenes that saturate stop being
    comparable: 41 scenes shared an appeal of exactly 1.0 on a real library,
    and 43 of the top 200 shared a score with another scene. Appeal is
    ranked and thresholded directly (Prune, Sentiment review), so those ties
    are lost information, not a harmless display detail.

    ``1 - exp(-t)`` rather than ``tanh(t)``: the same saturating shape, but
    the exponential is already used across the Go/Python boundary here and
    is proven to agree bit-for-bit, which the artifact parity gate requires.
    """
    knee_at = knee * bound
    head = bound - knee_at
    magnitude = abs(value)
    if magnitude <= knee_at or head <= 0:
        return _clamp(value, -bound, bound)
    return math.copysign(knee_at + head * (1 - math.exp(-(magnitude - knee_at) / head)), value)


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _edge_matches(entry: dict[str, object]) -> list[Any]:
    """The build's similar-performer matches, validated for persistence."""
    matches = entry.get("matches")
    if not isinstance(matches, list):
        raise RuntimeError("performer similarity result is missing matches")
    return matches


_CLASSIFICATION_FAMILIES = (
    "content",
    "content_neighbor",
    "performer_identity",
    "performer_similarity",
    "studio",
    "structure",
)


def _classification_payload(
    components: dict[str, object], *, stretch_contributor_count: int = 3
) -> dict[str, object]:
    """Slim component view that lane classification reads.

    Classification only needs the six family values, the direct signals, and a
    bounded Stretch contributor list; this avoids storing (and later parsing) the
    full components_json with its unbounded top-contributor metadata for every
    scene.
    """
    payload: dict[str, object] = {}
    for family in _CLASSIFICATION_FAMILIES:
        component = components.get(family)
        value = component.get("value") if isinstance(component, dict) else 0.0
        payload[family] = {"value": _number(value)}
    direct = components.get("direct")
    payload["direct"] = {
        "signals": list(direct.get("signals", [])) if isinstance(direct, dict) else []
    }
    payload["stretch_contributors"] = _stretch_contributor_payload(
        components, count=stretch_contributor_count
    )
    return payload


def _confirmed_tag_candidates(contributions: list[dict[str, object]]) -> list[dict[str, object]]:
    """Content-family contributions restricted to StashDB-confirmed tags.

    Description terms and unconfirmed tags cannot be named as a Stretch taste
    dimension — see docs/workpackage-lane-redesign.md ("Facets, not tags").
    """
    candidates = []
    for item in contributions:
        metadata = item.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("tag_id") is None:
            continue
        reason = metadata.get("role_reason")
        if not (isinstance(reason, str) and reason.startswith("stashdb_")):
            continue
        candidates.append(
            {
                "feature_id": item["feature_id"],
                "name": metadata.get("tag_name") or item["name"],
                "facet_type": "tag",
                "value": item["value"],
                "affinity": item["affinity"],
                "confidence": item["confidence"],
                "effective_support": item["effective_support"],
            }
        )
    return candidates


_STRETCH_CONTRIBUTOR_FIELDS = (
    "feature_id",
    "name",
    "facet_type",
    "value",
    "affinity",
    "confidence",
    "effective_support",
)


def _stretch_contributor_payload(components: dict[str, object], *, count: int) -> dict[str, object]:
    """Bounded positive/negative contributor list for the Stretch lane.

    Combines the confirmed-tag and studio candidates computed alongside the
    content/studio components, sorted by signed value, and capped at `count` per
    side — six small records rather than the unbounded per-feature detail
    258452e removed from classification_json.
    """
    pool: list[dict[str, object]] = []
    for family in ("content", "studio"):
        component = components.get(family)
        if isinstance(component, dict):
            pool.extend(cast(list[dict[str, object]], component.get("stretch_candidates") or []))
    positive = sorted(
        (item for item in pool if _number(item.get("value")) > 0),
        key=lambda item: (-_number(item["value"]), str(item["name"])),
    )[:count]
    negative = sorted(
        (item for item in pool if _number(item.get("value")) < 0),
        key=lambda item: (_number(item["value"]), str(item["name"])),
    )[:count]
    return {
        "positive": [{key: item[key] for key in _STRETCH_CONTRIBUTOR_FIELDS} for item in positive],
        "negative": [{key: item[key] for key in _STRETCH_CONTRIBUTOR_FIELDS} for item in negative],
    }


def _entity_dormancy_rows(
    artifact: sqlite3.Connection, model_id: str, feature_version: str
) -> list[tuple[str, str, int, float, int, int]]:
    """Per-entity (performer/studio/confirmed tag) play history for the
    Dormant lane: entity_type, entity_id, last_played_at_ms, positive_strength,
    play_count, distinct_scene_count.

    Only entities with at least one recorded play appear (last_played_at_ms
    has no meaningful value otherwise, and the Dormant gate's play_count
    floor would reject them anyway). positive_strength averages over
    *distinct* played scenes, not raw play events, so a scene replayed many
    times doesn't out-vote scenes played once each. Tags are restricted to
    StashDB-confirmed ones (see docs/workpackage-lane-redesign.md, "Tag
    confirmation") since the lane names the entity to the user, and their
    positive_strength comes from the tag's own learned feature_affinity
    rather than a play-weighted mean — the taste signal is in the affinity,
    not in how many of the tag's scenes happened to be played.
    """
    rows: list[tuple[str, str, int, float, int, int]] = []
    performer_rows = artifact.execute(
        """
        WITH plays AS (
            SELECT sp.performer_id AS entity_id, spl.scene_id, spl.played_at_ms
            FROM scene_performer sp JOIN source_play spl ON spl.scene_id = sp.scene_id
        ),
        stats AS (
            SELECT entity_id, max(played_at_ms) AS last_played_at_ms, count(*) AS play_count,
                   count(DISTINCT scene_id) AS distinct_scene_count
            FROM plays GROUP BY entity_id
        ),
        distinct_scenes AS (SELECT DISTINCT entity_id, scene_id FROM plays),
        appeal AS (
            SELECT ds.entity_id,
                   sum(mss.direct_appeal * mss.direct_confidence) AS weighted_sum,
                   sum(mss.direct_confidence) AS weight_sum
            FROM distinct_scenes ds
            JOIN model_scene_score mss ON mss.scene_id = ds.scene_id AND mss.model_id = ?
            GROUP BY ds.entity_id
        )
        SELECT s.entity_id, s.last_played_at_ms, s.play_count, s.distinct_scene_count,
               COALESCE(a.weighted_sum, 0) AS weighted_sum, COALESCE(a.weight_sum, 0) AS weight_sum
        FROM stats s LEFT JOIN appeal a ON a.entity_id = s.entity_id
        """,
        (model_id,),
    )
    for row in performer_rows:
        weight_sum = _number(row["weight_sum"])
        positive_strength = _number(row["weighted_sum"]) / weight_sum if weight_sum else 0.0
        rows.append(
            (
                "performer",
                str(row["entity_id"]),
                int(row["last_played_at_ms"]),
                positive_strength,
                int(row["play_count"]),
                int(row["distinct_scene_count"]),
            )
        )
    studio_rows = artifact.execute(
        """
        WITH plays AS (
            SELECT ss.studio_id AS entity_id, spl.scene_id, spl.played_at_ms
            FROM source_scene ss JOIN source_play spl ON spl.scene_id = ss.scene_id
            WHERE ss.studio_id IS NOT NULL
        ),
        stats AS (
            SELECT entity_id, max(played_at_ms) AS last_played_at_ms, count(*) AS play_count,
                   count(DISTINCT scene_id) AS distinct_scene_count
            FROM plays GROUP BY entity_id
        ),
        distinct_scenes AS (SELECT DISTINCT entity_id, scene_id FROM plays),
        appeal AS (
            SELECT ds.entity_id,
                   sum(mss.direct_appeal * mss.direct_confidence) AS weighted_sum,
                   sum(mss.direct_confidence) AS weight_sum
            FROM distinct_scenes ds
            JOIN model_scene_score mss ON mss.scene_id = ds.scene_id AND mss.model_id = ?
            GROUP BY ds.entity_id
        )
        SELECT s.entity_id, s.last_played_at_ms, s.play_count, s.distinct_scene_count,
               COALESCE(a.weighted_sum, 0) AS weighted_sum, COALESCE(a.weight_sum, 0) AS weight_sum
        FROM stats s LEFT JOIN appeal a ON a.entity_id = s.entity_id
        """,
        (model_id,),
    )
    for row in studio_rows:
        weight_sum = _number(row["weight_sum"])
        positive_strength = _number(row["weighted_sum"]) / weight_sum if weight_sum else 0.0
        rows.append(
            (
                "studio",
                str(row["entity_id"]),
                int(row["last_played_at_ms"]),
                positive_strength,
                int(row["play_count"]),
                int(row["distinct_scene_count"]),
            )
        )
    tag_rows = artifact.execute(
        """
        WITH confirmed_tags AS (
            SELECT fd.feature_id, json_extract(fd.metadata_json, '$.tag_id') AS tag_id
            FROM feature_definition fd
            WHERE fd.feature_version = ? AND fd.family = 'content'
              AND json_extract(fd.metadata_json, '$.tag_id') IS NOT NULL
              AND json_extract(fd.metadata_json, '$.role_reason') LIKE 'stashdb_%'
        ),
        plays AS (
            SELECT ct.tag_id AS entity_id, spl.scene_id, spl.played_at_ms
            FROM scene_tag st
            JOIN confirmed_tags ct ON ct.tag_id = st.tag_id
            JOIN source_play spl ON spl.scene_id = st.scene_id
        ),
        stats AS (
            SELECT entity_id, max(played_at_ms) AS last_played_at_ms, count(*) AS play_count,
                   count(DISTINCT scene_id) AS distinct_scene_count
            FROM plays GROUP BY entity_id
        )
        SELECT s.entity_id, s.last_played_at_ms, s.play_count, s.distinct_scene_count,
               fa.affinity, fa.confidence
        FROM stats s
        JOIN confirmed_tags ct ON ct.tag_id = s.entity_id
        JOIN feature_affinity fa ON fa.feature_id = ct.feature_id AND fa.model_id = ?
        """,
        (feature_version, model_id),
    )
    for row in tag_rows:
        rows.append(
            (
                "tag",
                str(row["entity_id"]),
                int(row["last_played_at_ms"]),
                _number(row["affinity"]) * _number(row["confidence"]),
                int(row["play_count"]),
                int(row["distinct_scene_count"]),
            )
        )
    return rows


def _numpy_cosine_matrix(
    np: Any,
    values: Any,
    known_values: Any,
    confidences: Any,
    known_confidences: Any,
    norms: Any,
    known_norms: Any,
) -> Any:
    """Vectorized block cosine for profile blocks that use the shared-key dot product.

    Matches the pure-Python _cosine: dot over shared keys divided by the product of
    norms, scaled by the mean of the pairwise minimum confidences, clamped to [0, 1].
    """
    dot = values @ known_values.T
    # Shared counts never exceed the feature count, so float32 is exact and uses the
    # BLAS matmul path; the confidence mean is then computed in float64.
    shared = ((values != 0).astype(np.float32) @ (known_values != 0).astype(np.float32).T).astype(
        np.float64
    )
    confidence_sum = np.zeros((values.shape[0], known_values.shape[0]), dtype=np.float64)
    for column in range(values.shape[1]):
        if not confidences[:, column].any() or not known_confidences[:, column].any():
            continue
        confidence_sum += np.minimum.outer(confidences[:, column], known_confidences[:, column])
    with np.errstate(divide="ignore", invalid="ignore"):
        confidence = np.where(shared > 0, confidence_sum / shared, 0.0)
        cosine = dot / (norms[:, None] * known_norms[None, :]) * confidence
    return np.clip(cosine, 0.0, 1.0)


def _numpy_numeric_matrix(
    np: Any,
    values: Any,
    known_values: Any,
    confidences: Any,
    known_confidences: Any,
    scales: Any,
) -> tuple[Any, Any]:
    """Vectorized numeric-block closeness and shared-key counts.

    Mirrors the pure-Python _numeric: each shared key contributes
    exp(-abs difference / scale) * min confidence; the block value is the mean over
    the shared keys.
    """
    value = np.zeros((values.shape[0], known_values.shape[0]), dtype=np.float64)
    count = np.zeros_like(value)
    for column in range(values.shape[1]):
        both = np.outer(values[:, column] != 0, known_values[:, column] != 0)
        if not both.any():
            continue
        closeness = np.exp(
            -np.abs(np.subtract.outer(values[:, column], known_values[:, column])) / scales[column]
        )
        value += (
            closeness
            * np.minimum.outer(confidences[:, column], known_confidences[:, column])
            * both
        )
        count += both
    return value, count


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
        # Replaced by build(); the unadopted default keeps the shipped curve so
        # calling _scene_labels() outside a build behaves as it always did.
        self._view_curve_fit = ViewCurveFit(
            DEFAULT_VIEW_CURVE, 0.0, False, "not_fitted", 0, 0, math.inf, math.inf, math.inf
        )

    def build(self) -> ModelBuildResult:
        started = time.perf_counter()
        stage_started = started
        timings: dict[str, int] = {}
        # FeatureBuilder is deterministic and reuses an existing version when neither
        # source data nor feature configuration changed. Always ask it for the current
        # version so a feature-only configuration change cannot silently train against
        # stale vectors.
        feature = FeatureBuilder(
            self.connection,
            self.config,
            clock_ms=self.clock_ms,
            progress=lambda processed, total: self._report(0.25 * processed / max(1, total)),
        ).build()
        feature_version = feature.feature_version
        self._report(0.25)
        timings.update(
            {f"feature_{name}": duration for name, duration in feature.stage_timings_ms.items()}
        )
        record_duration(
            "python",
            "model.features",
            round((time.perf_counter() - stage_started) * 1000),
        )
        stage_started = time.perf_counter()
        reference_at_ms = (self.clock_ms() // 86_400_000) * 86_400_000
        # Fit the watch-time response curve before labels are read: the fitted
        # curve is what turns a session duration into a view outcome, so it has
        # to be in hand before any label is computed. Because the labels feed
        # the evidence fingerprint, a changed curve changes the model_id on its
        # own -- reproducibility needs no separate versioning.
        self._view_curve_fit = self._fit_view_curve()
        labels = self._scene_labels()
        training_labels = self._training_labels(labels)
        self._report(0.30)
        timings["labels"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "model.labels", timings["labels"])
        evidence_fingerprint = self._evidence_fingerprint(labels)
        model_digest = hashlib.sha256(
            (
                f"{feature_version}\0{evidence_fingerprint}\0{self._source_fingerprint()}\0"
                f"{self.config.canonical_json()}\0{PERFORMER_SIMILARITY_AFFINITY_CUTOFF}\0"
                f"{MODEL_BUILD_VERSION}\0{reference_at_ms}"
            ).encode()
        ).hexdigest()
        model_id = f"model-{model_digest[:20]}"
        existing = self.connection.execute(
            """
            SELECT status, artifact_basename, validation_status FROM model_version
            WHERE model_id=?
            """,
            (model_id,),
        ).fetchone()
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
                    "UPDATE model_version SET reuse_count=reuse_count+1 WHERE model_id=?",
                    (model_id,),
                )
            self._report(1.0)
            timings["total"] = round((time.perf_counter() - started) * 1000)
            return self._result(
                model_id, feature_version, len(labels), reused=True, timings=timings
            )

        model_config_json = json.dumps(
            {
                "config": asdict(self.config),
                "model_build_version": MODEL_BUILD_VERSION,
                "reference_at_ms": reference_at_ms,
                "view_curve": self._view_curve_fit.as_payload(),
            },
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
            # _affinities' general per-scene loop is scoped to the absolute
            # channel (see _affinities), so its own baseline must be too, or a
            # pairwise pick anywhere in the corpus would still nudge every
            # shared feature's affinity via label_mean even though the loop
            # itself no longer touches that feature for this comparison.
            absolute_label_mean = self._absolute_label_mean(training_labels)
            affinities = self._affinities(scene_features, training_labels, absolute_label_mean)
            self._report(0.35)
            timings["affinities"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "model.affinities", timings["affinities"])
            stage_started = time.perf_counter()
            scores, performer_similarity_scores = self._scores(
                feature_version,
                scene_features,
                affinities,
                labels,
                training_labels,
                label_mean,
                reference_at_ms,
                timings,
            )
            score_total = round((time.perf_counter() - stage_started) * 1000)
            timings["scoring"] = max(0, score_total - timings["similarity"])
            record_duration("python", "model.scores", score_total)
            stage_started = time.perf_counter()
            timings.update(
                self._publish(
                    model_id,
                    feature_version,
                    affinities,
                    labels,
                    scores,
                    performer_similarity_scores,
                )
            )
            self._report(0.98)
            record_duration(
                "python",
                "model.publish",
                round((time.perf_counter() - stage_started) * 1000),
            )
        except Exception:
            model_store.fail(model_id)
            raise
        stage_started = time.perf_counter()
        prune_snapshots(self.connection)
        timings["cleanup"] = round((time.perf_counter() - stage_started) * 1000)
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

    def _fit_view_curve(self) -> ViewCurveFit:
        """Fit the watch-time response curve on this instance's first plays.

        The label is an outcome the curve cannot influence: did the user come
        back to that scene more than a day later. The ordering is fixed by
        scene_id so cross-validation folds are assigned identically here and in
        the Go mirror without either side needing a random seed.
        """
        first_plays = [
            (float(row["active_seconds"]), bool(row["returned"]))
            for row in self.connection.execute(
                """
                WITH first_play AS (
                    SELECT scene_id, MIN(started_at_ms) AS first_ms
                    FROM play_session GROUP BY scene_id
                )
                SELECT s.active_seconds AS active_seconds,
                       EXISTS(
                           SELECT 1 FROM play_session later
                           WHERE later.scene_id = s.scene_id
                             AND later.started_at_ms > s.started_at_ms + 86400000
                       ) AS returned
                FROM play_session s
                JOIN first_play f
                  ON f.scene_id = s.scene_id AND f.first_ms = s.started_at_ms
                WHERE s.active_seconds > 0
                ORDER BY s.scene_id
                """
            )
        ]
        return fit_view_curve(first_plays)

    def _recomputed_view_outcome(
        self, row: sqlite3.Row, payload: dict[str, Any]
    ) -> tuple[float, float, str] | None:
        """Re-derive an occasion's outcome under the fitted curve.

        The stored `behavior_event.outcome` is whatever the curve compiled in at
        write time produced, and the builder cannot re-run the importer, so the
        occasion's signals are reconstructed from data that is still on hand:
        the view signal from the session's duration, the repeat signal from the
        gap to the previous session of the same scene, and the O signal from the
        payload's record of which signals took part. Those three are the entire
        signal set an occasion can carry -- confirmed against the stored data,
        where `primary_signal` only ever takes the values view, repeat and o.

        Returns None when the occasion cannot be reconstructed (no surviving
        session row), in which case the caller keeps the stored value.
        """
        if row["active_seconds"] is None:
            return None
        active_seconds = float(row["active_seconds"])
        if not math.isfinite(active_seconds) or active_seconds < 0:
            return None
        historical = str(row["provenance"]) == "historical_import"
        occurred_at_ms = int(row["occurred_at_ms"])
        present = {str(payload.get("primary_signal", ""))}
        supporting = payload.get("supporting_signals")
        if isinstance(supporting, list):
            present.update(str(item) for item in supporting)

        signals = []
        view = viewing_outcome(
            active_seconds,
            occurred_at_ms,
            historical_imputed=historical,
            view_curve=self._view_curve_fit.curve if self._view_curve_fit.adopted else None,
        )
        if view is not None:
            signals.append(view)
        if "repeat" in present and row["previous_started_ms"] is not None:
            gap_hours = (int(row["started_at_ms"]) - int(row["previous_started_ms"])) / 3_600_000
            repeat = repeat_outcome(gap_hours, occurred_at_ms)
            if repeat is not None:
                signals.append(repeat)
        if "o" in present:
            signals.append(o_outcome(occurred_at_ms))
        if not signals:
            return None
        collapsed = collapse_signals(signals)
        if collapsed is None:
            return None
        return (collapsed.value, collapsed.confidence, collapsed.primary_signal)

    def _scene_labels(self) -> dict[str, _SceneLabel]:
        signals: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
        for row in self.connection.execute(
            """
            SELECT e.scene_id AS scene_id, e.event_type AS event_type, e.outcome AS outcome,
                   e.confidence AS confidence, e.payload_json AS payload_json,
                   e.provenance AS provenance, e.occurred_at_ms AS occurred_at_ms,
                   s.active_seconds AS active_seconds, s.started_at_ms AS started_at_ms,
                   (
                       SELECT MAX(previous.started_at_ms) FROM play_session previous
                       WHERE previous.scene_id = s.scene_id
                         AND previous.started_at_ms < s.started_at_ms
                   ) AS previous_started_ms
            FROM behavior_event e
            LEFT JOIN play_session s ON s.session_id = e.session_id
            WHERE e.scene_id IS NOT NULL AND e.outcome IS NOT NULL
            ORDER BY e.scene_id, e.occurred_at_ms
            """
        ):
            payload = json.loads(row["payload_json"])
            recomputed = self._recomputed_view_outcome(row, payload)
            if recomputed is None:
                recomputed = (
                    float(row["outcome"]),
                    float(row["confidence"]),
                    str(payload.get("primary_signal", row["event_type"])),
                )
            signals[str(row["scene_id"])].append(recomputed)
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
            """
            SELECT scene_id, value FROM feedback
            WHERE reversed_by_id IS NULL AND feedback_type='curation_rating'
            ORDER BY scene_id, occurred_at_ms
            """
        ):
            value = row["value"]
            try:
                rating = int(value)
            except (TypeError, ValueError):
                continue
            if not 0 <= rating <= 10:
                continue
            signals[str(row["scene_id"])].append(
                (
                    _clamp((rating - 5) / 5),
                    self.config.model.curation_rating_confidence,
                    "curation_rating",
                )
            )
        for row in self.connection.execute(
            """
            SELECT scene_id, feedback_type, payload_json FROM feedback
            WHERE reversed_by_id IS NULL
              AND feedback_type IN (
                  'curation_pair_winner', 'curation_pair_loser', 'curation_pair_tie'
              )
            ORDER BY scene_id, occurred_at_ms
            """
        ):
            payload = json.loads(str(row["payload_json"]) or "{}")
            try:
                selection_probability = float(payload.get("selection_probability") or 1.0)
                predicted_winner = float(payload.get("predicted_winner") or 0.0)
                predicted_loser = float(payload.get("predicted_loser") or 0.0)
            except (TypeError, ValueError):
                continue
            if not 0 < selection_probability <= 1:
                continue
            feedback_type = str(row["feedback_type"])
            # Surprise-weighted: a pick that contradicts the model's predicted
            # ordering is stronger evidence than one that confirms it.
            surprise = max(0.0, predicted_loser - predicted_winner)
            confidence = (
                self.config.model.curation_pair_confidence
                * (1.0 + self.config.model.curation_pair_surprise_bonus * surprise)
                * min(self.config.model.curation_pair_ips_cap, 1.0 / selection_probability)
            )
            confidence = min(1.0, confidence)
            signals[str(row["scene_id"])].append(
                (PAIR_SIGNAL_OUTCOMES[feedback_type], confidence, feedback_type)
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
            absolute_signals = [
                signal for signal in scene_signals if signal[2] not in PAIR_SIGNAL_TYPES
            ]
            # float(): sum() over no absolute signals returns int 0, which the
            # fingerprint would serialize as "0" where the Go core writes "0.0".
            absolute_evidence = float(sum(confidence for _, confidence, _ in absolute_signals))
            absolute_outcome = (
                sum(value * confidence for value, confidence, _ in absolute_signals)
                / absolute_evidence
                if absolute_evidence > 0
                else 0.0
            )
            labels[scene_id] = _SceneLabel(
                _clamp(outcome),
                1 - math.exp(-evidence),
                evidence,
                tuple(signal for _, _, signal in scene_signals),
                _clamp(absolute_outcome),
                absolute_evidence,
            )
        return labels

    def _metadata_wrong_scenes(self) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT DISTINCT scene_id FROM feedback
                WHERE feedback_type='metadata_wrong' AND reversed_by_id IS NULL
                """
            )
        }

    def _training_labels(self, labels: dict[str, _SceneLabel]) -> dict[str, _SceneLabel]:
        metadata_wrong = self._metadata_wrong_scenes()
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
                label.absolute_outcome,
                label.absolute_evidence,
            )
            for scene_id, label in sorted(labels.items())
        ]
        feedback_state = [
            tuple(row)
            for row in self.connection.execute(
                """
                SELECT feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                       reversed_by_id, payload_json
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
        tag_preferences = [
            tuple(row)
            for row in self.connection.execute(
                """
                SELECT tag_id, preference_id, value, occurred_at_ms
                FROM direct_tag_preference ORDER BY tag_id
                """
            )
        ]
        return hashlib.sha256(
            json.dumps(
                {
                    "labels": payload,
                    "feedback": feedback_state,
                    "exclusions": exclusions,
                    "pruning": pruning,
                    "tag_preferences": tag_preferences,
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

    def _source_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for label, statement in (
            (
                "source_play",
                """
                SELECT scene_id, max(played_at_ms) FROM source_play
                GROUP BY scene_id ORDER BY scene_id
                """,
            ),
            (
                "source_performer",
                """
                SELECT performer_id, favorite, rating100
                FROM source_performer ORDER BY performer_id
                """,
            ),
            (
                "source_studio",
                "SELECT studio_id, favorite FROM source_studio ORDER BY studio_id",
            ),
            (
                "source_file",
                """
                SELECT scene_id, max(available) FROM source_file
                GROUP BY scene_id ORDER BY scene_id
                """,
            ),
        ):
            _fingerprint_table(self.connection, digest, label, statement)
        return digest.hexdigest()

    def _pair_events(self) -> list[_PairEvent]:
        """Reconstruct answered comparisons from their matched winner/loser
        feedback rows, sharing a pair_id in payload_json. A tie has no winner
        so it is not a _PairEvent; a pair reversed on only one side (a
        feedback correction touching just the winner or loser row) yields no
        complete match and is dropped, same as the excluded scene below."""
        metadata_wrong = self._metadata_wrong_scenes()
        by_pair: dict[str, dict[str, Any]] = {}
        for row in self.connection.execute(
            """
            SELECT scene_id, feedback_type, payload_json FROM feedback
            WHERE reversed_by_id IS NULL
              AND feedback_type IN ('curation_pair_winner', 'curation_pair_loser')
            ORDER BY scene_id, occurred_at_ms
            """
        ):
            payload = json.loads(str(row["payload_json"]) or "{}")
            pair_id = payload.get("pair_id")
            scene_id = str(row["scene_id"])
            if not pair_id or scene_id in metadata_wrong:
                continue
            try:
                selection_probability = float(payload.get("selection_probability") or 1.0)
                predicted_winner = float(payload.get("predicted_winner") or 0.0)
                predicted_loser = float(payload.get("predicted_loser") or 0.0)
            except (TypeError, ValueError):
                continue
            if not 0 < selection_probability <= 1:
                continue
            surprise = max(0.0, predicted_loser - predicted_winner)
            confidence = min(
                1.0,
                self.config.model.curation_pair_confidence
                * (1.0 + self.config.model.curation_pair_surprise_bonus * surprise)
                * min(self.config.model.curation_pair_ips_cap, 1.0 / selection_probability),
            )
            entry = by_pair.setdefault(str(pair_id), {"confidence": confidence})
            if str(row["feedback_type"]) == "curation_pair_winner":
                entry["winner_scene"] = scene_id
            else:
                entry["loser_scene"] = scene_id
        return [
            _PairEvent(entry["winner_scene"], entry["loser_scene"], entry["confidence"])
            for _, entry in sorted(by_pair.items())
            if "winner_scene" in entry and "loser_scene" in entry
        ]

    def _affinities(
        self,
        scene_features: dict[str, tuple[StoredFeature, ...]],
        labels: dict[str, _SceneLabel],
        absolute_label_mean: float,
    ) -> dict[str, _Affinity]:
        accumulators: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for scene_id, label in labels.items():
            # Absolute channel only: pairwise picks are accumulated as matched
            # pairs below, where shared features cancel by construction rather
            # than approximately (this loop's own cancellation only held when
            # both scenes had equal confidence and the corpus-wide mean was 0).
            if label.absolute_evidence <= 0:
                continue
            absolute_confidence = 1 - math.exp(-label.absolute_evidence)
            for feature in scene_features.get(scene_id, ()):
                weight = absolute_confidence * feature.confidence * abs(feature.value)
                accumulators[feature.feature_id].append(
                    (
                        scene_id,
                        weight,
                        (label.absolute_outcome - absolute_label_mean)
                        * math.copysign(1, feature.value),
                    )
                )
        # Pairwise comparisons: matched winner/loser, so a feature both scenes
        # share is skipped entirely (no numerator or support contribution) —
        # only what differed between the two scenes carries information. No
        # label_mean subtraction: the comparison already isolates the signal.
        for event in self._pair_events():
            winner_features = {f.feature_id: f for f in scene_features.get(event.winner_scene, ())}
            loser_features = {f.feature_id: f for f in scene_features.get(event.loser_scene, ())}
            # sorted(): set difference has no defined order, and this feeds
            # floating-point sums that must stay byte-identical run to run.
            for feature_id in sorted(winner_features.keys() - loser_features.keys()):
                feature = winner_features[feature_id]
                weight = event.confidence * feature.confidence * abs(feature.value)
                accumulators[feature_id].append(
                    (event.winner_scene, weight, math.copysign(1, feature.value))
                )
            for feature_id in sorted(loser_features.keys() - winner_features.keys()):
                feature = loser_features[feature_id]
                weight = event.confidence * feature.confidence * abs(feature.value)
                accumulators[feature_id].append(
                    (event.loser_scene, weight, -math.copysign(1, feature.value))
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
        tag_features = {
            str(feature.metadata["tag_id"]): feature.feature_id
            for features in scene_features.values()
            for feature in features
            if feature.family == "content" and feature.metadata.get("tag_id")
        }
        for row in self.connection.execute(
            "SELECT tag_id, value FROM direct_tag_preference ORDER BY tag_id"
        ):
            direct_feature_id = tag_features.get(str(row["tag_id"]))
            if direct_feature_id is None:
                continue
            learned = result.get(
                direct_feature_id,
                _Affinity(direct_feature_id, 0.0, 0.0, 0.0, 0, {}),
            )
            direct_support = 8.0
            direct_value = float(row["value"])
            result[direct_feature_id] = _Affinity(
                direct_feature_id,
                _clamp(
                    (learned.affinity * learned.support + direct_value * direct_support)
                    / (learned.support + direct_support)
                ),
                max(learned.confidence, 0.9),
                learned.support + direct_support,
                learned.scene_count,
                {
                    **learned.contexts,
                    "declared_preference": direct_value,
                    "learned_affinity": learned.affinity,
                    "learned_confidence": learned.confidence,
                },
            )
        term_features = {
            feature.name.removeprefix("desc:"): feature.feature_id
            for features in scene_features.values()
            for feature in features
            if feature.family == "content" and feature.name.startswith("desc:")
        }
        for row in self.connection.execute(
            "SELECT term, value FROM direct_term_preference ORDER BY term"
        ):
            direct_feature_id = term_features.get(str(row["term"]))
            if direct_feature_id is None:
                continue
            learned = result.get(
                direct_feature_id,
                _Affinity(direct_feature_id, 0.0, 0.0, 0.0, 0, {}),
            )
            direct_support = 8.0
            direct_value = float(row["value"])
            result[direct_feature_id] = _Affinity(
                direct_feature_id,
                _clamp(
                    (learned.affinity * learned.support + direct_value * direct_support)
                    / (learned.support + direct_support)
                ),
                max(learned.confidence, 0.9),
                learned.support + direct_support,
                learned.scene_count,
                {
                    **learned.contexts,
                    "declared_preference": direct_value,
                    "learned_affinity": learned.affinity,
                    "learned_confidence": learned.confidence,
                },
            )
        return result

    @staticmethod
    def _label_mean(labels: dict[str, _SceneLabel]) -> float:
        support = sum(label.confidence for label in labels.values())
        if support <= 0:
            return 0.0
        return sum(label.outcome * label.confidence for label in labels.values()) / support

    @staticmethod
    def _absolute_label_mean(labels: dict[str, _SceneLabel]) -> float:
        """The population baseline for _affinities' general per-scene loop.

        Scoped to the absolute channel (matching that loop's own scope) so a
        pairwise pick's learning-channel outcome never shifts the baseline a
        shared feature is measured against — otherwise a feature two scenes
        share would still drift slightly whenever any pair anywhere in the
        corpus changed, even though its own weight and outcome did not.
        """
        weighted = [
            (1 - math.exp(-label.absolute_evidence), label.absolute_outcome)
            for label in labels.values()
            if label.absolute_evidence > 0
        ]
        support = sum(confidence for confidence, _ in weighted)
        if support <= 0:
            return 0.0
        return sum(confidence * outcome for confidence, outcome in weighted) / support

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
        timings: dict[str, int],
    ) -> tuple[tuple[_Score, ...], dict[str, dict[str, object]]]:
        with span("python", "model.score_vectors"):
            vectors = FeatureStore(self.connection).scene_content_vectors(feature_version)
        all_scene_ids = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT scene_id FROM source_scene ORDER BY scene_id"
            )
        ]
        similarity_started = time.perf_counter()
        with span("python", "model.score_neighbors"):
            preference_vectors, discriminative_tag_count = self._preference_content_vectors(
                vectors, scene_features, affinities
            )
            progress_total = len(preference_vectors) + len(all_scene_ids)
            neighbors = self._content_neighbors(
                feature_version, affinities, training_labels, label_mean, progress_total
            )
        with span("python", "model.score_performer_similarity"):
            performer_similarity_scores = self._performer_similarity_scores(
                feature_version, scene_features, affinities
            )
        timings["similarity"] = round((time.perf_counter() - similarity_started) * 1000)
        baseline_support = sum(label.confidence for label in training_labels.values())
        baseline = (
            label_mean * baseline_support / (self.config.model.affinity_prior + baseline_support)
        )
        baseline = _soft_bound(baseline, self.config.model.baseline_bound)
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
        studio_names = {
            str(row["studio_id"]): str(row["name"] or "")
            for row in self.connection.execute("SELECT studio_id, name FROM source_studio")
        }
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
                            "effective_support": affinity.support,
                            "metadata": feature.metadata,
                            "affinity_metadata": affinity.contexts,
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
                family_payload: dict[str, object] = {
                    "raw": raw,
                    "value": _soft_bound(raw, bound),
                    "evidence_confidence": evidence_confidence,
                    "top": sorted(
                        contributions,
                        key=lambda item: (-abs(_number(item["value"])), str(item["name"])),
                    )[:5],
                }
                if family == "content":
                    family_payload["stretch_candidates"] = _confirmed_tag_candidates(contributions)
                components[family] = family_payload
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
                "value": _soft_bound(identity_raw, self.config.model.performer_identity_bound),
                "performers": identity_values,
                "evidence_confidence": identity_confidence,
            }
            components["performer_similarity"] = {
                "raw": similarity_raw,
                "value": _soft_bound(similarity_raw, self.config.model.performer_similarity_bound),
                "performers": similarity_values,
                "evidence_confidence": similarity_confidence,
            }
            studio_features = [feature for feature in features if feature.family == "studio"]
            studio_items = []
            stretch_studio_candidates: list[dict[str, object]] = []
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
                # A studio only qualifies as a Stretch dimension when the model has an
                # actual feature_affinity row for it — without that, "learned" is 0.0
                # for every studio the model has no opinion on and they would all tie
                # at maximum challenge distance. See docs/workpackage-lane-redesign.md
                # defect 8.
                if affinity is not None:
                    stretch_studio_candidates.append(
                        {
                            "feature_id": feature.feature_id,
                            "name": studio_names.get(studio_id) or feature.name,
                            "facet_type": "studio",
                            "value": learned,
                            "affinity": affinity.affinity,
                            "confidence": affinity.confidence,
                            "effective_support": affinity.support,
                        }
                    )
            studio_raw = sum(_number(item["value"]) for item in studio_items)
            studio_confidence = max(
                (_number(item.get("confidence")) for item in studio_items), default=0.0
            )
            family_confidences["studio"] = studio_confidence
            components["studio"] = {
                "raw": studio_raw,
                "value": _soft_bound(studio_raw, self.config.model.studio_bound),
                "studios": studio_items,
                "evidence_confidence": studio_confidence,
                "stretch_candidates": stretch_studio_candidates,
            }
            neighbor_data = neighbors.get(
                scene_id,
                _NeighborEvidence(0.0, label_mean, 0.0, 0.0, 0.0, ()),
            )
            family_confidences["content_neighbor"] = neighbor_data.confidence
            components["content_neighbor"] = {
                "raw": neighbor_data.value,
                "value": _soft_bound(neighbor_data.value, self.config.model.neighbor_bound),
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
            general = _soft_bound(component_total, 1.0)
            direct = labels.get(scene_id, _SceneLabel(0.0, 0.0, 0.0, ()))
            # Absolute channel only: a pairwise pick is evidence about the
            # features that differed, not a verdict on this scene's own appeal.
            exact_confidence = direct_confidence(direct.absolute_evidence, config=self.config.model)
            appeal = blend_appeal(general, direct.absolute_outcome, exact_confidence)
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
                "value": direct.absolute_outcome,
                "confidence": exact_confidence,
                "effective_evidence": direct.absolute_evidence,
                "signals": list(direct.signal_types),
                "residual": _clamp(direct.absolute_outcome - general, -2, 2),
                "learning_outcome": direct.outcome,
                "learning_evidence": direct.effective_evidence,
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
                    direct.absolute_outcome,
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
                self._report(0.35 + 0.40 * progress_index / max(1, progress_total))
        return tuple(scores), performer_similarity_scores

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
                learned_affinity = (
                    _number(affinity.contexts.get("learned_affinity", affinity.affinity))
                    if affinity
                    else 0.0
                )
                learned_confidence = (
                    _number(affinity.contexts.get("learned_confidence", affinity.confidence))
                    if affinity
                    else 0.0
                )
                strengths[feature.name] = max(0.0, learned_affinity) * learned_confidence
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

    @staticmethod
    def _neighbor_evidence(
        scene_id: str,
        selected: list[tuple[str, float, float, float]],
        label_mean: float,
        confidence_scale: float,
    ) -> _NeighborEvidence:
        """Derive evidence fields from the selected neighbor tuples.

        Shared by the numpy and compiled-core paths so the post-selection math
        stays identical by construction.
        """
        denominator = sum(item[2] for item in selected)
        outcome_mean = (
            sum(item[2] * item[3] for item in selected) / denominator if denominator else 0.0
        )
        lift = outcome_mean - label_mean if denominator else 0.0
        confidence = 1 - math.exp(-denominator / confidence_scale) if denominator else 0.0
        return _NeighborEvidence(
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

    def _feature_artifact_path(self, feature_version: str) -> Path:
        row = self.connection.execute(
            """
            SELECT artifact_basename FROM feature_build
            WHERE feature_version=? AND validation_status='valid'
            """,
            (feature_version,),
        ).fetchone()
        if row is None or not row[0]:
            raise RuntimeError(f"feature artifact missing for {feature_version}")
        return artifact_path(database_path(self.connection), str(row[0]))

    def _content_neighbors(
        self,
        feature_version: str,
        affinities: dict[str, _Affinity],
        labels: dict[str, _SceneLabel],
        label_mean: float,
        progress_total: int,
    ) -> dict[str, _NeighborEvidence]:
        """Content-neighbor evidence via the compiled core (numpy's role).

        The binary reads the content feature rows from the feature artifact and
        derives the preference vectors itself, so this path takes the same
        inputs the numpy path derives from (affinities, labels, config) instead
        of the already-weighted vectors.
        """
        affinity_payload: dict[str, object] = {}
        for feature_id, affinity in affinities.items():
            entry: dict[str, object] = {
                "affinity": affinity.affinity,
                "confidence": affinity.confidence,
            }
            for key in ("learned_affinity", "learned_confidence"):
                if key in affinity.contexts:
                    entry[key] = _number(affinity.contexts[key])
            affinity_payload[feature_id] = entry
        payload: dict[str, object] = {
            "db": str(self._feature_artifact_path(feature_version)),
            "feature_version": feature_version,
            "labels": {
                scene_id: [label.outcome, label.confidence] for scene_id, label in labels.items()
            },
            "label_mean": label_mean,
            "affinities": affinity_payload,
            "config": {
                "min_similarity": self.config.model.minimum_neighbor_similarity,
                "neighbor_count": self.config.model.neighbor_count,
                "confidence_scale": self.config.model.neighbor_confidence_scale,
                "generic_weight": self.config.model.neighbor_generic_weight,
            },
            "progress_total": progress_total,
        }
        response = core.run_core(
            "content-neighbors",
            payload,
            progress=(
                (lambda fraction: self._report(0.35 + 0.40 * fraction)) if self.progress else None
            ),
            profile=current_trace() is not None,
        )
        entries = cast(dict[str, dict[str, object]], response)
        default = _NeighborEvidence(0.0, 0.0, 0.0, 0.0, 0.0, ())
        result: dict[str, _NeighborEvidence] = {}
        for scene_id, entry in entries.items():
            neighbors = entry.get("neighbors")
            if not isinstance(neighbors, list) or not neighbors:
                result[scene_id] = default
                continue
            selected: list[tuple[str, float, float, float]] = []
            for raw in neighbors:
                item = cast(list[Any], raw)
                selected.append((str(item[0]), float(item[1]), float(item[2]), float(item[3])))
            result[scene_id] = self._neighbor_evidence(
                scene_id,
                selected,
                label_mean,
                self.config.model.neighbor_confidence_scale,
            )
        return result

    @staticmethod
    def _identity_affinity(
        scene_features: dict[str, tuple[StoredFeature, ...]],
        affinities: dict[str, _Affinity],
    ) -> dict[str, tuple[float, float]]:
        """Known-performer signals shared by every similarity implementation."""
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
        return identity_affinity

    def _performer_similarity_scores(
        self,
        feature_version: str,
        scene_features: dict[str, tuple[StoredFeature, ...]],
        affinities: dict[str, _Affinity],
    ) -> dict[str, dict[str, object]]:
        """Performer-similarity scores via the compiled core (numpy's role).

        The binary reads the performer profiles from the feature artifact; the
        result dict is already the production format.
        """
        identity_affinity = self._identity_affinity(scene_features, affinities)
        payload: dict[str, object] = {
            "db": str(self._feature_artifact_path(feature_version)),
            "feature_version": feature_version,
            "identity_affinity": {
                performer_id: [value, confidence]
                for performer_id, (value, confidence) in identity_affinity.items()
            },
            "block_weights": dict(self.config.feature.performer_block_weights),
            "cutoff": PERFORMER_SIMILARITY_AFFINITY_CUTOFF,
            "numeric_blocks": sorted(NUMERIC_BLOCKS),
            "numeric_scales": dict(NUMERIC_SCALES),
        }
        response = core.run_core(
            "performer-similarity", payload, profile=current_trace() is not None
        )
        return cast(dict[str, dict[str, object]], response)

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
        recent_by_name: dict[str, list[tuple[int, float]]] = {}
        recent_scene_ids: list[str] = []
        recent_played: list[int] = []
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
                index = len(recent_scene_ids)
                recent_scene_ids.append(scene_id)
                recent_played.append(played_at)
                for name, value in vectors[scene_id].items():
                    recent_by_name.setdefault(name, []).append((index, value))
        return {
            "reference": reference_at_ms,
            "performers": performers,
            "studios": studios,
            "scene_performers": scene_performers,
            "scene_studios": scene_studios,
            "not_now": not_now,
            # Transposed recent-content index: satiation dots accumulate once per
            # candidate feature instead of once per (feature, recent scene) pair.
            "recent_by_name": recent_by_name,
            "recent_scene_ids": recent_scene_ids,
            "recent_played": recent_played,
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
        recent_by_name = context["recent_by_name"]
        recent_scene_ids = context["recent_scene_ids"]
        recent_played = context["recent_played"]
        scene_vectors = context["scene_vectors"]
        assert isinstance(recent_by_name, dict)
        assert isinstance(recent_scene_ids, list)
        assert isinstance(recent_played, list)
        assert isinstance(scene_vectors, dict)
        candidate = scene_vectors.get(scene_id, {})
        if isinstance(candidate, dict) and candidate:
            dots: dict[int, float] = {}
            for name, value in candidate.items():
                for index, recent_value in recent_by_name.get(name, ()):
                    dots[index] = dots.get(index, 0.0) + value * recent_value
            for index, cosine in dots.items():
                if recent_scene_ids[index] == scene_id:
                    continue
                days = max(0.0, (reference - recent_played[index]) / 86_400_000)
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
        performer_similarity_scores: dict[str, dict[str, object]],
    ) -> dict[str, int]:
        timings: dict[str, int] = {}
        writing_started = time.perf_counter()
        scores_by_scene = {score.scene_id: score for score in scores}
        feature_path = self._feature_artifact_path(feature_version)
        artifact, temporary, final = create_artifact(self.connection, "model", model_id)
        attach_build_sources(artifact, self.connection, feature_path)
        published = False

        def insert_rows(sql: str, rows: Iterable[tuple[object, ...]]) -> None:
            for batch in batched(rows, 1_000):
                with transaction(artifact):
                    artifact.executemany(sql, batch)

        try:
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
            self._report(0.78)
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
                        label.absolute_outcome,
                        label.absolute_evidence,
                        direct_confidence(label.absolute_evidence, config=self.config.model),
                        _clamp(
                            label.absolute_outcome - scores_by_scene[scene_id].general_appeal,
                            -2,
                            2,
                        ),
                    )
                    for scene_id, label in sorted(labels.items())
                    # A scene deleted from Stash since these signals were recorded has no
                    # score to compare against. feedback carries no foreign key to
                    # source_scene (unlike behavior_event/play_session) because it is kept
                    # as user-facing history past scene deletion, so this can still happen.
                    if scene_id in scores_by_scene
                ),
            )
            self._report(0.81)
            insert_rows(
                """
                INSERT INTO model_scene_score(
                    model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                    appeal, current_fit, confidence, metadata_confidence, recovery,
                    components_json, classification_json, eligibility_json
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
                        # Lane classification reads only the six family values and the
                        # direct signals; keeping them in a small document avoids
                        # parsing the full components_json (with its top-contributor
                        # metadata for explanations) for every scene on every build.
                        json.dumps(
                            _classification_payload(
                                score.components,
                                stretch_contributor_count=(
                                    self.config.ranking.stretch_contributor_count
                                ),
                            ),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(score.eligibility, sort_keys=True, separators=(",", ":")),
                    )
                    for score in scores
                ),
            )
            insert_rows(
                """
                INSERT INTO model_scene_neighbor(
                    model_id, scene_id, rank, neighbor_scene_id, similarity, weight, outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        model_id,
                        score.scene_id,
                        rank,
                        neighbor["scene_id"],
                        neighbor["similarity"],
                        neighbor["weight"],
                        neighbor["outcome"],
                    )
                    for score in scores
                    for rank, neighbor in enumerate(score.neighbors)
                ),
            )
            self._report(0.85)
            insert_rows(
                """
                INSERT INTO model_performer_edge(
                    model_id, performer_id, rank, similar_performer_id,
                    similarity, affinity, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        model_id,
                        performer_id,
                        rank,
                        str(match["performer_id"]),
                        _number(match["similarity"]),
                        _number(match["affinity"]),
                        _number(match["confidence"]),
                    )
                    for performer_id, entry in sorted(performer_similarity_scores.items())
                    for rank, match in enumerate(_edge_matches(entry))
                ),
            )
            insert_rows(
                """
                INSERT INTO model_entity_dormancy(
                    model_id, entity_type, entity_id, last_played_at_ms,
                    positive_strength, play_count, distinct_scene_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (model_id, *row)
                    for row in _entity_dormancy_rows(artifact, model_id, feature_version)
                ),
            )
            timings["database_writing"] = round((time.perf_counter() - writing_started) * 1000)
            from curator.ranking import LanePolicy, SlateBuilder

            indexing_started = time.perf_counter()
            stage_started = time.perf_counter()
            LanePolicy(artifact, self.config).classify(
                model_id,
                progress=lambda processed, total: self._report(
                    0.85 + 0.02 * processed / max(1, total)
                ),
                now_ms=self.clock_ms(),
            )
            timings["lane_classification"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "model.lane_classification", timings["lane_classification"])
            slate_builder = SlateBuilder(artifact, self.config)
            slate_builder.materialize(
                model_id,
                force=True,
                progress=lambda processed, total: self._report(
                    0.87 + 0.04 * processed / max(1, total)
                ),
            )
            timings.update(slate_builder.materialize_timings_ms)
            for name in ("score_first_ordering", "varied_ordering"):
                record_duration("python", f"model.{name}", timings[name])
            timings["reason_generation"] = 0
            record_duration("python", "model.reason_generation", 0)
            self._report(0.94)
            stage_started = time.perf_counter()
            create_indexes(artifact, "model")
            timings["sqlite_index_creation"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration(
                "python", "model.sqlite_index_creation", timings["sqlite_index_creation"]
            )
            timings["indexing"] = round((time.perf_counter() - indexing_started) * 1000)
            self._report(0.96)
            validation_started = time.perf_counter()
            stored_count = int(
                artifact.execute(
                    "SELECT count(*) FROM model_scene_score WHERE model_id=?", (model_id,)
                ).fetchone()[0]
            )
            lane_count = int(
                artifact.execute(
                    "SELECT count(*) FROM model_scene_lane WHERE model_id=?", (model_id,)
                ).fetchone()[0]
            )
            reason_scene_count = reason_count = 0
            lane_state = artifact.execute(
                "SELECT 1 FROM model_lane_order_state WHERE model_id=?", (model_id,)
            ).fetchone()
            if stored_count != len(scores) or lane_state is None:
                raise RuntimeError(
                    "model validation failed: "
                    f"scores={stored_count}/{len(scores)}, "
                    f"lane state={lane_state is not None}"
                )
            summary = validate_artifact(
                artifact,
                "model",
                {
                    "scenes": stored_count,
                    "lanes": lane_count,
                    "reason_scenes": int(reason_scene_count),
                    "reasons": int(reason_count),
                },
                # ponytail: generated models are atomic and rebuildable; restore the
                # full-file scan if installed evidence ever shows artifact corruption.
                check_integrity=False,
            )
            timings["validation"] = round((time.perf_counter() - validation_started) * 1000)
            self._report(0.97)
            publication_started = time.perf_counter()
            size = publish_file(artifact, temporary, final)
            with transaction(self.connection):
                self.connection.execute(
                    "UPDATE model_version SET status='superseded' WHERE status='published'"
                )
                self.connection.execute(
                    """
                    UPDATE model_version SET status='published', published_at_ms=?,
                        artifact_basename=?, artifact_schema_version=?, artifact_bytes=?,
                        scene_count=?, lane_count=?, reason_scene_count=?, reason_count=?,
                        validation_status='valid', validation_summary_json=?,
                        cleanup_error=NULL
                    WHERE model_id=?
                    """,
                    (
                        self.clock_ms(),
                        final.name,
                        ARTIFACT_SCHEMA_VERSION,
                        size,
                        stored_count,
                        lane_count,
                        int(reason_scene_count),
                        int(reason_count),
                        json.dumps(summary, sort_keys=True, separators=(",", ":")),
                        model_id,
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO application_meta(key, value) VALUES ('current_model_id', ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (model_id,),
                )
            published = True
            activate_artifact(self.connection, "model", final)
            timings["publication"] = round((time.perf_counter() - publication_started) * 1000)
            self._report(0.98)
            return timings
        finally:
            if not published:
                discard_artifact(artifact, temporary)
                if not temporary.exists():
                    final.unlink(missing_ok=True)
