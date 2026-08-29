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
// the value clamped to [0, 1] and %.4f formatting, plus the active job's
// sidecar progress sink (debounced) when one is attached.
func progressLog(value float64) {
	fmt.Fprintf(os.Stderr, "\x01p\x02%.4f\n", math.Max(0.0, math.Min(value, 1.0)))
	progressSinkMu.Lock()
	sink := activeProgressSink
	progressSinkMu.Unlock()
	if sink != nil {
		sink.report(value)
	}
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

// runTaskBody posts the task to the Curator-owned worker queue and returns
// immediately, freeing Stash's single-slot job queue (docs/decisions/004).
// Same-type queued/running jobs coalesce into the existing already_running
// response. Worker coordination failures are terminal for this invocation:
// tasks never fall back to inline writes because a resident daemon may still
// own the sidecar.
func runTaskBody(pluginDir string, payload jVal, mode string, settings jVal) (jVal, error) {
	if !taskModeNative(mode) {
		return jvNull(), fmt.Errorf("unknown Curator task: %s", mode)
	}
	if err := checkWorkerStateWritableFn(pluginDir); err != nil {
		return jvNull(), fmt.Errorf("Curator worker coordination unavailable; refusing inline task: %w", err)
	}
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	jobID := uuid4()
	now := nowMs()
	staleBefore := now - 6*3_600_000
	var existingJobID, existingJobType string
	// Recover dead-owner running rows first (idempotent, independent of the
	// enqueue below) so a crashed worker's rows do not block the queue.
	recoverOrphanJobs(db, now)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		var existingID, existingType string
		err := conn.QueryRowContext(ctx, `
SELECT job_id, job_type FROM curator_job WHERE state IN ('queued', 'running')
AND job_type=? AND started_at_ms>? ORDER BY started_at_ms DESC LIMIT 1`,
			mode, staleBefore).Scan(&existingID, &existingType)
		if err == sql.ErrNoRows {
			payloadRaw, merr := marshalJVal(payload)
			if merr != nil {
				return merr
			}
			_, ierr := conn.ExecContext(ctx, `
INSERT INTO curator_job(job_id, job_type, state, started_at_ms, queued_at_ms, payload_json)
VALUES (?, ?, 'queued', ?, ?, ?)`, jobID, mode, now, now, payloadRaw)
			return ierr
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
	if workerErr := ensureWorker(pluginDir, payload, settings); workerErr != nil {
		failure := fmt.Errorf("Curator worker unavailable; queued task was not started: %w", workerErr)
		if err := execImmediate(db, `UPDATE curator_job SET state='failed', finished_at_ms=?, error=?
WHERE job_id=? AND state='queued'`, nowMs(), truncateString(failure.Error(), 2000), jobID); err != nil {
			return jvNull(), err
		}
		return jvNull(), failure
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("job_id", jvStr(jobID)),
		jvKey("queued", jvBool(true)),
		jvKey("job_type", jvStr(mode)),
	), nil
}

// openTaskSidecar opens the sidecar with artifact attaches on for every mode
// except compact/vacuum, which require a core-only connection (matching
// backend.py's reopen). It is a var so daemon tests can force an open failure
// and assert the fail-closed retirement path.
var openTaskSidecarFn = openTaskSidecar

func openTaskSidecar(pluginDir string, payload jVal, settings jVal, mode string) (dbx, error) {
	attach := mode != "compact" && mode != "vacuum"
	return openSidecar(pluginDir, payload, settings, attach)
}

// marshalJVal serializes a payload for the queue snapshot.
func marshalJVal(v jVal) (string, error) {
	var b strings.Builder
	v.writeJSON(&b)
	return b.String(), nil
}

// executeClaimedJob runs one claimed (state='running') job to completion:
// heartbeat + progress through the sidecar, the mode body, and guarded state
// transitions. Shared by the inline fallback and the daemon.
func executeClaimedJob(db dbx, pluginDir string, payload jVal, mode string, settings jVal, jobID string, startedAtMs int64) (jVal, error) {
	done := make(chan struct{})
	defer close(done)
	go heartbeatLoop(db, jobID, done)
	// The sink writes on its own connection (the execution pool is pinned to
	// one conn), so progress updates never block behind the mode's own
	// statements — or deadlock when a marker fires inside one of its txns.
	var prev *progressSink
	sink, sinkErr := newProgressSink(databasePath(pluginDir, payload, settings), jobID)
	if sinkErr != nil {
		infoLog(fmt.Sprintf("progress sink unavailable: %v", sinkErr))
	} else {
		prev = setProgressSink(sink)
		defer func() {
			setProgressSink(prev)
			sink.close()
		}()
	}
	infoLog(fmt.Sprintf("Stash Curator %s started", mode))
	progressLog(0.01)
	summary, taskErr := runTaskMode(db, pluginDir, payload, mode, settings, startedAtMs)
	// Land the last progress value before the terminal transition removes the
	// state='running' guard the sink writes under.
	if sink != nil {
		sink.flush()
	}
	if taskErr != nil {
		txnErr := withTxn(db, func(conn *sql.Conn) error {
			_, err := conn.ExecContext(context.Background(), `
UPDATE curator_job SET state='failed', finished_at_ms=?, error=?
WHERE job_id=? AND state='running'`, nowMs(), truncateString(taskErr.Error(), 2000), jobID)
			return err
		})
		if txnErr != nil {
			return jvNull(), txnErr
		}
		errorLog(fmt.Sprintf("Stash Curator %s failed: %s", mode, taskErr.Error()))
		return jvNull(), taskErr
	}
	progressLog(1.0)
	if sink != nil {
		sink.flush()
	}
	txnErr := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
UPDATE curator_job SET state='complete', finished_at_ms=?, summary_json=?
WHERE job_id=? AND state='running'`, nowMs(), summary.marshalSortedKeys(), jobID)
		return err
	})
	if txnErr != nil {
		return jvNull(), txnErr
	}
	infoLog(fmt.Sprintf("Stash Curator %s completed", mode))
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
	case "expand-rebuild":
		return taskExpandRebuild(db, pluginDir, payload, settings)
	case "build", "force-build", "update-model":
		return taskBuild(db, pluginDir, payload, mode)
	case "sync-build", "full-sync-build":
		return taskSyncBuild(db, pluginDir, payload, mode, settings)
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
	links, err := externalLinksRefresh(payload, db, mappedProgress(0.05, 0.08))
	if err != nil {
		return jvNull(), err
	}
	var summary jVal
	err = pythonSpan("task.expand_refresh", func() error {
		summary, err = expandRefresh(db, base, apiKey, links,
			int(pythonInt(cfg.get("expand_horizon_days"))),
			cfg.get("expand_gender").asString(),
			"",
			cfg.get("expand_wildcard").truthy(),
			int(pythonInt(cfg.get("expand_candidate_limit"))),
			int(pythonInt(cfg.get("expand_similar_seed_top_k"))),
			int(pythonInt(cfg.get("expand_similar_seed_per_favorite"))),
			false,
			nowMs(), mappedProgress(0.08, 0.98))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	return summary, nil
}

// taskExpandRebuild mirrors backend.py's expand-rebuild mode: a full,
// non-incremental refresh that re-pulls the whole window and ignores the
// watermark, so scenes a recent incremental pass missed are re-fetched.
func taskExpandRebuild(db dbx, pluginDir string, payload jVal, settings jVal) (jVal, error) {
	progressLog(0.05)
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	infoLog("Force rebuilding full Expand candidate window")
	base, apiKey, err := stashdbClient(payload)
	if err != nil {
		return jvNull(), err
	}
	links, err := externalLinksRefresh(payload, db, mappedProgress(0.05, 0.08))
	if err != nil {
		return jvNull(), err
	}
	var summary jVal
	err = pythonSpan("task.expand_rebuild", func() error {
		var err error
		summary, err = expandRefresh(db, base, apiKey, links,
			int(pythonInt(cfg.get("expand_horizon_days"))),
			cfg.get("expand_gender").asString(),
			"",
			cfg.get("expand_wildcard").truthy(),
			int(pythonInt(cfg.get("expand_candidate_limit"))),
			int(pythonInt(cfg.get("expand_similar_seed_top_k"))),
			int(pythonInt(cfg.get("expand_similar_seed_per_favorite"))),
			true,
			nowMs(), mappedProgress(0.08, 0.98))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.98)
	return summary, nil
}

// drainPendingEntityChanges mirrors backend.py's
// _drain_pending_entity_changes: process the hook queue through the sync
// service, dropping rows that complete or vanish.
func drainPendingEntityChanges(db dbx, base string, headers map[string]string) (int64, error) {
	rows, err := db.Query(`SELECT entity_type, entity_id, operation FROM pending_entity_change ORDER BY created_at_ms`)
	if err != nil {
		return 0, err
	}
	type pendingRow struct {
		entityType string
		entityID   string
		operation  string
	}
	var pending []pendingRow
	for rows.Next() {
		var entityType, entityID, operation string
		if err := rows.Scan(&entityType, &entityID, &operation); err != nil {
			rows.Close()
			return 0, err
		}
		pending = append(pending, pendingRow{entityType, entityID, operation})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	if len(pending) == 0 {
		return 0, nil
	}
	service, err := newSyncService(base, headers, newSyncRepository(db), 250)
	if err != nil {
		return 0, err
	}
	var drained int64
	var dropped []pendingRow
	for _, row := range pending {
		var opErr error
		if row.operation == "delete" {
			opErr = service.deleteEntity(row.entityType, row.entityID)
		} else {
			_, opErr = service.upsertEntity(row.entityType, row.entityID)
		}
		if opErr == nil {
			dropped = append(dropped, row)
			drained++
		} else if strings.Contains(opErr.Error(), "did not return") {
			dropped = append(dropped, row)
			warnLog(fmt.Sprintf("pending entity change failed for %s %s: %s",
				row.entityType, row.entityID, opErr.Error()))
		} else {
			warnLog(fmt.Sprintf("pending entity change failed for %s %s: %s",
				row.entityType, row.entityID, opErr.Error()))
		}
	}
	if len(dropped) > 0 {
		if err := withTxn(db, func(conn *sql.Conn) error {
			for _, row := range dropped {
				if _, err := conn.ExecContext(context.Background(),
					`DELETE FROM pending_entity_change WHERE entity_type=? AND entity_id=?`,
					row.entityType, row.entityID); err != nil {
					return err
				}
			}
			return nil
		}); err != nil {
			return 0, err
		}
	}
	return drained, nil
}

// syncEntityCounts serializes the count maps in the canonical entity order
// (ENTITY_OPERATIONS order: tags, studios, performers, scenes, scene_plays).
func syncEntityCounts(counts map[string]int64) jVal {
	out := jvObj()
	for _, entity := range []string{"tag", "studio", "performer", "scene", "scene_play"} {
		if value, ok := counts[entity]; ok {
			out.set(entity, jvInt(value))
		}
	}
	return out
}

// taskBuild mirrors backend.py's build / update-model mode.
func taskBuild(db dbx, pluginDir string, payload jVal, mode string) (jVal, error) {
	progressLog(0.1)
	infoLog("Building the recommendation model")
	modelMilestone := -1
	reportModel := func(processed, total int) {
		fraction := 1.0
		if total > 0 {
			fraction = math.Min(float64(processed)/float64(total), 1.0)
		}
		progressLog(0.03 + 0.92*fraction)
		milestone := int(fraction * 10)
		if milestone > modelMilestone {
			modelMilestone = milestone
			infoLog(fmt.Sprintf("Building recommendation model: %d%%", milestone*10))
		}
	}
	if mode == "build" || mode == "force-build" {
		if err := withTxn(db, func(conn *sql.Conn) error {
			if mode == "force-build" {
				if _, err := conn.ExecContext(context.Background(),
					`UPDATE model_version SET status='superseded' WHERE status='published'`); err != nil {
					return err
				}
			}
			return coordinatorRequest(conn, "manual_build", nowMs())
		}); err != nil {
			return jvNull(), err
		}
	}
	base, headers := stashConnection(payload)
	infoLog("Importing entity changes recorded by hooks")
	var drained int64
	err := pythonSpan("task.drain_entity_changes", func() error {
		var err error
		drained, err = drainPendingEntityChanges(db, base, headers)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	if drained > 0 {
		infoLog(fmt.Sprintf("Imported %d entity changes", drained))
	}
	var models []drainResult
	err = pythonSpan("task.model_build", func() error {
		var err error
		models, err = coordinatorDrain(db, true, 1, reportModel)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	if len(models) == 0 {
		progressLog(0.98)
		infoLog("No pending preference changes")
		return jvObj(jvKey("updated", jvBool(false))), nil
	}
	model := models[0]
	infoLog(fmt.Sprintf("Model build: %d ms, peak RSS %d kB",
		model.stageTimingsMs["total"], peakRSSKB()))
	progressLog(0.95)
	infoLog("Organizing scenes into recommendation lanes")
	laneCount, err := classifyLanesTask(db, model.modelID, mappedProgress(0.95, 0.97))
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.97)
	infoLog("Preparing recommendation pages")
	laneCaches, err := prepareLanesTask(db, model.modelID, false, mappedProgress(0.97, 0.99))
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.99)
	return jvObj(
		jvKey("updated", jvBool(true)),
		jvKey("model_id", jvStr(model.modelID)),
		jvKey("lane_classifications", jvInt(laneCount)),
		jvKey("lane_candidate_caches", laneCaches),
		jvKey("stage_timings_ms", stageTimingsJVal(model.stageTimingsMs)),
		jvKey("peak_rss_kb", jvInt(peakRSSKB())),
	), nil
}

// stageTimingOrder mirrors the model build's timings insertion order.
var stageTimingOrder = []string{
	"feature_lookup", "feature_build", "feature_database_writing", "feature_indexing",
	"feature_validation", "feature_publication", "feature_total", "labels", "affinities",
	"similarity", "scoring", "database_writing", "lane_classification",
	"score_first_ordering", "varied_ordering", "reason_generation",
	"sqlite_index_creation", "indexing", "validation", "publication", "cleanup", "total",
}

// stageTimingsJVal serializes the stage timings dict in insertion order.
func stageTimingsJVal(timings map[string]int64) jVal {
	out := jvObj()
	for _, key := range stageTimingOrder {
		if value, ok := timings[key]; ok {
			out.set(key, jvInt(value))
		}
	}
	return out
}

// stageTimingsJValForExpand serializes the expand refresh phase timings in a
// stable insertion order (the refresh summary's stage_timings_ms).
func stageTimingsJValForExpand(timings map[string]int64) jVal {
	out := jvObj()
	for _, key := range expandStageTimingOrder {
		if value, ok := timings[key]; ok {
			out.set(key, jvInt(value))
		}
	}
	return out
}

// expandStageTimingOrder mirrors ExpandService.refresh's timing insertion
// order (Go and Python must agree so a future comparison stays stable).
var expandStageTimingOrder = []string{
	"taxonomy", "seeds", "fetch", "score", "database_writing", "total",
	"seeds_profiles", "seeds_chase_network", "seeds_chase_match", "seeds_chase_calls",
}

// taskSyncBuild mirrors backend.py's sync-build / full-sync-build mode.
func taskSyncBuild(db dbx, pluginDir string, payload jVal, mode string, settings jVal) (jVal, error) {
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	loggedMilestones := map[string]int{}
	reportSync := func(entity string, processed, total int64, position, entityCount int) {
		fraction := 1.0
		if total > 0 {
			fraction = math.Min(float64(processed)/float64(total), 1.0)
		}
		progressLog(0.03 + 0.52*(float64(position)+fraction)/float64(maxInt(1, entityCount)))
		milestone := int(fraction * 10)
		if milestone > loggedMilestones[entity] {
			loggedMilestones[entity] = milestone
			infoLog(fmt.Sprintf("Synchronizing %ss: %d/%d", entity, processed, total))
		}
	}
	base, headers := stashConnection(payload)
	infoLog("Synchronizing Stash metadata")
	var synced syncResult
	err = pythonSpan("task.sync", func() error {
		service, err := newSyncService(base, headers, newSyncRepository(db),
			pythonInt(cfg.get("sync_page_size")))
		if err != nil {
			return err
		}
		service.progress = reportSync
		synced, err = service.sync(mode == "full-sync-build", false)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	var pruneChanged bool
	err = pythonSpan("task.reconcile_prune", func() error {
		var err error
		pruneChanged, err = reconcilePruneTag(db, cfg.get("prune_tag_name").asString())
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.58)
	infoLog("Rebuilding historical preference signals")
	historicalSceneIDs := []string(nil)
	if mode != "full-sync-build" && !synced.resumed {
		historicalSceneIDs = synced.sceneIDs
	}
	var historical historicalBuildResult
	err = pythonSpan("task.historical_events", func() error {
		var err error
		historical, err = historicalRebuild(db, historicalSceneIDs, mappedProgress(0.58, 0.68))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.68)
	if err := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `DELETE FROM pending_entity_change`)
		return err
	}); err != nil {
		return jvNull(), err
	}
	for _, entity := range sortedStringKeys(synced.deletedEntityCounts) {
		infoLog(fmt.Sprintf("Removed %d %ss deleted from Stash", synced.deletedEntityCounts[entity], entity))
	}
	sourceChanged := mode == "full-sync-build" || synced.resumed ||
		len(synced.changedEntityCounts) > 0 || len(synced.deletedEntityCounts) > 0 || pruneChanged
	currentModelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if sourceChanged || currentModelID == "" {
		if err := withTxn(db, func(conn *sql.Conn) error {
			return coordinatorRequest(conn, "source_sync", nowMs())
		}); err != nil {
			return jvNull(), err
		}
	}
	var modelID string
	var stageTimings map[string]int64
	if sourceChanged || currentModelID == "" {
		infoLog("Building the recommendation model")
		var models []drainResult
		err = pythonSpan("task.model_build", func() error {
			var err error
			models, err = coordinatorDrain(db, true, 1, mappedProgress(0.68, 0.95))
			return err
		})
		if err != nil {
			return jvNull(), err
		}
		modelID = models[0].modelID
		stageTimings = models[0].stageTimingsMs
		infoLog(fmt.Sprintf("Model build: %d ms, peak RSS %d kB",
			stageTimings["total"], peakRSSKB()))
	} else {
		progressLog(0.95)
		infoLog("No Stash changes; keeping the current recommendation model")
		modelID = currentModelID
		stageTimings = map[string]int64{}
	}
	progressLog(0.95)
	infoLog("Organizing scenes into recommendation lanes")
	laneCount, err := classifyLanesTask(db, modelID, mappedProgress(0.95, 0.97))
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.97)
	infoLog("Preparing recommendation pages")
	laneCaches, err := prepareLanesTask(db, modelID, false, mappedProgress(0.97, 0.99))
	if err != nil {
		return jvNull(), err
	}
	progressLog(0.99)
	infoLog(fmt.Sprintf("Recommendation model ready: %s", modelID))
	return jvObj(
		jvKey("sync_run_id", jvStr(synced.runID)),
		jvKey("entity_counts", syncEntityCounts(synced.entityCounts)),
		jvKey("changed_entity_counts", syncEntityCounts(synced.changedEntityCounts)),
		jvKey("historical_scenes", jvInt(historical.sceneCount)),
		jvKey("model_id", jvStr(modelID)),
		jvKey("lane_classifications", jvInt(laneCount)),
		jvKey("lane_candidate_caches", laneCaches),
		jvKey("stage_timings_ms", stageTimingsJVal(stageTimings)),
		jvKey("peak_rss_kb", jvInt(peakRSSKB())),
	), nil
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
		backup, err = backupDatabaseValidated(db, destination, false, mappedProgress(0.05, 0.95))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	if err := mirrorDerivedArtifacts(db, directory); err != nil {
		// The database backup is the contract; the artifact mirror is
		// best-effort additive recovery data, so a mirror failure warns
		// (plugin logs) instead of failing the backup task.
		warnLog("derived artifact mirror failed: " + err.Error())
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
