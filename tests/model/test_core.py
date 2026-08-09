"""Builder-level compiled-core differential and fallback behavior.

Runs the real PreferenceModelBuilder pipeline against a seeded synthetic
sidecar (same fixture as tests/model/test_builder.py) and asserts the compiled
core matches the numpy stage outputs within tolerance (exact ids, 1e-9 floats),
and that the dispatch/fallback contract holds: binary present -> core used,
absent -> numpy, then pure Python, and a broken binary fails the stage loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from curator import core as core_module
from curator.core import CoreError
from curator.model import PreferenceModelBuilder
from curator.model import builder as builder_module
from tests.model.test_builder import REFERENCE_MS, _database


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
    if not builder_module.optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    builder, context = _built_context(tmp_path)
    numpy_result = builder._content_neighbors_numpy(
        context["preference"],
        context["training_labels"],
        context["label_mean"],
        context["progress_total"],
    )
    core_result = builder._content_neighbors_core(
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
    if not builder_module.optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    builder, context = _built_context(tmp_path)
    numpy_result = builder._performer_similarity_scores_numpy(
        context["feature_version"], context["scene_features"], context["affinities"]
    )
    core_result = builder._performer_similarity_scores_core(
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


def test_model_build_with_core_persists_identical_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two identical seeded sidecars built through different implementations
    must produce the same model id and matching persisted rows."""
    if not builder_module.optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    real_binary = builder_module.core.core_binary
    core_path = tmp_path / "core.sqlite3"
    numpy_path = tmp_path / "numpy.sqlite3"
    core_connection = _database(core_path)
    numpy_connection = _database(numpy_path)
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    numpy_build = PreferenceModelBuilder(numpy_connection, clock_ms=lambda: REFERENCE_MS).build()
    monkeypatch.setattr(builder_module.core, "core_binary", real_binary)
    core_build = PreferenceModelBuilder(core_connection, clock_ms=lambda: REFERENCE_MS).build()

    assert core_build.model_id == numpy_build.model_id

    def neighbor_rows(connection: object, model_id: str) -> list[tuple[object, ...]]:
        return sorted(
            tuple(row)
            for row in connection.execute(  # type: ignore[union-attr]
                """
                SELECT scene_id, rank, neighbor_scene_id, similarity, weight, outcome
                FROM model_scene_neighbor WHERE model_id=? ORDER BY scene_id, rank
                """,
                (model_id,),
            )
        )

    core_neighbors = neighbor_rows(core_connection, core_build.model_id)
    numpy_neighbors = neighbor_rows(numpy_connection, numpy_build.model_id)
    assert [row[:3] for row in core_neighbors] == [row[:3] for row in numpy_neighbors]
    for core_row, numpy_row in zip(core_neighbors, numpy_neighbors, strict=True):
        for index in (3, 4, 5):
            assert core_row[index] == pytest.approx(numpy_row[index], rel=1e-9)

    def edge_rows(connection: object, model_id: str) -> list[tuple[object, ...]]:
        return sorted(
            tuple(row)
            for row in connection.execute(  # type: ignore[union-attr]
                """
                SELECT performer_id, rank, similar_performer_id, similarity, affinity, confidence
                FROM model_performer_edge WHERE model_id=? ORDER BY performer_id, rank
                """,
                (model_id,),
            )
        )

    core_edges = edge_rows(core_connection, core_build.model_id)
    numpy_edges = edge_rows(numpy_connection, numpy_build.model_id)
    assert [row[:3] for row in core_edges] == [row[:3] for row in numpy_edges]
    for core_row, numpy_row in zip(core_edges, numpy_edges, strict=True):
        for index in (3, 4, 5):
            assert core_row[index] == pytest.approx(numpy_row[index], rel=1e-9)

    def component_values(connection: object, model_id: str) -> dict[str, dict[str, float]]:
        values: dict[str, dict[str, float]] = {}
        for row in connection.execute(  # type: ignore[union-attr]
            "SELECT scene_id, components_json FROM model_scene_score WHERE model_id=?",
            (model_id,),
        ):
            components = json.loads(str(row["components_json"]))
            values[str(row["scene_id"])] = {
                family: float(components[family]["value"])
                for family in (
                    "content",
                    "content_neighbor",
                    "performer_identity",
                    "performer_similarity",
                    "studio",
                    "structure",
                )
            }
        return values

    core_components = component_values(core_connection, core_build.model_id)
    numpy_components = component_values(numpy_connection, numpy_build.model_id)
    assert set(core_components) == set(numpy_components)
    for scene_id in numpy_components:
        for family in numpy_components[scene_id]:
            assert core_components[scene_id][family] == pytest.approx(
                numpy_components[scene_id][family], rel=1e-9
            )


def test_content_neighbors_dispatch_falls_back_without_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder, context = _built_context(tmp_path)
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    monkeypatch.setattr(builder_module.optional_deps, "NUMPY_AVAILABLE", True)
    numpy_called: list[bool] = []
    python_called: list[bool] = []

    def fake_numpy(*args: object, **kwargs: object) -> object:
        numpy_called.append(True)
        return {}

    def fake_python(*args: object, **kwargs: object) -> object:
        python_called.append(True)
        return {}

    monkeypatch.setattr(builder, "_content_neighbors_numpy", fake_numpy)
    monkeypatch.setattr(builder, "_content_neighbors_python", fake_python)
    result = builder._content_neighbors(
        context["preference"],
        context["training_labels"],
        context["label_mean"],
        context["progress_total"],
    )
    assert numpy_called and not python_called and result == {}

    numpy_called.clear()
    monkeypatch.setattr(builder_module.optional_deps, "NUMPY_AVAILABLE", False)
    builder._content_neighbors(
        context["preference"],
        context["training_labels"],
        context["label_mean"],
        context["progress_total"],
    )
    assert python_called and not numpy_called


def test_performer_dispatch_prefers_core_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder, context = _built_context(tmp_path)
    core_called: list[bool] = []
    numpy_called: list[bool] = []
    python_called: list[bool] = []

    def fake_core(*args: object, **kwargs: object) -> dict[str, object]:
        core_called.append(True)
        return {}

    def fake_numpy(*args: object, **kwargs: object) -> dict[str, object]:
        numpy_called.append(True)
        return {}

    def fake_python(*args: object, **kwargs: object) -> dict[str, object]:
        python_called.append(True)
        return {}

    monkeypatch.setattr(builder, "_performer_similarity_scores_core", fake_core)
    monkeypatch.setattr(builder, "_performer_similarity_scores_numpy", fake_numpy)
    monkeypatch.setattr(builder, "_performer_similarity_scores_python", fake_python)

    monkeypatch.setattr(builder_module.core, "core_binary", lambda: Path("/binary"))
    builder._performer_similarity_scores(
        context["feature_version"], context["scene_features"], context["affinities"]
    )
    assert core_called and not numpy_called and not python_called

    core_called.clear()
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    builder._performer_similarity_scores(
        context["feature_version"], context["scene_features"], context["affinities"]
    )
    assert numpy_called and not core_called and not python_called

    numpy_called.clear()
    monkeypatch.setattr(builder_module.optional_deps, "NUMPY_AVAILABLE", False)
    builder._performer_similarity_scores(
        context["feature_version"], context["scene_features"], context["affinities"]
    )
    assert python_called and not numpy_called and not core_called


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
