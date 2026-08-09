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
   one raw-mode test for the fallback path).
4. Measure again with the same methodology as the baseline table; target per-edit
   hook cost below ~300 ms on the integration box and confirm a synthetic bulk edit
   completes in seconds.
5. Verify hooks, operations, tasks, and progress reporting all work through RPC on the
   live install; confirm Stash restarts the process after a forced kill.

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
