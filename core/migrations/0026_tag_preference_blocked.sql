-- Add a `blocked` flag to direct tag preferences so a Block / Never level
-- can hard-exclude scenes carrying the tag while leaving the five-point weight
-- scale (-1, -0.5, 0, 0.5, 1) untouched.
ALTER TABLE direct_tag_preference_history ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1));
ALTER TABLE direct_tag_preference ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1));
