-- Scheduled background tasks (docs/decisions/004, Phase 2b): durable
-- next-run state for time-based tasks the daemon enqueues (daily
-- expand-refresh, sync-build, and backup). The settings are the source of
-- truth for enablement and cadence; this table only persists the computed
-- next/last run times so a daemon restart does not lose the schedule.

CREATE TABLE scheduled_task (
    task_type TEXT PRIMARY KEY,
    next_run_at_ms INTEGER CHECK (next_run_at_ms IS NULL OR next_run_at_ms >= 0),
    last_run_at_ms INTEGER CHECK (last_run_at_ms IS NULL OR last_run_at_ms >= 0)
) STRICT;
