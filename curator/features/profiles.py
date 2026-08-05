"""Inspectable, missing-aware performer profiles and similarity."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProfileValue:
    value: float
    confidence: float


@dataclass(frozen=True)
class PerformerProfile:
    performer_id: str
    blocks: dict[str, dict[str, ProfileValue]]
    norms: dict[str, float] = field(init=False, repr=False, compare=False)
    keys: dict[str, frozenset[str]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "norms",
            {
                block: math.sqrt(sum(item.value**2 for item in values.values()))
                for block, values in self.blocks.items()
                if block not in NUMERIC_BLOCKS
            },
        )
        # Frozen key sets avoid rebuilding a set from each block dict on every
        # similarity call; the builder compares every profile against every known
        # profile, so this is the difference between tens of millions of conversions
        # and a single hash each.
        object.__setattr__(
            self, "keys", {block: frozenset(values) for block, values in self.blocks.items()}
        )


@dataclass(frozen=True)
class SimilarityResult:
    similarity: float
    block_similarities: dict[str, float]
    block_weights: dict[str, float]


NUMERIC_SCALES = {
    "height_cm": 12.0,
    "weight_kg": 15.0,
    "band_inches": 6.0,
    "cup_index": 2.0,
    "waist_inches": 7.0,
    "hip_inches": 8.0,
    "waist_to_hip": 0.12,
    "waist_to_height": 0.10,
    "hip_to_height": 0.12,
    "age_recording": 8.0,
}
NUMERIC_BLOCKS = {"measurements", "height", "age"}


def _cosine(
    left: dict[str, ProfileValue],
    right: dict[str, ProfileValue],
    left_norm: float,
    right_norm: float,
    left_keys: frozenset[str] | None = None,
    right_keys: frozenset[str] | None = None,
) -> float | None:
    # Precomputed frozensets keep the same iteration order as freshly built sets
    # (both derive from the same dict insertion order), so dot-product accumulation
    # stays bit-identical to the previous set(left) & set(right) form.
    shared = (left_keys or frozenset(left)) & (right_keys or frozenset(right))
    if not shared:
        return 0.0
    dot = 0.0
    confidence_sum = 0.0
    for key in shared:
        left_value = left[key]
        right_value = right[key]
        dot += left_value.value * right_value.value
        right_confidence = right_value.confidence
        left_confidence = left_value.confidence
        confidence_sum += (
            left_confidence if left_confidence < right_confidence else right_confidence
        )
    if left_norm == 0 or right_norm == 0:
        return None
    confidence = confidence_sum / len(shared)
    return max(0.0, min(1.0, dot / (left_norm * right_norm) * confidence))


def _numeric(
    left: dict[str, ProfileValue],
    right: dict[str, ProfileValue],
    left_keys: frozenset[str] | None = None,
    right_keys: frozenset[str] | None = None,
) -> float | None:
    shared = (left_keys or frozenset(left)) & (right_keys or frozenset(right))
    if not shared:
        return None
    values = []
    for key in sorted(shared):
        scale = NUMERIC_SCALES.get(key, 1.0)
        left_value = left[key]
        right_value = right[key]
        closeness = math.exp(-abs(left_value.value - right_value.value) / scale)
        right_confidence = right_value.confidence
        left_confidence = left_value.confidence
        values.append(
            closeness
            * (left_confidence if left_confidence < right_confidence else right_confidence)
        )
    return sum(values) / len(values)


def block_similarity(
    left: PerformerProfile,
    right: PerformerProfile,
    block: str,
) -> float | None:
    """Compare one shared block, or return None when it carries no usable evidence."""
    if block not in left.blocks or block not in right.blocks:
        return None
    if block in NUMERIC_BLOCKS:
        return _numeric(
            left.blocks[block], right.blocks[block], left.keys[block], right.keys[block]
        )
    return _cosine(
        left.blocks[block],
        right.blocks[block],
        left.norms[block],
        right.norms[block],
        left.keys[block],
        right.keys[block],
    )


def block_similarities(
    left: PerformerProfile,
    right: PerformerProfile,
    block_weights: dict[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Per-block similarities and the weights they were measured with."""
    similarities: dict[str, float] = {}
    used_weights: dict[str, float] = {}
    for block in sorted(set(left.blocks) & set(right.blocks)):
        weight = block_weights.get(block, 0.0)
        if weight <= 0:
            continue
        similarity = block_similarity(left, right, block)
        if similarity is None:
            continue
        similarities[block] = similarity
        used_weights[block] = weight
    return similarities, used_weights


def similarity_penalty(left: PerformerProfile, right: PerformerProfile) -> float:
    """Scale contradicting body evidence down; depends on no block that varies by scene."""
    penalty = 1.0
    left_cup = left.blocks.get("measurements", {}).get("cup_index")
    right_cup = right.blocks.get("measurements", {}).get("cup_index")
    if left_cup and right_cup:
        penalty *= math.exp(-0.18 * max(0.0, abs(left_cup.value - right_cup.value) - 1))
    left_aug = set(left.blocks.get("augmentation", {}))
    right_aug = set(right.blocks.get("augmentation", {}))
    if left_aug and right_aug and not left_aug & right_aug:
        penalty *= 0.65
    return penalty


def combine_similarities(
    left: PerformerProfile,
    right: PerformerProfile,
    similarities: dict[str, float],
    used_weights: dict[str, float],
) -> SimilarityResult:
    """Weight measured blocks into one score, so callers can reuse per-block work."""
    denominator = sum(used_weights.values())
    total = (
        sum(similarities[block] * used_weights[block] for block in similarities) / denominator
        if denominator
        else 0.0
    )
    return SimilarityResult(total * similarity_penalty(left, right), similarities, used_weights)


def performer_similarity(
    left: PerformerProfile,
    right: PerformerProfile,
    block_weights: dict[str, float],
) -> SimilarityResult:
    similarities, used_weights = block_similarities(left, right, block_weights)
    return combine_similarities(left, right, similarities, used_weights)
