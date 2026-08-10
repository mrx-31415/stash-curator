CREATE INDEX model_scene_score_prune_idx
ON model_scene_score(model_id, appeal, confidence, scene_id);
