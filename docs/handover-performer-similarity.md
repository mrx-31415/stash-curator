# Performer-similarity build optimization handover

Updated: 2026-07-30.

## Goal

Reduce model-build time by excluding negligible learned performer affinities from
similarity propagation. Keep direct performer-identity scoring unchanged.

This is independent of runtime explanations and score-first ordering. Do not combine
the work packages.

## Measured baseline

Installed profiling on a 23,891-scene library measured:

- full model build: about 409 seconds;
- all similarity work: about 132 seconds;
- performer similarity: about 56 seconds;
- learned performer-identity affinities: 334 total, 206 with effective absolute
  affinity at least `0.005`, and 149 at least `0.01`.

Filtering at `0.005` should remove about 38% of the similarity seeds and may save
roughly 20 seconds. Treat that as a hypothesis to measure, not a promised result.
Keep private scene, performer, and library identifiers out of tracked files and
command output.

## Current flow

`PreferenceModelBuilder._performer_similarity_scores()` in
`curator/model/builder.py`:

1. derives an effective identity affinity as `affinity * confidence`;
2. loads all performer profiles;
3. compares every profile with every known-affinity profile, avoiding duplicate
   known/known comparisons;
4. retains the five most similar matches and propagates their affinity and
   confidence.

`performer_similarity()` and profile block behavior live in
`curator/features/profiles.py`. Existing coverage is primarily in
`tests/model/test_builder.py`, including the known-pair comparison-count test.

The build already records the `model.score_performer_similarity` span. Use it for the
installed before/after comparison.

## Smallest implementation

Filter only the `known` similarity seed set to entries whose effective affinity has
`abs(value) >= 0.005`. Do not filter the identity-affinity data used by exact
performer scoring, change `performer_similarity()`, add configuration, or add a
dependency.

The cutoff deliberately changes propagation from near-neutral performers: their exact
identity contribution remains, but they no longer act as similarity neighbors.
Document the fixed heuristic next to the filter with its measured ceiling and upgrade
path if the code would otherwise make the number look arbitrary.

Split the broad publication `indexing` timer only if needed to obtain trustworthy
stage measurements; avoid an unrelated timing refactor.

## Required checks

- Add one focused regression test proving sub-threshold identities are not compared
  while above-threshold identities are, and keep the existing known-pair deduplication
  assertion.
- Run `scripts/verify changed tests/model/test_builder.py` while iterating and
  `scripts/verify full` once near completion.
- For installed validation, compare cold and warm
  `model.score_performer_similarity` and total build times.
- Privately compare recommendation quality and explanations before and after,
  especially scenes whose only useful evidence comes from weak performer affinities.
- Do not commit, push, or install unless the user asks in that thread.

## Acceptance

- Exact performer-identity contribution is unchanged.
- Similarity calls use only seeds at or above the fixed effective-affinity cutoff.
- Ordering and output remain deterministic.
- Synthetic tests pass and installed timings improve materially without a visible
  recommendation-quality regression.

## Copy-paste prompt

```text
Read AGENTS.md and docs/handover-performer-similarity.md completely. Implement only
the bounded performer-similarity propagation optimization; do not touch runtime
explanations or score-first ordering.

Trace the complete builder/profile flow and tests before editing. Use the fixed
effective-affinity cutoff abs(affinity * confidence) >= 0.005 only for similarity
seeds, preserving exact performer-identity scoring. Add one focused regression test,
run scripts/verify changed tests/model/test_builder.py, then scripts/verify full once.
Report the diff and checks. Do not commit, push, or install unless I explicitly ask.
Keep all live-library identifiers and evaluation details private.
```
