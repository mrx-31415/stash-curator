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
scene feedback, pair picks, and direct tag preferences.
Performer ratings and favorites, and studio favorites, provide additional hints.
Tags, performers, and studios connect those signals to other
scenes. Better metadata and a few deliberate answers give it more useful evidence;
you do not need to rate the whole library.

Pair picks express a relative preference between two scenes. Tag ratings
express a preference for that feature. **Strong dislike** lowers preference;
**Never** is a hard exclusion for matching content. **Clear answer** removes the
direct preference or block. These are separate from **Never show**, which suppresses
one scene.

Scene descriptions are display metadata, not recommendation signals. Description
term extraction and ratings have been retired; saved term answers are preserved
but no longer affect scores or exclusions. Scenes with sparse tags can still use
performer, studio, and viewing evidence. After updating, rebuild the model and
refresh Expand to replace previously computed scores.

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

The **Curator affinity** gauge on performer cards and pages shows the performer
signal used in recommendations: confidence-weighted scene evidence, your
performer rating and favorite bonus, and a weaker estimate from similar performers.
Similarity confidence increases with strong, agreeing matches and is capped at
65%. Missing performer attributes are unknown: similarity compares the usable
attributes on both performers, without requiring every field to be populated.
Conflicting matches reduce confidence. Strong direct evidence reduces the inferred
contribution. Estimates never become training evidence for other performers.
The similarity estimate appears after rebuilding the model. Its tooltip breaks
those contributions down while confidence is shown separately below the value.
A performer without evidence
shows **0.00 · No evidence**: they contribute zero, but this is not a learned neutral
preference. A dash means the value is loading or unavailable. Scene evidence
measures outcomes relative to your library baseline; a negative learned
contribution can coexist with a positive overall
preference. Favorites, rated performers, and performers with similarity evidence
can have a value without scene history.

This is a signed recommendation contribution: zero is neutral, positive values
favour the performer, and negative values reduce their contribution. Its size
is separate from confidence. A favorite adds +0.18; a performer rating adds
between -0.10 and +0.10, with 50/100 neutral. A favorite rated 100/100 therefore
starts at +0.28 before scene evidence. There is no +0.35 cap. The raw combined
signal includes a confidence-weighted similarity estimate; the ring fills at
magnitude 1.0. For scene scoring, direct performer evidence and similarity remain
separate contributions bounded to 0.30 and 0.16 respectively, alongside content,
studio, and other scoring signals.

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

Recommendation cards show a short reason for their selection, including positive
preference matches for Best Bets, prior outcomes and cooldown recovery for Revisit,
and the named past preference and time away for Dormant. For You uses each card's
source lane. The visible reason is capped at two lines; **Why this?** retains the
full explanation.

Stretch names a familiar anchor and its selected challenge, distinguishing too
little evidence from a negative preference estimate. Blind Spots names the
underexplored studio and tag, with play counts in the expanded explanation.
These facts belong to the model that selected the card; missing evidence is
reported as unavailable.

Negative scenes in Sentiment review name contributing content features, performers,
studios, and examples of similar scenes. Similar-scene outcomes are compared with
the library average; below-average outcomes need not be negative. Cooldown and
Not now affect Current Fit, so they are not reasons for negative sentiment.
These explanations describe estimates, not necessarily explicit dislikes.

Every explanation is planned from reason codes derived from published model evidence.
Curator derives it when you expand **Why this?**, keeping the recommendation page
fast. The plain-language summary names the strongest facts; the score tree exposes
the contributions, confidence, timing changes, exploration reason, and final lane.
The summary describes evidence stored in the model. It explains an estimate of your
preferences; use feedback to correct that estimate when a suggestion misses.
