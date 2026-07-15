"""Conservative reconstruction of sessions from Stash aggregates."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from curator.events.contracts import (
    DEFAULT_CALIBRATION,
    EventCalibration,
    NormalizedOutcome,
    OutcomeSignal,
)
from curator.events.curves import collapse_signals, o_outcome, repeat_outcome, viewing_outcome


def stable_event_id(kind: str, scene_id: str, timestamp_ms: int, ordinal: int) -> str:
    raw = f"{kind}\0{scene_id}\0{timestamp_ms}\0{ordinal}".encode()
    return f"historical-{kind}-{hashlib.sha256(raw).hexdigest()[:32]}"


@dataclass(frozen=True)
class HistoricalPlay:
    played_at_ms: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.played_at_ms < 0 or self.ordinal < 0:
            raise ValueError("historical play timestamp and ordinal must be non-negative")


@dataclass(frozen=True)
class HistoricalO:
    occurred_at_ms: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.occurred_at_ms < 0 or self.ordinal < 0:
            raise ValueError("historical O timestamp and ordinal must be non-negative")


@dataclass(frozen=True)
class ReconstructedSession:
    session_id: str
    scene_id: str
    started_at_ms: int
    ended_at_ms: int
    active_seconds: float
    confidence: float
    outcome: NormalizedOutcome | None
    matched_o: HistoricalO | None


@dataclass(frozen=True)
class StandaloneOutcome:
    event_id: str
    scene_id: str
    outcome: NormalizedOutcome


@dataclass(frozen=True)
class HistoricalReconstruction:
    sessions: tuple[ReconstructedSession, ...]
    standalone_outcomes: tuple[StandaloneOutcome, ...]


def _match_os(
    plays: tuple[HistoricalPlay, ...],
    os: tuple[HistoricalO, ...],
    window_ms: int,
) -> tuple[dict[int, HistoricalO], set[int]]:
    candidates = sorted(
        (
            (abs(play.played_at_ms - outcome.occurred_at_ms), play_index, o_index)
            for play_index, play in enumerate(plays)
            for o_index, outcome in enumerate(os)
            if abs(play.played_at_ms - outcome.occurred_at_ms) <= window_ms
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    matched_plays: dict[int, HistoricalO] = {}
    matched_os: set[int] = set()
    for _, play_index, o_index in candidates:
        if play_index in matched_plays or o_index in matched_os:
            continue
        matched_plays[play_index] = os[o_index]
        matched_os.add(o_index)
    return matched_plays, matched_os


def reconstruct_history(
    scene_id: str,
    total_play_duration_seconds: float,
    plays: tuple[HistoricalPlay, ...],
    os: tuple[HistoricalO, ...],
    *,
    calibration: EventCalibration = DEFAULT_CALIBRATION,
) -> HistoricalReconstruction:
    """Rebuild pseudo-sessions while retaining exact repeat and O timestamps."""
    if not math.isfinite(total_play_duration_seconds) or total_play_duration_seconds < 0:
        raise ValueError("total_play_duration_seconds must be non-negative")
    ordered_plays = tuple(sorted(plays, key=lambda item: (item.played_at_ms, item.ordinal)))
    ordered_os = tuple(sorted(os, key=lambda item: (item.occurred_at_ms, item.ordinal)))
    average_seconds = total_play_duration_seconds / len(ordered_plays) if ordered_plays else 0.0
    matched, matched_os = _match_os(
        ordered_plays,
        ordered_os,
        round(calibration.o_match_window_hours * 3_600_000),
    )

    sessions: list[ReconstructedSession] = []
    previous_timestamp: int | None = None
    for index, play in enumerate(ordered_plays):
        signals: list[OutcomeSignal] = []
        view = viewing_outcome(
            average_seconds,
            play.played_at_ms,
            historical_imputed=True,
            calibration=calibration,
        )
        if view:
            signals.append(view)
        if previous_timestamp is not None:
            repeat = repeat_outcome(
                (play.played_at_ms - previous_timestamp) / 3_600_000,
                play.played_at_ms,
                calibration=calibration,
            )
            if repeat:
                signals.append(repeat)
        matched_o = matched.get(index)
        if matched_o:
            signals.append(o_outcome(matched_o.occurred_at_ms, calibration=calibration))
        sessions.append(
            ReconstructedSession(
                stable_event_id("session", scene_id, play.played_at_ms, play.ordinal),
                scene_id,
                play.played_at_ms,
                play.played_at_ms + round(average_seconds * 1000),
                average_seconds,
                calibration.historical_view_confidence,
                collapse_signals(signals, calibration=calibration),
                matched_o,
            )
        )
        previous_timestamp = play.played_at_ms

    standalone: list[StandaloneOutcome] = []
    for index, outcome in enumerate(ordered_os):
        if index in matched_os:
            continue
        normalized = collapse_signals(
            (o_outcome(outcome.occurred_at_ms, calibration=calibration),),
            calibration=calibration,
        )
        if normalized is None:  # pragma: no cover - an O always produces one signal
            continue
        standalone.append(
            StandaloneOutcome(
                stable_event_id("o", scene_id, outcome.occurred_at_ms, outcome.ordinal),
                scene_id,
                normalized,
            )
        )
    return HistoricalReconstruction(tuple(sessions), tuple(standalone))
