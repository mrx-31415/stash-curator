// Task-mode runner — a port of backend.py's _run_task / _run_task_body
// lifecycle: the curator_job state machine (stale-run recovery, single
// running-job guard, complete/failed transitions with summary_json), the
// stderr progress/log protocol, and the per-mode task bodies. Modes that
// depend on the model build or the sync family are wired as their ports
// land; unported modes still fall back to backend.py.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
)

// progressLog mirrors backend.py's _progress: a stderr progress marker with
// the value clamped to [0, 1] and %.4f formatting.
func progressLog(value float64) {
	fmt.Fprintf(os.Stderr, "\x01p\x02%.4f\n", math.Max(0.0, math.Min(value, 1.0)))
}

func infoLog(message string) {
	fmt.Fprintf(os.Stderr, "\x01i\x02%s\n", message)
}

func errorLog(message string) {
	fmt.Fprintf(os.Stderr, "\x01e\x02%s\n", message)
}

// mappedProgress mirrors backend.py's _mapped_progress.
func mappedProgress(start, end float64) func(processed, total int) {
	return func(processed, total int) {
		fraction := 1.0
		if total > 0 {
			fraction = math.Min(float64(processed)/float64(total), 1.0)
		}
		progressLog(start + (end-start)*fraction)
	}
}

// runTask mirrors backend.py's _run_task: the mode runs under the _profiled
// lifecycle with kind "task".
func runTask(pluginDir string, payload jVal, mode string) (jVal, error) {
	return profiledKind(pluginDir, payload, mode, "task",
		func(settings jVal) (jVal, error) { return runTaskBody(pluginDir, payload, mode, settings) })
}

// runTaskBody mirrors backend.py's _run_task_body.
func runTaskBody(pluginDir string, payload jVal, mode string, settings jVal) (jVal, error) {
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	jobID := uuid4()
	startedAtMs := nowMs()
	staleBefore := nowMs() - 6*3_600_000
	var existingJobID, existingJobType string
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `
UPDATE curator_job SET state='failed', finished_at_ms=?, error='interrupted'
WHERE state='running' AND started_at_ms<=?`, nowMs(), staleBefore); err != nil {
			return err
		}
		var existingID, existingType string
		err := conn.QueryRowContext(ctx, `
SELECT job_id, job_type FROM curator_job WHERE state='running'
AND started_at_ms>? ORDER BY started_at_ms DESC LIMIT 1`, staleBefore).Scan(&existingID, &existingType)
		if err == sql.ErrNoRows {
			if _, err := conn.ExecContext(ctx, `
UPDATE model_update_state SET last_error='interrupted before task completion'
WHERE last_started_at_ms IS NOT NULL
AND last_started_at_ms>COALESCE(last_finished_at_ms, -1)
AND last_error IS NULL`); err != nil {
				return err
			}
			_, err := conn.ExecContext(ctx, `
INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES (?, ?, 'running', ?)`, jobID, mode, startedAtMs)
			return err
		}
		if err != nil {
			return err
		}
		existingJobID, existingJobType = existingID, existingType
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	if existingJobID != "" {
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("job_id", jvStr(existingJobID)),
			jvKey("already_running", jvBool(true)),
			jvKey("job_type", jvStr(existingJobType)),
		), nil
	}
	if mode == "compact" || mode == "vacuum" {
		// Compaction requires a core-only connection; vacuum runs without the
		// attached artifact views, matching Python's reopen.
		db.Close()
		db, err = openSidecar(pluginDir, payload, settings, false)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
	}
	infoLog(fmt.Sprintf("Stash Curator %s started", mode))
	progressLog(0.01)
	summary, taskErr := runTaskMode(db, pluginDir, payload, mode, settings, startedAtMs)
	if taskErr != nil {
		txnErr := withTxn(db, func(conn *sql.Conn) error {
			_, err := conn.ExecContext(context.Background(), `
UPDATE curator_job SET state='failed', finished_at_ms=?, error=?
WHERE job_id=?`, nowMs(), truncateString(taskErr.Error(), 2000), jobID)
			return err
		})
		if txnErr != nil {
			return jvNull(), txnErr
		}
		errorLog(fmt.Sprintf("Stash Curator %s failed: %s", mode, taskErr.Error()))
		return jvNull(), taskErr
	}
	txnErr := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
UPDATE curator_job SET state='complete', finished_at_ms=?, summary_json=?
WHERE job_id=?`, nowMs(), summary.marshalSortedKeys(), jobID)
		return err
	})
	if txnErr != nil {
		return jvNull(), txnErr
	}
	infoLog(fmt.Sprintf("Stash Curator %s completed", mode))
	progressLog(1.0)
	out := jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("job_id", jvStr(jobID)),
	)
	for _, pair := range summary.obj {
		out.set(pair.key, pair.val)
	}
	return out, nil
}

func truncateString(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// runTaskMode dispatches the mode-specific body and returns the summary dict
// (Python's `summary` variable; summary_json is its sorted-key dump).
func runTaskMode(db dbx, pluginDir string, payload jVal, mode string, settings jVal, startedAtMs int64) (jVal, error) {
	switch mode {
	case "backup":
		return taskBackup(db, pluginDir, payload, settings, startedAtMs)
	case "compact":
		return taskCompact(db)
	case "vacuum":
		return taskVacuum(db, pluginDir, payload, settings)
	case "prepare":
		return taskPrepare(db)
	case "sync-plays":
		return taskSyncPlays(db, pluginDir, payload, settings)
	case "expand-refresh":
		return taskExpandRefresh(db, pluginDir, payload, settings)
	case "build", "update-model", "sync-build", "full-sync-build":
		return runTaskModePending(db, pluginDir, payload, mode, settings)
	}
	return jvNull(), fmt.Errorf("unknown Curator task: %s", mode)
}

// taskPrepare mirrors backend.py's prepare mode.
func taskPrepare(db dbx) (jVal, error) {
	progressLog(0.05)
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model; build recommendations first")
	}
	infoLog("Preparing recommendation pages")
	laneCaches, err := prepareLanesTask(db, modelID, false, mappedProgress(0.05, 0.99))
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.99)
	return jvObj(
		jvKey("model_id", jvStr(modelID)),
		jvKey("lane_candidate_caches", laneCaches),
	), nil
}

// taskSyncPlays mirrors backend.py's sync-plays mode.
func taskSyncPlays(db dbx, pluginDir string, payload jVal, settings jVal) (jVal, error) {
	progressLog(0.05)
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	infoLog("Synchronizing recent plays")
	base, headers := stashConnection(payload)
	var synced syncResult
	err = pythonSpan("task.sync_plays", func() error {
		service, err := newSyncService(base, headers, newSyncRepository(db), pythonInt(cfg.get("sync_page_size")))
		if err != nil {
			return err
		}
		synced, err = service.sync(false, true)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.95)
	changedPlays := synced.changedEntityCounts["scene_play"]
	if changedPlays > 0 {
		infoLog(fmt.Sprintf("Imported %d recently played scenes", changedPlays))
	}
	progressLog(0.99)
	sceneIDs := jvArr()
	for _, id := range synced.sceneIDs {
		sceneIDs.arr = append(sceneIDs.arr, jvStr(id))
	}
	return jvObj(
		jvKey("sync_run_id", jvStr(synced.runID)),
		jvKey("changed_play_scenes", jvInt(changedPlays)),
		jvKey("scene_ids", sceneIDs),
	), nil
}

// taskExpandRefresh mirrors backend.py's expand-refresh mode.
func taskExpandRefresh(db dbx, pluginDir string, payload jVal, settings jVal) (jVal, error) {
	progressLog(0.05)
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	infoLog("Collecting bounded StashDB candidates")
	base, apiKey, err := stashdbClient(payload)
	if err != nil {
		return jvNull(), err
	}
	links, err := externalLinksRefresh(payload, db)
	if err != nil {
		return jvNull(), err
	}
	var summary jVal
	err = pythonSpan("task.expand_refresh", func() error {
		var err error
		summary, err = expandRefresh(db, base, apiKey, links,
			int(pythonInt(cfg.get("expand_horizon_days"))),
			cfg.get("expand_gender").asString(),
			cfg.get("expand_wildcard").truthy(),
			nowMs(), mappedProgress(0.05, 0.98))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	return summary, nil
}

// runTaskModePending routes the modes whose dependency ports are still in
// flight; once each port lands the switch case above routes directly. This
// keeps the runner compiling while the build/sync/ranking pieces land.
func runTaskModePending(db dbx, pluginDir string, payload jVal, mode string, settings jVal) (jVal, error) {
	return jvNull(), fmt.Errorf("task mode %s not yet ported", mode)
}

// taskBackup mirrors backend.py's backup mode: an online backup into the
// configured backup directory named curator-<started_at_ms>.sqlite3.backup.
func taskBackup(db dbx, pluginDir string, payload jVal, settings jVal, startedAtMs int64) (jVal, error) {
	progressLog(0.05)
	directory := backupDirectory(pluginDir, payload, settings)
	destination := filepath.Join(directory, fmt.Sprintf("curator-%d.sqlite3.backup", startedAtMs))
	var backup string
	err := pythonSpan("task.backup", func() error {
		var err error
		backup, err = backupDatabase(db, destination, false, mappedProgress(0.05, 0.95))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	return jvObj(jvKey("backup", jvStr(backup))), nil
}

// taskCompact mirrors backend.py's compact mode.
func taskCompact(db dbx) (jVal, error) {
	progressLog(0.1)
	infoLog("Validating generation artifacts")
	var summary jVal
	err := pythonSpan("task.compact", func() error {
		var err error
		summary, err = compactLegacyGenerations(db, 5_000, -1, mappedProgress(0.10, 0.95))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	return summary, nil
}

// taskVacuum mirrors backend.py's vacuum mode.
func taskVacuum(db dbx, pluginDir string, payload jVal, settings jVal) (jVal, error) {
	status, err := compactionStatus(db)
	if err != nil {
		return jvNull(), err
	}
	if status.get("status").asString() != "complete" {
		return jvNull(), fmt.Errorf("compact legacy Curator data before vacuuming")
	}
	progressLog(0.05)
	database := realpath(databasePath(pluginDir, payload, settings))
	var before int64
	if info, err := os.Stat(database); err != nil {
		return jvNull(), err
	} else {
		before = info.Size()
	}
	infoLog("Vacuuming compacted Curator data")
	err = pythonSpan("task.vacuum", func() error {
		progressLog(0.10)
		if _, err := db.Exec(`VACUUM`); err != nil {
			return err
		}
		progressLog(0.94)
		_, err := db.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	var after int64
	if info, err := os.Stat(database); err != nil {
		return jvNull(), err
	} else {
		after = info.Size()
	}
	return jvObj(
		jvKey("bytes_before", jvInt(before)),
		jvKey("bytes_after", jvInt(after)),
	), nil
}

// runTaskModePending keeps strings import used by other helpers in this file.
var _ = strings.TrimSpace
