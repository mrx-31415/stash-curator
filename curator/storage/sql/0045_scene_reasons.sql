-- Scene reasons (Curate -> Why these?): one answer per scene card, saying
-- what makes the scene work for the user (polarity 1) or what puts them off
-- (polarity -1), with the tapped subjects as separate rows. `flipped` records
-- that the user corrected Curator's direction for the scene. Answers are
-- append-only: a client retry reuses answer_id and is ignored.

CREATE TABLE scene_reason_answer (
    answer_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    polarity INTEGER NOT NULL CHECK (polarity IN (-1, 1)),
    flipped INTEGER NOT NULL DEFAULT 0 CHECK (flipped IN (0, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0)
) STRICT;

CREATE INDEX scene_reason_answer_scene_idx ON scene_reason_answer(scene_id);

-- subject_id is '' for the scene itself ("Just this scene"). A missing_tag is
-- a tag the user says the scene shows but is not tagged with.
CREATE TABLE scene_reason (
    answer_id TEXT NOT NULL REFERENCES scene_reason_answer(answer_id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL
        CHECK (subject_type IN ('performer', 'tag', 'studio', 'missing_tag', 'scene')),
    subject_id TEXT NOT NULL,
    PRIMARY KEY (answer_id, subject_type, subject_id)
) STRICT, WITHOUT ROWID;
