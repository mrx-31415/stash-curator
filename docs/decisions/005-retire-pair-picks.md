# Decision: retire Pair picks

Status: **accepted (2026-10-26)**. Retires the deliberate two-scene comparison
flow delivered by `docs/workpackage-pairwise-picks.md`. The implicit-skip
channel (#146 Channel A), which reuses the matched-pair affinity accumulator,
stays.

## Context

Pair picks asked the user which of two unwatched scenes they preferred. Each
answer became winner/loser feedback, and the model build turned it into
`+w` for every feature only the winner had and `−w` for every feature only the
loser had, with `w = 0.10 × feature confidence` against an affinity prior of
1.0 pseudo-count.

Review found three structural problems:

1. **No credit assignment.** Two scenes differ in dozens of tags, performers
   and a studio, while a choice usually turns on one or two of them, or on
   something the metadata does not describe at all. Every differing feature got
   the same credit.
2. **Negligible, partly inert weight.** A feature needed about ten consistent
   picks to move halfway off its prior. The IPS cap of 1.0 made inverse-propensity
   weighting a no-op, and the surprise bonus rarely added more than a few
   percent.
3. **Absolute-channel leak.** Pick outcomes reached the content-neighbors
   kernel and `labelMean` through `label.outcome`, so a scene known only as a
   pick loser read as disliked to its neighbors.

Uneven tag coverage makes problem 1 worse: a missing tag is often a concept
that is present but untagged, so the loser side's "absent" features are partly
false negatives.

## Evidence

An offline prototype compared the shipped rule against a redesign: a joint
Bradley–Terry fit with a model offset, imputed absences for missing tags,
per-scene latent terms, and probe pairs matched on performer and studio.

- **Synthetic recovery.** The simulated user prefers 8 tags and has hidden
  per-scene quality. Tags are dropped per scene with uneven coverage on a real
  tag graph. Accuracy is on noise-free held-out pairs; a model that knew the
  true weights but saw only the observed tags would reach 0.62.

  | picks | redesign accuracy | shipped rule accuracy | true tags found (redesign / shipped) |
  |------:|------------------:|----------------------:|-------------------------------------:|
  |   170 | 0.56              | 0.56                  | about 0.3 / about 0.3                |
  |   500 | 0.60              | 0.59–0.60             | about 0.5 / 0.45–0.55                |
  |  1500 | 0.64              | 0.62                  | 0.88 / 0.67                          |

- **Real pick history.** On a few hundred real picks, no method, and not even
  the model's own prediction at pick time, beat chance by more than about two
  standard errors under cross-validation.

Pick volume, not the estimator, dominates. Even a correct redesign only pays
off after more than a thousand deliberate picks, far more than users give.

## Decision

Remove the Pick tab, the `get_curation_picks`, `submit_curation_picks` and
`get_curation_pair_verdict` operations (Go runtime and Python oracle), the
pick label conversion, and the three `curation_pair_*` model constants.

Better uses of the same user attention:

- **Direct feature feedback.** One Tag sentiment answer lands on its feature
  with a support of 8, more than the share of hundreds of picks that would
  ever reach that tag. It also sidesteps credit assignment and missing tags:
  the answer is about the concept, not about one scene's tagging.
- **Implicit comparisons from normal use.** Played or thumbed cards beating
  the cards shown above them produce comparisons in volume at no cost.

## Consequences

- Applied migrations `0030` and `0033` are unchanged. The `curation_pair` table
  and the answered `curation_pair_*` feedback rows stay as history, are shown in
  Feedback history, and are no longer read by the model build or Impact.
- Removing the constants changes the canonical model config, so the next update
  rebuilds the model once. Recommendations shift slightly where old picks had
  moved affinities.
- The scene-label absolute and learning channels now carry identical values.
  The split stays in place because explanations and the fingerprint expose
  both; collapsing it is a possible cleanup with no behavior change.
- An old `?section=stream` Curate link falls back to Tag sentiment.

## Follow-up

`docs/workpackage-tag-questions.md` makes Tag sentiment the main Curate
activity by asking first about the tags whose answers would change
recommendations most. That moves the probe selection idea to the channel where
an answer is direct.
