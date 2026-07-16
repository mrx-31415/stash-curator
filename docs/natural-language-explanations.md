# Natural-language explanation design

Status: deterministic microplanner implemented; evaluation in progress

This document proposes a middle ground between repetitive sentence templates and an
unconstrained language model for Stash Curator's **Why this?** descriptions. The core
idea is a compositional microplanner: Curator builds each explanation from verified
reason objects, arranging and realizing them according to their meaning and
relationship rather than randomly selecting a complete canned sentence.

An optional small language model may later improve the surface style, but it must not
become the source of recommendation facts.

The generalized findings from the 200-record rewrite experiment are documented in
[`prose-corpus-analysis.md`](prose-corpus-analysis.md). They refine this proposal with
measured length/variation targets and lane-specific discourse plans.

## 1. Goals

The explanation system should:

- sound like a knowledgeable personal curator rather than a score dump;
- state why this particular item was selected at this particular time;
- mention concrete tags and similarity dimensions when they materially contributed;
- combine reinforcing, conflicting, and timing evidence into a coherent paragraph;
- vary naturally because recommendations contain different evidence, not merely
  because a random template was selected;
- remain stable for the same model, slate, and reason graph;
- make every factual claim traceable to structured evidence;
- support progressive disclosure from a short summary to full inspector detail;
- respect the visibility level of private and sensitive reasons.

It should not:

- invent an attribute, preference, comparison, or causal claim;
- describe a relative model residual as an explicit dislike;
- expose sensitive performer attributes mechanically or gratuitously;
- regenerate visibly different prose whenever the page is refreshed;
- require a network language-model service for normal operation;
- conceal weak or conflicting evidence behind confident prose.

## 2. Why fixed sentence templates feel robotic

Selecting one of several complete phrases helps only superficially. The same semantic
shape remains visible:

> X is a strong positive signal. Y matches things you enjoy. I ranked it lower because
> Z appeared recently.

The larger problem is not word choice. It is that every reason is rendered as an
independent sentence with the same order and grammatical role. Natural explanations
instead aggregate related evidence, establish contrast, omit redundant facts, and
change sentence structure according to the evidence available.

For example, performer similarity can be the main thesis of one recommendation and a
supporting detail in another. A recent-studio penalty may deserve its own contrastive
clause when it materially changes the rank, but no mention at all when its effect is
negligible.

## 3. Proposed architecture

```text
stored model decomposition
          │
          ▼
     reason graph
          │
          ▼
   content selection
          │
          ▼
 rhetorical planning
          │
          ▼
 aggregation and referring expressions
          │
          ▼
 deterministic surface realization
          │
          ├──────────────► final explanation
          │
          └──► optional constrained rewriter ──► validation ──► final explanation
```

Scoring produces decomposition. The reason graph translates decomposition into
versioned semantic claims. The language layer may select, combine, order, and phrase
those claims, but it may not recompute the recommendation or add new claims.

## 4. Semantic input

The microplanner consumes reason objects rather than prose fragments. A reason should
contain enough information to support both short prose and detailed inspection:

```json
{
  "code": "appeal.performer_similar",
  "direction": "positive",
  "magnitude": 0.13,
  "confidence": 0.71,
  "subject": {"type": "performer", "id": "performer-a"},
  "comparison": {"type": "performer", "id": "performer-b"},
  "evidence": {
    "similarity": 0.82,
    "shared_aspects": ["content", "measurements", "age_at_recording"]
  },
  "visibility": "sensitive",
  "provenance": "performer_profile_similarity"
}
```

The language layer should receive display names through a separate resolver. IDs and
display strings are presentation data; neither should determine the semantic claim.

## 5. Content selection

Most cards should explain two or three ideas, not enumerate every non-zero component.
Selection is therefore an editorial step.

### 5.1 Candidate claims

Group reasons into roles:

- **core appeal:** the strongest evidence that the item fits established taste;
- **corroboration:** a distinct evidence family that strengthens the core claim;
- **exploration:** the assumption, unknown region, or coverage gap being tested;
- **direct memory:** exact-item history such as a prior positive outcome or revisit;
- **current adjustment:** cooldown, recent appetite, Not now, or diversity movement;
- **reservation:** meaningful below-baseline or explicitly negative evidence.

### 5.2 Selection rules

A reasonable default planner is:

1. choose one core reason by confidence-weighted contribution;
2. choose one non-redundant corroborating family when it adds real information;
3. include an exploration reason whenever exploration defines the lane;
4. include a current adjustment only when it materially changes placement;
5. include a reservation when it explains why an otherwise strong item is a stretch;
6. cap the short explanation at roughly three semantic units.

Tags from the same family should usually be aggregated into one claim. Performer
identity and performer similarity are often redundant and should not both be stated
unless the distinction matters.

The planner should record omitted reasons so the inspector can still expose them.

## 6. Rhetorical planning

Selected facts need a relationship, not just an order. The planner assigns a small
set of rhetorical relations:

| Relation | Meaning | Typical realization |
|---|---|---|
| reinforcement | two independent reasons agree | “X fits, and Y reinforces that” |
| elaboration | one reason explains another | “similar to B, especially in X and Y” |
| contrast | positive evidence has meaningful friction | “X fits, although Y is weaker” |
| concession | deliberate exploration despite a reservation | “Even though X is uncertain…” |
| timing | long-term appeal differs from current fit | “It fits your taste, but not quite now” |
| consequence | evidence affected placement | “That was enough to move it into Discover” |

This creates evidence-shaped explanations. A Best Bet with two agreeing families
should read differently from a Discover item that retains one anchor while challenging
another.

### 6.1 Lane-level discourse strategies

**Best Bets**

- lead with the strongest concrete fit;
- add corroboration from a separate family;
- mention a current adjustment only if it meaningfully affected the order.

**Revisit**

- lead with direct memory;
- state why the item is timely again;
- use reusable taste evidence only as supporting context.

**Discover**

- state the familiar anchor and the challenged or unknown aspect;
- avoid presenting model uncertainty as a fact about the user;
- make the tradeoff understandable in one contrastive sentence.

**Adventure**

- say what kind of probe this is;
- identify any coherent anchor or coverage gap;
- be candid when evidence is intentionally thin.

## 7. Aggregation

Aggregation makes the largest difference to perceived naturalness.

### Tags

Instead of:

> Tag X is positive. Tag Y is positive. Tag Z is positive.

Produce a single semantic unit:

> X and Y are the clearest content matches, with Z providing weaker support.

The grouping should preserve relative strength. Do not list three tags as equally
important when one dominates the score.

### Performer similarity

Instead of:

> Performer A is similar to Performer B. The similarity is based on proportions.
> The similarity is also based on content.

Produce:

> Curator places A near B, mainly because of their content profiles and body
> proportions.

Similarity language must distinguish:

- the target performer;
- the known performer supplying preference evidence;
- the blocks responsible for similarity;
- whether the known-performer evidence is positive, negative, or uncertain.

### Current adjustments

Several small repetition penalties should normally become one clause:

> I moved it down slightly to keep the page from repeating a recent studio and content
> pattern.

Only the inspector needs the individual penalty values.

## 8. Referring expressions and local context

The renderer should track what has already been mentioned inside the paragraph:

- use a full entity name on first reference;
- use “they,” “the performer,” “the studio,” or “this scene” afterward;
- avoid beginning consecutive sentences with the same entity;
- avoid repeating “this scene” in every sentence;
- use “also” only when a previous reinforcing claim exists;
- use “however” or “although” only for genuine contrast.

It may also track recent card phrasing within one generated slate. This is not used to
change facts, only to avoid identical openings across adjacent cards. For example, if
the previous card began with a performer comparison, the next explanation may lead
with its tag evidence when both are similarly strong.

This context must remain deterministic for the slate order.

## 9. Surface realization without an LLM

The deterministic realizer should operate on clauses and lexical choices, not whole
pre-written paragraphs.

A clause can be represented as:

```text
subject: performer A
predicate: resembles
object: performer B
modifier: mainly in content profile and proportions
polarity: positive
certainty: moderate
discourse role: elaboration
```

The realizer chooses:

- active or passive-like structure;
- whether evidence leads or follows;
- a calibrated verb such as “matches,” “resembles,” “supports,” or “suggests”;
- a connective based on rhetorical relation;
- hedging based on confidence;
- singular/plural agreement and natural list punctuation.

Variation should be chosen by semantic conditions first. Stable hashing may choose
between equivalent lexical realizations only after the structure has been determined.
This prevents wording from changing on refresh while avoiding one universal phrase.

The implementation keeps evidence selection and discourse planning in Python, while
reviewed clause and plan variants live in
`curator/explanations/realizations.json`. JSON keeps the runtime dependency-free and
is included in the Python package. The loader validates every placeholder before any
text can be rendered.

Generated examples may be used offline to propose additional variants. They are
reviewed, reduced to fact-preserving clauses or plan shapes, and added to the catalog;
Curator does not splice arbitrary generated paragraphs at runtime. This allows a much
larger language inventory without letting generated prose become a source of facts.

### Confidence language

| Confidence | Language |
|---|---|
| high | “is a close match,” “strongly resembles” |
| medium | “looks similar,” “provides useful support” |
| low | “may be adjacent,” “is a tentative signal” |

Confidence wording must not turn a relative score into psychological certainty.

## 10. Worked examples

### Best Bet

Input:

- strong positive tags: scenario X and clothing Y;
- performer A resembles liked performer B through content and proportions;
- studio evidence is weakly positive;
- no meaningful current adjustment.

Possible realization:

> Scenario X and clothing Y make this a close content match. Performer A also sits
> near B in the model, particularly in scene profile and proportions, which strengthens
> the recommendation.

### Discover

Input:

- performer identity is a strong anchor;
- one tag family is below the user's typical viewed-scene baseline;
- neighbor evidence remains positive;
- confidence is moderate.

Possible realization:

> Performer A gives this a familiar starting point, and nearby scenes in the content
> model have worked well. The scenario is less typical of your history, so this is a
> measured stretch rather than a safe pick.

### Revisit

Input:

- several durable returns;
- prior strong outcome;
- recovery is high after cooldown;
- recent studio repetition is minor.

Possible realization:

> You have returned to this scene several times, and enough time has passed for it to
> be timely again. I kept it just below the first revisit slot because the studio has
> appeared recently.

### Adventure

Input:

- coherent but under-covered tag cluster;
- no known performer preference;
- metadata confidence is adequate;
- little neighbor evidence.

Possible realization:

> This comes from a well-described part of the library that your history barely
> covers. There is little performer or neighbor evidence to lean on, so it is an
> intentional probe rather than a predicted favorite.

## 11. Optional constrained language-model rewriter

A language model can improve rhythm and reduce the remaining hand-authored feel, but
it should rewrite a verified draft rather than generate an explanation from scores.

### 11.1 Placeholder representation

Provide the rewriter with semantic placeholders:

```text
[PERFORMER_A] resembles [PERFORMER_B] in [ASPECT_LIST].
[TAG_LIST] supplies positive content evidence.
[STUDIO] has a small recent-repetition penalty.
```

Instruction:

```text
Combine these claims into one concise explanation. Preserve every claim and its
certainty. Do not add preferences, attributes, causes, entities, or recommendations.
Use only the supplied placeholders.
```

Substitute display values only after the rewrite. This prevents the model from
inventing names and substantially narrows the generation problem.

### 11.2 Validation

Accept a rewrite only when:

- every required placeholder is preserved exactly once or in an approved grouped
  form;
- no unknown placeholder or proper noun appears;
- direction and uncertainty markers remain compatible with the source reasons;
- prohibited causal or psychological language is absent;
- the output satisfies configured length and sensitivity limits.

If any check fails, use the deterministic microplanner output.

### 11.3 Runtime options

The rewriter could be:

- disabled, using only deterministic realization;
- a small local model bundled or configured separately;
- an explicitly configured external API for users who accept the privacy tradeoff.

External rewriting must be opt-in. Structured reasons may contain sensitive library
and behavioral information and must never be transmitted implicitly.

## 12. Stability and caching

Cache the final explanation using a hash of:

```text
model version
reason-graph version
selected reason IDs and values
lane and subtype
slate adjustment reasons
renderer version
tone configuration
```

The same evidence should produce the same explanation. A rebuild, feedback event,
material rank adjustment, or renderer-version change may legitimately produce new
text.

Language-model rewrites should also be cached. A live model call per card would add
latency, cost, nondeterminism, and failure modes without improving recommendation
quality.

## 13. Sensitivity and privacy

The planner must honor each reason's visibility:

- **standard:** may appear in normal and redacted explanations;
- **private:** may appear locally but should be omitted or generalized when sharing;
- **sensitive:** may appear only when enabled and phrased at an approved level of
  specificity.

For example, a local explanation might mention “similar body proportions,” while a
redacted report should fall back to “a similar overall performer profile.” Exact
measurements should remain inspector data and should not appear in card prose by
default.

## 14. Configuration

Initial controls should remain modest:

- explanation detail: concise, balanced, or detailed;
- sensitive similarity descriptions: enabled or generalized;
- voice: neutral or curator-like;
- optional language-model rewriting: off by default;
- maximum semantic units and approximate sentence count.

Avoid exposing dozens of lexical controls. Renderer details belong in versioned
configuration or developer diagnostics.

## 15. Implementation sequence

### Phase 1: deterministic microplanner (implemented foundation)

Implemented: semantic evidence units, deterministic lane plans, non-redundant content
selection, external validated realizations, stable variation, direct-memory-first
Revisit prose, and mandatory Discover/Adventure boundaries.

Remaining: richer aggregation, confidence-sensitive wording, referring-expression
and slate-local repetition handling, and persistent caching by reason signature.

### Phase 2: evaluation

1. create synthetic golden plans independently of golden prose;
2. compare current and microplanned explanations on private recommendations;
3. review truthfulness, usefulness, repetition, sensitivity, and tone;
4. retain generalized failures as synthetic regression cases.

### Phase 3: optional rewriter spike

1. evaluate a small local model on placeholder-only drafts;
2. implement structural validation and deterministic fallback;
3. measure latency, package size, and rewrite acceptance rate;
4. decide whether the naturalness gain justifies a supported runtime option.

## 16. Testing

Tests should cover semantics separately from prose.

### Planner tests

- the highest-value non-redundant facts are selected;
- exploration is always stated for Discover and Adventure when applicable;
- a material current-fit adjustment is not silently omitted;
- weak adjustments do not crowd out core evidence;
- a relative negative is not rendered as explicit dislike;
- sensitive reasons obey visibility configuration.

### Realizer tests

- singular/plural agreement and list formatting;
- reinforcement and contrast use appropriate connectives;
- entity references do not become ambiguous;
- repeated adjacent cards receive different structures when evidence permits;
- identical model and slate inputs remain deterministic;
- every rendered claim points back to one or more reason IDs.

### Rewriter tests

- missing, duplicated, or invented placeholders reject the rewrite;
- changed polarity or confidence rejects the rewrite;
- unknown proper nouns reject the rewrite;
- timeout or model failure returns the deterministic explanation;
- private evidence is never sent when rewriting is disabled or disallowed.

## 17. Recommendation

Implement the deterministic microplanner first. It addresses the structural cause of
robotic prose while preserving Curator's strongest explanation properties:
truthfulness, inspectability, privacy, and stable output.

Treat language-model rewriting as an optional presentation enhancement over a
complete deterministic explanation. It should never participate in scoring, reason
selection, or factual interpretation.

The initial implemented slice now names representative content-neighbor scenes,
shows the distinctive tags they share, exposes those scenes as links in the local
evaluation report, and omits generic slate-diversity boilerplate from card prose.
The reason graph still retains every adjustment for inspection. Broader rhetorical
planning, referring-expression tracking, and optional constrained rewriting remain
future phases.
