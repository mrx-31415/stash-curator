package main

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestWorkerDoesNotInheritEnqueueCapture(t *testing.T) {
	t.Setenv("CURATOR_CORE_CPU_PROFILE_DIR", "enqueue-cpu")
	t.Setenv("CURATOR_CORE_MEM_PROFILE_DIR", "enqueue-mem")
	t.Setenv("GOMEMLIMIT", "2GiB")
	env := strings.Join(workerEnvironment(), "\n")
	if strings.Contains(env, "CURATOR_CORE_CPU_PROFILE_DIR=") || strings.Contains(env, "CURATOR_CORE_MEM_PROFILE_DIR=") || !strings.Contains(env, "GOMEMLIMIT=2GiB") {
		t.Fatal("worker inherited capture paths or lost its memory limit")
	}
}

func TestRecoveryDoesNotInterruptHealthyBuild(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1700000000000); err != nil {
		t.Fatal(err)
	}
	now := nowMs()
	if _, err := db.Exec(`INSERT INTO curator_job(job_id,job_type,state,started_at_ms,heartbeat_at_ms)
VALUES ('healthy','update-model','running',?,?)`, now-1000, now); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`UPDATE model_update_state SET last_started_at_ms=?,last_finished_at_ms=?,last_error=NULL`, now-1000, now-2000); err != nil {
		t.Fatal(err)
	}
	recoverOrphanJobs(db, now)
	var lastError sql.NullString
	if err := db.QueryRow(`SELECT last_error FROM model_update_state`).Scan(&lastError); err != nil || lastError.Valid {
		t.Fatalf("healthy build marked interrupted: %v, %v", lastError, err)
	}
	if _, err := db.Exec(`UPDATE curator_job SET heartbeat_at_ms=? WHERE job_id='healthy'`, now-heartbeatStaleMs-1); err != nil {
		t.Fatal(err)
	}
	recoverOrphanJobs(db, now)
	if err := db.QueryRow(`SELECT last_error FROM model_update_state`).Scan(&lastError); err != nil || !lastError.Valid || jobState(t, db, "healthy") != "failed" {
		t.Fatalf("dead build not recovered: %v, %v", lastError, err)
	}
}

func TestWorkerProfilesExecution(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1700000000000); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"configuration":{"plugins":{"stash-curator":{"profilingEnabled":true}}}}}`))
	}))
	defer server.Close()
	u, _ := url.Parse(server.URL)
	payload := taskPayload(path, "prepare")
	payload.set("server_connection", jvObj(jvKey("Host", jvStr(u.Hostname())), jvKey("Port", jvStr(u.Port()))))
	insertQueued(t, db, "profile-job", "prepare", payload.marshalCompact(), nowMs())
	jobID, startedAtMs, _, mode, err := claimQueuedJob(db, false)
	if err != nil {
		t.Fatal(err)
	}
	if runWorkerJob(t.TempDir(), db, jobID, startedAtMs, payload, mode) {
		t.Fatal("ordinary task failure retired worker")
	}
	// Prepare fails without a model; the execution and its error still need a trace.
	var status, raw string
	if err := db.QueryRow(`SELECT status,trace_json FROM profile_trace WHERE operation='worker-prepare'`).Scan(&status, &raw); err != nil {
		t.Fatal(err)
	}
	if status != "error" || jobState(t, db, jobID) != "failed" {
		t.Fatalf("execution failure missing from profile/job: %s", status)
	}
	trace, err := parseJSON([]byte(raw))
	if err != nil || len(trace.get("traceEvents").arr) < 2 {
		t.Fatalf("worker trace missing execution spans: %s", raw)
	}
}
