# Stash Curator recommendation design

Status: canonical design, 2026-07-15
Working product name: **Stash Curator**
Working repository name: `stash-curator`
Working tagline: **Navigate your library, guided by your taste.**

**Curator** is clear about the product's role: it learns from a personal library,
selects what is relevant, and presents those choices with context.

This document defines product behavior, model semantics, and design invariants. A
separate implementation document will define components, schemas, interfaces,
algorithms precise enough to code, delivery phases, tests, and acceptance criteria.
Implementation choices may evolve without changing this design unless they alter a
stated user promise or modeling rule.

## 1. Purpose

Stash Curator should minimize searching and quickly present a varied set containing
something the viewer finds appealing and satisfying in the moment. A good scene holds
the viewer's interest, contains sections they value, and may be worth returning to.

An outcome recorded through Stash's O history is the strongest direct success signal
available, but it is not the only form of success. Meaningful viewing, independent
returns, explicit feedback, and seeking out preferred sections can all be positive
evidence. Recommendation clicks are intermediate behavior, not the goal.

The product should do two things at once:

1. help the user find a satisfying choice now;
2. learn and occasionally challenge its own model so it does not become repetitive
   or permanently mistake missing evidence for dislike.

## 2. Product contract

### 2.1 Main view

The plugin adds one Stash-native page containing a scene-card grid with five tabs:

| Tab | User promise |
|---|---|
| **For You** | A varied everyday slate, weighted toward a good choice now |
| **Best Bets** | The most reliable current matches, watched or unseen |
| **Revisit** | Directly enjoyed scenes that are ready to return |
| **Discover** | Familiar appeal with one explained deviation or unknown |
| **Adventure** | Deliberate model-gap probes, including occasional likely misses |

The product may later recommend performers, studios, galleries, or other entities.
Neither the product name nor its preference model should be scene-specific.

### 2.2 Default For You composition

For You is composed as a slate, not as five independently concatenated lists. For an
initial 20-card page, use soft targets of approximately:

```text
10–12 Best Bets
 3–4 Revisit
 3–5 Discover
 about 1 anchored Adventure
```

Roughly 25% may contain mild friction, but only about 5% should be a true Adventure.
Early positions are conservative. Unused lane capacity may be borrowed by another
lane. A **Familiar ←→ Adventurous** control shifts these targets.

### 2.3 Feedback

The fast controls are thumbs up and thumbs down. A detail menu provides:

- **Not now** — temporary timing/cooldown feedback;
- **Never show** — durable hard exclusion;
- **Review for pruning** — reversible maintenance queue, never automatic deletion;
- **Metadata is wrong** — do not train from the current metadata snapshot;
- optional aspect-level feedback explaining what helped or hurt.

A newer thumbs down suppresses that exact item from every recommendation lane,
including Adventure. It remains learnable rather than permanent: later deliberate
organic use plus strong positive evidence, or an explicit reversal, can restore it.
**Never show** can only be reversed manually.

### 2.4 Explanations

Cards stay visually quiet. Reasons use progressive disclosure:

1. optional small reason indicator on the card;
2. one-line summary on hover, keyboard focus, or tap;
3. a click-open **Why this?** drawer;
4. optional scores-on-cards and developer diagnostics.

No essential information may be hover-only.

## 3. Scoring terminology

Keep the following concepts separate:

| Concept | Meaning |
|---|---|
| **Appeal** | Expected satisfaction if the item is played; relatively stable taste |
| **Current Fit** | How well that Appeal fits now after cooldown and recent appetite |
| **Confidence** | How much independent, relevant evidence supports the estimate |
| **Exploration value** | How useful the item is for correcting uncertainty or coverage gaps |
| **Choice likelihood** | Probability of selecting a shown card; presentation/context dependent |
| **Selection utility** | Ephemeral lane-and-position score after diversity and exploration |

The MVP represents Appeal and Current Fit as signed internal indices in `[-1, 1]`,
where zero is neutral/unknown, and may display them as `0–100` with 50 as neutral.
Confidence is in `[0, 1]`. Selection utility is policy-local and is not displayed as
Appeal. During cold start, Appeal is a relative index, not a calibrated probability.
Choice likelihood is not trained until Curator has logged enough known impressions;
it must never become a synonym for taste or reward clickbait.

## 4. Algorithm at a glance

Curator is a two-stage recommender: it first estimates each item's underlying
Appeal, then constructs a lane-specific slate that accounts for timing, exploration,
and variety. The complete flow is:

```text
Stash metadata + historical behavior + Curator feedback
                         │
                         ▼
        normalize events and build versioned features
                         │
                         ▼
      learn bounded affinities for tags, performers, studios,
          content neighbors, and direct item experience
                         │
                         ▼
      General Appeal ── blend ── Direct item evidence
                         │
                         ▼
     Appeal × cooldown/recent appetite = Current Fit
                         │
                         ▼
       lane policy adds confidence and exploration value
                         │
                         ▼
   greedy slate builder applies performer, studio, and content
                    diversity penalties
                         │
                         ▼
       ranked cards + inspectable reasons + logged impression
```

In compact form:

```text
general_appeal = bounded_sum(feature_family_affinities)
appeal         = blend(general_appeal, direct_item_evidence,
                       direct_evidence_confidence)
current_fit    = clamp(appeal + timing_adjustments)
lane_utility   = lane_policy(current_fit, confidence, exploration_value)
next_card      = argmax(lane_utility - slate_diversity_penalties)
```

The later sections define each term. The preference model estimates likely
satisfaction; lane policy and slate construction decide what should be shown right
now. Diversity changes presentation, never learned taste.

### 4.1 Public data assumptions

- Stash GraphQL provides sufficient metadata and aggregate behavior for the MVP.
- Library-wide requests are too expensive for interactive ranking, so Curator uses
  an incremental local cache.
- Metadata is positive-unlabeled: presence is evidence; absence is usually unknown.
- O history is a strong positive when present, but its absence is not negative.
- Unplayed scenes are unknown, never implicit dislikes.
- Tags and markers vary in completeness and quality; marker end times cannot be
  assumed, and tag hierarchy is supporting evidence rather than a full taxonomy.
- Performer favorites are useful but broad and therefore remain bounded priors.
- Age at recording is preferable to current age when scene and birth dates exist.
- Raw content similarity needs minimum-support and overlap-confidence guards.
- Soft topic models remain diagnostic until administrative tags are reliably clean.

## 5. Architecture

### 5.1 Deployment

The MVP is a self-contained Stash plugin. A standalone service is a fallback only if
process startup or a future resident model proves impossible inside the plugin.

1. Plugin JavaScript registers a Curator route and renders normal Stash cards.
2. Scheduled/manual backend tasks incrementally sync GraphQL data and rebuild model
   state in plugin-owned SQLite.
3. The page requests complete slates, reasons, feedback batches, or replacements.
4. The page fetches current card data for returned IDs through standard GraphQL.
5. Expensive imports and model rebuilds run outside interactive requests.

Interactive calls are batched by slate or feedback group, never one call per card.
The implementation document owns process boundaries and plugin-operation details.

### 5.2 Sidecar SQLite

Plugin-owned SQLite stores the incremental cache, immutable behavior events,
feature/model versions, impressions, reasons, and feedback. It must support durable
migrations, idempotent event ingestion, backup/export, reset, and a configurable
location. Stash GraphQL remains authoritative for library entities; Stash custom
fields are not an event store.

### 5.3 Browser reliability

Unacknowledged browser events survive navigation and transient failure and are
retried idempotently. The implementation document chooses the browser storage
mechanism.

## 6. Data collection

### 6.1 Imported Stash facts

Sync scenes, files, tags, markers, performers, studios, dates, play history, O
history, favorites, and configured physical attributes. Initial sync is paginated;
later sync is incremental by update time/ID with periodic reconciliation.

### 6.2 Historical pseudo-sessions

Stash retains play timestamps and cumulative active play duration, not per-play
duration. Reconstruct a common session shape using:

```text
average_duration = total_play_duration / len(play_history)

for timestamp in play_history:
    emit session(
        started_at = timestamp,
        active_seconds = average_duration,
        provenance = historical_imputed
    )
```

Match O timestamps to the nearest plausible play. Preserve all original aggregates
so reconstruction can be changed later.

Imputed duration has reduced confidence and may create positive evidence only.
An imputed average below 30 seconds is unknown/near-zero duration evidence, never a
short-exit negative. Directly observed repeat timestamps retain normal strength.

### 6.3 Direct web-player sessions

Instrument every scene played in the Stash web UI while Curator's global UI extension
is active, not only while the Curator page is open. Capture:

- active playing seconds, excluding pause/buffering;
- start, maximum, and final positions;
- coarse played ranges;
- seeking and large seek destinations;
- natural completion and subsequent navigation;
- overlapping/nearby markers;
- originating Curator impression, lane, position, and model version.

Store compact summaries, not per-second events. Played ranges, seeks, and marker
overlap are record-only in the MVP. External players are out of scope.

### 6.4 Source semantics

| Source | Taste/Appeal | Current appetite | Choice model | Rank evaluation |
|---|---:|---:|---:|---:|
| Curator impression | yes | yes | yes | yes |
| Other Stash web navigation | yes | yes | no | no |
| Historical import | conservative positive | where timestamps permit | no | no |

The intrinsic meaning of an O, thumb, or direct outcome does not change by source.
Curator origin adds known exposure, position, alternatives, and policy context.

## 7. Training evidence

### 7.1 Provisional relative strength

```text
O                                     +1.00
bare thumbs up                        +0.90
independent repeat                    up to +0.55
meaningful view after saturation      +0.30 to +0.40
short meaningful view                 about +0.10
direct short exit                     about -0.10
short exit then replacement           about -0.25
bare thumbs down                      -1.00
```

These values are training strengths, not Appeal points. Within one occasion, use
the strongest outcome rather than adding O and thumb up independently. Agreement
may add a small amount of confidence.

### 7.2 Viewing time

Direct active viewing below about 30 seconds is a weak negative. Positive evidence
ramps quickly and largely saturates after a few minutes; little additional credit is
needed after roughly five to ten minutes. End-of-file completion has no special
bonus because viewers often jump among useful sections and stop away from the end.

Total watch time alone is never a strong satisfaction label.

### 7.3 Repeat independence

Use a smooth return weight instead of calendar-day rules:

```text
repeat_independence(gap_hours) = 1 - exp(-gap_hours / 6)
repeat_bonus = base_repeat_bonus * repeat_independence(gap_hours)
```

This discounts clustered returns from one viewing occasion while retaining evidence
from genuinely independent returns.

### 7.4 Quick replacement

A directly observed Curator-originated play under 30 seconds followed by another
observed scene selection within five minutes is a modest negative for the first
recommendation. The replacement may originate elsewhere in Stash. No positive
feedback or substantial resumed playback may intervene.

### 7.5 Ignored impressions

Record an impression only after at least half the card is visible for approximately
one second. Ignored impressions and page abandonment are ambiguous and are record-only
in the MVP. Later models may learn a small exposure-aware effect from repeated ignores,
but an ignored card is never direct negative feedback.

## 8. Feature representation

### 8.1 Tag roles

Names are helpful defaults, not authority. Support these roles:

- content;
- performer attribute;
- quality/technical;
- workflow/administrative;
- ignored.

Role resolution is layered:

1. configurable default ignoring bracketed automation tags;
2. configurable exact tag-ID exclusions;
3. configurable regex/prefix rules, recommending `[Workflow: ...]`,
   `[Technical: ...]`, and `[Curator: Ignore]` for future tags;
4. reversible tag-ID overrides in SQLite and the inspector.

Never rename or reparent Stash tags automatically. Show why each tag was excluded.

### 8.2 Positive-unlabeled metadata

Present tags/markers are positive evidence that content exists. Absence is unknown.
Sparse metadata lowers confidence, not Appeal. Marker absence is especially
studio-conditioned.

Use tempered IDF-like rarity weighting. Rare tags may be specific, but typos and
one-offs receive shrinkage and a capped rarity boost. Parent tags receive damped
credit where hierarchy exists.

### 8.3 MVP feature families

```text
general_appeal_index = baseline
                     + bounded(content tags and marker tags)
                     + bounded(content-neighbor evidence)
                     + bounded(performer identity)
                     + bounded(performer similarity/attributes)
                     + bounded(studio)
```

Every family has positive and negative bounds. Rich metadata raises confidence but
cannot grow a family without limit. Log pre-clamp and post-clamp values.

Text topics, NMF topics, and explicit interaction terms are not MVP ranking inputs.

### 8.4 Content neighbors

Build a neutral TF-IDF scene vector from role-filtered scene tags and lower-weight
marker tags. Preserve that catalog vector for diversity and Adventure coverage.

For preference prediction, derive a second vector space. Weight each tag by its
confidence-shrunk positive outcome lift relative to the viewer's training mean, then
renormalize the scene vector. Once discriminative evidence exists, tags with no
positive lift do not create Best Bets neighbor similarity; before any lift can be
estimated, fall back to the neutral vector. Neighbor evidence then combines this
preference-weighted similarity, outcomes, and evidence quantity:

```text
training_mean = weighted_mean(outcome(all labeled scenes), scene confidence)
overlap_confidence = 1 - exp(-shared_informative_features / 4)
evidence_similarity = cosine_similarity * overlap_confidence
neighbor_mean = weighted_mean(outcome(neighbors), evidence_similarity^3)
neighbor_appeal = (neighbor_mean - training_mean) * evidence_confidence
```

This prevents one shared tag from producing false certainty. The component remains
bounded and explanations cite representative enjoyed neighbors plus the
discriminative shared tags that made them close. General catalog tags can still shape
Adventure and diversity without masquerading as evidence of taste. Other reusable
feature affinities are likewise learned as outcome lift relative to the weighted
training mean. This is essential during positive-unlabeled cold start: a below-average
association is model friction, not proof of an explicit dislike.

### 8.5 Performer evidence

Performer favorite is a strong prior, not repeated observations. Performer identity
and similarity/physical attributes remain separate contributions.

Similarity is primarily a bridge for a new or weakly known performer. Apply a smooth
novelty factor based on confidence in the target performer's direct identity evidence:

```text
novelty_weight = max(configured_floor, 1 - identity_confidence)
similarity_contribution = raw_similarity_contribution * novelty_weight
```

Thus a familiar liked performer stands on direct evidence rather than being
double-counted through resemblance to another performer. The raw similarity remains
inspectable.

For multiple performers, use asymmetric aggregation: a strongly liked performer
usually outweighs one mild negative, while the negative remains visible friction.
Explicit performer exclusion is hard. Performer count/structure is a small separate
feature so outcomes can determine whether multi-performer scenes add residual value.

MVP similarity combines performer content profiles with configured physical
attributes; it does not use the user's preference score as a similarity feature.
Derive age at recording when possible. Parse measurements into band,
normalized cup progression, waist, and hips; derive bounded waist-to-hip,
waist-to-height, hip-to-height, and related proportion features. Normalize common
equivalents such as `DD` and `E`, while retaining reduced confidence because sizing
systems and source data vary. Breast-augmentation evidence is an explicit feature:
prefer performer-level metadata, otherwise infer it conservatively from repeated
scene tags with provenance.

Missing attributes contribute no similarity. Correlated raw dimensions and ratios
share a fixed feature-family budget, and no single physical field may dominate.
Explanations translate the resulting profile into restrained plain language such as
“similar height, fuller bust, and pronounced waist-to-hip proportions.” They expose
source uncertainty and avoid presenting approximate metadata as precise anatomy.

Default relative importance within the physical-attribute family is configurable.
Body proportions, age at recording, augmentation evidence, and broad appearance lead;
tattoos are medium-high evidence, piercings medium evidence, and eye color only a low
weight tie-breaker. These weights affect similarity, not general desirability.

### 8.6 Correlation and confidence

Confidence uses effective independent contexts, not raw event count. Ten scenes with
the same performer, studio, and tags strengthen all associations but are not ten
independent confirmations. Recurrence across varied contexts matters more.

## 9. General and scene-specific Appeal

Keep scene ID out of the general model. Maintain an independent direct estimate for
the exact scene:

```text
general_appeal = predict_from_reusable_features(scene)
direct_appeal = estimate_from_exact_scene_outcomes(scene)
direct_confidence = 1 - exp(-effective_direct_evidence / 0.8)

Appeal = (1 - direct_confidence) * general_appeal
       + direct_confidence * direct_appeal
```

A single strong explicit outcome gives direct evidence roughly 70% control; repeated
independent outcomes make it dominate. Repeated meaningful views have no artificial
confidence ceiling. A newer thumbs down suppresses the exact item before scoring,
regardless of predicted Appeal. Direct outcomes also provide bounded training examples
for reusable features.

If reusable metadata cannot explain the outcome, the remaining difference stays as
an honest scene-specific residual rather than poisoning unrelated features.

## 10. Current Fit

Long-term Appeal persists until contrary evidence. Time does not decay taste toward
neutral; it affects confidence and current appetite.

Exact-scene recovery starts with:

```text
scene_recovery(days_since_played) = sigmoid((days_since_played - 90) / 15)
```

Approximate recovery is 2% at day 30, 12% at day 60, 50% at day 90, 88% at day 120,
and 98% at day 150. Center and width are configurable and later learnable.

Recovery controls a non-negative cooldown penalty; it does not multiply signed Appeal:

```text
cooldown_penalty = max(0, Appeal) * (1 - scene_recovery)
Current Fit = clamp(Appeal - cooldown_penalty
                    + other_timing_adjustments)
```

This prevents a recent play from making a disliked scene appear less negative.

Current Fit adjusts Appeal for:

- exact-scene recovery;
- recent performer, studio, and content-type satiation;
- temporary **Not now** feedback.

Unseen status affects confidence and lane policy, not Appeal or Current Fit. Page
diversity belongs to selection utility.

## 11. Lane policies

Eligibility rules, hard exclusions, pruning state, file availability, and explicit
thumb suppression run before every lane policy.

### 11.1 Best Bets

Require high Appeal/Current Fit, sufficient evidence confidence, and adequate
metadata support. Rank candidates by relative library percentiles for content
neighbors, performer evidence, content affinity, and studio evidence. Require either
neighbor evidence corroborated by a distinct anchor family or reliable direct scene
evidence. An unseen favorite-performer scene can qualify, but supporting content
raises reliability. Exploration-only uncertainty cannot qualify.

Apply this relevance gate before slate diversity. Diversity chooses among genuinely
strong candidates; it does not rescue an otherwise middling candidate into Top Picks.

### 11.2 Revisit

Require direct positive evidence plus cooldown recovery. Strong evidence includes O,
durable repeats, thumbs up, or meaningful repeated viewing. Apply recent performer
and content satiation even when the exact scene is old.

### 11.3 Discover

Discover operates near the learned boundary:

- **Adjacent:** strong familiar core plus one unknown;
- **Stretch:** strong core Appeal plus one moderate negative or several unknowns;
- **Frontier:** recognizable connection plus broader uncertainty.

Prefer one named negative assumption at most. Multiple established negatives move
the candidate to Adventure. Explain the challenge:

> Curator has negative evidence for X, but this strongly matches Y and Z. It is
> testing whether X still matters in this combination.

Unknown/non-favorite performer discovery may use content neighbors and performer
similarity. A favorite performer with no played support is still a Discover case if
content provides the real evidence.

### 11.4 Adventure

Adventure is not ascending badness. Compose distinct model-gap subtypes:

- **anchored model gap:** familiar positive anchor plus unusual content;
- **structured combination challenge:** potentially interesting combination not
  represented by additive history;
- **under-covered island:** coherent library region rarely surfaced;
- **model disagreement:** components disagree materially;
- **pure probe:** metadata-complete catalog sample with minimal preference filtering.

Within those subtypes, prioritize under-covered content, distance from established
content neighbors, unknown performers/studios, and usable metadata. These are
coverage-gap signals, not inverted Appeal.

For the first five positions, start with approximately:

```text
2 anchored model gaps
1 structured combination challenge
1 under-covered island
1 pure probe
```

Put the pure probe later and require a plausibility/metadata floor elsewhere. For
You's single Adventure card is anchored by default.

## 12. Slate construction and variety

Do not independently sort and take the top N. Build the slate greedily:

```text
utility(candidate, slate, recent_history) =
    lane_value
  + exploration_or_stretch_bonus
  + uncovered_content_bonus
  - same_performer_penalty
  - same_studio_penalty
  - content_similarity_penalty
```

`lane_value` already contains Current Fit, including cooldown and recent appetite;
slate construction must not apply those adjustments a second time. Its penalties
serve only page and rolling-history variety.

Rules:

- adjacent shared performers are forbidden by default;
- relax only when the candidate pool makes the constraint impossible, and log it;
- studio repetition is a soft penalty, including parent/sibling relationships;
- content similarity is continuous and excludes performer/studio identity;
- apply diversity to the current slate and a rolling recent-history window;
- a large relevance advantage may overcome soft, never hard, penalties;
- retain raw lane value and final utility separately.

Soft NMF topics may later support coverage labels, but continuous similarity is the
MVP authority.

## 13. Learning and feedback propagation

Every direct outcome updates the exact scene strongly. It also supplies a bounded
training example to general feature families.

Do not distribute equal blame or credit to every attached feature. In the MVP,
regularized feature estimates, family bounds, and effective independent contexts
prevent one outcome from moving every attached feature equally. Contribution/ablation
and correlation-aware attribution may refine this later. Repeated evidence across
varied scenes consolidates general taste; detailed aspect feedback overrides automatic
attribution.

Learned preference means persist without contrary evidence. Confidence may widen
after long inactivity, making a soft belief easier to retest without pretending the
taste reversed.

## 14. Inspector

The **Why this?** drawer opens with a short natural-language explanation written in
the voice of a knowledgeable guide. It should combine the strongest reasons into a
coherent statement rather than print feature labels or a template-like score dump:

> You often return to performers with a similar physical profile, and its scenario
> and pacing resemble scenes you have enjoyed. I ranked it a little lower today
> because you recently watched the same studio.

Every claim must be generated from structured reason codes and stored evidence; an
unconstrained language model must not invent rationales. Reusable phrase planning,
aggregation, and surface variation should make explanations sound natural while
remaining deterministic and auditable.

Below that summary, progressive disclosure shows:

1. general Appeal and its top feature-family contributions;
2. direct scene estimate, evidence, and confidence;
3. blended Appeal;
4. Current Fit adjustments;
5. exploration/stretch reason;
6. page/recent-history diversity adjustments;
7. lane eligibility and final selection reason;
8. source events and representative neighbor scenes.

Prefer plain-language comparisons, with ablation detail available on demand—“without
Studio Y, Appeal would be about 8 points higher.” Say **associated with**, not
**caused by**. Similarity explanations should describe a small number of meaningful
traits or content patterns, never enumerate sensitive attributes mechanically.

The global Taste Inspector provides searchable performer, tag, studio, attribute,
and content-neighborhood evidence with confidence, supporting scenes, missingness,
manual priors, exclusions, and tag roles.

## 15. Configuration

Lead with good defaults and understandable controls. Put implementation details in
advanced/debug settings.

| Group | User-facing controls |
|---|---|
| Feed | page size, For You mixture, position conservatism |
| Cooldown | recovery center/width, Revisit strength |
| Diversity | adjacent performer rule, studio/content penalties, history horizon |
| Exploration | Discover/Adventure shares, intensity, soft-boundary challenges |
| Signals | relative O/thumb/repeat/view weights, view saturation, quick replacement |
| Metadata | tag roles/rules, parents, markers, physical attributes, text features |
| Feedback | pruning behavior, hard exclusions, retest policy |
| Storage/model | SQLite path, refresh schedule, model/version status |

Physical performer attributes are enabled by default but configurable. Presets such
as Conservative, Balanced, and Adventurous may sit above the effective controls.

## 16. Evaluation

### 16.1 Offline

- time-based holdout of recent positive sessions;
- rank held-out positives against sampled unknowns;
- coverage and concentration by performer, studio, and content neighborhood;
- explanation and metadata-confidence audits;
- regression fixtures from reviewed recommendation slates.

Keep private, user-reviewed slates as local regression fixtures. Repository fixtures
must use synthetic or explicitly shareable data and must not expose library contents,
behavior totals, candidate IDs, or personal evaluation notes.

### 16.2 Online

Log impression ID, model/feature version, lane, position, policy score, component
scores, reason snapshot, opens, plays, outcomes, and feedback. Log a selection
probability only when the policy genuinely defines one; never invent propensities for
a deterministic ranker. Measure:

- selection and positive-outcome rate by lane/position;
- repeat and O rates without treating absent O as failure;
- explicit feedback and stretch acceptance;
- unique performers/studios and longest streak;
- catalog/content coverage over 7/30 days;
- model corrections and Adventure information gain;
- Best Bets regret guardrail as exploration increases.

## 17. MVP and later work

### Validation slice before the product MVP

Before building the complete Stash page, implement a read-only vertical slice that
syncs metadata, builds the deterministic model, produces every lane with reasons, and
exports an HTML evaluation report. This validates ranking and explanations without
coupling them to player instrumentation or full UI work. It is an implementation
milestone, not a separate product mode.

### MVP: deterministic and inspectable

- Stash-native page and five tabs;
- incremental GraphQL-to-SQLite cache;
- historical pseudo-sessions;
- direct player-session logging;
- tag-role filtering;
- bounded additive affinities and content neighbors;
- direct-scene blending and smooth cooldown;
- lane policies and slate diversity;
- reasons, thumbs, detailed feedback, and pruning review;
- reviewed-slate regression fixtures.

### Later: learned policy

- regularized/Bayesian satisfaction and choice heads;
- posterior/Thompson exploration;
- propensity-aware evaluation;
- learned replay intervals;
- selected interactions after residual diagnostics.

### Optional research

- NMF topics for coverage and explanations;
- lexical title/description baseline, then optional local embeddings;
- weak tag inference with provenance, never automatic Stash writes;
- learned performer embeddings and residual similarity features;
- direct read-only Stash DB adapter only if incremental GraphQL is insufficient.

## 18. Product identity

The working name is **Stash Curator**. It is more immediately legible than earlier
candidates and remains broad enough for future performer, studio, gallery, or other
library recommendations. “Curator” can sound static on its own, so product language
must consistently emphasize learning and timing.

Working tagline: **Navigate your library, guided by your taste.**

Lane names remain functional rather than themed.

## 19. Remaining product questions

1. Initial page size and continuation behavior.
2. Whether presets lead configuration or appear alongside direct controls.
3. Exact tag-role defaults beyond known automation and technical tag patterns.
4. How much non-favorite performer discovery Discover should reserve explicitly.

## Appendix: repository privacy boundary

The implementation-facing design is intentionally independent of any one library.
Detailed GraphQL experiments, library audit statistics, candidate IDs, and personal
evaluation notes remain local and excluded from version control.
Only generalized conclusions, synthetic fixtures, and reproducible read-only audit
tools may enter the public repository.
