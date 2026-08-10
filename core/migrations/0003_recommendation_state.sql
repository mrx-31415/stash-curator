CREATE TABLE feature_build (
    feature_version TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('building', 'published', 'superseded', 'failed')),
    config_json TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    published_at_ms INTEGER CHECK (published_at_ms IS NULL OR published_at_ms >= created_at_ms),
    error TEXT
) STRICT;

CREATE UNIQUE INDEX one_published_feature_build_idx
ON feature_build(status) WHERE status = 'published';

CREATE TABLE model_scene_score (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    general_appeal REAL NOT NULL CHECK (general_appeal BETWEEN -1 AND 1),
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    direct_confidence REAL NOT NULL CHECK (direct_confidence BETWEEN 0 AND 1),
    appeal REAL NOT NULL CHECK (appeal BETWEEN -1 AND 1),
    current_fit REAL NOT NULL CHECK (current_fit BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    metadata_confidence REAL NOT NULL CHECK (metadata_confidence BETWEEN 0 AND 1),
    recovery REAL NOT NULL CHECK (recovery BETWEEN 0 AND 1),
    components_json TEXT NOT NULL,
    neighbors_json TEXT NOT NULL DEFAULT '[]',
    eligibility_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX model_scene_score_fit_idx ON model_scene_score(model_id, current_fit DESC);

CREATE TABLE model_scene_reason (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    reason_index INTEGER NOT NULL CHECK (reason_index >= 0),
    reason_code TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('positive', 'negative', 'unknown', 'neutral')),
    magnitude REAL NOT NULL CHECK (magnitude BETWEEN 0 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    subject_type TEXT,
    subject_id TEXT,
    visibility TEXT NOT NULL CHECK (visibility IN ('standard', 'sensitive', 'private')),
    provenance TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, scene_id, reason_index)
) STRICT, WITHOUT ROWID;

CREATE TABLE model_scene_lane (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    lane TEXT NOT NULL CHECK (lane IN ('for_you', 'best_bets', 'revisit', 'discover', 'adventure')),
    subtype TEXT,
    lane_value REAL NOT NULL,
    qualification_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, scene_id, lane)
) STRICT, WITHOUT ROWID;

CREATE INDEX model_scene_lane_value_idx
ON model_scene_lane(model_id, lane, lane_value DESC);
