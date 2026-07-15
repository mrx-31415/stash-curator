"""Typed contracts shared by historical imports and direct player capture."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class SessionOrigin(StrEnum):
    """Where a directly observed session began."""

    CURATOR = "curator"
    STASH = "stash"


@dataclass(frozen=True)
class EventCalibration:
    """Central provisional calibration for normalized behavioral evidence."""

    short_exit_seconds: float = 30.0
    view_rise_seconds: float = 90.0
    view_positive_max: float = 0.35
    direct_short_exit_min: float = -0.10
    direct_view_confidence: float = 0.80
    historical_view_confidence: float = 0.45
    repeat_base: float = 0.55
    repeat_tau_hours: float = 6.0
    repeat_confidence: float = 0.80
    o_value: float = 1.0
    o_confidence: float = 1.0
    thumb_up_value: float = 0.90
    thumb_down_value: float = -1.0
    explicit_feedback_confidence: float = 1.0
    agreement_confidence_bonus: float = 0.05
    replacement_window_seconds: float = 300.0
    replacement_value: float = -0.25
    replacement_confidence: float = 0.90
    substantial_resume_seconds: float = 30.0
    o_match_window_hours: float = 6.0

    def __post_init__(self) -> None:
        positive = (
            self.short_exit_seconds,
            self.view_rise_seconds,
            self.repeat_tau_hours,
            self.replacement_window_seconds,
            self.substantial_resume_seconds,
            self.o_match_window_hours,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("time calibration values must be positive")
        bounded = (
            self.view_positive_max,
            -self.direct_short_exit_min,
            self.direct_view_confidence,
            self.historical_view_confidence,
            self.repeat_base,
            self.repeat_confidence,
            self.o_value,
            self.o_confidence,
            self.thumb_up_value,
            -self.thumb_down_value,
            self.explicit_feedback_confidence,
            self.agreement_confidence_bonus,
            -self.replacement_value,
            self.replacement_confidence,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in bounded):
            raise ValueError("outcome and confidence calibration values must be in [0, 1]")


DEFAULT_CALIBRATION = EventCalibration()


@dataclass(frozen=True)
class PlayedRange:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.start_seconds)
            or not math.isfinite(self.end_seconds)
            or self.start_seconds < 0
            or self.end_seconds < self.start_seconds
        ):
            raise ValueError("played range must be non-negative and ordered")


@dataclass(frozen=True)
class DirectSessionInput:
    """Compact, record-first contract for a direct Stash web-player session."""

    session_id: str
    scene_id: str
    started_at_ms: int
    ended_at_ms: int
    active_seconds: float
    origin: SessionOrigin
    source_route: str
    start_position_seconds: float
    maximum_position_seconds: float
    final_position_seconds: float
    played_ranges: tuple[PlayedRange, ...] = ()
    seek_destinations_seconds: tuple[float, ...] = ()
    nearby_marker_ids: tuple[str, ...] = ()
    natural_completion: bool = False
    impression_id: str | None = None
    lane: str | None = None
    impression_position: int | None = None
    model_id: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id or not self.scene_id:
            raise ValueError("session_id and scene_id are required")
        if self.started_at_ms < 0 or self.ended_at_ms < self.started_at_ms:
            raise ValueError("session timestamps must be non-negative and ordered")
        positions = (
            self.active_seconds,
            self.start_position_seconds,
            self.maximum_position_seconds,
            self.final_position_seconds,
            *self.seek_destinations_seconds,
        )
        if any(not math.isfinite(value) or value < 0 for value in positions):
            raise ValueError("session durations and positions must be non-negative")
        if self.impression_position is not None and self.impression_position < 0:
            raise ValueError("impression_position must be non-negative")
        if self.origin is SessionOrigin.CURATOR and self.impression_id is None:
            raise ValueError("Curator-originated sessions require an impression_id")


@dataclass(frozen=True)
class OutcomeSignal:
    """One candidate label observed during a viewing occasion."""

    signal_type: str
    value: float
    confidence: float
    observed_at_ms: int
    provenance: str

    def __post_init__(self) -> None:
        if not self.signal_type or not self.provenance:
            raise ValueError("signal type and provenance are required")
        if not math.isfinite(self.value) or not -1 <= self.value <= 1:
            raise ValueError("signal value must be in [-1, 1]")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("signal confidence must be in [0, 1]")
        if self.observed_at_ms < 0:
            raise ValueError("signal timestamp must be non-negative")


@dataclass(frozen=True)
class NormalizedOutcome:
    """The strongest bounded label for one viewing occasion."""

    value: float
    confidence: float
    primary_signal: str
    observed_at_ms: int
    provenance: str
    supporting_signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.primary_signal or not self.provenance:
            raise ValueError("primary signal and provenance are required")
        if not math.isfinite(self.value) or not -1 <= self.value <= 1:
            raise ValueError("outcome value must be in [-1, 1]")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("outcome confidence must be in [0, 1]")
        if self.observed_at_ms < 0:
            raise ValueError("outcome timestamp must be non-negative")
