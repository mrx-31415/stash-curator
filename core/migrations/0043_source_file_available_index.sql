-- Lane eligibility and counting probe each scene for an available file.
CREATE INDEX source_file_available_scene_idx ON source_file(scene_id) WHERE available = 1;
