-- Scene dismissals for StashDB results in Find (Expand, StashDB Similar,
-- Performer Hunt). External scenes have no local scene id, so they cannot use
-- the feedback table and never train the model directly; a dismissal only
-- hides the scene from Find. 'not_now' rows carry an expiry, 'not_interested'
-- rows do not. payload_json snapshots the cached StashDB payload so Feedback
-- history can show the scene after it leaves the Expand cache.
CREATE TABLE external_dismissal (
    endpoint TEXT NOT NULL,
    external_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('not_interested', 'not_now')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    expires_at_ms INTEGER CHECK (expires_at_ms IS NULL OR expires_at_ms >= created_at_ms),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (endpoint, external_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX external_dismissal_created_idx ON external_dismissal(endpoint, created_at_ms);
