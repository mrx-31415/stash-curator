import pytest

from curator.events.historical import HistoricalO, HistoricalPlay, reconstruct_history

HOUR_MS = 3_600_000


def test_reconstruction_imputes_duration_but_keeps_exact_repeat_timing() -> None:
    plays = (HistoricalPlay(HOUR_MS, 0), HistoricalPlay(13 * HOUR_MS, 0))
    os = (HistoricalO(HOUR_MS + 1_000, 0),)

    result = reconstruct_history("scene-1", 600, plays, os)

    assert len(result.sessions) == 2
    assert {session.active_seconds for session in result.sessions} == {300}
    assert result.sessions[0].matched_o == os[0]
    assert result.sessions[0].outcome is not None
    assert result.sessions[0].outcome.primary_signal == "o"
    assert result.sessions[1].outcome is not None
    assert result.sessions[1].outcome.primary_signal == "repeat"
    assert result.standalone_outcomes == ()


def test_short_imputed_average_is_unknown_not_a_negative_exit() -> None:
    result = reconstruct_history("scene-1", 10, (HistoricalPlay(HOUR_MS, 0),), ())
    assert len(result.sessions) == 1
    assert result.sessions[0].active_seconds == 10
    assert result.sessions[0].outcome is None


def test_unmatched_o_is_preserved_as_exact_standalone_success() -> None:
    result = reconstruct_history(
        "scene-1",
        10,
        (HistoricalPlay(HOUR_MS, 0),),
        (HistoricalO(20 * HOUR_MS, 0),),
    )
    assert result.sessions[0].matched_o is None
    assert len(result.standalone_outcomes) == 1
    assert result.standalone_outcomes[0].outcome.value == 1
    assert result.standalone_outcomes[0].outcome.confidence == 1


def test_o_matching_is_nearest_and_one_to_one() -> None:
    result = reconstruct_history(
        "scene-1",
        120,
        (HistoricalPlay(10 * HOUR_MS, 0),),
        (HistoricalO(9 * HOUR_MS, 0), HistoricalO(10 * HOUR_MS + 1, 0)),
    )
    assert result.sessions[0].matched_o == HistoricalO(10 * HOUR_MS + 1, 0)
    assert len(result.standalone_outcomes) == 1


def test_invalid_source_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        reconstruct_history("scene-1", -1, (), ())
