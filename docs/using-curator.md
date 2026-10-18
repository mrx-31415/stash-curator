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
Curator follows available theme colors and surfaces. With Sticky enabled, external
scene cards also use its studio/date row, performer names, and tag pills. Other
themes keep Curator's usual metadata layout. After updating, run **Refresh Expand
cache** once to fetch studio logos for existing discovery results.
Cards keep Appeal visible; selection evidence and lane rank are under **Why this?**.
For endless scrolling, enable **Virtual endless scrolling** under
**Manage → Settings → Page settings**, alongside **Results per page** (or Curator's plugin settings).
It is off by default. All three recommendation views then load the next ranked page
about four screen heights before the bottom, one request at a time. Thumbnails also
preload the next batch's screenshots at low priority; videos wait for hover.
Thumbnails and Wall render only nearby rows. Cards use the browser's
offscreen rendering support and stay mounted, preserving expanded panels and feedback
state; loaded cards still occupy memory. Returning from another Stash page restores
your position and nearby loaded batches in the same tab. Deep lists retain up to
12 nearby batches; earlier results load as you scroll upward. Storage size limits
can retain fewer batches. Changing filters,
moods, or choosing **New picks** starts a fresh list. **Results per page** controls
the fetch size; **Load more** also lets you load explicitly or retry a failed request.

Use **New picks** for a fresh draw from the lane's strongest
recommendations. Higher-ranked scenes have better odds, while scenes you saw
on screen recently have lower odds for a while. Scenes are never permanently
removed by rotation: their odds recover over the configured rotation cooldown
(7 days by default). A play or thumbs-up does not count as an ignored view.
Returning to the page keeps the current draw; a new local day or a new model
refreshes it. Refreshing the same lane twice in one tab also draws again; a
single refresh keeps the current cards in place.

## Play a lane

Choose a recommendation lane and your filters or mood, then click **Play lane**.
Playback starts with the current picks. Use **Next** beside the player or the
player's next-track button to advance; Curator fetches another batch from the
same lane when needed. Filters and mood stay fixed for that playlist, and scenes
already queued do not repeat. Deleted scenes are skipped.

The playlist stays in the current browser tab, including after a refresh.
**Stop playlist** returns the current scene to ordinary playback. When no more
scenes qualify, Curator shows **End of recommendations**. A failed fetch keeps
the current scene playing and offers **Retry next**. Moving on is manual.

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

The **Rate tags** action on recommendation and Library Similar cards lets you
rate the scene's tags with the sentiment controls, including **Never** and **Clear**.
Card rating actions open a wider slider panel, with one aligned label header and
one compact row per tag. Each row shows the current answer and **Clear**.
The panel shows the full list and scrolls with the page, with **Collapse** at the bottom.
On phones, shorter sliders show just the two end labels; the current answer stays
visible on the right. Long tag names are shortened to keep each rating on one row.
**Never (block)** excludes matching content; it is stronger than dislike.

After an accepted thumbs down, Curator may offer an optional, dismissible follow-up
with up to three relevant content tags. Answer only the tags that contributed to the
problem, or choose a scene-specific or metadata explanation; the original thumbs down
remains independent.

### Affinity on detail pages

Scene and performer pages show one collapsed Curator bar below the ratings and
O-count controls. The bar keeps affinity or Appeal, confidence, and **Similar**
visible; performers also have **Performer Hunt**. Click the triangle or use the
keyboard to expand the details. The bar stays in place when expanded.

Under **Manage → Settings → Page settings → Detail page controls**, choose
**Large** (default) for the full-width bar, **Small** for compact icons and a score
inside the existing toolbar, or **Off** to hide these page controls. In Small mode,
expanding moves the details below the toolbar; collapsing returns the icons to it.

Performer details separate scene evidence, favorite/rating, and similar-performer
inference. They name the similar performers used by the published model and link
to up to eight scenes with the strongest learning evidence. Those scenes are model
inputs, not necessarily explicit performer likes or dislikes.

Scene details separate long-term Appeal from Current Fit, show direct history, and
name contributing content features, performers, studios, and fit adjustments.
Expand **Why this score?** for the explanation or **Scenes behind this estimate**
for related-scene evidence when available. Individual input signals do not add
directly to Appeal because the model applies family weights and score bounds.
Missing evidence is distinct from a learned neutral preference; confidence describes
evidence strength, not the probability of enjoyment.

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

Choose **Cards** or **Thumbnails** in Expand, Similar, Performer Hunt, or Shortlist.
Find remembers this choice separately from Recommendations. Thumbnails show only
the image; switch to Cards for match details and actions. Library scene thumbnails
play previews on hover; external results and performers show still images.

The **Virtual endless scrolling** switch in **Page settings** applies to Find too.
Both Cards and Thumbnails load the next batch early as you approach the bottom.
They restore your position and nearby batches when you return from another Stash page.
Loaded cards retain their expanded controls while the browser skips offscreen
rendering. Turn the switch off to use pagination.
Library Similar's playing Wall keeps pagination to bound simultaneous videos.

### Expand

Find and recommendation cards keep evidence and score breakdowns under **Why this?**,
with the remaining actions alongside it. Date, primary score, and tag/performer counts
share a row where space allows, above the description. Local tag ratings sit beside
the thumbs. External thumbnails open StashDB, so cards omit separate Open and Copy
buttons. Expand has pagination above and below its results; both controls preserve
the current filters and sort order.
On mobile, pagination uses compact first («), previous (‹), next (›), and last (») page buttons around the current page, all on one line.

Expand ranks a refreshed pool of StashDB scene candidates and related performers
against your local model. Refresh its cache from Curator or with the **Refresh Expand
cache** task, then browse candidates, save filters, or shortlist leads. The refresh
retains eligible leads found through Similar and Performer Hunt, updates their scores
after model changes, and drops scenes outside the recent-release horizon.

Expand reuses the last query's ordering across pages. Changes to candidates, filters,
blocks, tag equivalents, or local library matches invalidate it; shortlist changes
appear immediately. Unchanged pages load only their own candidate payloads, using a
database revision marker instead of scanning the entire pool.

Scene ownership matches use a local index of StashDB IDs and exact pHashes, including
scenes without StashDB links. Sync maintains the index; scene hooks queue targeted
updates that Expand applies before filtering. Metadata edits that leave IDs and
hashes unchanged preserve cached ordering. Existing installs populate the index
as part of background Expand refresh and force-rebuild, or during a full sync.
Refresh also applies queued scene updates, so opening Expand after it completes
does not need to initialize the index. If none of these tasks has run yet, opening
Expand starts a background initialization task as a fallback. Expand shows
“Checking your library…” and automatically displays candidates when the task finishes;
progress and any failures appear in Manage → Tasks. The “Prepare local scene matches”
task retries interrupted initialization. Profiling separates fetching, indexing,
pending updates, and loading the local matches. After bulk fingerprint generation or
changes made outside Stash, run a full sync to reconcile changes missed by hooks.

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
**Rate tags** to rate tags that map exactly to local tags.
This does not create scene-level feedback for media
outside the library. Saved candidates appear in **Expand → Shortlist**.

### Similar

<figure class="capture guide-capture">
  <img src="{{ '/assets/showcase-find-poster.jpg' | relative_url }}" alt="Find with Expand, Similar, and Performer Hunt tabs above six related scene previews" width="960" height="675" loading="lazy">
  <figcaption>Similar results from the library for a selected scene.</figcaption>
</figure>

Open Similar from Curator or the **Similar** action on a Stash scene or performer.
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

Performer pages keep **Similar** and **Performer Hunt** in the collapsed
[Curator affinity bar](#affinity-on-detail-pages), alongside the score and confidence.

The film action on a StashDB Similar performer card opens the same hunt for that
*external* performer directly, so its full catalog is fetched from StashDB instead of
being limited to the bounded Expand candidate cache.

On Stash's **Performers** card grid, a compact Curator pill sits at the bottom right
of each portrait, above Ascension's badge when present. It shows affinity and the
Similar/Hunt actions.
The grid shares one affinity request while cards load.
Choose **Curator affinity** in Stash's **Performers** sort menu to order the full
filtered result by your current affinity estimate. The direction arrow switches
between highest and lowest affinity; performers without an estimate remain last.
Filters, pagination, and the existing card and list views still apply. Matching
performer IDs are cached for up to 30 seconds, so recent metadata edits may take
that long to change the result set.
In the same page's filter dialog, choose **Curator affinity** to compare the score
with a decimal value (for example, **Greater than 0.15**). It works with native
sorts as well as Curator affinity sorting, and filters before pagination. **Is
null** selects performers without an estimate; **Is not null** selects performers
with an estimate, including zero. Other comparisons exclude unestimated performers.

Stash's native scene card grids show a compact Curator pill over the thumbnail,
with Appeal, model confidence, a divider, and a **Similar** shortcut. It uses the
performer pill's design and sits at the bottom left, leaving native resolution and
duration visible at the bottom right.
The scene detail toolbar uses the same pill, including the **Similar** shortcut.
**Curator Appeal** in a scene list's sort menu orders
the full filtered result by long-term scene Appeal; scenes without a published
estimate stay last in either direction. The same filter accepts decimal comparisons
and **Is null**/**Is not null** for scenes without/with an estimate, including zero.
Native search, other filters, pagination, counts, duration, and file-size totals
apply to the matching scenes. Scores are looked up in batches, and sorting and
filtering run in the backend. This uses the existing published model's Appeal on
the -1 to +1 scale; Current Fit and lane ranking remain separate. Newly added scenes
may lack an estimate until the next sync and model build.

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
- Automatic and scheduled tasks wait while a Curator page is visible, then resume
  90 seconds after its last heartbeat. This applies across tabs and users. Tasks
  you start explicitly still run; a task already running finishes normally.
- On Linux containers, the worker uses half the container memory limit as a soft
  Go memory budget, leaving room for Stash and build subprocesses. An explicit
  `GOMEMLIMIT` takes precedence.
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
  traces stay local until cleared. `worker-*` traces measure actual background
  execution; task traces without that prefix measure the request to enqueue work.
