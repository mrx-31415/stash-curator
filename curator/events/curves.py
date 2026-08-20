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


def _log_odds(coefficients: tuple[float, ...], seconds: float) -> float:
    log_t = math.log(seconds)
    return coefficients[0] + coefficients[1] * log_t + coefficients[2] * log_t * log_t


def view_value(
    active_seconds: float,
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
    view_curve: tuple[float, float, float, float] | None = None,
) -> float | None:
    """View evidence for a session duration, in [direct_short_exit_min, view_positive_max].

    Without a fitted curve this is the shipped two-piece shape: a short-exit
    cliff below `short_exit_seconds` and an exponential rise above it.

    With one, it is a single continuous function of duration, read against the
    instance's own base return rate. `view_curve` is the three fitted
    coefficients plus the logit of that base rate, and the value is how far the
    duration's predicted return probability sits from average, scaled so the
    peak reaches `view_positive_max` and the floor reaches
    `direct_short_exit_min`. The output range is unchanged.

    Three properties follow from centring on the base rate rather than on the
    threshold, and each replaced something worse:

    * There is no step. The shipped shape jumped from no evidence at 29.9s to
      near-maximum at 30.0s once the rise was refitted, because the fitted
      probability is already close to its peak by 30s. Centring removes the
      threshold from the arithmetic entirely.
    * Short plays are negative rather than absent. Measured, durations under
      the lower crossover return at a rate far below the library average
      (p < 1e-4), which is the negative evidence this model otherwise almost
      never sees.
    * Long plays abstain rather than voting. Past the peak the fitted parabola
      keeps falling, but measured return rates out there are not
      distinguishable from the base rate (p = 0.36), so the decline is the
      functional form extrapolating rather than evidence. Returning None there
      says "this duration tells us nothing", which is the honest reading.
    """
    threshold = calibration.short_exit_seconds
    if view_curve is None:
        if active_seconds < threshold:
            return calibration.direct_short_exit_min * (1 - active_seconds / threshold)
        return calibration.view_positive_max * (
            1 - math.exp(-(active_seconds - threshold) / calibration.view_rise_seconds)
        )

    if active_seconds <= 0.0:
        # A zero duration means no duration was recorded, not that the scene
        # was watched for no time: most directly observed sessions never
        # receive one, because Curator sees the start rather than the whole
        # play. Reading that as the strongest possible dislike would put the
        # floor under missing data. The shipped shape does exactly that; the
        # fitted curve abstains instead.
        return None
    curvature = view_curve[2]
    base_logit = view_curve[3]
    if curvature >= 0.0:
        return view_value(active_seconds, calibration=calibration)
    peak_seconds = math.exp(-view_curve[1] / (2.0 * curvature))
    span = _log_odds(view_curve, peak_seconds) - base_logit
    if span < 1e-9:
        return view_value(active_seconds, calibration=calibration)

    relative = (_log_odds(view_curve, active_seconds) - base_logit) / span
    if active_seconds > peak_seconds:
        # Soft clamp. Past the peak the fitted parabola keeps falling, but the
        # measured return rate out there is not distinguishable from the base
        # rate, so the fall is the functional form extrapolating rather than
        # evidence. Decaying toward `view_tail_min` says what is actually
        # supported: a long play is engagement, but it stops carrying
        # information about returning. Both branches meet at the peak with zero
        # slope in duration, because `relative` is maximized there.
        floor = calibration.view_tail_min
        decay = math.exp(min(relative, 1.0) - 1.0)
        return floor + (calibration.view_positive_max - floor) * decay
    if relative >= 0.0:
        return calibration.view_positive_max * min(relative, 1.0)
    return calibration.direct_short_exit_min * min(-relative, 1.0)


def viewing_outcome(
    active_seconds: float,
    observed_at_ms: int,
    *,
    historical_imputed: bool = False,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
    view_curve: tuple[float, float, float, float] | None = None,
) -> OutcomeSignal | None:
    """Return bounded view evidence for one session.

    Without a fitted curve an imputed duration can never be negative, as it
    always could not: the shipped shape reads a short duration as dislike, and
    an imputed duration is an average over every play of the scene rather than
    a measurement, so a low average was not something to hold against it.

    A fitted curve lifts that restriction deliberately. The evidence for the
    negative limb is strong, and imputed signals are already discounted where
    the design puts that discount -- `historical_view_confidence` is 0.45
    against a direct session's 0.80. The case the old rule protected against,
    a scene played briefly but often, is covered by `collapse_signals`: repeat
    evidence reaches 0.55 and outranks the -0.10 view floor, so the repeated
    play wins the occasion.
    """
    if not math.isfinite(active_seconds) or active_seconds < 0:
        raise ValueError("active_seconds must be non-negative")
    if (
        view_curve is None
        and historical_imputed
        and active_seconds < calibration.short_exit_seconds
    ):
        return None
    value = view_value(active_seconds, calibration=calibration, view_curve=view_curve)
    if value is None or abs(value) < 1e-12:
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
