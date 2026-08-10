"""Compiled-core differential harness (transport and kernel level).

Python owns the data (seeded synthetic corpora, never a real sidecar); the
curator-core binary must reproduce the numpy stage outputs within tolerance —
exact ids/counts, 1e-9 relative for floats. These tests skip when the binary is
not built; the CI core job builds it and runs the suite with CURATOR_CORE set.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

import pytest

from curator import core as core_module
from curator.config import DEFAULT_CONFIG
from curator.core import CoreError, core_binary, run_core
from curator.features.store import StoredFeature
from curator.model import builder as builder_module
from curator.model.builder import PreferenceModelBuilder
from curator.storage import MigrationRunner, connect_database
from curator.storage.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    FEATURE_SCHEMA,
    attach_active_artifacts,
)

FEATURE_VERSION = "fv-" + "a" * 20


def synthetic_corpus(
    seed: int,
    n_scenes: int,
    d_features: int,
    nnz: int,
    n_performers: int = 0,
) -> dict[str, object]:
    """Seeded synthetic corpus with content vectors and optional performer
    profiles. Values are |N(0,1)| row-normalized like the POC generator."""
    rng = random.Random(seed)
    names = [f"f{index:04d}" for index in range(d_features)]
    scenes = [f"s{index:04d}" for index in range(n_scenes)]
    content: list[tuple[str, str, float]] = []
    for scene in scenes:
        chosen = rng.sample(names, min(nnz, d_features))
        values = [abs(rng.gauss(0.0, 1.0)) for _ in chosen]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        for name, value in zip(chosen, values, strict=True):
            content.append((scene, name, value / norm))
    labels = {
        scene: [rng.uniform(-1.0, 1.0), rng.uniform(0.2, 1.0)]
        for scene in scenes
        if rng.random() < 0.55
    }
    affinities = {
        name: [rng.uniform(-0.8, 0.8), rng.uniform(0.3, 1.0)]
        for name in rng.sample(names, max(1, d_features // 5))
    }
    profiles: list[tuple[str, str, str, float, float]] = []
    performers = [f"p{index:03d}" for index in range(n_performers)]
    for performer in performers:
        for name in rng.sample(names, max(1, d_features // 8)):
            profiles.append(
                (performer, "content", name, abs(rng.gauss(0.0, 1.0)), rng.uniform(0.5, 1.0))
            )
        profiles.append((performer, "measurements", "cup_index", float(rng.randint(26, 40)), 1.0))
        profiles.append((performer, "measurements", "height_cm", rng.uniform(140.0, 190.0), 0.9))
        if rng.random() < 0.4:
            profiles.append((performer, "augmentation", "fake", 1.0, 1.0))
        profiles.append((performer, "hair", "brown", 1.0, 0.8))
    identity = {
        performer: [rng.uniform(-0.7, 0.7), rng.uniform(0.4, 1.0)]
        for performer in rng.sample(performers, max(0, n_performers * 3 // 10))
    }
    return {
        "content": content,
        "profiles": profiles,
        "labels": labels,
        "affinity_names": affinities,
        "identity": identity,
        "scenes": scenes,
        "performers": performers,
    }


def _feature_definition_rows(corpus: dict[str, object]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for _scene, name, _value in corpus["content"]:
        rows.append((f"cid-{name}", "content", name))
    for performer, block, key, _value, _confidence in corpus["profiles"]:
        rows.append((f"pid-{performer}-{block}-{key}", f"profile:{block}", key))
    return sorted(set(rows))


def write_feature_artifact(path: Path, corpus: dict[str, object]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(FEATURE_SCHEMA)
    connection.execute(f"PRAGMA user_version = {ARTIFACT_SCHEMA_VERSION}")
    connection.execute(
        "INSERT INTO artifact_meta(kind, generation_id, schema_version) VALUES ('feature', ?, ?)",
        (FEATURE_VERSION, ARTIFACT_SCHEMA_VERSION),
    )
    connection.executemany(
        """
        INSERT INTO feature_definition(feature_id, feature_version, family, name, provenance)
        VALUES (?, ?, ?, ?, 'synthetic')
        """,
        (
            (feature_id, FEATURE_VERSION, family, name)
            for feature_id, family, name in _feature_definition_rows(corpus)
        ),
    )
    connection.executemany(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES (?, 'scene', ?, ?, ?, 1.0)
        """,
        (
            (FEATURE_VERSION, scene, f"cid-{name}", value)
            for scene, name, value in corpus["content"]
        ),
    )
    connection.executemany(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES (?, 'performer', ?, ?, ?, ?)
        """,
        (
            (
                FEATURE_VERSION,
                performer,
                f"pid-{performer}-{block}-{key}",
                value,
                confidence,
            )
            for performer, block, key, value, confidence in corpus["profiles"]
        ),
    )
    connection.commit()
    connection.close()


def core_with_feature_artifact(
    tmp_path: Path, corpus: dict[str, object]
) -> tuple[sqlite3.Connection, Path]:
    """A minimal core DB whose feature_build row points at a synthetic artifact,
    with the artifact attached (mirroring a published feature generation)."""
    derived = tmp_path / "curator-derived"
    derived.mkdir(parents=True, exist_ok=True)
    artifact = derived / f"feature-{FEATURE_VERSION}.sqlite3"
    write_feature_artifact(artifact, corpus)
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms,
            published_at_ms, artifact_basename, artifact_schema_version, validation_status
        ) VALUES (?, 'published', '{}', 'synthetic', 1, 1, ?, ?, 'valid')
        """,
        (FEATURE_VERSION, artifact.name, ARTIFACT_SCHEMA_VERSION),
    )
    attach_active_artifacts(connection)
    return connection, artifact


def _scene_labels(corpus: dict[str, object]) -> dict[str, builder_module._SceneLabel]:
    return {
        scene_id: builder_module._SceneLabel(outcome, confidence, 1.0, ("o",))
        for scene_id, (outcome, confidence) in corpus["labels"].items()
    }


def _content_affinities(corpus: dict[str, object]) -> dict[str, builder_module._Affinity]:
    affinities: dict[str, builder_module._Affinity] = {}
    for index, (name, (affinity, confidence)) in enumerate(corpus["affinity_names"].items()):
        feature_id = f"cid-{name}"
        contexts: dict[str, object] = {}
        if index % 2 == 0:
            contexts["learned_affinity"] = affinity * 0.8
            contexts["learned_confidence"] = confidence * 0.9
        affinities[feature_id] = builder_module._Affinity(
            feature_id, affinity, confidence, 1.0, 1, contexts
        )
    return affinities


def _scene_features(
    corpus: dict[str, object], with_identity: bool = False
) -> dict[str, tuple[StoredFeature, ...]]:
    by_scene: dict[str, list[StoredFeature]] = {}
    for scene, name, value in corpus["content"]:
        by_scene.setdefault(scene, []).append(
            StoredFeature(f"cid-{name}", "content", name, value, 1.0, {})
        )
    if with_identity:
        n_scenes = len(corpus["scenes"])
        for index, (performer, (_value, confidence)) in enumerate(corpus["identity"].items()):
            scene = corpus["scenes"][index % n_scenes]
            by_scene.setdefault(scene, []).append(
                StoredFeature(
                    f"pid-{performer}-identity",
                    "performer_identity",
                    f"performer:{performer}",
                    1.0,
                    confidence,
                    {},
                )
            )
    for scene in by_scene:
        by_scene[scene].sort(key=lambda feature: feature.name)
    return {
        scene: tuple(features)
        for scene, features in sorted(by_scene.items(), key=lambda item: item[0])
    }


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_module.core_binary()
    if path is None:
        pytest.skip("curator-core binary is not built (run scripts/build_core.sh)")
    return path


CONTENT_CORPORA = [
    (120, 60, 8),
    (300, 400, 20),
    (60, 20, 12),
    (400, 120, 10),
]


@pytest.mark.parametrize(("n_scenes", "d_features", "nnz"), CONTENT_CORPORA)
def test_content_neighbors_core_matches_numpy(
    tmp_path: Path, binary: Path, n_scenes: int, d_features: int, nnz: int
) -> None:
    if not builder_module.optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    corpus = synthetic_corpus(7, n_scenes, d_features, nnz, n_performers=0)
    connection, _artifact = core_with_feature_artifact(tmp_path, corpus)
    builder = PreferenceModelBuilder(connection)
    labels = _scene_labels(corpus)
    scene_features = _scene_features(corpus)
    affinities = _content_affinities(corpus)
    vectors = {scene: dict(rows) for scene, rows in _content_by_scene(corpus).items()}
    preference, _ = builder._preference_content_vectors(vectors, scene_features, affinities)
    label_mean = builder._label_mean(labels)
    progress_total = len(preference) + len(corpus["scenes"])

    numpy_result = builder._content_neighbors_numpy(preference, labels, label_mean, progress_total)
    core_result = builder._content_neighbors_core(
        FEATURE_VERSION, affinities, labels, label_mean, progress_total
    )

    _assert_neighbor_evidence_equal(core_result, numpy_result)


def _content_by_scene(corpus: dict[str, object]) -> dict[str, list[tuple[str, float]]]:
    result: dict[str, list[tuple[str, float]]] = {}
    for scene, name, _value in corpus["content"]:
        result.setdefault(scene, []).append((name, _value))
    for scene in result:
        result[scene].sort(key=lambda item: item[0])
    return result


def _assert_neighbor_evidence_equal(
    core_result: dict[str, builder_module._NeighborEvidence],
    numpy_result: dict[str, builder_module._NeighborEvidence],
) -> None:
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


def test_performer_similarity_core_matches_numpy(tmp_path: Path, binary: Path) -> None:
    if not builder_module.optional_deps.NUMPY_AVAILABLE:
        pytest.skip("numpy is not installed")
    corpus = synthetic_corpus(13, 150, 90, 12, n_performers=60)
    connection, _artifact = core_with_feature_artifact(tmp_path, corpus)
    builder = PreferenceModelBuilder(connection)
    # identity affinity values are (affinity * confidence, confidence); the
    # affinity object's affinity field is value / confidence so the numpy path
    # reproduces the exact payload values.
    identity_affinities: dict[str, builder_module._Affinity] = {}
    for performer, (value, confidence) in corpus["identity"].items():
        feature_id = f"pid-{performer}-identity"
        identity_affinities[feature_id] = builder_module._Affinity(
            feature_id, value / confidence, confidence, 1.0, 1, {}
        )
    scene_features = _scene_features(corpus, with_identity=True)
    numpy_result = builder._performer_similarity_scores_numpy(
        FEATURE_VERSION, scene_features, identity_affinities
    )
    core_result = builder._performer_similarity_scores_core(
        FEATURE_VERSION, scene_features, identity_affinities
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


def _artifact_path(tmp_path: Path, corpus: dict[str, object]) -> Path:
    artifact = tmp_path / "curator-derived" / f"feature-{FEATURE_VERSION}.sqlite3"
    if not artifact.exists():
        core_with_feature_artifact(tmp_path, corpus)
    return artifact


def _content_payload(
    tmp_path: Path, corpus: dict[str, object], threads: int = 0
) -> dict[str, object]:
    return {
        "db": str(_artifact_path(tmp_path, corpus)),
        "feature_version": FEATURE_VERSION,
        "labels": corpus["labels"],
        "label_mean": 0.1,
        "affinities": {
            f"cid-{name}": {"affinity": affinity, "confidence": confidence}
            for name, (affinity, confidence) in corpus["affinity_names"].items()
        },
        "config": {
            "min_similarity": DEFAULT_CONFIG.model.minimum_neighbor_similarity,
            "neighbor_count": DEFAULT_CONFIG.model.neighbor_count,
            "confidence_scale": DEFAULT_CONFIG.model.neighbor_confidence_scale,
            "generic_weight": DEFAULT_CONFIG.model.neighbor_generic_weight,
        },
        "progress_total": len(corpus["scenes"]),
        "threads": threads,
    }


def test_content_neighbors_deterministic_across_threads(tmp_path: Path, binary: Path) -> None:
    corpus = synthetic_corpus(23, 500, 200, 14, n_performers=0)
    single = run_core("content-neighbors", _content_payload(tmp_path, corpus, threads=1))
    multi = run_core("content-neighbors", _content_payload(tmp_path, corpus, threads=4))
    assert json.dumps(single, sort_keys=True) == json.dumps(multi, sort_keys=True)


def test_run_core_streams_progress(tmp_path: Path, binary: Path) -> None:
    corpus = synthetic_corpus(31, 1200, 300, 12, n_performers=0)
    progress: list[float] = []
    result = run_core(
        "content-neighbors",
        _content_payload(tmp_path, corpus),
        progress=progress.append,
    )
    assert progress, "expected streamed progress lines"
    assert progress == sorted(progress), "progress must be monotonic"
    assert 0 < progress[-1] <= 1
    assert set(result) == set(corpus["scenes"])


def test_run_core_records_core_spans_into_trace(tmp_path: Path, binary: Path) -> None:
    from curator.profiling import begin_trace, end_trace

    corpus = synthetic_corpus(41, 400, 150, 10, n_performers=0)
    trace, token = begin_trace("unit", "test")
    try:
        run_core(
            "content-neighbors",
            _content_payload(tmp_path, corpus),
            profile=True,
        )
    finally:
        end_trace(trace, token)
    names = [event["name"] for event in trace.events if event["cat"] == "core"]
    expected = {
        "core.read_features",
        "core.preference_vectors",
        "core.build_columns",
        "core.kernel",
        "core.encode_result",
    }
    assert expected <= set(names)
    for event in trace.events:
        if event["cat"] == "core":
            assert int(event["dur"]) > 0
            assert event["ts"] >= trace.started_at_ns // 1_000


def test_run_core_profiling_off_emits_no_spans(tmp_path: Path, binary: Path) -> None:
    from curator.profiling import begin_trace, end_trace

    corpus = synthetic_corpus(43, 200, 100, 8, n_performers=0)
    trace, token = begin_trace("unit", "test")
    try:
        run_core("content-neighbors", _content_payload(tmp_path, corpus), profile=False)
    finally:
        end_trace(trace, token)
    assert not [event for event in trace.events if event["cat"] == "core"]


def _fake_binary(tmp_path: Path, *, stage_exit: int = 0) -> Path:
    script = tmp_path / "fake-curator-core"
    script.write_text(
        f"""#!/usr/bin/env python3
import json, sys
if sys.argv[1] == "version":
    print(json.dumps({{"protocol": 1, "version": "0.0.1"}}))
else:
    if {stage_exit} != 0:
        print("fake stage failure", file=sys.stderr)
        sys.exit({stage_exit})
    print(json.dumps({{"result": {{"scene": {{"neighbors": []}}}}}}))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_core_binary_probe_accepts_matching_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _fake_binary(tmp_path)
    monkeypatch.setenv("CURATOR_CORE", str(fake))
    core_module._clear_cache()
    try:
        assert core_binary() == fake
    finally:
        monkeypatch.delenv("CURATOR_CORE", raising=False)
        core_module._clear_cache()


def test_platform_binary_name_maps_go_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        (("Linux", "x86_64"), "curator-core-linux-amd64"),
        (("Linux", "aarch64"), "curator-core-linux-arm64"),
        (("Darwin", "arm64"), "curator-core-darwin-arm64"),
        (("Windows", "AMD64"), "curator-core-windows-amd64.exe"),
    ]
    for (system, machine), expected in cases:
        monkeypatch.setattr(core_module.platform, "system", lambda s=system: s)
        monkeypatch.setattr(core_module.platform, "machine", lambda m=machine: m)
        assert core_module._platform_binary_name() == expected
    monkeypatch.setattr(core_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(core_module.platform, "machine", lambda: "mips64")
    assert core_module._platform_binary_name() == "curator-core-linux-mips64"


def test_core_binary_probe_rejects_mismatched_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "wrong-protocol"
    fake.write_text(
        '#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps({"protocol": 99}))\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("CURATOR_CORE", str(fake))
    core_module._clear_cache()
    try:
        assert core_binary() is None
    finally:
        monkeypatch.delenv("CURATOR_CORE", raising=False)
        core_module._clear_cache()


def test_run_core_raises_on_broken_binary(tmp_path: Path) -> None:
    broken = _fake_binary(tmp_path, stage_exit=3)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CURATOR_CORE", str(broken))
    core_module._clear_cache()
    try:
        with pytest.raises(CoreError, match="fake stage failure"):
            run_core("content-neighbors", {"db": str(tmp_path), "labels": {}, "config": {}})
    finally:
        monkeypatch.undo()
        core_module._clear_cache()


def test_run_core_records_multihop_span_into_trace(tmp_path: Path, binary: Path) -> None:
    from curator.profiling import begin_trace, end_trace

    trace, token = begin_trace("unit", "test")
    try:
        run_core(
            "multi-hop",
            {
                "adjacency": {
                    "a": {"b": 1.0},
                    "b": {"a": 1.0},
                    "c": {},
                },
                "seed": "a",
            },
            profile=True,
        )
    finally:
        end_trace(trace, token)
    assert [event["name"] for event in trace.events if event["cat"] == "core"] == ["core.pagerank"]
