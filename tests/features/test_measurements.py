import pytest

from curator.features.measurements import augmentation_category, parse_measurements


def test_measurements_normalize_dd_to_e_and_derive_ratio() -> None:
    parsed = parse_measurements("34DD-24-36")
    assert parsed is not None
    assert parsed.normalized_cup == "E"
    assert parsed.cup_index == 5
    assert parsed.waist_to_hip == pytest.approx(2 / 3)
    assert parsed.confidence < 1


def test_measurements_normalize_ddd_to_f() -> None:
    parsed = parse_measurements("32DDD-23-35")
    assert parsed is not None
    assert parsed.normalized_cup == "F"
    assert parsed.cup_index == 6


def test_invalid_or_missing_measurements_add_nothing() -> None:
    assert parse_measurements(None) is None
    assert parse_measurements("unknown") is None
    assert parse_measurements("10A-2-3") is None


def test_augmentation_is_explicitly_normalized() -> None:
    assert augmentation_category("Natural") == "natural"
    assert augmentation_category("Fake") == "augmented"
    assert augmentation_category("Unknown") is None
