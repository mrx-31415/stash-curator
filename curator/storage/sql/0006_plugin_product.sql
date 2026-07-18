CREATE TABLE curator_config (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    config_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) STRICT;

INSERT INTO curator_config(singleton, updated_at_ms) VALUES (1, 0);

CREATE TABLE curator_job (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed')),
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    finished_at_ms INTEGER CHECK (finished_at_ms IS NULL OR finished_at_ms >= started_at_ms),
    summary_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
) STRICT;

CREATE INDEX curator_job_started_idx ON curator_job(started_at_ms DESC);
