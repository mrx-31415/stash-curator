"""Versioned explanation payload builder (apiSchemaVersion 2).

The backend owns the score semantics, fact ranking, materiality, units, and
deterministic summary. This module turns a ModelSceneScore plus its derived
reasons into the exact v2 payload shape the frontend renders:

    {apiSchemaVersion, summary, components[], reasons[], lane_context{},
     scores: {appeal, current_fit, confidence, rank}, evidence_fingerprint{}}

Materiality thresholds are mirrored module constants (see the Go mirror in
core/explanations.go) — not frontend rules or config-backed model inputs.
"""

from __future__ import annotations

from curator.explanations.reasons import Reason
from curator.model.store import ModelSceneScore

# Materiality thresholds. The same values are mirrored in Go
# (core/explanations.go); they are plain module constants on both sides.
MATERIAL_CONTENT = 0.05
MATERIAL_PERFORMER = 0.05
MATERIAL_STUDIO = 0.05
MATERIAL_SIMILAR = 0.05
MATERIAL_DIRECT = 0.05
MATERIAL_RESIDUAL = 0.10
MATERIAL_FIT = 0.01
MATERIAL_CAUTION = 0.05

# The six fixed radar axes. Metadata coverage is neutral (usable resolved
# evidence coverage), not a preference axis.
FINGERPRINT_AXES = (
    ("content", "Content"),
    ("performers", "Performers"),
    ("studios", "Studios"),
    ("similar_scenes", "Similar scenes"),
    ("direct_history", "Direct history"),
    ("metadata_coverage", "Metadata coverage"),
)

# The fixed tone per fingerprint axis. Metadata coverage is neutral.
FINGERPRINT_TONES = {
    "content": "support",
    "performers": "support",
    "studios": "support",
    "similar_scenes": "support",
    "direct_history": "support",
    "metadata_coverage": "neutral",
}


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _component_value(score: ModelSceneScore, name: str, default: float = 0.0) -> float:
    component = score.components.get(name)
    if not isinstance(component, dict):
        return default
    value = component.get("value", default)
    return float(value) if isinstance(value, (int, float)) else default


def _component_has_evidence(score: ModelSceneScore, name: str) -> bool:
    component = score.components.get(name)
    if not isinstance(component, dict):
        return False
    return "value" in component


def _percentile_rank(scene_id: str, lane: str, ordered_values: list[tuple[str, float]]) -> float:
    """Percentile rank of scene_id within the qualified, ordered population for
    the source lane (before slate diversity/deduplication). Ties share the
    midpoint rank, mirroring curator/ranking/policy._percentiles.

    The `lane` argument is accepted for parity with the Go mirror; the rank is
    a pure percentile of the provided population.
    """
    del lane
    if not ordered_values:
        return 0.0
    ordered = sorted(ordered_values, key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        percentile = ((start + end - 1) / 2) / denominator
        for id_, _ in ordered[start:end]:
            if id_ == scene_id:
                return percentile
        start = end
    return 0.0


def _evidence_fingerprint(
    score: ModelSceneScore,
    components: dict[str, float],
    *,
    direct_history: float,
    metadata_coverage: float,
) -> dict[str, object]:
    """Backend-normalized 0..1 visual strengths for the six fixed axes.

    Each family carries a `tone` (support/caution/neutral), a normalized
    `strength`, and a `present` flag. Missing families use "No evidence"
    (present=False), not an indistinguishable zero. Metadata coverage is
    always present and always neutral.
    """
    axes: dict[str, object] = {}
    values = {
        "content": components.get("content", 0.0),
        "performers": components.get("performers", 0.0),
        "studios": components.get("studios", 0.0),
        "similar_scenes": components.get("similar_scenes", 0.0),
        "direct_history": direct_history,
        "metadata_coverage": metadata_coverage,
    }
    # Axis -> the underlying model component key(s) that prove evidence exists.
    evidence_keys = {
        "content": ("content",),
        "performers": ("performer_identity", "performer_similarity"),
        "studios": ("studio",),
        "similar_scenes": ("content_neighbor",),
        "direct_history": ("direct",),
        "metadata_coverage": (),
    }
    for key, label in FINGERPRINT_AXES:
        raw = values[key]
        present = key == "metadata_coverage" or any(
            _component_has_evidence(score, component) for component in evidence_keys[key]
        )
        axes[key] = {
            "label": label,
            "strength": _clamp(abs(raw), 0.0, 1.0),
            "tone": FINGERPRINT_TONES[key],
            "present": present,
        }
    return {"axes": axes}


def _components_rows(score: ModelSceneScore) -> list[dict[str, object]]:
    """Named, scaled breakdown rows with real units (0..1 bars).

    Novelty is NOT a model component and is not listed here; it exists only
    as lane context (adventure/discover) and is surfaced by lane_context.
    """
    content = _clamp(abs(_component_value(score, "content")), 0.0, 1.0)
    performers = _clamp(
        abs(
            _component_value(score, "performer_identity")
            + _component_value(score, "performer_similarity")
        ),
        0.0,
        1.0,
    )
    studio = _clamp(abs(_component_value(score, "studio")), 0.0, 1.0)
    direct = _clamp(abs(_component_value(score, "direct")), 0.0, 1.0)
    right_now = _clamp(score.current_fit, -1.0, 1.0)
    confidence = _clamp(score.confidence, 0.0, 1.0)
    return [
        {
            "key": "content_similarity",
            "label": "Content similarity",
            "value": content,
            "unit": "similarity",
        },
        {
            "key": "performer_match",
            "label": "Performer match",
            "value": performers,
            "unit": "similarity",
        },
        {"key": "studio_appeal", "label": "Studio appeal", "value": studio, "unit": "appeal"},
        {"key": "direct_feedback", "label": "Direct feedback", "value": direct, "unit": "appeal"},
        {"key": "right_now_fit", "label": "Right-now fit", "value": right_now, "unit": "appeal"},
        {"key": "confidence", "label": "Confidence", "value": confidence, "unit": "percent"},
    ]


def _ranked_reasons(reasons: tuple[Reason, ...]) -> list[Reason]:
    """Backend-owned fact ranking.

    Supports first (by descending signed strength), then cautions (negative
    reasons by descending strength), then the rest (neutral/context) — the
    ordering the frontend renders as up-to-three evidence rows and the full
    technical-details inventory.
    """
    support: list[Reason] = []
    caution: list[Reason] = []
    neutral: list[Reason] = []
    for reason in reasons:
        if reason.direction == "positive":
            support.append(reason)
        elif reason.direction == "negative":
            caution.append(reason)
        else:
            neutral.append(reason)

    def strength_key(r: Reason) -> tuple[float, str, str]:
        return (-(r.magnitude * r.confidence), r.code, str(r.subject_id or ""))

    support.sort(key=strength_key)
    caution.sort(key=strength_key)
    neutral.sort(key=strength_key)
    return [*support, *caution, *neutral]


def _lane_context(
    lane: str | None,
    subtype: str | None,
    qualification: dict[str, object],
    *,
    lane_rank: float,
) -> dict[str, object]:
    """Typed lane context — a discriminated union per lane.

    Model evidence (components/reasons) stays separate from lane_context. The
    lane callout is action-oriented: why the current lane selected the scene.
    """
    if lane is None:
        return {}
    context: dict[str, object] = {
        "lane": lane,
        "subtype": subtype,
        "rank": lane_rank,
    }
    qual = qualification or {}
    if lane == "revisit":
        context["facets"] = {
            "direct_appeal": _clamp(abs(float(qual.get("direct_appeal", 0.0) or 0.0)), 0.0, 1.0),
            "direct_confidence": _clamp(float(qual.get("direct_confidence", 0.0) or 0.0), 0.0, 1.0),
            "recovery": _clamp(float(qual.get("recovery", 0.0) or 0.0), 0.0, 1.0),
            "durable_signals": qual.get("durable_signals", []),
        }
        context["intent"] = "revisit"
    elif lane == "best_bets":
        context["facets"] = {
            "current_fit": _clamp(float(qual.get("current_fit", 0.0) or 0.0), -1.0, 1.0),
            "confidence": _clamp(float(qual.get("confidence", 0.0) or 0.0), 0.0, 1.0),
            "metadata_confidence": _clamp(
                float(qual.get("metadata_confidence", 0.0) or 0.0), 0.0, 1.0
            ),
            "relevance": _clamp(float(qual.get("relevance", 0.0) or 0.0), 0.0, 1.0),
            "corroborated": bool(qual.get("corroborated", False)),
            "direct_reliable": bool(qual.get("direct_reliable", False)),
        }
        context["intent"] = "best_bet"
    elif lane == "stretch":
        context["facets"] = {
            "anchor_features": qual.get("anchor_features", []),
            "challenged_feature": qual.get("challenged_feature"),
            "challenge_kind": qual.get("challenge_kind"),
            "anchor_strength": _clamp(
                abs(float(qual.get("anchor_strength", 0.0) or 0.0)), 0.0, 1.0
            ),
            "challenge_distance": _clamp(
                float(qual.get("challenge_distance", 0.0) or 0.0), 0.0, 1.0
            ),
        }
        context["intent"] = "challenge"
    elif lane == "blind_spots":
        context["facets"] = {
            "dark_facets": qual.get("dark_facets", []),
            "corroborating_types": qual.get("corroborating_types", 0),
        }
        context["intent"] = "coverage"
    elif lane == "dormant":
        context["facets"] = {
            "dormant_entity": qual.get("dormant_entity"),
            "days_since_played": qual.get("days_since_played"),
        }
        context["intent"] = "dormancy"
    return context


def asdict_reason(reason: Reason) -> dict[str, object]:
    """dataclasses.asdict for a Reason, preserving field order."""
    return {
        "code": reason.code,
        "direction": reason.direction,
        "magnitude": reason.magnitude,
        "confidence": reason.confidence,
        "subject_type": reason.subject_type,
        "subject_id": reason.subject_id,
        "visibility": reason.visibility,
        "provenance": reason.provenance,
        "detail": reason.detail,
        "model_id": reason.model_id,
        "feature_version": reason.feature_version,
    }


def build_v2_explanation(
    *,
    model_id: str,
    scene_id: str,
    summary: str,
    reasons: tuple[Reason, ...],
    supporting_reasons: tuple[Reason, ...],
    score: ModelSceneScore,
    lane: str | None = None,
    subtype: str | None = None,
    qualification: dict[str, object] | None = None,
    lane_rank: float | None = None,
) -> dict[str, object]:
    """Assemble the exact apiSchemaVersion 2 explanation payload."""
    del model_id, scene_id, supporting_reasons
    components = {
        "content": _clamp(abs(_component_value(score, "content")), 0.0, 1.0),
        "performers": _clamp(
            abs(
                _component_value(score, "performer_identity")
                + _component_value(score, "performer_similarity")
            ),
            0.0,
            1.0,
        ),
        "studios": _clamp(abs(_component_value(score, "studio")), 0.0, 1.0),
        "similar_scenes": _clamp(abs(_component_value(score, "content_neighbor")), 0.0, 1.0),
    }
    direct_history = _clamp(abs(_component_value(score, "direct")), 0.0, 1.0)
    metadata_coverage = _clamp(score.metadata_confidence, 0.0, 1.0)
    rank = _clamp(lane_rank if lane_rank is not None else 0.0, 0.0, 1.0)

    scores = {
        "appeal": {"value": score.appeal, "unit": "signed"},
        "current_fit": {"value": score.current_fit, "unit": "signed"},
        "confidence": {"value": score.confidence, "unit": "percent"},
        "rank": {"value": rank, "unit": "percent"},
    }
    evidence = _evidence_fingerprint(
        score,
        components,
        direct_history=direct_history,
        metadata_coverage=metadata_coverage,
    )
    return {
        "apiSchemaVersion": 2,
        "summary": summary,
        "components": _components_rows(score),
        "reasons": [asdict_reason(reason) for reason in _ranked_reasons(reasons)],
        "lane_context": _lane_context(lane, subtype, qualification or {}, lane_rank=rank),
        "scores": scores,
        "evidence_fingerprint": evidence,
    }
