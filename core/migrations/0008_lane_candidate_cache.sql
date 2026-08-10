CREATE TABLE model_lane_candidate_cache (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (lane IN ('best_bets', 'revisit', 'discover', 'adventure')),
    candidates_json TEXT NOT NULL,
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (model_id, lane)
) STRICT, WITHOUT ROWID;
