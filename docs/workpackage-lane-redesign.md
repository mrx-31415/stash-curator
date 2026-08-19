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

A second pass tested whether the lanes could be made less tag-dependent. A
third re-sampled the revised spec and found four more defects, also folded in:

8. **A facet with no affinity row is not "untested", it is unmodelled.** Only
   268 of 998 studio features carry a `feature_affinity` row. Under a bare
   `effective_support < threshold` rule the other 730 all qualified as
   challenges, every one at `1 - confidence = 1.0` — an unbounded pool tied at
   maximum distance, reproducing defect 1 through a new facet. The `untested`
   kind now requires an existing affinity row with low support. The conceptual
   line: **Stretch challenges dimensions the model has an opinion about; Blind
   Spots handles what it has never seen.**
9. **Performer attributes cannot be Stretch dimensions.** `feature_affinity`
   carries rows for `content`, `performer_identity`, `studio` and `structure`
   only — nothing for `profile:*`. There is no affinity, confidence or support
   from which to compute `challenge_distance`. Attributes remain valid for
   Blind Spots, which derives darkness from observed rates rather than learned
   affinity.
10. **Averaging darkness penalised corroboration.** Ranking on
    `mean(darkness)` meant a scene with *more* independent agreement scored
    *lower*, because additional corroborators diluted the strongest signal. The
    best-corroborated card in sampling — three facets on one coherent niche —
    ranked fifth. Ranking now takes the strongest facet and adds a bonus per
    additional independent facet type.
11. **A region must be narrow to mean anything.** With only a lower bound on
    facet breadth, one era bucket and one ethnicity facet appeared in four of
    the five top cards, acting as free corroboration for unrelated niches. A
    facet covering 12% of the library corroborates everything and therefore
    distinguishes nothing. Breadth is now bounded above as well as below.

That third pass also confirmed Dormant reproduces identically across runs, and
that the two Stretch kinds separate cleanly on confidence (roughly 0.6-0.9 for
tested-negative against 0.1-0.15 for untested).

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
| tag | `scene_tag`, filtered — see below | hand-applied multi-label, noisiest |

Era (`source_scene.scene_date`) and performer attributes were evaluated as
facets and dropped; see *Explicitly not proposed*. The extraction machinery
stays general so they can be reinstated if the blocking reasons are removed.

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

Dark-region counts at a `darkness >= 0.55`, `60 <= library <= 500` bar came out
**studio 20, tag 12** — studio alone supplies more than tags do, from a field
that cannot be mis-tagged.

**The generalization's real payoff is studio.** Era and performer attributes
were both carried into the spec and then fell back out under sampling, for
different reasons recorded below: attributes have no learned affinity (so they
cannot drive Stretch) and are too broad to be regions (so they cannot drive
Blind Spots), and every era bucket spans thousands of scenes. The lane set is
therefore **studio + confirmed tag**, with the facet machinery kept general so
attributes can join later if `profile:*` affinities are ever built.

**Corroboration is the reliability mechanism.** A scene qualifies for Blind
Spots only when **two or more independent facet types** are simultaneously
dark. In sampling this produced cards where a studio and two separate tags all
independently flagged the same coherent niche — a far more trustworthy signal
than any single field being sparse. It also buys margin: because a noisy single
facet can no longer qualify alone, the per-facet threshold can be *lower*
without losing precision. Reliability comes from agreement across independent
measurements, not from a stricter bar on one field.

Corroboration only works if the corroborators are *specific*. A facet spanning
a large fraction of the library agrees with everything, so it inflates the
count without adding evidence — hence the breadth ceiling in the gate below.

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

**Candidate dimensions.** StashDB-confirmed tags and studios — the two facet
types that carry a learned `feature_affinity`. Performer attributes are
deliberately *excluded*: `feature_affinity` has no `profile:*` rows, so there
is nothing to compute `challenge_distance` from. Admitting them would require
adding profile families to the affinity build, which is a model change rather
than a lane change and belongs in its own workpackage.

**Definitions.** Over the scene's contributor list, restricted to confirmed
taste dimensions:

- Anchor set `A` = contributors with `affinity >= stretch_anchor_affinity`
  (0.015) and `confidence >= stretch_anchor_confidence` (0.5).
- Challenge set `C` = contributors that are either
  - *tested negative*: `affinity <= -stretch_anchor_affinity` and
    `confidence >= stretch_anchor_confidence`; or
  - *untested*: the feature **has** a `feature_affinity` row but
    `effective_support < stretch_untested_support`.

  The affinity-row requirement is load-bearing. Roughly three quarters of
  studio features have no affinity row at all; without the requirement they all
  qualify at `1 - confidence = 1.0` and tie at maximum distance. A dimension
  the model has never scored is *unmodelled*, which is Blind Spots' concern,
  not a challenge Stretch can pose.
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

**Shelf size.** The gate admits a large share of eligible scenes, but the
per-dimension cap means the shelf a user can actually page through is bounded
by the number of distinct challengeable dimensions — the confirmed tags and
studios carrying an affinity row. Quote that bound, not the gate share.

Sampling separates the two kinds cleanly on confidence, which suggests the
names could be better: `tested_negative` cards sit around 0.6-0.9 confidence
and `untested` around 0.1-0.15, so what distinguishes them is the *strength* of
the model's stance, not its existence. `known_dislike` / `weak_evidence` would
describe the split more honestly.

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

**Facet coverage.** For every facet (studio, confirmed tag — see *Facet
sources*), count library presence and played presence, then:

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
`dark_min_library <= library_count[f] <= dark_max_library` (60 and 500).

**The upper bound matters as much as the lower one.** A facet spanning a large
share of the library is not a region — it co-occurs with everything, so it
corroborates everything. Without the ceiling, one era bucket and one ethnicity
facet appeared in four of the five top-ranked cards, inflating corroboration
counts for niches they had nothing to do with. The ceiling removes every era
bucket, the broad demographic facets, and the largest studios.

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

**Ranking — inverted relative to today, and corroboration-rewarding.**

```
lane_value = max(darkness(f) for dark facets f)
           * (1 + dark_corroboration_bonus * (facet_types - 1))   # default 0.15
           * metadata_confidence
           * (1 + max(0, appeal))
```

Taking the **strongest** facet rather than the mean is deliberate. Averaging
lets a weaker corroborator drag a card down, so a scene with more independent
agreement ranks lower than one with less — the opposite of the intent. In
sampling, the best-corroborated card (three facets on one coherent niche)
ranked fifth under `mean` and first under `max` plus bonus.

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

**Shelf size.** As with Stretch, quote the bound the user experiences: with one
card per dark facet, the shelf is bounded by the number of dark facets, which
is an order of magnitude smaller than the gate share.

**Facet-level dismissal.** Several dark studios are ones the user owns 60-120
scenes of and has never played. That may mean "unexplored" or "bulk-acquired
and not to my taste," and the lane would otherwise keep offering them. Blind
Spots therefore needs a dismissal that suppresses a whole *facet*, not just a
scene — which is also the cleanest signal the Curate loop could consume.

**Very broad dark facets are a pruning signal, not an exploration card.** The
breadth ceiling excludes studios the user owns well over a thousand scenes of
and almost never plays. That observation is real and worth surfacing — but as
"you own N scenes from this studio and play almost none," on the pruning
surface, not as a per-scene recommendation. It is the same data serving a
different intent, which is exactly the conflation this workpackage is trying to
undo.

### Dormant — new

**New table required** (migration 0034 — see *Architecture context* for why
the number moved):

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

### Route the breadth-ceiling signal to pruning

`pruning_candidate` already has its own table, scoring, and UI panel
(`PrunePanel` in `plugin/stash-curator.js`), fully independent of the four
lanes today — the only structural link is that pruned scenes are excluded
from lane eligibility (`core/eligibility.go`). This is not a restructuring,
then; it closes one specific gap. Adventure's dominant signal today is
metadata thinness, the same character of signal that drives prune-suspect
scoring, so without any code coupling the same poorly-tagged scenes tend to
surface on both the explore lane and as prune suspects — a coincidence of
shared signal character, not a shared pipeline, and Blind Spots' facet
approach mostly moves away from it (see *Facets, not tags*). The genuine gap
is the breadth ceiling itself (see *Blind Spots*, "the upper bound matters as
much as the lower one"): a studio the user owns well over a thousand scenes
of and almost never plays is excluded from Blind Spots as too broad to be a
region, and that observation — "you own N scenes from this studio and play
almost none" — is real and worth surfacing, but today it is simply discarded
rather than routed anywhere. Land it as a new derived prune reason.

## New properties summary

| what | where | kind |
|---|---|---|
| Bounded named content contributors in `classification_json` | `builder.py` `_classification_payload` + Go mirror | payload change — invalidates cached models once |
| `model_entity_dormancy` table | migration 0034, core + artifact schema | new table |
| `entity_dormancy` curve | `curator/model/curves.py` + Go mirror | new curve |
| Facet extraction (studio + confirmed tag; machinery general) | `LanePolicy` / `laneClassify` | new derivation, existing tables |
| StashDB tag-confirmation filter | `tag_role.resolution_reason` | existing data, newly used |
| Regularized `darkness(f)` + support floor + corroboration | `LanePolicy` / `laneClassify` | replaces `_adventure_context` gap math |
| `model_scene_lane` / `model_lane_candidate_cache` / `model_lane_order` lane CHECK rebuild | migration 0034 | schema change |
| `stretch_*`, `dormant_*`, `dark_*` constants | `RankingConfig` + `modelSubConfig` | config, fingerprint-guarded |

Nothing above needs a new *source* — no new Stash fields, no external fetches.

**Cost.** Stretch adds a bounded number of small records per scene to the
artifact. Blind Spots reuses counts already built in `_adventure_context`,
extends them across the facet types, and *drops* the unknown performer/studio
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
- **Era as a facet at all.** Era survived the first pass as a corroborating
  facet and was then removed by the breadth ceiling: every bucket spans
  thousands of scenes, so it corroborates any old scene for free and
  distinguishes nothing. It is also confounded with acquisition recency —
  older scenes have had *more* time to be watched and are watched less, so
  "does not watch old scenes" is plausibly a preference to honour rather than a
  blind spot to challenge. Dropped on both counts.
- **Performer attributes as Stretch dimensions.** Their play-rate spread is
  real (roughly 1.5x-2.6x between the least- and most-played value of a given
  attribute), but `feature_affinity` has no `profile:*` rows, so there is no
  learned stance to challenge. They also proved too broad to survive the Blind
  Spots breadth ceiling. Building attribute affinities is a plausible follow-up
  workpackage; it is a model change, not a lane change.
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
- **Migration 0034** (renumbered from the original 0033 during rebase: `main`
  had independently claimed 0033 for an unrelated ELO-table drop; mirrored
  byte-identical in `core/migrations/` and `curator/storage/sql/`). Three
  tables carry a `CHECK (lane IN (...))` naming the old lane list and cannot
  be altered in place, so all three are rebuilt: `model_scene_lane` (from
  migration 0003 — contrary to an earlier version of this doc, its `lane`
  column is **not** unconstrained), `model_lane_candidate_cache` (migration
  0008), and `model_lane_order` + `source_lane` (migration 0015). The same
  migration adds `model_entity_dormancy`. All three rebuilt tables are
  `MODEL_TABLES` entries (`curator/storage/artifacts.py`), so a connection
  with an active model artifact shadows each name with a temp view; every
  `DROP`/`CREATE TABLE` is `main.`-qualified to target the core-schema copy
  instead, and `model_scene_lane`'s two indexes (which `CREATE INDEX` cannot
  schema-qualify) are preceded by `DROP VIEW IF EXISTS temp.model_scene_lane`.
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
   No new table, no new pass. **Shipped** (migration 0034, PR #172).
2. **Blind Spots** — facet extraction, regularized darkness, corroboration
   gate, ranking inversion, facet dismissal. Needs the 0034 lane rename.
3. **Dormant** — the entity pass, the table, and the curve.
4. **Route the Blind Spots breadth-ceiling signal to pruning** and doc/UI
   copy alignment.

Steps 1-3 all want migration 0034 (already landed by step 1); land any
further schema for steps 2-3 as its own migration, and gate the lanes behind
config if they cannot ship together.

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
- Rename the Stretch subtypes to `known_dislike` / `weak_evidence`? Sampling
  shows the split is about the strength of the model's stance, not whether one
  exists, and the current names imply the latter.
- Is `dark_max_library` (default 500, roughly 2% of a large library) better
  expressed as an absolute count or as a share of the library? A share travels
  better across library sizes.
