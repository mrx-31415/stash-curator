---
title: How recommendations work
permalink: /recommendations/
---

# How recommendations work

Curator uses a deterministic, inspectable pipeline. You do not need to understand
the scoring to use it, but every score and explanation can be inspected. Missing
metadata is treated as unknown rather than negative, and an unplayed scene is never
assumed to be disliked.

## What teaches Curator

Curator uses Stash ratings and viewing history, playback captured in the browser,
scene feedback, pair picks, and direct tag or description-term preferences.
Performer ratings and favorites, and studio favorites, provide additional hints.
Tags, description terms, performers, and studios connect those signals to other
scenes. Better metadata and a few deliberate answers give it more useful evidence;
you do not need to rate the whole library.

Pair picks express a relative preference between two scenes. Tag and term ratings
express a preference for that feature. **Strong dislike** lowers preference;
**Never** is a hard exclusion for matching content. **Clear answer** removes the
direct preference or block. These are separate from **Never show**, which suppresses
one scene.

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

- **Best Bets** requires strong fit supported by corroborating signals or reliable
  direct positive evidence, and excludes anything with recorded viewing history.
- **Revisit** requires a prior strong positive and enough cooldown recovery.
- **Stretch** keeps a familiar anchor while naming one confirmed tag or studio the
  model challenges — either a dimension it has learned to dislike, or one it has too
  little evidence about — and requires that named challenge to exist.
- **Blind Spots** surfaces studios or confirmed tags you have barely played, gated
  on at least two independently corroborating facets so a single noisy field can't
  qualify a scene alone.
- **Dormant** offers unseen scenes with a performer, studio, or confirmed tag you had
  a real positive history with but haven't touched in a while. The model build checks
  how long that preference has been dormant.
- **For You** mixes those policies with conservative items early and only a small
  Blind Spots and Dormant share.

Hard exclusions, unavailable files, explicit suppression, and Prune state are
checked before lane scoring.

## Variety is presentation, not taste

After candidates qualify, Curator builds the ranked slate one card at a time. It
avoids adjacent performer repeats and softly varies studios and very similar content.
The page then draws from the strongest candidates: higher rank improves a scene's
odds, while recent qualified views that did not lead to a play or thumbs-up lower
them temporarily. These presentation choices do not change Appeal or the evidence
shown in **Why this?**.

**Balanced** uses the varied order; **Score-first** removes the variety adjustments.
Filters narrow the qualifying candidates without teaching a preference.

## How explanations work

Every explanation is planned from reason codes derived from published model evidence.
Curator derives it when you expand **Why this?**, keeping the recommendation page
fast. The plain-language summary names the strongest facts; the score tree exposes
the contributions, confidence, timing changes, exploration reason, and final lane.
The summary describes evidence stored in the model. It explains an estimate of your
preferences; use feedback to correct that estimate when a suggestion misses.
