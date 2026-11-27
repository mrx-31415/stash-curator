-- Which viewing Curator learns from. Every play is kept: player sessions,
-- Stash's play history and the signals derived from them. A rule marks a
-- period, for one scene or for all of them, as counted ('include') or not
-- ('exclude'). For a play the deciding rule is the most specific one that
-- covers it (one scene before all scenes), then the newest. With no rule the
-- play counts. The "Pause learning from viewing" setting is an open exclude
-- rule for all scenes, ended when the setting is turned off.
--
-- Replaces learning_pause (0052). Its 'forgotten' periods deleted player
-- sessions when they were made; they carry over as exclude rules so the
-- plays Curator still has from them stay out.
CREATE TABLE viewing_rule (
    rule_id INTEGER PRIMARY KEY,
    scene_id TEXT,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    ended_at_ms INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms > started_at_ms),
    choice TEXT NOT NULL CHECK (choice IN ('include', 'exclude')),
    reason TEXT NOT NULL CHECK (reason IN ('paused', 'chosen')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT;

INSERT INTO viewing_rule(scene_id, started_at_ms, ended_at_ms, choice, reason, created_at_ms)
SELECT NULL, started_at_ms,
       CASE WHEN ended_at_ms IS NOT NULL AND ended_at_ms <= started_at_ms
            THEN started_at_ms + 1 ELSE ended_at_ms END,
       'exclude', CASE reason WHEN 'paused' THEN 'paused' ELSE 'chosen' END, started_at_ms
FROM learning_pause ORDER BY pause_id;

DROP TABLE learning_pause;

CREATE INDEX viewing_rule_scene_idx ON viewing_rule(scene_id, rule_id);

-- The counted subsets. Readers that learn from viewing read these instead of
-- the tables, so a rule applies everywhere at once. A play's rule is looked up
-- for its scene first, then for every scene, each the newest covering one.
-- The sessions and signals Curator derives from Stash's play history are
-- rebuilt from counted_source_play whenever a choice changes, so only Stash's
-- plays and Curator's own player sessions are checked here.
CREATE VIEW counted_source_play AS
SELECT p.* FROM source_play p
WHERE COALESCE(
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id = p.scene_id AND p.played_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR p.played_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id IS NULL AND p.played_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR p.played_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    'include') = 'include';

CREATE VIEW counted_source_o AS
SELECT o.* FROM source_o o
WHERE COALESCE(
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id = o.scene_id AND o.occurred_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR o.occurred_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id IS NULL AND o.occurred_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR o.occurred_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    'include') = 'include';

CREATE VIEW counted_play_session AS
SELECT s.* FROM play_session s
WHERE s.provenance <> 'direct_player'
   OR COALESCE(
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id = s.scene_id AND s.started_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR s.started_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id IS NULL AND s.started_at_ms >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR s.started_at_ms < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    'include') = 'include';

-- A player signal follows its session's start, or its own time without one.
-- Deliberate feedback lives in other tables and is never filtered.
CREATE VIEW counted_behavior_event AS
SELECT e.* FROM behavior_event e
LEFT JOIN play_session s ON s.session_id = e.session_id
WHERE e.provenance <> 'direct_player'
   OR e.scene_id IS NULL
   OR COALESCE(
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id = e.scene_id AND COALESCE(s.started_at_ms, e.occurred_at_ms) >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR COALESCE(s.started_at_ms, e.occurred_at_ms) < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    (SELECT r.choice FROM viewing_rule r
     WHERE r.scene_id IS NULL AND COALESCE(s.started_at_ms, e.occurred_at_ms) >= r.started_at_ms
       AND (r.ended_at_ms IS NULL OR COALESCE(s.started_at_ms, e.occurred_at_ms) < r.ended_at_ms)
     ORDER BY r.rule_id DESC LIMIT 1),
    'include') = 'include';

-- Stash's own per-scene play count less the plays that do not count. Stash
-- counts plays it holds no timestamp for too, so the count is not rebuilt
-- from source_play.
CREATE VIEW counted_scene_play AS
SELECT s.scene_id,
       max(0, s.play_count
              - (SELECT count(*) FROM source_play p WHERE p.scene_id = s.scene_id)
              + (SELECT count(*) FROM counted_source_play c WHERE c.scene_id = s.scene_id)) AS play_count
FROM source_scene s;
