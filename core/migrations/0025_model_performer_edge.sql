-- Multi-hop affinity graph: the top similar-performer matches the build derives
-- during performer-similarity propagation, persisted so query-time personalized
-- PageRank can walk the performer-collaboration graph without recomputing pairwise
-- profile similarity. Sibling of model_scene_neighbor in the core schema, mirroring
-- how every other MODEL_TABLES entry has both a core-schema copy (used when no
-- artifact is attached, e.g. tests) and an artifact-schema copy (used by real
-- published models, see curator/storage/artifacts.py MODEL_SCHEMA).
CREATE TABLE model_performer_edge (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    performer_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 2),
    similar_performer_id TEXT NOT NULL,
    similarity REAL NOT NULL,
    affinity REAL NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (model_id, performer_id, rank)
) STRICT, WITHOUT ROWID;

CREATE INDEX model_performer_edge_similar_idx
ON model_performer_edge(model_id, similar_performer_id);
