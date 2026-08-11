# Slice 3 — write-path ops, task modes, and entity-sync (Go backend port)

READ FIRST: `docs/handover.md`, `docs/handover-go-backend-slice2.md` (delivery
section — the perf addendum and the Slice 3 handoff), `docs/decisions/002-runtime-swap-planning.md`
§8, `plugin/backend.py` (the `_task` dispatch ~line 1300 and the write-path
branches of `_api`), `curator/sync/` (the task wiring that consumes
`core/syncclient.go`), `curator/model/builder.py` + `curator/features/builder.py`
(the build stages), `curator/expand.py` (`refresh`, `update_shortlist`),
`curator/history.py`, `curator/config.py`, `core/ops.go` + `core/tracing.go` +
`core/profiled.go`, `core/expand.go` + `core/syncclient.go` (extend, don't
fork), and `AGENTS.md`.

## Goal

Port the write-path interactive ops and task modes into the Go core so every
backend mutation runs natively with Python fallback only for the frontend
parity leftovers (Slice 4). Byte-identical JSON vs `backend.py` for the same
payloads and sidecar state (write-path outputs are small: status dicts,
backup listings, job ids). Task modes run to completion with the same
sidecar state modulo run-varying timestamps and the same logs; the build
stages reproduce the published model artifact (the artifact file is the
oracle — byte-compare artifact tables, not just JSON).

## What already shipped (do not redo)

- The Stash sync client surface: `core/syncclient.go` (operations, adapters,
  `SyncRepository`, `SyncService`) — `source_hash` parity via the Python
  JSON writer (`marshalSortedKeys`), all SQL mirrored. Slice 3 wires it into
  the `sync-build`/`full-sync-build`/`entity-sync`/`sync-plays` modes.
- The network-read plumbing the write ops share: StashDB client, external
  links, `taxonomyIndexResolve`, the `CURATOR_STASHDB_ENDPOINT` seam.
- Performance notes that carry over: never nest DB queries inside a Rows
  loop (the pool has `SetMaxOpenConns(1)` — deadlock); taxonomy-style
  indexes load once per call; the multi-hop walk is seed-only; the
  glibc-math ports (`pyExp`/`pyLog`/`pyTanh`) are corpus-pinned.

## The slice plan (from the planning doc §8)

1. **Mechanical SQLite ops first** (smallest, no oracle):
   `list_backups`/`create_backup`/`delete_backup`, `compact`, `vacuum`,
   `clear_profiles`, `update_config`, `get_job_status`/`get_diagnostics`
   updates. The backup flow has a state-machine with rollback — mirror it.
2. **Interactive write ops**: `update_shortlist` (ExpandService),
   `submit_feedback`/`correct_feedback`/`get_feedback_history` (history),
   `submit_tag_preferences`, `submit_events`, `replace_item` (slate),
   `set_prune_tag`/`update_pruning`/`get_prune_candidates` (pruning).
3. **Task modes**: `backup`, `prepare` (ExpandService.refresh pieces),
   `expand-refresh`, `build`/`update-model` (the build stages: affinities,
   scoring, lanes, publication — the largest port chunk), `prune`, then the
   sync family: `sync-build`/`full-sync-build` (wire `SyncService.sync`),
   `entity-sync`, `sync-plays`.
4. **Profile-trace parity** extends to task modes (the `_task` trace
   lifecycle, stage spans, `timings_ms`/`counts` in task output where the
   Python side reports them).

Non-goals: the frontend parity pass and deleting the Python fallback paths
(Slice 4).

## Harness plan

Extend the slice-2 differential harness (`tests/core/test_backend_slice2.py`
patterns) to the write ops: same sidecar copy for both backends, run the op,
then compare stdout bytes plus the resulting sidecar state (all tables
modulo `fetched_at_ms`/run timestamps). For the build stages, compare the
produced artifact database tables (and the published `model_version` rows)
against the Python-oracle artifact; the `scripts/verify core` differential
gate already seeds synthetic corpora for the kernels — reuse that corpus.
Task modes that hit Stash/StashDB use the existing stub servers; the sync
modes need a deterministic Stash graph fixture (scenes/performers/studios +
play history) with `updated_at` values that exercise the cursor logic.

## Acceptance criteria

Differential tests in `tests/core/` prove byte-identical stdout vs the
Python backend on builder-seeded synthetic sidecars for every ported
write-path op and task mode, with state parity (all mutated sidecar tables
modulo run-varying fields); the build stages reproduce the artifact tables;
profile-trace parity extends to the task modes; unported ops still work via
the fallback through the installed zip; `scripts/verify core` + `scripts/verify full`
+ `scripts/verify integration` green; static binary, no new runtime deps
(`core/go.mod` unchanged).

## Constraints

- SQLite schema changes always get a new ordered migration; never edit an
  applied migration. Backups/compaction must respect the existing on-disk
  format (the plugin's `data/` layout and the `-derived` artifact dirs).
- Never delete media; Stash/StashDB access stays read-only except the
  reversible Prune-tag mutation when the user asks to test it.
- Keep the Python oracle untouched; the `CURATOR_STASHDB_ENDPOINT` seam
  stays test-only.

## First agent prompt

Port `list_backups`/`create_backup`/`delete_backup`, `compact`, and `vacuum`
with differential + state-parity tests, verify, then continue down the plan.

## Session 2026-08-11 — delivered (uncommitted)

The first agent prompt is delivered, plus the interactive-write slice and the
mechanical task modes:

**Native in `curator-core` (Python fallback still covers the rest):**
- Backup ops: `list_backups` / `create_backup` / `delete_backup` /
  `restore_backup` (`core/backups.go`) — online-backup API (modernc
  `NewBackup` via the driver conn), restore's supersede/rollback state
  machine, `_validate_backup` parity.
- Compact/vacuum: `compact_legacy_generations` with the fingerprint-gated
  restartable state machine (`core/compact.go`).
- Interactive writes (`core/writes.go`, `core/prune.go`,
  `core/profile_traces.go`): `update_shortlist`, `submit_feedback`,
  `correct_feedback`, `submit_tag_preferences`, `submit_events` (incl. the
  viewing/replacement signal curves using the glibc-faithful `pyExp` so
  stored REAL outcomes are bit-identical), `update_config`,
  `get_pruning_queue` / `get_prune_candidates` / `dismiss_prune_candidate` /
  `update_pruning` / `get_exclusions` / `reverse_exclusion` / `set_prune_tag`
  (Stash mutation) / `reconcile_prune_tag`, `list_profiles` / `get_profile` /
  `clear_profiles`.
- Task runner (`core/tasks.go`): the `_run_task_body` job lifecycle (stale
  recovery, single-running-job guard, complete/failed transitions) with
  native `backup`, `compact`, `vacuum`, `prepare`, and `sync-plays` modes.
- `core/historical.go`: `HistoricalEventStore.rebuild` (used by the sync
  family) and `core/materialize.go`: `SlateBuilder.materialize` (the greedy
  orderings reusing the runtime slate's candidate loader) used by `prepare`.

**Differential/state-parity tests** (`tests/core/test_backend_slice3_*.py`,
128 tests in `tests/core/` green): backup file content parity (both
implementations produce valid same-size backups of identical logical
content), compact/vacuum/backup task-mode byte-identity + state parity,
interactive-write byte-identity incl. every error path, behavior_event
outcome-float parity (pyExp), profile ops.

**Bugs found and fixed while porting:** the Go attach path failed on NULL
`artifact_basename` (published rows without artifacts); the task runner
shadowed `job_id` inside the transaction closure so the INSERT stored an
empty id and the completion UPDATE matched nothing.

Follow-up in the same session: the `expand-refresh` task mode is native too
(`core/expand_refresh.go`): the full `ExpandService.refresh` port including
the taxonomy refresh/publish side (`taxonomyFetch`/`taxonomyStorePublish`,
the embedded `stashdb_category_roles.json` resource for the category-role
fingerprint), the incremental-fetch probe, seeds, the candidate
merge/age-out/expand_cache writes, and `_rescore_candidates`. The StashDB
fetch reuses the network-layer `fetchScenes` + `expandService.score`.
Differential + state-parity tests in `tests/core/test_backend_slice3_refresh.py`
(reuses the slice-2 builder-seeded expand sidecar; 130 tests in `tests/core/`
green).

Follow-up in the same session: the **feature build stage is native and
differentially verified** (`core/featurebuild.go` + `core/build_artifacts.go`):
the deterministic `fv-<sha256>` version derivation (with a raw-UTF8 JSON
fingerprint variant for Python's `ensure_ascii=False` hashing), tag-role
resolution (the config rules + the taxonomy index with the default category
role), scene features (tag df/rarity/shrinkage + description TF-IDF with the
160-word stopword set), performer features (profile:content/age/measurements/
categoricals/augmentation with the fallback `repeated_scene_tags` path), and
the artifact publication (create/publish/activate + `tag_role`/
`tag_taxonomy_match`/`feature_build` sidecar writes). Exposed as a
`feature-build` kernel command; `tests/core/test_backend_slice3_featurebuild.py`
proves content-identical feature artifacts, matching `feature_version`, sidecar
row parity, and cross-implementation reuse (132 tests in `tests/core/` green).

**Still open in this slice (Python fallback active):** the `build`/`update-model`
and `sync-build`/`full-sync-build` modes (the remaining model build stages:
labels, affinities, scoring with the compiled-core kernels, lane
classification, publication — `curator/model/builder.py` + `ranking/policy.py`
oracles extracted), profile-trace parity tests for task modes, `scripts/verify
full` + integration, and the live installed verification on 192.168.1.100
after a Stash reload.
