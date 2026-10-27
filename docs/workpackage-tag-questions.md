# Workpackage: Tag questions (high-value Tag sentiment prompts)

Status: proposed. Follows `docs/decisions/005-retire-pair-picks.md`: the user
attention that went into Pair picks moves to direct feature answers, asked in
the order that changes recommendations most.

## Goal

Curate opens on a short queue of tag questions ("More or less of this?") ranked
by how much one answer would change what Curator recommends. Each answer is an
ordinary Tag sentiment answer (`direct_tag_preference`), so there is no new
model input, no credit assignment, and no dependence on how thoroughly any one
scene is tagged.

Non-goals: new model mechanics, performer or studio questions (possible
later; performers already have favorites and ratings), and reason-on-dismiss
chips (a separate package, see Follow-up).

## Why tags, and why ranked

- One answer enters the affinity blend with a support of 8
  (`directSupport`), so it controls `8 / (support + 8)` of that tag's blended
  affinity. A pick spread `0.10 × feature confidence` across every feature
  that differed between two scenes.
- Today Tag sentiment lists every classified tag (sorted by name, with
  confidence and inferred-value sorts). It works for a user who knows what
  to fix, but it does not say where an answer matters. Most tags are rare or
  already well supported, so a random answer usually moves nothing visible.

## Package: backend

### Op `get_tag_questions` (Go runtime + Python oracle)

Request: `{ "limit": 5 }` (1..10, default 5). Read-only: it uses the published
model and its artifacts, like `get_taste_profile`.

Candidates are tags in the taste profile with:

- no direct answer and no Never block;
- the `content` or `performer_attribute` role;
- not generic: skip when `scene_count ≥ 5` and `scene_count ≥ 0.8 × total
  scenes` (the existing follow-up rule);
- at least `min_reach_scenes` (default 5) scenes in the reach pool below.

**Value of an answer**, per candidate tag `t`:

```
leverage_t = 8 / (support_t + 8)            # share of the blend an answer controls
reach_t    = Σ_{s ∈ pool, t ∈ s} w_s / Σ_{s ∈ pool} w_s
w_s        = 1 / log2(rank_s + 1)           # discounted by the scene's appeal rank
value_t    = leverage_t × reach_t
```

`pool` is the top `reach_pool_size` (default 300) recommendable scenes by
published `current_fit`: unwatched or recovered, eligible, not excluded or
blocked. This is the set the lanes draw from, so `reach` measures how much of
what you are shown carries the tag, weighted toward the top.

Order by `value` descending, then `|inferred|` ascending (questions the model
is least sure about first), then name, then tag id. Fully deterministic.

Response:

```json
{ "schema_version": 2,
  "items": [ { "tag_id": "…", "name": "…", "inferred_value": 0.12,
               "confidence": 0.31, "support": 1.4, "reach": 0.18,
               "leverage": 0.85, "examples": ["scene-id", "scene-id", "scene-id"] } ] }
```

`examples` holds up to 3 pool scenes carrying the tag, highest-ranked first,
for thumbnails that make the concept concrete. They are the user's own scenes,
so no external lookups are needed.

Config-backed constants (`reach_pool_size`, `min_reach_scenes`) live in a new
`TagQuestionConfig`, kept out of `ModelConfig` so they do not change model
fingerprints.

### Answers

Answers reuse `submit_tag_preferences` unchanged, including Never and Clear,
the local queue during transient failures, and the batched model update. No
migration.

## Package: frontend

- **Tag questions** becomes the first Curate section; Tag sentiment (the full
  list) and Impact follow. An old `section=stream` link lands on the first
  section, as it does today.
- One question card at a time: tag name, its taxonomy category, up to 3
  example thumbnails, a one-line reason ("In 18% of what Curator would show
  you; it is unsure how you feel"), the existing `TagSentimentControl`, and
  **Skip**.
- Skipped tags are remembered per browser for 30 days (localStorage, wrapped
  in try/catch), then filtered out of the next fetch. Skipping never writes an
  answer.
- After 5 answers: a short summary, **Apply now** (the existing
  `applyFeedbackAndAwaitBuild`), and **Five more**.
- Keyboard: `1`–`5` map to the sentiment steps, `S` skips; ARIA live region
  for the progress text. Controls stay outside `card-section` (SFW Switch
  contract).

## Measurement

No efficacy number existed for picks; this package needs one so it is not
judged by feel either.

- Impact gains an **Answered questions** line: per answered question tag, the
  affinity before and after the build, and how many top-pool scenes moved.
- The build log records the number of direct answers since the previous build.

## Tests

- Op (differential Go/Python): ordering determinism, every exclusion rule
  (answered, blocked, generic, role, below min reach), limit bounds,
  examples drawn only from the pool, no published model → clear error.
- Value math unit test: a well-supported tag ranks below an unsupported one
  with equal reach; a tag absent from the pool never appears.
- Runtime: the question card renders, keyboard mapping, skip persistence with
  storage unavailable, Apply now path, SFW Switch contract.
- Browser smoke: Curate opens on Tag questions with a synthetic second plugin
  present; native content survives; no JavaScript errors.
- `scripts/verify full` before handoff.

## Installed verification

After updating: answer five questions, apply, and confirm in Impact that the
answered tags moved and that recommendations containing them shifted. Check
desktop and mobile layout.

## Follow-up

**Reason on dismiss.** When a user thumbs down or picks Not now on a
recommendation, offer optional chips for the 2–3 tags or the performer that
contributed most to it, plus "just not now" and "something else". A tapped
chip becomes a mild dislike answer on that tag. It captures the reason at the
moment the user knows it, during normal use.
