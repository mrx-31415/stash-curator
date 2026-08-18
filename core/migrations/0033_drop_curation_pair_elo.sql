-- curation_pair_elo was "optional steering state for pair selection"
-- (migration 0030) explicitly deferred as "Phase 4 (optional)" in
-- docs/workpackage-pairwise-picks.md and never wired into pair scoring: it
-- was written on every submit and read by nothing. Dropping it rather than
-- carrying dead byte-identical Go/Python state for a feature phase that was
-- never built.

DROP TABLE curation_pair_elo;
