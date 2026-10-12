CREATE TABLE local_scene_match (
    scene_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('stashdb_id', 'phash')),
    value TEXT NOT NULL,
    PRIMARY KEY (scene_id, kind, value)
) STRICT, WITHOUT ROWID;

CREATE INDEX local_scene_match_value_idx ON local_scene_match(kind, value, scene_id);

CREATE TABLE local_scene_match_pending (
    scene_id TEXT PRIMARY KEY,
    revision TEXT NOT NULL
) STRICT;
