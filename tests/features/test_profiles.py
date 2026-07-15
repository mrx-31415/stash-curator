from curator.features.profiles import PerformerProfile, ProfileValue, performer_similarity

WEIGHTS = {"proportions": 1.0, "eyes": 0.2, "tattoos": 0.75}


def test_missing_blocks_add_no_similarity_or_weight() -> None:
    left = PerformerProfile("left", {"proportions": {"height_cm": ProfileValue(170, 1)}})
    missing = PerformerProfile("missing", {})
    result = performer_similarity(left, missing, WEIGHTS)
    assert result.similarity == 0
    assert result.block_similarities == {}
    assert result.block_weights == {}


def test_known_category_mismatch_is_zero_while_numeric_closeness_is_smooth() -> None:
    left = PerformerProfile(
        "left",
        {
            "proportions": {"height_cm": ProfileValue(170, 1)},
            "eyes": {"eye:blue": ProfileValue(1, 1)},
        },
    )
    right = PerformerProfile(
        "right",
        {
            "proportions": {"height_cm": ProfileValue(172, 1)},
            "eyes": {"eye:brown": ProfileValue(1, 1)},
        },
    )
    result = performer_similarity(left, right, WEIGHTS)
    assert result.block_similarities["eyes"] == 0
    assert 0 < result.block_similarities["proportions"] < 1
    assert result.block_weights == {"eyes": 0.2, "proportions": 1.0}
