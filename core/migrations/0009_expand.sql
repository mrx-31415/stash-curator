CREATE TABLE external_entity (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('scene', 'performer')),
    external_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    score REAL NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    fetched_at_ms INTEGER NOT NULL CHECK (fetched_at_ms >= 0),
    PRIMARY KEY (entity_type, external_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX external_entity_score_idx
ON external_entity(entity_type, score DESC);

CREATE TABLE expand_cache (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    model_id TEXT NOT NULL,
    fetched_at_ms INTEGER NOT NULL CHECK (fetched_at_ms >= 0),
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms >= fetched_at_ms),
    scene_count INTEGER NOT NULL CHECK (scene_count >= 0),
    performer_count INTEGER NOT NULL CHECK (performer_count >= 0)
) STRICT;
