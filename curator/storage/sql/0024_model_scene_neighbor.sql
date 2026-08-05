-- Sibling of model_scene_score in the core schema, mirroring how every other MODEL_TABLES
-- entry (model_scene_score, model_scene_reason, model_scene_lane, ...) has both a core-schema
-- copy (used when no artifact is attached, e.g. tests) and an artifact-schema copy (used by
-- real published models, see curator/storage/artifacts.py MODEL_SCHEMA). Pure addition, no
-- RENAME/DROP involved, so it carries none of the temp-view rescan hazard a table rebuild
-- would (see migration 0023's comment for that story).
CREATE TABLE model_scene_neighbor (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 4),
    neighbor_scene_id TEXT NOT NULL,
    similarity REAL NOT NULL,
    weight REAL NOT NULL,
    outcome REAL NOT NULL,
    PRIMARY KEY (model_id, scene_id, rank)
) STRICT, WITHOUT ROWID;
