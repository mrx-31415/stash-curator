# Planning: Curator-owned background task worker and scheduler

Status: **Phase 1 implemented (2026-08-17); scheduling pending**. Design
record for a detached, Curator-owned worker that takes task execution out of
Stash's single-slot job queue and adds scheduled tasks. Complements ADR 001
(raw-plugin backend runtime, accepted), `docs/decisions/002-runtime-swap-planning.md`
(compiled core), and issue #145 (direction 1: Curator-owned background
execution).

Updated: 2026-08-17.

## 1. Problem

- Every Curator task runs inside Stash's single-slot `JobManager` queue:
  the frontend calls `runPluginTask` (stash-curator.js), Stash spawns
  `launcher.py <mode>`, which execs `curator-core`, and the Stash job
  completes only when that process exits. A 150-409 s `sync-build` holds the
  slot the whole time, blocking every other Stash job (scan, generate,
  autotag, ...) and every other Curator task (`already_running` guard).
- There is no scheduling. "Auto" model updates are driven by frontend timers
  (`scheduleModelUpdate` / `scheduleModelMaintenance` in stash-curator.js)
  that call `runTask("Apply recent Curator feedback")`; with no browser tab
  open, nothing runs. `ModelUpdateCoordinator`'s docstring already assumes "a
  resident plugin supplies the wake-up loop" — that resident never existed.
- Scope decision: this is Curator-only. No stashapp/stash change (issue #145
  direction 2, a concurrent `JobManager.Start`) is in scope: it would benefit
  every plugin but is outside our control and unnecessary for the goals.

## 2. Current state (banked findings, verified against origin/main)

- Task invocation: frontend `runTask(name)` → GraphQL
  `runPluginTask(plugin_id: "stash-curator", task_name: ...)`; Stash appends
  the yml `execArgs` mode to the exec (`plugin/stash-curator.yml` `tasks:`,
  10 modes: sync-build, full-sync-build, build, update-model, sync-plays,
  prepare, backup, compact, vacuum, expand-refresh).
- All 10 task modes are native Go (`runTaskMode` switch, `core/tasks.go`).
  `runTaskModePending` is a dead stub. A worker is the same binary, no
  Python, no new exec surface.
- Task lifecycle (`runTaskBody`, `core/tasks.go`): 6 h stale window marks
  ancient `running` rows failed; a single `running` row newer than 6 h blocks
  new tasks (`already_running`); insert `curator_job` row
  (`job_id, job_type, state, started_at_ms, finished_at_ms, error,
  summary_json`); run the mode body; transition `complete`/`failed`.
- `health` (core/ops.go) applies a 120 s "interrupted" heuristic only when
  no matching job appears in Stash's own job list (`activeJob.kind ==
  jNull`). Both heuristics are valid only because one job == one
  Stash-spawned process.
- Progress: task stderr markers `\x01p\x02<fraction>` / `\x01i\x02<msg>`
  are parsed by Stash's job runner into the Stash job's `progress`; the
  frontend renders it from `health.active_jobs` (`CuratorTaskIndicator`
  reads `job.progress`). Curator's own `curator_job` rows carry no progress.
  Completion/failure reporting already flows through `curator_job` →
  `get_job_status` → indicator's `doneJob`/`latestFailure` without a live
  Stash job.
- Sidecar: SQLite WAL, 30 s busy_timeout, 128 MiB page cache, 512 MiB mmap
  on read-only connections (`curator/storage/database.py`, `core/sqlite.go`).
- Kernels: `runCoreKernel` (core/modelbuild.go) re-execs the current binary
  (`os.Executable()`) per kernel — works from a worker unchanged.
- Model update gating: `modelUpdateState` + `ModelUpdateCoordinator.ready()`
  (curator/model/updates.py) already implement the requested/threshold/
  interval semantics behind the `modelUpdate*` settings; only the trigger is
  missing.
- No cancellation exists anywhere in Curator; Stash's Tasks tab can only
  kill the whole job process.

## 3. Decision

Take the long-running task path out of the Stash job slot: the Stash-spawned
process becomes an **enqueuer** that records the task in the sidecar and
returns immediately; a **Curator-owned detached daemon** (a new mode of the
shipped `curator-core` binary) claims, runs, and reports queued tasks; a
**scheduler** inside the daemon enqueues tasks on a schedule. Interactive
operations keep the existing raw-plugin one-process-per-request protocol
unchanged.

## 4. Design

### 4.1 Enqueue-and-return (frees the Stash slot)

`runTaskBody` inserts a `state='queued'` `curator_job` row carrying a
`payload_json` snapshot (the `server_connection` sync/expand jobs need after
the spawning process is gone), ensures the worker is alive, and returns
`{job_id, queued: true}` immediately (~100 ms). Semantics:

- same-type coalescing keeps the `already_running` behavior (`already_queued`);
- if the worker cannot be spawned (unusual platform), run inline exactly as
  today — no behavior regression.

### 4.2 Daemon (`curator-core <pluginDir> daemon`)

- Detached spawn: `setsid` + stdio redirected to `data/curator-daemon.log`
  so the process survives Stash job teardown and Stash restarts. Must verify
  how Stash kills jobs (process-group kill is the case setsid defeats).
- Single instance: pid file with staleness and process-ownership checks; a
  reused PID is discarded rather than signalled or treated as the worker.
- Startup recovery: mark its own `running`/`queued` rows `failed`
  (`interrupted`) — ownership-based replacement for the 6 h window.
- Queue loop: atomically claim `queued` → `running` (one at a time; SQLite
  single-writer and builds serialize anyway), heartbeat
  (`heartbeat_at_ms`, ~20 s), run the existing `runTaskMode` bodies,
  transition `complete`/`failed` with `summary_json`.
- Ensure-worker on every plugin invocation (operation or task): compare the
  daemon's recorded executable fingerprint with the installed binary, terminate
  a stale generation, and spawn the current one. The resident daemon also
  watches that fingerprint, stops claiming new work after a replacement, lets
  an active job finish, and exits so the next invocation starts the new binary.
- This is the crash-resurrection and plugin-update rotation path; the
  fingerprint combines platform file identity, size, mtime, and permissions.
- Lifetime: lazy spawn on first task; exit when idle after a grace period
  (recommended) rather than permanently resident.

### 4.3 Liveness rewrite

The 120 s health heuristic (keyed on Stash's job list) and the 6 h stale
window both break once the Stash job completes instantly. Replace with
ownership: `health` reports `active_jobs` from `curator_job`
(queued + running, with progress/stage/description and owner heartbeat), and
dead-owner / stale-heartbeat rows (> ~5 min) are marked failed by the
ensure-worker path and daemon startup. The frontend indicator follows with no
structural change.

### 4.4 Reporting back as tasks run

Completion/failure reporting already works through `curator_job` and stays.
Live progress currently rides Stash's job record, which disappears; restore
it Curator-side:

- `progress` (REAL 0..1) and `stage` (TEXT) columns on `curator_job`;
- the daemon writes progress/stage to the DB **debounced** (~1 write/s, only
  on material change — builds emit per-batch/per-stage markers; unthrottled
  writes during a build would be the mistake here);
- `health`/`get_job_status` return them (health also supplies a `description`
  per job from the yml task names);
- frontend: the progress bar already renders `job.progress` — no change
  needed for the bar; queued-state label and Cancel are the real additions.

### 4.5 Cancellation

- Queued → cancelled instantly. Running → cooperative context cancellation
  threaded into `runTaskMode` bodies (sync page walks, build stages). Hard
  kill → SIGTERM then SIGKILL after grace.
- New op `cancel_job(job_id)` + Cancel button in the task indicator.
- UX note: Stash's Tasks tab can no longer stop Curator work (its job is
  already done) — cancellation moves into Curator's UI. Call this out in the
  handoff.

### 4.6 Scheduling

- New `scheduled_task` table: task_type, interval_ms, next_run_at_ms,
  enabled, last run/result. Scheduler goroutine wakes every ~30-60 s and
  enqueues due tasks, coalescing same-type.
- First candidates, in value order: `update-model` (kills the browser-timer
  dependency; gated by the existing `modelUpdate*` settings via
  `ModelUpdateCoordinator.ready()`), `sync-plays` (hourly), `sync-build`
  (daily), `backup` (daily).
- Interval-based only — no cron parser dependency. Config surface: yml
  `schedule*` settings, with the #151 Settings panel as the natural home.

### 4.7 Migration surface (new ordered migration, ~0030)

- `curator_job`: state CHECK gains `'queued'`; add `queued_at_ms`,
  `heartbeat_at_ms`, `owner_pid`, `payload_json`, `progress`, `stage`.
- New `scheduled_task` table.
- `backend.py` is the dev-side parity reference, not shipped (launcher:
  "no Python runtime ships in the plugin"); the lifecycle change is Go-only.
  Check the differential gates do not pin the inline task lifecycle.

## 5. Risks and open questions

- **Stash kill semantics**: verify whether Stash job stop/teardown kills the
  process group — setsid must defeat it. The one environment check that
  gates the whole design.
- **Plugin update vs running daemon**: zip install replaces the binary under a
  running daemon. Generation fingerprints rotate stale workers on invocation;
  the resident watcher drains the current job and exits without claiming more
  work, then the next invocation spawns the new version.
- **Progress write amplification**: debounce is mandatory (see 4.4).
- **Connection staleness**: jobs enqueued before a Stash restart carry a
  stale `server_connection`; refresh per enqueue, fail clear on stale URL.
- **Always-resident vs lazy-with-idle-exit**: lazy recommended (no permanent
  process on an otherwise idle plugin).
- **backend.py parity divergence** on the task lifecycle: keep the inline
  path as fallback so the reference and the differential gates stay honest.

## 6. Sequencing

- **Phase 1 (foundation)**: migration 0030; daemon mode (queue claim +
  heartbeat + orphan recovery); enqueue-and-return; ensure-worker; health
  re-keyed; progress/stage persistence; SIGTERM/ctx cancel. Verify: Stash
  slot frees instantly, jobs complete through the daemon, crash/stale
  recovery works, differential gates green.
- **Phase 2 (scheduling)**: `scheduled_task` + scheduler loop + `update-model`
  wake-up + yml `schedule*` settings.
- **Phase 3 (UX)**: task-indicator queued state + Cancel buttons; schedule
  config in the #151 Settings panel.

## 7. Verification

- Per phase: `scripts/verify changed <paths>` while iterating,
  `scripts/verify full` before handoff; the compiled-core differential gates
  must stay green (no float/ordering drift).
- Installed verification: Stash's job queue never shows a long-running
  Curator job; jobs complete via the daemon with live progress in the
  indicator; kill the daemon mid-build → next invocation recovers the
  orphan; scheduled `update-model` fires with no browser open; restart Stash
  mid-task → the daemon survives and the job completes.

## 8. Phase 1 deltas from this design (implemented 2026-08-17)

- **No `stage` column**: the frontend derives stage labels from the
  synthesized `description` + `progress` thresholds (`curatorTaskStage`), so
  only `progress` is persisted.
- **Cross-type guard relaxed by design**: the old "any running task blocks
  every task" guard became per-type coalescing; the daemon serializes its
  own claims. The mode-body guards (backup/compact/vacuum/reset refuse while
  running) are unchanged.
- **Unknown task modes still error at the invocation boundary**
  (`taskModeNative` check in `runTaskBody`), preserving the
  `unknown Curator task` contract for the frontend.
- **Migration 0031 avoids `ALTER TABLE RENAME`** entirely (DROP + CREATE +
  copy): SQLite's RENAME rescans the schema and trips a real bug on attached
  generation temp views' shadowed names ("views may not be indexed") — the
  constraint test_cascade_migration_survives_attached_generation_temp_views
  pins.
- **Progress writes debounced to ~1/s** via the daemon's progress sink;
  heartbeat every 20 s; stale-heartbeat recovery at 5 min; legacy
  pre-heartbeat rows keep the 6 h window.
- **Cancel**: queued → `cancelled` instantly; running → `cancel_requested`
  flag honored by the heartbeat loop, which marks the row `cancelled` and
  (in daemon mode) exits the process — matching today's kill semantics for
  a long build.
- **Differential harness moved**: task-mode comparison went from invocation
  stdout (which is now a queued marker) to the completed job's durable
  summary + sidecar state, via the shared worker runner in
  `tests/core/worker.py` (enqueue → daemon → poll `get_job_status`).
- `health`/`get_job_status` re-keyed to worker-owned rows with matching
  Python parity (`backend.py` stays the inline oracle; `cancel_job` added on
  both sides).

## 9. Remaining for Phase 2

- **Phase 2a implemented (2026-08-17)**: the daemon's event-driven auto-scheduler
  (`core/autotasks.go`) — replaces the browser-tab wake-up loop. With the new
  `autoTasksEnabled` setting on: `update-model` is enqueued when the existing
  `ModelUpdateCoordinator` gating (`modelUpdate*` settings) is ready and nothing
  is rebuilding; `sync-plays` is enqueued when plays newer than the last sync
  have been quiet for ~60 s. The dirtying operations (feedback, corrections,
  tag/term preferences, events, prune decisions, entity hooks) ensure the
  worker exists (`ensureAutoWorker`), and the daemon stays resident while a
  model update is pending or plays are unsynced — so the max-wait backstop
  fires with no browser open. Toggle exposed in Manage → Settings.
- **Phase 2b implemented (2026-08-17)**: time-based schedules in the same daemon
  scheduler. Migration 0032 adds the durable `scheduled_task` table
  (`next_run_at_ms`/`last_run_at_ms`); `schedule*` settings (default **off**)
  enable a daily-cadence `expand-refresh` (StashDB candidate freshness),
  `sync-build`, and `backup` — backup runs first when both are due so a rebuild
  never touches an unprotected sidecar. First enablement seeds `next_run` one
  interval out (never fires immediately); late runs catch up. Any enabled
  schedule keeps the daemon resident (a daily task must not depend on a browser
  respawning it). Enabling a schedule spawns the daemon via the settings write
  (`update_config`) and via the frontend's constant polls (`health`,
  `get_job_status`, `get_config` all ensure the worker).
- Phase 3 UX: task-indicator Cancel buttons; schedule config in the Settings
  panel (the Scheduling group is already rendered there).
