ALTER TABLE feature_build ADD COLUMN scene_count INTEGER CHECK (scene_count >= 0);
ALTER TABLE feature_build ADD COLUMN performer_count INTEGER CHECK (performer_count >= 0);
ALTER TABLE feature_build ADD COLUMN feature_count INTEGER CHECK (feature_count >= 0);

UPDATE feature_build
SET scene_count = (
        SELECT count(DISTINCT entity_id) FROM entity_feature
        WHERE entity_feature.feature_version = feature_build.feature_version
          AND entity_type = 'scene'
    ),
    performer_count = (
        SELECT count(DISTINCT entity_id) FROM entity_feature
        WHERE entity_feature.feature_version = feature_build.feature_version
          AND entity_type = 'performer'
    ),
    feature_count = (
        SELECT count(*) FROM feature_definition
        WHERE feature_definition.feature_version = feature_build.feature_version
    );
