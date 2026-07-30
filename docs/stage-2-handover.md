# Stage 2 generation-storage handover

## Objective

Implement immutable feature and model SQLite generation files. Keep durable state in
`curator.sqlite3`; build, validate, and atomically publish rebuildable data beside it:

- `feature-<fingerprint>.sqlite3`
- `model-<model-id>.sqlite3`

Use Python and SQLite only. Preserve public behavior for recommendations, lanes,
explanations, reports, Similar, Expand, and Prune.

## Starting state

Stage 1 is implemented, verified, and locally installed:

- migration 18 stores feature scene, performer, and definition counts;
- reused feature results do not scan `entity_feature` for counts;
- feature/model builds report granular stage timings;
- existing fingerprint, top-K, and retention changes are the baseline;
- the full suite passed with 201 tests.

The worktree is intentionally dirty. Read `AGENTS.md`, `docs/handover.md`,
`docs/architecture.md`, `git status --short`, and the complete diff first. Preserve
every existing change. Migrations 17 and 18 are uncommitted but installed locally;
the next migration must be 19.

Live observations:

- core database: about 1.56 GB;
- real model build: 675.6 seconds;
- model reuse checks: 22.6 and 11.7 seconds;
- cold `get_slate`: 9.5 seconds, including 5.3 seconds materialized selection and
  2.9 seconds explanations;
- warm lane selection: 6–11 ms;
- only 20 of 23,891 scored scenes had reason rows, confirming runtime explanation
  generation is a cold-load cost;
- migration 17's removed lane-order index is unrelated; live queries use primary
  keys.

Do not put private live IDs, URLs, credentials, reports, or recommendation data in
tracked files or output.

## Required implementation

### Registry and paths

Reuse `feature_build` and `model_version` as the core registry. Add validated artifact
basename, schema version, byte size, counts, and validation summary/status.

Resolve artifacts only inside a derived-cache directory beside the core database.
Reject absolute paths, traversal, symlinks, unexpected names, and files outside that
directory.

### Artifact lifecycle

For each generation:

1. create a recognized temporary file on the same filesystem;
2. create tables and bulk-load before secondary indexes;
3. create indexes and every explanation/reason row;
4. validate integrity, schema version, counts, lane state, and complete reason
   coverage;
5. close handles and atomically rename to the final basename;
6. switch the active core pointer in one short transaction.

Any failure must leave the previous generation active and usable. Mark the attempt
failed and clean its temporary file when safe.

### Storage split

Feature artifacts own rebuildable feature data, including `feature_definition`,
`entity_feature`, and `scene_content_search`.

Model artifacts own rebuildable model data, including affinities, direct scene state,
scores, lane classifications/caches/orders/state, and `model_scene_reason`.

Keep durable source cache, jobs, feedback/events, impressions, history, exclusions,
pruning state, settings, and lightweight registry metadata in the core.

Do not delete legacy core derived rows yet. A schema-18 database should continue
working until the next successful build publishes generation files.

### Read compatibility

Attach the active feature/model files read-only. A connection keeps the generation it
attached; a new connection sees a newly published pointer.

Keep existing Python interfaces where practical. Trace and cover `FeatureStore`,
`RecommendationModelStore`, `LanePolicy`, `SlateBuilder`, explanations, reporting,
Similar, Expand, Prune, and API diagnostics.

Runtime reads must never write an immutable artifact. Generate all reason rows before
publication while preserving current response shape and factual content.

### Retention and operations

Retain the active and previous models plus their referenced feature files. Retire
older generations by unlinking validated artifact files, not cascading through core
rows. Failed unlink must be retryable and must not fail publication.

Core backups exclude artifacts. Restore invalidates the active generation pointer and
reports that recommendations need rebuilding. Reset removes only exact core files and
recognized artifacts/temporaries; never recursively delete a directory.

Expose aggregate diagnostics for active generations, artifact sizes/schema versions,
validation, reuse, reason coverage, and cleanup retries.

## Tests

Cover:

- artifact path validation;
- temporary creation, validation, rename, and atomic pointer switch;
- failed build/validation retaining the old generation;
- readers spanning publication;
- complete build-time reason coverage and read-only runtime explanations;
- cleanup retention and unlink retry;
- backup exclusion and restore invalidation;
- safe reset boundaries;
- schema-18 transition;
- parity for slates, lanes, scores, explanations, reports, Similar, Expand, and Prune.

Run focused checks during implementation and `scripts/verify full` once at completion.
Inspect `git diff --check`, file-specific diffs, and final status.

## Boundaries

Do not implement Stage 3 candidate/similarity caches, bounded reranking, legacy
compaction, or backup deletion. Add no service or dependency.

Do not commit, push, install, or mutate the live Stash/Curator databases. If the full
cutover cannot be completed safely in one package, stop at a real tested compatibility
boundary; do not create artifact copies that retain cascade deletion and runtime
writes.
