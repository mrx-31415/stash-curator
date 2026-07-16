# Stash Curator implementation plan

Status: implementation plan, 2026-07-15
Product: **Stash Curator**
Tagline: **Navigate your library, guided by your taste.**

This document turns the product and recommendation design into executable work. The
design document is authoritative for user promises and model semantics. This plan is
authoritative for component boundaries, delivery order, interfaces, tests, and the
definition of done. If implementation convenience conflicts with the design, update
the implementation rather than silently changing the product.

## 1. Delivery objective

Deliver Curator in two gates:

1. a read-only validation slice that syncs real Stash data, builds the deterministic
   model, produces every lane, explains each result, and exports an HTML report;
2. a Stash-native plugin that adds the five-tab view, durable feedback, impression
   logging, and global web-player session capture.

The first gate proves recommendation quality before UI and event plumbing dominate
the work. The second turns the validated core into the product.

## 2. Scope and non-goals

### 2.1 First validation gate

Included:

- read-only Stash GraphQL client;
- incremental SQLite cache;
- historical pseudo-session reconstruction;
- tag roles and feature construction;
- deterministic Appeal, Current Fit, lane, and slate scoring;
- performer and scene similarity;
- structured reasons and deterministic natural-language explanations;
- CLI and self-contained HTML evaluation report;
- synthetic tests plus private local evaluation.

Excluded:

- Stash mutations;
- permanent player instrumentation;
- production feedback controls;
- Bayesian/Thompson exploration;
- language-model-generated explanations;
- title/description embeddings and NMF as ranking inputs;
- automatic metadata correction or library pruning.

### 2.2 Product MVP gate

Adds:

- Stash-native Curator route and five tabs;
- global Stash web-player session capture;
- impression and choice logging;
- thumbs and detailed feedback;
- pruning review queue and hard exclusions;
- scheduled/incremental rebuilds;
- durable browser retry queue;
- inspector and configuration UI.

## 3. Repository and privacy boundary

The standalone repository will be `stash-curator`:

```text
stash-curator/
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── stash-curator.yml
├── docs/
│   ├── design.md
│   ├── implementation.md
│   └── decisions/
├── curator/
│   ├── cli.py
│   ├── config.py
│   ├── graphql/
│   ├── storage/
│   │   └── sql/
│   ├── events/
│   ├── features/
│   ├── model/
│   ├── ranking/
│   ├── explanations/
│   └── reporting/
├── ui/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
├── scripts/
└── .github/workflows/
```

Never commit:

- Stash URLs, API keys, cookies, or filesystem paths;
- library exports, SQLite databases, or GraphQL responses;
- real scene/performer IDs or names in fixtures;
- behavior totals, reviewed recommendations, or personal evaluation notes;
- generated local reports.

Use synthetic IDs and metadata in repository tests. Keep private configuration and
evaluation artifacts outside the repository. Add defensive ignore patterns before
the first data sync.

## 4. Runtime decisions and deployment gate

### 4.1 Validation runtime

Use Python managed by `uv` for the validation slice. Prefer Python 3.12+ and keep the
core dependency-light. Initial expected dependencies:

- a small HTTP client for GraphQL;
- SQLite from the standard library;
- NumPy/SciPy and scikit-learn for sparse vectors and nearest neighbors;
- a Markdown/templating library only if the report cannot remain dependency-light.

Pin all dependencies in `uv.lock`. Ranking must be deterministic for a fixed dataset,
configuration, model version, and seed.

### 4.2 Plugin runtime spike

Before implementing the full UI, prove one supported deployment path inside the
target Stash Docker setup:

1. plugin task starts the backend;
2. backend can resolve the Stash endpoint and authenticate through plugin context;
3. backend can create and migrate SQLite in persistent plugin storage;
4. one batched operation returns a synthetic slate to the UI;
5. restart preserves state;
6. failure and cancellation produce useful Stash logs.

Candidate packaging strategies, in preference order:

1. packaged Python runtime supported by the Stash plugin ecosystem;
2. bundled standalone executable built from the validated Python core;
3. a compiled backend adapter around a portable core;
4. a separate sidecar service only if plugin-local execution cannot satisfy the
   design.

Record the result in `docs/decisions/001-backend-runtime.md`. Do not couple model
code to a plugin transport before this decision.

## 5. Configuration contract

Configuration is layered:

```text
built-in defaults
  < repository/user config file
  < sidecar settings changed in the UI
  < CLI overrides for validation only
```

The effective configuration is stored with each model version and report. At minimum
it contains:

- Stash connection and sync page size;
- SQLite path and migration policy;
- tag-role rules and tag-ID overrides;
- enabled feature families and family bounds;
- signal strengths and viewing-time curve;
- direct-evidence confidence curve;
- cooldown center and width;
- lane thresholds and For You mixture;
- performer-attribute weights;
- diversity windows and penalties;
- deterministic random seed;
- report redaction mode.

Secrets are supplied through environment variables or an ignored local file and are
never serialized into model metadata or reports.

## 6. Command-line contract

The validation slice exposes:

```text
curator doctor
curator sync [--full]
curator build-model
curator recommend --lane <lane> --count <n> [--json]
curator similar-performers --performer-id <id> --count <n>
curator explain --scene-id <id>
curator report [--output <path>]
curator db migrate|status|backup
```

Every command supports structured JSON output for tests and agent automation. Human
output goes to stdout; diagnostics go to stderr. Failures return non-zero status and
never leave a partially published model version.

`doctor` checks connectivity, schema compatibility, writable storage, migrations,
metadata availability, and configuration without modifying Stash.

## 7. Component boundaries

```text
Stash GraphQL
     │
     ▼
Sync adapter ──► normalized cache ──► event/session normalization
                                         │
                                         ▼
                                 versioned feature builder
                                         │
                                         ▼
                                  deterministic model
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                    lane policy                    reason graph
                         │                               │
                         └──────────► slate builder ◄────┘
                                         │
                                  CLI / report / UI
```

Rules:

- GraphQL models never leak directly into scoring code.
- Cached source facts are separate from derived features.
- Immutable events are separate from mutable aggregate/model state.
- Ranking returns IDs and structured reasons, not rendered cards.
- Explanation prose is rendered from reason codes, never recomputed from display
  strings.
- A model version is immutable after publication.

## 8. SQLite data model

Use ordered SQL migrations packaged under `curator/storage/sql`. Foreign keys are
enabled. Operational timestamps use UTC epoch milliseconds; source-domain dates such
as scene date and performer birthdate remain normalized text.

The sidecar is not a second authoritative library database. It has two deliberately
different kinds of data:

- a rebuildable, normalized cache of the subset read from Stash that ranking needs;
- Curator-owned behavioral and derived state that Stash does not represent.

The source cache overlaps with Stash on stable IDs, selected display metadata,
relationships, tags and markers, file availability/duration, favorites/ratings, and
play/O history. It does not copy media, images, complete GraphQL responses, or every
Stash field. Stash remains authoritative: synchronization updates the cache and full
reconciliation removes records no longer present upstream.

Curator-owned tables contain impressions, future direct play sessions, normalized
outcomes, feedback, exclusions/pruning decisions, feature snapshots, affinities,
scores, explanations, lane classifications, and recommendation history. These are
kept separate because they need immutable provenance, versioning, and inexpensive
local joins that the Stash schema/API does not provide. Deleting the sidecar loses
that Curator-owned learning history, but the source cache and historical projection
can otherwise be rebuilt from Stash.

### 8.1 Source cache

| Table | Purpose | Required identity |
|---|---|---|
| `source_scene` | normalized scene facts and behavior aggregates | `scene_id` |
| `source_file` | duration and availability | `file_id` |
| `source_performer` | identity, favorite, physical attributes | `performer_id` |
| `source_studio` | studio and parent relation | `studio_id` |
| `source_tag` | source name and hierarchy | `tag_id` |
| `scene_performer` | scene/performer relation | composite |
| `scene_tag` | scene/tag relation and provenance | composite |
| `scene_marker` | temporal tag evidence | `marker_id` |
| `source_play` | source play timestamps | composite stable key |
| `source_o` | source O timestamps | composite stable key |
| `sync_cursor` | cursor/watermark and reconciliation state | entity type |

Keep source payload hashes or update timestamps to skip unchanged rows. Preserve raw
source aggregates required to reconstruct pseudo-sessions, but do not retain entire
GraphQL payloads by default.

### 8.2 Curator events

| Table | Purpose |
|---|---|
| `behavior_event` | immutable normalized play/outcome/feedback event |
| `play_session` | compact observed or historical-imputed session |
| `impression` | request context, lane, model/config version |
| `impression_item` | shown item, position, policy score, reason snapshot |
| `feedback` | thumb/detail feedback and reversals |
| `exclusion` | current hard/temporary suppression state |
| `pruning_candidate` | reversible review queue |

Each incoming browser event has a client-generated idempotency key. Store provenance,
confidence, source, timestamps, and related impression/session IDs explicitly.

### 8.3 Derived model state

| Table | Purpose |
|---|---|
| `feature_definition` | stable feature ID, family, provenance, version |
| `tag_role` | configuration-versioned role and resolution reason |
| `entity_feature` | sparse entity/feature values |
| `model_version` | immutable build metadata and publication state |
| `feature_affinity` | learned affinity, confidence, support, family |
| `direct_scene_state` | direct estimate, effective evidence, confidence |
| `recommendation_history` | selected/shown history used for cooldown/diversity |

Build into a new unpublished model version inside one transaction or staging tables.
Publish it atomically after validation checks pass.

Versioned snapshots need bounded retention. Keep the current published model, models
referenced by retained impressions/evaluations, and a small configurable number of
recent superseded builds. Delete older reason, score, lane, affinity, and feature
snapshots transactionally, then offer an explicit maintenance command to reclaim
SQLite free pages. The validation prototype does not implement this policy yet, so
derived snapshots currently accumulate.

## 9. GraphQL synchronization

### 9.1 Queries

Implement named, paginated queries for:

- server version/schema capability;
- scenes and files;
- tags and parents;
- markers and their tags;
- performers and configured attributes;
- studios and parent studios;
- play and O history;
- favorites and ratings where available.

Centralize query documents and response adapters. Schema-version conditionals belong
in the adapter, not downstream model code.

### 9.2 Initial and incremental sync

Initial sync:

1. inspect capabilities;
2. migrate the sidecar;
3. fetch entities in bounded pages;
4. normalize and upsert each page transactionally;
5. record page progress;
6. reconcile relationship tables;
7. mark the snapshot complete.

Incremental sync uses update timestamps and stable IDs where supported, plus periodic
full ID reconciliation to detect deletions. Interrupted sync resumes safely. A slate
continues using the last published complete model while a sync/build is in progress.

The implemented sync policy has two modes:

- normal sync reads each entity newest-first by `updated_at` and stops after crossing
  the last completed watermark; the boundary page is upserted again so equal
  timestamps cannot create a brittle hard edge;
- full sync traverses every entity by stable ascending ID, records IDs in a run-local
  seen set, and reconciles deletions only after all traversals complete.

Normalized records, full-sync seen IDs, the pending high watermark, and the next page
number commit in one SQLite transaction. A failed run retains that page boundary and
is resumed on the next invocation. Completed entity traversals are skipped during
resume. Published models are not read or modified by synchronization.

### 9.3 Safety

The validation client contains no mutation documents. Integration tests assert that
every operation type is `query`. The later plugin isolates Stash mutations, if any,
behind an explicit write adapter; recommendation and feedback storage remain sidecar
writes unless the design specifically requires otherwise.

## 10. Event and session normalization

Use one normalized outcome scale in `[-1, 1]` with signal provenance and confidence.
Provisional strengths come from the design:

```text
O                                +1.00
thumb up                         +0.90
independent repeat               up to +0.55
saturated meaningful view        +0.30 to +0.40
short meaningful view            about +0.10
direct short exit                about -0.10
quick replacement               about -0.25
thumb down                       -1.00
```

For one viewing occasion, select the strongest outcome rather than summing correlated
signals. Supporting agreement may raise confidence slightly but cannot exceed the
family cap.

### 10.1 Historical pseudo-sessions

For each scene with play timestamps and cumulative duration:

```text
imputed_seconds = cumulative_duration / number_of_plays
```

Create one session per timestamp with `historical_imputed` provenance. Imputed
duration can create reduced-confidence positive evidence only. It never creates a
short-exit negative. Preserve the source aggregates so reconstruction can be rebuilt.

### 10.2 Direct sessions

Aggregate player events into compact sessions containing active seconds, positions,
coarse played ranges, seeks, completion, marker overlap, source route, and originating
impression. Ranges/seeks/markers are record-only in the MVP.

The viewing contribution is a configurable smooth curve that:

- is weakly negative below approximately 30 directly observed seconds;
- crosses neutral near that threshold;
- rises quickly;
- largely saturates after several minutes;
- gives no special end-of-file bonus.

The implemented provisional curve is continuous at the neutral threshold `T`:

```text
direct_view(t < T)  = negative_floor * (1 - t / T)
view(t >= T)        = positive_cap * (1 - exp(-(t - T) / rise_seconds))
```

Defaults are `T = 30 seconds`, `negative_floor = -0.10`,
`positive_cap = +0.35`, and `rise_seconds = 90`. This yields roughly `+0.10` at one
minute and is close to saturation after several minutes. Historical-imputed duration
uses only the non-negative branch and reduced confidence. Completion remains
record-only and cannot alter this curve.

### 10.3 Repeats and replacement

```text
repeat_independence(gap_hours) = 1 - exp(-gap_hours / 6)
```

Detect a quick replacement when a Curator-originated play ends under the configured
threshold and another observed Stash scene is selected within the configured window,
without intervening positive feedback or substantial resumed playback.

`EventCalibration` owns every provisional strength, confidence, threshold, and time
constant. Historical reconstruction matches O timestamps one-to-one to the nearest
play inside a configurable plausibility window; unmatched O events remain standalone
exact-scene successes. The sidecar projection is deterministic and rebuildable from
preserved `source_scene`, `source_play`, and `source_o` facts. Source reads and derived
projection replacement commit in one SQLite transaction.

## 11. Feature construction

### 11.1 Tag roles

Resolve tag role in this order:

1. explicit tag-ID override;
2. configured exact/prefix/regex rule;
3. bracketed automation default;
4. content default.

Store both role and resolution reason. Present metadata is evidence; missing metadata
is unknown. Apply tempered IDF, minimum support, shrinkage for one-offs, capped rarity,
and damped parent-tag credit.

### 11.2 Scene vectors

Build sparse scene vectors from:

- content scene tags at full configured weight;
- marker tags at lower weight unless also scene tags;
- optional derived content clusters only after the MVP.

Exclude performer and studio identity from content vectors so diversity can measure
content independently.

### 11.3 Performer vectors

Keep these blocks separately inspectable:

- aggregated performer scene-content profile;
- categorical appearance attributes;
- numeric dimensions and derived proportions;
- age-at-recording distribution;
- tattoos, piercings, and augmentation status;
- identity preference evidence, which is not a similarity feature.

Normalize cup aliases such as `DD → E` and `DDD → F` with reduced metadata confidence.
Prefer direct performer augmentation metadata; use repeated scene evidence only as a
lower-confidence fallback. Missing attributes add no similarity.

Initial relative attribute weights are configuration defaults:

```text
eye color       low
piercings       medium
tattoos         medium-high
hair/ethnicity  medium-high
proportions, age, augmentation, content profile  leading
```

Use block normalization so a dense block cannot dominate merely by having more
columns. Save per-block similarities for explanations.

## 12. Deterministic model

### 12.1 General Appeal

Internal Appeal is a signed index in `[-1, 1]`. Estimate bounded contributions for:

- content tags and markers;
- content neighbors;
- performer identity;
- performer similarity/attributes;
- studio.

Each feature affinity stores mean, effective support, confidence, and provenance.
For the MVP, collapse all evidence for one scene into one confidence-weighted scene
label before training reusable features. Because the initial history is mostly
positive-unlabeled, learn reusable preferences as lift relative to the typical
training outcome rather than treating every viewed feature as an absolute positive.
For feature `f`:

```text
training_mean = weighted_mean(scene_outcome_s, scene_confidence_s)
relative_outcome_s = scene_outcome_s - training_mean
support_f = sum(scene_confidence_s for scenes containing f)
affinity_f = sum(scene_confidence_s * relative_outcome_s)
             / (prior_strength_f + support_f)
confidence_f = 1 - exp(-support_f / confidence_scale_f)
contribution_f = feature_value_f * affinity_f * confidence_f
```

This prevents many plays of one scene from masquerading as many independent feature
contexts and prevents a positive-only history from pushing nearly every candidate to
the score ceiling. A negative learned affinity means "less associated with success
than the viewer's observed baseline," not an explicit dislike. Family totals are
clamped to configured positive and negative bounds before summation. Confidence is
combined across distinct evidence families so correlated tags cannot create certainty
merely through volume. Record distinct-scene and distinct-studio/performer-context
counts for inspection; correlation-aware context weighting may replace the simple
scene-level collapse later without changing stored events. The MVP has no learned
interaction model.

### 12.2 Content neighbors

```text
tag_preference_strength = max(0, affinity_f) * confidence_f
preference_vector_tag = catalog_vector_tag
                        * normalized(tag_preference_strength)
overlap_confidence = 1 - exp(-shared_informative_features / 4)
evidence_similarity = cosine_similarity * overlap_confidence
neighbor_mean = weighted_mean(outcome, evidence_similarity^3)
neighbor_lift = neighbor_mean - training_mean
neighbor_appeal = neighbor_lift * evidence_confidence
```

Require minimum feature and outcome support. Keep neighbor contribution bounded and
retain the representative neighbors used in the reason graph. Preserve the unmodified
catalog vector separately for diversity and Adventure coverage. If no positive tag
lift exists yet, use the catalog vector as the cold-start fallback; otherwise,
zero-lift generic tags do not create preference-neighbor overlap.

### 12.3 Performer novelty bridge

For each target performer, retain raw profile similarity but scale its score and
confidence by `max(novelty_floor, 1 - identity_confidence)`. Favorite and sufficiently
supported direct identity evidence therefore suppress redundant similarity. New or
weakly known performers retain the full bridge from similar known performers.

### 12.4 Direct scene state

```text
direct_appeal = confidence_weighted_mean(exact_scene_outcomes)
direct_confidence = 1 - exp(-effective_direct_evidence / 0.8)
Appeal = (1 - direct_confidence) * general_appeal
       + direct_confidence * direct_appeal
```

A current thumbs down suppresses the exact scene before scoring. Never-show and file
unavailability are hard exclusions. Preserve unexplained direct residual instead of
forcing unrelated reusable features to explain it.

### 12.5 Current Fit

```text
recovery = sigmoid((days_since_played - cooldown_center_days)
                   / cooldown_width_days)
cooldown_penalty = max(0, Appeal) * (1 - recovery)
Current Fit = clamp(Appeal - cooldown_penalty + timing_adjustments)
```

Timing adjustments include recent performer/studio/content satiation and Not-now.
Unseen status affects confidence and lane policy, not Appeal or Current Fit.
Initial defaults are `cooldown_center_days = 90` and `cooldown_width_days = 15`.

## 13. Lane policy

All lanes first apply file availability, hard exclusions, pruning state, and current
thumb suppression.

Thresholds below are provisional calibration parameters, not product promises. Keep
them named and configurable rather than scattering literals through code.

### Best Bets

- high Current Fit;
- sufficient evidence and metadata confidence;
- high relative relevance across the eligible library, using content-neighbor,
  performer, content-tag, and studio percentiles;
- either neighbor evidence corroborated by a distinct anchor family, or reliable
  direct scene evidence;
- no exploration-only qualification;
- no recorded viewing history.

Rank qualified candidates primarily by relative relevance, then Current Fit and
confidence. This shortlist-first policy keeps diversity from promoting merely
adequate candidates over clearly stronger matches.

### Revisit

- recorded viewing history;
- direct positive evidence;
- sufficient exact-scene recovery;
- durable repeat, O, thumb up, or repeated meaningful viewing;
- recent performer/content satiation still applies.

### Discover

Classify as adjacent, stretch, or frontier. Require a recognizable positive anchor.
Allow one moderate negative assumption or several unknowns; multiple established
negatives move the item to Adventure. Store the challenged assumption explicitly.

### Adventure

Classify as anchored model gap, structured combination challenge, under-covered
island, model disagreement, or pure probe. The first page targets two anchored gaps,
one combination, one island, and one later pure probe. For You receives anchored
Adventure by default.

Rank Adventure using under-covered content, distance from known content neighbors,
unknown performers/studios, and metadata confidence. This makes the lane a structured
probe of the model's blind spots rather than an inverse Best Bets list.

### For You

Construct one slate with soft targets for a 20-card page:

```text
10–12 Best Bets
 3–4 Revisit
 3–5 Discover
 about 1 anchored Adventure
```

Borrow unused capacity without violating hard rules. Earlier positions are more
conservative.

## 14. Slate builder

Generate a larger eligible pool per lane, then select greedily:

```text
while slate not full:
    for candidate in remaining:
        utility = lane_value(candidate)
                + exploration_or_stretch_bonus(candidate)
                + uncovered_content_bonus(candidate, slate)
                - performer_diversity_penalty(candidate, slate, history)
                - studio_diversity_penalty(candidate, slate, history)
                - content_similarity_penalty(candidate, slate, history)
    choose deterministic argmax using stable ID as final tie-breaker
```

Adjacent shared performers are forbidden by default. Relax only if explicitly
configured and the pool cannot fill, and emit a diagnostic. Studio and continuous
content repetition are soft. Do not reapply cooldown or appetite; lane value already
contains Current Fit.

Return raw Appeal, Current Fit, lane value, final utility, eligibility decisions,
penalties, and reason IDs separately.

## 15. Structured reasons and natural language

The ranker produces a reason graph, not prose. A reason contains:

- stable reason code;
- subject entity/feature IDs;
- direction and bounded magnitude;
- confidence and provenance;
- comparison or representative evidence;
- visibility/sensitivity level;
- model and feature version.

Initial reason-code families:

```text
appeal.tag_positive / appeal.tag_negative
appeal.performer_identity
appeal.performer_similar
appeal.studio
appeal.content_neighbor
direct.positive / direct.negative / direct.residual
fit.cooldown / fit.satiation / fit.not_now
explore.unknown / explore.challenge / explore.coverage / explore.disagreement
diversity.performer / diversity.studio / diversity.content
eligibility.excluded / eligibility.lane
```

The explanation planner selects a few non-redundant reasons, orders them as positive
core → qualification/challenge → current adjustment, and renders deterministic phrase
templates with controlled variation. It must not infer facts absent from the reason
graph. Detailed inspection shows scores, evidence, and ablations on demand.

Golden tests assert both reason graphs and representative prose. Prose snapshots may
change intentionally; reason semantics require explicit versioning.

## 16. HTML evaluation report

Generate one self-contained local HTML file containing:

- build/config/model summary;
- For You and each individual lane;
- scene metadata sufficient for local identification;
- lazy-loaded cover images and links back to the corresponding Stash scene when a
  Stash URL is supplied;
- natural-language Why-this summary;
- Appeal, Current Fit, confidence, lane value, and final utility;
- strongest positive/negative/unknown reasons;
- representative scene neighbors;
- lane subtype and diversity adjustments;
- optional local-only review controls or printable review fields.

Default repository/test reports use synthetic data. A private report may include real
names and IDs but is written only to an ignored output directory. The report generator
must support redacted output for bug reports.

## 17. Plugin integration

After the validation gate:

### 17.1 UI contract

- one Curator route;
- For You, Best Bets, Revisit, Discover, Adventure tabs;
- normal Stash scene cards and navigation;
- progressive Why-this drawer;
- thumbs and detail feedback;
- Familiar/Adventurous control;
- inspector and advanced configuration;
- loading, empty, stale-model, rebuilding, and error states.

The UI requests one complete slate operation and then current card facts through
Stash GraphQL. Never make one backend process call per card.

### 17.2 Browser events

The global extension records qualified impressions and compact player summaries for
all Stash web plays while active. Events receive client UUIDs, enter a durable retry
queue, and are acknowledged in batches. No essential event depends on unload-time
network delivery.

### 17.3 Backend operations

Define transport-neutral operations before mapping them to Stash plugin calls:

```text
health
get_slate
replace_item
get_explanation
submit_events
submit_feedback
get_inspector_entity
get_config / update_config
start_sync / start_build / get_job_status
```

Every response includes schema version and relevant model/config versions.

## 18. Testing strategy

### Unit

- signal and viewing curves;
- historical reconstruction;
- tag role resolution;
- cup normalization and body proportions;
- missing-value similarity;
- confidence and cooldown curves;
- lane classification;
- diversity penalties and hard adjacency;
- reason planning and rendering.

### Integration

- GraphQL adapter against recorded synthetic responses;
- initial, incremental, interrupted, and deletion reconciliation sync;
- migration from every released schema version;
- atomic model publication;
- CLI JSON contracts;
- full synthetic sync → model → report path;
- plugin task transport spike.

### Property/invariant

- absent metadata never acts as explicit dislike;
- adding unrelated tags cannot create unbounded Appeal;
- cooldown never improves a negative Appeal;
- a current thumb down always suppresses the exact scene;
- adjacent shared performers never occur under default policy;
- deterministic inputs produce identical slates and reasons;
- no validation GraphQL operation is a mutation;
- private identifiers never appear in committed fixtures.

### Human evaluation

Maintain private reviewed slates by model version. Review lane correctness, ordering,
explanation truthfulness, variety, and obvious misses. Convert only generalized bugs
into synthetic regression fixtures.

## 19. Observability and versioning

Every slate records:

- model, feature, reason-schema, config, and code versions;
- sync watermark;
- lane and subtype;
- raw component values and clamps;
- eligibility decisions;
- diversity adjustments;
- stable deterministic seed/tie-break context;
- latency by phase.

Provide diagnostics for stale cache/model, excluded candidate counts, relaxed rules,
missing metadata, feature-family saturation, and explanation failures. Logs redact
secrets and avoid dumping full library objects.

## 20. Work packages

Each package is independently assignable after its dependencies are complete.

### WP-00 — Repository foundation

Status: complete.

Dependencies: approved design and implementation plan.

Deliverables:

- standalone repository, license, README, docs;
- Python/uv project and locked dependencies;
- formatting, linting, type checking, tests, and CI;
- privacy-safe `.gitignore` and synthetic fixture policy;
- version module and changelog convention.

Acceptance:

- clean checkout passes all CI commands;
- no network or real Stash is required for unit tests;
- package and CLI help build reproducibly.

### WP-01 — SQLite foundation

Status: complete.

Dependencies: WP-00.

Deliverables: migration runner, initial schema, transactions, model publication,
backup/status commands.

Acceptance: migration tests pass from empty and every fixture version; interrupted
build cannot replace the published model.

### WP-02 — GraphQL adapter and sync

Status: complete.

Dependencies: WP-01.

Deliverables: capability probe, named queries, response adapters, paginated initial
sync, incremental sync, reconciliation, doctor command.

Acceptance: synthetic integration covers resume and deletion; validation client
contains and sends queries only.

Implemented with named read-only queries for capabilities, tags, studios,
performers, and scenes (including files, markers, relationships, play history, and O
history). Final query documents and both sort modes were validated read-only against
Stash v0.31.1; committed fixtures remain entirely synthetic.

### WP-03 — Event normalization

Status: complete.

Dependencies: WP-01, WP-02.

Deliverables: historical pseudo-sessions, normalized outcome records, repeat and
quick-replacement functions, direct-session input contract.

Acceptance: all curves and invariants have boundary tests; historical imputations
cannot create negative exits.

Implemented with a typed direct-player session contract, centralized calibration,
smooth view/repeat curves, strongest-signal occasion collapse, conservative
historical reconstruction, one-to-one O matching, quick-replacement detection, and
an idempotent SQLite historical projection. Direct ranges, seeks, markers, and
completion are captured by contract but remain record-only as designed.

### WP-04 — Feature pipeline

Status: complete.

Dependencies: WP-02.

Deliverables: tag roles, sparse scene vectors, performer profiles, physical-attribute
normalization, feature versioning.

Acceptance: deterministic feature matrix; missing fields add no similarity; admin
tags are explainably excluded; block contributions are inspectable.

Implemented with precedence-based tag roles, versioned sparse scene vectors,
separate content/performer/studio/structure families, missing-aware performer
profiles, age-at-recording and physical-attribute normalization, DD-to-E cup
normalization, augmentation state, and inspectable weighted similarity blocks.
Feature IDs, source/config fingerprints, and stable ordering make repeated builds
reproducible.

### WP-05 — Deterministic model

Status: complete.

Dependencies: WP-03, WP-04.

Deliverables: feature affinities, neighbor evidence, direct scene state, Appeal,
Current Fit, confidence, atomic build command.

Acceptance: scale/bounds invariants pass; direct evidence and cooldown behave as the
design specifies; a complete synthetic model builds reproducibly.

Implemented with baseline-centered feature affinities, lift-based sparse
content-neighbor evidence, performer identity and profile similarity,
studio/structure contributions, family clamps, evidence-family confidence,
exact-scene evidence blending, smooth cooldown and satiation, hard eligibility state,
and atomic publication. `build-model` rebuilds the historical projection and
publishes a deterministic model without replacing the prior model on failure.

### WP-06 — Lanes and slate builder

Status: complete.

Dependencies: WP-05.

Deliverables: eligibility, five lane policies, Adventure subtypes, For You mixture,
greedy diversity selection, recommend CLI.

Acceptance: golden synthetic slates meet lane and adjacency rules; soft penalties
change order without acting as exclusions; output includes full score decomposition.

Implemented with relative, corroborated Best Bets qualification; direct-evidence
Revisit; anchored Discover; coverage-gap Adventure ranking and five Adventure
subtypes; the configured For You lane mixture; default hard
adjacent-performer separation; soft performer, studio, content, and recent-history
variety penalties; stable tie-breaking; and complete JSON score decomposition from
`recommend`.

### WP-07 — Reasons and report

Status: complete.

Dependencies: WP-05, WP-06.

Deliverables: reason schema, planner, deterministic prose renderer, explain CLI,
self-contained HTML report, redaction mode.

Acceptance: every recommendation has truthful structured reasons; report renders all
lanes; repository golden output contains synthetic data only.

Implemented with a versioned reason graph derived only from stored model and ranking
decomposition, deterministic positive-core/exploration/adjustment planning,
controlled natural-language templates, `explain`, and a self-contained five-lane
HTML inspector. Redaction aliases scene, performer, studio, and tag IDs and names.
Synthetic acceptance tests cover exact provenance, representative prose, both CLI
contracts, all report lanes, redaction, and the full sync-to-model-to-report path.

### Gate A — Recommendation validation

Run private sync/build/report. Review at least several pages across all lanes and a
set of performer-neighbor queries. Record model defects, turn generalizable defects
into synthetic tests, adjust centralized calibration values, and repeat.

Exit when:

- Best Bets and Revisit are consistently useful;
- Discover challenges one explainable assumption;
- Adventure shows the intended subtype gradient;
- For You is varied without sacrificing early relevance;
- explanations are truthful and useful;
- no unresolved defect requires changing the product design.

### WP-08 — Plugin runtime spike

Dependencies: Gate A.

Deliverables: runtime ADR, minimal manifest/task/UI bridge, persistent SQLite test,
packaging proof in target Docker.

Acceptance: restart-safe round trip and logs work from an installed plugin package.

### WP-09 — Stash-native UI

Dependencies: WP-07, WP-08.

Deliverables: route, tabs, cards, lane controls, Why-this drawer, inspector shell,
loading/error/stale states.

Acceptance: all five lanes work without per-card backend calls; navigation uses normal
Stash behavior; keyboard/touch access exposes essential explanations.

### WP-10 — Events and feedback

Dependencies: WP-03, WP-08, WP-09.

Deliverables: qualified impressions, global player summaries, durable retry queue,
thumb/detail feedback, exclusions, pruning queue.

Acceptance: duplicate delivery is harmless; navigation/restart does not lose queued
events; thumb-down and never-show semantics match the design.

### WP-11 — Jobs, configuration, and release

Dependencies: WP-08 through WP-10.

Deliverables: scheduled/manual sync/build, job status, configuration UI, backup/reset,
package archive, source index, release CI, compatibility declaration.

Acceptance: clean Stash installation can add the source, install Curator, build a
model, use the page, restart, update, and uninstall without losing Stash-owned data.

### Gate B — Product MVP

Exit when all product-MVP bullets in the design are implemented, integration and
privacy tests pass, upgrade/uninstall behavior is documented, and a private end-to-end
trial produces useful recommendations from newly collected events.

## 21. Open decisions before WP-00

Resolve or explicitly defer:

1. final license, provisionally AGPL-3.0 to align with Stash and the existing plugins;
2. supported Stash version range and initial platform matrix;
3. page size and continuation behavior;
4. initial lane threshold values and configuration presets;
5. initial tag-role defaults that are generic enough to publish;
6. whether report review controls write temporary local annotations;
7. how many private review rounds are required for Gate A.

The plugin backend runtime is deliberately resolved later by WP-08, after the core
has demonstrated value.

## 22. Definition of ready for an agent

A work package may be assigned when:

- all listed dependencies are merged;
- its input/output interfaces are present or specified;
- unresolved choices affecting it have an ADR or explicit provisional default;
- synthetic fixtures needed for its tests exist;
- the agent can complete it without private library access.

An agent handoff must include changed files, commands run, test results, assumptions,
remaining risks, and any proposed design deviation. No agent may use private data to
make a repository test pass.
