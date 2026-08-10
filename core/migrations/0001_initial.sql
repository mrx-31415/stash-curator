CREATE TABLE application_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE source_studio (
    studio_id TEXT PRIMARY KEY,
    name TEXT,
    parent_studio_id TEXT REFERENCES source_studio(studio_id),
    updated_at TEXT,
    source_hash TEXT NOT NULL
) STRICT;

CREATE TABLE source_scene (
    scene_id TEXT PRIMARY KEY,
    title TEXT,
    details TEXT,
    scene_date TEXT,
    studio_id TEXT REFERENCES source_studio(studio_id),
    play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
    play_duration_seconds REAL NOT NULL DEFAULT 0 CHECK (play_duration_seconds >= 0),
    rating100 INTEGER CHECK (rating100 BETWEEN 0 AND 100),
    updated_at TEXT,
    source_hash TEXT NOT NULL
) STRICT;

CREATE TABLE source_file (
    file_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    duration_seconds REAL CHECK (duration_seconds >= 0),
    available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
    source_hash TEXT NOT NULL
) STRICT;

CREATE INDEX source_file_scene_idx ON source_file(scene_id);

CREATE TABLE source_performer (
    performer_id TEXT PRIMARY KEY,
    name TEXT,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    birthdate TEXT,
    ethnicity TEXT,
    country TEXT,
    eye_color TEXT,
    hair_color TEXT,
    height_cm INTEGER CHECK (height_cm > 0),
    weight_kg INTEGER CHECK (weight_kg > 0),
    measurements TEXT,
    augmentation TEXT,
    tattoos TEXT,
    piercings TEXT,
    updated_at TEXT,
    source_hash TEXT NOT NULL
) STRICT;

CREATE TABLE source_tag (
    tag_id TEXT PRIMARY KEY,
    name TEXT,
    updated_at TEXT,
    source_hash TEXT NOT NULL
) STRICT;

CREATE TABLE tag_parent (
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    parent_tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (tag_id, parent_tag_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE scene_performer (
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    performer_id TEXT NOT NULL REFERENCES source_performer(performer_id) ON DELETE CASCADE,
    position INTEGER,
    PRIMARY KEY (scene_id, performer_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX scene_performer_performer_idx ON scene_performer(performer_id);

CREATE TABLE scene_tag (
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    provenance TEXT NOT NULL DEFAULT 'scene',
    PRIMARY KEY (scene_id, tag_id, provenance)
) STRICT, WITHOUT ROWID;

CREATE INDEX scene_tag_tag_idx ON scene_tag(tag_id);

CREATE TABLE scene_marker (
    marker_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    seconds REAL NOT NULL CHECK (seconds >= 0),
    end_seconds REAL CHECK (end_seconds IS NULL OR end_seconds >= seconds),
    primary_tag_id TEXT REFERENCES source_tag(tag_id),
    source_hash TEXT NOT NULL
) STRICT;

CREATE INDEX scene_marker_scene_idx ON scene_marker(scene_id);

CREATE TABLE marker_tag (
    marker_id TEXT NOT NULL REFERENCES scene_marker(marker_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (marker_id, tag_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE source_play (
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    played_at_ms INTEGER NOT NULL CHECK (played_at_ms >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (scene_id, played_at_ms, ordinal)
) STRICT, WITHOUT ROWID;

CREATE TABLE source_o (
    scene_id TEXT NOT NULL REFERENCES source_scene(scene_id) ON DELETE CASCADE,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (scene_id, occurred_at_ms, ordinal)
) STRICT, WITHOUT ROWID;

CREATE TABLE sync_cursor (
    entity_type TEXT PRIMARY KEY,
    watermark TEXT,
    page_cursor TEXT,
    state TEXT NOT NULL CHECK (state IN ('idle', 'running', 'complete', 'failed')),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
) STRICT;

CREATE TABLE impression (
    impression_id TEXT PRIMARY KEY,
    requested_at_ms INTEGER NOT NULL CHECK (requested_at_ms >= 0),
    lane TEXT NOT NULL,
    model_id TEXT,
    config_version TEXT NOT NULL,
    request_context_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE play_session (
    session_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    ended_at_ms INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms),
    active_seconds REAL NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    provenance TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    impression_id TEXT REFERENCES impression(impression_id),
    summary_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX play_session_scene_idx ON play_session(scene_id, started_at_ms);

CREATE TABLE behavior_event (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    scene_id TEXT,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    outcome REAL CHECK (outcome BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    provenance TEXT NOT NULL,
    session_id TEXT REFERENCES play_session(session_id),
    impression_id TEXT REFERENCES impression(impression_id),
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX behavior_event_scene_idx ON behavior_event(scene_id, occurred_at_ms);

CREATE TABLE impression_item (
    impression_id TEXT NOT NULL REFERENCES impression(impression_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    policy_score REAL NOT NULL,
    reason_snapshot_json TEXT NOT NULL,
    PRIMARY KEY (impression_id, scene_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE feedback (
    feedback_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    value TEXT,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    reversed_by_id TEXT REFERENCES feedback(feedback_id),
    impression_id TEXT REFERENCES impression(impression_id),
    payload_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX feedback_scene_idx ON feedback(scene_id, occurred_at_ms);

CREATE TABLE exclusion (
    exclusion_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    exclusion_type TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    expires_at_ms INTEGER,
    reversed_at_ms INTEGER,
    UNIQUE (entity_type, entity_id, exclusion_type)
) STRICT;

CREATE TABLE pruning_candidate (
    scene_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('review', 'keep', 'remove')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    reason TEXT
) STRICT;

CREATE TABLE feature_definition (
    feature_id TEXT PRIMARY KEY,
    feature_version TEXT NOT NULL,
    family TEXT NOT NULL,
    name TEXT NOT NULL,
    provenance TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE tag_role (
    tag_id TEXT NOT NULL REFERENCES source_tag(tag_id) ON DELETE CASCADE,
    config_version TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('content', 'performer_attribute', 'quality_technical',
                        'workflow_administrative', 'ignored')),
    resolution_reason TEXT NOT NULL,
    PRIMARY KEY (tag_id, config_version)
) STRICT, WITHOUT ROWID;

CREATE TABLE entity_feature (
    feature_version TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    feature_id TEXT NOT NULL REFERENCES feature_definition(feature_id) ON DELETE CASCADE,
    value REAL NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (feature_version, entity_type, entity_id, feature_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX entity_feature_feature_idx ON entity_feature(feature_id);

CREATE TABLE model_version (
    model_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('building', 'published', 'superseded', 'failed')),
    feature_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    sync_watermark TEXT,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    published_at_ms INTEGER CHECK (published_at_ms IS NULL OR published_at_ms >= created_at_ms)
) STRICT;

CREATE UNIQUE INDEX one_published_model_idx
ON model_version(status) WHERE status = 'published';

CREATE TABLE feature_affinity (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    feature_id TEXT NOT NULL REFERENCES feature_definition(feature_id),
    affinity REAL NOT NULL CHECK (affinity BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    effective_support REAL NOT NULL CHECK (effective_support >= 0),
    distinct_scene_count INTEGER NOT NULL CHECK (distinct_scene_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, feature_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE direct_scene_state (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL,
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    effective_evidence REAL NOT NULL CHECK (effective_evidence >= 0),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    residual REAL NOT NULL CHECK (residual BETWEEN -2 AND 2),
    PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE recommendation_history (
    history_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    impression_id TEXT REFERENCES impression(impression_id),
    lane TEXT NOT NULL,
    shown_at_ms INTEGER NOT NULL CHECK (shown_at_ms >= 0),
    selected_at_ms INTEGER
) STRICT;

CREATE INDEX recommendation_history_scene_idx
ON recommendation_history(scene_id, shown_at_ms);
