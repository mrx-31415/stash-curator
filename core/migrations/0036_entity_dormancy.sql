-- Stage 3 of the lane redesign (docs/workpackage-lane-redesign.md): the new
-- Dormant lane. Per-entity (performer/tag/studio) play history summary,
-- computed once per model build and read at classification and slate time
-- with a live now_ms so a week-old artifact can't call a taste dormant that
-- was watched yesterday. First appearance of this MODEL_TABLES entry, so
-- (unlike migrations 0034/0035) no attached-artifact shadow view can exist
-- for it yet — attach_active_artifacts only creates a view for tables the
-- artifact actually has, and no artifact predating this migration has one.

CREATE TABLE model_entity_dormancy (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('performer', 'tag', 'studio')),
    entity_id TEXT NOT NULL,
    last_played_at_ms INTEGER NOT NULL,
    positive_strength REAL NOT NULL,
    play_count INTEGER NOT NULL CHECK (play_count >= 0),
    distinct_scene_count INTEGER NOT NULL CHECK (distinct_scene_count >= 0),
    PRIMARY KEY (model_id, entity_type, entity_id)
) STRICT;
