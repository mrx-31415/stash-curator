-- Background task queue for the Curator-owned worker
-- (docs/decisions/004-background-task-worker.md): 'queued'/'cancelled'
-- lifecycle states, worker ownership + heartbeat, the enqueue payload
-- snapshot, the cooperative-cancel flag, and live progress. The old state
-- CHECK cannot be altered in place, so the table is rebuilt.
--
-- The rebuild deliberately avoids ALTER TABLE RENAME: with a published
-- generation attached, SQLite's RENAME rescans the schema and trips a real
-- bug on the attached temp views' shadowed names ("views may not be
-- indexed"). DROP + CREATE + copy has no such dependency (see
-- test_cascade_migration_survives_attached_generation_temp_views).

CREATE TABLE curator_job_new (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'complete', 'failed', 'cancelled')),
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    finished_at_ms INTEGER CHECK (finished_at_ms IS NULL OR finished_at_ms >= started_at_ms),
    summary_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    queued_at_ms INTEGER CHECK (queued_at_ms IS NULL OR queued_at_ms >= 0),
    heartbeat_at_ms INTEGER CHECK (heartbeat_at_ms IS NULL OR heartbeat_at_ms >= 0),
    owner_pid INTEGER,
    payload_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    progress REAL CHECK (progress IS NULL OR (progress >= 0.0 AND progress <= 1.0))
) STRICT;

INSERT INTO curator_job_new (job_id, job_type, state, started_at_ms, finished_at_ms, summary_json, error)
    SELECT job_id, job_type, state, started_at_ms, finished_at_ms, summary_json, error
    FROM curator_job;

DROP TABLE curator_job;

CREATE TABLE curator_job (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'complete', 'failed', 'cancelled')),
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    finished_at_ms INTEGER CHECK (finished_at_ms IS NULL OR finished_at_ms >= started_at_ms),
    summary_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    queued_at_ms INTEGER CHECK (queued_at_ms IS NULL OR queued_at_ms >= 0),
    heartbeat_at_ms INTEGER CHECK (heartbeat_at_ms IS NULL OR heartbeat_at_ms >= 0),
    owner_pid INTEGER,
    payload_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    progress REAL CHECK (progress IS NULL OR (progress >= 0.0 AND progress <= 1.0))
) STRICT;

INSERT INTO curator_job (job_id, job_type, state, started_at_ms, finished_at_ms, summary_json, error,
    queued_at_ms, heartbeat_at_ms, owner_pid, payload_json, cancel_requested, progress)
    SELECT job_id, job_type, state, started_at_ms, finished_at_ms, summary_json, error,
        queued_at_ms, heartbeat_at_ms, owner_pid, payload_json, cancel_requested, progress
    FROM curator_job_new;

DROP TABLE curator_job_new;

CREATE INDEX curator_job_started_idx ON curator_job(started_at_ms DESC);
CREATE INDEX curator_job_queue_idx ON curator_job(state, queued_at_ms);
