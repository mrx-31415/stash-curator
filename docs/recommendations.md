---
title: How recommendations work
permalink: /recommendations/
---

# How recommendations work

Curator uses a deterministic, inspectable pipeline. You do not need to understand
the scoring to use it, but every score and explanation can be inspected. Missing
metadata is treated as unknown rather than negative, and an unplayed scene is never
assumed to be disliked.

## Understand the scores

**Appeal** is the long-term estimate of how satisfying an item is likely to be. It
combines bounded evidence from content, performers, studios, similar scenes, and
direct item history. Strong direct outcomes can override weaker inferences.

**Current Fit** is how suitable the item is right now. It starts from Appeal and
adjusts for exact-scene cooldown, recent performer or content repetition, and **Not
now** feedback. Time changes today's fit; it does not erase learned taste.

**Confidence** is the strength and variety of the evidence behind the estimate. It is
not another preference score. A high estimate with thin evidence belongs in a
different lane than a high estimate backed by varied outcomes.

## Lane policy

- **Best Bets** requires strong fit and enough independent supporting evidence, and excludes
  anything with recorded viewing history.
- **Revisit** requires a prior strong positive and enough cooldown recovery.
- **Stretch** keeps a familiar anchor while naming one confirmed tag or studio the
  model challenges — either a dimension it has learned to dislike, or one it has too
  little evidence about — and requires that named challenge to exist.
- **Adventure** probes under-covered or conflicting regions of the model. It is not
  simply a list of low scores.
- **For You** mixes those policies with conservative items early and only a small
  Adventure share.

Hard exclusions, unavailable files, explicit suppression, and Prune state are
checked before lane scoring.

## Variety is presentation, not taste

After candidates qualify, Curator builds the page one card at a time. It avoids
adjacent performer repeats and softly varies studios and very similar content. These
choices alter the slate, not Appeal. A page can therefore be varied without changing
your learned preferences.

## Why the explanation is trustworthy

Every explanation is planned from reason codes derived from published model evidence.
Curator derives it when you expand **Why this?**, keeping the recommendation page
fast. The plain-language summary names the strongest facts; the score tree exposes
the contributions, confidence, timing changes, exploration reason, and final lane.
The wording may vary, but it cannot invent evidence that is not in the model.
