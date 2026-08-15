-- Pairwise pick rounds: two-card comparisons ("which do you prefer?") whose
-- winner/loser labels feed the model with smooth, matching-free decomposition
-- (shared features cancel in the affinity accumulation; differing features get
-- weighted). Pairs are chosen deterministically by an information score
-- (model-conflict x coverage x dimension-fit); selection_probability is the
-- normalized score share, used later for inverse-propensity weighting of the
-- labels. curation_pair_elo is optional steering state for pair selection
-- (updated on submit, never a model input).

CREATE TABLE curation_pair (
    pair_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,
    scene_a TEXT NOT NULL,
    scene_b TEXT NOT NULL,
    dimension TEXT NOT NULL
        CHECK (dimension IN ('tag', 'performer', 'studio', 'orthogonal')),
    selection_probability REAL NOT NULL
        CHECK (selection_probability > 0 AND selection_probability <= 1),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'answered', 'skipped', 'superseded')),
    winner TEXT CHECK (winner IN ('a', 'b')),
    occurred_at_ms INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX curation_pair_round_idx ON curation_pair(round_id, status);

CREATE TABLE curation_pair_elo (
    scene_id TEXT PRIMARY KEY,
    elo REAL NOT NULL,
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) STRICT;
