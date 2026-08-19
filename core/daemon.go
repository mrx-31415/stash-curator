// Background task worker (docs/decisions/004): a detached, Curator-owned
// process that claims and executes queued curator_job rows, so long-running
// tasks stop occupying Stash's single-slot job queue. The daemon is this
// binary in a new mode — `curator-core <pluginDir> daemon` — spawned by the
// enqueuer (ensureWorker) with a new session and log-file stdio so it
// survives the invoking Stash job. Interactive ops keep the one-process-
// per-request raw-plugin protocol unchanged; only the task path changes.
//
// Liveness is ownership-based: running rows carry owner_pid + heartbeat_at_ms
// written by the executing process, replacing the old 120s/6h heuristics that
// inferred liveness from Stash's job list (which no longer shows the work).
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Worker process tuning. The two hot-loop values are vars so Go tests can
// shorten them; the staleness windows stay constants (tests pin time via
// timeNowUnixMilli).
const (
	heartbeatStaleMs = 5 * 60_000    // running rows older than this are orphans
	legacyStaleMs    = 6 * 3_600_000 // pre-heartbeat rows keep the old window
	idleExitMs       = 5 * 60_000    // exit after this long with no queued work
	claimPollMs      = 1_000
)

var (
	heartbeatIntervalMs = 20_000 // liveness write while a job runs
	progressDebounceMs  = 500    // cap progress writes during a build
	workerCheckMs       = 5_000  // detect replacement of the installed binary
	workerStopWaitMs    = 2_000  // grace period before forcing stale workers down
)

// workerState is written by the enqueuer (which has the Stash payload) and
// re-read by the daemon (which has none): where the sidecar lives and how to
// reach Stash for the per-job settings fetch. BinaryFingerprint identifies
// the exact installed executable generation so an old resident daemon cannot
// survive a plugin update.
type workerState struct {
	DatabasePath      string            `json:"database_path"`
	StashBase         string            `json:"stash_base"`
	StashHeaders      map[string]string `json:"stash_headers"`
	ServerConnection  string            `json:"server_connection,omitempty"`
	BinaryFingerprint string            `json:"binary_fingerprint,omitempty"`
}

func workerStatePath(pluginDir string) string {
	return filepath.Join(pluginDir, "data", "curator-worker.json")
}

func workerPidPath(pluginDir string) string {
	return filepath.Join(pluginDir, "data", "curator-daemon.pid")
}

func workerLogPath(pluginDir string) string {
	return filepath.Join(pluginDir, "data", "curator-daemon.log")
}

func workerStateDataDir(pluginDir string) string {
	return filepath.Join(pluginDir, "data")
}

// checkWorkerStateWritable fails before a task mutates the sidecar when the
// caller cannot coordinate with the daemon. This is especially important for
// direct invocations under a different UID from the Stash container.
func checkWorkerStateWritable(pluginDir string) error {
	directory := workerStateDataDir(pluginDir)
	if err := os.MkdirAll(directory, 0o755); err != nil {
		return fmt.Errorf("could not create worker state directory: %w", err)
	}
	temporary, err := os.CreateTemp(directory, ".curator-worker-probe-*")
	if err != nil {
		return fmt.Errorf("worker state directory is not writable: %w", err)
	}
	name := temporary.Name()
	if err := temporary.Close(); err != nil {
		_ = os.Remove(name)
		return fmt.Errorf("could not close worker state probe: %w", err)
	}
	if err := os.Remove(name); err != nil {
		return fmt.Errorf("could not remove worker state probe: %w", err)
	}
	return nil
}

var checkWorkerStateWritableFn = checkWorkerStateWritable

func writeWorkerState(pluginDir string, state workerState) error {
	directory := workerStateDataDir(pluginDir)
	if err := os.MkdirAll(directory, 0o755); err != nil {
		return err
	}
	raw, err := json.Marshal(state)
	if err != nil {
		return err
	}
	temporary, err := os.CreateTemp(directory, ".curator-worker-*.tmp")
	if err != nil {
		return err
	}
	temporaryName := temporary.Name()
	cleanup := func() {
		_ = temporary.Close()
		_ = os.Remove(temporaryName)
	}
	if err := temporary.Chmod(0o644); err != nil {
		cleanup()
		return err
	}
	if _, err := temporary.Write(raw); err != nil {
		cleanup()
		return err
	}
	if err := temporary.Sync(); err != nil {
		cleanup()
		return err
	}
	if err := temporary.Close(); err != nil {
		_ = os.Remove(temporaryName)
		return err
	}
	if err := os.Rename(temporaryName, workerStatePath(pluginDir)); err != nil {
		_ = os.Remove(temporaryName)
		return err
	}
	return nil
}

func readWorkerState(pluginDir string) (workerState, error) {
	var state workerState
	raw, err := os.ReadFile(workerStatePath(pluginDir))
	if err != nil {
		return state, err
	}
	err = json.Unmarshal(raw, &state)
	return state, err
}

func readWorkerPid(pluginDir string) (int, bool) {
	raw, err := os.ReadFile(workerPidPath(pluginDir))
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil || pid <= 0 {
		return 0, false
	}
	return pid, true
}

// workerBinaryPath returns the installed platform binary. Development builds
// use the running executable when the packaged per-arch name is absent.
func workerBinaryPath(pluginDir string) string {
	name := fmt.Sprintf("curator-core-%s-%s", runtime.GOOS, runtime.GOARCH)
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	candidate := filepath.Join(pluginDir, name)
	if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() {
		return candidate
	}
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	return exe
}

// workerBinaryFingerprint changes when a plugin update replaces the running
// executable. File identity catches atomic replacement; size and mtime catch
// in-place replacement on platforms without a portable file identity.
func workerBinaryFingerprint(pluginDir string) (string, error) {
	path := workerBinaryPath(pluginDir)
	if path == "" {
		return "", fmt.Errorf("could not resolve curator-core executable")
	}
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s|%s|%d|%d|%o", filepath.Clean(path), workerFileIdentity(info),
		info.Size(), info.ModTime().UnixNano(), info.Mode().Perm()), nil
}

// workerPidAliveFn and workerPidIsWorkerFn are injectable for rotation tests.
var workerPidAliveFn = pidAlive

var workerPidIsWorkerFn = workerPidIsWorker

// stopWorkerFn is injectable so rotation tests never signal a real process.
var stopWorkerFn = stopWorker

func removeWorkerPidIfOwned(pluginDir string) {
	if pid, ok := readWorkerPid(pluginDir); ok && pid == os.Getpid() {
		_ = os.Remove(workerPidPath(pluginDir))
	}
}

func stopWorker(pid int) error {
	if !pidAlive(pid) {
		return nil
	}
	if err := terminateWorker(pid); err != nil && pidAlive(pid) {
		return err
	}
	deadline := time.Now().Add(time.Duration(workerStopWaitMs) * time.Millisecond)
	for pidAlive(pid) && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if !pidAlive(pid) {
		return nil
	}
	return forceKillWorker(pid)
}

// rotateStaleWorker stops a live daemon whose generation predates the
// installed executable. A live PID that is not actually a Curator daemon is
// treated as stale metadata and is never signalled.
func rotateStaleWorker(pluginDir, fingerprint string) error {
	pid, ok := readWorkerPid(pluginDir)
	if !ok || !workerPidAliveFn(pid) {
		return nil
	}
	if !workerPidIsWorkerFn(pid, pluginDir) {
		_ = os.Remove(workerPidPath(pluginDir))
		return nil
	}
	state, err := readWorkerState(pluginDir)
	if err == nil && state.BinaryFingerprint == fingerprint {
		return nil
	}
	if err := stopWorkerFn(pid); err != nil {
		return fmt.Errorf("could not stop stale Curator daemon %d: %w", pid, err)
	}
	return nil
}

func workerUpdateWatcher(pluginDir, initialFingerprint string, changed chan<- struct{}, done <-chan struct{}) {
	ticker := time.NewTicker(time.Duration(workerCheckMs) * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			current, err := workerBinaryFingerprint(pluginDir)
			if err != nil || current == initialFingerprint {
				continue
			}
			infoLog("installed curator-core changed; daemon retiring")
			select {
			case changed <- struct{}{}:
			case <-done:
			}
			return
		}
	}
}

// spawnWorkerFn is injectable so Go tests can force the inline fallback
// instead of exec'ing the test binary as a daemon.
var spawnWorkerFn = spawnWorker

// spawnWorker starts the daemon detached from Stash's process tree: a new
// session (setsid), stdin from /dev/null, stdout/stderr appended to the
// worker log. The parent exits right after, so the child is reparented to
// init instead of being killed with the Stash job. Deliberately no Wait:
// the enqueuer exits immediately and init reaps the child.
func spawnWorker(pluginDir string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	logFile, err := os.OpenFile(workerLogPath(pluginDir), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	devnull, err := os.Open(os.DevNull)
	if err != nil {
		logFile.Close()
		return err
	}
	cmd := exec.Command(exe, pluginDir, "daemon")
	cmd.SysProcAttr = daemonSysProcAttr()
	cmd.Stdin = devnull
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	if err := cmd.Start(); err != nil {
		devnull.Close()
		logFile.Close()
		return err
	}
	devnull.Close()
	logFile.Close()
	return nil
}

// ensureAutoWorker spawns the daemon when schedules or auto tasks are
// enabled and none is running. Unlike ensureWorker (task-driven, only spawns
// when a job is queued), this must spawn even with an empty queue — the
// scheduler inside the daemon seeds and runs the schedules itself. Called
// from every API-sidecar open, so any Curator activity (including the
// Settings panel's own reload after a toggle) spawns or keeps the worker.
func ensureAutoWorker(pluginDir string, payload jVal, settings jVal, db dbx) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return
	}
	config := cfg.get("config")
	if !config.get("auto_tasks_enabled").truthy() && !anyScheduleEnabled(config) {
		return
	}
	fingerprint, err := workerBinaryFingerprint(pluginDir)
	if err != nil || rotateStaleWorker(pluginDir, fingerprint) != nil {
		return
	}
	base, headers := stashConnection(payload)
	serverConn, _ := marshalJVal(payload.get("server_connection"))
	state := workerState{
		DatabasePath:      databasePath(pluginDir, payload, settings),
		StashBase:         base,
		StashHeaders:      headers,
		ServerConnection:  serverConn,
		BinaryFingerprint: fingerprint,
	}
	if pid, ok := readWorkerPid(pluginDir); ok && workerPidAliveFn(pid) && workerPidIsWorkerFn(pid, pluginDir) {
		if err := writeWorkerState(pluginDir, state); err != nil {
			return
		}
		return
	}
	recoverOrphanJobs(db, nowMs())
	if err := writeWorkerState(pluginDir, state); err != nil {
		return
	}
	_ = spawnWorkerFn(pluginDir)
}

// recoverOrphanJobs fails running rows whose executing process is gone:
// heartbeat stale (a daemon or inline runner died) or, for pre-heartbeat
// rows, older than the legacy 6h stale window. It also records the same
// interrupted state on the model-update tracker a build leaves behind.
// Idempotent, safe on every call path (enqueue, health, daemon startup).
func recoverOrphanJobs(db dbx, now int64) {
	execImmediate(db, `UPDATE curator_job SET state='failed', finished_at_ms=?, error='interrupted'
WHERE state='running' AND heartbeat_at_ms IS NOT NULL AND heartbeat_at_ms<=?`,
		now, now-heartbeatStaleMs)
	execImmediate(db, `UPDATE curator_job SET state='failed', finished_at_ms=?, error='interrupted'
WHERE state='running' AND heartbeat_at_ms IS NULL AND started_at_ms<=?`,
		now, now-legacyStaleMs)
	execImmediate(db, `UPDATE model_update_state SET last_error='interrupted before task completion'
WHERE last_started_at_ms IS NOT NULL
AND last_started_at_ms>COALESCE(last_finished_at_ms, -1)
AND last_error IS NULL`)
}

// ensureWorker guarantees a daemon exists whenever there is queued work. The
// enqueuer calls it after inserting a queued row; health calls it so a
// crashed daemon's orphans are recovered and its queue restarts. A live pid
// is reused only when its recorded binary fingerprint matches the installed
// executable; otherwise it is terminated before the new worker is spawned.
// The sidecar is opened (and migrated) before the state file is written, so a
// freshly spawned daemon never sees an un-migrated database path.
func ensureWorker(pluginDir string, payload jVal, settings jVal) error {
	base, headers := stashConnection(payload)
	serverConn, _ := marshalJVal(payload.get("server_connection"))
	fingerprint, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		return fmt.Errorf("could not identify curator-core executable: %w", err)
	}
	if err := rotateStaleWorker(pluginDir, fingerprint); err != nil {
		return err
	}
	state := workerState{
		DatabasePath:      databasePath(pluginDir, payload, settings),
		StashBase:         base,
		StashHeaders:      headers,
		ServerConnection:  serverConn,
		BinaryFingerprint: fingerprint,
	}
	if pid, ok := readWorkerPid(pluginDir); ok && workerPidAliveFn(pid) && workerPidIsWorkerFn(pid, pluginDir) {
		if err := writeWorkerState(pluginDir, state); err != nil {
			return fmt.Errorf("could not write worker state: %w", err)
		}
		return nil
	}
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return fmt.Errorf("could not open sidecar to recover worker: %w", err)
	}
	recoverOrphanJobs(db, nowMs())
	var queued int
	scanErr := db.QueryRow(`SELECT 1 FROM curator_job WHERE state='queued' LIMIT 1`).Scan(&queued)
	db.Close()
	if scanErr != nil && scanErr != sql.ErrNoRows {
		return scanErr
	}
	if scanErr == sql.ErrNoRows {
		return nil // nothing to run; the caller handles its own row inline
	}
	if err := writeWorkerState(pluginDir, state); err != nil {
		return fmt.Errorf("could not write worker state: %w", err)
	}
	return spawnWorkerFn(pluginDir)
}

// runDaemon is the worker main loop, served by `curator-core <pluginDir>
// daemon`. It claims queued jobs one at a time, executes them with the same
// mode bodies the inline path uses, heartbeats and reports progress through
// the sidecar, recovers orphans at startup, and exits after an idle period
// so an idle plugin runs no resident process.
func runDaemon(pluginDir string) {
	state, err := readWorkerState(pluginDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "curator-core daemon: no worker state (%v); the daemon is only spawned from a Curator invocation\n", err)
		os.Exit(1)
	}
	daemonFingerprint, err := workerBinaryFingerprint(pluginDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "curator-core daemon: could not identify executable: %v\n", err)
		os.Exit(1)
	}
	if state.BinaryFingerprint != "" && state.BinaryFingerprint != daemonFingerprint {
		infoLog("daemon generation is stale; exiting")
		return
	}
	if pid, ok := readWorkerPid(pluginDir); ok && pid != os.Getpid() && workerPidAliveFn(pid) && workerPidIsWorkerFn(pid, pluginDir) {
		// A concurrent spawn won the race; it owns the worker.
		os.Exit(0)
	}
	if err := os.WriteFile(workerPidPath(pluginDir), []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "curator-core daemon: could not write pid file: %v\n", err)
		os.Exit(1)
	}
	defer removeWorkerPidIfOwned(pluginDir)

	daemonExitOnCancel = true
	loop, loopPath := openDaemonLoop(pluginDir, state)
	if loop == nil {
		os.Exit(1)
	}
	defer loop.Close()

	// Graceful shutdown: mark the in-flight job cancelled and exit.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	defer signal.Stop(sigCh)
	go func() {
		<-sigCh
		markRunningCancelled(loop)
		removeWorkerPidIfOwned(pluginDir)
		os.Exit(0)
	}()

	updateDone := make(chan struct{})
	updateDetected := make(chan struct{}, 1)
	go workerUpdateWatcher(pluginDir, daemonFingerprint, updateDetected, updateDone)
	defer close(updateDone)

	recoverOrphanJobs(loop, nowMs())
	autoPayload := autoPayloadFromState(state)
	lastTick := nowMs()
	idleSince := nowMs()
	for {
		select {
		case <-updateDetected:
			// Let an active job finish, but do not claim more work under the
			// old executable. The next invocation starts the new generation.
			infoLog("daemon stopped after plugin update")
			return
		default:
		}
		// Re-read the worker state each pass so a databasePath change (or a
		// per-sidecar test harness) takes effect without a daemon restart.
		if fresh, err := readWorkerState(pluginDir); err == nil {
			path := fresh.DatabasePath
			if path == "" {
				path = filepath.Join(pluginDir, "data", "curator.sqlite3")
			}
			if path != loopPath {
				if next, _ := openDaemonLoop(pluginDir, fresh); next != nil {
					loop.Close()
					loop = next
					loopPath = path
				}
			}
			autoPayload = autoPayloadFromState(fresh)
		}
		now := nowMs()
		if now-lastTick >= autoTickMs {
			lastTick = now
			if enqueued, err := schedulerTick(loop, autoPayload, now); err != nil {
				errorLog("auto-scheduler failed: " + err.Error())
			} else {
				for _, mode := range enqueued {
					infoLog("auto-enqueued task " + mode)
				}
			}
		}
		jobID, startedAtMs, payload, mode, err := claimQueuedJob(loop)
		if err != nil {
			errorLog("daemon claim failed: " + err.Error())
			time.Sleep(claimPollMs * time.Millisecond)
			continue
		}
		if jobID != "" {
			idleSince = nowMs()
			runWorkerJob(pluginDir, loop, jobID, startedAtMs, payload, mode)
			continue
		}
		// Idle-exit only when nothing is queued AND the auto-scheduler has no
		// pending work (a dirty model or unsynced plays keep the daemon alive
		// so the gated update fires without a browser tab).
		stayAlive, stayErr := schedulerStayAlive(loop, nowMs())
		if stayErr != nil {
			errorLog("stay-alive check failed: " + stayErr.Error())
		}
		if !stayAlive && nowMs()-idleSince > idleExitMs {
			infoLog("daemon idle; exiting")
			return
		}
		time.Sleep(claimPollMs * time.Millisecond)
	}
}

// openDaemonLoop opens the loop connection (no artifact attaches — the
// per-job execution opens its own) and migrates defensively, so the daemon
// never reads a schema the enqueuer has not finished migrating.
func openDaemonLoop(pluginDir string, state workerState) (dbx, string) {
	path := state.DatabasePath
	if path == "" {
		path = filepath.Join(pluginDir, "data", "curator.sqlite3")
	}
	loop, err := openDatabase(realpath(path), false, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "curator-core daemon: could not open sidecar: %v\n", err)
		return nil, ""
	}
	if err := migrate(loop, nowMs()); err != nil {
		loop.Close()
		fmt.Fprintf(os.Stderr, "curator-core daemon: could not migrate sidecar: %v\n", err)
		return nil, ""
	}
	return loop, path
}

// daemonExitOnCancel makes the cancel path terminate the daemon process:
// the mode body runs synchronously in the main goroutine and cannot be
// interrupted, so a cancelled running job ends the process; its row is
// already marked 'cancelled' and the queue restarts on the next invocation.
var daemonExitOnCancel = false

// markRunningCancelled marks every running job owned by this process as
// cancelled (shutdown path).
func markRunningCancelled(db dbx) {
	execImmediate(db, `UPDATE curator_job SET state='cancelled', finished_at_ms=?, error='cancelled'
WHERE state='running' AND (owner_pid=? OR owner_pid IS NULL)`, nowMs(), os.Getpid())
}

// claimQueuedJob atomically claims the oldest queued row: state queued →
// running with owner_pid + heartbeat, returning the payload snapshot. An
// empty jobID means the queue is empty.
func claimQueuedJob(db dbx) (string, int64, jVal, string, error) {
	var jobID, jobType, payloadJSON string
	var startedAtMs int64
	err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		row := conn.QueryRowContext(ctx, `
SELECT job_id, job_type, started_at_ms, payload_json FROM curator_job
WHERE state='queued' ORDER BY queued_at_ms, started_at_ms LIMIT 1`)
		if err := row.Scan(&jobID, &jobType, &startedAtMs, &payloadJSON); err != nil {
			if err == sql.ErrNoRows {
				jobID = ""
				return nil
			}
			return err
		}
		result, err := conn.ExecContext(ctx, `
UPDATE curator_job SET state='running', owner_pid=?, heartbeat_at_ms=?, cancel_requested=0
WHERE job_id=? AND state='queued'`, os.Getpid(), nowMs(), jobID)
		if err != nil {
			return err
		}
		affected, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if affected == 0 {
			jobID = "" // another worker claimed it; try the next row
		}
		return nil
	})
	if err != nil {
		return "", 0, jvNull(), "", err
	}
	if jobID == "" {
		return "", 0, jvNull(), "", nil
	}
	payload, err := parseJSON([]byte(payloadJSON))
	if err != nil {
		return "", 0, jvNull(), "", fmt.Errorf("queued job %s has a corrupt payload: %w", jobID, err)
	}
	return jobID, startedAtMs, payload, jobType, nil
}

// runWorkerJob executes one claimed job with the same lifecycle as the
// inline path: fresh artifact-attached connection, settings from the payload
// snapshot, executeClaimedJob transitions, failures recorded on the row.
func runWorkerJob(pluginDir string, loop dbx, jobID string, startedAtMs int64, payload jVal, mode string) {
	settings := pluginSettings(payload)
	db, err := openTaskSidecar(pluginDir, payload, settings, mode)
	if err != nil {
		execImmediate(loop, `UPDATE curator_job SET state='failed', finished_at_ms=?, error=?
WHERE job_id=? AND state='running'`, nowMs(), truncateString(err.Error(), 2000), jobID)
		return
	}
	defer db.Close()
	_, _ = executeClaimedJob(db, pluginDir, payload, mode, settings, jobID, startedAtMs)
}

// heartbeatLoop writes liveness and watches the cooperative-cancel flag for
// one running job. On cancel the row is marked 'cancelled'; in daemon mode
// the process then exits (the synchronous mode body cannot be interrupted).
func heartbeatLoop(db dbx, jobID string, done chan struct{}) {
	ticker := time.NewTicker(time.Duration(heartbeatIntervalMs) * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			now := nowMs()
			execImmediate(db, `UPDATE curator_job SET heartbeat_at_ms=? WHERE job_id=? AND state='running'`, now, jobID)
			var requested int
			err := db.QueryRow(`SELECT cancel_requested FROM curator_job WHERE job_id=? AND state='running'`, jobID).Scan(&requested)
			if err == nil && requested == 1 {
				execImmediate(db, `UPDATE curator_job SET state='cancelled', finished_at_ms=?, error='cancelled'
WHERE job_id=? AND state='running'`, now, jobID)
				if daemonExitOnCancel {
					os.Exit(0)
				}
				return
			}
		}
	}
}

// ── progress sink ───────────────────────────────────────────────────────────

// progressSink persists progressLog markers into the running job's row,
// debounced so a build's per-batch markers do not turn into write
// amplification on the sidecar the build is already using. The sink uses its
// OWN connection (not the mode body's): the execution pool is pinned to one
// connection, so writing through it would block behind the mode's statements
// — and deadlock if a progress marker fires inside one of the mode's
// transactions. A second WAL writer just waits on busy_timeout.
type progressSink struct {
	db           dbx
	jobID        string
	mu           sync.Mutex
	lastWriteMs  int64
	pendingValue float64
	pending      bool
}

func newProgressSink(path, jobID string) (*progressSink, error) {
	db, err := openDatabase(realpath(path), false, nil)
	if err != nil {
		return nil, err
	}
	return &progressSink{db: db, jobID: jobID}, nil
}

func (s *progressSink) close() {
	s.flush()
	s.db.Close()
}

// flush writes the pending value unconditionally (no debounce); call before
// the terminal state transition so the last progress is not lost.
func (s *progressSink) flush() {
	s.mu.Lock()
	s.flushLocked(nowMs())
	s.mu.Unlock()
}

func (s *progressSink) report(value float64) {
	s.mu.Lock()
	if s.pending && value == s.pendingValue {
		s.mu.Unlock()
		return
	}
	s.pending = true
	s.pendingValue = value
	now := nowMs()
	if now-s.lastWriteMs >= int64(progressDebounceMs) {
		s.flushLocked(now)
	}
	s.mu.Unlock()
}

func (s *progressSink) flushLocked(now int64) {
	if !s.pending {
		return
	}
	execImmediate(s.db, `UPDATE curator_job SET progress=? WHERE job_id=? AND state='running'`, s.pendingValue, s.jobID)
	s.lastWriteMs = now
	s.pending = false
}

var (
	progressSinkMu     sync.Mutex
	activeProgressSink *progressSink
)

func setProgressSink(s *progressSink) *progressSink {
	progressSinkMu.Lock()
	defer progressSinkMu.Unlock()
	prev := activeProgressSink
	activeProgressSink = s
	return prev
}
