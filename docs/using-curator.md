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

## Inspect and teach

Open **Why this?** for a plain-language reason and score tree. It separates durable
Appeal from Current Fit, shows confidence, and names positive or negative evidence.
The structured evidence—not generated prose—is authoritative.

Use thumbs up or down for direct feedback. The detail menu also supports **Not now**,
**Never show**, **Review for pruning**, and **Metadata is wrong**. New feedback is
queued durably in the browser during transient failures and applied in a small model
update. A later explicit action can reverse earlier feedback.

## Similar

Open Similar from Curator or the compass action on a Stash scene or performer.
Library results use content overlap and preference-aware performer profiles. Switch
to StashDB only when you want external candidates; local and remote results remain
separate and the reference entity stays visible.

## Expand

Expand is optional StashDB discovery. Refresh its cache from Curator or with the
**Refresh Expand cache** task, then browse scenes and performers, save filters, or
shortlist candidates. External results are metadata leads, not proof that a scene is
available locally. Optional Whisparr actions require separate settings.

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
