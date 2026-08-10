"""Personalized multi-hop affinity over the performer-collaboration graph.

The model build already derives, for every library performer, the few performers
most similar to the known-affinity set (see PreferenceModelBuilder.
_performer_similarity_scores). Those matches are persisted as model_performer_edge,
so a query-time random walk with restart can rank scenes by *connectivity* through
the performer graph: seed scene -> its liked performers -> similar performers ->
their scenes. That reach is a different signal from the pairwise similarity in
SimilarityService: it aggregates every path between the seed and a candidate
instead of taking the single best performer pair, and it can cross two performer
edges (A stars P1, P1 ~ P2, P2 ~ P3, candidate stars P3) that pairwise scoring
cannot see.

The walkable graph is naturally small: membership edges exist only for performers
with a positive learned identity affinity (a bounded set), and every performer's
similar matches are drawn from that same set, so the performer node set is the
affinity set itself. The accelerated path uses networkx.pagerank (which requires
scipy); the pure-Python power iteration implements the same recurrence, so results
match in either mode.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from curator import core, optional_deps
from curator.profiling import current_trace

DAMPING = 0.85
MAX_ITERATIONS = 100
TOLERANCE = 1e-6
TOP_K = 50
# Minimum PageRank score for a scene to count as reachable. With performer-only
# graphs (~15 nodes) this was 1e-3; studio/tag bridges grow the graph to hundreds
# of nodes and the absolute score floor must be low enough to not exclude the
# diluted-but-still-positive reach. TOP_K already caps the result set.
REACH_FLOOR = 1e-6
# Mirrors PreferenceModelBuilder.PERFORMER_SIMILARITY_AFFINITY_CUTOFF: below this,
# a learned identity affinity is too weak to carry reach.
AFFINITY_CUTOFF = 0.005
# Fixed edge weights for non-performer node types in the walkable graph.
# Scene—performer edges use the learned identity affinity (bounded, positive only);
# performer—performer edges use similarity³ (the build's propagation weighting).
# Studios and tags carry a lower fixed weight so they act as secondary bridges.
STUDIO_WEIGHT = 0.3
TAG_WEIGHT = 0.15


@dataclass(frozen=True)
class _Graph:
    """Deterministic weighted directed adjacency, outgoing weights row-normalized."""

    adjacency: dict[str, dict[str, float]]
    seed: str
    scenes: frozenset[str]


def _normalize(edges: list[tuple[str, float]]) -> dict[str, float]:
    total = sum(weight for _, weight in edges)
    if total <= 0:
        return {}
    return {target: weight / total for target, weight in edges}


class MultiHopAffinity:
    """Random walk with restart over the persisted performer-collaboration graph."""

    def __init__(self, connection: sqlite3.Connection, model_id: str) -> None:
        self.connection = connection
        self.model_id = model_id
        self._affinity: dict[str, float] = {}
        self._edges: dict[str, list[tuple[str, float]]] = {}
        self._scene_performers: dict[str, tuple[str, ...]] = {}
        self._performer_scenes: dict[str, tuple[str, ...]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        connection = self.connection
        affinity: dict[str, float] = {}
        for row in connection.execute(
            """
            SELECT fd.name, fa.affinity, fa.confidence
            FROM feature_affinity fa
            JOIN feature_definition fd ON fd.feature_id = fa.feature_id
            WHERE fa.model_id=? AND fd.family='performer_identity'
                AND fd.name LIKE 'performer:%'
            """,
            (self.model_id,),
        ):
            effective = float(row["affinity"]) * float(row["confidence"])
            if effective >= AFFINITY_CUTOFF:
                affinity[str(row["name"]).removeprefix("performer:")] = effective
        self._affinity = affinity
        if not affinity:
            return
        # The walk only ever reaches performers in the positive-affinity set: seeds
        # come from membership, and similar matches are drawn from the known-
        # affinity set, so edges and membership are loaded only for that set.
        placeholders = ", ".join("?" for _ in affinity)
        parameters = tuple(affinity)
        edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for row in connection.execute(
            f"""
            SELECT performer_id, similar_performer_id, similarity
            FROM model_performer_edge
            WHERE model_id=? AND performer_id IN ({placeholders})
            ORDER BY performer_id, rank
            """,
            (self.model_id, *parameters),
        ):
            edges[str(row["performer_id"])].append(
                (str(row["similar_performer_id"]), float(row["similarity"]) ** 3)
            )
        self._edges = dict(edges)
        membership: dict[str, set[str]] = defaultdict(set)
        for row in connection.execute(
            f"""
            SELECT scene_id, performer_id FROM scene_performer
            WHERE performer_id IN ({placeholders}) ORDER BY scene_id, performer_id
            """,
            parameters,
        ):
            membership[str(row["scene_id"])].add(str(row["performer_id"]))
        self._scene_performers = {
            scene_id: tuple(sorted(performers)) for scene_id, performers in membership.items()
        }
        by_performer: dict[str, set[str]] = defaultdict(set)
        for scene_id, performers in self._scene_performers.items():
            for performer in performers:
                by_performer[performer].add(scene_id)
        self._performer_scenes = {
            performer: tuple(sorted(scenes)) for performer, scenes in by_performer.items()
        }
        # Studio and tag memberships for scenes in the walkable graph: loaded once
        # per model so _graph can add their bridge nodes without per-request queries.
        walkable_scenes = tuple(self._scene_performers)
        if not walkable_scenes:
            self._scene_studios: dict[str, str | None] = {}
            self._scene_tags: dict[str, tuple[str, ...]] = {}
            return
        scene_placeholders = ", ".join("?" for _ in walkable_scenes)
        self._scene_studios = {}
        for row in connection.execute(
            f"""
            SELECT scene_id, studio_id FROM source_scene
            WHERE scene_id IN ({scene_placeholders}) AND studio_id IS NOT NULL
            """,
            walkable_scenes,
        ):
            self._scene_studios[str(row["scene_id"])] = str(row["studio_id"])
        scene_tags: dict[str, set[str]] = defaultdict(set)
        for row in connection.execute(
            f"""
            SELECT st.scene_id, st.tag_id FROM scene_tag st
            WHERE st.scene_id IN ({scene_placeholders})
            ORDER BY st.scene_id, st.tag_id
            """,
            walkable_scenes,
        ):
            scene_tags[str(row["scene_id"])].add(str(row["tag_id"]))
        self._scene_tags = {scene: tuple(sorted(tags)) for scene, tags in scene_tags.items()}

    def _graph(self, seed_scene: str) -> _Graph:
        """Walkable subgraph reachable from the seed scene.

        Membership edges connect the seed to its affinity performers; performer
        edges connect affinity performers to their similar matches; each reached
        performer reconnects to all of their model scenes, which is what lets a
        walk cross performer chains and land on scenes the seed does not share.
        """
        self._load()
        adjacency: dict[str, dict[str, float]] = defaultdict(dict)
        seeds = self._scene_performers.get(seed_scene, ())
        for performer in seeds:
            weight = self._affinity[performer]
            adjacency.setdefault(seed_scene, {})[performer] = weight
            adjacency.setdefault(performer, {})[seed_scene] = weight
        frontier = list(seeds)
        # Performer chains: mass on a reached performer flows to their similar
        # matches (and from there to *their* scenes), bounded by the affinity set.
        seen: set[str] = set(frontier)
        while frontier:
            performer = frontier.pop(0)
            for similar, similarity in self._edges.get(performer, ()):
                adjacency.setdefault(performer, {})[similar] = similarity
                if similar in seen:
                    continue
                seen.add(similar)
                weight = self._affinity.get(similar, 0.0)
                for scene in self._performer_scenes.get(similar, ()):
                    adjacency.setdefault(similar, {})[scene] = weight
                frontier.append(similar)
        return self._finalize_graph(adjacency, seed_scene)

    def reach(self, scene_id: str) -> dict[str, float]:
        """Personalized PageRank seeded at ``scene_id``; ranked reachable scenes.

        Returns {scene_id: score} for the top scenes excluding the seed, with
        scores at or above REACH_FLOOR. Deterministic in both engine modes.
        """
        scores = self._walk(scene_id)
        ranked = sorted(
            (
                scene
                for scene in scores
                if scene in self._scene_performers
                and scene != scene_id
                and scores[scene] >= REACH_FLOOR
            ),
            key=lambda scene: (-scores[scene], scene),
        )[:TOP_K]
        return {scene: scores[scene] for scene in ranked}

    def performer_reach(self, seed_id: str, target_performer_ids: set[str]) -> dict[str, float]:
        """Graph reach scores for specific performers, seeded at ``seed_id``
        (a scene or performer). Used by remote discovery to score StashDB
        scenes by how connected their linked performers are."""
        scores = self._walk(seed_id)
        return {
            performer_id: scores[performer_id]
            for performer_id in target_performer_ids
            if performer_id in scores and scores[performer_id] >= REACH_FLOOR
        }

    def _walk(self, seed_id: str) -> dict[str, float]:
        """Raw PageRank scores for all nodes, seeded at a scene or performer."""
        self._load()
        graph = self._graph_for(seed_id)
        if len(graph.adjacency) < 2:
            return {}
        if core.core_binary() is not None:
            return self._walk_core(graph)
        nx = optional_deps.nx
        if nx is not None and _scipy_available():
            return _pagerank_networkx(graph)
        return _pagerank_python(graph)

    def _walk_core(self, graph: _Graph) -> dict[str, float]:
        """PageRank via the compiled core (networkx's role).

        The walkable graph is built here (sidecar reads + seed resolution); the
        binary only runs the power iteration over the row-stochastic adjacency,
        mirroring the pure-Python recurrence bit-for-bit.
        """
        response = core.run_core(
            "multi-hop",
            {
                "adjacency": {node: dict(edges) for node, edges in graph.adjacency.items()},
                "seed": graph.seed,
                "damping": DAMPING,
                "max_iterations": MAX_ITERATIONS,
                "tolerance": TOLERANCE,
            },
            profile=current_trace() is not None,
        )
        return {str(node): float(score) for node, score in cast(dict[str, Any], response).items()}

    def _graph_for(self, seed_id: str) -> _Graph:
        """Walkable graph seeded at a scene or performer node."""
        self._load()
        adjacency: dict[str, dict[str, float]] = defaultdict(dict)
        if seed_id in self._scene_performers:
            return self._graph(seed_id)
        if seed_id not in self._affinity:
            return _Graph({}, seed_id, frozenset())
        # Performer seed: add membership edges to their scenes, then proceed
        # with performer chains exactly as for a scene seed.
        weight = self._affinity[seed_id]
        for scene in self._performer_scenes.get(seed_id, ()):
            adjacency.setdefault(seed_id, {})[scene] = weight
            adjacency.setdefault(scene, {})[seed_id] = weight
        frontier = [seed_id]
        seen: set[str] = {seed_id}
        while frontier:
            performer = frontier.pop(0)
            for similar, similarity in self._edges.get(performer, ()):
                adjacency.setdefault(performer, {})[similar] = similarity
                if similar in seen:
                    continue
                seen.add(similar)
                w = self._affinity.get(similar, 0.0)
                for scene in self._performer_scenes.get(similar, ()):
                    adjacency.setdefault(similar, {})[scene] = w
                frontier.append(similar)
        return self._finalize_graph(adjacency, seed_id)

    def _finalize_graph(self, adjacency: dict[str, dict[str, float]], seed_id: str) -> _Graph:
        """Add tag/studio bridges, normalize, and return the finalized graph."""
        # Secondary bridges for scene nodes in the graph.
        for node in list(adjacency):
            if node not in self._scene_performers:
                continue
            studio = self._scene_studios.get(node)
            if studio is not None:
                studio_node = f"studio:{studio}"
                adjacency.setdefault(node, {})[studio_node] = STUDIO_WEIGHT
                adjacency.setdefault(studio_node, {})[node] = STUDIO_WEIGHT
            # Only the seed bridges through its tags — reached scenes use their
            # performers and studio, not their tags.
            if node != seed_id:
                continue
            for tag_id in self._scene_tags.get(node, ()):
                tag_node = f"tag:{tag_id}"
                adjacency.setdefault(node, {})[tag_node] = TAG_WEIGHT
                adjacency.setdefault(tag_node, {})[node] = TAG_WEIGHT
        # Mass conservation: every edge target must be a node.
        for edges in list(adjacency.values()):
            for target in edges:
                adjacency.setdefault(target, {})
        for node, edges in adjacency.items():
            if node == seed_id:
                adjacency[seed_id] = _normalize(sorted(edges.items()))
                continue
            adjacency[node] = _normalize(sorted(edges.items()))
        return _Graph(dict(adjacency), seed_id, frozenset(self._scene_performers))


def _scipy_available() -> bool:
    """networkx.pagerank dispatches to its scipy backend; without scipy we use the
    pure-Python power iteration instead."""
    try:
        import scipy  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False
    return True


def _pagerank_networkx(graph: _Graph) -> dict[str, float]:
    """networkx.pagerank (scipy backend) over the pre-normalized adjacency.

    Weights are already row-stochastic, so the sparse transition matrix matches the
    pure-Python recurrence and both engines converge to the same fixed point.
    """
    import networkx as nx  # type: ignore[import-untyped]

    directed = nx.DiGraph()
    directed.add_nodes_from(sorted(graph.adjacency))
    for node, edges in graph.adjacency.items():
        for target, weight in edges.items():
            directed.add_edge(node, target, weight=weight)
    scores: dict[str, float] = nx.pagerank(
        directed,
        alpha=DAMPING,
        personalization={graph.seed: 1.0},
        max_iter=MAX_ITERATIONS,
        tol=TOLERANCE,
    )
    return scores


def _pagerank_python(graph: _Graph) -> dict[str, float]:
    """Power iteration over the same recurrence as the networkx path.

    v' = alpha * row-stochastic(A) @ v + (1 - alpha) * personalization, with
    dangling mass returned to the seed (personalization), matching networkx's
    dangling handling so both engines converge to the same fixed point.
    """
    adjacency = graph.adjacency
    seed = graph.seed
    nodes = sorted(adjacency)
    dangling = [node for node in nodes if not adjacency[node]]
    x = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(MAX_ITERATIONS):
        xlast = x
        x = {node: 0.0 for node in nodes}
        danglesum = DAMPING * sum(xlast[node] for node in dangling)
        for node in nodes:
            for target, weight in adjacency[node].items():
                x[target] += DAMPING * xlast[node] * weight
            x[node] += danglesum * (1.0 if node == seed else 0.0)
            if node == seed:
                x[node] += 1.0 - DAMPING
        error = sum(abs(x[node] - xlast[node]) for node in nodes)
        if error < len(nodes) * TOLERANCE:
            break
    return x
