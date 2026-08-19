-- Stage 3 of the lane redesign (docs/workpackage-lane-redesign.md): the new
-- Dormant lane joins the rotation. Same shape as migrations 0034/0035: every
-- lane/source_lane CHECK constraint enumerating the lane list cannot be
-- altered in place, so each table carrying one is rebuilt again to admit
-- 'dormant': model_scene_lane, model_lane_candidate_cache, and
-- model_lane_order + model_lane_order_state.
--
-- No data migration: model_entity_dormancy (migration 0036) has no rows yet
-- for any existing model (it's a new build-time pass), so no scene could
-- have classified into 'dormant' before this migration regardless.
--
-- main-qualified and shadow-view handling: see migration 0034 for the full
-- explanation.

DROP VIEW IF EXISTS temp.model_scene_lane;
DROP TABLE main.model_scene_lane;

CREATE TABLE main.model_scene_lane (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (
        lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant')
    ),
    subtype TEXT,
    lane_value REAL NOT NULL,
    qualification_json TEXT NOT NULL DEFAULT '{}',
    appeal REAL,
    PRIMARY KEY (model_id, scene_id, lane)
) STRICT, WITHOUT ROWID;

CREATE INDEX model_scene_lane_value_idx
ON model_scene_lane(model_id, lane, lane_value DESC);

CREATE INDEX model_scene_lane_appeal_idx
ON model_scene_lane(model_id, scene_id, appeal);

DROP TABLE main.model_lane_candidate_cache;

CREATE TABLE main.model_lane_candidate_cache (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (
        lane IN ('best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant')
    ),
    candidates_json TEXT NOT NULL,
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (model_id, lane)
) STRICT, WITHOUT ROWID;

DROP TABLE main.model_lane_order;
DROP TABLE main.model_lane_order_state;

CREATE TABLE main.model_lane_order (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (
        lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant')
    ),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first', 'varied')),
    position INTEGER NOT NULL CHECK (position >= 0),
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    source_lane TEXT NOT NULL CHECK (
        source_lane IN ('best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant')
    ),
    utility REAL NOT NULL,
    ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;

-- No scene_id index: migration 0017 dropped model_lane_order_scene_idx as
-- unused; this rebuild carries the same access pattern as 0034/0035 and
-- stays without it.

CREATE TABLE main.model_lane_order_state (
    model_id TEXT PRIMARY KEY REFERENCES model_version(model_id) ON DELETE CASCADE,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
