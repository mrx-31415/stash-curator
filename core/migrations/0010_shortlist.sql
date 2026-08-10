CREATE TABLE external_shortlist (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('scene', 'performer')),
    external_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    score REAL NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    added_at_ms INTEGER NOT NULL CHECK (added_at_ms >= 0),
    PRIMARY KEY (entity_type, external_id)
) STRICT, WITHOUT ROWID;
