# Workpackage: Signal improvements (labels, calibration, and cache identity)

Status: WP1 shipped, WP4 withdrawn on measurement, three proposed. Arising from
a measurement session against a real-library sidecar. Ordered by evidence
strength, not by appeal.

Measured figures below are from one private instance; shares and ratios carry,
absolute counts do not. Every claim here was measured against a read-only
snapshot, and the ones that failed measurement are recorded in *Rejected* so
they are not re-proposed from the same data.

## Context: the binding constraint is labels

3.8% of scenes carry any behavioural label, against 13,595 distinct scene
features — roughly fifteen features per labelled example. Worse, the labels are
effectively single-class: 913 of 914 scored scenes are positive. The model has
never seen a negative example it did not infer from absence.

That is why WP2 and WP3 (which create labels) rank above WP5 (which uses
existing labels better), and why several attractive-looking ideas were rejected
outright: with this sample size the evaluation cannot resolve them.

---

## WP1 — The model digest must identify the code that produced it

**Problem.** `model_digest` is built from feature version, evidence
fingerprint, source fingerprint, config, the similarity cutoff,
`MODEL_BUILD_VERSION`, and a day-truncated `reference_at_ms`.
`_source_fingerprint()` hashes source *data* only — plays, performers, studios,
files — never code. So an algorithm change deployed with unchanged feedback,
features and config produces an **identical `model_id`**, finds the published
row, increments `reuse_count`, and serves the previous algorithm's artifact.

**Evidence.** Reproduced under controlled conditions: two builds with
materially different Go scoring code produced the same `model_id`, and the
second returned `reused=True` without running. Deleting the artifact was
required to force an honest rebuild. In production the window was real —
`model-a3a…` was built six minutes before `2a7cddc` changed the affinity
algorithm, and carries `reuse_count = 1`.

**Change.** Make code identity part of the key. `algorithm_version`
(`curator/config.py:78`, currently 6) already sits in `config.canonical_json()`
and therefore already reaches the digest — it simply is never bumped. Either
enforce bumping it whenever scoring semantics change, or derive a build
fingerprint automatically so the discipline is not manual.

**Files.** `curator/config.py`, `curator/model/builder.py` (digest
construction), `core/modelbuild3.go` (`modelSubConfig`).

**Acceptance.** A test that changes scoring behaviour without touching
feedback, features or config, and asserts the resulting `model_id` differs.

**Effort.** Low. **Depends on.** Nothing. **Confidence.** Certain — this is a
demonstrated defect, not a hypothesis.

**Shipped** in PR #182, by the second route rather than the first: a manifest
of the scoring sources is hashed into a shared constant that both the Go
builder and the Python oracle feed into the digest, so the identity is derived
rather than remembered. `algorithm_version` had been bumped once in the
repository's history against dozens of scoring commits, which settled the
choice between enforcing the bump and deriving the fingerprint.

---

## WP2 — Re-shape the watch-time response curve, per instance

**Problem.** `viewing_outcome()` is monotonically increasing in watch time:
`view_positive_max · (1 − e^−(t−30)/90)`. Measured against an outcome the curve
cannot influence (did the user return to that scene on a later day), the real
relationship is an **inverted U peaking near 60 seconds**. The curve therefore
assigns its maximum where measured outcomes are near-worst.

**Evidence.** Per scene, on first play:

| first-play | scenes | returned | rate | curve says |
|---|---|---|---|---|
| <15s | 337 | 18 | 5.3% | −0.192 |
| 30–60s | 107 | 22 | **20.6%** | +0.054 |
| 90–120s | 135 | 23 | 17.0% | +0.198 |
| 3–5m | 200 | 14 | **7.0%** | +0.316 |
| 5–10m | 58 | 5 | 8.6% | +0.347 |

30–60s versus 3–5m is a 13.6-point gap at ≈3.2σ. A 3–5 minute play and a
sub-15-second play have statistically similar outcomes and are scored half a
point apart.

A logistic fit, quadratic in log-duration, is estimable and generalises:
`logit(p) = −3.332 + 0.734·ln t − 0.092·(ln t)²`, peak at 53s, LR test against a
monotone fit p = 0.0092, and it wins on 5-fold held-out likelihood
(437.45 vs 439.79 vs 442.60 for constant).

**Change.** Fit three coefficients per instance at build time and store them in
the model artifact, so they version, reproduce, and reach the digest. Keep the
existing output range so nothing downstream sees a new contract.

Guards, so a cold install is never worse off:

- minimum sample (order of 200 first-plays, 30+ positives);
- adopt only if the fit beats the shipped constants on **held-out** likelihood
  — "it won", not "it converged";
- require negative curvature; otherwise keep the default.

Shrink the fitted coefficients toward the global default in proportion to
sample size, so an instance moves smoothly from shipped to personal behaviour
rather than jumping between builds.

**Two known flaws in the current fit.** It is too generous below 30s (+0.134 at
15s, where the empirical rate is well under the base rate), because a quadratic
cannot fall fast enough at the left edge while also fitting the peak and tail —
so keep the existing `short_exit_seconds` cliff and replace only the rise. And
roughly 90% of sessions are `historical_imputed` rather than observed, so the
durations are reconstructed from Stash history rather than measured directly.

**Files.** `curator/events/curves.py`, `curator/events/contracts.py`,
`core/historical.go`, model artifact schema.

**Acceptance.** Fitted curve beats the shipped constants on held-out
likelihood; guards demonstrably fall back on a synthetic cold instance.

**Effort.** Medium. **Depends on.** Nothing. **Confidence.** High for the
shape; medium for any specific parameterisation.

---

## WP3 — Implicit negatives from impressions

**Problem.** Every recommendation the UI has rendered is recorded with its rank
and the score that placed it there. `impression_item` is read by **zero**
model-build files. The model infers dislike from absence, which is
indistinguishable from "never surfaced". A skip is a far stronger statement.

**Evidence.** Excluding prefetched impressions (which were never displayed):
607 scenes shown, 106 ever played, **501 never played** — the only genuine
negative class available anywhere in the data.

**Change.** Treat a non-prefetched impression with no subsequent play as weak
negative evidence, weighted by position. The shape maps onto machinery that
already exists: this is the pairwise-pick mechanism with a weaker gradient, and
`_pair_events`' surprise / IPS weighting is the right tool for discounting a
skip at rank 40 against one at rank 1.

**Three limitations, all real.**

1. *Attribution is one-directional.* 1,533 of 1,696 sessions are
   `historical_imputed` and 172 are `direct_player`, of which 13 carry an
   impression id. Only 18 sessions fall within an hour of a showing. Plays
   mostly do not flow through Curator, so an impression cannot be credited with
   causing a play. The negative side survives this — "shown and never played"
   needs no attribution — but position-bias correction is weaker without it.
2. *Development browsing inflates skips.* Lanes are viewed heavily while
   working on them. The `prefetched` flag removes speculative fetches
   (164 of 449), but repeated deliberate viewing remains. It biases toward more
   skips of repeatedly-shown scenes, which is at least a known direction.
3. *It is not symmetric with a play.* A skip should carry materially less
   weight than a watch, and the weight is a parameter to fit, not assume.

**Files.** `curator/model/builder.py` (a negative channel alongside
`_pair_events`), `core/modelbuild.go` for parity.

**Acceptance.** Skipped scenes differ measurably from never-shown ones before
any modelling work begins. If they do not, stop.

**Effort.** Medium. **Depends on.** Nothing. The original "better after WP4"
no longer applies: WP4 is withdrawn, so attribution will not improve and the
negative class — which needs none — is the whole of the package.
**Confidence.** Medium — the class exists, its informativeness is unverified.

---

## WP4 — Record which impression a play came from

**Withdrawn on measurement.** The proposed scene-plus-time-window join cannot
clear its own acceptance bar; see *Rejected, with reasons*. The problem it
described is real, but inference is not the remedy.

---

## WP5 — Hierarchical affinity smoothing over the tag taxonomy

**Problem.** Affinities are learned per flat `feature_id` and thin features are
shrunk toward a global zero. A structured tag hierarchy exists and is ignored.

**Evidence.** 565 of 830 tags used on scenes have a parent (68%), covering
**76.8%** of all scene-tag links.

**Change.** Let a child tag borrow from its parent: the prior stops meaning
"no opinion" and starts meaning "what we know about the category".
`affinity_prior` already exists — it simply points at zero.

**Why it cannot regress disorganised tags.** A tag with no parent has nothing
to borrow and keeps exactly today's prior. The unorganised 23% behaves
identically to now; only the organised majority changes. This is unusually safe
for a change to the scoring core.

**Files.** `curator/model/builder.py` (`_affinities`), `core/modelbuild.go`.

**Acceptance.** Parent-level affinity predicts child-tag behaviour better than
the global prior — check before building.

**Effort.** Medium. **Depends on.** Nothing. **Confidence.** Medium-high.

Note WP2 and WP5 want the same primitive: shrinkage toward a structured prior
in proportion to evidence. Building it once, generally, is worth considering.

---

## Rejected, with reasons

Recorded so they are not re-derived from the same data.

- **Completion ratio instead of absolute watch time.** Premise false: a short
  play is often a *good* sign in this library, so normalising by scene length
  does not fix the curve. Superseded by WP2, which addresses the curve's shape.
- **Conjunctive component combination.** The observation is solid — a demoted
  cluster showed a content-to-performer ratio of 2.99 against a corpus norm of
  1.57, i.e. theme evidence carrying weak performer evidence into the top
  decile, which an additive score permits and a conjunctive one would not. But
  no tested remedy clears the bar: geometric mean +0.011 AUC (95% CI
  [−0.013, +0.034]), min() +0.005, an explicit imbalance penalty 0.000 at 0.5
  and −0.008 at 1.0. Revisit once WP3 supplies more labels.
- **Amplifying `performer_similarity`.** Selection ignores affinity and the
  normalisation makes the result a weighted mean, both real defects. Fixing
  them raised the signal 8.5× and moved model fit by −0.002 ± 0.005, because
  the component has no measurable relationship to observed behaviour
  (ρ = −0.010 against +0.20 to +0.28 for every other family).
- **Marker timing as within-scene sentiment.** 62,706 of 62,707 markers have no
  `end_seconds` — they are point events, so segment-level watching is not
  answerable, only "did the session reach this moment". Weaker than it appears
  and the most expensive to build.
- **Inferring a play's impression from a scene-plus-time-window join (WP4).**
  The acceptance bar was "a materially larger share of sessions carry an
  impression id". Measured against the same snapshot: of the unlinked sessions
  in the impression era, the join attributes 3% at a five-minute window and 4%
  at two hours; stretching to twenty-four hours reaches 8% at the cost of
  calling a day-old showing causal. The ceiling is the reason. Only **22%** of
  those sessions played a scene that had *ever* been impressed, with no time
  bound at all — so no window tuning can pass roughly one session in five, and
  the realistic windows reach a twentieth of that.

  The cause is the one WP4's own evidence section named: plays originate in
  Stash's UI, not Curator's. Curator has impressed a small fraction of the
  library, and roughly four in five played scenes were never among them. This
  was checked against an instrumentation explanation and rejected — impressions
  are recorded across every lane, on every day of the sample, from both the
  plugin route and the similar-scene surface. The gap is usage, not coverage.

  What survives: hardening *observed* linkage so a play started from a Curator
  card always carries its impression id. That has the same 22% ceiling, but the
  links are observed rather than inferred, and it needs no provenance flag.
  Not proposed here — the ceiling makes it low-value until Curator drives a
  materially larger share of plays.
- **Session sequence, time-of-day conditioning, ties as scale calibration.**
  Cheap and data-ready, but none matched how the library is actually used.

## Sequencing

WP1, WP2 and WP5 are independent. WP4 is withdrawn (see *Rejected*), which
removes WP3's stated dependency: attribution is not going to improve, so WP3
stands or falls on the negative class alone — which needs no attribution.

Suggested order: **WP1** (a demonstrated defect, low effort), **WP2** (largest
measured mis-fit), **WP5**, then **WP3**, whose own acceptance check —
skipped scenes differing measurably from never-shown ones — should be run
before any modelling work.

WP1 shipped in PR #182: the digest now carries a fingerprint of the scoring
sources, so an algorithm change with unchanged data and config no longer
reuses the previous algorithm's artifact.

## Method note

Four ideas were proposed on structural plausibility and failed when measured:
amplifying `performer_similarity`, serialising lane-classification
qualifications for memory, completion ratio, and — added after this document
was first written — WP4's impression inference. Each was a real mechanism never
sized against the thing it was meant to explain.

WP4 is the sharpest case, because the evidence that sank it was already in this
document. WP3's first limitation records that only 18 sessions fall within an
hour of a showing; nobody checked that number against WP4's acceptance bar
before ranking it second. Writing an acceptance criterion is not the same as
evaluating it.

Size each package before implementing it. The acceptance criteria above are
written as pre-conditions for that reason: an hour of SQL against a snapshot
settles most of them, and either answer is worth more than a week of
implementation on a hunch.
