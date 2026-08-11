# Slice 4 — frontend parity and Python-fallback removal (Go backend port)

READ FIRST: `docs/handover.md` (current state: slices 0–3 merged),
`docs/handover-go-backend-slice3.md` (the delivered write path, task modes,
and model build), `docs/decisions/002-runtime-swap-planning.md` §4 (the
**tolerance policy** — issue #113 reversed the byte-exactness requirement),
`plugin/backend.py` (the `_api` dispatch and `_run_entity_hook`), the
hook wiring in `plugin/stash-curator.yml` (`hooks:`), and `AGENTS.md`.

## Goal

Every operation and task mode the frontend or Stash can invoke runs natively
in `curator-core`, so the Python fallback paths can be retired. Differential
coverage follows the current policy: structure, ids, counts, orderings,
strings, and integers compare exactly; floats compare within rel 1e-9
tolerance. The frontend JS is unchanged — this slice closes the last gaps in
the op/task surface, not the UI.

## Current state (merged, 2026-08-11)

- Native ops: all read-path interactive ops, the network-layer ops, the
  write-path ops, and the task modes (`backup`, `compact`, `vacuum`,
  `prepare`, `sync-plays`, `expand-refresh`, `build`, `update-model`,
  `sync-build`, `full-sync-build`) — see `core/backend.go` dispatch and
  `taskModeNative`.
- The differential gates are tolerance-based (`tests/core/compare.py`:
  `assert_equivalent` / `artifact_tolerant_diff`); the bit-exact CPython math
  ports are deleted (issue #113).
- The StashDB + Stash sync client surfaces and the model build are native.
- The Python fallback (`core/fallback.go` → `plugin/backend.py`) still serves
  the items below.

## Remaining work items

### 1. Port the four remaining ops (currently Python-only)

Diff of `plugin/backend.py`'s `_api` dispatch vs `core/backend.go`:

| op | Python implementation | notes |
| --- | --- | --- |
| `get_external_tag_choices` | `api.tag_external_choices` (~line 854) | expand-filter tag dropdown; reads the taxonomy tables |
| `get_inspector_entity` | `api.inspector` (~line 962) | entity inspector panel |
| `get_tag_sentiment_follow_up` | `api.tag_sentiment_follow_up` (~line 849) | scene sentiment follow-up, `limit` capped at 3; the JS calls it (stash-curator.js ~790) |
| `reset` | `_api` reset branch (~line 1614) | destructive sidecar reset; requires `confirmation == "RESET"`; confirm the exact wipe semantics with the user before porting |

Add each to the `dispatch` switch in `core/backend.go`, mirror the Python
behavior (including the error paths — e.g. `reset` without confirmation
raises), and cover with a differential test in `tests/core/` using the
tolerance comparator. `get_external_tag_choices` is the only one of the four
with a Python-only dependency on the taxonomy store — the Go taxonomy read
path (`core/taxonomy_resolve.go`) already covers the tables it needs.

### 2. Port the `entity-sync` hook mode natively

`backend.go:77` currently forces `entity-sync` to the Python fallback. The
Python handler (`plugin/backend.py:_run_entity_hook`) is deliberately tiny —
mirror it exactly:

- Parse `args.hookContext`; map the hook type via `_HOOK_ENTITY_TYPES`; on an
  unknown type return `{"handled": false, "hook_type": ...}`.
- Operation is `"delete"` for `*.Destroy.Post` hooks, else `"upsert"`.
- One bounded write to `pending_entity_change`; **no curator_job row, no
  single-running-job guard, no GraphQL fetch, no model build** (hooks run
  inline inside Stash's mutation path; failures must log and return a neutral
  result, never raise).
- The enqueue-then-drain design means the model build's drain
  (`core/tasks.go` / the sync-build path) already consumes these rows.

The sync service (`core/syncclient.go`) is already ported; the hook only
enqueues, so this is a small op, not a sync client task.

### 3. Retire the Python fallback paths

After items 1–2, every op in `_api` and every task mode is native. Then:

- `core/fallback.go`: the `dispatch` default case becomes unreachable for
  known ops — decide whether to drop the fallback entirely (unknown ops error)
  or keep it as a safety net.
- Packaging: `scripts/build_plugin.py` currently ships `backend.py` + the
  `curator` package + the binary. Removing the Python backend from the zip is
  a product decision (fallback is the safety net during rollout); the
  launcher exec line already points at the binary. Confirm the end state with
  the user before deleting any packaged Python.

## Constraints and landmines

- **Tolerance policy (issue #113):** never reintroduce a bit-exact math port
  or a byte-exact float gate. Structure/ids/counts/orderings stay exact.
- `SetMaxOpenConns(1)` — never nest DB queries inside a `Rows` loop (deadlock).
- Do not "fix" the masked-NaN performer kernel divergence (reviewed product
  decision, planning doc §8).
- The Go attach fallback chain and `core/jsonv.go` as shipped.
- SQLite schema changes need a new ordered migration; never edit applied
  migrations.
- Live Stash and StashDB access is read-only unless the user explicitly asks
  to test the reversible Prune-tag mutation. Curator never deletes media.
- Never stage `WATCHDOG.yml` (user's file, untracked).
- `entity-sync` must stay inline-safe: no job rows, no lock contention — the
  hook runs inside Stash's mutation path.

## Known issues to close alongside

- **#109 — `database is locked (261)`** (Expand + other tabs): observed
  after the Go rewrite; SQLite busy-recovery on the NFS-backed sidecar. The
  durable fix is tracked in **#103** (keep the working sidecar on local
  storage; sync to the NFS dir).
- **#110 — expand-refresh progress bar** does not advance.
- The `main.jVal` bind error from the live sync task: fixed (file durations /
  marker `end_seconds` now bind as floats) and reinstall superseded the stale
  binary; if it recurs, capture the op that triggered it.
- The integration `get_similar` 1-ulp flake is tolerance-covered now; keep the
  structural-exact assertions when touching `test_backend_swap.py`.

## Acceptance criteria

- `get_external_tag_choices`, `get_inspector_entity`,
  `get_tag_sentiment_follow_up`, and `reset` run natively with differential
  tests in `tests/core/` (tolerance comparator) covering the success and
  error paths.
- `entity-sync` runs natively with no `curator_job` row; the hooks integration
  test (`tests/integration/test_hooks.py`) passes through the installed zip.
- `scripts/verify changed` / `full` / `integration` green; static binary,
  no new runtime deps, `core/go.mod` unchanged.
- The frontend parity leftovers in `handover.md` are removed from the "next
  work package" section, or the fallback-retention decision is documented.

## Verification

- Differential + state-parity tests: `scripts/verify changed tests/core/...`.
- Full suite: `scripts/verify full`.
- Installed: `scripts/install-local.sh`, then reproduce each newly native op
  and the hook path once for cold start and once for steady state; check
  Stash logs, task progress, and desktop/mobile layouts. Live behavior on
  192.168.1.100 can only be verified after the user reloads plugins/restarts
  Stash — never claim an installed fix is verified until that retest happens.
## Session 2026-08-11 — delivered (uncommitted)

All four remaining ops and the entity-sync hook mode are native in
`curator-core`; the in-binary Python fallback is retired.

**Native in `curator-core`:**
- `get_external_tag_choices` (`core/frontend.go`): the source_tag /
  tag_role / direct_tag_preference / source_tag_stash_id read plus the
  taxonomy alias → local tag fallback (same UNION query as Python).
- `get_inspector_entity` (`core/frontend.go`): scene (full
  `ModelSceneScore` asdict + explanation via the extracted
  `renderExplanationForScene`, shared with `get_explanation`) and performer
  (`source_performer` dict row + `similar_performers` via the existing
  `performerProfilesAll`/`performerSimilarity` kernels).
- `get_tag_sentiment_follow_up` (`core/frontend.go`): reuses the native
  taste-profile output (`getTasteProfileBody`) and applies the Python
  filter/sort/limit.
- `reset` (`core/frontend.go`): confirmation gate, running-job guard,
  removal of the database + WAL/SHM + `recognized_artifacts` (new
  `recognizedArtifacts` port of `artifacts.recognized_artifacts`), then a
  fresh migrated sidecar. Unprofiled like Python's dispatch branch.
- `entity-sync` (`core/entity_hook.go`): the `_run_entity_hook` port —
  hook-type map, upsert/delete by `.Destroy.Post` suffix, one bounded
  `pending_entity_change` upsert + `coordinatorRequest("entity_hook")`
  inside a transaction, **no `curator_job` row**, and a neutral
  `{"handled": false, "reason": ...}` (truncated to 500) instead of raising.

**Fallback retirement (decision recorded):** `core/fallback.go` is deleted;
`dispatch`'s default and unknown task modes error with Python's exact
messages (`unknown Curator API operation: ...`, `unknown Curator task: ...`).
`backend.py` stays in the shipped zip by decision — `plugin/launcher.py`
still falls back to it when no per-arch binary exists — pending the user's
confirmation to remove the packaged Python.

**Differential tests** (`tests/core/test_backend_slice4.py`, 26 tests):
stdout byte-parity (tolerance comparator) for the four ops' success and
error paths, reset's surviving-file/artifact/remake parity, and the hook's
output + `pending_entity_change` + no-job-row + coordinator parity (modulo
`created_at_ms`). The integration suite's stale "unported op falls back"
test became `test_write_op_byte_identical_through_plugin`, and the
inspector/sentiment ops were added to `_entity_ops`.

**Verification:** `scripts/verify core`-equivalent gate (168 tests in
`tests/core` + `tests/model/test_core.py` green), full non-integration
suite (476 passed), `go vet` clean, static binary; `core/go.mod`
unchanged. Live installed verification on 192.168.1.100 still requires a
Stash reload/restart after the user installs the rebuilt plugin.
