"""Bounded direct-evidence and cooldown curves."""

from __future__ import annotations

import math

from curator.config import DEFAULT_CONFIG, ModelConfig


def direct_confidence(
    effective_evidence: float, *, config: ModelConfig = DEFAULT_CONFIG.model
) -> float:
    if effective_evidence < 0 or not math.isfinite(effective_evidence):
        raise ValueError("effective_evidence must be finite and non-negative")
    return 1 - math.exp(-effective_evidence / config.direct_confidence_scale)


def scene_recovery(
    days_since_played: float, *, config: ModelConfig = DEFAULT_CONFIG.model
) -> float:
    if days_since_played < 0 or not math.isfinite(days_since_played):
        raise ValueError("days_since_played must be finite and non-negative")
    exponent = -(days_since_played - config.cooldown_center_days) / config.cooldown_width_days
    return 1 / (1 + math.exp(max(-60.0, min(60.0, exponent))))


def blend_appeal(general: float, direct: float, confidence: float) -> float:
    if not all(math.isfinite(value) and -1 <= value <= 1 for value in (general, direct)):
        raise ValueError("appeal inputs must be finite and in [-1, 1]")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be finite and in [0, 1]")
    return max(-1.0, min(1.0, (1 - confidence) * general + confidence * direct))
