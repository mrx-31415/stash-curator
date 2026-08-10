"""Test-only numpy oracle for the compiled-core differential gate.

The compiled core is the single runtime implementation; numpy remains the
independent reference the gate pins the Go kernels against. These functions
replicate the former production numpy paths (`_content_neighbors_numpy`,
`_performer_similarity_scores_numpy`) exactly, parameterized by the builder
config so the tests can compare Go vs numpy on identical inputs. Nothing here
ships in the plugin's runtime path.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from curator import optional_deps
from curator.features import FeatureStore
from curator.model.builder import _NeighborEvidence


def content_neighbors_numpy(
    vectors: Mapping[str, Mapping[str, float]],
    labels: Mapping[str, object],
    label_mean: float,
    progress_total: int,
    *,
    min_similarity: float,
    neighbor_count: int,
    confidence_scale: float,
) -> dict[str, _NeighborEvidence]:
    """Vectorized content-neighbor evidence, mirroring the former numpy path."""
    np = optional_deps.np
    assert np is not None
    scene_ids = list(vectors)
    labeled_ids = sorted(scene_id for scene_id in labels if scene_id in vectors)
    default = _NeighborEvidence(0.0, 0.0, 0.0, 0.0, 0.0, ())
    result: dict[str, _NeighborEvidence] = {}
    if not labeled_ids:
        return {scene_id: default for scene_id in scene_ids}
    column_names = sorted({name for scene_id in labeled_ids for name in vectors[scene_id]})
    if not column_names:
        return {scene_id: default for scene_id in scene_ids}
    column_index = {name: index for index, name in enumerate(column_names)}
    labeled_position = {scene_id: column for column, scene_id in enumerate(labeled_ids)}
    labeled_values = np.zeros((len(labeled_ids), len(column_names)), dtype=np.float64)
    for column, scene_id in enumerate(labeled_ids):
        for name, value in vectors[scene_id].items():
            labeled_values[column, column_index[name]] = value
    target_values = np.zeros((len(scene_ids), len(column_names)), dtype=np.float64)
    for row, scene_id in enumerate(scene_ids):
        for name, value in vectors[scene_id].items():
            if name not in column_index:
                continue
            target_values[row, column_index[name]] = value
    labeled_conf = np.array([labels[scene_id].confidence for scene_id in labeled_ids])
    labeled_outcome = np.array([labels[scene_id].outcome for scene_id in labeled_ids])
    labeled_binary = (labeled_values != 0).astype(np.float32)
    target_binary = (target_values != 0).astype(np.float32)
    self_column = np.array([labeled_position.get(scene_id, -1) for scene_id in scene_ids])
    for start in range(0, len(scene_ids), 4096):
        end = min(start + 4096, len(scene_ids))
        similarities = target_values[start:end] @ labeled_values.T
        shared = (target_binary[start:end] @ labeled_binary.T).astype(np.float64)
        similarities *= 1.0 - np.exp(-shared / 4.0)
        weights = similarities**3 * labeled_conf[np.newaxis, :]
        valid = similarities >= min_similarity
        for local_row in range(end - start):
            own = int(self_column[start + local_row])
            if own >= 0:
                valid[local_row, own] = False
        for local_row in range(end - start):
            scene_id = scene_ids[start + local_row]
            valid_indices = np.flatnonzero(valid[local_row])
            if len(valid_indices) == 0:
                result[scene_id] = default
                continue
            row_weights = weights[local_row, valid_indices]
            chosen = min(neighbor_count, len(row_weights))
            boundary = float(
                np.partition(row_weights, len(row_weights) - chosen)[len(row_weights) - chosen]
            )
            candidates = valid_indices[row_weights >= boundary]
            evidence = [
                (
                    labeled_ids[int(column)],
                    float(similarities[local_row, int(column)]),
                    float(weights[local_row, int(column)]),
                    float(labeled_outcome[int(column)]),
                )
                for column in candidates
            ]
            evidence.sort(key=lambda item: (-item[2], item[0]))
            selected = evidence[:neighbor_count]
            result[scene_id] = _assemble_evidence(scene_id, selected, label_mean, confidence_scale)
    return result


def _assemble_evidence(
    scene_id: str,
    selected: list[tuple[str, float, float, float]],
    label_mean: float,
    confidence_scale: float,
) -> _NeighborEvidence:
    denominator = sum(item[2] for item in selected)
    outcome_mean = sum(item[2] * item[3] for item in selected) / denominator if denominator else 0.0
    lift = outcome_mean - label_mean if denominator else 0.0
    confidence = 1 - math.exp(-denominator / confidence_scale) if denominator else 0.0
    return _NeighborEvidence(
        lift * confidence,
        outcome_mean,
        lift,
        confidence,
        denominator,
        tuple(
            {
                "scene_id": item[0],
                "similarity": item[1],
                "weight": item[2],
                "outcome": item[3],
            }
            for item in selected[:5]
        ),
    )


def performer_similarity_numpy(
    connection: object,
    feature_version: str,
    scene_features: Mapping[str, object],
    affinities: Mapping[str, object],
    *,
    block_weights: Mapping[str, float],
    cutoff: float,
) -> dict[str, dict[str, object]]:
    """Vectorized performer-similarity scores, mirroring the former numpy path."""
    from curator.model.builder import PreferenceModelBuilder

    np = optional_deps.np
    assert np is not None
    identity_affinity = PreferenceModelBuilder._identity_affinity(  # type: ignore[arg-type]
        scene_features, affinities
    )
    profiles = FeatureStore(connection).performer_profiles(feature_version)  # type: ignore[arg-type]
    known = {
        key: profiles[key]
        for key, (value, _) in identity_affinity.items()
        if key in profiles and abs(value) >= cutoff
    }
    profile_ids = list(profiles)
    known_ids = list(known)
    known_position = {performer_id: column for column, performer_id in enumerate(known_ids)}
    known_affinity = np.array([identity_affinity[performer_id][0] for performer_id in known_ids])
    known_confidence = np.array([identity_affinity[performer_id][1] for performer_id in known_ids])
    block_names = sorted({block for profile in profiles.values() for block in profile.blocks})
    block_keys = {
        block: sorted(
            {key for profile in profiles.values() for key in profile.blocks.get(block, {})}
        )
        for block in block_names
    }
    values: dict[str, object] = {}
    confidences: dict[str, object] = {}
    present: dict[str, object] = {}
    for block in block_names:
        keys = block_keys[block]
        key_position = {key: column for column, key in enumerate(keys)}
        block_values = np.zeros((len(profile_ids), len(keys)), dtype=np.float64)
        block_confidences = np.zeros_like(block_values)
        block_present = np.zeros(len(profile_ids), dtype=bool)
        for row, performer_id in enumerate(profile_ids):
            entries = profiles[performer_id].blocks.get(block)
            if not entries:
                continue
            block_present[row] = True
            for key, item in entries.items():
                block_values[row, key_position[key]] = item.value
                block_confidences[row, key_position[key]] = item.confidence
        values[block] = block_values
        confidences[block] = block_confidences
        present[block] = block_present
    known_positions = np.array([profile_ids.index(performer_id) for performer_id in known_ids])
    known_values = {block: values[block][known_positions, :] for block in block_names}  # type: ignore[index]
    known_confidences = {block: confidences[block][known_positions, :] for block in block_names}  # type: ignore[index]
    known_present = {block: present[block][known_positions] for block in block_names}  # type: ignore[index]
    from curator.features.profiles import NUMERIC_BLOCKS, NUMERIC_SCALES

    numerator = np.zeros((len(profile_ids), len(known_ids)), dtype=np.float64)
    denominator = np.zeros_like(numerator)
    block_similarities: dict[str, object] = {}
    used: dict[str, object] = {}
    for block in block_names:
        weight = block_weights.get(block, 0.0)
        if weight <= 0:
            continue
        both_present = np.outer(present[block], known_present[block])  # type: ignore[index]
        if block in NUMERIC_BLOCKS:
            value = np.zeros((len(profile_ids), len(known_ids)), dtype=np.float64)
            count = np.zeros_like(value)
            for column in range(values[block].shape[1]):  # type: ignore[union-attr]
                both = np.outer(values[block][:, column] != 0, known_values[block][:, column] != 0)  # type: ignore[index]
                if not both.any():
                    continue
                scale = NUMERIC_SCALES.get(block_keys[block][column], 1.0)
                closeness = np.exp(
                    -np.abs(
                        np.subtract.outer(values[block][:, column], known_values[block][:, column])
                    )  # type: ignore[index]
                    / scale
                )
                value += (
                    closeness
                    * np.minimum.outer(
                        confidences[block][:, column],
                        known_confidences[block][:, column],  # type: ignore[index]
                    )
                    * both
                )
                count += both
            block_value = np.divide(value, count, out=np.zeros_like(value), where=count > 0)
            block_used = both_present & (count > 0)
        else:
            norms = np.array(
                [profiles[performer_id].norms.get(block, 0.0) for performer_id in profile_ids]
            )
            known_norms = norms[known_positions]
            dot = values[block] @ known_values[block].T  # type: ignore[index]
            shared = (
                (values[block] != 0).astype(np.float32)  # type: ignore[index]
                @ (known_values[block] != 0).astype(np.float32).T  # type: ignore[index]
            ).astype(np.float64)
            confidence_sum = np.zeros((len(profile_ids), len(known_ids)), dtype=np.float64)
            for column in range(values[block].shape[1]):  # type: ignore[union-attr]
                if not confidences[block][:, column].any() or not (
                    known_confidences[block][:, column].any()
                ):  # type: ignore[index]
                    continue
                confidence_sum += np.minimum.outer(
                    confidences[block][:, column],
                    known_confidences[block][:, column],  # type: ignore[index]
                )
            confidence = np.where(shared > 0, confidence_sum / shared, 0.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                block_value = np.clip(
                    dot / (norms[:, None] * known_norms[None, :]) * confidence, 0.0, 1.0
                )
            block_used = both_present & (norms[:, None] != 0) & (known_norms[None, :] != 0)
        block_similarities[block] = block_value
        used[block] = block_used
        numerator += block_value * block_used * weight
        denominator += block_used * weight
    penalty = np.ones((len(profile_ids), len(known_ids)), dtype=np.float64)
    measurements = values.get("measurements")
    if measurements is not None and measurements.shape[1]:  # type: ignore[union-attr]
        cup_position = (
            block_keys["measurements"].index("cup_index")
            if "cup_index" in block_keys["measurements"]
            else -1
        )
        if cup_position >= 0:
            cup_all = measurements[:, cup_position]  # type: ignore[index]
            cup_known = known_values["measurements"][:, cup_position]  # type: ignore[index]
            both_cup = np.outer(cup_all != 0, cup_known != 0)
            cup_difference = np.abs(np.subtract.outer(cup_all, cup_known))
            penalty *= np.where(
                both_cup, np.exp(-0.18 * np.maximum(0.0, cup_difference - 1.0)), 1.0
            )
    augmentation = values.get("augmentation")
    if augmentation is not None and augmentation.shape[1]:  # type: ignore[union-attr]
        augmentation_binary = (augmentation != 0).astype(np.float32)  # type: ignore[index]
        known_augmentation_binary = (known_values["augmentation"] != 0).astype(np.float32)  # type: ignore[index]
        shared_augmentation = augmentation_binary @ known_augmentation_binary.T
        both_augmentation = np.outer(
            augmentation_binary.any(axis=1),
            known_augmentation_binary.any(axis=1),  # type: ignore[index]
        )
        penalty *= np.where(both_augmentation & (shared_augmentation == 0), 0.65, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        similarity = np.where(denominator > 0, numerator / denominator * penalty, 0.0)
    result: dict[str, dict[str, object]] = {}
    for performer_index, performer_id in enumerate(profile_ids):
        row = similarity[performer_index]
        candidates = [
            (known_ids[column], float(row[column]))
            for column in range(len(known_ids))
            if known_ids[column] != performer_id and float(row[column]) > 0
        ]
        selected = sorted(candidates, key=lambda item: (-item[1], item[0]))[:5]
        denominator_value = sum(item[1] ** 3 for item in selected)
        value = (
            sum(float(known_affinity[known_position[item[0]]]) * item[1] ** 3 for item in selected)
            / denominator_value
            if denominator_value
            else 0.0
        )
        confidence = (
            sum(
                float(known_confidence[known_position[item[0]]]) * item[1] ** 3 for item in selected
            )
            / denominator_value
            if denominator_value
            else 0.0
        )
        result[performer_id] = {
            "value": value,
            "confidence": confidence,
            "matches": [
                {
                    "performer_id": known_id,
                    "similarity": score,
                    "affinity": identity_affinity[known_id][0],
                    "confidence": identity_affinity[known_id][1],
                    "blocks": {
                        block: float(
                            block_similarities[block][performer_index, known_position[known_id]]  # type: ignore[index]
                        )
                        for block in used
                        if bool(used[block][performer_index, known_position[known_id]])  # type: ignore[index]
                    },
                }
                for known_id, score in selected[:3]
            ],
        }
    return result
