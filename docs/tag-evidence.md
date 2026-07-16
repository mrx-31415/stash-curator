# Tag and performer evidence design

Status: proposed architecture; read-only audit complete

This note separates what a scene contains from what its cast is like. The distinction
matters because a physical characteristic may currently appear as a scene tag, a
performer-profile field, and a reason that two performers are similar. Treating all
three as independent evidence exaggerates one underlying fact.

## 1. Current limitation

Tag-role resolution currently defaults nearly every non-administrative tag to
`content`. The feature builder then uses those tags for:

- direct content affinity;
- preference-weighted scene neighbors;
- diversity and Adventure coverage;
- the aggregated content profile used in performer similarity.

Structured performer metadata separately supplies proportions, age at recording,
appearance, augmentation, tattoos, piercings, and other similarity blocks. Physical
scene tags can therefore be counted both as content and as performer evidence.

The `performer_attribute` role and synchronized performer-tag relationships exist,
but are not yet consumed by the feature pipeline.

## 2. Semantic roles and scope

Resolve each tag into both a semantic role and, where relevant, a subject scope.

| Role | Examples of meaning | Ranking use |
|---|---|---|
| `scene_content` | acts, scenarios, clothing, setting, presentation | content affinity and neighbors |
| `cast_attribute` | appearance, body profile, age band, augmentation, tattoos | performer generalization |
| `quality_technical` | resolution, encoding, production quality | optional quality policy |
| `workflow` | queues, automation, hiding, processing state | never matching |
| `ignored` | explicitly excluded evidence | never matching |

Cast-attribute observations additionally store:

- dimension and normalized value;
- subject scope: `performer`, `single_cast`, `cast_existential`, or `unknown`;
- provenance and confidence;
- whether structured metadata confirms or conflicts with the observation.

Resolution precedence remains explicit tag-ID overrides, configured hierarchy/name
rules, and conservative defaults. Ambiguous terms stay scene content until mapped.
The inspector must show the selected role and why it was selected.

## 3. Canonical performer profile

Build one provenance-aware profile per performer. Evidence precedence is:

1. structured performer metadata;
2. typed tags attached directly to the performer;
3. repeated attribute tags from single-performer scenes, only as missing-field
   fallback.

Never overwrite structured metadata with inferred tags. Preserve disagreements and
lower fallback confidence. Learn source/tag reliability by measuring agreement with
structured metadata on single-performer scenes.

An initial confidence scale may use approximately:

| Source | Confidence |
|---|---:|
| structured metadata | 0.8–1.0 |
| typed performer tag | 0.7–0.85 |
| repeated single-cast scene tag | 0.45–0.65 |
| ambiguous multi-cast observation | about 0.2; initially non-predictive |

Tag absence remains unknown.

## 4. Single- and multi-performer scenes

A physical scene tag has no inherent subject attribution.

- On a single-performer scene, it may update a missing profile field with reduced
  confidence and recurrence requirements.
- On a multi-performer scene, retain it as an existential cast observation. Do not
  assign it to every performer.
- If a direct performer tag or structured metadata identifies the subject, use that
  stronger evidence instead.

Training attribution mass stays bounded per scene. A scene with `n` performers must
not contribute a full outcome observation to every performer or receive an implicit
cast-size bonus.

## 5. Shared performer-generalization family

Use one bounded generalization family rather than adding attribute preference and raw
performer similarity independently.

```text
attribute_preference_p = learned_preference(profile(p))
identity_residual_k = identity_affinity_k
                      - learned_preference(profile(k))
residual_similarity_p = weighted_transfer(identity_residual_k,
                                           similarity(profile(p), profile(k)))
novelty_weight_p = max(floor, 1 - identity_confidence_p)

performer_generalization_p = novelty_weight_p
    * clamp(attribute_preference_p + residual_similarity_p,
            shared_generalization_bound)

performer_total_p = direct_identity_p + performer_generalization_p
```

The attribute term learns general tendencies. Similarity transfers only what was
special about known performers after those general tendencies are accounted for.
Both fade as the target performer becomes familiar. This prevents the same physical
attribute from contributing as scene-tag appeal, direct attribute preference, and
similarity to a known performer.

Correlated raw measurements and derived ratios continue to share block budgets.
Require support across distinct performers and contexts, not merely many scenes from
one performer or studio.

## 6. Scene vectors and exploration

Cast-attribute tags do not participate in semantic scene-neighbor vectors. Content
neighbors should answer “what happens and how is it presented?”, not “what does the
cast look like?”

Preserve a separate cast-profile distance for:

- unfamiliar-performer recommendations;
- perceived variety;
- Discover challenges;
- under-covered Adventure regions.

This distance is not added again as ordinary content appeal.

## 7. Explanation policy

- Familiar performer: lead with direct history; suppress resemblance and generic
  attribute prose outside the inspector.
- Unfamiliar performer: name either a learned overall profile tendency or the closest
  familiar examples, whichever contributes more. Usually do not narrate both.
- Single-cast fallback tag: state that scene tagging suggests the attribute and that
  performer metadata is incomplete.
- Multi-cast tag: say only that the cast includes the attribute; never name a person.
- Keep acts/scenarios/style in the content thesis and cast profile in a separate
  corroborating role.

Sensitive specificity remains configurable. Exact measurements stay inspector-only.

## 8. Staged validation

1. **Read-only taxonomy audit:** propose mappings and compare them with structured
   metadata on single-performer scenes. Measure agreement, conflicts, and
   studio/source effects without changing ranking.
2. **Shadow profile build:** test role/scope resolution, provenance precedence,
   missingness, conflicts, and single-versus-multi attribution.
3. **Shadow attribute model:** perform leave-one-performer-out evaluation and verify
   that one observation cannot increase two families independently.
4. **Residual-similarity ablation:** compare identity-only, attribute-only, raw
   similarity, and attribute-plus-residual-similarity models against retained
   pairwise feedback and top-list stability.
5. **Explanation validation:** prohibit sensitive overclaim, individual attribution
   from multi-cast tags, and resemblance narration for familiar performers.

Reclassification creates a new feature and model version. Old reports remain tied to
their original taxonomy and reproducible.
