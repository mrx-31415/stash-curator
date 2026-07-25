CREATE TABLE model_lane_order (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (
        lane IN ('for_you', 'best_bets', 'revisit', 'discover', 'adventure')
    ),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first', 'varied')),
    position INTEGER NOT NULL CHECK (position >= 0),
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    source_lane TEXT NOT NULL CHECK (
        source_lane IN ('best_bets', 'revisit', 'discover', 'adventure')
    ),
    utility REAL NOT NULL,
    ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX model_lane_order_scene_idx
ON model_lane_order(model_id, scene_id);

CREATE TABLE model_lane_order_state (
    model_id TEXT PRIMARY KEY REFERENCES model_version(model_id) ON DELETE CASCADE,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
