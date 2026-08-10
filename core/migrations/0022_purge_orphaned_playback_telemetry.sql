-- play_session and behavior_event key on scene_id without a foreign key, so scenes deleted
-- from Stash before this version lingered in them indefinitely. A model build then labeled
-- those scenes from their orphaned telemetry and crashed cross-referencing the live scene
-- list it never appears in. New deletions are now cleaned up as they happen; this sweeps
-- whatever already accumulated. behavior_event goes first: it references play_session, which
-- SQLite will not let this drop out from under it.
DELETE FROM behavior_event WHERE (scene_id IS NOT NULL
        AND scene_id NOT IN (SELECT scene_id FROM source_scene))
    OR session_id IN (
        SELECT session_id FROM play_session
        WHERE scene_id NOT IN (SELECT scene_id FROM source_scene)
    );
DELETE FROM play_session WHERE scene_id NOT IN (SELECT scene_id FROM source_scene);
