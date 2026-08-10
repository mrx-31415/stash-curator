ALTER TABLE model_scene_lane ADD COLUMN appeal REAL;

UPDATE model_scene_lane
SET appeal = (
  SELECT score.appeal FROM model_scene_score score
  WHERE score.model_id=model_scene_lane.model_id
    AND score.scene_id=model_scene_lane.scene_id
)
WHERE model_id IN (SELECT model_id FROM model_version WHERE status='published');

CREATE INDEX model_scene_lane_appeal_idx
ON model_scene_lane(model_id, scene_id, appeal);
