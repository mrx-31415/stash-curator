# Workpackage: Lane redesign (intent-shaped recommendation lanes)

Status: proposed. Supersedes the current four-lane policy in
`curator/ranking/policy.py` / `core/laneclassify.go`. Best Bets and Revisit
survive essentially unchanged; Discover and Adventure are replaced.

## Goal

Make each lane answer a distinct *reason the user would click it*, rather than
a distinct band on one confidence score. Today the four lanes sit on a single
axis — evidence strength, high to low — so Best Bets → Discover → Adventure is
a threshold ramp on the same quantity. That is why the bottom two blur
together: they are the same idea at different cutoffs.

Non-goals: changing Appeal / Current Fit / Confidence themselves, changing the
variety machinery in the slate builder, replacing the pruning workflow, or
adding new external data sources.

## Evidence

Measured against a real-library model artifact (shares and ratios only; the
absolute corpus is a private instance). Lane membership as a share of eligible
scenes:

| lane | share of eligible scenes |
|---|---|
| adventure | **100%** |
| discover | 71% |
| best_bets | 22% |
| revisit | 0.5% |

**1. Adventure has no qualification gate.** Every eligible scene receives an
adventure row (`policy.py` appends unconditionally, outside any `if`). Best
Bets rejects 78% of the library; Adventure rejects nothing. A lane that admits
everything cannot carry meaning — it is a global sort order presented as a
shelf.

**2. Adventure is blind to whether the user would like the scene.** Its
`lane_value` is `0.38·coverage_gap + 0.25·distance + 0.17·unknown_performers +
0.08·unknown_studio + 0.12·metadata_confidence` — no appeal and no fit term at
all. Its top-200 averages **56% of the library's mean appeal** and **77% of
the library's mean confidence**. It systematically ranks up what the model
likes and knows least.

**3. Its dominant term is a metadata-thinness proxy, not a taste frontier.**
`coverage_gap` is a weighted mean over the scene's content vector, so a scene
with few features gets an unregularized extreme instead of being pulled toward
the base rate by common features. Adventure's top-500 carry **46% as many tags
as the library mean**. The lane surfaces the worst-described files, not the
most interesting regions. This is also why the same lane doubles as the prune
hint — "try this" and "delete this" are opposite actions sharing one shelf.

**4. Discover ranks on fit, not on exploration.** Decomposing
`current_fit + 0.12·(1 − confidence) + 0.5·strongest_anchor` over its top 200:
the fit term supplies **78%** of the value, `strongest_anchor` 19% (and that
is itself a taste signal), and the uncertainty term **1.9%**. Discover is the
set of scenes that just missed the Best Bets corroboration bar, ordered by the
same quantity Best Bets uses.

**5. Discover cannot keep its documented promise.** `docs/recommendations.md`
says it "tests one named uncertainty," but **64% of Discover rows carry
`challenged_assumption: null`** — there is no named uncertainty to render.
Symmetrically, **64% of Adventure's top-200 have `positive_anchors: {}`**:
nothing whatsoever ties them to the user's taste.

**6. Subtypes are unstable enough to mislead.** Between two consecutive model
builds on the same library, `under_covered_island` moved from 4 rows to 6,230,
`anchored_model_gap` from 941 to 55, and `stretch` from 0 to 5,504. The
classifier is a first-match-wins ladder over cliff thresholds, so a rebuild
relabels scenes wholesale. Meanwhile `SlateBuilder._target` rotates through
all five adventure subtypes as though they were balanced buckets.

**7. The framing error underneath all of it.** In a library where the large
majority of scenes are unplayed, "unseen" and "content-distant" are not scarce
and therefore carry almost no discriminating power. The scarce quantities are
*model confidence* and *user attention*. An exploration axis built on
unseen-ness is measuring the wrong thing.

## Reframe: two axes, not one

Each lane is fixed by a pair — *evidence strength* × *relationship to the
user's history* — so no two lanes are separated only by a threshold.

| lane | evidence | relationship to history | user intent |
|---|---|---|---|
| Best Bets | high | adjacent, unseen | "give me a sure thing" |
| Revisit | high | this exact scene, recovered | "give me back something I loved" |
| Stretch | medium | one named dimension changed | "surprise me, but not much" |
| Dormant | high but stale | a taste cluster gone quiet | "what did I drift away from?" |
| Blind Spots | none | unjudgeable region | "help me teach the model" |

## Validation

Every definition below was sampled against an existing published artifact with
a throwaway read-only script before being written down. This was cheap —
`components_json.content.top[]` already carries the per-feature contributions
that Stretch needs, so no migration, model rebuild, or Go work was required to
see real cards. The scripts are not shipped, matching the PoC convention in
`docs/workpackage-curation-loop.md`.

The first pass exposed seven defects in the initial spec, all now folded in:

1. **Stretch ranked on incomparable scales.** The two challenge kinds used
   different distance formulas (`|affinity| * confidence` versus
   `1 - confidence`) compared in one ordering, so `untested` swamped
   `tested_negative` and the lane effectively sorted by *low confidence*.
   Fixed by percentile-normalizing distance **within** kind.
2. **"Content family" was ambiguous, and it dominated the outcome.** The scene
   content vector mixes the `content` family (tag features) with
   `performer_identity` (roughly 3.5x as many features). Unrestricted, Blind
   Spots keyed almost entirely on performer features and silently became
   "performers you have never watched" — which, in a library that is
   overwhelmingly unplayed, is close to the whole library. It admitted 41% of
   eligible scenes; restricting to genuine facet types brought it under 1%.
3. **Sparse scenes re-entered through `representativeness`.** A scene with a
   single content feature scores share 1.0 on it. Fixed with a minimum content
   feature count per scene, not just a share floor.
4. **Dormant had no per-entity cap** — every top card was the same performer.
5. **Technical tags were being named as taste dimensions.** A codec tag
   surfaced as a Stretch challenge because `tag_role` classifies it `content`.
   See the confirmation filter below.
6. **Stretch had no per-dimension cap** — every top card challenged the same
   tag.
7. **The dormancy curve saturates.** Past roughly 250 days every qualified card
   sits at 0.98-1.00, so the term contributed nothing to ordering while
   appearing to. Demoted to a gate; ranking uses `positive_strength * fit_rank`.

A second pass then tested whether the lanes could be made less tag-dependent.
That produced the facet generalization below, plus three measured rejections.

**"Gate share" is the wrong metric for two of these lanes.** Stretch and
Dormant both admit ~30% of eligible scenes, but their per-dimension and
per-entity caps mean the shelf a user actually sees is bounded by the number of
distinct challengeable dimensions and dormant entities respectively. Only Blind
Spots is genuinely gated at the scene level.

## Signal inventory

What the classifier can read today, and where it comes from. This is the
constraint set the lane definitions are built from.

**Per-scene scalars** — `model_scene_score`: `general_appeal`, `direct_appeal`,
`direct_confidence`, `appeal`, `current_fit`, `confidence`,
`metadata_confidence`, `recovery`.

**Component families** — `components_json` carries `baseline`, `content`,
`content_neighbor`, `performer_identity`, `performer_similarity`, `studio`,
`structure`, `direct`, each with a signed `value`. `content` additionally
carries `top[]`: the scene's strongest signed per-feature contributions, each
with `feature_id`, `name`, `affinity`, `confidence`, `value`, and a `metadata`
blob (`tag_id`, `tag_name`, `document_frequency`).

**What classification actually sees is less.** `_classification_payload`
(`curator/model/builder.py:134`) writes a deliberately lean
`classification_json`: the six family `value` scalars plus `direct.signals`.
`top[]` is stripped. This matters — see Stretch.

**Facet sources** (the axes both exploration lanes key on):

| facet type | source | reliability |
|---|---|---|
| studio | `source_scene.studio_id` | one authoritative FK per scene |
| performer attribute | `entity_feature` families `profile:hair`, `profile:ethnicity`, `profile:augmentation`, `profile:eyes`, plus `measurements` / `tattoos` / `piercings` / `age` / `height` | from the performer record, not per-scene tagging |
| era | `source_scene.scene_date`, bucketed | one date field |
| tag | `scene_tag`, filtered — see below | hand-applied multi-label, noisiest |

**Tag confirmation.** `tag_role` classifies tags into `content` /
`performer_attribute` / `workflow_administrative`, but the `content` bucket
includes technical and workflow tags. The usable separator is
`resolution_reason`: tags confirmed against the StashDB taxonomy carry a
`stashdb_unique_name_or_alias:...` resolution, while unconfirmed ones only ever
resolve via the `content_default` fallback — roughly 540 confirmed against
2,900 default-only. **Any tag named to the user as a taste dimension must be
StashDB-confirmed.** This is what keeps codec and workflow tags out of both
lanes, and it needs no new data.

**Per-scene relations** — `model_scene_neighbor` (`neighbor_scene_id`,
`similarity`, `weight`, `outcome`, `rank`), `model_performer_edge`
(`performer_id`, `rank`, `similar_performer_id`).

**Feature-level** — `feature_affinity` (`affinity`, `confidence`,
`effective_support`, `distinct_scene_count`), `entity_feature`,
`feature_definition` (`family`, `name`, `provenance`).

**History** — `source_play`, `play_session`, `source_o`, `feedback`,
`scene_performer`, `scene_tag`, `source_scene.studio_id`, `tag_parent`.

## Facets, not tags

The first draft of both exploration lanes stood entirely on tags — the single
noisiest, sparsest, most tagger-dependent field available. Both lanes are
therefore generalized from *tag* to *facet*, and Blind Spots gains a
corroboration rule.

Measured play-rate spread by facet type, on a real library:

| facet | spread between least- and most-played value |
|---|---|
| era (5-year buckets) | ~20x |
| performer ethnicity | 2.6x |
| performer hair colour | 1.8x |
| performer augmentation | 1.5x |

Dark-region counts at a `darkness >= 0.55`, `library >= 60` bar came out
**studio 25, tag 12, era 1, performer attribute 1** — studio alone more than
doubles what tags supply, from a field that cannot be mis-tagged.

**Corroboration is the reliability mechanism.** A scene qualifies for Blind
Spots only when **two or more independent facet types** are simultaneously
dark. In sampling this produced cards where a studio and two separate tags all
independently flagged the same coherent niche — a far more trustworthy signal
than any single field being sparse. It also buys margin: because a noisy single
facet can no longer qualify alone, the per-facet threshold can be *lower*
without losing precision. Reliability comes from agreement across independent
measurements, not from a stricter bar on one field.

## Proposed lanes

Each lane gives: inputs, the gate, the ranking expression, the
`qualification_json` contract the explanation renders from, and the subtype
rule. All new constants are config-backed in `RankingConfig` with a Go
`modelSubConfig` mirror.

### Best Bets — unchanged

### Revisit — unchanged gate, optional second tier

The existing gate stays. Measured on a real library, the three numeric clauses
admit roughly **six times** as many played scenes as survive the durable-signal
filter (`o`, `thumb_up`, `repeat`, `scene_rating`, `curation_rating`) — that
filter is what makes the lane precise, so it remains the primary tier.

Optional tier 2 admits the numeric-gate-only population, ranked strictly below
every durable-tier row via a constant offset rather than interleaving, with
`tier: "durable" | "numeric"` recorded in `qualification_json`. Motivation is
supply, not quality: `for_you_pattern` requests Revisit in 4 of 20 slots.

### Stretch — replaces Discover

**New property required.** The named challenged dimension does not exist in
what the classifier reads: the data is in `components_json.content.top[]` but
is stripped by `_classification_payload`. Extend that payload to keep a bounded
contributor list — the top `stretch_contributor_count` (default 3) positive and
3 negative contributors, each reduced to `{feature_id, name, value, affinity,
confidence, effective_support}`. This preserves the intent of `258452e`: the
bulk that commit removed was the `metadata` blob and unbounded family detail,
not six small records. Artifact payload change, invalidates cached models once.

**Candidate dimensions.** Tags (StashDB-confirmed only), performer attributes,
and studio. Performer attributes are *preferred* when available: they are
low-cardinality, single-valued, derived from the performer record rather than
per-scene tagging, and immediately legible as "one thing changed."

**Definitions.** Over the scene's contributor list, restricted to confirmed
taste dimensions:

- Anchor set `A` = contributors with `affinity >= stretch_anchor_affinity`
  (0.015) and `confidence >= stretch_anchor_confidence` (0.5).
- Challenge set `C` = contributors that are either
  - *tested negative*: `affinity <= -stretch_anchor_affinity` and
    `confidence >= stretch_anchor_confidence`; or
  - *untested*: `effective_support < stretch_untested_support`.
- `anchor_strength = sum(value for A)`.
- `challenged = argmax(|value|) over C` — **the named dimension**.
- `challenge_distance` = `|affinity| * confidence` for tested-negative,
  `1 - confidence` for untested.

**Both the anchor set and the challenge set are filtered to confirmed taste
dimensions.** Sampling surfaced a codec tag as a challenge and a workflow
curation tag as an anchor; the `resolution_reason` filter removes both.

**Gate.**

```
not best_bet
and direct_confidence < revisit_direct_confidence
and A is non-empty
and C is non-empty                     # <- the hard requirement
and current_fit >= stretch_fit_floor   # floor only, not the sort key
```

`C is non-empty` removes the 64% of rows that today carry
`challenged_assumption: null` and cannot explain themselves.

**Ranking.**

```
lane_value = normalized(anchor_strength) * normalized_within_kind(challenge_distance)
```

Two properties are load-bearing and were both found by sampling:

- **Normalize within kind.** `challenge_distance` means something different for
  a tested negative than for an untested dimension; the two must be ranked on
  separate percentile scales and merged, or the untested branch swamps the
  other and the lane sorts by low confidence.
- **Multiply, do not add.** A card must be *both* well-anchored *and* genuinely
  a stretch; neither term may carry a card alone.

`fit_rank` is a deterministic tie-break only. Demoting fit from sort key to
floor is what stops Stretch reproducing the Best Bets ordering — today
`current_fit` supplies 78% of Discover's `lane_value`.

**Diversity.** At most `stretch_per_dimension` (default 1) card per challenged
dimension per page. Without it every top card challenges the same dimension.

**Qualification contract.**

```json
{"anchor_features": [{"feature_id": "...", "name": "...", "value": 0.0}],
 "challenged_feature": {"feature_id": "...", "name": "...", "facet_type": "tag",
                        "affinity": 0.0, "confidence": 0.0},
 "challenge_kind": "tested_negative" | "untested",
 "anchor_strength": 0.0, "challenge_distance": 0.0}
```

**Subtype** = `challenge_kind`. Two values read off the data rather than off a
threshold ladder, so they do not churn between builds.

### Blind Spots — replaces Adventure

**Facet coverage.** For every facet (studio, performer attribute, era bucket,
confirmed tag), count library presence and played presence, then:

```
base_rate   = played_scenes / total_scenes
rate(f)     = (played_count[f] + alpha * base_rate) / (library_count[f] + alpha)
darkness(f) = clamp(1 - rate(f) / base_rate, 0, 1)
```

`alpha = dark_prior_strength` (default 20) — a Beta-posterior shrink toward the
base rate, replacing the current `min(3, log1p((expected+2)/(played+2)))`. The
existing formula is an unregularized mean over a sparse vector, which is why
Adventure's top-500 carry 46% as many tags as the library mean.

A facet is **dark** when `darkness(f) >= dark_threshold` (0.55) and
`library_count[f] >= dark_min_library` (60).

**Gate — corroboration.**

```
scene is unplayed and eligible
and content_feature_count(scene) >= dark_min_features   (4)
and |{facet_type of dark facets on this scene}| >= dark_min_facet_types  (2)
```

The facet-type count, not the facet count, is what matters: two dark tags are
one measurement, a dark tag plus a dark studio are two. This is the clause that
stops the lane admitting every eligible scene, and the minimum feature count
stops sparse scenes re-entering through `representativeness`.

**Ranking — inverted relative to today.**

```
lane_value = mean(darkness(f) for dark facets f)
           * metadata_confidence
           * (1 + max(0, appeal))
```

The `unknown_performer_share`, `unknown_studio` and `content_distance` terms
are **dropped entirely**. They are precisely the terms that select thin
metadata, and thin metadata is the opposite of what a teach-the-model card
needs. Sampling confirmed the inversion works: selected scenes carry metadata
confidence 0.70-0.89.

**Diversity.** One card per dark facet per page. The subtype rotation slot in
`SlateBuilder._target` becomes a dark-*facet* rotation, which is a real
balancing axis unlike the five subtypes it replaces.

**Qualification contract.**

```json
{"dark_facets": [{"facet_type": "studio", "id": "...", "name": "...",
                  "library_count": 0, "played_count": 0, "darkness": 0.0}],
 "corroborating_types": 2}
```

**Subtype**: `never_played` (every dark facet has `played_count == 0`) or
`under_played`. Two factual values.

**Framing.** "Help me judge this," not "you might like this." Wire to the
pairwise Curate loop (`docs/workpackage-pairwise-picks.md`); its success metric
is *did the model learn*, not *did the user watch*.

**Facet-level dismissal.** Several dark studios are ones the user owns 60-120
scenes of and has never played. That may mean "unexplored" or "bulk-acquired
and not to my taste," and the lane would otherwise keep offering them. Blind
Spots therefore needs a dismissal that suppresses a whole *facet*, not just a
scene — which is also the cleanest signal the Curate loop could consume.

### Dormant — new

**New table required** (migration 0033):

```sql
CREATE TABLE model_entity_dormancy (
    model_id TEXT NOT NULL REFERENCES model_version(model_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('performer', 'tag', 'studio')),
    entity_id TEXT NOT NULL,
    last_played_at_ms INTEGER NOT NULL,
    positive_strength REAL NOT NULL,
    play_count INTEGER NOT NULL,
    distinct_scene_count INTEGER NOT NULL,
    PRIMARY KEY (model_id, entity_type, entity_id)
) STRICT;
```

Like every other `MODEL_TABLES` entry it needs both a core-schema and an
artifact-schema copy (`curator/storage/artifacts.py` `MODEL_SCHEMA`).

**Build-time computation.** Joining `source_play` through `scene_performer` /
`scene_tag` / `source_scene.studio_id`: `last_played_at_ms`, `play_count`,
`distinct_scene_count`, and `positive_strength` — a `direct_confidence`-weighted
mean of `direct_appeal` over the entity's played scenes for performers and
studios, or `affinity * confidence` from `feature_affinity` for tags.

**New curve required** (`curator/model/curves.py` + Go mirror), same shape as
`scene_recovery`:

```python
def entity_dormancy(days_since_entity_played, *, config):
    exponent = -(days_since_entity_played - config.dormancy_center_days) / config.dormancy_width_days
    return 1 / (1 + math.exp(clamp(exponent, -60, 60)))
```

Defaults `dormancy_center_days = 120`, `dormancy_width_days = 45`.

**Evaluated at slate time, not frozen at build.** `SlateBuilder` already
recomputes `scene_recovery` against a live `now_ms` in `_direct_play_filters` /
`_live_current_fit` rather than trusting the build-time column. Dormancy is
time-dependent the same way, so the table stores `last_played_at_ms` and the
curve is applied at query time. A week-old artifact must not call a taste
dormant that was watched yesterday.

**Gate.** The scene is eligible and unplayed, and has at least one entity with:

```
play_count >= dormant_min_plays              (3)
and distinct_scene_count >= dormant_min_scenes (2)
and positive_strength >= dormant_min_positive
and entity_dormancy(now) >= dormant_floor    (0.5)
```

**Ranking.**

```
lane_value = positive_strength * fit_rank
```

**The dormancy curve is a gate, not a ranking term.** It saturates: past
roughly 250 days every qualified card sits at 0.98-1.00, so including it in the
ordering looks meaningful while contributing nothing. Keeping it out of
`lane_value` is the honest form. If dormancy *should* discriminate among
long-parked tastes, that needs a non-saturating transform and is a separate
decision — but note it is not obvious that a three-year-old taste is a better
recommendation than a one-year-old one.

**Diversity.** At most `dormant_per_entity` (default 1) card per entity per
page. Without it a single strongly-dormant entity floods the lane.

**Qualification contract.**

```json
{"dormant_entity": {"type": "performer", "id": "...", "name": "..."},
 "days_since_played": 0, "positive_strength": 0.0,
 "supporting_plays": 0, "dormancy": 0.0}
```

**Why no existing lane covers it.** `recovery` is per-scene and saturates at
1.0, so a taste parked long ago contributes nothing distinguishing once its
scenes have cooled. `current_fit` penalises *recent* repetition but has no term
rewarding long absence. Revisit returns the same scene; Dormant returns a new
scene from a parked taste. Best Bets would surface these only if current
corroborating evidence were strong — which is what dormancy erodes.

**Subtype** = `entity_type`.

### Pruning moves out of recommendations

`pruning_candidate` already has its own table. Give it a maintenance surface so
no lane means both "try this" and "delete this."

## New properties summary

| what | where | kind |
|---|---|---|
| Bounded named content contributors in `classification_json` | `builder.py` `_classification_payload` + Go mirror | payload change — invalidates cached models once |
| `model_entity_dormancy` table | migration 0033, core + artifact schema | new table |
| `entity_dormancy` curve | `curator/model/curves.py` + Go mirror | new curve |
| Facet extraction (studio / attribute / era / confirmed tag) | `LanePolicy` / `laneClassify` | new derivation, existing tables |
| StashDB tag-confirmation filter | `tag_role.resolution_reason` | existing data, newly used |
| Regularized `darkness(f)` + support floor + corroboration | `LanePolicy` / `laneClassify` | replaces `_adventure_context` gap math |
| `model_lane_order` lane CHECK rebuild | migration 0033 | schema change |
| `stretch_*`, `dormant_*`, `dark_*` constants | `RankingConfig` + `modelSubConfig` | config, fingerprint-guarded |

Nothing above needs a new *source* — no new Stash fields, no external fetches.

**Cost.** Stretch adds a bounded number of small records per scene to the
artifact. Blind Spots reuses counts already built in `_adventure_context`,
extends them across four facet types, and *drops* the unknown performer/studio
passes. Dormant adds one entity-level pass over `source_play` joined to
`scene_performer` / `scene_tag`, bounded by play history rather than library
size — a new pass, to be measured against the existing lane-classification
budget before landing.

## Explicitly not proposed

Each of these was measured, not assumed.

- **Taxonomy category rollup.** The obvious way to fix tag sparsity is to roll
  the StashDB-matched tags up into their 28 taxonomy categories. Measured, it
  fails: all 13 categories with meaningful support sit between **5.05% and
  5.89%** play rate. Aggregation destroys exactly the variance the lane needs.
  Recorded here so it is not re-proposed.
- **Duration and performer-count facets.** Spreads of roughly 2.7x and 3.4x
  exist, but every bucket covers thousands of scenes so no bucket ever goes
  dark. Usable as filters, useless as regions.
- **Era as a weighted signal.** Era produces real dark regions but is
  confounded with acquisition recency — older scenes have had *more* time to be
  watched and are watched less, so "does not watch old scenes" may be a
  preference to honour rather than a blind spot to challenge. Included as a
  corroborating facet, deliberately not weighted on its own.
- **"You never finished this."** Ruled out on data: the overwhelming majority
  of played scenes register under 20% completion in Stash's play-duration
  tracking, so abandonment is indistinguishable from normal use.
- **"Backlog" (owned a long time, never played).** `sync_seen` carries no
  timestamp and `sync_run` rows are pruned by retention, so first-seen time is
  unrecoverable. Needs a `first_seen_ms` column first. Deferred, not rejected.
- **"New arrivals."** A distinct ordering, not a distinct intent — better as a
  sort/filter.

## Architecture context

- Every op is dual-implemented (Go binary = runtime, Python = differential
  oracle) with byte-identical differential tests. `LanePolicy.classify` and
  `laneClassify` must stay row-for-row equal, including `qualification_json`
  key order. Every formula above lands twice.
- **Migration 0033** (mirrored byte-identical in `core/migrations/` and
  `curator/storage/sql/`): `model_lane_order` from migration 0015 carries
  `CHECK (lane IN ('for_you','best_bets','revisit','discover','adventure'))`
  and a matching `source_lane` check, so renaming or adding a lane means
  rebuilding that table. The same migration adds `model_entity_dormancy`.
  `model_scene_lane.lane` is unconstrained `TEXT`.
- New thresholds are config-backed so the canonical-config fingerprint guards
  them; changing them invalidates cached models, which is intended.
- The contributor-list payload change alters the model fingerprint once.
  Combined with the lane renames this is a one-time full rebuild — worth
  landing the payload change and the lane renames in the same release.

### Touch points

- **Policy:** `curator/ranking/policy.py` (`LANES`, `classify`,
  `_adventure_subtype`, `_adventure_context`), `core/laneclassify.go`.
- **Model build:** `curator/model/builder.py` (`_classification_payload`,
  dormancy pass), `curator/model/curves.py`, and Go mirrors.
- **Slate:** `curator/ranking/slate.py` (`FAMILIAR_PATTERN`,
  `ADVENTUROUS_PATTERN`, `QUERIED_SCORE_FIRST_LANES`, `_target`, live dormancy
  evaluation alongside `_live_current_fit`), `core/slate.go`,
  `core/slate_greedy.go`.
- **Config:** `curator/config.py` (`RankingConfig`, `ModelConfig`,
  `for_you_pattern`).
- **Surface:** `plugin/stash-curator.js` (`LANES`), `curator/api.py`,
  `curator/cli.py`, `curator/reporting/html.py`.
- **Explanations:** `curator/explanations/planner.py`,
  `curator/explanations/render.py`, `core/explanations_render.go` — each new
  `qualification_json` contract needs a reason code and a rendered phrasing.
- **Artifacts:** `curator/storage/artifacts.py` (`MODEL_SCHEMA` gains
  `model_entity_dormancy`), `core/build_artifacts.go`, `core/materialize.go`.
- **Docs:** `docs/recommendations.md` (its lane-policy section is currently
  inaccurate about Discover), `docs/using-curator.md`.
- **Tests:** 11 modules reference the current lane names, notably
  `tests/ranking/test_slate.py`, `tests/explanations/test_reasons.py`,
  `tests/test_api.py`.

## Sequencing

1. **Stretch** — contributor-payload extension, the required-challenge gate,
   the confirmation filter, per-kind normalization, and the per-dimension cap.
   No new table, no new pass.
2. **Blind Spots** — facet extraction, regularized darkness, corroboration
   gate, ranking inversion, facet dismissal. Needs the 0033 lane rename.
3. **Dormant** — the entity pass, the table, and the curve.
4. **Pruning surface split** and doc/UI copy alignment.

Steps 1-3 all want migration 0033; land the schema once and gate the lanes
behind config if they cannot ship together.

## Open questions

- Does `for_you_pattern` keep five lanes in rotation, or does Blind Spots stay
  out of For You entirely given its teach-the-model framing?
- Dormancy horizon: fixed defaults, or derived per-user from the distribution
  of inter-play gaps? And should long-parked tastes discriminate at all, or is
  gate-only correct?
- Should Dormant and Revisit share a UI shelf ("Back to...") while staying
  separate lanes in the model?
- May a scene appear in both Dormant and Best Bets? The slate already dedups by
  `scene_id`, so the open part is which lane gets attribution in the
  explanation.
- Where does facet-level dismissal live — a Blind Spots control, a Curate
  outcome, or both?
