import math

import pytest

from curator.events.contracts import OutcomeSignal
from curator.events.curves import (
    collapse_signals,
    o_outcome,
    repeat_independence,
    repeat_outcome,
    thumb_outcome,
    viewing_outcome,
)


def test_direct_view_curve_has_smooth_neutral_crossing_and_saturation() -> None:
    immediate = viewing_outcome(0, 1)
    almost_neutral = viewing_outcome(29, 1)
    neutral = viewing_outcome(30, 1)
    short_meaningful = viewing_outcome(60, 1)
    saturated = viewing_outcome(600, 1)
    very_long = viewing_outcome(60_000, 1)

    assert immediate is not None and immediate.value == pytest.approx(-0.10)
    assert almost_neutral is not None and -0.01 < almost_neutral.value < 0
    assert neutral is None
    assert short_meaningful is not None and short_meaningful.value == pytest.approx(
        0.0992, abs=0.001
    )
    assert saturated is not None and saturated.value > 0.34
    assert very_long is not None and very_long.value <= 0.35


def test_imputed_view_duration_never_creates_negative_evidence() -> None:
    assert viewing_outcome(0, 1, historical_imputed=True) is None
    assert viewing_outcome(29.999, 1, historical_imputed=True) is None
    positive = viewing_outcome(60, 1, historical_imputed=True)
    assert positive is not None
    assert positive.value > 0
    assert positive.confidence == 0.45


def test_repeat_independence_is_smooth_and_bounded() -> None:
    assert repeat_independence(0) == 0
    assert repeat_independence(6) == pytest.approx(1 - math.exp(-1))
    assert repeat_independence(10_000) == pytest.approx(1)
    assert repeat_outcome(0, 1) is None
    independent = repeat_outcome(24, 1)
    assert independent is not None and 0 < independent.value < 0.55
    with pytest.raises(ValueError, match="non-negative"):
        repeat_independence(-1)


def test_one_occasion_selects_strongest_signal_instead_of_summing() -> None:
    view = viewing_outcome(600, 100)
    repeat = repeat_outcome(24, 100)
    assert view is not None and repeat is not None

    outcome = collapse_signals((view, repeat, o_outcome(100)))

    assert outcome is not None
    assert outcome.value == 1
    assert outcome.primary_signal == "o"
    assert outcome.confidence == 1
    assert set(outcome.supporting_signals) == {"view", "repeat"}


def test_equal_strength_direct_signal_uses_the_latest_observation() -> None:
    outcome = collapse_signals((o_outcome(100), thumb_outcome(False, 200)))
    assert outcome is not None
    assert outcome.value == -1
    assert outcome.primary_signal == "thumb_down"


def test_supporting_agreement_only_raises_confidence_not_value() -> None:
    primary = OutcomeSignal("primary", 0.4, 0.6, 100, "test")
    support = OutcomeSignal("support", 0.2, 0.7, 100, "test")
    outcome = collapse_signals((primary, support))
    assert outcome is not None
    assert outcome.value == 0.4
    assert outcome.confidence == pytest.approx(0.65)
