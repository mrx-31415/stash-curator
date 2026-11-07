-- Periods when Curator does not learn from viewing: while the "Pause
-- learning from viewing" setting is on (ended_at_ms NULL until it is turned
-- off), and periods the viewer asked Curator to forget afterwards. Player
-- sessions and Stash play-history plays inside a period are left out.
-- Deliberate feedback (thumbs, tag answers, dismissals) still counts.
CREATE TABLE learning_pause (
    pause_id INTEGER PRIMARY KEY,
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    ended_at_ms INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms),
    reason TEXT NOT NULL CHECK (reason IN ('paused', 'forgotten'))
) STRICT;
