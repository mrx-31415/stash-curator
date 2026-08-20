# Workpackage: Signal improvements (labels, calibration, and cache identity)

Status: WP1 shipped, WP2 and WP4 withdrawn on measurement, two proposed. Arising from
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

That is why WP3 (which creates labels) ranks above WP5 (which uses existing
labels better), and why several attractive-looking ideas were rejected
outright: with this sample size the evaluation cannot resolve them.

It is also why the scarcity cuts both ways. WP2 was withdrawn partly because
the only signals able to adjudicate its outcome variable — 24 scenes with an O
event — are too sparse to fit against. The same scarcity that makes new labels
valuable makes claims about labels hard to check.

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

**Withdrawn on measurement.** The inverted U is real, but the outcome it was
measured against does not mean what the package assumed. See *Rejected, with
reasons*.

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

Note WP5 wants shrinkage toward a structured prior in proportion to evidence.
WP2 wanted the same primitive; a working implementation of it, guards and all,
is on the withdrawn `feat/watch-time-curve` branch and can be lifted from there
rather than written again.

---

## Rejected, with reasons

Recorded so they are not re-derived from the same data.

- **Completion ratio instead of absolute watch time.** The overwhelming
  majority of played scenes register under 20% completion, so abandonment is
  not separable from normal use by this measure. Note that its original
  rejection here reasoned "a short play is often a *good* sign in this
  library", which the O-event measurement under WP2 contradicts outright: no
  sub-30-second first play has ever produced an O. That premise came from the
  same return-rate reading that sank WP2.
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
- **Re-shaping the watch-time curve against return-rate (WP2).** The inverted
  U reproduces exactly: measured against "did the user return to this scene on
  a later day", first plays of 30-60s return at roughly twice the base rate and
  plays of 3-5m at well below it, a quadratic in log-duration beats both a
  monotone and a constant fit on held-out likelihood, and the curve does assign
  its maximum where that outcome is near-worst.

  The outcome variable is the problem. It was chosen because the curve cannot
  influence it, which addresses circularity but never establishes that it
  tracks preference. Measured against the signals that actually state a
  preference, watch time runs the other way. By O events — the strongest label
  in the system, carrying `o_value = 1.0`:

  | first play | scenes | with an O | vs base (2.02%) |
  |---|---|---|---|
  | <30s | 330 | **0** (0.00%) | p = 0.0025 |
  | 30s-2m | 344 | 7 (2.03%) | p = 0.85 |
  | 2-5m | 457 | 16 (3.50%) | p = 0.043 |

  Not one sub-30-second first play ever produced an O. Median duration of O'd
  scenes is 144s against 100s for the rest (Mann-Whitney p = 0.00086). That is
  monotone in watch time — the shape the shipped curve already has, including
  its negative limb below the short-exit threshold.

  The two outcomes barely overlap: 120 scenes returned and 24 carry an O, but
  only 9 do both. They measure different things. The likely confound is that a
  long play is a scene consumed to satisfaction while a short one is a scene
  sampled and returned to *because it has not been watched yet* — so return
  rate reads as incompleteness of the first visit, not as liking.

  A fitted curve was built, mirrored in Go, and measured against a real library
  before this was caught. It moved two thirds of all labels, and the scenes it
  demoted hardest — single plays of 8-10 minutes — were confirmed by the
  library's owner to be among the best in it, while the ones it promoted were
  not. Qualitative review found this before the statistics did.

  Retargeting the fit at O events does not rescue the package: 24 O-positive
  scenes sit below the 30-positive guard the package itself specifies, so the
  fit would correctly refuse to adopt. Revisit only if a preference signal
  accumulates enough support to fit against.

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

WP1 is shipped. WP2 and WP4 are withdrawn on measurement (see *Rejected*),
which leaves WP5 and WP3, both independent.

WP4's withdrawal removes WP3's stated dependency: attribution is not going to
improve, so WP3 stands or falls on the negative class alone, which needs none.
Run its own acceptance check — do skipped scenes differ measurably from
never-shown ones — before any modelling work.

Suggested order: **WP5**, then **WP3**.

WP1 shipped in PR #182: the digest now carries a fingerprint of the scoring
sources, so an algorithm change with unchanged data and config no longer
reuses the previous algorithm's artifact.

## Method note

Five ideas were proposed on structural plausibility and failed when measured:
amplifying `performer_similarity`, serialising lane-classification
qualifications for memory, completion ratio, WP4's impression inference, and
WP2's curve re-shaping. Each was a real mechanism never sized against the thing
it was meant to explain.

WP4 and WP2 are the instructive pair, because both survived a careful reading
of this document and failed anyway, for different reasons.

WP4 was never sized against its own acceptance bar, even though the number that
sinks it was already written here — WP3's first limitation records that only 18
sessions fall within an hour of a showing.

WP2 is the sharper lesson. Its evidence was real and reproduced exactly; what
went unchecked was whether its *outcome variable* meant what it claimed. "An
outcome the curve cannot influence" rules out circularity and nothing else. A
proxy still has to be shown to track the thing being optimised, and this one
demonstrably does not — it disagrees with every explicit preference signal in
the data. Validate the target before fitting anything to it, and prefer a
target the user has stated over one inferred from behaviour.

It was caught by looking at the affected scenes. Any change that moves labels
should be spot-checked against titles someone can recognise before it ships;
two thirds of the labels moved, and the ranking looked wrong immediately to
someone who knew the library.

Size each package before implementing it. The acceptance criteria above are
written as pre-conditions for that reason: an hour of SQL against a snapshot
settles most of them, and either answer is worth more than a week of
implementation on a hunch.
