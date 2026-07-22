from unittest.mock import Mock

import curator.features.profiles as profiles_module
from curator.features.profiles import PerformerProfile, ProfileValue, performer_similarity

WEIGHTS = {
    "measurements": 1.0,
    "augmentation": 0.9,
    "height": 0.7,
    "eyes": 0.1,
    "tattoos": 0.35,
}


def test_missing_blocks_add_no_similarity_or_weight() -> None:
    left = PerformerProfile("left", {"height": {"height_cm": ProfileValue(170, 1)}})
    missing = PerformerProfile("missing", {})
    result = performer_similarity(left, missing, WEIGHTS)
    assert result.similarity == 0
    assert result.block_similarities == {}
    assert result.block_weights == {}


def test_known_category_mismatch_is_zero_while_numeric_closeness_is_smooth() -> None:
    left = PerformerProfile(
        "left",
        {
            "height": {"height_cm": ProfileValue(170, 1)},
            "eyes": {"eye:blue": ProfileValue(1, 1)},
        },
    )
    right = PerformerProfile(
        "right",
        {
            "height": {"height_cm": ProfileValue(172, 1)},
            "eyes": {"eye:brown": ProfileValue(1, 1)},
        },
    )
    result = performer_similarity(left, right, WEIGHTS)
    assert result.block_similarities["eyes"] == 0
    assert 0 < result.block_similarities["height"] < 1
    assert result.block_weights == {"eyes": 0.1, "height": 0.7}


def test_cup_and_augmentation_conflicts_reduce_similarity() -> None:
    close = PerformerProfile(
        "close",
        {
            "measurements": {"cup_index": ProfileValue(4, 1)},
            "augmentation": {"augmented": ProfileValue(1, 1)},
        },
    )
    conflict = PerformerProfile(
        "conflict",
        {
            "measurements": {"cup_index": ProfileValue(0, 1)},
            "augmentation": {"natural": ProfileValue(1, 1)},
        },
    )

    assert (
        performer_similarity(close, close, WEIGHTS).similarity
        > performer_similarity(close, conflict, WEIGHTS).similarity
    )


def test_cosine_norms_are_computed_once(monkeypatch) -> None:
    sqrt = Mock(wraps=profiles_module.math.sqrt)
    monkeypatch.setattr(profiles_module.math, "sqrt", sqrt)
    profile = PerformerProfile("profile", {"eyes": {"eye:blue": ProfileValue(1, 1)}})

    performer_similarity(profile, profile, WEIGHTS)
    performer_similarity(profile, profile, WEIGHTS)

    assert sqrt.call_count == 1
