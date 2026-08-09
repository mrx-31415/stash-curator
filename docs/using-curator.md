---
title: Using Curator
permalink: /using-curator/
---

# Using Curator

## Choose a lane

| Lane | Best used for |
| --- | --- |
| **For You** | A varied everyday mix of dependable matches, revisits, and a little discovery |
| **Best Bets** | Strong unseen matches with enough independent supporting evidence |
| **Revisit** | Scenes you previously enjoyed, shown again after enough time away |
| **Discover** | Mostly familiar recommendations plus one explained test of your taste |
| **Adventure** | Deliberate probes into uncertain or under-covered parts of the model |

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
queued durably in the browser during transient failures and applied in a batched
model update. A later explicit action can reverse earlier feedback; one action may
not change the next recommendation immediately.

Open **Taste Profile** to review tag beliefs and answer with a fixed sentiment
from strong dislike to strong like. A direct answer is strong evidence rather than a
hard exclusion; **Neutral** is an explicit near-zero preference, while **Clear
answer** returns the tag to behavior-derived inference. Answers are queued locally
during transient failures. Direct answers affect tag fit but do not count as separate
behavioral corroboration. Search includes classified local tags, including performer
attributes and tags that currently appear on zero scenes, so preferences can be declared
before that content enters the library.

After an accepted thumbs down, Curator may offer an optional, dismissible follow-up
with up to three relevant content tags. Answer only the tags that contributed to the
problem, or choose a scene-specific or metadata explanation; the original thumbs down
remains independent.

## Similar

Open Similar from Curator or the compass action on a Stash scene or performer.
Library results use content overlap and preference-aware performer profiles. Switch
to StashDB only when you want external candidates; local and remote results remain
separate and the reference entity stays visible.

| Source | What you get | Requirement |
| --- | --- | --- |
| **Library** | Related scenes or performers already in Stash | A synced Curator model |
| **StashDB** | External metadata candidates, ranked with local preferences | A configured StashDB stash-box |

Local matches use the configured page size. StashDB Similar keeps up to 100 matches
from one remote search and pages that stable result locally.

## Expand

Expand is optional StashDB discovery. Refresh its cache from Curator or with the
**Refresh Expand cache** task, then browse scenes and performers, save filters, or
shortlist candidates. Refresh is incremental where the StashDB instance supports the
`updated_at` watermark (fetching only changed entries) and falls back to a full fetch
otherwise; either way it keeps the existing candidates and rows discovered by hunts or
StashDB Similar, re-scores the pool when the model has changed, and drops candidates
older than the recent-release horizon. External results are metadata leads, not proof
that a scene is available locally. Filters and ordering are applied before paging. If Whisparr is
configured, **Send to Whisparr** appears on external scene cards; it sends only the
scene you explicitly select.
Use the tag action on an external scene to rate its tags that map exactly to local
tags; this does not create scene-level feedback for media outside the library.

The top-level Performer Hunt view queries StashDB directly for scenes listed for a selected local
performer with a StashDB identity. It compares exact StashDB scene links and separates
All, In library, and Not linked locally results; unlinked does not mean definitively
missing because local scenes without StashDB identities cannot be matched. Queries
follow StashDB pagination up to 1,000 scenes and disclose when that cap truncates the
result. Include and exclude tag filters apply to the fetched result.
The film action on a StashDB Similar performer card opens the same hunt for that
*external* performer directly, so its full catalog is fetched from StashDB instead of
being limited to the bounded Expand candidate cache.
The **Hide exact PHash matches** filter is enabled by default. It also applies to
Expand and StashDB Similar scenes. Disable it to inspect candidates marked
**Likely local · exact PHash**; a matching PHash is strong evidence, not guaranteed
identity.

## Prune

Prune groups explicit dislikes, suspected poor fits, and candidates surfaced during
exploration. Review each item before applying the configured tag. Applying or removing
the tag changes Stash metadata only; it does not delete a file or rewrite your feedback.
Curator never deletes media, and the tag can be removed from the same view or in Stash.

## Routine maintenance

- Sync after meaningful library or metadata changes.
- Run the first sync/build before expecting recommendation lanes to contain results.
- Back up before plugin updates and before uninstalling.
- Treat Adventure and external results as exploration, not guaranteed matches.
- If Curator feels stale, check task status and run the normal sync before a full one.
- Enable profiling only while measuring a reproducible slow operation; retained
  traces stay local until cleared.
