// Auto-scheduler (docs/decisions/004, Phase 2a): the daemon's event-driven
// wake-up loop. It replaces the browser-tab timers that used to drive model
// updates and play syncs — with auto_tasks_enabled on, pending model updates
// are applied and new plays are synced without any tab open. Gated entirely
// by the existing modelUpdate* settings; the daemon stays resident while work
// is pending (schedulerStayAlive) so the max-wait backstop can fire.
package main

import (
	"context"
	"database/sql"
	"time"
)

var (
	// autoTickMs is the scheduler cadence inside the daemon.
	autoTickMs int64 = 30_000
	// autoPlayQuietMs is the trailing quiet window before new plays trigger
	// a sync-plays run (mirrors the frontend's play-sync debounce).
	autoPlayQuietMs int64 = 60_000
)

// autoPayloadFromState builds the enqueue payload for auto-scheduled tasks
// from the worker's stored Stash connection (the daemon has no per-request
// payload of its own).
func autoPayloadFromState(state workerState) jVal {
	server := jvObj()
	if state.ServerConnection != "" {
		if parsed, err := parseJSON([]byte(state.ServerConnection)); err == nil && parsed.kind == jObj {
			server = parsed
		}
	}
	return jvObj(
		jvKey("server_connection", server),
		jvKey("args", jvObj()),
	)
}

// enqueueAutoTask inserts a queued job the same way the Stash-facing enqueue
// does, but without the worker-ensure dance (the daemon IS the worker). An
// active job of the same type coalesces into a no-op.
func enqueueAutoTask(db dbx, mode string, payload jVal, now int64) (bool, error) {
	payloadRaw, err := marshalJVal(payload)
	if err != nil {
		return false, err
	}
	jobID := uuid4()
	enqueued := false
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		var existing int
		err := conn.QueryRowContext(ctx, `
SELECT 1 FROM curator_job WHERE state IN ('queued', 'running')
AND job_type=? AND started_at_ms>? LIMIT 1`,
			mode, now-6*3_600_000).Scan(&existing)
		if err == nil {
			return nil // coalesced: this task type is already active
		}
		if err != sql.ErrNoRows {
			return err
		}
		if _, err := conn.ExecContext(ctx, `
INSERT INTO curator_job(job_id, job_type, state, started_at_ms, queued_at_ms, payload_json)
VALUES (?, ?, 'queued', ?, ?, ?)`, jobID, mode, now, now, payloadRaw); err != nil {
			return err
		}
		enqueued = true
		return nil
	})
	return enqueued, err
}

// modelRebuilding reports whether a model-touching job is running (build,
// update-model, sync-build, full-sync-build), matching health's query.
func modelRebuilding(db dbx, now int64) (bool, error) {
	var probe int
	err := db.QueryRow(`SELECT 1 FROM curator_job
WHERE state='running' AND started_at_ms>? AND job_type IN (
    'build', 'update-model', 'sync-build', 'full-sync-build'
) LIMIT 1`, now-6*3_600_000).Scan(&probe)
	if err == nil {
		return true, nil
	}
	if err == sql.ErrNoRows {
		return false, nil
	}
	return false, err
}

// playWatermark is the sync-plays trigger state: are there plays newer than
// the last completed sync-plays, and when did the newest one end?
type playWatermark struct {
	unsynced    bool
	lastEndedAt int64
}

// playWatermarkFn reads the sidecar play stream vs the last sync-plays run.
// A NULL play stream (never played) is not unsynced.
func playWatermarkFn(db dbx) (playWatermark, error) {
	var lastSync sql.NullInt64
	err := db.QueryRow(`SELECT finished_at_ms FROM curator_job
WHERE job_type='sync-plays' AND state='complete' ORDER BY finished_at_ms DESC LIMIT 1`).Scan(&lastSync)
	if err != nil && err != sql.ErrNoRows {
		return playWatermark{}, err
	}
	var lastPlay sql.NullInt64
	if err := db.QueryRow(`SELECT max(ended_at_ms) FROM play_session`).Scan(&lastPlay); err != nil {
		return playWatermark{}, err
	}
	if !lastPlay.Valid {
		return playWatermark{}, nil
	}
	return playWatermark{
		unsynced:    !lastSync.Valid || lastPlay.Int64 > lastSync.Int64,
		lastEndedAt: lastPlay.Int64,
	}, nil
}

// scheduleSpec describes one time-based scheduled task (Phase 2b). The run
// order matters: backup before sync-build so a rebuild never runs on an
// unprotected sidecar; expand-refresh last (cheapest, network-bound).
// atHour anchors the schedule to a wall-clock hour (0-23) when set (-1 =
// interval-relative, the pre-anchor behavior).
type scheduleSpec struct {
	mode          string
	enabled       bool
	intervalHours float64
	atHour        int64
}

func scheduleSpecs(config jVal) []scheduleSpec {
	return []scheduleSpec{
		{"backup", config.get("schedule_backup_enabled").truthy(), pythonFloatOr(config.get("schedule_backup_interval_hours"), 24), configHour(config, "schedule_backup_at_hour")},
		{"sync-build", config.get("schedule_sync_build_enabled").truthy(), pythonFloatOr(config.get("schedule_sync_build_interval_hours"), 24), configHour(config, "schedule_sync_build_at_hour")},
		{"expand-refresh", config.get("schedule_expand_refresh_enabled").truthy(), pythonFloatOr(config.get("schedule_expand_refresh_interval_hours"), 24), configHour(config, "schedule_expand_refresh_at_hour")},
	}
}

// configHour reads an optional 0-23 hour setting; -1 when unset.
func configHour(config jVal, key string) int64 {
	value := config.get(key)
	if value.kind == jNull {
		return -1
	}
	return pythonInt(value)
}

// nextRunFor computes the next run time: the next wall-clock occurrence of
// the anchor hour when one is set (e.g. daily 04:00), else interval-relative.
func nextRunFor(spec scheduleSpec, now int64, intervalMs int64) int64 {
	if spec.atHour >= 0 && spec.atHour <= 23 {
		return nextAnchoredRun(now, spec.atHour, spec.intervalHours)
	}
	return now + intervalMs
}

// nextAnchoredRun returns the next wall-clock occurrence of the anchor hour,
// advanced by whole days when the interval is longer than 24h (48h = every
// other day at the same hour; anything under 24h is daily at the hour).
func nextAnchoredRun(nowMs int64, hour int64, intervalHours float64) int64 {
	base := nextOccurrenceOfHour(nowMs, hour)
	days := int64(intervalHours / 24)
	if days < 1 {
		days = 1
	}
	return base + (days-1)*24*3_600_000
}

// nextOccurrenceOfHour returns the next local-time instant at the given hour
// (today if it is still ahead, otherwise tomorrow).
func nextOccurrenceOfHour(nowMs int64, hour int64) int64 {
	nowTime := time.UnixMilli(nowMs)
	next := time.Date(nowTime.Year(), nowTime.Month(), nowTime.Day(), int(hour), 0, 0, 0, nowTime.Location())
	if !next.After(nowTime) {
		next = next.Add(24 * time.Hour)
	}
	return next.UnixMilli()
}

// anyScheduleEnabled reports whether any time-based schedule is on — the
// daemon must stay resident then, or a daily task would never fire on an
// idle system (nothing else spawns it without a browser).
func anyScheduleEnabled(config jVal) bool {
	for _, spec := range scheduleSpecs(config) {
		if spec.enabled {
			return true
		}
	}
	return false
}

// runDueSchedules enqueues scheduled tasks whose next_run_at_ms has passed,
// then advances the durable row. A task with no row yet (first enable) is
// seeded with next_run = now + interval — never fired immediately. Late
// catch-up is free: an overdue row stays due until the daemon runs.
func runDueSchedules(db dbx, payload jVal, config jVal, now int64) ([]string, error) {
	var enqueued []string
	for _, spec := range scheduleSpecs(config) {
		if !spec.enabled {
			continue
		}
		intervalMs := int64(pyRound(spec.intervalHours * 3_600_000))
		if intervalMs <= 0 {
			intervalMs = 24 * 3_600_000
		}
		var next sql.NullInt64
		err := db.QueryRow(`SELECT next_run_at_ms FROM scheduled_task WHERE task_type=?`, spec.mode).Scan(&next)
		if err == sql.ErrNoRows {
			if _, err := db.Exec(`INSERT INTO scheduled_task(task_type, next_run_at_ms) VALUES (?, ?)`,
				spec.mode, nextRunFor(spec, now, intervalMs)); err != nil {
				return enqueued, err
			}
			continue
		}
		if err != nil {
			return enqueued, err
		}
		// Anchored schedules keep their wall-clock phase: recompute the next
		// occurrence each tick (unless already overdue, so catch-up still
		// fires) — this also applies an at_hour change to an existing row.
		if spec.atHour >= 0 && spec.atHour <= 23 && (!next.Valid || next.Int64 > now) {
			expected := nextAnchoredRun(now, spec.atHour, spec.intervalHours)
			if !next.Valid || next.Int64 != expected {
				if _, err := db.Exec(`UPDATE scheduled_task SET next_run_at_ms=? WHERE task_type=?`,
					expected, spec.mode); err != nil {
					return enqueued, err
				}
				next = sql.NullInt64{Int64: expected, Valid: true}
			}
		}
		if !next.Valid || next.Int64 > now {
			continue
		}
		ok, err := enqueueAutoTask(db, spec.mode, payload, now)
		if err != nil {
			return enqueued, err
		}
		if ok {
			enqueued = append(enqueued, spec.mode)
		}
		if _, err := db.Exec(`UPDATE scheduled_task SET next_run_at_ms=?, last_run_at_ms=? WHERE task_type=?`,
			nextRunFor(spec, now, intervalMs), now, spec.mode); err != nil {
			return enqueued, err
		}
	}
	return enqueued, nil
}

// schedulerTick runs one auto-scheduler pass: enqueue update-model when the
// coordinator is ready and nothing is rebuilding, and sync-plays when new
// plays have been quiet for the debounce window. Returns the modes enqueued.
func schedulerTick(db dbx, payload jVal, now int64) ([]string, error) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return nil, err
	}
	config := cfg.get("config")
	var enqueued []string
	// Time-based schedules (2b) are independent of auto_tasks_enabled.
	scheduled, err := runDueSchedules(db, payload, config, now)
	if err != nil {
		return enqueued, err
	}
	enqueued = append(enqueued, scheduled...)
	if !config.get("auto_tasks_enabled").truthy() {
		return enqueued, nil
	}
	status, err := modelUpdateStatus(db)
	if err != nil {
		return nil, err
	}
	rebuilding, err := modelRebuilding(db, now)
	if err != nil {
		return nil, err
	}
	ready := modelUpdateReady(status, now,
		int(pythonInt(config.get("model_update_event_threshold"))),
		pyRound(pythonFloatOr(config.get("model_update_max_wait_minutes"), 0)*60_000),
		pyRound(pythonFloatOr(config.get("model_update_min_interval_minutes"), 0)*60_000),
	)
	if ready && !rebuilding {
		ok, err := enqueueAutoTask(db, "update-model", payload, now)
		if err != nil {
			return enqueued, err
		}
		if ok {
			enqueued = append(enqueued, "update-model")
		}
	}
	watermark, err := playWatermarkFn(db)
	if err != nil {
		return enqueued, err
	}
	if watermark.unsynced && now-watermark.lastEndedAt >= autoPlayQuietMs {
		ok, err := enqueueAutoTask(db, "sync-plays", payload, now)
		if err != nil {
			return enqueued, err
		}
		if ok {
			enqueued = append(enqueued, "sync-plays")
		}
	}
	return enqueued, nil
}

// schedulerStayAlive reports whether the daemon should stay resident: an
// enabled time-based schedule (2b), a dirty (pending) model, or unsynced
// plays. The claim loop already keeps it alive while jobs are queued.
func schedulerStayAlive(db dbx, now int64) (bool, error) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return false, err
	}
	config := cfg.get("config")
	if anyScheduleEnabled(config) {
		return true, nil
	}
	if !config.get("auto_tasks_enabled").truthy() {
		return false, nil
	}
	status, err := modelUpdateStatus(db)
	if err != nil {
		return false, err
	}
	if status.pending() {
		return true, nil
	}
	watermark, err := playWatermarkFn(db)
	if err != nil {
		return false, err
	}
	return watermark.unsynced, nil
}
