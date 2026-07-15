"""Smooth, bounded behavioral evidence curves."""

from __future__ import annotations

import math
from collections.abc import Iterable

from curator.events.contracts import (
    DEFAULT_CALIBRATION,
    EventCalibration,
    NormalizedOutcome,
    OutcomeSignal,
)


def viewing_outcome(
    active_seconds: float,
    observed_at_ms: int,
    *,
    historical_imputed: bool = False,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> OutcomeSignal | None:
    """Return bounded view evidence; imputed duration can never be negative."""
    if not math.isfinite(active_seconds) or active_seconds < 0:
        raise ValueError("active_seconds must be non-negative")
    threshold = calibration.short_exit_seconds
    if active_seconds < threshold:
        if historical_imputed:
            return None
        value = calibration.direct_short_exit_min * (1 - active_seconds / threshold)
    else:
        value = calibration.view_positive_max * (
            1 - math.exp(-(active_seconds - threshold) / calibration.view_rise_seconds)
        )
    if abs(value) < 1e-12:
        return None
    return OutcomeSignal(
        signal_type="view",
        value=value,
        confidence=(
            calibration.historical_view_confidence
            if historical_imputed
            else calibration.direct_view_confidence
        ),
        observed_at_ms=observed_at_ms,
        provenance="historical_imputed" if historical_imputed else "direct_player",
    )


def repeat_independence(
    gap_hours: float, *, calibration: EventCalibration = DEFAULT_CALIBRATION
) -> float:
    """Discount clustered returns smoothly without calendar boundaries."""
    if not math.isfinite(gap_hours) or gap_hours < 0:
        raise ValueError("gap_hours must be non-negative")
    return 1 - math.exp(-gap_hours / calibration.repeat_tau_hours)


def repeat_outcome(
    gap_hours: float,
    observed_at_ms: int,
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> OutcomeSignal | None:
    value = calibration.repeat_base * repeat_independence(gap_hours, calibration=calibration)
    if value <= 0:
        return None
    return OutcomeSignal(
        "repeat",
        value,
        calibration.repeat_confidence,
        observed_at_ms,
        "source_play_history",
    )


def o_outcome(
    observed_at_ms: int, *, calibration: EventCalibration = DEFAULT_CALIBRATION
) -> OutcomeSignal:
    return OutcomeSignal(
        "o",
        calibration.o_value,
        calibration.o_confidence,
        observed_at_ms,
        "source_o_history",
    )


def thumb_outcome(
    positive: bool,
    observed_at_ms: int,
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> OutcomeSignal:
    return OutcomeSignal(
        "thumb_up" if positive else "thumb_down",
        calibration.thumb_up_value if positive else calibration.thumb_down_value,
        calibration.explicit_feedback_confidence,
        observed_at_ms,
        "explicit_feedback",
    )


def collapse_signals(
    signals: Iterable[OutcomeSignal],
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> NormalizedOutcome | None:
    """Select rather than sum correlated signals from one occasion."""
    candidates = tuple(signals)
    if not candidates:
        return None
    primary = max(candidates, key=lambda item: (abs(item.value), item.observed_at_ms))
    supporting = tuple(
        item.signal_type
        for item in candidates
        if item is not primary and item.value * primary.value > 0
    )
    confidence = primary.confidence
    if supporting:
        confidence = min(1.0, confidence + calibration.agreement_confidence_bonus)
    return NormalizedOutcome(
        primary.value,
        confidence,
        primary.signal_type,
        primary.observed_at_ms,
        primary.provenance,
        supporting,
    )
