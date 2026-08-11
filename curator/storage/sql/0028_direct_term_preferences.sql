-- Direct description-term preferences: a five-point rating plus an optional
-- hard block for the description tokens the model already builds as
-- `desc:<term>` content features. Terms are library-relative tokens from the
-- same tokenizer (lowercase [a-zA-Z]{3,}, stopword-filtered, TF-IDF-capped);
-- unlike tags they have no source table, so `term` is stored as plain text.
-- The shape mirrors 0016/0026 (append-only history + current row, fixed
-- five-point scale, blocked flag) so the preference queue, staleness
-- replacement, and model-rebuild trigger behave identically to tags. A
-- blocked entry stores value -1 and the blocked flag drives hard exclusion.

CREATE TABLE direct_term_preference_history (
    preference_id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    value REAL CHECK (value IS NULL OR value IN (-1, -0.5, 0, 0.5, 1)),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    replaced_by_id TEXT REFERENCES direct_term_preference_history(preference_id)
) STRICT;

CREATE INDEX direct_term_preference_history_term_idx
ON direct_term_preference_history(term, occurred_at_ms);

CREATE TABLE direct_term_preference (
    term TEXT PRIMARY KEY,
    preference_id TEXT NOT NULL UNIQUE
        REFERENCES direct_term_preference_history(preference_id) ON DELETE CASCADE,
    value REAL NOT NULL CHECK (value IN (-1, -0.5, 0, 0.5, 1)),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0)
) STRICT, WITHOUT ROWID;
