# Stage 3 performance-and-compaction handover

## Objective

Finish the generation-storage rollout with measured candidate/similarity caches,
bounded request-time reranking, safe legacy-core compaction, and explicit backup
deletion. Keep Python and SQLite as the only runtime dependencies and preserve public
behavior for recommendations, lanes, explanations, reports, Similar, Expand, and
Prune.

Do not add a cache merely because Stage 3 names one. Measure the installed paths
first, retain the Stage 2 implementation where it is already fast, and add only the
smallest persisted data that removes a demonstrated bottleneck.

## Starting state

Stages 1 and 2 are implemented, verified, and locally installed:

- migrations 17 through 19 are uncommitted;
- feature and model data publish as validated immutable SQLite artifacts;
- active artifacts attach read-only and readers keep their attached generation;
- model builds generate reason rows for every scored scene;
- retention unlinks validated artifacts with retry metadata;
- core backups exclude artifacts, restore invalidates generation pointers, and reset
  removes only recognized files;
- diagnostics expose generation sizes, schema versions, validation, reuse, reason
  coverage, and cleanup retries;
- a failed-build retry bug was fixed by preserving `last_error` until the next build
  actually starts;
- the full suite passes with 206 tests.

The worktree is intentionally dirty. Read `AGENTS.md`, `docs/handover.md`,
`docs/architecture.md`, `docs/stage-2-handover.md`, `git status --short`, and the
complete diff first. Preserve every existing change. The next migration must be 20.

Do not put private live IDs, URLs, credentials, reports, recommendation data, or
evaluation notes in tracked files or command output.

## Installed results

The first Stage 2 publication exposed two defects before a generation could become
active:

1. 126 scored scenes had no specific structured evidence. A factual neutral
   `fallback` reason now supplies complete coverage without changing rendered claims.
2. An immediate retry cleared the prior failure too early and looked like an active
   build. `ModelUpdateCoordinator.request()` now leaves error clearing to build start.

The successful installed build reported:

- total model build: 525.4 seconds, down from 675.6 seconds;
- feature lookup/reuse: 10.0 seconds;
- affinities: 7.1 seconds;
- similarity: 99.7 seconds;
- scoring: 10.6 seconds;
- artifact writes: 8.4 seconds;
- lane/reason indexing: 80.8 seconds;
- validation: 276.5 seconds;
- publication: 75 ms;
- cleanup: 31.7 seconds.

Published generations:

- feature artifact: 193,437,696 bytes, 4,675 definitions, 23,745 scenes, and
  2,352 performers;
- model artifact: 536,911,872 bytes, 23,891 scores, 43,074 lane rows, and
  218,676 reasons;
- reason coverage: 23,891 of 23,891 scored scenes;
- both artifacts pass `PRAGMA quick_check`.

Read-only checks for 20 For You items:

- connection open/attach: 55 ms;
- cold materialized slate: 165 ms;
- cold stored explanations: 187 ms;
- warm materialized slate: 23 ms;
- warm stored explanations: 159 ms.

These timings bypass impression recording and browser/Stash transport, so compare
them with the corresponding backend stages rather than the complete HTTP request.

## Core repair performed

After publication, SQLite reported a malformed B-tree isolated to `curator_job`.
Both generation artifacts were healthy. A byte-for-byte pre-repair copy was created
beside the core and verified with an identical SHA-256 hash.

Normal transactional `DROP TABLE` could not traverse the damaged B-tree. The repair:

1. removed only the `curator_job` table, auto-index, and started-time index entries
   through SQLite writable-schema recovery;
2. recreated the table and index exactly from migration 6;
3. ran `VACUUM` to discard the orphaned damaged pages;
4. ran both `PRAGMA quick_check` and full `PRAGMA integrity_check`.

Both checks return `ok`, migration 19 remains applied, and the repaired core is
775,479,296 bytes. Historical `curator_job` rows were intentionally lost; all other
logical tables and active generation metadata remain. The verified pre-repair copy
must not be removed by automatic backup cleanup.

The final normal-backend diagnostics invocation was blocked by the execution
environment's approval quota. The next session should first run diagnostics and one
native task-status query through a fresh process or the Stash UI. Stash itself was not
reachable from this host during validation, so the installed backend task was invoked
directly against the sidecar.

## Required Stage 3 work

### Measure before caching

Capture bounded profiles for:

- cold and warm For You plus one source lane;
- Similar for scenes and performers;
- Expand local ranking and cached external results;
- Prune candidate reads;
- model similarity construction and validation;
- core and artifact table/index sizes via SQLite `dbstat` when available.

The Stage 2 slate path is already fast. Keep it unless an end-to-end installed profile
shows a material bottleneck. Validation is currently the largest build stage, followed
by similarity construction and lane/reason indexing.

### Artifact schema compatibility

If Stage 3 adds artifact tables, write schema version 2 while continuing to read the
installed schema-1 artifacts until a successful replacement publishes. Never make a
code upgrade invalidate the only active generation before rebuilding.

Build every new cache before publication and keep runtime attachments read-only.
Validate cache bounds and parity against uncached calculations.

### Candidate and similarity caches

Persist only measured reusable work:

- bounded lane candidate inputs needed for request-time reranking;
- bounded scene/performer similarity neighbors when direct sparse queries or model
  construction are proven expensive;
- the generation/config fingerprints needed to reject stale cache rows.

Set explicit per-entity and global bounds. Bulk-load before secondary indexes. Do not
copy durable history, exclusions, or feedback into artifacts.

### Bounded reranking

Rerank only a bounded cached window. Preserve:

- hard eligibility and exclusion rules;
- live cooldown behavior;
- deterministic score-first and varied ordering;
- stable pagination and current response shapes;
- lane qualification and truthful ranking reasons.

Keep the existing materialized-order path as the parity oracle until installed
measurements and tests show the bounded path is equivalent.

### Legacy core compaction

Compact only rebuildable legacy rows whose registry entry has a valid published
artifact. Keep the legacy table schemas so restore/schema-18 compatibility can still
fall back until a new generation publishes.

Use bounded, restartable batches rather than a long migration transaction. Never
delete source cache, feedback/events, impressions, recommendation history,
exclusions, pruning state, settings, jobs, registry metadata, or the active/previous
artifact files. Report rows and bytes reclaimed, then run `VACUUM` only as an explicit
operation.

### Backup deletion

Add explicit deletion for recognized completed Curator backups only:

- reject absolute paths, traversal, symlinks, temporary files, artifacts, and
  unrecognized names;
- require exact user confirmation;
- refuse deletion while a Curator job is running;
- never automatically delete the pre-repair safety copy;
- do not add automatic age/count retention until requested.

Failed deletion must be reported without affecting the core or generations.

## Tests

Cover:

- schema-1 artifacts remain readable after a schema-2-capable upgrade;
- cache bounds, fingerprint invalidation, and cached/uncached parity;
- readers spanning schema-2 publication;
- bounded reranking parity, eligibility, cooldown, variety, and pagination;
- runtime attempts cannot write artifact caches;
- interrupted/resumed legacy compaction and exact durable-table preservation;
- compaction refusal without a valid active artifact;
- backup deletion path validation, confirmation, running-job refusal, and preservation
  of safety/temporary/unrecognized files;
- diagnostics after the empty `curator_job` repair;
- parity for slates, scores, explanations, reports, Similar, Expand, and Prune.

Run focused checks while iterating and `scripts/verify full` once near completion.
Inspect `git diff --check`, file-specific diffs, and final status. Install or mutate
the live sidecar only when explicitly requested.

## Boundaries

Do not add a service, scheduler, dependency, approximate vector database, or
distributed cache. Do not redesign the recommendation model, feedback semantics, or
UI. Do not delete media or mutate Stash except for the existing explicit reversible
Prune-tag operation.

If measurements show that a named Stage 3 cache or reranker is unnecessary, keep the
existing path, record the evidence in tests/diagnostics, and complete the remaining
measured work instead.

## Implementation record

Fresh installed diagnostics and native task status passed after the `curator_job`
repair. Migration 19 is current, both schema-1 artifacts validate, readiness is
complete, no update is pending, and subsequent build and sync-build jobs completed
without errors.

Installed read-only measurements:

- For You ranking/explanations: 521/395 ms cold and 27/172 ms warm;
- source-lane ranking/explanations: 216/240 ms cold and 24/159 ms warm;
- Similar scenes: 2.8 seconds cold and 1.7 seconds warm;
- Similar performers: 2.2 seconds cold and 2.0 seconds warm;
- Expand cached/local ranking: 120/1,031 ms;
- Prune candidate read: 80 ms;
- model similarity/indexing/validation: 89.4/107.2/187.3 seconds;
- feature/model artifact `quick_check`: 13.1/80.3 seconds.

`dbstat` measured 526.5 MB of logical core pages. The largest rebuildable legacy
allocations were scores (190.1 MB), feature rows/index (113.1 MB), content
search/index (68.7 MB), lane orders (29.6 MB), and lane rows (16.4 MB).

No new candidate/similarity cache or bounded reranker was added. Existing immutable
materialized score-first/varied orders already provide fast request-time selection
while preserving live eligibility and cooldown behavior. Prebuilding global
similarity neighbors would increase the already dominant build and validation stages
for a path bounded below three seconds, so the existing sparse calculation remains.

Stage 3 adds schema-1/2 read compatibility, artifact-validated restartable legacy
compaction, aggregate compaction diagnostics, a separate explicit `VACUUM` task, and
exact-confirmation deletion of validated completed backups. Compaction and vacuum
remain unrun against the installed sidecar; the protected pre-repair safety copy is
unrecognized by deletion and remains untouched.

The verified worktree was locally installed on 2026-07-30. Installed source hashes
match the worktree, diagnostics and native task status pass, materialized For You,
Similar, Expand, Prune, and explanations return normally, artifact writes are
refused, and backup-deletion safety checks pass without deleting anything.
