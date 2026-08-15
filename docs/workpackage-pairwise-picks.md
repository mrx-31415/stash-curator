# Workpackage: Pairwise picks (ELO-style comparison + smooth decomposition)

Status: planned. Builds on the curation loop
(`docs/workpackage-curation-loop.md`, shipped): the new piece is a "Pick"
interaction where the user compares two scenes (left/right) instead of rating
them, plus the pair-selection and label-conversion machinery that turns those
comparisons into model signal with smooth, matching-free decomposition.

## Goal

A "Pick" tab in Curate: short rounds of two-card comparisons ("which do you
prefer?") that generate preference labels for the model and win-rate verdicts
for hypotheses. The design commits to three principles decided in review:

1. **No discrete matching cases.** Performer-matched, tag-matched, and random
   pairs are all valid; the model decomposes the signal smoothly. The ±1
   winner/loser conversion is algebraically the Bradley–Terry logistic pairwise
   objective's gradient: for a pair sharing feature `f`, the winner's `+w` and
   loser's `−w` cancel in the affinity accumulation; a feature only in the
   winner gets `+w`, only in the loser gets `−w`. So each comparison updates
   feature affinities in proportion to the *difference* between the scenes —
   the degree of orthogonality is a soft knob (where signal concentrates), not
   a mechanism.
2. **Smart selection, bias-corrected.** Pairs are chosen for information
   (model-conflict first, coverage of under-tested features), and the
   selection bias is corrected with inverse-propensity weighting: each
   comparison is reweighted by `1/selection_probability` (capped), and the
   generator stores its own selection probabilities.
3. **Model-grounded, surprise-weighted confidence.** Each pick's label
   confidence is higher when the pick *contradicts* the model's predicted
   ordering (disagreement with strong prior evidence), lower when it confirms.
   Magnitude comes from the model's absolute scale, not the user's number
   usage. Ratings remain the absolute anchors — picks never replace them.

ELO is explicitly NOT a model input: it is an optional lightweight
selection-steering score. The v1 proxy for it is the model's predicted appeal
gap (conflict scoring), which is what ELO would approximate anyway.

Non-goals: replacing the rating flow (ratings stay for exploration + scale
anchors; the hypothesis-rating form may retire later once picks prove out,
but that is a separate cleanup), learned conditional affinities (option 5),
term-level picks, write-back to Stash (read-only live access).

## Architecture context

- Every op is dual-implemented (Go binary = runtime, Python = differential
  oracle) with byte-identical differential tests, as in the curation loop.
- Migrations: one new ordered migration (next number: **0030**), mirrored
  byte-identical in `core/migrations/` and `curator/storage/sql/`.
- The model-build label fingerprint gains `payload_json` in its feedback-state
  list (Py + Go): pair label confidence depends on per-pick payload values, so
  the fingerprint must cover them. This changes the fingerprint for every
  build once (model reuse invalidated once), then stabilizes.
- New calibration constants are config-backed (`ModelConfig` + Go
  `modelSubConfig`) so the canonical-config fingerprint guards them: changing
  them invalidates models.

## Package: backend

### Migration 0030: `curation_pair` (+ optional `curation_pair_elo`)

```sql
CREATE TABLE curation_pair (
    pair_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,              -- one generation call = one round
    scene_a TEXT NOT NULL,
    scene_b TEXT NOT NULL,
    dimension TEXT NOT NULL
        CHECK (dimension IN ('tag', 'performer', 'studio', 'orthogonal')),
    selection_probability REAL NOT NULL CHECK (selection_probability > 0 AND selection_probability <= 1),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'skipped', 'superseded')),
    winner TEXT CHECK (winner IN ('a', 'b')),
    occurred_at_ms INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}'
        -- {predicted_a, predicted_b, base_tag_id?, context_tag_id?,
        --  performer_id?, coverage_score}
) STRICT;

CREATE TABLE curation_pair_elo (
    scene_id TEXT PRIMARY KEY,
    elo REAL NOT NULL,
    updated_at_ms INTEGER NOT NULL
) STRICT;
```

`curation_pair_elo` is optional steering state (updated on submit, K-factor
16, used only by pair selection). It can be dropped from v1 without touching
the conversion; the doc keeps it because the reviewer asked for ELO framing.

History: picks are immutable once answered; corrections reuse the `feedback`
reversal pattern (a reversed pair label is excluded by `reversed_by_id`).

### Ops (Go + Python oracle + differential tests)

All selection deterministic (ORDER BY, tie-breaks, no RNG).

**`get_curation_picks`** — request:

```json
{ "budget": 10,                     // pairs per round, 4..20, default 10
  "dimension": "tag",               // tag | performer | studio | orthogonal
  "base_tag_id": 228,               // tag dimension only (optional)
  "context_tag_id": 1309,           // tag dimension only (optional)
  "performer_id": "p1" }            // performer dimension only (optional)
```

Response:

```json
{ "round_id": "…", "dimension": "tag",
  "pairs": [ { "pair_id": "…",
               "scene_a": { "scene_id": "1001", "title": "…", "studio": "…",
                            "date": "…", "tags": [ {"name": "…", "category": "…"} ] },
               "scene_b": { … },
               "predicted_a": 0.31, "predicted_b": 0.28,
               "selection_probability": 0.042 } ],
  "policy": "conflict-first + coverage, dimension prior tag, IPS-corrected" }
```

Selection policy (deterministic):

1. **Candidate pool** by dimension:
   - `tag`: pairs across the hypothesis cells (base×context 2×2); when the
     request names base/context tags. A shared-performer pair is preferred but
     never required (soft prior, weight below).
   - `performer`: pairs sharing ≥1 tag, differing performers (the
     tag-matched performer signal).
   - `studio`: pairs differing studio, otherwise similar.
   - `orthogonal`: any pair from the unlabeled pool (max-coverage reuse).
2. **Information score** per candidate pair:
   `score = conflict × coverage × dimension_fit`
   - `conflict = 1 / (1 + |predA − predB|)` — near-tied model predictions are
     most informative (use the published model's `general_appeal`; missing
     model → 1.0).
   - `coverage` — rarity-weighted novelty of the pair's feature *difference*
     (tags/performers in the symmetric difference), reusing the exploration
     rarity weights; prefers pairs that exercise under-tested combinations.
   - `dimension_fit = 1 + 0.5 × shared(performer|tag|studio)` for the
     requested dimension — the soft matching prior, never a hard filter.
3. **Selection + propensity**: normalize scores across candidates; the chosen
   pair's `selection_probability` = its normalized share (softmax-approx; the
   approximation is documented and the same in both implementations).
4. **Diversity**: a scene appears in at most 2 pairs per round; capped pairs.

**`submit_curation_picks`** — request:

```json
{ "round_id": "…",
  "picks": [ { "pair_id": "…", "winner": "a" | "b" | "skip" } ] }
```

Validation mirrors `submit_curation_ratings`: round exists and open, pair in
round, winner valid, no duplicates, no re-answers. Writes, per answered pair,
two feedback rows (transactionally):

- `curation_pair_winner`, value `'10'` → outcome +1
- `curation_pair_loser`, value `'0'` → outcome −1

both with `payload_json = {"pair_id", "round_id", "dimension",
"predicted_winner", "predicted_loser", "selection_probability"}` — the
predicted values are aligned to the winner/loser sides at submit time (the
label builder cannot know which scene was "a"), and the confidence is computed
at build, not submit. `skip` marks the pair `skipped` with no labels. Updates
`curation_pair_elo` (optional table) and the pair status; round `status`
follows the batch pattern (`open` → `answered`).

**`get_curation_pair_verdict`** — request `{ "round_id": "…" }`. Response by
dimension:

- `tag`: per-cell win rates over the hypothesis cells (wins in L&T vs wins in
  L&!T, and the contrast = win-share difference), plus n answered. No
  confidence thresholds beyond n ≥ 8.
- `performer`: per-performer win rates (wins when the performer was on the
  winning side / total appearances), top/bottom.
- `orthogonal`: overall win balance + top tags by win-share (like the explore
  verdict but from picks).

### Label conversion (model build, Py + Go)

New signal sources in `_scene_labels` / `modelSceneLabels`:

- `curation_pair_winner`: outcome +1, `curation_pair_loser`: outcome −1.
- Per-pair confidence, computed at build from the payload:

```
surprise    = max(0, pred_loser − pred_winner)     # pick contradicts model
confidence  = base × (1 + surprise_bonus × surprise)
              × min(ips_cap, 1 / selection_probability)
clamped to [0, 1]
```

with defaults `curation_pair_confidence = 0.5`, `curation_pair_surprise_bonus
= 2.0`, `curation_pair_ips_cap = 4.0` (config-backed, ModelConfig + Go
`modelSubConfig`). `reversed_by_id IS NOT NULL` rows are excluded, as for all
feedback signals.

**Acceptance property (the smooth decomposition, pinned by tests):** in the
affinity accumulator, a pair sharing feature `f` contributes `+w − w = 0` to
`f`; a feature only on the winner contributes `+w`, only on the loser `−w`.
This must hold regardless of dimension — matching only concentrates signal.
Unit test: two scenes sharing tags T1 (shared) and T2 (winner-only), T3
(loser-only) → T1 net 0, T2 +w, T3 −w in the affinity inputs.

Fingerprint: the evidence fingerprint's `feedback_state` list gains
`payload_json` (Py + Go) so pair payloads are covered.

### Package tests

- Differential (`tests/core/test_backend_slice6_pairs.py`): all three ops,
  success + error paths, determinism (two identical calls byte-identical),
  all four dimensions, budget bounds, skip handling, re-answer errors,
  verdict per dimension.
- Unit (`tests/curation/test_pairs.py`): the cancellation property above,
  conflict/coverage/dimension_fit scoring, propensity normalization,
  surprise/IPS confidence math (contradict vs confirm), selection
  determinism, diversity cap.
- Model-build differential with pair rows present; fingerprint change tests
  (payload in feedback_state) for both implementations.
- Migration ordering/mirror; `scripts/verify full` once near completion.

## Package: frontend

Third tab in Curate: **Scene batches | Pick | Tag sentiment** (the existing
tab bar grows one entry; `curateTab` state gains `"pick"`).

**Round setup** (reuse the suggestion flow): for tag dimension — the
suggested-hypotheses cards get a "Pick-test" action next to Generate (same
base/context); for performer — a performer search; for orthogonal — one click.

**Pick view**: two scene cards side by side (reuse `CurationSceneCard` media
+ title/studio/date/tags; the rating strip is hidden — this is a comparison,
not a rating), a left/right choice, plus **Skip** and **Similar** (tie) —
similar records no labels. Progress "x/10", and a running tally ("you've
chosen left 6, right 3"). Submit → `submit_curation_picks`, then the
per-dimension verdict (win-rate bars).

Interaction rules: keyboard (←/→ to pick), mobile-tap on either card, ARIA
(`aria-pressed` on the choice, live region for the tally). SFW Switch
contract unchanged: controls outside `card-section`.

## Sequencing

Phase 1 — storage + ops (migration 0030, `get_curation_picks` with the full
selection policy, `submit_curation_picks`, `get_curation_pair_verdict`,
differential + unit tests). No model change yet: rounds produce data.
Phase 2 — label conversion (new feedback types, surprise/IPS confidence,
fingerprint payload, Py + Go, model-build differential).
Phase 3 — frontend Pick tab + runtime tests.
Phase 4 (optional) — `curation_pair_elo` steering + hypothesis-rating form
retirement review.

Phases 1–3 are each independently shippable; 1 can land without 2 (data
collects; labels start on 2's merge).

## Verification plan

- Per phase: `scripts/verify changed <paths>`; `scripts/verify full` before
  handoff.
- Installed verification (after the user updates the plugin): run a tag-
  dimension round on lesbian×threesome (BGG), a performer round, an orthogonal
  round; confirm the verdict win rates match the raw pick counts; confirm the
  model build picks up the pair labels (label count in the build output);
  check that a pair with shared tags shows zero net movement on the shared
  tag's affinity (the cancellation property on live data); desktop + mobile
  layout; SFW Switch.

## Open decisions (defaults chosen)

1. `curation_pair_confidence = 0.5`, `surprise_bonus = 2.0`, `ips_cap = 4.0`
   — config-backed, tune after the first live rounds.
2. `selection_probability` uses a softmax-approx normalized score; exact
   greedy selection probabilities are not computed (documented approximation,
   mirrored in both implementations).
3. ELO steering is optional (Phase 4); predicted-appeal conflict is the v1
   proxy.
4. "Similar" (tie) records no labels in v1; a tie may become a low-confidence
   ±ε pair in v2.
5. Per-scene pair cap 2 per round; revisit if verdicts need more depth per
   scene.
