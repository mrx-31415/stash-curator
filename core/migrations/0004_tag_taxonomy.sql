CREATE TABLE source_tag_stash_id (
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    stash_id TEXT NOT NULL,
    PRIMARY KEY (tag_id, endpoint)
) STRICT, WITHOUT ROWID;

CREATE INDEX source_tag_stash_id_external_idx
ON source_tag_stash_id(endpoint, stash_id);

CREATE TABLE taxonomy_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    fetched_at_ms INTEGER NOT NULL CHECK (fetched_at_ms >= 0),
    category_count INTEGER NOT NULL CHECK (category_count >= 0),
    tag_count INTEGER NOT NULL CHECK (tag_count >= 0)
) STRICT;

CREATE TABLE taxonomy_category (
    snapshot_id TEXT NOT NULL REFERENCES taxonomy_snapshot(snapshot_id) ON DELETE CASCADE,
    category_id TEXT NOT NULL,
    name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    description TEXT,
    PRIMARY KEY (snapshot_id, category_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE taxonomy_tag (
    snapshot_id TEXT NOT NULL REFERENCES taxonomy_snapshot(snapshot_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category_id TEXT,
    PRIMARY KEY (snapshot_id, tag_id),
    FOREIGN KEY (snapshot_id, category_id)
        REFERENCES taxonomy_category(snapshot_id, category_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE taxonomy_tag_alias (
    snapshot_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, tag_id, alias),
    FOREIGN KEY (snapshot_id, tag_id)
        REFERENCES taxonomy_tag(snapshot_id, tag_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE TABLE tag_taxonomy_match (
    local_tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES taxonomy_snapshot(snapshot_id) ON DELETE CASCADE,
    external_tag_id TEXT,
    external_category_id TEXT,
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    ambiguity_count INTEGER NOT NULL DEFAULT 0 CHECK (ambiguity_count >= 0),
    PRIMARY KEY (local_tag_id, snapshot_id)
) STRICT, WITHOUT ROWID;
