-- Rolling Whisparr search: StashDB scenes Curator searches for on a paced
-- schedule until Whisparr has them, so a bulk send never fires one indexer
-- search per scene at once and a release that appears later is still found.
-- state: 'active' (in the rotation), 'done' (Whisparr has the file or the
-- scene is in the library), 'gave_up' (not found within the give-up window),
-- or 'stopped' (taken out of the rotation by the user).
CREATE TABLE whisparr_search (
    external_id TEXT PRIMARY KEY,
    whisparr_id INTEGER NOT NULL CHECK (whisparr_id > 0),
    added_at_ms INTEGER NOT NULL CHECK (added_at_ms >= 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_searched_at_ms INTEGER CHECK (last_searched_at_ms IS NULL OR last_searched_at_ms >= 0),
    next_due_at_ms INTEGER NOT NULL CHECK (next_due_at_ms >= 0),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'done', 'gave_up', 'stopped')),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) STRICT, WITHOUT ROWID;

CREATE INDEX whisparr_search_due ON whisparr_search(state, next_due_at_ms);

-- The sweep's own pacing: when it last ran, and until when it waits because
-- Whisparr reported indexers in backoff (or could not be reached).
CREATE TABLE whisparr_sweep (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_run_at_ms INTEGER NOT NULL DEFAULT 0 CHECK (last_run_at_ms >= 0),
    paused_until_ms INTEGER NOT NULL DEFAULT 0 CHECK (paused_until_ms >= 0),
    last_error TEXT
) STRICT;
