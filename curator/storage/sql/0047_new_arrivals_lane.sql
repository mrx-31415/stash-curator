-- New Arrivals lane: the user's best-fitting scenes among those most recently
-- added to Stash.
--
-- source_scene gains Stash's created_at (as epoch milliseconds) and organized
-- flag. Existing rows only learn them when the scene is fetched again, and an
-- incremental sync only fetches scenes Stash changed since its watermark, so
-- the scene cursor's watermarks are cleared: the next sync reads every scene
-- once. Its page cursor is kept so an interrupted run still resumes.
--
-- Every lane/source_lane CHECK constraint is then rebuilt to admit
-- 'new_arrivals', exactly as migration 0037 did for 'dormant'. No data
-- migration: the rows are build caches, and the scoring fingerprint change
-- that ships with this lane rebuilds the model.
--
-- main-qualified and shadow-view handling: see migration 0034 for the full
-- explanation.

ALTER TABLE source_scene ADD COLUMN created_at_ms INTEGER
    CHECK (created_at_ms IS NULL OR created_at_ms >= 0);
ALTER TABLE source_scene ADD COLUMN organized INTEGER NOT NULL DEFAULT 0
    CHECK (organized IN (0, 1));

UPDATE sync_cursor
SET watermark = NULL, baseline_watermark = NULL, pending_watermark = NULL
WHERE entity_type = 'scene';

DROP VIEW IF EXISTS temp.model_scene_lane;
DROP TABLE main.model_scene_lane;

CREATE TABLE main.model_scene_lane (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (
        lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant', 'new_arrivals')
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
        lane IN ('best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant', 'new_arrivals')
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
        lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant', 'new_arrivals')
    ),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first', 'varied')),
    position INTEGER NOT NULL CHECK (position >= 0),
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    source_lane TEXT NOT NULL CHECK (
        source_lane IN ('best_bets', 'revisit', 'stretch', 'blind_spots', 'dormant', 'new_arrivals')
    ),
    utility REAL NOT NULL,
    ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;

-- No scene_id index: migration 0017 dropped model_lane_order_scene_idx as
-- unused; this rebuild carries the same access pattern as 0034/0035/0037
-- and stays without it.

CREATE TABLE main.model_lane_order_state (
    model_id TEXT PRIMARY KEY REFERENCES model_version(model_id) ON DELETE CASCADE,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
