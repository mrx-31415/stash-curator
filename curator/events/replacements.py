"""Quick-replacement evidence for directly observed Curator selections."""

from __future__ import annotations

import math

from curator.events.contracts import (
    DEFAULT_CALIBRATION,
    DirectSessionInput,
    EventCalibration,
    OutcomeSignal,
    SessionOrigin,
)


def quick_replacement_outcome(
    original: DirectSessionInput,
    replacement: DirectSessionInput,
    *,
    intervening_positive_feedback: bool = False,
    resumed_active_seconds: float = 0.0,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> OutcomeSignal | None:
    """Return modest negative evidence when a short Curator choice is replaced."""
    if not math.isfinite(resumed_active_seconds) or resumed_active_seconds < 0:
        raise ValueError("resumed_active_seconds must be non-negative")
    elapsed_seconds = (replacement.started_at_ms - original.ended_at_ms) / 1000
    disqualified = (
        original.origin is not SessionOrigin.CURATOR
        or original.active_seconds >= calibration.short_exit_seconds
        or replacement.scene_id == original.scene_id
        or elapsed_seconds < 0
        or elapsed_seconds > calibration.replacement_window_seconds
        or intervening_positive_feedback
        or resumed_active_seconds >= calibration.substantial_resume_seconds
    )
    if disqualified:
        return None
    return OutcomeSignal(
        "quick_replacement",
        calibration.replacement_value,
        calibration.replacement_confidence,
        replacement.started_at_ms,
        "direct_player",
    )
