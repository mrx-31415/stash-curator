-- Stage 1 of the lane redesign (docs/workpackage-lane-redesign.md): Discover is
-- replaced by Stretch. Every lane/source_lane CHECK constraint naming
-- 'discover' cannot be altered in place, so each table carrying one is
-- rebuilt: model_scene_lane (0003), model_lane_candidate_cache (0008), and
-- model_lane_order + model_lane_order_state (0015).
--
-- No data migration: the Stretch classification payload change (bounded
-- contributor list in classification_json) already invalidates every cached
-- model, so every row in these materialized caches is stale regardless of
-- the rename and is dropped rather than remapped.
--
-- main-qualified: all four tables are MODEL_TABLES entries
-- (curator/storage/artifacts.py), so a connection with an active model
-- artifact attached shadows each name with a temp view over the artifact
-- copy. An unqualified DROP/CREATE TABLE would resolve to that view ("use
-- DROP VIEW to delete view..."); main. targets the core schema copy
-- directly. CREATE INDEX has no schema-qualified table form, so
-- model_scene_lane's shadow view is dropped outright before its two indexes
-- are rebuilt — attach_active_artifacts only ever runs once per connection
-- (at connect time), and no migrate() call site reads model_scene_lane
-- again on the same connection afterward, so there is nothing to restore
-- it for; a fresh connection recreates it as usual.

DROP VIEW IF EXISTS temp.model_scene_lane;
DROP TABLE main.model_scene_lane;

CREATE TABLE main.model_scene_lane (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'adventure')),
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
    lane TEXT NOT NULL CHECK (lane IN ('best_bets', 'revisit', 'stretch', 'adventure')),
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
        lane IN ('for_you', 'best_bets', 'revisit', 'stretch', 'adventure')
    ),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first', 'varied')),
    position INTEGER NOT NULL CHECK (position >= 0),
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    source_lane TEXT NOT NULL CHECK (
        source_lane IN ('best_bets', 'revisit', 'stretch', 'adventure')
    ),
    utility REAL NOT NULL,
    ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;

-- No scene_id index: migration 0017 dropped model_lane_order_scene_idx as
-- unused, and this rebuild carries the same access pattern (model_id, lane,
-- ordering) covered by the primary key, so it stays dropped.

CREATE TABLE main.model_lane_order_state (
    model_id TEXT PRIMARY KEY REFERENCES model_version(model_id) ON DELETE CASCADE,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
