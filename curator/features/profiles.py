"""Inspectable, missing-aware performer profiles and similarity."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileValue:
    value: float
    confidence: float


@dataclass(frozen=True)
class PerformerProfile:
    performer_id: str
    blocks: dict[str, dict[str, ProfileValue]]


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


def _cosine(left: dict[str, ProfileValue], right: dict[str, ProfileValue]) -> float | None:
    shared = set(left) & set(right)
    if not shared:
        return 0.0
    dot = sum(left[key].value * right[key].value for key in shared)
    left_norm = math.sqrt(sum(item.value**2 for item in left.values()))
    right_norm = math.sqrt(sum(item.value**2 for item in right.values()))
    if left_norm == 0 or right_norm == 0:
        return None
    confidence = sum(min(left[key].confidence, right[key].confidence) for key in shared) / len(
        shared
    )
    return max(0.0, min(1.0, dot / (left_norm * right_norm) * confidence))


def _numeric(left: dict[str, ProfileValue], right: dict[str, ProfileValue]) -> float | None:
    shared = set(left) & set(right)
    if not shared:
        return None
    values = []
    for key in sorted(shared):
        scale = NUMERIC_SCALES.get(key, 1.0)
        closeness = math.exp(-abs(left[key].value - right[key].value) / scale)
        values.append(closeness * min(left[key].confidence, right[key].confidence))
    return sum(values) / len(values)


def performer_similarity(
    left: PerformerProfile,
    right: PerformerProfile,
    block_weights: dict[str, float],
) -> SimilarityResult:
    similarities: dict[str, float] = {}
    used_weights: dict[str, float] = {}
    numeric_blocks = {"measurements", "height", "age"}
    for block in sorted(set(left.blocks) & set(right.blocks)):
        weight = block_weights.get(block, 0.0)
        if weight <= 0:
            continue
        similarity = (
            _numeric(left.blocks[block], right.blocks[block])
            if block in numeric_blocks
            else _cosine(left.blocks[block], right.blocks[block])
        )
        if similarity is None:
            continue
        similarities[block] = similarity
        used_weights[block] = weight
    denominator = sum(used_weights.values())
    total = (
        sum(similarities[block] * used_weights[block] for block in similarities) / denominator
        if denominator
        else 0.0
    )
    return SimilarityResult(total, similarities, used_weights)
