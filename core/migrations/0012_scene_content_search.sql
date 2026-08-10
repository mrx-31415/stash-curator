CREATE TABLE scene_content_search (
  feature_version TEXT NOT NULL,
  feature_id TEXT NOT NULL,
  scene_id TEXT NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY (feature_id, scene_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX scene_content_search_scene_idx
ON scene_content_search(feature_version, scene_id, feature_id);

INSERT INTO scene_content_search(feature_version, feature_id, scene_id, value)
SELECT ef.feature_version, ef.feature_id, ef.entity_id, ef.value
FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
JOIN feature_build fb USING(feature_version)
WHERE fb.status='published' AND ef.entity_type='scene' AND fd.family='content';
