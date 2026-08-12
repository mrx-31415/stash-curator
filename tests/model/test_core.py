"""Builder-level compiled-core differential tests.

Runs the real PreferenceModelBuilder pipeline against a seeded synthetic
sidecar (same fixture as tests/model/test_builder.py) and asserts the compiled
core matches the numpy stage outputs within tolerance (exact ids, 1e-9 floats),
and that the dispatch contract holds: the binary is the single kernel
implementation, a missing binary surfaces as ``CoreError`` at the stage
boundary, and a broken binary fails the stage loudly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from curator import core as core_module
from curator import optional_deps
from curator.core import CoreError
from curator.model import PreferenceModelBuilder
from curator.model import builder as builder_module
from tests.model.test_builder import REFERENCE_MS, _database

# The Python-era stage key set (stageTimingOrder in core/tasks.go): the
# model-build kernel result must report all 22 keys.
STAGE_TIMING_KEYS = (
    "feature_lookup",
    "feature_build",
    "feature_database_writing",
    "feature_indexing",
    "feature_validation",
    "feature_publication",
    "feature_total",
    "labels",
    "affinities",
    "similarity",
    "scoring",
    "database_writing",
    "lane_classification",
    "score_first_ordering",
    "varied_ordering",
    "reason_generation",
    "sqlite_index_creation",
    "indexing",
    "validation",
    "publication",
    "cleanup",
    "total",
)


def _built_context(tmp_path: Path) -> tuple[builder_module.PreferenceModelBuilder, object]:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    built = builder.build()
    scene_features = builder_module.FeatureStore(connection).entity_features(
        built.feature_version, "scene"
    )
    labels = builder._scene_labels()
    training_labels = builder._training_labels(labels)
    label_mean = builder._label_mean(training_labels)
    affinities = builder._affinities(scene_features, training_labels, label_mean)
    vectors = builder_module.FeatureStore(connection).scene_content_vectors(built.feature_version)
    preference, _ = builder._preference_content_vectors(vectors, scene_features, affinities)
    progress_total = len(preference) + len(
        connection.execute("SELECT scene_id FROM source_scene").fetchall()
    )
    return builder, {
        "feature_version": built.feature_version,
        "scene_features": scene_features,
        "labels": labels,
        "training_labels": training_labels,
        "label_mean": label_mean,
        "affinities": affinities,
        "preference": preference,
        "progress_total": progress_total,
    }


def test_content_neighbors_core_matches_numpy_on_built_corpus(tmp_path: Path) -> None:
    if not optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    builder, context = _built_context(tmp_path)
    from tests.oracle import content_neighbors_numpy

    numpy_result = content_neighbors_numpy(
        context["preference"],
        context["training_labels"],
        context["label_mean"],
        context["progress_total"],
        min_similarity=builder.config.model.minimum_neighbor_similarity,
        neighbor_count=builder.config.model.neighbor_count,
        confidence_scale=builder.config.model.neighbor_confidence_scale,
    )
    core_result = builder._content_neighbors(
        context["feature_version"],
        context["affinities"],
        context["training_labels"],
        context["label_mean"],
        context["progress_total"],
    )
    assert set(core_result) == set(numpy_result)
    for scene_id in numpy_result:
        core_evidence = core_result[scene_id]
        numpy_evidence = numpy_result[scene_id]
        assert core_evidence.value == pytest.approx(numpy_evidence.value, rel=1e-9)
        assert core_evidence.outcome_mean == pytest.approx(numpy_evidence.outcome_mean, rel=1e-9)
        assert core_evidence.lift == pytest.approx(numpy_evidence.lift, rel=1e-9)
        assert core_evidence.confidence == pytest.approx(numpy_evidence.confidence, rel=1e-9)
        assert core_evidence.total_weight == pytest.approx(numpy_evidence.total_weight, rel=1e-9)
        assert [n["scene_id"] for n in core_evidence.neighbors] == [
            n["scene_id"] for n in numpy_evidence.neighbors
        ]
        for core_neighbor, numpy_neighbor in zip(
            core_evidence.neighbors, numpy_evidence.neighbors, strict=True
        ):
            assert core_neighbor["similarity"] == pytest.approx(
                numpy_neighbor["similarity"], rel=1e-9
            )
            assert core_neighbor["weight"] == pytest.approx(numpy_neighbor["weight"], rel=1e-9)
            assert core_neighbor["outcome"] == pytest.approx(numpy_neighbor["outcome"], rel=1e-9)


def test_performer_similarity_core_matches_numpy_on_built_corpus(tmp_path: Path) -> None:
    if not optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    builder, context = _built_context(tmp_path)
    from tests.oracle import performer_similarity_numpy

    numpy_result = performer_similarity_numpy(
        builder.connection,
        context["feature_version"],
        context["scene_features"],
        context["affinities"],
        block_weights=dict(builder.config.feature.performer_block_weights),
        cutoff=builder_module.PERFORMER_SIMILARITY_AFFINITY_CUTOFF,
    )
    core_result = builder._performer_similarity_scores(
        context["feature_version"], context["scene_features"], context["affinities"]
    )
    assert set(core_result) == set(numpy_result)
    for performer_id in numpy_result:
        assert core_result[performer_id]["value"] == pytest.approx(
            numpy_result[performer_id]["value"], rel=1e-9
        )
        assert core_result[performer_id]["confidence"] == pytest.approx(
            numpy_result[performer_id]["confidence"], rel=1e-9
        )
        assert [m["performer_id"] for m in core_result[performer_id]["matches"]] == [
            m["performer_id"] for m in numpy_result[performer_id]["matches"]
        ]
        for core_match, numpy_match in zip(
            core_result[performer_id]["matches"],
            numpy_result[performer_id]["matches"],
            strict=True,
        ):
            assert core_match["similarity"] == pytest.approx(numpy_match["similarity"], rel=1e-9)
            assert core_match["affinity"] == pytest.approx(numpy_match["affinity"], rel=1e-9)
            assert core_match["confidence"] == pytest.approx(numpy_match["confidence"], rel=1e-9)
            assert set(core_match["blocks"]) == set(numpy_match["blocks"])
            for block in numpy_match["blocks"]:
                assert core_match["blocks"][block] == pytest.approx(
                    numpy_match["blocks"][block], rel=1e-9
                )


def test_missing_binary_fails_the_stage_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compiled core is a runtime requirement: a missing binary raises an
    actionable error instead of silently falling back."""
    from curator.core import CoreError

    builder, context = _built_context(tmp_path)
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    with pytest.raises(CoreError, match="curator-core is required"):
        builder._content_neighbors(
            context["feature_version"],
            context["affinities"],
            context["training_labels"],
            context["label_mean"],
            context["progress_total"],
        )
    with pytest.raises(CoreError, match="curator-core is required"):
        builder._performer_similarity_scores(
            context["feature_version"], context["scene_features"], context["affinities"]
        )


def test_broken_binary_fails_the_stage_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "broken-core"
    script.write_text(
        """#!/usr/bin/env python3
import json, sys
if sys.argv[1] == "version":
    print(json.dumps({"protocol": 1, "version": "0.0.1"}))
else:
    print("stage exploded", file=sys.stderr)
    sys.exit(7)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setattr(core_module, "core_binary", lambda: script)
    with pytest.raises(CoreError, match="stage exploded"):
        core_module.run_core("content-neighbors", {"db": str(tmp_path), "labels": {}})


def test_core_available_flag_matches_resolver(tmp_path: Path) -> None:
    assert core_module.core_available() is (core_module.core_binary() is not None)
    assert builder_module.core.core_binary() is core_module.core_binary()


def test_model_build_kernel_result_surface(tmp_path: Path) -> None:
    """curator-core model-build reports the full 22-key stage_timings_ms,
    per-stage memory snapshots, and final peak RSS on its result line — the
    GOMAXPROCS sweep and the CI perf budget read them without the profile
    flag."""
    binary = core_module.core_binary()
    if binary is None:
        pytest.skip("curator-core binary is not built")
    sidecar = tmp_path / "curator.sqlite3"
    _database(sidecar)
    payload = json.dumps(
        {"db": str(sidecar), "now_ms": REFERENCE_MS}, separators=(",", ":")
    ).encode()
    result = subprocess.run(
        [str(binary), "model-build"], input=payload, capture_output=True, timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = None
    for line in result.stdout.decode().splitlines():
        parsed = json.loads(line)
        if "result" in parsed:
            output = parsed["result"]
    assert output is not None
    assert output["reused"] is False
    assert output["scene_count"] == 6
    assert set(output["stage_timings_ms"]) == set(STAGE_TIMING_KEYS)
    assert output["stage_timings_ms"]["total"] > 0
    for key in STAGE_TIMING_KEYS:
        memory = output["stage_memory"][key]
        assert memory["peak_rss_kb"] > 0, f"stage {key} lacks peak_rss_kb"
        for field in ("heap_alloc_kb", "heap_sys_kb", "total_alloc_kb", "num_gc"):
            assert field in memory, f"stage {key} memory lacks {field}"
    assert output["peak_rss_kb"] > 0
