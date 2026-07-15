from dataclasses import replace
from typing import Any

import pytest

from curator.events import DirectSessionInput, PlayedRange, SessionOrigin
from curator.events.replacements import quick_replacement_outcome


def _session(
    scene_id: str,
    start_ms: int,
    active_seconds: float,
    *,
    origin: SessionOrigin = SessionOrigin.STASH,
) -> DirectSessionInput:
    return DirectSessionInput(
        session_id=f"session-{scene_id}",
        scene_id=scene_id,
        started_at_ms=start_ms,
        ended_at_ms=start_ms + round(active_seconds * 1000),
        active_seconds=active_seconds,
        origin=origin,
        source_route="/scenes/test",
        start_position_seconds=0,
        maximum_position_seconds=active_seconds,
        final_position_seconds=active_seconds,
        played_ranges=(PlayedRange(0, active_seconds),),
        impression_id="impression-1" if origin is SessionOrigin.CURATOR else None,
    )


def test_quick_replacement_is_modest_negative_for_short_curator_choice() -> None:
    original = _session("one", 0, 20, origin=SessionOrigin.CURATOR)
    replacement = _session("two", original.ended_at_ms + 60_000, 10)
    outcome = quick_replacement_outcome(original, replacement)
    assert outcome is not None
    assert outcome.value == -0.25


@pytest.mark.parametrize(
    ("change", "kwargs"),
    [
        ({"origin": SessionOrigin.STASH, "impression_id": None}, {}),
        ({"active_seconds": 30}, {}),
        ({}, {"intervening_positive_feedback": True}),
        ({}, {"resumed_active_seconds": 30}),
    ],
)
def test_replacement_disqualifiers(change: dict[str, Any], kwargs: dict[str, Any]) -> None:
    original = replace(_session("one", 0, 20, origin=SessionOrigin.CURATOR), **change)
    replacement = _session("two", original.ended_at_ms + 60_000, 10)
    assert quick_replacement_outcome(original, replacement, **kwargs) is None


def test_replacement_must_be_different_and_within_five_minutes() -> None:
    original = _session("one", 0, 20, origin=SessionOrigin.CURATOR)
    same = _session("one", original.ended_at_ms + 1, 10)
    late = _session("two", original.ended_at_ms + 300_001, 10)
    boundary = _session("two", original.ended_at_ms + 300_000, 10)
    assert quick_replacement_outcome(original, same) is None
    assert quick_replacement_outcome(original, late) is None
    assert quick_replacement_outcome(original, boundary) is not None


def test_direct_session_contract_rejects_invalid_context() -> None:
    with pytest.raises(ValueError, match="impression_id"):
        _session("one", 0, 10, origin=SessionOrigin.CURATOR).__class__(
            session_id="invalid",
            scene_id="one",
            started_at_ms=0,
            ended_at_ms=1,
            active_seconds=1,
            origin=SessionOrigin.CURATOR,
            source_route="/",
            start_position_seconds=0,
            maximum_position_seconds=1,
            final_position_seconds=1,
        )
