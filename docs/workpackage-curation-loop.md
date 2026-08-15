# Workpackage: Curation loop (hypothesis batches + exploration sampler)

Status: planned. Supersedes nothing. Three PoCs on live data already pinned the
design: hypothesis batch-fetch, category-filtered exploration sampler, and the
label-outcome hypothesis generator (`/tmp/poc_batch.py`, `/tmp/poc_explore.py`,
`/tmp/poc_hypotheses.py` — throwaway, not shipped).

## Goal

A "Curate" lane in the plugin where the user rates short scene batches chosen
by Curator, and the ratings feed the preference model. Two batch modes:

- **Hypothesis**: tests a declared (base tag × context tag) relationship with a
  stratified 2×2 sample (prototyped: lesbian/threesome, 7/7/3/3 + anchors).
- **Exploration**: maximizes new *interactive* tag coverage with a
  rarity-weighted max-coverage sampler, excluding StashDB appearance categories
  (prototyped: 20 scenes → 390/711 interactive tags, 20 distinct studios).

Ratings become model labels immediately (new `curation_rating` signal), so the
scalar model improves with every batch even before any pair-rule mechanism
exists. Verdicts (per-cell contrast) are computed from the batch's own ratings,
not the model — no rebuild needed to see them.

Non-goals (explicitly out of scope, reserved for later packages): pair-rule
schema/resolution ("lesbian → threesome = +0.5"), rule-writing actions from the
verdict, learned conditional affinities (option 5), term-level curation.

## Architecture context

- Runtime ops are served by the compiled core (`core/`, Go); `plugin/backend.py`
  is the differential oracle. **Every op here is dual-implemented** with
  byte-identical differential tests (structure exact, floats rel 1e-9).
- Migrations: one new ordered migration (next number: **0029**), mirrored
  byte-identical in `core/migrations/` and `curator/storage/sql/`. Never edit
  an applied migration.
- The plugin frontend is `plugin/stash-curator.js` (React), CSS, with runtime
  string-assertion tests in `plugin/test_runtime.py`. Navigation is lane-based;
  Curation is a new lane (pattern: `TasteProfilePanel`, `lane === "taste"`).
- SFW Switch contract (AGENTS.md): scene cards keep `scene-card` /
  `*-card-image` / `card-section` classes; **rating controls live OUTSIDE
  `card-section`** (the switch blurs that section).

## Package 1 — Backend: selection, ratings, model integration

### Migration 0029: `curation_batch` + `curation_batch_item`

```sql
CREATE TABLE curation_batch (
    batch_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('hypothesis', 'explore')),
    base_tag_id TEXT,              -- hypothesis mode only; tag ids are TEXT in this schema
    context_tag_id TEXT,           -- hypothesis mode only
    budget INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'rated', 'superseded')),
    created_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'   -- policy parameters, cell counts
) STRICT;

CREATE TABLE curation_batch_item (
    batch_id TEXT NOT NULL REFERENCES curation_batch(batch_id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL,
    cell TEXT NOT NULL,               -- 'L&T' | 'L&!T' | '!L&T' | '!L&!T' | 'explore'
    anchor INTEGER NOT NULL DEFAULT 0,
    rated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (batch_id, scene_id)
) STRICT, WITHOUT ROWID;
```

History: batch items are immutable once issued; ratings live in `feedback`
(reusable, reversals already supported) — **no feedback schema change**.

Ratings: `feedback_type = 'curation_rating'`, `value` = `"0"`..`"10"` (TEXT,
matching the existing column), `payload_json` = `{"batch_id": ...,
"cell": ...}`. Reasons reuse existing types (`metadata_wrong`, `not_now`) plus
a new `contradicts_hypothesis` (informative only in v1; mined later).

### Ops (Go + Python oracle + differential tests)

All selection is **deterministic**: every query `ORDER BY scene_id`, tie-breaks
by `scene_id`, no RNG. Pool exclusion: already-labeled scenes (builder's exact
label set), `metadata_wrong`, blocked-tag scenes.

**`get_curation_batch`** — request:

```json
{ "mode": "hypothesis"|"explore",
  "base_tag_id": 228,          // hypothesis only
  "context_tag_id": 60,        // hypothesis only; null -> generator suggests
  "budget": 20 }               // 10..40, default 20
```

Response:

```json
{ "batch_id": "…", "mode": "hypothesis",
  "base_tag_id": 9001, "context_tag_id": 9002,
  "items": [ { "scene_id": "1001", "cell": "L&T", "anchor": false,
               "tags": [ {"name": "Threesome", "category": "Group Makeup"} ] } ],
  "pool": { "L&T": 64, "L&!T": 61, "!L&T": 222, "!L&!T": 2041 },
  "policy": "stratified 7/7/3/3, studio round-robin, unlabeled only" }
```

Algorithms (as prototyped):

- **Hypothesis**: allocate `L&T`/`L&!T` = 35% each, `!L&T` = 15%, `!L&!T`
  anchors = 15% of budget (rounding to whole scenes, contrast cells first);
  within cell, studio round-robin (one scene per studio before repeats);
  anchors drawn from the library appeal middle band (current model
  `model_scene_score.general_appeal` ±200 around the median, deterministic
  order).
- **Explore**: greedy max-coverage over *interactive* tags, rarity weight
  `1/sqrt(library_tag_count)`, incremental value updates, studio penalty ×0.5
  for repeat studios, plus 3 anchors from the middle band.
- **Category filter** (both modes' candidate space, explore's value function):
  exclude these `taxonomy_category` names — Hair Color, Hair Style, Body Type,
  Breasts, Face, Skin Tone, Piercings, Ass, Genitals, Height, Tattoos, Race.
  Tags without a resolvable taxonomy match are treated as interactive.
  Taxonomy joins: `tag_taxonomy_match.external_category_id` →
  `taxonomy_category` (same snapshot).

**`submit_curation_ratings`** — request:

```json
{ "batch_id": "…",
  "ratings": [ { "scene_id": "1001", "value": 8, "reason": null },
               { "scene_id": "1002", "value": 2, "reason": "contradicts_hypothesis" } ] }
```

Validation: batch exists and `status='open'`; every scene is in the batch;
value integer 0..10; no duplicate scene in the payload; a scene already rated
in this batch returns an explicit error (caller reverses first). Writes
`feedback` rows (type `curation_rating`, value as TEXT, payload with
batch_id/cell) + sets `rated=1`; batch `status='rated'` when all items rated.
Partial submission allowed (resume by re-issuing with remaining scenes).
Wire-contract note: `budget`/`min_support` of 0 are falsy and coerce to the
default (20) in both backends (`int(args.get(key) or default)` mirror).

**`get_curation_verdict`** — request `{ "batch_id": "…" }`. Response:

```json
{ "batch_id": "…", "mode": "hypothesis",
  "cells": [ { "cell": "L&T", "n": 7, "mean_outcome": 0.34 },
             { "cell": "L&!T", "n": 6, "mean_outcome": 0.14 } ],
  "contrast": { "delta": 0.20, "n_total": 13, "confirmed": true },
  "suggested_rule": { "base_tag_id": 9001, "context_tag_id": 9002, "value": 0.5 },
  "note": "rule-writing lands with the pair-rule package" }
```

Semantics: cell stats from the batch's own `curation_rating` rows only
(attribution, no merging with other labels); outcome = `(value-5)/5`.
`confirmed = |delta| >= 0.15 AND n_total >= 10` (calibration constants,
config-default). `suggested_rule.value` = five-point rounding of the contrast
cell mean. Explore mode: no `contrast`; instead top positive/negative tags by
mean outcome (the discovery ranking) and no suggested rule. Verdict is
read-only over `feedback` — **no rebuild required**.

**`get_tag_context_candidates`** — request `{ "tag_id": 228, "min_support": 20 }`.
Response: ranked candidate contexts for the generator:

```json
{ "tag_id": 228, "items": [ { "tag_id": 60, "name": "Threesome",
    "category": "Group Makeup", "cooccurrence": 665, "rate": 0.514,
    "labeled_n": 27, "contrast": 0.20 } ] }
```

Candidate space: co-occurring tags (≥ min_support) in interactive categories,
appearance categories excluded. Ranking: by label-outcome contrast (mean
outcome with vs without among labeled base-tag scenes), co-occurrence as
tie-break. Tags without labels sort by co-occurrence rate. This is the
"hypothesis formation" half.

### Model integration

- `_scene_labels` (`curator/model/builder.py`): new signal source —
  `feedback_type='curation_rating'`, `value` parsed as int, outcome
  `clamp((value-5)/5, -1, 1)`, confidence `config.model.curation_rating_confidence`
  (default 0.8), signal type `"curation_rating"`. Defensively skips
  non-numeric or out-of-range values (Go mirror identical).
- `ModelConfig.curation_rating_confidence: float = 0.8` (`curator/config.py` +
  Go `modelSubConfig`). Config-backed, not `EventCalibration`, so the model
  fingerprint (canonical config JSON) invalidates models if it ever changes.
- `curation_rating` joins the durable-signal sets (`curator/ranking/policy.py`
  + `core/laneclassify.go`) — a deliberate rating is durable evidence.
- Confirmation thresholds (|delta| >= 0.15, n_total >= 10), the anchor band
  (200), `min_support` (20), and the contrast label floor (4) are module
  constants in `curator/curation.py` + `core/curation.go`, NOT config: they
  never enter the model fingerprint, so no rebuild churn when tuned.
- Fingerprint: `feedback_state` already lists every feedback row
  (id, scene_id, type, value, occurred_at_ms, reversed_by_id) — new type rides
  it for free. Batch/curation tables do NOT need to enter the model fingerprint
  (they don't affect the build, only the ops).

### Package 1 tests

- Differential (Go vs Python, `tests/core/test_backend_slice5_curation.py`):
  all four ops, success + error paths, determinism (two identical calls,
  byte-identical output), hypothesis + explore modes, budget bounds, partial
  submission, resubmission errors, verdict attribution (batch's own ratings
  only), generator with/without labels.
- Migration: ordering, Go/Python mirror byte-identity.
- Unit: selection algorithms (unlabeled exclusion, studio round-robin,
  anchor band, category exclusion incl. unmatched-tag fallback), rarity
  weighting, calibration mapping, confirmation thresholds.
- Model-build differential with `curation_rating` rows present.
- `scripts/verify full` once near completion.

## Package 2 — Frontend: Curate lane

New navigation lane `curate` (icon `faBullseye`, already imported), rendered
`lane === "curate" && <CuratePanel />` beside TasteProfilePanel. Three states:

**1. Setup** (`CurateSetupForm`):
- Mode toggle: Hypothesis test / Exploration.
- Hypothesis: base tag search (pattern: taste profile search, backed by
  `get_tag_context_candidates` for a "Suggest contexts" button — shows ranked
  candidates with category + contrast, one click fills the context field).
- Budget select 10/20/40. "Generate batch" → `get_curation_batch`.

**2. Batch review** (`CurationSceneGrid` + `CurationSceneCard`):
- Grid of scene cards. Card = `scene-card` class with `*-card-image`; the
  rating strip is a sibling OUTSIDE `card-section` (SFW Switch contract).
- Per card: thumbnail, interactive tag chips (name + category), cell badge
  (`L&T` / `L&!T` / control / anchor), current model appeal (context), rating
  control.
- `CurationRatingControl`: 0–10 button row (compact, like
  `TagSentimentControl`'s short labels), keyboard reachable, `aria-pressed`;
  plus reason chips: Skip, "Metadata is wrong", "Not now",
  "No [context tag]" (hypothesis mode only; posts `contradicts_hypothesis`).
- Progress "rated x/20", anchor cards labeled "calibration". Submit →
  `submit_curation_ratings`; partial submit allowed; resume view for an open
  batch (batch state read back from `curation_batch`/`curation_batch_item`).

**3. Verdict** (`CurationVerdict`): after all rated — cell bars (mean outcome
per cell), contrast delta, confirmed/not, suggested rule shown with a
"lands in a later package" note (no rule-writing action in this package).

State handling: loading, empty pool ("no unlabeled scenes match"), op errors
(actionable message), batch already fully rated (show verdict). Batch list
(open batches) so users can resume.

CSS: `curator-curate-*` classes, dark-theme-safe (match existing palette).
Runtime tests: `plugin/test_runtime.py` asserts new lane, components, strings
(`"curate"`, `CurationSceneCard`, `"contradicts_hypothesis"`, verdict strings).
Manual: desktop + mobile layout, SFW switch (controls visible outside blurred
section), keyboard nav, submit/reverse flow, verdict after partial batches.

## Sequencing

**Specify both together (this doc), execute Package 1 then Package 2.**

- The API contract above is the seam and is already frozen by the PoCs; both
  sides implement against it. Writing both specs now prevents contract drift
  during the differential-gated backend work.
- Not concurrent: the frontend renders ops that don't exist; the backend's
  differential gate cannot be passed by Go while Python lags. Parallel
  execution would serialize on the contract anyway, with no gain.
- Backend alone is user-verifiable via the established link trick (Stash deep
  links from batch items) while Package 2 is built.
- Pair-rule dependency: the verdict's "Add rule" action is deliberately
  deferred (non-goal). The loop still improves the model immediately through
  the `curation_rating` label signal; pair rules land as a follow-up package
  and consume the same `get_curation_verdict` suggestion.

## Verification plan

- Per package: `scripts/verify changed <paths>` while iterating;
  `scripts/verify full` before handoff; `git diff`/`git status` review.
- Installed verification (after user updates the plugin): reproduce a
  hypothesis batch and an explore batch cold + steady state, submit ratings,
  confirm verdict math by hand, check Stash logs/task progress, desktop +
  mobile layout, SFW Switch.
- No commits/pushes unless explicitly requested; Conventional Commits subjects
  on merge.

## Open decisions (resolved in implementation)

1. `curation_rating_confidence = 0.8` — config-backed; tune after first live
   batch (a config change invalidates the model fingerprint, so it is safe).
2. Confirmation thresholds (`|delta| >= 0.15`, `n_total >= 10`) — module
   constants in both implementations; tuning them needs no migration.
3. Budget cap 40 — enforced in the migration CHECK and the op validation.
4. Exploration anchors: 3 per batch; re-rated known-outcome anchors for
   scale-drift detection deferred to v2.
