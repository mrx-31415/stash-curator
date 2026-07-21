---
title: How recommendations work
permalink: /recommendations/
---

# How recommendations work

Curator uses a deterministic, inspectable pipeline. It treats missing metadata as
unknown rather than negative and never assumes an unplayed scene is disliked.

## The three numbers that matter

**Appeal** estimates how satisfying an item is likely to be in general. It combines
bounded evidence from content, performers, studios, similar scenes, and direct item
history. Strong direct outcomes can override weaker inferences.

**Current Fit** starts from Appeal and adjusts for timing: exact-scene cooldown,
recent performer or content repetition, and **Not now** feedback. Time changes
whether something fits today; it does not erase learned taste.

**Confidence** describes how much independent, relevant evidence supports the
estimate. It is not another preference score. A high estimate with thin evidence
belongs in a different lane than a high estimate backed by varied outcomes.

## Lane policy

- **Best Bets** requires strong fit and enough corroborating evidence, and excludes
  anything with recorded viewing history.
- **Revisit** requires a prior strong positive and enough cooldown recovery.
- **Discover** keeps a familiar anchor while testing one named uncertainty or mild
  negative assumption.
- **Adventure** probes under-covered or conflicting regions of the model. It is not
  simply a list of low scores.
- **For You** mixes those policies with conservative items early and only a small
  Adventure share.

Hard exclusions, unavailable files, explicit suppression, and Prune state are
checked before lane scoring.

## Variety is presentation, not taste

After candidates qualify, Curator builds the page one card at a time. Shared
performers are avoided in adjacent cards; repeated studios and very similar content
receive soft penalties. These choices alter the slate, not Appeal. A page can
therefore be varied without pretending your preferences changed.

## Why the explanation is trustworthy

Every explanation is planned from stored reason codes and evidence. Deterministic
prose combines the strongest facts, while the expanded score tree exposes the
underlying contributions, confidence, timing changes, exploration reason, and final
lane choice. The wording may vary; the evidence cannot invent new facts.
