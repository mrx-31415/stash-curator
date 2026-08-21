"""Versioned, user-facing score and evidence presentation data."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from curator.model import ModelSceneScore

_COMPONENT_SPECS = (
    ("content_similarity", "Content similarity", "-1..1"),
    ("performer_match", "Performer match", "-1..1"),
    ("studio_appeal", "Studio appeal", "-1..1"),
    ("direct_feedback", "Direct feedback", "-1..1"),
    ("right_now_fit", "Right now", "-1..1"),
)

_REASON_LABELS = {
    "direct.positive": "Direct positive history",
    "direct.negative": "Direct negative history",
    "direct.residual": "Direct history adjustment",
    "appeal.performer_identity": "Performer match",
    "appeal.performer_similar": "Similar performer profile",
    "appeal.studio": "Studio appeal",
    "appeal.content_neighbor": "Similar scenes",
    "appeal.tag_positive": "Familiar content pattern",
    "appeal.tag_negative": "Less familiar content pattern",
    "appeal.tag_declared_positive": "Declared positive content preference",
    "appeal.tag_declared_negative": "Declared negative content preference",
    "fit.cooldown": "Scene cooldown",
    "fit.satiation": "Recent repetition",
    "fit.not_now": "Not now feedback",
    "eligibility.lane": "Eligible for this lane",
    "explore.challenge": "Lane challenge",
    "explore.coverage": "Library coverage gap",
    "dormant.entity": "Dormant preference",
}


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _direction(value: float) -> str:
    return "positive" if value > 1e-9 else "negative" if value < -1e-9 else "neutral"


def _family_value(components: dict[str, object], name: str) -> float:
    value = components.get(name)
    if not isinstance(value, dict):
        return 0.0
    if name == "fit":
        return sum(_number(value.get(key)) for key in ("cooldown", "satiation", "not_now"))
    return _number(value.get("value"))


def _component(
    name: str,
    label: str,
    value: float,
    scale: str,
    confidence: float,
    *,
    available: bool = True,
    detail: str = "",
) -> dict[str, object]:
    value = _clamp(value)
    result: dict[str, object] = {
        "name": name,
        "label": label,
        "value": value,
        "scale": scale,
        "direction": _direction(value),
        "confidence": max(0.0, min(1.0, confidence)),
        "available": available,
    }
    if detail:
        result["detail"] = detail
    return result


def score_components(score: ModelSceneScore) -> list[dict[str, object]]:
    """Map stored model families to stable, plain-language rows."""
    raw = score.components
    content = _family_value(raw, "content") + _family_value(raw, "content_neighbor")
    performer = _family_value(raw, "performer_identity") + _family_value(
        raw, "performer_similarity"
    )
    studio = _family_value(raw, "studio")
    direct = _number(score.direct_appeal)
    fit = _family_value(raw, "fit")
    confidence = max(0.0, min(1.0, score.confidence))
    values = {
        "content_similarity": ("Content similarity", content, "-1..1"),
        "performer_match": ("Performer match", performer, "-1..1"),
        "studio_appeal": ("Studio appeal", studio, "-1..1"),
        "direct_feedback": ("Direct feedback", direct, "-1..1"),
        "right_now_fit": ("Right now", fit, "-1..1"),
    }
    rows = [
        _component(name, label, value, scale, confidence, available=abs(value) > 1e-9)
        for name, (label, value, scale) in values.items()
    ]
    rows.append(
        {
            "name": "model_confidence",
            "label": "Model confidence",
            "value": confidence,
            "scale": "0..1",
            "direction": "neutral",
            "confidence": confidence,
            "available": True,
        }
    )
    return rows


def _axis(
    name: str, value: float, confidence: float, *, available: bool = True
) -> dict[str, object]:
    value = max(-1.0, min(1.0, value))
    return {
        "name": name,
        "support": max(0.0, min(1.0, value)),
        "caution": max(0.0, min(1.0, -value)),
        "confidence": max(0.0, min(1.0, confidence)),
        "available": available,
    }


def evidence_fingerprint(score: ModelSceneScore) -> dict[str, object]:
    raw = score.components
    content = _family_value(raw, "content") + _family_value(raw, "content_neighbor")
    performer = _family_value(raw, "performer_identity") + _family_value(
        raw, "performer_similarity"
    )
    studio = _family_value(raw, "studio")
    direct = _number(score.direct_appeal)
    neighbor = _family_value(raw, "content_neighbor")
    return {
        "version": 1,
        "axes": [
            _axis("content", content, score.confidence, available=abs(content) > 1e-9),
            _axis("performers", performer, score.confidence, available=abs(performer) > 1e-9),
            _axis("studios", studio, score.confidence, available=abs(studio) > 1e-9),
            _axis("similar_scenes", neighbor, score.confidence, available=abs(neighbor) > 1e-9),
            _axis(
                "direct_history",
                direct,
                score.direct_confidence,
                available=score.direct_confidence > 0,
            ),
        ],
        "metadata_coverage": {
            "available": score.metadata_confidence > 1e-9,
            "value": max(0.0, min(1.0, score.metadata_confidence)),
            "scale": "0..1",
        },
        "confidence": max(0.0, min(1.0, score.confidence)),
    }


def reason_label(code: str) -> str:
    if code in _REASON_LABELS:
        return _REASON_LABELS[code]
    fallback = code.rsplit(".", 1)[-1].replace("_", " ")
    return fallback[:1].upper() + fallback[1:]


def evidence_rows(reasons: Iterable[Any]) -> list[dict[str, object]]:
    """Return up to three material facts, preserving backend ranking."""
    candidates = [
        reason
        for reason in reasons
        if not str(reason.code).startswith(("eligibility.", "diversity."))
        and str(reason.code) != "fallback"
        and abs(float(reason.magnitude)) > 1e-9
    ]
    candidates.sort(key=lambda reason: (-float(reason.magnitude), str(reason.code)))
    return [
        {
            "code": reason.code,
            "label": reason_label(reason.code),
            "direction": reason.direction,
            "magnitude": float(reason.magnitude),
            "confidence": float(reason.confidence),
            "detail": reason.detail,
        }
        for reason in candidates[:3]
    ]


def scores_payload(
    score: ModelSceneScore, *, lane: str | None = None, rank: float | None = None
) -> dict[str, object]:
    return {
        "appeal": {
            "label": "Appeal",
            "value": score.appeal,
            "scale": "-1..1",
            "direction": _direction(score.appeal),
        },
        "current_fit": {
            "label": "Current fit",
            "value": score.current_fit,
            "scale": "-1..1",
            "direction": _direction(score.current_fit),
        },
        "confidence": {
            "label": "Model confidence",
            "value": score.confidence,
            "scale": "0..1",
            "direction": "neutral",
        },
        "rank": {
            "label": f"Rank in {lane.replace('_', ' ').title()}" if lane else "Lane rank",
            "value": rank,
            "scale": "0..1",
            "relative": True,
            "lane": lane,
            "available": lane is not None and rank is not None,
        },
    }


def lane_context_payload(item: Any | None) -> dict[str, object]:
    if item is None:
        return {"available": False, "display_lane": None, "source_lane": None, "subtype": None}
    return {
        "available": True,
        "display_lane": item.lane,
        "source_lane": item.source_lane,
        "subtype": item.subtype,
        "qualification": item.qualification,
    }
