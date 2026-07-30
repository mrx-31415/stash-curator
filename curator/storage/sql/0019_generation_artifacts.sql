ALTER TABLE feature_build ADD COLUMN artifact_basename TEXT;
ALTER TABLE feature_build ADD COLUMN artifact_schema_version INTEGER;
ALTER TABLE feature_build ADD COLUMN artifact_bytes INTEGER CHECK (artifact_bytes >= 0);
ALTER TABLE feature_build ADD COLUMN validation_status TEXT;
ALTER TABLE feature_build ADD COLUMN validation_summary_json TEXT;
ALTER TABLE feature_build ADD COLUMN cleanup_error TEXT;
ALTER TABLE feature_build ADD COLUMN reuse_count INTEGER NOT NULL DEFAULT 0
    CHECK (reuse_count >= 0);

ALTER TABLE model_version ADD COLUMN artifact_basename TEXT;
ALTER TABLE model_version ADD COLUMN artifact_schema_version INTEGER;
ALTER TABLE model_version ADD COLUMN artifact_bytes INTEGER CHECK (artifact_bytes >= 0);
ALTER TABLE model_version ADD COLUMN scene_count INTEGER CHECK (scene_count >= 0);
ALTER TABLE model_version ADD COLUMN lane_count INTEGER CHECK (lane_count >= 0);
ALTER TABLE model_version ADD COLUMN reason_scene_count INTEGER CHECK (reason_scene_count >= 0);
ALTER TABLE model_version ADD COLUMN reason_count INTEGER CHECK (reason_count >= 0);
ALTER TABLE model_version ADD COLUMN validation_status TEXT;
ALTER TABLE model_version ADD COLUMN validation_summary_json TEXT;
ALTER TABLE model_version ADD COLUMN cleanup_error TEXT;
ALTER TABLE model_version ADD COLUMN reuse_count INTEGER NOT NULL DEFAULT 0
    CHECK (reuse_count >= 0);
