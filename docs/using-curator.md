---
title: Using Curator
permalink: /using-curator/
---

# Using Curator

## Choose a lane

| Lane | Best used for |
| --- | --- |
| **For You** | A varied everyday slate drawn from the other recommendation policies |
| **Best Bets** | Reliable unseen matches with enough supporting evidence |
| **Revisit** | Previously enjoyed scenes whose cooldown has recovered |
| **Discover** | Familiar appeal plus one explained unknown or stretch |
| **Adventure** | Deliberate model-gap probes where more misses are expected |

Cards are arranged as a slate. Curator avoids adjacent performer repetition and
softly varies studios and content, so the page is not merely the top 20 scores.
Previous and Next continue through that same ranked sequence, preserving earlier
variety decisions. Use the **Balanced** button beside a recommendation lane's
description to switch between varied and score-first order. This also updates
**Disable recommendation variety** in Curator's plugin settings. Both orders are
published with the model, so later pages do not rerank the library.

## Inspect and teach

Open **Why this?** for a plain-language reason and score tree. It separates durable
Appeal from Current Fit, shows confidence, and names positive or negative evidence.
The structured evidence—not generated prose—is authoritative.

Use thumbs up or down for direct feedback. The detail menu also supports **Not now**,
**Never show**, **Review for pruning**, and **Metadata is wrong**. New feedback is
queued durably in the browser during transient failures and applied in a small model
update. A later explicit action can reverse earlier feedback.

Open **Taste Profile** to review content-tag beliefs and answer with a fixed sentiment
from strong dislike to strong like. A direct answer is strong evidence rather than a
hard exclusion; **Neutral** is an explicit near-zero preference, while **Clear
answer** returns the tag to behavior-derived inference. Answers are queued locally
during transient failures.

## Similar

Open Similar from Curator or the compass action on a Stash scene or performer.
Library results use content overlap and preference-aware performer profiles. Switch
to StashDB only when you want external candidates; local and remote results remain
separate and the reference entity stays visible.
Local matches use the configured page size. StashDB Similar keeps up to 100 matches
from one remote search and pages that stable result locally.

## Expand

Expand is optional StashDB discovery. Refresh its cache from Curator or with the
**Refresh Expand cache** task, then browse scenes and performers, save filters, or
shortlist candidates. External results are metadata leads, not proof that a scene is
available locally. Filters and ordering are applied before paging. Optional Whisparr
actions require separate settings.

The top-level Performer Hunt view queries StashDB directly for scenes listed for a selected local
performer with a StashDB identity. It compares exact StashDB scene links and separates
All, In library, and Not linked locally results; unlinked does not mean definitively
missing because local scenes without StashDB identities cannot be matched. Queries
follow StashDB pagination up to 1,000 scenes and disclose when that cap truncates the
result. Include and exclude tag filters apply to the fetched result.
The **Hide exact PHash matches** filter is enabled by default. It also applies to
Expand and StashDB Similar scenes. Disable it to inspect candidates marked
**Likely local · exact PHash**; a matching PHash is strong evidence, not guaranteed
identity.

## Prune

Prune groups explicit dislikes, suspected poor fits, and candidates surfaced during
exploration. Review each item before applying the configured tag. Curator never
deletes media, and the tag can be removed from the same view or in Stash.

## Routine maintenance

- Sync after meaningful library or metadata changes.
- Back up before plugin updates and before uninstalling.
- Treat Adventure and external results as exploration, not guaranteed matches.
- If Curator feels stale, check task status and run the normal sync before a full one.
- Enable profiling only while measuring a reproducible slow operation; retained
  traces stay local until cleared.
