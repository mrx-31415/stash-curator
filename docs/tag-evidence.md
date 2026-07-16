# Tag and performer evidence design

Status: taxonomy classification implemented; profile enrichment proposed

This note separates what a scene contains from what its cast is like. The distinction
matters because a physical characteristic may currently appear as a scene tag, a
performer-profile field, and a reason that two performers are similar. Treating all
three as independent evidence exaggerates one underlying fact.

## 1. Current boundary

Tag-role resolution now separates StashDB body and appearance categories from scene
content. The feature builder excludes tags classified as `performer_attribute` from:

- direct content affinity;
- preference-weighted scene neighbors;
- diversity and Adventure coverage;
- the aggregated content profile used in performer similarity.

Structured performer metadata separately supplies proportions, age at recording,
appearance, augmentation, tattoos, piercings, and other similarity blocks. Physical
scene tags would therefore be double-counted without the role boundary.

The role, cached taxonomy, match provenance, and synchronized performer-tag
relationships exist. Building dated, subject-aware observations from those tags is
the remaining profile-enrichment work; the current implementation deliberately
excludes them from content vectors without yet counting them as new preference
evidence.

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

### Automated classification

Classification is designed as a versioned, mostly automatic pipeline rather than a
requirement that users rename every tag:

1. apply explicit local tag-ID overrides, which always win;
2. map a local tag's StashDB ID to the cached StashDB taxonomy when available;
3. otherwise resolve a unique normalized canonical name or alias from that taxonomy;
4. recognize configured namespaces and conservative fallback vocabulary;
5. use local tag hierarchy, whether a tag occurs on performers or scenes, and
   agreement with structured metadata on single-cast scenes;
6. combine those signals into a role, scope, confidence, and human-readable rationale.

Stash exposes `stash_ids` on tags, while StashDB exposes stable tag and category IDs,
canonical names, aliases, category descriptions, and category groups. Curator should
periodically download that public taxonomy into its sidecar and perform all matching
locally; it never needs to send library tag names or behavior to StashDB. A configured
StashDB token is used only for the read-only taxonomy fetch. The cached snapshot keeps
model builds reproducible and permits offline operation.

Category IDs, not only broad groups, determine semantics. The `PEOPLE` group contains
both physical attributes and scene presentation such as Clothing. Initial
performer-attribute categories include Body Type, Ass, Breasts, Face, Genitals, Hair
Color, Hair Style, Height, Piercings, Race, Skin Tone, and Tattoos. Clothing remains
scene content. StashDB's Age Group describes character presentation, so it must not
replace age-at-recording derived from performer birthdate and scene date.

Mapping records retain local tag ID, external tag/category IDs, match method, taxonomy
snapshot, confidence, and ambiguity. Stable-ID matches are strongest. A canonical or
alias match is accepted automatically only when unique; ambiguous or absent terms
fall through to local rules or review. For example, the current snapshot maps
`Athletic Body` and `Athletic Woman` to `Athletic` in Body Type, `Trimmed` to
`Trimmed Pussy` in Genitals, and `Bubble Butt` to the Ass category. The conservative
fallback vocabulary retains these terms as performer attributes if a future or
older taxonomy snapshot cannot resolve them.

The implemented resolver recognizes explicit rules, the cached StashDB taxonomy,
and a conservative fallback vocabulary. Its reviewed category policy lives in
[`stashdb_category_roles.json`](../curator/taxonomy/stashdb_category_roles.json), not
in a private library export. Usage/agreement classification and the review queue are
later profile-enrichment work.

High-confidence mappings are accepted automatically. A later review queue will hold
medium-confidence mappings; low-confidence or genuinely ambiguous tags remain
`scene_content` and cannot silently become performer facts. A later offline
classifier or language model may propose mappings for unfamiliar names, but it does
not publish them without the same confidence and consistency checks. Corrections are
stored as durable ID overrides, so review effort teaches the resolver rather than
being repeated after every sync.

This makes a naming convention such as `[Attribute: Blonde]` useful but optional.
Namespaced tags resolve immediately; ordinary existing tags can still be classified
from their vocabulary, hierarchy, usage, and agreement with metadata.

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

### Attribute blocks and priority

Physical attributes are not interchangeable. The default similarity ordering is:

```text
measurements and proportions
  > augmentation
  > ethnicity
  > height
  > age at recording
  > hair color
  > tattoos
  > piercings
  > eye color
```

The implementation keeps these as separate blocks so configuration can express the
ordering. Measurements include bust, waist, hips, cup normalization, and derived
waist-to-hip shape, with a shared budget so correlated values do not multiply their
importance. Height is separate. Content-profile similarity remains a distinct,
high-value non-physical block.

### Attributes that change over time

Hair color is an observation, not a permanent identity field. The performer metadata
value is treated as a lower-confidence current or fallback value. A hair attribute
attached to a dated scene describes the performer at recording time and takes
precedence for that scene when its subject can be established. It does not overwrite
the global performer profile. Store observation date, provenance, confidence, and
subject scope so a brunette scene and a later blonde scene can both be represented
truthfully.

Tattoos, piercings, augmentation, and measurements can also change, although usually
more slowly, and use the same observation model when dated evidence exists. Age is
always derived at recording time rather than from current age.

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
