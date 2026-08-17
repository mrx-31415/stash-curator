// Slice-0 backend operations: round_trip, health, get_config, get_job_status —
// byte-identical to plugin/backend.py for the same payloads and sidecar state.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

const apiSchemaVersion = 1

// stashdbEndpoint mirrors curator/expand.py STASHDB.
const stashdbEndpoint = "https://stashdb.org/graphql"

// taskDisplayNames maps the yml task mode to its display name so health can
// synthesize the Stash-style job description the frontend's task indicator
// and stage mapping consume (mirrors backend.py's TASK_DISPLAY_NAMES).
var taskDisplayNames = map[string]string{
	"sync-build":      "Sync and build recommendations",
	"full-sync-build": "Full sync and build recommendations",
	"build":           "Rebuild recommendation model",
	"update-model":    "Apply recent Curator feedback",
	"sync-plays":      "Sync recent plays",
	"prepare":         "Prepare recommendation pages",
	"backup":          "Backup Curator data",
	"compact":         "Compact legacy Curator data",
	"vacuum":          "Vacuum compacted Curator data",
	"expand-refresh":  "Refresh Expand cache",
}

// activeCuratorJobs renders the queued + running curator_job rows in the
// Stash job shape the frontend's task indicator consumes ({id, description,
// progress}), with the Stash-style description the stage mapping matches.
func activeCuratorJobs(db dbx) ([]jVal, error) {
	rows, err := db.Query(`SELECT job_id, job_type, progress FROM curator_job
WHERE state IN ('queued', 'running') ORDER BY started_at_ms DESC LIMIT 10`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var jobs []jVal
	for rows.Next() {
		var jobID, jobType string
		var progress sql.NullFloat64
		if err := rows.Scan(&jobID, &jobType, &progress); err != nil {
			return nil, err
		}
		name, ok := taskDisplayNames[jobType]
		if !ok {
			name = jobType
		}
		progressVal := jvNull()
		if progress.Valid {
			progressVal = jvFloat(progress.Float64)
		}
		jobs = append(jobs, jvObj(
			jvKey("id", jvStr(jobID)),
			jvKey("description", jvStr("Running plugin task: "+name)),
			jvKey("progress", progressVal),
		))
	}
	return jobs, rows.Err()
}

func opRoundTrip(pluginDir string, payload jVal) (jVal, error) {
	db, err := openSidecar(pluginDir, payload, jvObj(), true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	if err := execImmediate(db, `INSERT INTO application_meta(key, value) VALUES ('plugin_round_trips', '1')
ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1`); err != nil {
		return jvNull(), err
	}
	var value string
	if err := db.QueryRow(`SELECT value FROM application_meta WHERE key='plugin_round_trips'`).Scan(&value); err != nil {
		return jvNull(), err
	}
	count, err := strconv.ParseInt(value, 10, 64)
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("round_trips", jvInt(count)),
		jvKey("synthetic_slate", jvArr(jvObj(
			jvKey("scene_id", jvStr("runtime-proof")),
			jvKey("lane", jvStr("for_you")),
			jvKey("position", jvInt(0)),
		))),
	), nil
}

// isBusyError reports whether err is a SQLite busy failure: SQLITE_BUSY (5)
// and the extended SQLITE_BUSY_RECOVERY (261), SQLITE_BUSY_SNAPSHOT (517),
// and SQLITE_BUSY_TIMEOUT (773) codes. The busy_timeout handler retries only
// the plain code in some SQLite versions (modernc ships 3.41.2), so the
// extended codes get a bounded retry here — the #109 mitigation for
// lock contention between concurrent plugin processes. The matcher follows
// similar.go's casefold "locked" convention.
func isBusyError(err error) bool {
	if err == nil {
		return false
	}
	message := strings.ToLower(err.Error())
	return strings.Contains(message, "locked") || strings.Contains(message, "busy")
}

// busyRetryBackoff is the sleep between busy-retry attempts (150 ms, 300 ms).
func busyRetryBackoff(attempt int) time.Duration {
	return time.Duration(150*(attempt+1)) * time.Millisecond
}

const busyRetryAttempts = 3

// execImmediate runs one statement in an explicit BEGIN IMMEDIATE transaction,
// mirroring curator.storage.transaction (no nested transactions). Busy
// failures before COMMIT are retried with backoff; a COMMIT failure is never
// retried (its outcome is ambiguous and re-running the statement could
// double-apply non-idempotent writes).
func execImmediate(db dbx, statement string, args ...any) error {
	var lastErr error
	for attempt := range busyRetryAttempts {
		conn, err := db.Conn(context.Background())
		if err != nil {
			return err
		}
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
			conn.Close()
			if isBusyError(err) && attempt < busyRetryAttempts-1 {
				lastErr = err
				time.Sleep(busyRetryBackoff(attempt))
				continue
			}
			return err
		}
		if _, err := conn.ExecContext(ctx, statement, args...); err != nil {
			conn.ExecContext(ctx, "ROLLBACK")
			conn.Close()
			if isBusyError(err) && attempt < busyRetryAttempts-1 {
				lastErr = err
				time.Sleep(busyRetryBackoff(attempt))
				continue
			}
			return err
		}
		if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
			conn.Close()
			return err
		}
		conn.Close()
		return nil
	}
	return lastErr
}

func opGetJobStatus(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	rows, err := db.Query(`SELECT * FROM curator_job ORDER BY started_at_ms DESC LIMIT 10`)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return jvNull(), err
	}
	jobs := jvArr()
	for rows.Next() {
		values := make([]any, len(columns))
		scanned := make([]any, len(columns))
		for i := range columns {
			scanned[i] = &values[i]
		}
		if err := rows.Scan(scanned...); err != nil {
			return jvNull(), err
		}
		row := make(map[string]any, len(columns))
		for i, name := range columns {
			row[name] = values[i]
		}
		job := jvObj(
			jvKey("job_id", jvStr(asDBString(row["job_id"]))),
			jvKey("job_type", jvStr(asDBString(row["job_type"]))),
			jvKey("state", jvStr(asDBString(row["state"]))),
			jvKey("started_at_ms", jvInt(asDBInt(row["started_at_ms"]))),
			jvKey("finished_at_ms", dbOptionalInt(row["finished_at_ms"])),
			jvKey("summary", dbSummary(row["summary_json"])),
			jvKey("error", dbOptionalString(row["error"])),
			jvKey("queued_at_ms", dbOptionalInt(row["queued_at_ms"])),
			jvKey("progress", dbOptionalFloat(row["progress"])),
		)
		jobs.arr = append(jobs.arr, job)
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("jobs", jobs),
	), nil
}

// opCancelJob cancels a queued job instantly and requests cooperative cancel
// of a running one (the worker marks it cancelled at its next heartbeat
// tick). A finished or unknown job reports cancelled: false.
func opCancelJob(pluginDir string, payload jVal) (jVal, error) {
	args := payload.get("args")
	jobID := args.get("job_id").asString()
	if jobID == "" {
		return jvNull(), fmt.Errorf("job_id is required")
	}
	settings := pluginSettings(payload)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	now := nowMs()
	result, err := db.Exec(`UPDATE curator_job SET state='cancelled', finished_at_ms=?
WHERE job_id=? AND state='queued'`, now, jobID)
	if err != nil {
		return jvNull(), err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return jvNull(), err
	}
	if affected > 0 {
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("job_id", jvStr(jobID)),
			jvKey("cancelled", jvBool(true)),
			jvKey("state", jvStr("cancelled")),
		), nil
	}
	result, err = db.Exec(`UPDATE curator_job SET cancel_requested=1
WHERE job_id=? AND state='running'`, jobID)
	if err != nil {
		return jvNull(), err
	}
	affected, err = result.RowsAffected()
	if err != nil {
		return jvNull(), err
	}
	if affected > 0 {
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("job_id", jvStr(jobID)),
			jvKey("cancelled", jvBool(true)),
			jvKey("state", jvStr("running")),
			jvKey("cancel_requested", jvBool(true)),
		), nil
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("job_id", jvStr(jobID)),
		jvKey("cancelled", jvBool(false)),
		jvKey("error", jvStr("no active job with that id")),
	), nil
}

func asDBString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	if b, ok := v.([]byte); ok {
		return string(b)
	}
	return ""
}

func asDBInt(v any) int64 {
	switch t := v.(type) {
	case int64:
		return t
	case float64:
		return int64(t)
	case string:
		n, _ := strconv.ParseInt(t, 10, 64)
		return n
	case []byte:
		n, _ := strconv.ParseInt(string(t), 10, 64)
		return n
	}
	return 0
}

// dbOptionalInt mirrors Python's `int(v) if v else None`: null and falsy
// zero both become None.
func dbOptionalInt(v any) jVal {
	switch t := v.(type) {
	case nil:
		return jvNull()
	case int64:
		if t == 0 {
			return jvNull()
		}
		return jvInt(t)
	case float64:
		if t == 0 {
			return jvNull()
		}
		return jvInt(int64(t))
	case string:
		if t == "" {
			return jvNull()
		}
		n, _ := strconv.ParseInt(t, 10, 64)
		return jvInt(n)
	case []byte:
		if len(t) == 0 {
			return jvNull()
		}
		n, _ := strconv.ParseInt(string(t), 10, 64)
		return jvInt(n)
	}
	return jvNull()
}

// dbOptionalString mirrors Python's `str(v) if v else None`: null and empty
// both become None.
func dbOptionalFloat(v any) jVal {
	if v == nil {
		return jvNull()
	}
	switch n := v.(type) {
	case float64:
		return jvFloat(n)
	case int64:
		return jvFloat(float64(n))
	case int:
		return jvFloat(float64(n))
	}
	return jvNull()
}

func dbOptionalString(v any) jVal {
	switch t := v.(type) {
	case nil:
		return jvNull()
	case string:
		if t == "" {
			return jvNull()
		}
		return jvStr(t)
	case []byte:
		if len(t) == 0 {
			return jvNull()
		}
		return jvStr(string(t))
	}
	return jvNull()
}

// dbSummary parses summary_json the way json.loads does.
func dbSummary(v any) jVal {
	raw := asDBString(v)
	parsed, err := parseJSON([]byte(raw))
	if err != nil {
		return jvNull()
	}
	return parsed
}

// opGetConfig mirrors backend.py's _profiled-wrapped get_config: a trace is
// opened first (so the settings fetch records a stash span), and when
// profilingEnabled is on the trace is saved as a profile_trace row — even
// when the operation fails. Save failures only log a warning.
func opGetConfig(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_config",
		func(settings jVal) (jVal, error) { return getConfigBody(pluginDir, payload, settings) })
}

func getConfigBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	result, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	result.set("code_version", jvStr(installedCodeVersion(pluginDir)))
	result.set("whisparr_enabled", jvBool(whisparrEnabled(settings)))
	return result, nil
}

// whisparrEnabled mirrors backend.py: str(value or "") for both keys must be
// non-empty after stripping.
func whisparrEnabled(settings jVal) bool {
	url := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrUrl")))
	key := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrApiKey")))
	return url != "" && key != ""
}

// pythonStrOrEmpty mirrors Python's `str(value or "")`.
func pythonStrOrEmpty(v jVal) string {
	if !v.truthy() {
		return ""
	}
	return v.asString()
}

// installedCodeVersion mirrors backend.py's _installed_code_version: sha256
// of the sorted, resolved installed python sources (plugin dir + its parent
// package root), truncated to 16 hex digits.
func installedCodeVersion(pluginDir string) string {
	roots := []string{pluginDir, filepath.Dir(pluginDir)}
	seen := make(map[string]bool)
	var files []string
	addFile := func(path string) {
		resolved := realpath(path)
		if seen[resolved] {
			return
		}
		if info, err := os.Stat(resolved); err != nil || !info.Mode().IsRegular() {
			return
		}
		seen[resolved] = true
		files = append(files, resolved)
	}
	for _, root := range roots {
		curatorDir := filepath.Join(root, "curator")
		filepath.WalkDir(curatorDir, func(path string, entry fs.DirEntry, err error) error {
			if err != nil {
				return nil // missing curator package under this root
			}
			if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".py") {
				addFile(path)
			}
			return nil
		})
	}
	entries, err := os.ReadDir(pluginDir)
	if err == nil {
		for _, entry := range entries {
			if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".py") {
				addFile(filepath.Join(pluginDir, entry.Name()))
			}
		}
	}
	sort.Strings(files)
	digest := sha256.New()
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		digest.Write(data)
	}
	return hex.EncodeToString(digest.Sum(nil))[:16]
}

func opHealth(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	base, headers := stashConnection(payload)
	stash, err := graphqlQuery(base, headers, runtimeQuery, jvNull())
	if err != nil {
		return jvNull(), err
	}
	version, err := requireKey(stash, "version")
	if err != nil {
		return jvNull(), err
	}
	stashVersion, err := requireKey(version, "version")
	if err != nil {
		return jvNull(), err
	}
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	now := nowMs()
	// Worker-owned liveness: fail running rows whose executing process is
	// gone (heartbeat stale or legacy pre-heartbeat age). This replaces the
	// old Stash-job-list + 120s heuristic, which no longer applies once
	// tasks run in the detached worker instead of a live Stash job.
	recoverOrphanJobs(db, now)
	activeJobs, err := activeCuratorJobs(db)
	if err != nil {
		return jvNull(), err
	}
	var activeJob jVal = jvNull()
	if len(activeJobs) > 0 {
		activeJob = activeJobs[0]
	}
	migration, err := queryMigrationStatus(db)
	if err != nil {
		return jvNull(), err
	}
	var currentModelID sql.NullString
	if err := db.QueryRow(`SELECT model_id FROM model_version WHERE status='published'`).Scan(&currentModelID); err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	var lastSyncAt sql.NullInt64
	if err := db.QueryRow(`SELECT finished_at_ms FROM curator_job
WHERE job_type IN ('sync-build', 'full-sync-build') AND state='complete'
ORDER BY finished_at_ms DESC LIMIT 1`).Scan(&lastSyncAt); err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	var modelRebuilding int
	err = db.QueryRow(`SELECT 1 FROM curator_job
WHERE state='running' AND started_at_ms>? AND job_type IN (
    'build', 'update-model', 'sync-build', 'full-sync-build'
) LIMIT 1`, now-6*3_600_000).Scan(&modelRebuilding)
	if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	rebuilding := err == nil
	modelUpdate, err := modelUpdateStatus(db)
	if err != nil {
		return jvNull(), err
	}
	modelUpdateReady := modelUpdateReady(
		modelUpdate,
		now,
		int(pythonInt(cfg.get("model_update_event_threshold"))),
		pyRound(pythonFloatOr(cfg.get("model_update_max_wait_minutes"), 0)*60_000),
		pyRound(pythonFloatOr(cfg.get("model_update_min_interval_minutes"), 0)*60_000),
	)
	capture := jvObj(
		jvKey("direct_playback_sessions", jvInt(scanCount(db, `SELECT count(*) FROM play_session WHERE provenance='direct_player'`))),
		jvKey("direct_behavior_events", jvInt(scanCount(db, `SELECT count(*) FROM behavior_event WHERE provenance='direct_player'`))),
		jvKey("qualified_impressions", jvInt(scanCount(db, `SELECT count(*) FROM impression_item WHERE qualified_at_ms IS NOT NULL`))),
		jvKey("last_playback_at_ms", scanMaxMs(db, `SELECT max(ended_at_ms) FROM play_session WHERE provenance='direct_player'`)),
	)

	var modelID jVal = jvNull()
	if currentModelID.Valid {
		modelID = jvStr(currentModelID.String)
	}
	var lastSyncMs jVal = jvNull()
	if lastSyncAt.Valid {
		lastSyncMs = jvInt(lastSyncAt.Int64)
	}
	boxes := stash.get("configuration").get("general").get("stashBoxes")
	stashdbAvailable := stashdbConfigured(boxes)
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("curator_version", jvStr(coreVersion)),
		jvKey("stash_version", stashVersion),
		jvKey("database", jvStr(databasePath(pluginDir, payload, settings))),
		jvKey("database_schema", jvInt(int64(migration.currentVersion))),
		jvKey("database_schema_latest", jvInt(int64(migration.latestVersion))),
		jvKey("sidecar_ready", jvBool(len(migration.pending) == 0)),
		jvKey("model_id", modelID),
		jvKey("ready", jvBool(currentModelID.Valid)),
		jvKey("sync_ready", jvBool(lastSyncAt.Valid)),
		jvKey("stashdb_available", jvBool(stashdbAvailable)),
		jvKey("capture", capture),
		jvKey("model_pending", jvBool(modelUpdate.pending())),
		jvKey("model_pending_events", jvInt(modelUpdate.pendingCount())),
		jvKey("model_update_ready", jvBool(modelUpdateReady)),
		jvKey("model_rebuilding", jvBool(rebuilding)),
		jvKey("active_job", activeJob),
		jvKey("active_jobs", jvArr(activeJobs...)),
		jvKey("last_sync_at_ms", lastSyncMs),
	), nil
}

// requireKey mimics Python's dict subscript on health's GraphQL fields: a
// missing key raises KeyError whose str() is the quoted key name.
func requireKey(v jVal, key string) (jVal, error) {
	if v.kind != jObj || !v.has(key) {
		return jvNull(), fmt.Errorf("'%s'", key)
	}
	return v.get(key), nil
}

func stashdbConfigured(boxes jVal) bool {
	if boxes.kind != jArr {
		return false
	}
	for _, box := range boxes.arr {
		endpoint := strings.TrimRight(box.get("endpoint").asString(), "/")
		if strings.EqualFold(endpoint, strings.TrimRight(stashdbEndpoint, "/")) && box.get("api_key").truthy() {
			return true
		}
	}
	return false
}

func scanCount(db dbx, query string) int64 {
	var count int64
	if err := db.QueryRow(query).Scan(&count); err != nil {
		return 0
	}
	return count
}

func scanMaxMs(db dbx, query string) jVal {
	var value sql.NullInt64
	if err := db.QueryRow(query).Scan(&value); err != nil || !value.Valid {
		return jvNull()
	}
	return jvInt(value.Int64)
}

type modelUpdateState struct {
	requestedGeneration int64
	publishedGeneration int64
	requestedAtMs       sql.NullInt64
	lastFinishedAtMs    sql.NullInt64
}

func (s modelUpdateState) pending() bool { return s.requestedGeneration > s.publishedGeneration }
func (s modelUpdateState) pendingCount() int64 {
	if s.requestedGeneration > s.publishedGeneration {
		return s.requestedGeneration - s.publishedGeneration
	}
	return 0
}

// modelUpdateStatus mirrors ModelUpdateCoordinator.status() on the fields
// health needs.
func modelUpdateStatus(db dbx) (modelUpdateState, error) {
	var state modelUpdateState
	err := db.QueryRow(`SELECT requested_generation, published_generation, requested_at_ms, last_finished_at_ms
FROM model_update_state WHERE singleton=1`).
		Scan(&state.requestedGeneration, &state.publishedGeneration, &state.requestedAtMs, &state.lastFinishedAtMs)
	return state, err
}

// modelUpdateReady mirrors ModelUpdateStatus.ready.
func modelUpdateReady(s modelUpdateState, nowMs int64, eventThreshold int, maxWaitMs int64, minIntervalMs int64) bool {
	if !s.pending() {
		return false
	}
	enoughEvents := s.pendingCount() >= int64(eventThreshold)
	waitedLongEnough := s.requestedAtMs.Valid && nowMs-s.requestedAtMs.Int64 >= maxWaitMs
	intervalElapsed := !s.lastFinishedAtMs.Valid || nowMs-s.lastFinishedAtMs.Int64 >= minIntervalMs
	return intervalElapsed && (enoughEvents || waitedLongEnough)
}

func pythonFloatOr(v jVal, fallback float64) float64 {
	f, err := pythonFloat(v)
	if err != nil {
		return fallback
	}
	return f
}
