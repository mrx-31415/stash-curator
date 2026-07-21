# Archived recommendation prose corpus analysis

> Historical research note. This is not current user documentation.

Status: 200-record private evaluation complete; implementation rules proposed

This document records generalized findings from a private recommendation-rewrite
experiment. The corpus and rewrites contain library-specific data and remain in
ignored local storage. No private entities or recommendation text belong in the
repository.

## 1. Experiment

The corpus contained 200 recommendations, balanced across four source lanes:

- 50 Best Bets;
- 50 Revisit;
- 50 Discover;
- 50 Adventure.

Each record supplied scene context, the current explanation, selected structured
reasons, and an instruction to produce concise personal-curator prose without adding
facts. Two independent rewrite passes handled disjoint halves of the corpus. A third
analysis pass compared current and rewritten language and extracted planner rules.

Because the two writers handled different records, this evaluates broad patterns but
not inter-writer agreement or paired alternative phrasings.

## 2. Quantitative findings

| Measure | Current | Rewritten | Change |
|---|---:|---:|---:|
| average words | 50.9 | 34.0 | -33% |
| average sentences | 2.94 | 2.02 | -31% |
| unique four-word openings | 37 | 167 | +351% |
| largest repeated opening | 51 records | 8 records | -84% |

No exact rewrite was duplicated. Contrastive language and explicit positive anchors
became substantially more common, while mechanical lane naming and repeated “your
history” phrasing fell.

The rewrites also introduced a new structural risk: 197 of 200 used exactly two
sentences. A microplanner must therefore learn evidence relationships and controlled
length variation rather than treating the rewrite corpus as sentence templates.

## 3. Evidence representation

Normalize every reason into a semantic unit before planning:

```text
EvidenceUnit
  code
  polarity
  strength
  confidence
  subject and sourced display facts
  specificity
  provenance
  redundancy group
  discourse role candidates
```

Never render directly from arbitrary model-detail dictionaries. Unknown means lack
of evidence, not negative evidence.

Default factual priority is:

```text
direct outcome
> known performer
> preference-aware content neighbor
> studio
> standalone tag affinity
> performer analogy
```

Lane strategy may reorder presentation, but not factual strength.

## 4. Content selection

Collapsed card prose should normally contain at most two positive supports and one
caveat or exploration purpose.

- Direct outcome is mandatory in Revisit.
- Merge content neighbor and shared tags into one semantic unit.
- Suppress standalone tag evidence when it repeats the neighbor’s shared tags.
- Mention at most two representative neighbors and two or three discriminative tags;
  leave complete evidence in the drawer.
- Drop weak same-polarity evidence instead of enumerating it.
- When direct positive evidence conflicts with a generic learned negative, state that
  direct experience overrides the weaker pattern.
- Established performer identity suppresses performer-similarity narration.

## 5. Lane discourse plans

### Best Bets

```text
CLAIM(primary concrete anchor)
+ JOINT_SUPPORT(neighbor or independent second family)
+ optional CONCESSION(material weak negative)
```

Best Bets is unseen-only, so it cannot rely on exact-scene success.

### Revisit

```text
DIRECT_SUCCESS
+ CORROBORATION(performer or content)
+ optional TIMING/OVERRIDE
```

Prior direct experience leads. Reusable taste evidence is context, not the thesis.

### Discover

```text
FAMILIAR_ANCHOR
+ optional BRIDGE(content or studio)
+ NOVELTY_BOUNDARY
```

- Adjacent: anchor plus bridge; novelty may be implicit when obvious.
- Stretch: positive case followed by the named challenge.
- Frontier: anchor plus candid lack of context, never implied dislike.

### Adventure

- Model disagreement: positive case + genuine contrast + purpose.
- Coverage gap: concrete bridge + purpose for exploring the under-covered cluster.
- Pure probe: purpose first + explicit low-support boundary.
- Unknown evidence must never be realized with negative psychological language.

## 6. Rhetorical planning

Use semantic relations rather than concatenated reason sentences:

- **reinforcement:** independent evidence families converge;
- **elaboration:** tags explain why a neighbor is close;
- **contrast:** positive and negative evidence genuinely disagree;
- **concession:** a recommendation remains worthwhile despite bounded friction;
- **timing:** durable appeal differs from current readiness;
- **purpose:** a Discover/Adventure card tests a named boundary or coverage gap;
- **override:** direct experience outranks a weaker reusable pattern.

Combine convergent reasons in one clause or sentence. Use “but,” “while,” and
“although” only for real opposition. Use consequence words such as “so” and “which”
only when the source facts entail that conclusion. Avoid a closing lane boilerplate
when the contrast already explains placement.

Calibrate caveats by magnitude: a low-strength residual is a “slight caution” or
“less proven,” a medium conflict is a “mixed signal,” and only explicit feedback may
justify hard dislike language.

## 7. Referring expressions and variation

- Introduce one salient performer or short scene title once, then use “this scene” or
  “it.”
- Avoid repeating “your history” in adjacent clauses.
- Do not use performer pronouns unless sourced.
- Long neighbor titles belong in the detail drawer; collapsed prose may say “two
  scenes you enjoyed.”
- Vary discourse skeletons first. Use deterministic lexical alternatives only within
  the chosen relation.
- Add a page-local repetition guard so adjacent cards do not share an opening.

Target a controlled length distribution rather than one universal shape:

- about 20% one sentence for simple convergent evidence;
- about 65% two sentences;
- about 15% three sentences for genuine conflict or exploration;
- roughly 20–50 words in collapsed prose.

## 8. Failure modes found

- Polished prose may infer a theme from a title that structured evidence did not
  supply.
- “Safe,” “natural fit,” and similar conclusions can overstate confidence.
- Random synonym rotation creates unnatural collocations without changing structure.
- Generic tags may duplicate neighbor tags in both evidence and prose.
- Negative neighbor evidence needs polarity-aware language.
- Long titles can overwhelm the recommendation.
- “Not mapped” may accidentally sound like dislike.
- Attribute tags can produce sensitive or wrongly attributed claims; follow the
  separate tag-evidence design.

## 9. Tests for the microplanner

1. Golden discourse plans for common reason patterns and every lane/subtype; assert
   roles and order rather than exact prose.
2. Provenance property: every entity, tag, and attribute in output maps to a supplied
   fact.
3. Input reason order does not alter the plan.
4. Adding a weak redundant tag does not alter collapsed prose.
5. Changing lane changes tradeoff framing, not underlying factual claims.
6. Direct success outranks a generic negative feature.
7. Unknown evidence never emits negative lexemes.
8. Neighbor count, shared-tag deduplication, and long-title bounds hold.
9. Established identity suppresses similarity narration.
10. Deterministic variants remain stable while the page-level repetition threshold
    holds.
11. Grammar tests cover articles, agreement, list cardinality, missing names, and
    punctuation.
12. Output remains within configured word and sentence bounds.

## 10. Recommendation

Implement semantic normalization, content selection, and lane-specific discourse
plans before expanding lexical variants. This should capture most of the rewrite
improvement deterministically. An optional constrained language-model rewriter can
then improve rhythm, but only over a complete verified plan with placeholder and
provenance validation.
