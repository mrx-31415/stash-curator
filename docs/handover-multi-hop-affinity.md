# Multi-hop affinity handover

Updated: 2026-08-07 — slice 2 complete (tag/studio bridges + ranking blend).

## Goal

Add a graph-based "multi-hop affinity" signal: personalized PageRank with restart
over the performer-collaboration graph, so Similar can rank scenes connected to the
target through chains of similar performers — even when no performer is shared
directly. Today's Similar is pairwise (shared performers, single-pair profile
similarity); multi-hop captures *connectivity evidence* (multiple independent paths)
and *recursive reach* (A→P1→Q→P2→B).

## Architecture

### Graph

Nodes: published scenes, library performers with positive learned identity affinity,
studios, and (for the seed scene only) tags.

Edges, by source node type:

- **seed scene** → its tags (fixed weight 0.15), its studio (0.3), its affinity
  performers (effective affinity weight, bidirectional). Tags bootstrap the
  candidate pool — they find scenes of a similar type to the seed.
- **reached scenes** → their affinity performers (bidirectional) and their studio
  (0.3). They do NOT bridge through their own tags — tags are a discovery mechanism
  for the seed only, not a general-purpose mesh.
- **performers** → similar performers (similarity³ weight, top-3 matches per
  performer, persisted from the build). This is the non-trivial structural edge:
  profile-based similarity between performers.
- **performers** → ALL their model scenes (effective affinity weight). Chain
  performers expand to their full filmography so the walk can discover through them.

The walk is: seed tags find the neighborhood → reached scenes' performers carry the
walk forward through profile-similarity → their scenes → their studios → further.

### Persistence

New model table `model_performer_edge` (core migration `0025_model_performer_edge`
plus the artifact `MODEL_SCHEMA` copy, mirroring `model_scene_neighbor`). To avoid
shadowing migrations on upgrades, `attach_active_artifacts` and `activate_artifact`
now create temp views only for tables the artifact actually has (filtered against
`alias.sqlite_master`).

MODEL_BUILD_VERSION bumped 4→5.

### Query-time engine

`curator/model/multi_hop.py`: personalized PageRank (RWR, damping 0.85) on the
walkable subgraph. The graph is naturally small because only positive-affinity
performers and their scenes participate. `networkx.pagerank` (which requires scipy)
runs when both are importable; a pure-Python power iteration implements the same
recurrence otherwise — parity-tested, deterministic.

### Surface

`SimilarityService.scenes()` blends multi-hop reach into `rank_score` with a fixed
weight (0.05). Reachable candidates gain a `multi_hop` relationship and a
`multi_hop_reach` detail. The JS renders "Multi-hop" in the relationship label.

### Fixed heuristics

- DAMPING = 0.85, MAX_ITERATIONS = 100, TOLERANCE = 1e-6
- TOP_K = 50, REACH_FLOOR = 1e-6 (scaled for studio/tag-expanded graphs)
- AFFINITY_CUTOFF = 0.005 (positive only)
- STUDIO_WEIGHT = 0.3, TAG_WEIGHT = 0.15
- MULTI_HOP_BLEND_WEIGHT = 0.05

## Required checks

- Parsistence parity: publish writes model_performer_edge rows matching the build's
  top-3 matches.
- Engine tests: reach on a hand-built graph, determinism, networkx/pure-python
  parity.
- Integration: rank_score formula includes the multi-hop blend, graceful when the
  graph produces no reach.
- Attach safety: an older artifact missing the new table must not shadow it during
  migrations (`test_attach_skips_tables_missing_from_older_artifact`).
- `scripts/verify full` passes.

## Next steps

- scipy: `cKDTree` for content-neighbor lookup in Similar (replace O(n²) search);
  `scipy.cluster` for discovery-lane variety.
- Performer Hunt multi-hop seeding: rank a similar performer's StashDB catalog by
  graph reach.
- Calibrate blend weight and tag/studio edge weights with installed measurement.
