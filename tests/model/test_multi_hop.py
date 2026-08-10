"""Multi-hop affinity: personalized PageRank over the performer-collaboration graph."""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

import pytest

from curator import optional_deps
from curator.features import FeatureStore
from curator.model import PreferenceModelBuilder
from curator.model import builder as builder_module
from curator.model.multi_hop import (
    REACH_FLOOR,
    MultiHopAffinity,
    _Graph,
    _pagerank_networkx,
    _pagerank_python,
)
from curator.similarity import SimilarityService
from curator.storage import MigrationRunner, connect_database
from tests.model.test_builder import REFERENCE_MS, _database


def _graph_database(path: Path) -> sqlite3.Connection:
    """Small deterministic walkable graph.

    Scenes: s (seed) stars p1; c stars p1 (one hop); d stars p2, where p1 ~ p2
    (two performer hops); f stars p3 with no edges (unreachable).
    """
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms)
        VALUES ('m', 'published', 'fv', '{}', 1)
        """
    )
    connection.executemany(
        """
        INSERT INTO feature_definition(feature_id, feature_version, family, name, provenance)
        VALUES (?, ?, 'performer_identity', ?, 'test')
        """,
        (
            ("performer:p1", "fv", "performer:p1"),
            ("performer:p2", "fv", "performer:p2"),
            ("performer:p3", "fv", "performer:p3"),
        ),
    )
    connection.executemany(
        """
        INSERT INTO feature_affinity(
            model_id, feature_id, affinity, confidence, effective_support,
            distinct_scene_count
        ) VALUES ('m', ?, ?, ?, 1, 1)
        """,
        (("performer:p1", 0.5, 1.0), ("performer:p2", 0.4, 1.0), ("performer:p3", 0.3, 1.0)),
    )
    connection.executemany(
        "INSERT INTO source_performer(performer_id, name, source_hash) VALUES (?, ?, ?)",
        (("p1", "One", "p1"), ("p2", "Two", "p2"), ("p3", "Three", "p3")),
    )
    connection.executemany(
        "INSERT INTO source_scene(scene_id, title, source_hash) VALUES (?, ?, ?)",
        (("s", "seed", "s"), ("c", "co-star", "c"), ("d", "second-hop", "d"), ("f", "far", "f")),
    )
    connection.executemany(
        "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, 0)",
        (("s", "p1"), ("c", "p1"), ("d", "p2"), ("f", "p3")),
    )
    connection.executemany(
        """
        INSERT INTO model_performer_edge(
            model_id, performer_id, rank, similar_performer_id, similarity, affinity, confidence
        ) VALUES ('m', ?, ?, ?, ?, ?, ?)
        """,
        (
            ("p1", 0, "p2", 0.9, 0.4, 1.0),
            ("p2", 0, "p1", 0.9, 0.5, 1.0),
        ),
    )
    return connection


def test_reach_ranks_chain_scenes_and_excludes_seed(
    tmp_path: Path,
) -> None:
    connection = _graph_database(tmp_path / "curator.sqlite3")
    reach = MultiHopAffinity(connection, "m").reach("s")

    # "c" co-stars p1 but is now excluded: the seed's own performer does not
    # expand to their other scenes (those are direct overlap, handled by Similar).
    # "d" stars p2, reachable through the p1→p2 performer edge.
    assert set(reach) == {"d"}
    # The disconnected scene is not reachable through any path.
    assert "f" not in reach


def test_reach_is_deterministic(tmp_path: Path) -> None:
    connection = _graph_database(tmp_path / "curator.sqlite3")
    service = MultiHopAffinity(connection, "m")
    first = service.reach("s")
    second = MultiHopAffinity(connection, "m").reach("s")
    assert first == second
    assert first == MultiHopAffinity(connection, "m").reach("s")


def test_reach_empty_when_seed_has_no_affinity_performers(tmp_path: Path) -> None:
    connection = _graph_database(tmp_path / "curator.sqlite3")
    # A scene with no performers at all is not in the walkable graph.
    connection.execute(
        "INSERT INTO source_scene(scene_id, title, source_hash) VALUES ('y', 'y', 'y')"
    )
    assert MultiHopAffinity(connection, "m").reach("y") == {}
    assert MultiHopAffinity(connection, "m").reach("missing") == {}


def _scipy_importable() -> bool:
    try:
        import scipy  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    optional_deps.nx is None or not _scipy_importable(),
    reason="networkx with scipy is not installed in this environment",
)
def test_networkx_and_python_paths_agree(tmp_path: Path) -> None:
    connection = _graph_database(tmp_path / "curator.sqlite3")
    graph = MultiHopAffinity(connection, "m")._graph("s")
    nx_scores = _pagerank_networkx(graph)
    python_scores = _pagerank_python(graph)

    assert set(nx_scores) == set(python_scores)
    for node in nx_scores:
        assert nx_scores[node] == pytest.approx(python_scores[node], rel=1e-9)
    ranking = sorted(
        (
            node
            for node in nx_scores
            if node in graph.scenes and node != "s" and nx_scores[node] >= REACH_FLOOR
        ),
        key=lambda node: (-nx_scores[node], node),
    )
    assert ranking == ["d"]


def test_reach_matches_pure_python_when_networkx_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _graph_database(tmp_path / "curator.sqlite3")
    monkeypatch.setattr(optional_deps, "nx", None)
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    service = MultiHopAffinity(connection, "m")
    scores = _pagerank_python(service._graph("s"))
    expected = {
        scene: scores[scene]
        for scene in sorted(
            (
                node
                for node in scores
                if node in service._scene_performers and node != "s" and scores[node] >= REACH_FLOOR
            ),
            key=lambda node: (-scores[node], node),
        )[:50]
    }
    assert service.reach("s") == expected


def test_publish_writes_performer_edges_matching_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    # Force the pure-Python path so the recomputed expectation matches exactly.
    monkeypatch.setattr(optional_deps, "NUMPY_AVAILABLE", False)
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    builder = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS)
    built = builder.build()

    rows = connection.execute(
        """
        SELECT performer_id, rank, similar_performer_id, similarity, affinity, confidence
        FROM model_performer_edge WHERE model_id=?
        ORDER BY performer_id, rank
        """,
        (built.model_id,),
    ).fetchall()
    assert rows, "expected persisted performer edges"

    scene_features = FeatureStore(connection).entity_features(built.feature_version, "scene")
    affinities = _affinities_from_store(connection, built.model_id)
    expected = builder._performer_similarity_scores(
        built.feature_version, scene_features, affinities
    )
    expected_rows = [
        (
            performer_id,
            rank,
            str(match["performer_id"]),
            match["similarity"],
            match["affinity"],
            match["confidence"],
        )
        for performer_id, entry in sorted(expected.items())
        for rank, match in enumerate(entry["matches"])
    ]
    assert [tuple(row) for row in rows] == [
        (
            performer,
            rank,
            similar,
            pytest.approx(similarity),
            pytest.approx(affinity),
            pytest.approx(confidence),
        )
        for performer, rank, similar, similarity, affinity, confidence in expected_rows
    ]


def _affinities_from_store(connection: sqlite3.Connection, model_id: str) -> dict[str, object]:
    affinities: dict[str, object] = {}
    for row in connection.execute(
        """
        SELECT feature_id, affinity, confidence, effective_support, distinct_scene_count,
               metadata_json
        FROM feature_affinity WHERE model_id=?
        """,
        (model_id,),
    ):
        affinities[str(row["feature_id"])] = builder_module._Affinity(
            str(row["feature_id"]),
            float(row["affinity"]),
            float(row["confidence"]),
            float(row["effective_support"]),
            int(row["distinct_scene_count"]),
            json.loads(str(row["metadata_json"])),
        )
    return affinities


def test_similarity_annotates_multi_hop_when_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    monkeypatch.setattr(optional_deps, "NUMPY_AVAILABLE", False)
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    results = SimilarityService(connection).scenes("old-good", 20)
    assert results
    # The fixture has only one positive-affinity performer with no chainable
    # edges; multi-hop degrades gracefully without crashing.
    for item in results:
        assert item.rank_score == pytest.approx(
            0.7 * item.similarity
            + 0.3 * item.appeal
            + 0.05 * item.details.get("multi_hop_reach", 0.0)
        )
        reach = item.details.get("multi_hop_reach")
        assert reach is None or 0.0 < reach <= 1.0
        if "multi_hop" in item.relationships:
            assert item.details["multi_hop_reach"] >= REACH_FLOOR


def test_core_pagerank_matches_networkx_and_python(tmp_path: Path) -> None:
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    connection = _graph_database(tmp_path / "curator.sqlite3")
    service = MultiHopAffinity(connection, "m")
    graph = service._graph_for("s")
    core_scores = service._walk_core(graph)
    assert core_scores == pytest.approx(_pagerank_python(graph), rel=1e-12)
    if optional_deps.nx is not None and _scipy_importable():
        assert core_scores == pytest.approx(_pagerank_networkx(graph), rel=1e-9)


@pytest.mark.parametrize(
    ("n_nodes", "density", "seed_index"),
    [(10, 0.3, 0), (50, 0.15, 1), (200, 0.05, 2), (25, 0.4, 3)],
)
def test_core_pagerank_matches_on_seeded_corpora(
    n_nodes: int, density: float, seed_index: int
) -> None:
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    rng = random.Random(1000 + seed_index)
    nodes = [f"n{index:03d}" for index in range(n_nodes)]
    adjacency: dict[str, dict[str, float]] = {}
    for node in nodes:
        edges = {
            target: rng.random() for target in nodes if target != node and rng.random() < density
        }
        if edges:
            total = sum(edges.values())
            adjacency[node] = {target: weight / total for target, weight in edges.items()}
        else:
            adjacency[node] = {}
    graph = _Graph(adjacency, nodes[seed_index % n_nodes], frozenset())
    service = MultiHopAffinity(None, "m")
    core_scores = service._walk_core(graph)
    assert core_scores == pytest.approx(_pagerank_python(graph), rel=1e-12)
    if optional_deps.nx is not None and _scipy_importable():
        assert core_scores == pytest.approx(_pagerank_networkx(graph), rel=1e-9)


def test_core_reach_matches_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if builder_module.core.core_binary() is None:
        pytest.skip("curator-core binary is not built")
    connection = _graph_database(tmp_path / "curator.sqlite3")
    service = MultiHopAffinity(connection, "m")
    real_binary = builder_module.core.core_binary
    monkeypatch.setattr(builder_module.core, "core_binary", lambda: None)
    expected = service.reach("s")
    monkeypatch.setattr(builder_module.core, "core_binary", real_binary)
    core_reach = service.reach("s")
    assert set(core_reach) == set(expected)
    for scene, score in expected.items():
        assert core_reach[scene] == pytest.approx(score, rel=1e-12)
