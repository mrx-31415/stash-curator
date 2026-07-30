# Stage 4 live storage cutover handover

## Objective

Prove the installed Stage 3 storage lifecycle against the live sidecar: native backup,
restartable legacy compaction, explicit vacuum, restart, and post-operation parity.
This is an operational acceptance stage. Do not add another cache, schema, abstraction,
or dependency unless a reproduced failure requires the smallest tested fix.

## Starting state

- Stages 1 through 3 are implemented, locally installed, and uncommitted.
- The full suite passes with 210 tests.
- Installed source hashes match the worktree.
- Fresh diagnostics and native task status pass after the `curator_job` repair.
- Migration 19 is current; the next migration, if genuinely needed, must be 20.
- Active schema-1 feature and model artifacts validate and remain readable.
- For You, Similar, Expand, Prune, explanations, and artifact immutability pass
  installed read-only smoke checks.
- Legacy compaction has never run.
- The core reports 249,159,680 existing reclaimable bytes from earlier repair work;
  `vacuum_pending=true` alone therefore does not prove Stage 4 compaction ran.
- Three recognized completed backups exist. The verified pre-repair safety copy is
  intentionally unrecognized and must remain untouched.
- The worktree is intentionally dirty. Preserve every existing change.

Do not expose private URLs, credentials, entity IDs, reports, recommendation data, or
backup paths in tracked files or command output.

## Authorization boundary

Live compaction and vacuum are destructive to rebuildable legacy rows and require
explicit user authorization in the new thread. They never authorize deleting media,
resetting/restoring the sidecar, pruning, or deleting pre-existing backups.

Before creating another backup, check available disk space. If a fresh backup cannot
be created safely, stop and ask; do not delete an old backup to make room.

## Required sequence

### 1. Establish the baseline

Through fresh installed processes:

- run diagnostics and native task status;
- confirm no Curator job is running;
- record core/artifact sizes, schema versions, validation status, and integrity;
- record aggregate row counts for every durable table class: source cache, feedback
  and events, impressions and history, exclusions, pruning state, settings, jobs,
  registries, and generation pointers;
- record legacy derived row counts separately;
- confirm the pre-repair safety copy still exists without printing its full path.

Use aggregate counts and hashes only.

### 2. Resolve native backup acceptance

Run **Backup Curator data** through Stash's native task path and measure:

- Stash task state/progress and elapsed time;
- matching `curator_job` state;
- completed file size;
- SQLite `quick_check` and migration compatibility.

Do not start compaction if completion is ambiguous, the task remains running, the
backup is invalid, or the timeout defect reproduces. Diagnose and make the smallest
tested fix, reinstall it, and repeat the native backup check first.

### 3. Run restartable compaction

After a fresh backup is verified, run **Compact legacy Curator data** once.

- Let artifact validation finish; it may take several minutes.
- Poll no more often than every 30–60 seconds.
- If interrupted, inspect diagnostics and integrity. Resume by running the same task;
  do not reset or restore merely because compaction is incomplete.
- Record rows deleted, rows remaining, logical bytes removed, reclaimable bytes, and
  final task state.

Then confirm:

- compaction status is `complete`;
- legacy rows for validated artifact generations are zero;
- every durable aggregate count exactly matches the baseline;
- core and both active artifacts pass `quick_check`;
- all active/previous artifact files and registry metadata remain.

Do not run vacuum until these checks pass.

### 4. Run explicit vacuum

Run **Vacuum compacted Curator data** once. Record file bytes before/after and elapsed
time. Then rerun core `quick_check`, diagnostics, native task status, and the durable
aggregate comparison.

Never use writable-schema recovery, manual deletes, reset, or restore in this stage.

### 5. Restart and verify parity

Restart local Stash once, then verify:

- diagnostics and native task status;
- cold and warm For You plus one source lane;
- explanations and recommendation history;
- Similar for a scene and performer;
- Expand cached and local ranking;
- Prune candidate reads without applying/removing tags;
- backup listing and exact-confirmation refusal;
- desktop/mobile route loading and keyboard navigation.

Creating and deleting one new disposable backup is permitted only when the user's
new-thread prompt explicitly authorizes deletion of that exact newly created file.
Never delete a pre-existing, restore-safety, or pre-repair backup.

## If a code change is required

Reproduce first, trace every caller, and fix the shared root with one focused
regression test. Run `scripts/verify changed <test>` while iterating and
`scripts/verify full` once before reinstalling. Preserve schema-1 artifact
compatibility and every durable table invariant.

Do not commit, push, publish, restore, reset, or mutate Stash media unless separately
authorized.

## Exit criteria

Stage 4 is complete when the native backup task finishes truthfully, compaction and
vacuum finish once, durable counts remain exact, integrity checks pass, the restarted
installed plugin preserves all public read behavior, and the protected backups remain.

## Implementation record

Stage 4 completed on 2026-07-30.

- The native backup task finished in 14.4 seconds. The sole new 775,700,480-byte
  backup passed `quick_check` and migration-19 compatibility.
- Initial compaction stopped safely after 981,927 rows with a foreign-key error. A
  retired superseded model still owned legacy affinities referencing active feature
  definitions. The compactor now includes only retired, superseded, artifact-free
  model generations after validating the active artifacts; a focused regression and
  the full 210-test suite pass.
- The resumed task removed the remaining 207,530 rows. Total legacy deletion was
  1,189,457 rows, with zero derived rows remaining and clean foreign-key/integrity
  checks.
- Explicit vacuum completed once and reduced the core from 775,700,480 to 95,678,464
  bytes. Stable pre/post-vacuum durable aggregates and generation pointers matched.
- After the container restart, diagnostics, task status, cold/warm For You and Best
  Bets, explanations, history, scene/performer Similar, scene/performer Expand, and
  Prune candidate reads passed. Desktop and mobile routes loaded without horizontal
  overflow and real Tab-key focus navigation worked.
- The exact new disposable backup was deleted after validation. All three pre-existing
  completed backups, the older temporary file, active/retained artifacts, and the
  protected pre-repair copy remain.

## Next-thread prompt

```text
Read AGENTS.md, docs/handover.md, docs/architecture.md,
docs/stage-3-handover.md, and docs/stage-4-handover.md, then execute Stage 4
completely. Preserve all existing worktree changes and inspect the complete diff
first.

I authorize these live operations only in the handover's order: create and validate
one fresh Curator backup through Stash's native task path; run the existing Compact
legacy Curator data task; after its integrity and durable-count checks pass, run the
existing Vacuum compacted Curator data task; restart local Stash once; and perform
the specified read-only installed verification.

I also authorize deleting only the exact new disposable backup created during this
Stage 4 run, after it validates and after you show that its identity is unambiguous.
Do not delete any pre-existing backup or the pre-repair safety copy. Do not reset or
restore the sidecar, mutate media, apply Prune tags, commit, push, or publish.

Resolve the pending native backup-task timeout before compaction if it reproduces.
Keep schema-1 artifacts readable, use aggregate/private-safe output, poll long tasks
no more often than every 30–60 seconds, and stop if backup validity, integrity, or
durable-count parity is uncertain.
```
