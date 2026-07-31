# Runtime explanations and score-first ordering handover

Updated: 2026-07-30.

## Implementation status

The code change is complete. Published artifacts now leave `model_scene_reason` empty,
derive requested reasons through the existing reason algorithm, query exact
score-first order for Best Bets, Revisit, and Discover, and retain materialized
score-first order for Adventure and For You. All varied orders remain materialized.

Installed validation is complete. Storage improved materially, and recommendation
cards now derive explanations only when **Why this?** is expanded.

## Goal

Make generated model artifacts smaller and faster to build by:

1. deriving explanations only for requested scenes; and
2. serving exact score-first results from indexed model data while retaining
   precomputed varied ordering for stable pagination.

This is an experiment with two removal decisions, not a mandate to delete both stored
datasets at once. Measure and prove runtime parity before removing either one. It is
independent of performer-similarity propagation.

## Measured baseline

Installed profiling on a 23,891-scene library measured:

- full model build: about 409 seconds;
- publication: about 243 seconds;
- combined lane classification, ordering, reason generation, and index creation:
  about 144 seconds;
- generated artifact: about 540 MiB;
- `model_scene_reason`: 218,770 rows and about 268 MiB;
- `model_lane_order`: 135,304 rows and about 30.8 MiB, plus an 8.6 MiB unique index.

The former 88-second whole-artifact integrity scan has already been removed. Schema,
cardinality, and lane-state validation remain.

Keep private scene, performer, and library identifiers out of tracked files and
command output.

## Current flow

### Reasons

`PreferenceModelBuilder._publish()` in `curator/model/builder.py` leaves the
compatibility reason table empty and records reason generation as zero.

`ReasonGraphStore.build(model_id, scene_ids=...)` in
`curator/explanations/reasons.py` already has a targeted calculation path, including
bounded neighbor context, but it persists results to `model_scene_reason`.

`ReasonGraphStore.derive()` reuses `_prepare_neighbor_context()` and
`_scene_reasons()` without writing. `ExplanationService` retains derived results only
for that service instance. Existing artifacts with persisted reasons remain readable.

`CuratorAPI.get_slate()` returns ranking data without generating prose. Expanding
**Why this?** calls the existing single-scene explanation endpoint and displays
accessible loading and error states.

### Ordering

`SlateBuilder.materialize()` stores every `varied` order plus the scheduled
`score_first` orders for Adventure and For You. `_load_materialized_slate()` queries
Best Bets, Revisit, and Discover by `(model_id, lane, lane_value DESC, scene_id)` when
diversity is disabled, then applies the same live eligibility, direct-play, recovery,
and cooldown rules.

Adventure retains subtype scheduling and For You retains source-lane mixing, so their
score-first rows remain materialized. Full-order parity tests prove the three queried
lanes match `_build_order(..., varied=False)`.

Keep varied ordering precomputed. It carries diversity state and stable pagination
semantics that should not be reconstructed independently for every request.

## Implemented changes

### Instrumentation

Publication now reports lane classification, score-first ordering, varied ordering,
reason generation, and SQLite index creation separately.

Installed timings are recorded below.

### Runtime reasons

`ReasonGraphStore.derive()` returns requested reasons without writes. Recommendation
cards call it through the existing explanation endpoint only when **Why this?** opens.
Synthetic fixtures prove parity with persisted reasons.

Bulk generation and reason-coverage validation are removed. The empty compatibility
table remains, avoiding a migration or artifact schema change.

### Queried score-first ordering

Best Bets, Revisit, and Discover use the indexed query. Adventure and For You retain
materialized score-first rows, and all lanes retain varied rows.

## Verification

- Reason parity tests in `tests/explanations/test_reasons.py`.
- Ordering parity, filtering, refill, and stable-page tests in
  `tests/ranking/test_slate.py`.
- API tests in `tests/test_api.py` proving returned recommendations still have
  truthful explanations without bulk reason rows.
- Artifact validation and archive/runtime tests affected by the storage change.
- `scripts/verify changed` with the focused test files while iterating, then
  `scripts/verify full` once near completion.
- `scripts/verify full`: 217 tests passed.
- Installed integrity, artifact layout, score-first parity, and truthful explanation
  checks passed.

## Installed results

The first native rebuild reused the prior artifact because model IDs did not include
an implementation revision. `MODEL_BUILD_VERSION` now invalidates artifacts when
model-building semantics change, with a regression test.

The subsequent cold build completed in 1,038.5 seconds:

- similarity: 535.1 seconds;
- lane classification: 118.0 seconds;
- score-first ordering: 45.1 seconds;
- varied ordering: 114.3 seconds;
- reason generation: 0 seconds;
- SQLite index creation: 7.3 seconds;
- validation: 0.1 seconds.

The model artifact is 253,177,856 bytes, down from about 540 MiB. It contains zero
persisted reason rows and 115,418 order rows: varied order for every lane and
score-first order only for Adventure and For You.

Initial installed 20-item requests generated every explanation eagerly:

- For You: 2,178 ms cold and 1,875 ms warm, including 1,223/1,475 ms for explanations;
- Best Bets: 1,412 ms cold and 1,600 ms warm, including 799/1,302 ms for explanations;
- indexed score-first Best Bets: 905 ms cold and 81 ms warm;
- single-scene explanation: 640 ms cold and 450 ms warm.

After moving recommendation explanations behind **Why this?**, For You returns in
571 ms cold and 369 ms warm. Opening one explanation takes about 0.8–1.0 seconds and
returns complete and selected reasons.

Core and artifact `PRAGMA quick_check` return `ok`; core foreign-key violations are
zero. The smaller artifact meets the storage goal without slowing initial page
delivery. No durable cache or migration was added.

Do not accept a smaller artifact that makes normal page requests visibly slow. Do
not add a cache unless on-demand explanation latency itself becomes a measured
problem.
