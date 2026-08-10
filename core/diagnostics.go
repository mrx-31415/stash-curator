// get_diagnostics — a port of backend.py's _diagnostics: migration status,
// readiness flags, generation diagnostics (curator/storage/artifacts.py),
// compaction status (curator/storage/database.py), and the recent job
// aggregate.
package main

import (
	"database/sql"
	"sort"
)

// diagnosticJobTypes mirrors backend.py's DIAGNOSTIC_JOB_TYPES.
var diagnosticJobTypes = map[string]bool{
	"sync-build": true, "full-sync-build": true, "sync-plays": true,
	"build": true, "update-model": true, "prepare": true,
	"backup": true, "compact": true, "vacuum": true, "expand-refresh": true,
}

func opGetDiagnostics(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_diagnostics",
		func(settings jVal) (jVal, error) { return getDiagnosticsBody(pluginDir, payload, settings) })
}

func getDiagnosticsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	migration, err := queryMigrationStatus(db)
	if err != nil {
		return jvNull(), err
	}
	var modelProbe int
	model := false
	err = db.QueryRow(`SELECT 1 FROM model_version WHERE status='published' LIMIT 1`).Scan(&modelProbe)
	if err == nil {
		model = true
	} else if err != sql.ErrNoRows {
		return jvNull(), err
	}
	sync := false
	err = db.QueryRow(`SELECT 1 FROM curator_job
WHERE job_type IN ('sync-build', 'full-sync-build') AND state='complete' LIMIT 1`).Scan(&modelProbe)
	if err == nil {
		sync = true
	} else if err != sql.ErrNoRows {
		return jvNull(), err
	}
	var requestedGen, publishedGen int64
	var lastDurationMs sql.NullInt64
	if err := db.QueryRow(`SELECT requested_generation, published_generation, last_duration_ms
FROM model_update_state WHERE singleton=1`).Scan(&requestedGen, &publishedGen, &lastDurationMs); err != nil {
		return jvNull(), err
	}
	type jobRow struct {
		jobType      string
		state        string
		startedAtMs  int64
		finishedAtMs sql.NullInt64
	}
	var rows []jobRow
	jobRows, err := db.Query(`SELECT job_type, state, started_at_ms, finished_at_ms
FROM curator_job ORDER BY started_at_ms DESC LIMIT 50`)
	if err != nil {
		return jvNull(), err
	}
	for jobRows.Next() {
		var row jobRow
		if err := jobRows.Scan(&row.jobType, &row.state, &row.startedAtMs, &row.finishedAtMs); err != nil {
			return jvNull(), err
		}
		if diagnosticJobTypes[row.jobType] {
			rows = append(rows, row)
		}
	}
	jobRows.Close()
	if err := jobRows.Err(); err != nil {
		return jvNull(), err
	}
	recentJobs := jvArr()
	for _, row := range rows[:minInt(10, len(rows))] {
		var finishedVal jVal = jvNull()
		var durationVal jVal = jvNull()
		if row.finishedAtMs.Valid {
			finishedVal = jvInt(row.finishedAtMs.Int64)
			durationVal = jvInt(row.finishedAtMs.Int64 - row.startedAtMs)
		}
		recentJobs.arr = append(recentJobs.arr, jvObj(
			jvKey("job_type", jvStr(row.jobType)),
			jvKey("outcome", jvStr(row.state)),
			jvKey("started_at_ms", jvInt(row.startedAtMs)),
			jvKey("finished_at_ms", finishedVal),
			jvKey("duration_ms", durationVal),
		))
	}
	durations := make(map[string][]int64)
	for _, row := range rows {
		if row.finishedAtMs.Valid {
			durations[row.jobType] = append(durations[row.jobType], row.finishedAtMs.Int64-row.startedAtMs)
		}
	}
	jobTypes := make([]string, 0, len(durations))
	for jobType := range durations {
		jobTypes = append(jobTypes, jobType)
	}
	sort.Strings(jobTypes)
	jobsAgg := jvArr()
	for _, jobType := range jobTypes {
		values := durations[jobType]
		sum := int64(0)
		max := int64(0)
		for _, v := range values {
			sum += v
			if v > max {
				max = v
			}
		}
		avg := int64(roundFloat(float64(sum) / float64(len(values))))
		jobsAgg.arr = append(jobsAgg.arr, jvObj(
			jvKey("job_type", jvStr(jobType)),
			jvKey("count", jvInt(int64(len(values)))),
			jvKey("average", jvInt(avg)),
			jvKey("maximum", jvInt(max)),
		))
	}
	generations, err := generationDiagnostics(db)
	if err != nil {
		return jvNull(), err
	}
	compaction, err := compactionStatus(db)
	if err != nil {
		return jvNull(), err
	}
	var lastModelUpdate jVal = jvNull()
	if lastDurationMs.Valid {
		lastModelUpdate = jvInt(lastDurationMs.Int64)
	}
	return jvObj(
		jvKey("report_version", jvInt(1)),
		jvKey("generated_at_ms", jvInt(nowMs())),
		jvKey("curator_version", jvStr(coreVersion)),
		jvKey("api_schema_version", jvInt(apiSchemaVersion)),
		jvKey("migration", jvObj(
			jvKey("current_version", jvInt(int64(migration.currentVersion))),
			jvKey("latest_version", jvInt(int64(migration.latestVersion))),
			jvKey("pending_count", jvInt(int64(len(migration.pending)))),
		)),
		jvKey("readiness", jvObj(
			jvKey("sidecar", jvBool(len(migration.pending) == 0)),
			jvKey("library_sync", jvBool(sync)),
			jvKey("recommendation_model", jvBool(model)),
			jvKey("model_update_pending", jvBool(requestedGen > publishedGen)),
		)),
		jvKey("generations", generations),
		jvKey("compaction", compaction),
		jvKey("recent_jobs", recentJobs),
		jvKey("timing_ms", jvObj(
			jvKey("last_model_update", lastModelUpdate),
			jvKey("jobs", jobsAgg),
		)),
	), nil
}

func roundFloat(f float64) float64 {
	return float64(pyRound(f))
}

// generationDiagnostics mirrors artifacts.generation_diagnostics.
func generationDiagnostics(db dbx) (jVal, error) {
	cleanup := int64(0)
	for _, table := range []string{"feature_build", "model_version"} {
		columns, err := tableColumns(db, table)
		if err != nil {
			return jvNull(), err
		}
		if _, ok := columns["cleanup_error"]; !ok {
			continue
		}
		var count int64
		if err := db.QueryRow(`SELECT count(*) FROM ` + table + ` WHERE cleanup_error IS NOT NULL`).Scan(&count); err != nil {
			return jvNull(), err
		}
		cleanup += count
	}
	result := jvObj(jvKey("cleanup_retry_count", jvInt(cleanup)))
	for _, kind := range []struct {
		kind       string
		table      string
		identifier string
	}{{"feature", "feature_build", "feature_version"}, {"model", "model_version", "model_id"}} {
		columns, err := tableColumns(db, kind.table)
		if err != nil {
			return jvNull(), err
		}
		if _, ok := columns["artifact_basename"]; !ok {
			result.set(kind.kind, jvNull())
			continue
		}
		var identifier, basename string
		var schemaVersion, bytes, reuseCount int64
		var validationStatus string
		var validationSummary, cleanupError sql.NullString
		err = db.QueryRow(`SELECT `+kind.identifier+`, artifact_basename, artifact_schema_version, artifact_bytes,
		       validation_status, validation_summary_json, cleanup_error, reuse_count
		FROM `+kind.table+` WHERE status='published'`).
			Scan(&identifier, &basename, &schemaVersion, &bytes, &validationStatus, &validationSummary, &cleanupError, &reuseCount)
		if err == sql.ErrNoRows {
			result.set(kind.kind, jvNull())
			continue
		}
		if err != nil {
			return jvNull(), err
		}
		var validation jVal = jvNull()
		if validationSummary.Valid && validationSummary.String != "" {
			validation, err = parseJSON([]byte(validationSummary.String))
			if err != nil {
				validation = jvNull()
			}
		} else {
			validation = jvNull()
		}
		result.set(kind.kind, jvObj(
			jvKey(kind.identifier, jvStr(identifier)),
			jvKey("artifact_basename", jvStr(basename)),
			jvKey("schema_version", jvInt(schemaVersion)),
			jvKey("bytes", jvInt(bytes)),
			jvKey("validation_status", jvStr(validationStatus)),
			jvKey("validation", validation),
			jvKey("reuse_count", jvInt(reuseCount)),
			jvKey("cleanup_retry", jvBool(cleanupError.Valid)),
		))
	}
	return result, nil
}

// compactionStatus mirrors storage.database.compaction_status.
func compactionStatus(db dbx) (jVal, error) {
	var value sql.NullString
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='legacy_compaction'`).Scan(&value)
	if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	stored := jvObj()
	if value.Valid {
		stored, err = parseJSON([]byte(value.String))
		if err != nil {
			stored = jvObj()
		}
	}
	var pageSize int64
	if err := db.QueryRow(`PRAGMA page_size`).Scan(&pageSize); err != nil {
		return jvNull(), err
	}
	var freelistCount int64
	if err := db.QueryRow(`PRAGMA freelist_count`).Scan(&freelistCount); err != nil {
		return jvNull(), err
	}
	status := "never_run"
	if v := stored.get("status"); v.kind == jStr && v.s != "" {
		status = v.s
	}
	return jvObj(
		jvKey("status", jvStr(status)),
		jvKey("rows_deleted", jvInt(pythonInt(stored.get("rows_deleted")))),
		jvKey("logical_bytes_removed", jvInt(pythonInt(stored.get("logical_bytes_removed")))),
		jvKey("reclaimable_bytes", jvInt(freelistCount*pageSize)),
		jvKey("vacuum_pending", jvBool(freelistCount > 0)),
	), nil
}
