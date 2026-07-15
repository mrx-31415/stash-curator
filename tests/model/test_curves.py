import pytest

from curator.model import blend_appeal, direct_confidence, scene_recovery


def test_direct_confidence_gives_one_strong_outcome_about_seventy_percent_control() -> None:
    assert direct_confidence(0) == 0
    assert direct_confidence(1) == pytest.approx(0.7135, abs=0.001)
    assert direct_confidence(10) > 0.999


def test_scene_recovery_matches_design_landmarks() -> None:
    assert scene_recovery(30) == pytest.approx(0.018, abs=0.005)
    assert scene_recovery(60) == pytest.approx(0.119, abs=0.005)
    assert scene_recovery(90) == pytest.approx(0.5)
    assert scene_recovery(120) == pytest.approx(0.881, abs=0.005)
    assert scene_recovery(150) == pytest.approx(0.982, abs=0.005)


def test_direct_blend_is_bounded_and_dominates_with_confidence() -> None:
    assert blend_appeal(-0.5, 1, 0) == -0.5
    assert blend_appeal(-0.5, 1, 1) == 1
    assert blend_appeal(-0.5, 1, 0.8) == pytest.approx(0.7)
