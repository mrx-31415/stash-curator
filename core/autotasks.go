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

// schedulerTick runs one auto-scheduler pass: enqueue update-model when the
// coordinator is ready and nothing is rebuilding, and sync-plays when new
// plays have been quiet for the debounce window. Returns the modes enqueued.
func schedulerTick(db dbx, payload jVal, now int64) ([]string, error) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return nil, err
	}
	config := cfg.get("config")
	if !config.get("auto_tasks_enabled").truthy() {
		return nil, nil
	}
	var enqueued []string
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

// schedulerStayAlive reports whether the daemon should stay resident for the
// auto-scheduler: a dirty (pending) model or unsynced plays. The claim loop
// already keeps it alive while jobs are queued.
func schedulerStayAlive(db dbx, now int64) (bool, error) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return false, err
	}
	if !cfg.get("config").get("auto_tasks_enabled").truthy() {
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
