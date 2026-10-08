---
title: Using Curator
permalink: /using-curator/
---

# Using Curator

Start in **Recommendations** after the first sync and model build. Use **Find** for
related or external scenes, **Curate** to teach your preferences, and **Manage** for
history, Prune, tasks, backups, and settings.

The screenshots show an isolated demo with fictional metadata and Blender film
excerpts. [Film credits and licenses]({{ '/' | relative_url }}#tour).

## Choose a lane

<figure class="capture guide-capture">
  <img src="{{ '/assets/showcase-tour-poster.jpg' | relative_url }}" alt="For You recommendations with six scene previews and the six lane choices above them" width="960" height="675" loading="lazy">
  <figcaption>For You is one of six recommendation lanes.</figcaption>
</figure>

| Lane | Best used for |
| --- | --- |
| **For You** | A varied everyday mix of dependable matches, revisits, and a little discovery |
| **Best Bets** | Strong unseen matches supported by corroborating signals or reliable direct feedback |
| **Revisit** | Scenes you previously enjoyed, shown again after enough time away |
| **Stretch** | Mostly familiar recommendations, with one confirmed tag or studio named as the challenge |
| **Blind Spots** | Studios or tags you've barely watched, corroborated by more than one signal |
| **Dormant** | A performer, studio, or tag you used to watch a lot, parked for a while |

Cards are arranged as a slate. Curator avoids adjacent performer repetition and
softly varies studios and content, so the page is not merely the top 20 scores.
Previous and Next continue through that same ranked sequence, preserving earlier
variety decisions. Use the **Balanced** button beside a recommendation lane's
description to switch between varied and score-first order. This also updates
**Disable recommendation variety** in Curator's plugin settings. Paging uses the
current model; new feedback, plays, filters, or a model update can change the results.
Use the lane filters to narrow the selection. Choose **Cards** for feedback and
explanations, **Thumbnails** for a compact grid of screenshots without text overlays,
or **Wall** for muted playing previews. Thumbnails play a muted preview while hovered
and restore the screenshot when the pointer leaves; touch devices show screenshots.
The selected recommendation view is remembered in this browser.

Use **New picks** for a fresh draw from the lane's strongest
recommendations. Higher-ranked scenes have better odds, while scenes you saw
on screen recently have lower odds for a while. Scenes are never permanently
removed by rotation: their odds recover over the configured rotation cooldown
(7 days by default). A play or thumbs-up does not count as an ignored view.
Returning to the page keeps the current draw; a new local day or a new model
refreshes it. Refreshing the same lane twice in one tab also draws again; a
single refresh keeps the current cards in place.

## Inspect and teach

Open **Why this?** for a plain-language reason and score tree. It separates durable
Appeal from Current Fit, shows confidence, and names positive or negative evidence.
The score tree shows the evidence behind the summary.

Use thumbs up or down for direct feedback. The detail menu also supports **Not now**,
**Never show**, **Mark for pruning**, and **Metadata is wrong**. Check the card's
confirmation or error after submitting feedback. Accepted feedback contributes to a
batched model update, so one action may not change the next recommendation immediately.
Use **Manage → Feedback history** to undo or replace a mistaken answer. **Not now**
temporarily hides a scene without recording dislike; **Metadata is wrong** excludes
its current metadata from training.

To correct a tag belief directly, use [Curate → Tag sentiment](#tag-sentiment).

The **Rate tags & terms** action on recommendation and Library Similar cards also
lets you rate the scene's tags and description terms used by the model. The same
sentiment controls, including **Never** and **Clear**, apply to both.

After an accepted thumbs down, Curator may offer an optional, dismissible follow-up
with up to three relevant content tags. Answer only the tags that contributed to the
problem, or choose a scene-specific or metadata explanation; the original thumbs down
remains independent.

## Curate

Curate brings together Pair picks, Tag sentiment, and Impact.

### Pair picks

<figure class="capture guide-capture">
  <img src="{{ '/assets/showcase-curate-poster.jpg' | relative_url }}" alt="Pair picks showing two scenes and the Left, Right, Equal, and Skip choices" width="960" height="524" loading="lazy">
  <figcaption>Pair picks puts two scenes side by side for a quick choice.</figcaption>
</figure>

Choosing between two scenes teaches shared preferences across their tags, performers,
and studios. Pick **Left** or **Right**, choose **Equal**, or **Skip** if you have no
opinion. The arrow keys do the same; **Back** or Backspace undoes the previous answer.

### Tag sentiment

**Moods** hide selected tags and their descendants from every recommendation
lane without changing your learned taste. Create, rename, delete, and edit moods under
**Manage → Settings → Recommendations → Moods**. Search and select excluded tags as
in Performer Hunt; changes save automatically. Choose one mood or **Off** in the
recommendation dropdown; **Manage moods…** opens these settings.
The active mood defaults to Off and is remembered in a cookie in the current browser.
Mood definitions are shared, and edits apply on each browser's next recommendation refresh.
Deleting the active mood returns the browser to Off. Existing Mood mode exclusions
become a mood called **Together**, preserving the browser's previous On/Off choice.
Empty lanes keep the exclusions enforced. This filter applies to recommendations;
Similar, discovery, and ordinary Stash browsing keep their existing behavior.

Review tag beliefs and answer with a fixed sentiment from strong dislike to strong like.
A direct answer is strong evidence rather than a hard exclusion. The separate
**Never** setting blocks matching content. **Neutral** is an explicit near-zero
preference, while **Clear answer** removes your direct answer or block and returns
the tag to behavior-derived inference. Answers are queued locally during transient failures. Direct answers affect
tag fit but do not count as separate behavioral corroboration. Search includes classified
local tags, including performer attributes and tags that currently appear on zero scenes,
so preferences can be declared before that content enters the library.

### Impact

Impact compares model builds so you can see how your feedback changed preferences
and recommendations. Use **Manage** for tasks, backups, feedback history,
diagnostics, and settings.

## Find

Find opens on Expand. Connect StashDB and refresh its candidate cache to see external
leads; Similar also works with scenes already in your library.

### Expand

Scene cards in Find show a compact, two-line preview of the available match
evidence, with full details under **Why this?**. Expand has pagination above and
below its results; both controls preserve the current filters and sort order.
On mobile, pagination uses compact first («), previous (‹), next (›), and last (») page buttons around the current page, all on one line.

Expand ranks a refreshed pool of StashDB scene candidates and related performers
against your local model. Refresh its cache from Curator or with the **Refresh Expand
cache** task, then browse candidates, save filters, or shortlist leads. The refresh
retains eligible leads found through Similar and Performer Hunt, updates their scores
after model changes, and drops scenes outside the recent-release horizon.

Saved filters and their defaults are stored in Curator's database and are shared
across browsers, including private browsing sessions. Plugin updates retain them.
Existing browser-only filters are imported when you open Curator in that browser;
if a name already exists in the database, the database version takes precedence.
Mark a filter **Default** to apply it automatically when reopening its view.
Choose a saved filter from the selector, or expand **Save current filters** to
name and save your current settings. The selector shows the matching saved name;
changing its settings shows **Current filters (unsaved)** until you save them.

Results come from a cached selection, not a search of the entire catalog. By default,
each refresh fetches up to 1,000 candidates within a 90-day release window; you can
adjust both in settings.

External results are metadata leads, not proof that a scene is available locally.
Filters and ordering apply before paging. Include and exclude tag pickers search
both local tags and the cached StashDB tag catalog in Expand, Performer Hunt, and
StashDB Similar. StashDB-only tags do not need to exist in your library; names and
aliases filter remote results. Refresh Expand's cache to update that catalog.
If Whisparr is configured, **Send to Whisparr** appears on external scene cards;
it sends only the scene you select. Use
**Rate tags & terms** to rate tags that map exactly to local tags and description
terms known to the model. This does not create scene-level feedback for media
outside the library. Saved candidates appear in **Expand → Shortlist**.

### Similar

<figure class="capture guide-capture">
  <img src="{{ '/assets/showcase-find-poster.jpg' | relative_url }}" alt="Find with Expand, Similar, and Performer Hunt tabs above six related scene previews" width="960" height="675" loading="lazy">
  <figcaption>Similar results from the library for a selected scene.</figcaption>
</figure>

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

### Performer Hunt

Performer Hunt searches both local performers with a StashDB identity and performers
on StashDB. Select one to fetch their scene catalog directly from StashDB.
It compares exact StashDB scene links and separates
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

Open **Manage → Prune** to review explicit dislikes, suspected poor fits, and
candidates marked for pruning. **Broad & unwatched** surfaces scenes from studios
that occupy a large part of your library but have barely been played. Use the
aggressiveness slider to include less certain model suspects. Review each item before applying the
configured tag. Applying or removing the tag changes Stash metadata only; it does not
delete a file or rewrite your feedback. Curator never deletes media, and the tag can be
removed from the same view or in Stash.

## Routine maintenance

- Curator's background worker can apply pending model updates and recent-play syncs;
  optionally schedule Expand refresh, sync/build, and backups in plugin settings.
- Sync after meaningful library or metadata changes; a full sync reconciles deletions and
  tag merges that targeted entity hooks do not cover.
- Run the first sync/build before expecting recommendation lanes to contain results.
- Plays recorded by Stash are imported automatically after Curator playback so cooldown and
  recovery stay current; the **Sync recent plays** task can also be run manually.
- Changes to scenes, performers, studios, and tags in Stash are queued through entity
  hooks and imported before the next model update. They do not appear immediately.
- Back up before plugin updates and before uninstalling.
- Treat Blind Spots and external results as exploration, not guaranteed matches.
- If Curator feels stale, check task status and run the normal sync before a full one.
- Enable profiling only while measuring a reproducible slow operation; retained
  traces stay local until cleared.
