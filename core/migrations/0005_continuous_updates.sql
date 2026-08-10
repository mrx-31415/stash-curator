CREATE TABLE model_update_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    requested_generation INTEGER NOT NULL DEFAULT 0 CHECK (requested_generation >= 0),
    published_generation INTEGER NOT NULL DEFAULT 0 CHECK (published_generation >= 0),
    requested_at_ms INTEGER,
    last_started_at_ms INTEGER,
    last_finished_at_ms INTEGER,
    last_duration_ms INTEGER,
    last_cause TEXT,
    last_error TEXT,
    stage_timings_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

INSERT INTO model_update_state(singleton) VALUES (1);
