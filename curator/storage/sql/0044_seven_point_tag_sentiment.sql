-- Tag sentiment gains Like and Dislike steps at +/-0.75 (a seven-point scale).
-- The value CHECKs from 0016 cannot be altered in place, so both tables are
-- rebuilt with DROP + CREATE + copy (no ALTER TABLE RENAME; see 0031). The
-- current-answer table is dropped before the history it references so the
-- implicit DELETE of DROP TABLE cannot cascade into it, and foreign keys are
-- checked at commit because history rows reference each other.

PRAGMA defer_foreign_keys = ON;

CREATE TABLE direct_tag_preference_history_copy AS
    SELECT preference_id, tag_id, value, occurred_at_ms, replaced_by_id, blocked
    FROM direct_tag_preference_history;

CREATE TABLE direct_tag_preference_copy AS
    SELECT tag_id, preference_id, value, occurred_at_ms, blocked
    FROM direct_tag_preference;

DROP TABLE direct_tag_preference;
DROP TABLE direct_tag_preference_history;

CREATE TABLE direct_tag_preference_history (
    preference_id TEXT PRIMARY KEY,
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    value REAL CHECK (value IS NULL OR value IN (-1, -0.75, -0.5, 0, 0.5, 0.75, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    replaced_by_id TEXT REFERENCES direct_tag_preference_history(preference_id),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1))
) STRICT;

CREATE INDEX direct_tag_preference_history_tag_idx
ON direct_tag_preference_history(tag_id, occurred_at_ms);

CREATE TABLE direct_tag_preference (
    tag_id TEXT PRIMARY KEY REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    preference_id TEXT NOT NULL UNIQUE
        REFERENCES direct_tag_preference_history(preference_id) ON DELETE CASCADE,
    value REAL NOT NULL CHECK (value IN (-1, -0.75, -0.5, 0, 0.5, 0.75, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1))
) STRICT, WITHOUT ROWID;

INSERT INTO direct_tag_preference_history (
    preference_id, tag_id, value, occurred_at_ms, replaced_by_id, blocked
)
    SELECT preference_id, tag_id, value, occurred_at_ms, replaced_by_id, blocked
    FROM direct_tag_preference_history_copy;

INSERT INTO direct_tag_preference (tag_id, preference_id, value, occurred_at_ms, blocked)
    SELECT tag_id, preference_id, value, occurred_at_ms, blocked
    FROM direct_tag_preference_copy;

DROP TABLE direct_tag_preference_copy;
DROP TABLE direct_tag_preference_history_copy;
