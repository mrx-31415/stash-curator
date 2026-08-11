// Profile-trace ops — list_profiles / get_profile / clear_profiles, ports of
// backend.py's dispatch branches and curator/profiling.py's list_traces /
// get_trace / clear_traces. These run without the _profiled lifecycle (like
// backend.py's excluded set).
package main

import (
	"database/sql"
	"fmt"
)

func opListProfiles(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	limit := argsInt(payload.get("args"), "limit", 50)
	if limit < 1 || limit > maxTraces {
		return jvNull(), fmt.Errorf("limit must be between 1 and %d", maxTraces)
	}
	items, err := listTraces(db, limit)
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("enabled", jvBool(settings.get("profilingEnabled").truthy())),
		jvKey("items", items),
	), nil
}

// listTraces mirrors profiling.list_traces.
func listTraces(db dbx, limit int64) (jVal, error) {
	rows, err := db.Query(`
SELECT trace_id, kind, operation, started_at_ms, duration_us, status,
       span_count, truncated
FROM profile_trace ORDER BY started_at_ms DESC, rowid DESC LIMIT ?`, limit)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var traceID, kind, operation, status string
		var startedAtMs, durationUs, spanCount, truncated int64
		if err := rows.Scan(&traceID, &kind, &operation, &startedAtMs, &durationUs,
			&status, &spanCount, &truncated); err != nil {
			return jvNull(), err
		}
		items.arr = append(items.arr, jvObj(
			jvKey("trace_id", jvStr(traceID)),
			jvKey("kind", jvStr(kind)),
			jvKey("operation", jvStr(operation)),
			jvKey("started_at_ms", jvInt(startedAtMs)),
			jvKey("duration_us", jvInt(durationUs)),
			jvKey("status", jvStr(status)),
			jvKey("span_count", jvInt(spanCount)),
			jvKey("truncated", jvInt(truncated)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return items, nil
}

func opGetProfile(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	traceID := pythonStrOrEmpty(payload.get("args").get("trace_id"))
	var kind, operation, status, traceJSON string
	var startedAtMs, durationUs, spanCount, truncated int64
	err = db.QueryRow(`
SELECT trace_id, kind, operation, started_at_ms, duration_us, status,
       span_count, truncated, trace_json
FROM profile_trace WHERE trace_id=?`, traceID).
		Scan(&traceID, &kind, &operation, &startedAtMs, &durationUs, &status,
			&spanCount, &truncated, &traceJSON)
	if err == sql.ErrNoRows {
		return jvNull(), fmt.Errorf("unknown profile trace: %s", traceID)
	}
	if err != nil {
		return jvNull(), err
	}
	parsed, err := parseJSON([]byte(traceJSON))
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("trace_id", jvStr(traceID)),
		jvKey("kind", jvStr(kind)),
		jvKey("operation", jvStr(operation)),
		jvKey("started_at_ms", jvInt(startedAtMs)),
		jvKey("duration_us", jvInt(durationUs)),
		jvKey("status", jvStr(status)),
		jvKey("span_count", jvInt(spanCount)),
		jvKey("truncated", jvInt(truncated)),
		jvKey("trace", parsed),
	), nil
}

func opClearProfiles(pluginDir string, payload jVal) (jVal, error) {
	if pythonStrOrEmpty(payload.get("args").get("confirmation")) != "CLEAR" {
		return jvNull(), fmt.Errorf("clearing profiles requires confirmation")
	}
	settings := pluginSettings(payload)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	res, err := db.Exec(`DELETE FROM profile_trace`)
	if err != nil {
		return jvNull(), err
	}
	deleted, err := res.RowsAffected()
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("deleted", jvInt(deleted)),
	), nil
}
