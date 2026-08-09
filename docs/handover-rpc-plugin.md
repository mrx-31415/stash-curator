# Resident RPC plugin handover

Updated: 2026-08-09.

## Goal

Remove the per-invocation Python process spawn from the plugin's hot paths (entity
hooks, operations, tasks) by converting the plugin from Stash's `raw` interface to its
resident `rpc` interface, so every call is a JSON-RPC message into a process that Stash
already keeps alive.

## Measured baseline

The entity-hook path was measured on a development host with the same dependencies
(numpy included) and against a copy of the live sidecar:

| Component | Time |
| --- | --- |
| Python process spawn + import (numpy) | 630-860 ms |
| Sidecar open + migrations + artifact attach | 10-120 ms (cold) / ~10 ms (warm) |
| GraphQL round trips (settings + find-by-id) | ~60-180 ms |
| Upsert + model request | ~10 ms |

The spawn is **70-85% of the per-edit cost**. A 500-scene bulk edit therefore blocks
Stash's mutation path for roughly 6-8 minutes today (the enqueue change in #90 already
removed the fetch + upsert from that path; the spawn remains the floor for raw hooks).
Converting to `interface: rpc` removes the spawn: per-edit drops to ~50-200 ms and a
bulk edit to roughly 30-60 seconds. The enqueue-only hooks (migration 27,
`pending_entity_change`) are the prerequisite: with RPC, the hook is just one small
INSERT in a resident process.

Keep private scene, performer, and library identifiers out of tracked files and
command output.

## What Stash provides (verified against v0.31 source)

- `interface: rpc` (`InterfaceEnumRPC` in `pkg/plugin/config.go`): Stash starts the
  plugin's exec command once and keeps it alive; every operation, task, and hook is a
  call into the resident process.
- The wire protocol is Go `net/rpc` with the JSON codec over the process's stdin/stdout
  (`pkg/plugin/rpc.go`, `net/rpc/jsonrpc`, lifecycle via the `pie` library, which
  reconnects on crash). Requests are newline-delimited JSON objects
  `{"method": "RPCRunner.Run", "params": [<PluginInput>], "id": <n>}` with
  `{"result": <PluginOutput>, "error": ..., "id": <n>}` responses; `RPCRunner.Stop` is
  the shutdown call.
- Hooks execute through the same task path: `executePostHooks` builds a `pluginTask`
  and `createTask()` dispatches to the interface's task builder, so an RPC plugin
  receives hook invocations as `RPCRunner.Run` calls with the same
  `hookContext` payload.
- Reference implementation: `pkg/plugin/examples/gorpc` (Go). There is no packaged
  Python RPC example; the Python plugin examples are raw (`pkg/plugin/examples/python`).
- The yml `exec` stays the same (Stash runs it once, inside its container); only
  `interface: rpc` changes. Stash restarts the process on crash via `pie`.

## Design

1. **Transport**: a small `net/rpc`-over-jsonrpc server in Python. Read one JSON
   object per line from stdin, dispatch `RPCRunner.Run` / `RPCRunner.Stop`, write the
   JSON response line. Keep it dependency-free (stdlib only): the wire format is
   simple, and the plugin must not gain runtime requirements.
2. **Entrypoint**: `backend.py` gains a `serve` mode (a flag or first argv) that runs
   the resident server; the raw stdin/stdout `main()` stays for development and
   fallback. The per-call bodies (`dispatch`, `_run_entity_hook`, `_run_task`) are
   unchanged — only the shell around them moves.
3. **Concurrency**: Stash issues calls concurrently (hooks especially, during bulk
   edits). The server must handle concurrent `Run` calls (threads or a small worker
   pool). The sidecar already tolerates this (WAL, busy_timeout); each call opens its
   own connection and closes it, as today.
4. **Lifecycle**: handle `RPCRunner.Stop` gracefully (flush/close), and ensure the
   process exits cleanly when stdin closes. `pie` reconnects if it crashes, but the
   handler should be defensive: a crashed resident process means hooks are missed
   until restart, so keep the queue semantics (drain on next rebuild) as the safety
   net.
5. **Instrumentation**: keep the existing span/profiling wrapper per call; the trace
   goes to the same `profile_trace` table.

## Implementation steps

1. Add the jsonrpc-over-stdio server (stdlib), with unit tests against the wire
   format (feed scripted request lines, assert response lines, including errors and
   `RPCRunner.Stop`).
2. Convert `main()` so the same handlers serve both the raw one-shot contract and the
   resident server; switch `stash-curator.yml` to `interface: rpc` behind a
   config-controlled choice if a fallback is wanted.
3. Rework the harness: integration tests currently drive `backend.py` via argv/stdin
   subprocesses; they must instead run the resident server and talk JSON-RPC (or keep
   one raw-mode test for the fallback path). The Phase 0 benchmark
   (`scripts/benchmark.py`) already drives the plugin through Stash's
   `runPluginOperation`/`runPluginTask` mutations and reads profiling traces from the
   sidecar, so it works unchanged over either interface — use it as the before/after
   measurement tool.
4. Measure again with the same methodology as the baseline table; target per-edit
   hook cost below ~300 ms on the integration box and confirm a synthetic bulk edit
   completes in seconds. The Phase 0 measured interactive medians (~1.1 s wall, of
   which ~55-250 ms work, 4 reps) are the "before" numbers to beat.
5. Verify hooks, operations, tasks, and progress reporting all work through RPC on the
   live install; confirm Stash restarts the process after a forced kill.

## Prepared state (2026-08-09, Phase 0 complete)

This work package is decided and prepped; it is the next session's task. What exists:

- `docs/handover-rpc-plugin.md` — this design (goal, baseline, wire protocol,
  risks, acceptance criteria above).
- `docs/decisions/002-runtime-swap-planning.md` — the full planning record:
  language comparison, Go-vs-numpy POC evidence, equality-coverage plan, release/
  dev workflow, and the Phase 0 measurements.
- `poc/golang-similarity-benchmark/` — the banked Go kernel benchmark (tracked).
- `scripts/benchmark.py` — the automated Phase 0 harness: starts Docker Stash with
  the plugin installed, enables profiling via `configurePlugin`, runs the ops
  battery + tasks, pulls traces from a copied sidecar, writes a scrubbed report to
  `.tmp/benchmark-report/`. Run with `uv run python scripts/benchmark.py --db PATH
  [--cold-build]`. Requires `STASH_CURATOR_DB`/`--db` (the live testing sidecar), a
  Docker daemon, and the Stash image.

Phase 0 findings that shape this work:

- Interactive operations are spawn-dominated: ~1.1 s median wall per call, of which
  ~55-250 ms is work (numpy import is ~400-700 ms of the spawn). Removing the spawn
  is the measured win; a resident process also pays the numpy import once instead of
  per call.
- Gotchas learned while building the harness (relevant to step 3 and to validating
  the RPC conversion): `health` and `round_trip` are intentionally not profiled;
  profiling enables via `configurePlugin(plugin_id, input: {profilingEnabled: true})`
  (config.yml alone does not reach the plugin); Stash's `jobQueue` query returns
  null in v0.31.1 while plugin tasks run, so task completion must be read from the
  sidecar's `curator_job` rows (filtered by `started_at_ms > submission`); plugin
  task submission is async (`runPluginTask` returns the job id).
- Defect to file (independent of this work): one `get_config` rep crashed the plugin
  process with `signal: bus error` after numpy import in the container
  (`docker logs integration-stash-1`).

Uncommitted worktree state at handoff (not yet committed): `.gitignore` (+`.tmp/`),
`docs/decisions/002-runtime-swap-planning.md`, `poc/`, `scripts/benchmark.py`. The
RPC conversion itself has not started.

## Risks

- The `net/rpc` jsonrpc framing must match exactly (method name, single-value params,
  id echo). Get the wire protocol wrong and Stash reports the plugin as failing to
  start; the fallback raw mode limits blast radius during rollout.
- Concurrency bugs (shared mutable state across calls) would be new to the plugin —
  today every invocation is a fresh process. The per-call connection model avoids
  most of it.
- Stash version compatibility: `interface: rpc` has existed for a long time, but the
  behavior of hooks under RPC should be re-verified on the target Stash version.

## Acceptance criteria

- Hook per-edit cost < ~300 ms including a resident call (no spawn).
- A 500-entity bulk edit completes in seconds, not minutes.
- Full unit + integration suites pass against the RPC transport.
- Crash recovery: kill the resident process; the next Stash call (or reload)
  restores it and the pending queue is not lost (it lives in the sidecar).
