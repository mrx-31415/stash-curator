# Planning: score presentation overhaul (#119, #122)

Status: **Plan only** — this change carries no code. Decision record for the
score-comprehension overhaul: issue #119 (a scene's displayed "Score" and
"Why this?" change meaning across lanes and tabs) and issue #122 (the number
labeled "Score" is not one thing, and the disclosure is a raw float tree).
Complements the runtime-swap record (002); the implementation slices and
rollout order are specified in sections 9–11.

Updated: 2026-08-12.

## 1. Goals restated

- One comprehensible score presentation: **consistent meaning across
  surfaces** for the same scene, a plain-language component breakdown
  (content similarity, performer match, studio appeal, direct feedback,
  novelty), a visible scale, and **real units instead of raw floats**.
- Fix the concrete #119 inconsistency: the same scene appears in several
  lanes (adventure is unconditional — `curator/ranking/policy.py:17` and the
  classify loop always append an adventure row) with a different
  lane-specific `final_utility`, and no card says the number is
  lane-relative; meanwhile the four "why" surfaces use four different
  explanation mechanisms.
- Keep every model value untouched. This is a **presentation + API-shape**
  plan: relabel, re-scale, re-render; do not change scoring, ranking, or
  stored artifacts.

## 2. Current state (grounded inventory)

### 2.1 Score surfaces

| Surface | Location | Number shown | What it actually is | Scale |
| --- | --- | --- | --- | --- |
| Recommendation card header | `plugin/stash-curator.js:1215` | `Score · ${item.final_utility.toFixed(2)}` | `final_utility` = `lane_value + Σbonuses − Σpenalties` (`core/slate.go:522`, `curator/ranking/slate.py:1231-1233`); `live_cooldown` penalty injected at read time (`core/slate.go:494`); diversity bonus only when varied (`curator/ranking/slate.py:248-251`) | **unbounded** (lane_value is 0..1 percentile blend, penalties/bonuses push it negative or >1) |
| — lane_value blends | `curator/ranking/policy.py:143-170, 205, 232, 249-255` | (not shown) | best_bets: `0.55·relevance + 0.25·fit_rank + 0.20·confidence`, where relevance itself is `(0.32·neighbor + 0.10·similarity + 0.28·performer + 0.20·content + 0.10·studio) · (0.90 + 0.10·metadata_confidence)`; revisit: `direct_appeal·direct_confidence·recovery + 0.25·current_fit`; discover: `current_fit + 0.12·(1−confidence) + 0.5·strongest_anchor`; adventure: `0.38·coverage_rank + 0.25·distance_rank + 0.17·unknown_performer_share + 0.08·unknown_studio + 0.12·metadata_confidence` | 0..1 percentile ranks |
| Recommendation disclosure | `plugin/stash-curator.js:1216-1221`, `ScoreNode` at `:437-461` | `appeal / current_fit / confidence / components / diversity_penalties / diversity_bonuses` | raw recursive float tree; snake_case keys title-cased (`name.replaceAll("_", " ")`), `toFixed(3)`, no units, no scale, no sign styling | mixed: appeal −1..1 (`migrations/0003_recommendation_state.sql:20` CHECK), current_fit −1..1, confidence 0..1, components each `{raw, value (clamped), evidence_confidence}` (`core/modelbuild2.go:770-905`) |
| Similar card (library) | `plugin/stash-curator.js:1593`; `scoreBar` at `:806-818` | `Score · ${item.rank_score.toFixed(2)}` plus `Similarity ${item.similarity} · predicted appeal ${item.appeal}` | `rank_score = 0.7·similarity + 0.3·appeal` where `appeal = (candidate_appeal + 1) / 2` (`core/similar.go:703-704`) — **a third blend**, and `scoreBar` normalizes segment widths by their sum, hiding absolute magnitude (`:812`) | 0..1 |
| Expand / StashDB / hunt card | `plugin/stash-curator.js:910` | `Score · ${item.score.toFixed(2)}` + `Match ${item.score} · found via ${sources}` or `Similarity … · appeal … + multi-hop` | local re-scoring of StashDB candidates: `0.40·tag + 0.10·term + 0.25·identity + 0.10·studio + 0.15·similarity` (+0.05 multi-hop; see `docs/handover.md` #95, `core/expand.go`) — **a fourth scale** | ~0..1 |
| Recommendation history row | `plugin/stash-curator.js:1254-1257` | no number; "Reason shown" = `item.reason_snapshot.map(reasonLabel).join(" · ")` | the snapshot is lane/eligibility/diversity codes persisted at impression time (`core/slate.go:499-511`, `core/history.go:55-99`) — not appeal reasons | n/a |
| Lane help copy | `plugin/stash-curator.js:2679` | text | `"The colored corner icon identifies the source lane; Score is ranking utility, not a probability."` | — |

### 2.2 Why-explanation sources (four, all different)

| Surface | Mechanism | Content |
| --- | --- | --- |
| Recommendation card | `get_explanation` op on `<details>` toggle (`plugin/stash-curator.js:1195-1198`) | `{schema_version, model_id, scene_id, summary, reasons, supporting_reasons}` (`core/explanations.go:947-954`); JS renders `explanation.summary` prose + a `reasonLabel(code) (magnitude.toFixed(2))` list (`:1202-1211`) |
| Similar (library) | `relationshipChips(item)` (`plugin/stash-curator.js:1536-1550`) | chips from `item.relationships` (`same_performer`, `similar_performer`, `shared_content`, `similar_structure`, `same_studio`, `multi_hop` — `core/similar.go:690-736`) + `details.shared_tags`; **no magnitudes, no prose** |
| Expand / StashDB | `payload.why.join(" · ")` (`plugin/stash-curator.js:910`) | string array from `expandWhy` (top-3 tags + top-2 terms + identity/similarity + cast note; `core/expand.go:268-306`, mirror `curator/expand.py:2143+`) or performer/studio phrases (`core/expand_similar.go:2003-2019`) |
| History | "Reason shown" codes vs "Why this now?" → `get_explanation` (`plugin/stash-curator.js:1250-1257`) | the snapshot codes (`eligibility.lane`, `diversity.<penalty>`) are **not** the current-model appeal reasons, so the two cells answer different questions |

### 2.3 Structural findings (evidence)

1. **`appeal` is the only lane/surface-invariant quantity for a local scene.**
   `model_scene_score.appeal` (−1..1, `core/modelbuild2.go:828`, `blendAppealOf` at `:55-58`) is carried verbatim into slate items
   (`core/slate.go:518`), Similar items (`core/similar.go:703` — though
   immediately rescaled), and lane rows (migration `0011_lane_appeal.sql`).
   `final_utility`, `rank_score`, and the expand `Match` are three different
   derived blends.
2. **The recommendation card mixes a lane-relative header with a
   lane-agnostic "why".** `get_explanation` takes only `scene_id`
   (`core/explanations.go:903-915`), so the prose never varies by lane, while
   the `Score` header is `final_utility` for the *current* lane. History's
   "Reason shown" is lane-specific but the "Why this now?" is not — the
   exact mismatch #119 describes.
3. **`reasonLabel` maps only 2 of ~12 reason codes** (`plugin/stash-curator.js:462-470`:
   `appeal.performer_identity`, `appeal.content_neighbor`; the rest fall back to a
   title-cased last segment). The real code inventory is
   `direct.positive/.negative/.residual`, `appeal.performer_identity`,
   `appeal.performer_similar`, `appeal.studio`, `appeal.content_neighbor`,
   `appeal.tag_positive/.negative`, `appeal.tag_declared_positive/.negative`,
   `fit.cooldown/.satiation/.not_now` (`core/explanations.go:420-429, 487-523, 693-777, 786-811`;
   priorities in `core/explanations_render.go:20-28`).
4. **Slate items already tolerate inline explanation fields the backend never
   emits** (`plugin/stash-curator.js:1109-1112` seeds the card from
   `item.explanation`/`item.supporting_reasons` if present) — a free
   forward-compat hook for phase B.
5. **Component vocabulary is fixed at build time.** `components_json` families
   are `content, structure, performer_identity, performer_similarity, studio,
   content_neighbor` plus `direct {value, confidence, effective_evidence,
   signals, residual}` and `fit {cooldown, satiation, not_now, recovery}`
   (`core/modelbuild2.go:850-899`). There is **no "novelty" component**: what
   reads as novelty lives in the adventure/discover lane context
   (`coverage_gap_percentile`, `content_distance_percentile`,
   `unknown_performer_share`, `unknown_studio` —
   `curator/ranking/policy.py:262-270`).
6. **Reports already model the target presentation**: `reports/calibration-v2.html`
   shows `Appeal +0.617`, `Current Fit +0.594` — signed, labeled, bounded
   numbers; and the prose reports show prose + a "Supporting evidence"
   disclosure.

## 3. Decision: unified score semantics — two labeled quantities

On **every** card that has a score, show the scene's intrinsic **Appeal**
and, separately and clearly labeled, the surface-specific relative quantity:

1. **Appeal** — `model_scene_score.appeal`, scale **−1..1**, signed display
   (report precedent: `Appeal +0.617`), identical for the same scene on every
   surface and every lane. This is the canonical intrinsic quantity.
2. **Lane utility** — `final_utility`, shown **only where a lane exists**
   (recommendation lanes), labeled with the lane name and its relative
   nature: `Rank in Best Bets · 0.81` (scale 0..1 percentile basis), and
   never bare "Score". Where no lane exists, the surface's own relative
   quantity keeps its own label:
   - Similar: `Similarity 0.71` (0..1) + `Appeal +0.40` — drop the blended
     `Score · rank_score` header or relabel it explicitly as the
     `0.7·similarity + 0.3·appeal` blend; the parts are already on the card.
   - Expand: `Match 0.66` (0..1) + `found via …` as provenance chips (a
     reason list, not a number).
   - History: no score numbers; the two "why" cells become consistent under
     section 4.

Concretely the recommendation summary becomes, e.g.,
`Appeal +0.62 (−1..1) · Rank in Best Bets 0.81 (0..1, lane-relative)`, with
the two values in separate labeled spans. The `final_utility` number remains
available in the disclosure for power users (see §5) but is never the
headline.

**Migration of the old copy** (`plugin/stash-curator.js:2679`): replace
"Score is ranking utility, not a probability" with copy that names both
quantities, e.g. "Appeal is the model's estimate of how much you'll like the
scene, on a −1..1 scale. The rank number is this lane's ordering utility
(0..1), not a probability."

## 4. Decision: one explanation schema across surfaces

One schema everywhere:

```jsonc
{
  "summary": "prose",                 // existing prose (get_explanation.summary)
  "components": [                     // NEW: named, scaled breakdown
    {"name": "content_similarity", "label": "Content similarity",
     "value": 0.18, "scale": "0..1", "direction": "positive",
     "detail": "similar to Scene X (0.89)"}
  ],
  "reasons": [{"code": "...", "magnitude": 0.123, ...}]  // existing, kept
}
```

- **Backend**: `get_explanation` gains a `components` array derived from the
  same reasons/score row (`core/explanations.go:923-955` renders the summary
  today; add a reason→component mapper beside `explanations_render.go`'s
  planner). Expand items gain `explanation` `{summary, components}` alongside
  the existing `why` (provenance) (`core/expand.go:268-306`,
  `core/expand_similar.go`); Similar items gain `explanation` components from
  the relationship/breakdown data already computed (`core/similar.go:703-736`).
  `reasonLabel`'s two-entry map grows to the full code inventory
  (`plugin/stash-curator.js:462-470`).
- **Frontend**: one `<Explanation>` renderer (prose summary + component rows)
  replaces the four divergent renderings:
  - Recommendation card list (`:1202-1211`),
  - Similar `relationshipChips` (`:1536-1550`) — chips keep their meaning as
    per-component detail chips inside the matching component row,
  - Expand `payload.why.join(" · ")` (`:910`),
  - History "Reason shown" (`:1254-1257`) — the snapshot codes render through
    the same name map; "Why this now?" is already `get_explanation`.
- **Schema version**: the explanation response shape changes; bump
  `apiSchemaVersion` (`core/ops.go:20`) in the same commit as the shape
  change and keep the frontend tolerant of the old shape during rollout
  (frontend checks for `components` presence — mirrors the existing
  `item.explanation` tolerance at `:1109-1112`).
- **Python mirror**: the compiled core is the single runtime; the Python
  backend is the reference/oracle mirror. The response shape change must land
  in both sides with byte-identical differential coverage
  (`tests/core/test_backend_slice1.py:360-369` is the existing
  `get_explanation` differential pattern).

## 5. Decision: plain-language component breakdown (ScoreNode replacement)

Replace `ScoreNode` (`plugin/stash-curator.js:437-461`) with a
`ScoreBreakdown` component rendering **named rows, each with a visible 0..1
bar, signed value, and unit**, mapped from the real model data:

| Row (plain language) | Source (grounded) | Scale |
| --- | --- | --- |
| Content similarity | `components.content` + `components.content_neighbor` clamped values (`core/modelbuild2.go:770-905`) | −1..1, bar 0..1 |
| Performer match | `components.performer_identity` + `performer_similarity` | −1..1 |
| Studio appeal | `components.studio.value` | −0.12..0.12 clamp → displayed 0..1 |
| Direct feedback | `components.direct.value` with `confidence`/`effective_evidence` as detail (`:880-886`) | −1..1 |
| Novelty | **not a model component** — derived from lane context only: adventure/discover `coverage_gap_percentile`, `content_distance_percentile`, `unknown_performer_share`, `unknown_studio` (`curator/ranking/policy.py:262-270`); shown only when the lane provides it, labeled "relative to your library" | 0..1 |
| Right now (fit) | `components.fit` cooldown/satiation/not_now (`core/modelbuild2.go:887-899`) — explains an Appeal/Current-fit gap | 0..1 deductions |
| Model confidence | `confidence` (0..1) as a footnote bar | 0..1 |

- The **raw float tree** (internals like `raw`, `evidence_confidence`,
  `studios`, `signals`, `residual`) moves behind a second, collapsible
  "Technical details" disclosure for diagnostics — or is dropped from cards
  entirely (Prune/Diagnostics keep raw numbers where they belong).
- `final_utility`, `lane_value`, `penalties`, `bonuses` stay available in the
  disclosure, labeled and unit-tagged, never as the headline.
- Reuse the existing segment styling (`curator-score-bar` /
  `curator-score-sim/app/mh`, `:806-818`) and the sentiment color classes
  (`curator-sentiment-*`, `:471-481`) for sign coloring; new styles go in
  `plugin/stash-curator.css`.

## 6. Units and scale policy (every number on a card)

| Quantity | Label | Scale | Display |
| --- | --- | --- | --- |
| Appeal | `Appeal` | −1..1 | signed `+0.62` / `−0.31`, color-coded |
| Lane rank | `Rank in <Lane>` | 0..1 | `0.81 of 0–1`, always with the lane name |
| Similarity | `Similarity` | 0..1 | 2 decimals, bar |
| Match (Expand) | `Match` | 0..1 | 2 decimals |
| Confidence | `Model confidence` | 0..1 | percent |
| Multi-hop | `Multi-hop` | 0..1 | 2 decimals, only when > 0 |
| Component rows | as in §5 | declared per row | bar + signed value |

No number is shown without its unit/scale and, where it is lane- or
list-relative, its frame of reference.

## 7. Fit with #120 (score-review view, in progress)

#120 (agent `fix120`) adds a score-review op (`core/score_review.go` new) that
surfaces the **bottom of the same appeal distribution** — i.e. it reads
`model_scene_score.appeal`/`confidence` (the same `model_scene_score_prune_idx`
index shape as Prune, `core/build_artifacts.go:217`). Constraints this plan
honors, and which #120 must honor back:

- `appeal` remains the canonical intrinsic quantity; the overhaul only
  relabels/re-bars presentation and never changes values, so #120's op and
  this plan are value-compatible by construction.
- The `ScoreBreakdown` renderer (§5) must be a shared component the
  score-review view reuses instead of a second renderer — extract it in phase
  A (§11) so #120 can consume it.
- The explanation schema (§4) is additive (`components` beside `reasons`);
  #120's op can adopt it without rework.

## 8. Non-goals

- No scoring/ranking/model changes; no artifact-schema changes (the optional
  history-snapshot extension in §9 is explicitly out of the critical path).
- No new model component for "novelty" — it is a derived display, never a
  stored model value (do not let it be mistaken for one; §5/§12).
- No change to the Prune/Diagnostics raw-number views.
- No change to `relationshipChips` semantics beyond rendering them through the
  shared schema.

## 9. File/symbol-level change list

Phase A — **frontend only** (no rebuild, plugin zip only):

- `plugin/stash-curator.js`
  - `RecommendationCard` summary (`:1215`): split into labeled Appeal + lane
    rank spans; keep `final_utility` in the disclosure.
  - `ScoreNode` (`:437-461`) → `ScoreBreakdown` (§5); `scoreBar` (`:806-818`)
    reused/adapted; `reasonLabel` (`:462-470`) → full code→name map.
  - `SimilarityPanel` card body (`:1593`): drop/re-label blended
    `Score · rank_score`; render `Similarity`/`Appeal` and shared
    `<Explanation>`; `relationshipChips` (`:1536-1550`) becomes detail chips.
  - `ExternalCard` (`:910`): `Score · item.score` header re-labeled `Match`
    (0..1) when it is a match score; `found via` stays provenance;
    `payload.why` renders through `<Explanation>`.
  - `RecommendationHistoryRow` (`:1254-1257`): render snapshot codes through
    the same label map.
  - Lane copy (`:2679`): new two-quantity copy (§3).
- `plugin/stash-curator.css`: bars/labels/scale styles.
- `tests/plugin/test_runtime.py` — update the source-pinning assertions that
  pin the old markup: `:412-414` (history labels), `:633-637`
  (`Score · ${item.score.toFixed(2)}` and `Score · ${item.rank_score.toFixed(2)}`
  summaries), `:644-646` (the "Score is ranking utility" copy and the
  two-entry reasonLabel map). Note: at plan time `:636` still matches the
  ExternalCard header, and the RecommendationCard `final_utility` summary is
  unpinned — add pins for the new labeled headers.

Phase B — **backend explanation schema**:

- `core/explanations.go`: `renderExplanationForScene` (`:923-955`) gains
  `components`; reason→component mapper.
- `core/explanations_render.go`: mapper + any new catalog positions
  (`realizations.json` lives in the shipped resource; keep variant text in
  lockstep — `:236-247`).
- `core/ops.go:20`: bump `apiSchemaVersion` with the shape change.
- `core/similar.go`: emit raw appeal (`:703` keeps the rescale for the field;
  add the raw −1..1 value for the card) + `explanation` components from
  `relationships`/`details.score_breakdown` (`:703-736`).
- `core/expand.go` (`expandWhy` `:268-306`) + `core/expand_similar.go`
  (`:2003-2019`): emit `explanation {summary, components}` beside `why`.
- Python mirror (reference only): `curator/api.py` explanation method,
  `curator/expand.py` `_why` (`:2143+`), `curator/ranking/slate.py` similar
  item dict (`:1014-1022` shape) — byte-identical differential coverage.
- Optional (out of critical path): extend the history snapshot
  (`impression_item.reason_snapshot_json`, `core/history.go:55-99`) to include
  the appeal/final_utility shown at impression time, with a migration.

## 10. Test plan

Existing anchors that must stay green or be extended:

- `tests/ranking/test_slate.py:723-727` — item key inventory incl.
  `lane_value`, `final_utility`, `components`.
- `tests/test_api.py:364-368` — `rank_score = 0.7·similarity + 0.3·appeal`
  on Similar items; `:52-53` — explanation summary/supporting_reasons present.
- `tests/model/test_multi_hop.py:257-261` — multi-hop rank blend.
- `tests/core/test_backend_slice1.py:360-369` — byte-identical
  `get_explanation` differential (core vs Python oracle).
- `tests/plugin/test_runtime.py:412-414, 633-637, 644-646` — source pins to
  migrate (§9).

New synthetic-corpus assertions:

1. **Lane invariance of Appeal**: for a seeded corpus, the same scene across
   lanes (best_bets/adventure/discover/revisit) reports identical `appeal`
   while `lane_value`/`final_utility` differ — extend `tests/ranking/test_slate.py`
   (or `tests/core/test_backend_slice3_*.py`).
2. **Explanation schema**: every surface's explanation has `summary` +
   `components`, component names come from the fixed vocabulary, and values
   are within the declared scales — extend `tests/test_api.py`.
3. **Expand Match scale**: `Match` ∈ 0..1 and `why`/explanation components
   reflect the 0.40/0.10/0.25/0.10/0.15 weights — extend `tests/test_expand.py`.
4. **Differential**: extended `get_explanation` (with `components`) is
   byte-identical between core and Python oracle (`tests/core/test_backend_slice1.py`
   pattern).
5. **Frontend pins**: `test_runtime.py` asserts the new labeled headers
   (`Appeal`, `Rank in <Lane>`), the `ScoreBreakdown` rows, and the new lane
   copy.

Browser verification on the synthetic docker corpus (`integration-stash-1`,
http://localhost:9998): open the same scene in Best Bets and Adventure and
assert the Appeal matches while the rank labels differ; open Similar and
Expand for the same scene; screenshot evidence; assert every visible number
carries a unit/scale label.

## 11. Rollout order

1. **Phase A — frontend only** (relabels, `ScoreBreakdown`, shared
   `<Explanation>`, copy migration, `test_runtime.py` pins). Ships as a
   plugin-only release; no model rebuild; verifiable against the existing
   payloads immediately. The shared renderers land here so #120 can consume
   them.
2. **Phase B — backend explanation schema** (`components` in
   `get_explanation`, similar raw appeal, expand `explanation`), Python
   mirror, `apiSchemaVersion` bump, differential gates; requires
   `scripts/build_core.sh` and the `scripts/verify core` gates. Frontend
   tolerates the old shape during the overlap window.
3. **Optional** — history snapshot extension with migration.

## 12. Risks and the decision the reviewer must weigh most carefully

- **The headline question:** whether the single blended "Score" number should
  effectively disappear in favor of two labeled quantities (Appeal + lane
  rank) on recommendation cards, and whether the Similar card's blended
  `rank_score` (0.7·similarity + 0.3·appeal, `core/similar.go:704`) is kept
  under an explicit label or dropped in favor of its already-shown parts.
  This changes what users compare across cards and is the one irreversible
  UX decision here — the recommendation is: **keep both quantities but always
  labeled; never a bare "Score"**. That directly satisfies #119's ask
  ("always show the scene's intrinsic appeal plus the lane utility as a
  separate, clearly-labeled quantity").
- **Novelty must not become a fake model number**: it is lane-context-derived
  only; display it solely where the lane computes it and label it
  "relative to your library" (§5).
- **Shape change discipline**: `get_explanation` shape change needs the
  `apiSchemaVersion` bump + differential updates in the same commit; ship
  phases A and B atomically in one plugin release if the tolerance window is
  judged too risky (the plugin ships as one zip, so atomicity is cheap).
- **#120 interlock**: the shared `ScoreBreakdown`/`<Explanation>` extraction
  in Phase A is the sequencing dependency both ways.
- **Pre-existing condition observed while planning:** `tests/plugin/test_runtime.py:636`
  pins the ExternalCard `Score · ${item.score.toFixed(2)}` header (still
  valid at plan time), while the RecommendationCard's `final_utility` header
  (`:1215`) is unpinned — Phase A must add pins for both new headers.

## 13. References

- Issues #119, #122 (this plan), #120 (score-review, in progress).
- `docs/decisions/002-runtime-swap-planning.md` (format and differential
  equality policy), `docs/handover.md` (slice 4 deliverable notes, #95 expand
  weights).
- Grounding reads: `plugin/stash-curator.js:437-470, 806-818, 910, 1109-1218,
  1235-1262, 1536-1550, 1593, 2679`; `core/explanations.go`,
  `core/explanations_render.go`, `core/laneclassify.go`, `core/slate.go`,
  `core/similar.go:690-736`, `core/expand.go:260-306`,
  `core/expand_similar.go:2000-2020`, `core/modelbuild2.go:820-905`,
  `core/history.go:55-100`, `core/ops.go:20`;
  `curator/ranking/slate.py:80-88, 248-251, 1014-1022, 1231-1233`,
  `curator/ranking/policy.py:17, 143-170, 205, 232, 249-270`,
  `curator/expand.py:2143+`.
