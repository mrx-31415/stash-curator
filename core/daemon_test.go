// Queue-lifecycle tests for the background worker (docs/decisions/004):
// claim, coalescing, orphan recovery, cancel, and the progress sink, all
// against a temp migrated sidecar. The daemon process itself is exercised
// end-to-end by the Python differential harness (tests/core/
// test_backend_slice3_tasks.py runs the real binary in daemon mode).
package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

// pinTime makes nowMs() return ms for the duration of fn.
func pinTime(t *testing.T, ms int64, fn func()) {
	t.Helper()
	prev := timeNowUnixMilli
	timeNowUnixMilli = func() int64 { return ms }
	defer func() { timeNowUnixMilli = prev }()
	fn()
}

// taskPayload builds a runTaskBody-compatible payload pointing at path.
func taskPayload(path string, mode string) jVal {
	return jvObj(
		jvKey("args", jvObj(
			jvKey("operation", jvStr(mode)),
			jvKey("database_path", jvStr(path)),
		)),
		jvKey("server_connection", jvObj()),
	)
}

// jobRow reads one curator_job row as a map.
func jobRow(t *testing.T, db dbx, jobID string) map[string]any {
	t.Helper()
	rows, err := db.Query(`SELECT * FROM curator_job WHERE job_id=?`, jobID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	if !rows.Next() {
		t.Fatalf("no curator_job row %s", jobID)
	}
	columns, err := rows.Columns()
	if err != nil {
		t.Fatal(err)
	}
	values := make([]any, len(columns))
	scanned := make([]any, len(columns))
	for i := range columns {
		scanned[i] = &values[i]
	}
	if err := rows.Scan(scanned...); err != nil {
		t.Fatal(err)
	}
	row := make(map[string]any, len(columns))
	for i, name := range columns {
		row[name] = values[i]
	}
	return row
}

func jobState(t *testing.T, db dbx, jobID string) string {
	t.Helper()
	return asDBString(jobRow(t, db, jobID)["state"])
}

// insertQueued seeds a queued row directly (as the enqueuer would).
func insertQueued(t *testing.T, db dbx, jobID, mode, payloadJSON string, queuedAtMs int64) {
	t.Helper()
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, queued_at_ms, payload_json)
VALUES (?, ?, 'queued', ?, ?, ?)`, jobID, mode, queuedAtMs, queuedAtMs, payloadJSON); err != nil {
		t.Fatal(err)
	}
}

func TestMigrateAddsWorkerColumns(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	rows, err := db.Query(`SELECT name FROM pragma_table_info('curator_job')`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	seen := map[string]bool{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatal(err)
		}
		seen[name] = true
	}
	for _, want := range []string{"queued_at_ms", "heartbeat_at_ms", "owner_pid", "payload_json", "cancel_requested", "progress"} {
		if !seen[want] {
			t.Fatalf("curator_job missing worker column %s", want)
		}
	}
	// The new states are accepted and old rows survive the rebuild.
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('j1', 'build', 'queued', 1), ('j2', 'build', 'cancelled', 2)`); err != nil {
		t.Fatalf("new states rejected: %v", err)
	}
}

func TestClaimQueuedJob(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	payload := `{"args":{"operation":"sync-plays"},"server_connection":{"host":"h","port":"1"}}`
	pinTime(t, 5_000, func() {
		insertQueued(t, db, "job-a", "sync-plays", payload, 4_000)
		jobID, startedAtMs, got, mode, err := claimQueuedJob(db)
		if err != nil {
			t.Fatal(err)
		}
		if jobID != "job-a" || startedAtMs != 4_000 || mode != "sync-plays" {
			t.Fatalf("unexpected claim: %q %d %q", jobID, startedAtMs, mode)
		}
		row := got.get("args").get("operation").asString()
		if row != "sync-plays" {
			t.Fatalf("payload not round-tripped: %q", row)
		}
		state := jobRow(t, db, "job-a")
		if jobState(t, db, "job-a") != "running" {
			t.Fatalf("state: %v", state["state"])
		}
		if int64(asDBInt(state["owner_pid"])) != int64(os.Getpid()) {
			t.Fatalf("owner_pid not recorded: %v", state["owner_pid"])
		}
		if asDBInt(state["heartbeat_at_ms"]) != 5_000 {
			t.Fatalf("heartbeat not seeded: %v", state["heartbeat_at_ms"])
		}
	})
}

func TestClaimEmptyAndSingleShot(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	jobID, _, _, _, err := claimQueuedJob(db)
	if err != nil {
		t.Fatal(err)
	}
	if jobID != "" {
		t.Fatalf("expected empty claim, got %q", jobID)
	}
	insertQueued(t, db, "job-a", "build", `{}`, 1)
	insertQueued(t, db, "job-b", "build", `{}`, 2)
	first, _, _, _, err := claimQueuedJob(db)
	if err != nil {
		t.Fatal(err)
	}
	if first != "job-a" {
		t.Fatalf("oldest first: got %q", first)
	}
	// The first claim removed the row from the queue; a second claim takes
	// the next one, never the claimed row again.
	second, _, _, _, err := claimQueuedJob(db)
	if err != nil {
		t.Fatal(err)
	}
	if second != "job-b" {
		t.Fatalf("second claim: got %q", second)
	}
	if jobState(t, db, "job-a") != "running" || jobState(t, db, "job-b") != "running" {
		t.Fatal("claimed rows must be running")
	}
}

func TestEnqueueCoalescesSameType(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	pinTime(t, 10_000, func() {
		insertQueued(t, db, "existing", "update-model", `{}`, 9_000)
		out, err := runTaskBody(pluginDir, taskPayload(path, "update-model"), "update-model", jvObj())
		if err != nil {
			t.Fatal(err)
		}
		if !out.get("already_running").truthy() {
			t.Fatalf("expected already_running, got %v", out)
		}
		if out.get("job_id").asString() != "existing" {
			t.Fatalf("wrong coalesced job: %v", out.get("job_id").asString())
		}
		var queued int
		if err := db.QueryRow(`SELECT count(*) FROM curator_job WHERE state='queued'`).Scan(&queued); err != nil {
			t.Fatal(err)
		}
		if queued != 1 {
			t.Fatalf("coalescing added a queued row: %d", queued)
		}
	})
}

func TestEnqueueQueuesAndWorkerClaims(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	prevSpawn := spawnWorkerFn
	spawnWorkerFn = func(string) error { return nil }
	defer func() { spawnWorkerFn = prevSpawn }()
	pinTime(t, 20_000, func() {
		out, err := runTaskBody(pluginDir, taskPayload(path, "sync-plays"), "sync-plays", jvObj())
		if err != nil {
			t.Fatal(err)
		}
		if !out.get("queued").truthy() {
			t.Fatalf("expected queued response, got %v", out)
		}
		jobID := out.get("job_id").asString()
		if jobID == "" || jobState(t, db, jobID) != "queued" {
			t.Fatalf("row not queued: %s %s", jobID, jobState(t, db, jobID))
		}
		claimed, _, _, mode, err := claimQueuedJob(db)
		if err != nil {
			t.Fatal(err)
		}
		if claimed != jobID || mode != "sync-plays" {
			t.Fatalf("claim mismatch: %q %q", claimed, mode)
		}
	})
}

func TestEnsureWorkerRotatesStaleBinary(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	insertQueued(t, db, "queued", "sync-plays", `{}`, 1)
	if err := os.MkdirAll(filepath.Join(pluginDir, "data"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(workerPidPath(pluginDir), []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := writeWorkerState(pluginDir, workerState{BinaryFingerprint: "old-generation"}); err != nil {
		t.Fatal(err)
	}
	previousAlive := workerPidAliveFn
	previousOwner := workerPidIsWorkerFn
	previousStop := stopWorkerFn
	previousSpawn := spawnWorkerFn
	alive := true
	stopCalls := 0
	spawnCalls := 0
	workerPidAliveFn = func(int) bool { return alive }
	workerPidIsWorkerFn = func(int, string) bool { return true }
	stopWorkerFn = func(int) error {
		stopCalls++
		alive = false
		return nil
	}
	spawnWorkerFn = func(string) error {
		spawnCalls++
		return nil
	}
	defer func() {
		workerPidAliveFn = previousAlive
		workerPidIsWorkerFn = previousOwner
		stopWorkerFn = previousStop
		spawnWorkerFn = previousSpawn
	}()

	if err := ensureWorker(pluginDir, taskPayload(path, "sync-plays"), jvObj()); err != nil {
		t.Fatal(err)
	}
	if stopCalls != 1 || spawnCalls != 1 {
		t.Fatalf("rotation calls: stop=%d spawn=%d", stopCalls, spawnCalls)
	}
	state, err := readWorkerState(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	current, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	if state.BinaryFingerprint != current {
		t.Fatalf("state fingerprint = %q, want %q", state.BinaryFingerprint, current)
	}
}

func TestEnsureWorkerIgnoresReusedPID(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	insertQueued(t, db, "queued", "sync-plays", `{}`, 1)
	fingerprint, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	if err := writeWorkerState(pluginDir, workerState{BinaryFingerprint: fingerprint}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(workerPidPath(pluginDir), []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		t.Fatal(err)
	}
	previousAlive := workerPidAliveFn
	previousOwner := workerPidIsWorkerFn
	previousStop := stopWorkerFn
	previousSpawn := spawnWorkerFn
	stopCalls := 0
	spawnCalls := 0
	workerPidAliveFn = func(int) bool { return true }
	workerPidIsWorkerFn = func(int, string) bool { return false }
	stopWorkerFn = func(int) error {
		stopCalls++
		return nil
	}
	spawnWorkerFn = func(string) error {
		spawnCalls++
		return nil
	}
	defer func() {
		workerPidAliveFn = previousAlive
		workerPidIsWorkerFn = previousOwner
		stopWorkerFn = previousStop
		spawnWorkerFn = previousSpawn
	}()

	if err := ensureWorker(pluginDir, taskPayload(path, "sync-plays"), jvObj()); err != nil {
		t.Fatal(err)
	}
	if stopCalls != 0 || spawnCalls != 1 {
		t.Fatalf("reused PID handling: stop=%d spawn=%d", stopCalls, spawnCalls)
	}
}
func TestHandoverWorkerSpawnsSuccessor(t *testing.T) {
	pluginDir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(pluginDir, "data"), 0o755); err != nil {
		t.Fatal(err)
	}
	name := "curator-core-" + runtime.GOOS + "-" + runtime.GOARCH
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	binary := filepath.Join(pluginDir, name)
	if err := os.WriteFile(binary, []byte("new-generation"), 0o755); err != nil {
		t.Fatal(err)
	}
	oldFingerprint, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	// The resident worker: its own pid in the pid file and a state row for
	// the previous generation.
	if err := os.WriteFile(workerPidPath(pluginDir), []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := writeWorkerState(pluginDir, workerState{BinaryFingerprint: "old-generation"}); err != nil {
		t.Fatal(err)
	}
	spawned := 0
	previousSpawn := spawnWorkerFn
	spawnWorkerFn = func(string) error { spawned++; return nil }
	defer func() { spawnWorkerFn = previousSpawn }()

	handoverWorker(pluginDir)

	if spawned != 1 {
		t.Fatalf("successor spawns = %d, want 1", spawned)
	}
	if _, err := os.Stat(workerPidPath(pluginDir)); !os.IsNotExist(err) {
		t.Fatalf("pid file not removed: %v", err)
	}
	state, err := readWorkerState(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	if state.BinaryFingerprint != oldFingerprint {
		t.Fatalf("state fingerprint = %q, want %q (the installed binary)", state.BinaryFingerprint, oldFingerprint)
	}
}

func TestWorkerUpdateWatcherDetectsReplacement(t *testing.T) {
	pluginDir := t.TempDir()
	name := "curator-core-" + runtime.GOOS + "-" + runtime.GOARCH
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	binary := filepath.Join(pluginDir, name)
	if err := os.WriteFile(binary, []byte("old"), 0o755); err != nil {
		t.Fatal(err)
	}
	initial, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		t.Fatal(err)
	}
	previousCheck := workerCheckMs
	workerCheckMs = 1
	defer func() { workerCheckMs = previousCheck }()
	changed := make(chan struct{}, 1)
	done := make(chan struct{})
	go workerUpdateWatcher(pluginDir, initial, changed, done)
	defer close(done)
	if err := os.WriteFile(binary, []byte("new-generation"), 0o755); err != nil {
		t.Fatal(err)
	}
	select {
	case <-changed:
	case <-time.After(time.Second):
		t.Fatal("worker update watcher did not detect replacement")
	}
}

func TestTaskPermissionFailureDoesNotOpenSidecar(t *testing.T) {
	pluginDir := t.TempDir()
	database := filepath.Join(t.TempDir(), "curator.sqlite3")
	previous := checkWorkerStateWritableFn
	checkWorkerStateWritableFn = func(string) error { return errors.New("permission denied") }
	defer func() { checkWorkerStateWritableFn = previous }()

	if _, err := runTaskBody(pluginDir, taskPayload(database, "build"), "build", jvObj()); err == nil {
		t.Fatal("permission failure must reject the task")
	}
	if _, err := os.Stat(database); !os.IsNotExist(err) {
		t.Fatalf("permission failure opened sidecar: %v", err)
	}
}

func TestBackupValidationFailureRemovesSnapshot(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(t.TempDir(), "curator.sqlite3.backup")
	previous := validateBackupFn
	validateBackupFn = func(string) error { return errors.New("invalid backup") }
	defer func() { validateBackupFn = previous }()

	if _, err := backupDatabaseValidated(db, destination, false, nil); err == nil {
		t.Fatal("invalid backup must fail validation")
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Fatalf("invalid backup remains published: %v", err)
	}
}

func TestEnqueueFailsClosedWhenWorkerUnavailable(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	previousSpawn := spawnWorkerFn
	spawnWorkerFn = func(string) error { return errors.New("no worker in tests") }
	defer func() { spawnWorkerFn = previousSpawn }()

	_, err := runTaskBody(pluginDir, taskPayload(path, "compact"), "compact", jvObj())
	if err == nil {
		t.Fatal("worker failure must not fall back to inline execution")
	}
	var state string
	var taskError string
	if err := db.QueryRow(`SELECT state, error FROM curator_job`).Scan(&state, &taskError); err != nil {
		t.Fatal(err)
	}
	if state != "failed" {
		t.Fatalf("failed worker left job in %q", state)
	}
	if !strings.Contains(taskError, "worker unavailable") {
		t.Fatalf("unexpected task error: %q", taskError)
	}
}

func TestIsSchemaSkewError(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"nil is not skew", nil, false},
		{"unknown migration versions", errors.New("database contains unknown migration versions: [33]"), true},
		{"unknown multiple migrations", errors.New("database contains unknown migration versions: [33 34]"), true},
		{"checksum mismatch", errors.New("migration 33 does not match the packaged checksum"), true},
		{"unrelated open error", errors.New("database disk image is malformed"), false},
		{"busy error", errors.New("database is locked"), false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := isSchemaSkewError(c.err); got != c.want {
				t.Fatalf("isSchemaSkewError(%q) = %v, want %v", c.err, got, c.want)
			}
		})
	}
}

func TestRunWorkerJobRetiresOnSchemaSkew(t *testing.T) {
	pluginDir := t.TempDir()
	path := filepath.Join(t.TempDir(), "curator.sqlite3")
	payload := taskPayload(path, "update-model")
	previous := openTaskSidecarFn
	openTaskSidecarFn = func(string, jVal, jVal, string) (dbx, error) {
		return nil, errors.New("database contains unknown migration versions: [33]")
	}
	defer func() { openTaskSidecarFn = previous }()

	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	insertQueued(t, db, "job-1", "update-model", "{}", 1_700_000_000_000)
	// The job must be marked running so the failure transition applies.
	if _, err := db.Exec(`UPDATE curator_job SET state='running', owner_pid=?, heartbeat_at_ms=? WHERE job_id='job-1'`, os.Getpid(), nowMs()); err != nil {
		t.Fatal(err)
	}

	retire := runWorkerJob(pluginDir, db, "job-1", 1_700_000_000_000, payload, "update-model")
	if !retire {
		t.Fatal("schema-skew sidecar open must signal daemon retirement")
	}
	if got := jobState(t, db, "job-1"); got != "failed" {
		t.Fatalf("job left in %q, want failed", got)
	}
	row := jobRow(t, db, "job-1")
	if !strings.Contains(asDBString(row["error"]), "unknown migration versions") {
		t.Fatalf("job error not recorded: %q", asDBString(row["error"]))
	}
}

func TestRunWorkerJobDoesNotRetireOnTransientOpenFailure(t *testing.T) {
	pluginDir := t.TempDir()
	path := filepath.Join(t.TempDir(), "curator.sqlite3")
	payload := taskPayload(path, "update-model")
	previous := openTaskSidecarFn
	openTaskSidecarFn = func(string, jVal, jVal, string) (dbx, error) {
		return nil, errors.New("database is locked")
	}
	defer func() { openTaskSidecarFn = previous }()

	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	insertQueued(t, db, "job-1", "update-model", "{}", 1_700_000_000_000)
	if _, err := db.Exec(`UPDATE curator_job SET state='running', owner_pid=?, heartbeat_at_ms=? WHERE job_id='job-1'`, os.Getpid(), nowMs()); err != nil {
		t.Fatal(err)
	}

	if retire := runWorkerJob(pluginDir, db, "job-1", 1_700_000_000_000, payload, "update-model"); retire {
		t.Fatal("transient open failure must not retire the daemon")
	}
}

func TestRecoverOrphanJobs(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// Heartbeat-stale running row → interrupted.
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, heartbeat_at_ms)
VALUES ('stale-heartbeat', 'build', 'running', 1, ?)`, now-heartbeatStaleMs-1); err != nil {
			t.Fatal(err)
		}
		// Legacy pre-heartbeat running row past 6h → interrupted.
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('legacy-old', 'build', 'running', ?)`, now-legacyStaleMs-1); err != nil {
			t.Fatal(err)
		}
		// Fresh heartbeat running row → untouched.
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, heartbeat_at_ms)
VALUES ('healthy', 'build', 'running', 1, ?)`, now-10_000); err != nil {
			t.Fatal(err)
		}
		recoverOrphanJobs(db, now)
		if jobState(t, db, "stale-heartbeat") != "failed" {
			t.Fatal("stale-heartbeat row not recovered")
		}
		if jobState(t, db, "legacy-old") != "failed" {
			t.Fatal("legacy-old row not recovered")
		}
		if jobState(t, db, "healthy") != "running" {
			t.Fatal("healthy row must survive recovery")
		}
	})
}

func TestCancelQueuedAndRunning(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	pluginDir := t.TempDir()
	pinTime(t, 40_000, func() {
		insertQueued(t, db, "queued-job", "build", `{}`, 1)
		payload := taskPayload(path, "cancel_job")
		payload.set("args", jvObj(
			jvKey("operation", jvStr("cancel_job")),
			jvKey("job_id", jvStr("queued-job")),
			jvKey("database_path", jvStr(path)),
		))
		out, err := opCancelJob(pluginDir, payload)
		if err != nil {
			t.Fatal(err)
		}
		if !out.get("cancelled").truthy() || out.get("state").asString() != "cancelled" {
			t.Fatalf("queued cancel response: %v", out)
		}
		if jobState(t, db, "queued-job") != "cancelled" {
			t.Fatal("queued job not cancelled")
		}
		// Running job: cooperative flag, row stays running.
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, owner_pid)
VALUES ('running-job', 'build', 'running', 1, ?)`, os.Getpid()); err != nil {
			t.Fatal(err)
		}
		payload.set("args", jvObj(
			jvKey("operation", jvStr("cancel_job")),
			jvKey("job_id", jvStr("running-job")),
			jvKey("database_path", jvStr(path)),
		))
		out, err = opCancelJob(pluginDir, payload)
		if err != nil {
			t.Fatal(err)
		}
		if !out.get("cancelled").truthy() || !out.get("cancel_requested").truthy() {
			t.Fatalf("running cancel response: %v", out)
		}
		row := jobRow(t, db, "running-job")
		if jobState(t, db, "running-job") != "running" || asDBInt(row["cancel_requested"]) != 1 {
			t.Fatal("running job not flagged for cancel")
		}
		// Unknown job: cancelled false.
		payload.set("args", jvObj(
			jvKey("operation", jvStr("cancel_job")),
			jvKey("job_id", jvStr("ghost")),
			jvKey("database_path", jvStr(path)),
		))
		out, err = opCancelJob(pluginDir, payload)
		if err != nil {
			t.Fatal(err)
		}
		if out.get("cancelled").truthy() {
			t.Fatalf("ghost job reported cancelled: %v", out)
		}
	})
}

func TestProgressSinkDebounceAndFlush(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('job-p', 'build', 'running', 1)`); err != nil {
		t.Fatal(err)
	}
	progressDebounceMs = 500
	var progress float64
	pinTime(t, 100_000, func() {
		sink, err := newProgressSink(path, "job-p")
		if err != nil {
			t.Fatal(err)
		}
		sink.report(0.5)
		if err := db.QueryRow(`SELECT progress FROM curator_job WHERE job_id='job-p'`).Scan(&progress); err != nil {
			t.Fatal(err)
		}
		if progress != 0.5 {
			t.Fatalf("first write missing: %v", progress)
		}
		// Same-millisecond write is debounced away...
		sink.report(0.6)
		// ...and the close flush lands the latest value.
		sink.close()
		if err := db.QueryRow(`SELECT progress FROM curator_job WHERE job_id='job-p'`).Scan(&progress); err != nil {
			t.Fatal(err)
		}
		if progress != 0.6 {
			t.Fatalf("close did not flush: %v", progress)
		}
	})
}

// TestProgressSinkDoesNotBlockTheModeConnection pins the structural fix for
// the single-connection pool: the sink writes on its own connection, so a
// progress marker fired while the mode holds the only pooled execution
// connection must not deadlock waiting for it.
func TestProgressSinkDoesNotBlockTheModeConnection(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('job-p', 'build', 'running', 1)`); err != nil {
		t.Fatal(err)
	}
	sink, err := newProgressSink(path, "job-p")
	if err != nil {
		t.Fatal(err)
	}
	defer sink.close()
	// Hold the mode's only pooled execution connection (idle — no write lock),
	// mimicking a long stage that keeps the connection checked out.
	held := make(chan struct{})
	release := make(chan struct{})
	go func() {
		conn, err := db.Conn(context.Background())
		if err != nil {
			t.Error(err)
			return
		}
		close(held)
		<-release
		conn.Close()
	}()
	<-held
	// The sink must still persist progress on its own connection: the write
	// must not wait on the held pooled connection (which the pre-fix code
	// would deadlock on).
	done := make(chan struct{})
	go func() {
		sink.report(0.42)
		sink.flush()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("progress report blocked on the mode's held connection")
	}
	close(release)
	var progress float64
	if err := db.QueryRow(`SELECT progress FROM curator_job WHERE job_id='job-p'`).Scan(&progress); err != nil {
		t.Fatal(err)
	}
	if progress != 0.42 {
		t.Fatalf("progress not persisted: %v", progress)
	}
}

func TestHeartbeatLoopCancelsRequested(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	heartbeatIntervalMs = 5
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, cancel_requested)
VALUES ('job-c', 'build', 'running', 1, 1)`); err != nil {
		t.Fatal(err)
	}
	prevCancelExit := daemonExitOnCancel
	daemonExitOnCancel = false // tests never exit the process
	defer func() { daemonExitOnCancel = prevCancelExit }()
	done := make(chan struct{})
	go heartbeatLoop(db, "job-c", done)
	// Poll for the transition; the tick interval is 5ms.
	var state string
	for range 100 {
		state = jobState(t, db, "job-c")
		if state == "cancelled" {
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	close(done)
	if state != "cancelled" {
		t.Fatalf("cancel flag not honored: %s", state)
	}
	row := jobRow(t, db, "job-c")
	if asDBString(row["error"]) != "cancelled" {
		t.Fatalf("error field: %v", row["error"])
	}
}
