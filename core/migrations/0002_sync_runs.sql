ALTER TABLE source_performer ADD COLUMN gender TEXT;
ALTER TABLE source_performer ADD COLUMN rating100 INTEGER CHECK (rating100 BETWEEN 0 AND 100);

ALTER TABLE source_studio ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1));
ALTER TABLE source_studio ADD COLUMN rating100 INTEGER CHECK (rating100 BETWEEN 0 AND 100);

CREATE TABLE performer_tag (
    performer_id TEXT NOT NULL REFERENCES source_performer(performer_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (performer_id, tag_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX performer_tag_tag_idx ON performer_tag(tag_id);

CREATE TABLE sync_run (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('incremental', 'full')),
    state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed')),
    server_version TEXT,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    completed_at_ms INTEGER CHECK (completed_at_ms IS NULL OR completed_at_ms >= started_at_ms),
    error TEXT
) STRICT;

ALTER TABLE sync_cursor ADD COLUMN run_id TEXT REFERENCES sync_run(run_id);
ALTER TABLE sync_cursor ADD COLUMN baseline_watermark TEXT;
ALTER TABLE sync_cursor ADD COLUMN pending_watermark TEXT;

CREATE TABLE sync_seen (
    run_id TEXT NOT NULL REFERENCES sync_run(run_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (run_id, entity_type, entity_id)
) STRICT, WITHOUT ROWID;
