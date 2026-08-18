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

## Signal inventory

What the classifier can read today, and where it comes from. This is the
constraint set the lane definitions below are built from.

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

**Per-scene relations** — `model_scene_neighbor` (`neighbor_scene_id`,
`similarity`, `weight`, `outcome`, `rank`), `model_performer_edge`
(`performer_id`, `rank`, `similar_performer_id`).

**Feature-level** — `feature_affinity` (`feature_id`, `affinity`,
`confidence`, `effective_support`, `distinct_scene_count`), `entity_feature`
(`entity_type`, `entity_id`, `feature_id`, `value`, `confidence`),
`feature_definition` (`family`, `name`, `provenance`).

**History** — `source_play` (`scene_id`, `played_at_ms`), `play_session`,
`source_o`, `feedback`, `scene_performer`, `scene_tag`,
`source_scene.studio_id`, `tag_parent`.

**Derived in `classify` today** — percentile ranks over content, neighbor,
neighbor-similarity, performer (identity + similarity), studio, and fit; plus
the per-feature `library_count` / `played_count` pair built inside
`_adventure_context`.

## Proposed lanes

Each lane below gives: inputs, the gate (a boolean over those inputs), the
ranking expression, the `qualification_json` contract the explanation renders
from, and the subtype rule. All new constants are config-backed in
`RankingConfig` with a Go `modelSubConfig` mirror.

### Best Bets — unchanged

Gate and ranking stay as they are.

### Revisit — unchanged gate, optional second tier

The existing gate (`direct_appeal > 0.10`, `direct_confidence >= 0.35`,
`recovery >= 0.10`, a durable signal in {`o`, `thumb_up`, `repeat`,
`scene_rating`, `curation_rating`}, and the scene played) stays. Measured on a
real library, the three numeric clauses admit roughly **six times** as many
played scenes as survive the durable-signal filter — that filter is what makes
the lane precise, so it stays as the primary tier.

Optional tier 2: admit the numeric-gate-only population, ranked strictly below
every durable-tier row (add a constant offset to the durable tier's
`lane_value` rather than interleaving). Record `tier: "durable" | "numeric"` in
`qualification_json` so the explanation can say which one a card came from.
Motivation is supply, not quality: `for_you_pattern` requests Revisit in 4 of
20 slots, which the durable pool alone cannot sustain across many pages.

### Stretch — replaces Discover

**New property required.** A named challenged dimension at *feature* (tag)
granularity does not exist in what the classifier reads. The data exists in
`components_json.content.top[]` but is stripped from `classification_json` by
`_classification_payload`. Extend that payload to keep a bounded contributor
list — the top `stretch_contributor_count` (default 3) positive and 3 negative
content contributors, each reduced to `{feature_id, name, value, affinity,
confidence, effective_support}`.

This preserves the intent of `258452e` ("Slash lane-classification reads with a
lean classification payload"): the bulk that commit removed was the `metadata`
blob and the unbounded family detail, not six small records. It is an artifact
payload change, so it invalidates cached models once, then stabilizes.

**Definitions.** Over the scene's contributor list:

- Anchor set `A` = contributors with `affinity >= stretch_anchor_affinity`
  (0.015) and `confidence >= stretch_anchor_confidence` (0.5).
- Challenge set `C` = contributors that are either
  - *tested negative*: `affinity <= -stretch_anchor_affinity` and
    `confidence >= stretch_anchor_confidence`; or
  - *untested*: `effective_support < stretch_untested_support` (a low
    absolute-evidence floor), regardless of affinity sign.
- `anchor_strength = sum(value for A)`.
- `challenged = argmax(|value|) over C` — **this is the named dimension**.
- `challenge_distance = |affinity(challenged)| * confidence(challenged)` for a
  tested negative; for an untested contributor, `1 - confidence(challenged)`
  (how little is known about it).

**Gate.**

```
not best_bet
and direct_confidence < revisit_direct_confidence
and A is non-empty
and C is non-empty                     # <- the new hard requirement
and current_fit >= stretch_fit_floor   # floor only, not the sort key
```

The `C is non-empty` clause is the whole point: it removes the 64% of rows that
today carry `challenged_assumption: null` and cannot explain themselves, and it
shrinks the lane from 71% of the library to shelf size.

**Ranking.**

```
lane_value = normalized(anchor_strength) * normalized(challenge_distance)
```

with `fit_rank` used only as a deterministic tie-break. Fit is demoted from
sort key to floor — that is what stops Stretch reproducing the Best Bets
ordering (today fit supplies 78% of Discover's `lane_value`). Multiplying
rather than adding is deliberate: a card must be *both* well-anchored *and*
genuinely a stretch, so neither term can carry a card alone.

**Qualification contract.**

```json
{"anchor_features": [{"feature_id": "...", "name": "...", "value": 0.0}],
 "challenged_feature": {"feature_id": "...", "name": "...",
                        "affinity": 0.0, "confidence": 0.0},
 "challenge_kind": "tested_negative" | "untested",
 "anchor_strength": 0.0, "challenge_distance": 0.0}
```

**Subtype** = `challenge_kind`. Two values, both read off the data rather than
off a threshold ladder, so they do not churn between builds the way
`adjacent` / `frontier` / `stretch` do.

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

**Build-time computation.** For each entity, joining `source_play` through
`scene_performer` / `scene_tag` / `source_scene.studio_id`:

- `last_played_at_ms = max(played_at_ms)`
- `play_count`, `distinct_scene_count` — support counts
- `positive_strength`:
  - performers and studios — `direct_confidence`-weighted mean of
    `direct_appeal` over that entity's played scenes;
  - tags — `feature_affinity.affinity * feature_affinity.confidence` for the
    corresponding feature, which is already the model's own estimate.

**New curve required** (`curator/model/curves.py` + Go mirror), deliberately
the same shape as `scene_recovery`:

```python
def entity_dormancy(days_since_entity_played, *, config):
    exponent = -(days_since_entity_played - config.dormancy_center_days) / config.dormancy_width_days
    return 1 / (1 + math.exp(clamp(exponent, -60, 60)))
```

Defaults `dormancy_center_days = 120`, `dormancy_width_days = 45`.

**Evaluated at slate time, not frozen at build.** This follows the established
pattern: `SlateBuilder` already recomputes `scene_recovery` against a live
`now_ms` in `_direct_play_filters` / `_live_current_fit` rather than trusting
the build-time `recovery` column. Dormancy is time-dependent in exactly the
same way, so the table stores `last_played_at_ms` and the *curve* is applied at
query time. A model artifact a week old must not claim a taste is dormant when
the user watched it yesterday.

**Gate.** The scene is eligible and unplayed, and has at least one entity with:

```
play_count >= dormant_min_plays              (3)
and distinct_scene_count >= dormant_min_scenes (2)
and positive_strength >= dormant_min_positive
and entity_dormancy(now) >= dormant_floor    (0.5)
```

The driving entity is the qualifying entity with the highest
`entity_dormancy(now) * positive_strength`.

**Ranking.**

```
lane_value = entity_dormancy(now) * positive_strength * fit_rank
```

**Qualification contract.**

```json
{"dormant_entity": {"type": "performer", "id": "...", "name": "..."},
 "days_since_played": 0, "positive_strength": 0.0,
 "supporting_plays": 0, "dormancy": 0.0}
```

**Why it is not covered by an existing lane.** `recovery` is per-scene and
saturates at 1.0, so a taste parked long ago contributes nothing distinguishing
once its scenes have cooled. `current_fit` penalises *recent* repetition but
has no term that rewards long absence. Revisit returns the same scene; Dormant
returns a new scene from a parked taste. Best Bets would surface these only if
current corroborating evidence were strong — which is precisely what dormancy
erodes.

**Subtype** = `entity_type` (`performer` / `tag` / `studio`), factual.

### Blind Spots — replaces Adventure

Same per-feature `library_count` / `played_count` inputs as today's
`_adventure_context`, recombined. Three changes, in order of importance.

**1. Regularize the darkness estimate.** Today: `min(3, log1p((expected+2) /
(played_count+2)))`, averaged over the content vector — which gives sparse
scenes unregularized extremes. Instead, per feature `f`:

```
base_rate = played_scenes / total_scenes
rate(f)   = (played_count[f] + alpha * base_rate) / (library_count[f] + alpha)
darkness(f) = clamp(1 - rate(f) / base_rate, 0, 1)
```

with `alpha = dark_prior_strength` (default 20). A Beta-posterior shrink toward
the base rate, so a feature on three scenes cannot look darker than a feature on
three hundred purely by having no plays.

**2. Add a support floor — this is the fix that gates the lane.** A feature is
*dark* only if `darkness(f) >= dark_threshold` **and**
`library_count[f] >= dark_min_library` (default 25) **and** its
`feature_definition.family` is a content family. A scene qualifies only if it
carries at least one dark feature at `value` share `>= dark_min_share` of its
content vector. Scenes in no dark region do not qualify at all — which is what
stops the lane admitting 100% of eligible scenes.

**3. Invert the ranking.** Today the lane ranks up unknown performers, unknown
studios, and content distance, with `metadata_confidence` at a weight of 0.12 —
which is why its top-500 carry 46% as many tags as the library mean. Within a
dark region we want the *flagship*, not the most alien file:

```
lane_value = darkness(driving_feature)
           * representativeness          # scene's value share on that feature
           * metadata_confidence
           * (1 + max(0, appeal))
```

The `unknown_performer_share`, `unknown_studio`, and `content_distance` terms
are **dropped entirely**. They are the terms that select thin metadata, and
thin metadata is the opposite of what a teach-the-model card needs.

**Diversity.** One scene per dark feature per page. The existing subtype
rotation slot in `SlateBuilder._target` becomes a dark-*feature* rotation, which
is a real balancing axis (unlike the five subtypes it replaces).

**Qualification contract.**

```json
{"dark_feature": {"feature_id": "...", "name": "..."},
 "library_count": 0, "played_count": 0, "darkness": 0.0,
 "representativeness": 0.0}
```

**Subtype**: `never_played` (`played_count == 0`) or `under_played`. Two
values, both factual counts rather than threshold ladders.

**Framing.** "Help me judge this," not "you might like this." Wire to the
pairwise Curate loop (`docs/workpackage-pairwise-picks.md`); its success metric
is *did the model learn*, not *did the user watch*.

### Pruning moves out of recommendations

`pruning_candidate` already has its own table. Give it a maintenance surface so
no lane means both "try this" and "delete this."

## New properties summary

| what | where | kind |
|---|---|---|
| Bounded named content contributors in `classification_json` | `curator/model/builder.py` `_classification_payload` + Go mirror | payload change — invalidates cached models once |
| `model_entity_dormancy` table | migration 0033, core + artifact schema | new table |
| `entity_dormancy` curve | `curator/model/curves.py` + Go mirror | new curve |
| Regularized `darkness(f)` + support floor | `LanePolicy` / `laneClassify` | replaces `_adventure_context` gap math |
| `model_lane_order` lane CHECK rebuild | migration 0033 | schema change (see below) |
| `stretch_*`, `dormant_*`, `dark_*` constants | `RankingConfig` + `modelSubConfig` | config, fingerprint-guarded |

Nothing above needs a new *source* — no new Stash fields, no new external
fetches. Stretch and Blind Spots are recombinations of data already computed at
build time; only Dormant adds a genuinely new derived pass, and it reads tables
that already exist.

**Cost.** Stretch adds a bounded number of small records per scene to the
artifact. Blind Spots reuses feature counts already built in
`_adventure_context` and *reduces* per-scene work by dropping the unknown
performer/studio passes. Dormant adds one entity-level pass over `source_play`
joined to `scene_performer` / `scene_tag`, which is bounded by play history
rather than library size — but it is a new pass and should be measured against
the existing lane-classification budget before landing.

## Explicitly not proposed

- **"You never finished this."** Ruled out on data: the overwhelming majority
  of played scenes register under 20% completion in Stash's play-duration
  tracking, so abandonment is indistinguishable from normal use. There is no
  usable completion signal.
- **"Backlog" (owned a long time, never played).** Good intent, not buildable
  today: `sync_seen` carries no timestamp and `sync_run` rows are pruned by
  retention, so first-seen time is unrecoverable. Needs a `first_seen_ms`
  column first. Deferred, not rejected.
- **"New arrivals."** Better served as a sort/filter than a lane; it is a
  distinct ordering, not a distinct intent.

## Architecture context

- Every op is dual-implemented (Go binary = runtime, Python = differential
  oracle) with byte-identical differential tests. `LanePolicy.classify` and
  `laneClassify` must stay row-for-row equal, including `qualification_json`
  key order. Every formula above lands twice.
- **Migration 0033** (mirrored byte-identical in `core/migrations/` and
  `curator/storage/sql/`): `model_lane_order` from migration 0015 carries
  `CHECK (lane IN ('for_you','best_bets','revisit','discover','adventure'))`
  and a matching `source_lane` check, so renaming or adding a lane means
  rebuilding that table. Same migration adds `model_entity_dormancy`.
  `model_scene_lane.lane` is unconstrained `TEXT` and needs no schema change.
- New thresholds are config-backed so the canonical-config fingerprint guards
  them; changing them invalidates cached models, which is intended.
- The contributor-list payload change alters the model fingerprint once.
  Combined with the lane renames, this is a one-time full rebuild — worth
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
- **Surface:** `plugin/stash-curator.js` (`LANES` labels/icons/descriptions),
  `curator/api.py`, `curator/cli.py`, `curator/reporting/html.py`.
- **Explanations:** `curator/explanations/planner.py`,
  `curator/explanations/render.py`, `core/explanations_render.go` — each new
  `qualification_json` contract needs a reason code and a rendered phrasing.
- **Artifacts:** `curator/storage/artifacts.py` (`MODEL_SCHEMA` gains
  `model_entity_dormancy`), `core/build_artifacts.go`, `core/materialize.go`.
- **Docs:** `docs/recommendations.md` (its lane-policy section is currently
  inaccurate about Discover), `docs/using-curator.md`.
- **Tests:** 11 modules reference the current lane names, notably
  `tests/ranking/test_slate.py` (subtype assertions),
  `tests/explanations/test_reasons.py`, `tests/test_api.py`.

## Sequencing

1. **Stretch** — the contributor-payload extension, the required-challenge
   gate, and the new sort key. No new table, no new pass. Delivers the clearest
   single improvement: a lane where every card can name why it is there.
2. **Blind Spots** — darkness regularization, support floor, ranking
   inversion. Retires the subtype rotation. Needs the 0033 lane rename.
3. **Dormant** — the entity pass, the table, and the curve. Highest value, most
   new plumbing.
4. **Pruning surface split** and doc/UI copy alignment.

Steps 1–3 all want migration 0033; land the schema once and gate the lanes in
behind config if they cannot ship together.

## Open questions

- Does `for_you_pattern` keep five lanes in rotation, or does Blind Spots stay
  out of For You entirely given its teach-the-model framing?
- Dormancy horizon: fixed defaults as above, or derived per-user from the
  distribution of inter-play gaps?
- Should Dormant and Revisit share a UI shelf ("Back to…") while staying
  separate lanes in the model?
- May a scene appear in both Dormant and Best Bets? Slate already dedups by
  `scene_id`, so the question is which lane gets attribution in the
  explanation.
