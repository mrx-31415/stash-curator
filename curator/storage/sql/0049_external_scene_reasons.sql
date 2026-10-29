-- "What put you off?" answers for StashDB scenes dismissed in Find. The scene
-- is not in the library, so the answer cannot reference source_scene the way
-- scene_reason_answer does; the tapped local performers, tags, and studios
-- feed the same per-subject reason evidence as Why these? answers. There are
-- no scene-level subjects: an external scene never becomes a scene label.
-- Answers are append-only: a client retry reuses answer_id and is ignored.
CREATE TABLE external_scene_reason_answer (
    answer_id TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    external_id TEXT NOT NULL,
    polarity INTEGER NOT NULL CHECK (polarity IN (-1, 1)),
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0)
) STRICT;

CREATE TABLE external_scene_reason (
    answer_id TEXT NOT NULL
        REFERENCES external_scene_reason_answer(answer_id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('performer', 'tag', 'studio')),
    subject_id TEXT NOT NULL CHECK (subject_id <> ''),
    PRIMARY KEY (answer_id, subject_type, subject_id)
) STRICT, WITHOUT ROWID;
