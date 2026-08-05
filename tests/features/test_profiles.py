from unittest.mock import Mock

import pytest

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


def test_cosine_via_cached_keys_matches_fresh_set_math() -> None:
    left = PerformerProfile(
        "left",
        {"eyes": {"eye:blue": ProfileValue(1, 0.9), "eye:brown": ProfileValue(0.2, 0.7)}},
    )
    right = PerformerProfile(
        "right",
        {"eyes": {"eye:blue": ProfileValue(0.8, 0.8), "eye:green": ProfileValue(1, 1)}},
    )
    cached = profiles_module.block_similarity(left, right, "eyes")
    shared = set(left.blocks["eyes"]) & set(right.blocks["eyes"])
    assert shared == {"eye:blue"}
    dot = sum(left.blocks["eyes"][key].value * right.blocks["eyes"][key].value for key in shared)
    confidence = sum(
        min(left.blocks["eyes"][key].confidence, right.blocks["eyes"][key].confidence)
        for key in shared
    ) / len(shared)
    expected = max(
        0.0,
        min(1.0, dot / (left.norms["eyes"] * right.norms["eyes"]) * confidence),
    )
    assert cached == pytest.approx(expected, rel=1e-12)


def test_cosine_norms_are_computed_once(monkeypatch) -> None:
    sqrt = Mock(wraps=profiles_module.math.sqrt)
    monkeypatch.setattr(profiles_module.math, "sqrt", sqrt)
    profile = PerformerProfile("profile", {"eyes": {"eye:blue": ProfileValue(1, 1)}})

    performer_similarity(profile, profile, WEIGHTS)
    performer_similarity(profile, profile, WEIGHTS)

    assert sqrt.call_count == 1


def test_reusing_block_work_matches_measuring_every_block() -> None:
    """Expand caches the scene-independent blocks; the split must not move the score."""
    weights = {**WEIGHTS, "age": 0.6, "ethnicity": 0.8}
    anchor = PerformerProfile(
        "anchor",
        {
            "measurements": {
                "cup_index": ProfileValue(4, 1),
                "waist_inches": ProfileValue(25, 1),
            },
            "height": {"height_cm": ProfileValue(170, 1)},
            "ethnicity": {"ethnicity:white": ProfileValue(1, 0.9)},
            "augmentation": {"augmented": ProfileValue(1, 1)},
            "age": {"age_recording": ProfileValue(29.5, 0.9)},
        },
    )
    undated_blocks = {
        "measurements": {"cup_index": ProfileValue(5, 1), "waist_inches": ProfileValue(27, 1)},
        "height": {"height_cm": ProfileValue(165, 1)},
        "ethnicity": {"ethnicity:white": ProfileValue(1, 0.9)},
        "augmentation": {"natural": ProfileValue(1, 1)},
    }
    undated = PerformerProfile("candidate", undated_blocks)
    similarities, used = profiles_module.block_similarities(undated, anchor, weights)
    numerator = sum(similarities[block] * used[block] for block in similarities)
    denominator = sum(used.values())
    penalty = profiles_module.similarity_penalty(undated, anchor)

    for age in (21.0, 29.5, 44.25):
        dated = PerformerProfile(
            "candidate", {**undated_blocks, "age": {"age_recording": ProfileValue(age, 0.9)}}
        )
        age_similarity = profiles_module.block_similarity(dated, anchor, "age")
        assert age_similarity is not None
        reused = (numerator + age_similarity * weights["age"]) / (denominator + weights["age"])
        direct = performer_similarity(dated, anchor, weights)

        assert reused * penalty == direct.similarity
        assert (
            profiles_module.combine_similarities(
                dated,
                anchor,
                {**similarities, "age": age_similarity},
                {**used, "age": weights["age"]},
            )
            == direct
        )


def test_block_work_split_handles_a_missing_age_block() -> None:
    anchor = PerformerProfile("anchor", {"height": {"height_cm": ProfileValue(170, 1)}})
    ageless = PerformerProfile("candidate", {"height": {"height_cm": ProfileValue(168, 1)}})
    similarities, used = profiles_module.block_similarities(
        ageless, anchor, {**WEIGHTS, "age": 0.6}
    )

    assert profiles_module.block_similarity(ageless, anchor, "age") is None
    assert profiles_module.combine_similarities(
        ageless, anchor, similarities, used
    ) == performer_similarity(ageless, anchor, {**WEIGHTS, "age": 0.6})
