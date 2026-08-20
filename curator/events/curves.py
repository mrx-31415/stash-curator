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


def _logit_probability(coefficients: tuple[float, float, float], seconds: float) -> float:
    log_t = math.log(seconds)
    z = coefficients[0] + coefficients[1] * log_t + coefficients[2] * log_t * log_t
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def view_rise(
    active_seconds: float,
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
    view_curve: tuple[float, float, float] | None = None,
) -> float:
    """The positive limb of the view curve, in [0, view_positive_max].

    Without a fitted curve this is the shipped exponential rise.

    With one, the value is the fitted return probability as a fraction of its
    value at the peak. That keeps the output range exactly as shipped -- the
    peak scores `view_positive_max` and nothing exceeds it -- while staying
    strictly positive, so ordering is preserved all the way out into the tail.

    Anchoring anywhere other than the peak was tried and rejected. Subtracting
    the probability at the short-exit threshold, or at the far edge of a
    bounded domain, drives everything past some duration to exactly zero, and
    `viewing_outcome` drops a signal that rounds to zero. Measured on a real
    library the threshold anchor erased 56% of view labels above the threshold
    -- a large, silent loss in the one quantity this model is most short of.

    The consequence is a step at the threshold: the cliff below it ends at zero
    while the fitted curve starts well above it. That reflects the measurement
    rather than hiding it -- the return rate roughly triples between the 15-30s
    and 30-60s buckets -- but it does make the threshold load-bearing, which
    matters most for imputed durations, since those are averages reconstructed
    from Stash history rather than measured directly.
    """
    threshold = calibration.short_exit_seconds
    shipped = calibration.view_positive_max * (
        1 - math.exp(-(active_seconds - threshold) / calibration.view_rise_seconds)
    )
    if view_curve is None:
        return shipped
    curvature = view_curve[2]
    if curvature >= 0.0:
        return shipped
    peak_seconds = math.exp(-view_curve[1] / (2.0 * curvature))
    if peak_seconds <= threshold:
        return shipped
    at_peak = _logit_probability(view_curve, peak_seconds)
    if at_peak < 1e-9:
        return shipped
    scaled = _logit_probability(view_curve, active_seconds) / at_peak
    if scaled > 1.0:
        scaled = 1.0
    return calibration.view_positive_max * scaled


def viewing_outcome(
    active_seconds: float,
    observed_at_ms: int,
    *,
    historical_imputed: bool = False,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
    view_curve: tuple[float, float, float] | None = None,
) -> OutcomeSignal | None:
    """Return bounded view evidence; imputed duration can never be negative."""
    if not math.isfinite(active_seconds) or active_seconds < 0:
        raise ValueError("active_seconds must be non-negative")
    threshold = calibration.short_exit_seconds
    if active_seconds < threshold:
        if historical_imputed:
            return None
        # The fitted curve is too generous below the threshold -- a quadratic
        # cannot fall fast enough at the left edge while also fitting the peak
        # and the tail -- so the short-exit cliff is kept as shipped and only
        # the rise above it is replaced.
        value = calibration.direct_short_exit_min * (1 - active_seconds / threshold)
    else:
        value = view_rise(active_seconds, calibration=calibration, view_curve=view_curve)
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
