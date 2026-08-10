-- Between 2026-07-19 and this release the browser tracker attached to a Stash player that
-- never reported progress, so every direct session recorded zero active seconds and no played
-- ranges. Those empty sessions were graded as short exits and penalized scenes the user may
-- have watched in full. Remove the penalties; the sessions themselves stay as navigation facts.
DELETE FROM behavior_event
WHERE provenance = 'direct_player'
  AND outcome < 0
  AND session_id IN (
    SELECT session_id FROM play_session
    WHERE provenance = 'direct_player'
      AND active_seconds <= 0
      AND json_array_length(COALESCE(json_extract(summary_json, '$.played_ranges'), '[]')) = 0
      AND COALESCE(json_extract(summary_json, '$.maximum_position_seconds'), 0)
          <= COALESCE(json_extract(summary_json, '$.start_position_seconds'), 0)
  );
