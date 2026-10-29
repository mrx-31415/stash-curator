-- StashDB performers the user is not into, picked in Find's "What put you
-- off?" card when the performer is not in the library. Find lowers the score
-- of every cached and future scene with them at serve time. Once a local
-- performer links to the same StashDB id, the model build counts the dislike
-- as a Why these?-style reason for that local performer (via the cached
-- external links), and Find stops applying its own penalty.
CREATE TABLE external_performer_dislike (
    endpoint TEXT NOT NULL,
    performer_id TEXT NOT NULL CHECK (performer_id <> ''),
    name TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (endpoint, performer_id)
) STRICT, WITHOUT ROWID;
