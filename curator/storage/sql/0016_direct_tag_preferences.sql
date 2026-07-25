CREATE TABLE direct_tag_preference_history (
    preference_id TEXT PRIMARY KEY,
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    value REAL CHECK (value IS NULL OR value IN (-1, -0.5, 0, 0.5, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    replaced_by_id TEXT REFERENCES direct_tag_preference_history(preference_id)
) STRICT;

CREATE INDEX direct_tag_preference_history_tag_idx
ON direct_tag_preference_history(tag_id, occurred_at_ms);

CREATE TABLE direct_tag_preference (
    tag_id TEXT PRIMARY KEY REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    preference_id TEXT NOT NULL UNIQUE
        REFERENCES direct_tag_preference_history(preference_id) ON DELETE CASCADE,
    value REAL NOT NULL CHECK (value IN (-1, -0.5, 0, 0.5, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0)
) STRICT, WITHOUT ROWID;
