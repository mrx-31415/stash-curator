---
title: Rediscover your Stash library
description: Local recommendations shaped by viewing and feedback, with optional StashDB discovery.
wide: true
---

<section class="hero">
  <div>
    <p class="eyebrow">Preview · Stash plugin</p>
    <h1>Rediscover scenes in your Stash library.</h1>
    <p class="lede">Curator uses your library metadata, viewing history, and feedback to recommend scenes you already have. Open <strong>Why this?</strong> to see why a scene appeared and correct the model when it gets something wrong. Connect StashDB for optional external metadata leads scored against your local taste model.</p>
    <div class="actions"><a class="button" href="#install">Install the preview</a><a class="button secondary" href="{{ '/recommendations/' | relative_url }}">How it recommends</a></div>
  </div>
  <img class="hero-mark" src="{{ '/assets/stash-curator.svg' | relative_url }}" alt="">
</section>

<section class="install" id="install">
  <p class="eyebrow">Install</p>
  <h2>Install and build your first recommendations</h2>
  <p>Requires Stash v0.31 and a <code>python</code> executable for the plugin launcher. Curator ships compiled core binaries for supported platforms; StashDB is optional. Add this URL under <strong>Settings → Plugins → Available Plugins</strong>:</p>
  <pre><code>https://mrx-31415.github.io/stash-curator/index.yml</code></pre>
  <p>Install <strong>Stash Curator</strong>, reload plugins, open the compass, and select <strong>Sync and build recommendations</strong> in the setup checklist or under <strong>Manage → Tasks</strong>. The first build can take several minutes. <a href="{{ '/getting-started/' | relative_url }}">Check prerequisites and follow the setup guide →</a></p>
  <p>When it is ready, open <strong>Recommendations → For You</strong>. Try <strong>Why this?</strong> on a suggestion, then give a thumbs up/down or compare scenes in <strong>Curate → Pair picks</strong>. Feedback affects rankings after a model update.</p>
</section>

## Curator in action

<section class="showcase" id="tour">
  <div class="showcase-copy"><span class="pill">Tour</span><h3>See scenes move before you choose</h3><p>Recommendations, Find, and Pair picks move through this eleven-second silent tour. Use the video controls to pause or replay it.</p></div>
  <div class="capture"><video controls autoplay muted loop playsinline poster="{{ '/assets/showcase-tour-poster.jpg' | relative_url }}" aria-label="Stash Curator tour" aria-describedby="tour-description" width="960" height="675"><source src="{{ '/assets/showcase-tour.webm' | relative_url }}" type="video/webm"><source src="{{ '/assets/showcase-tour.mp4' | relative_url }}" type="video/mp4">Your browser cannot play this video. <a href="{{ '/assets/showcase-tour.mp4' | relative_url }}">Download the tour</a>.</video></div>
  <p class="demo-note" id="tour-description">The video opens on For You recommendations with six moving scene previews, switches to Find's Similar results, then shows two scenes in Pair picks and advances to another pair after a choice.</p>
  <p class="demo-credit">Demo excerpts from <a href="https://video.blender.org/videos/watch/6402b77c-b61f-4a06-96ca-c8420a2becf4">Big Buck Bunny</a> and <a href="https://video.blender.org/videos/watch/64222c8a-c4c7-4b3b-9850-7fb2078edcf6">Glass Half</a> (<a href="https://creativecommons.org/licenses/by/3.0/">CC BY 3.0</a>), and <a href="https://video.blender.org/videos/watch/23f3ef79-15dc-44c5-aa45-cf92e78a4509">Caminandes: Llamigos</a> and <a href="https://video.blender.org/videos/watch/7b2eff2a-35f2-4403-9d88-d0dd6e4b5ba1">The Daily Dweebs</a> (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>). © Blender Foundation. Excerpts shortened, muted, and cropped.</p>
</section>

<div class="grid">
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#choose-a-lane">Recommendations →</a></h3><p>Start with For You, find strong unwatched matches in Best Bets, or return to familiar scenes in Revisit. Stretch, Blind Spots, and Dormant help you explore more of your library.</p></section>
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#find">Find →</a></h3><p>Find opens on Expand, which ranks a refreshed pool of StashDB leads when connected. Similar finds related scenes in your library or on StashDB; Performer Hunt follows a performer’s catalog. External results are leads, not proof that a scene is available locally.</p></section>
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#curate">Curate →</a></h3><p>Choose between two scenes in Pair picks or rate tags in Tag sentiment to teach Curator what you like. After a model update, Impact shows which preferences and recommendations changed.</p></section>
</div>

## Privacy and safety

Runs locally. Your history, feedback, and model stay in a SQLite sidecar you control;
StashDB is optional, read-only, and never sees your model. The only Stash mutation is
an explicit, reversible Prune tag — Curator never deletes media. See [Privacy]({{ '/privacy/' | relative_url }}).

## Preview status

Curator targets **Stash v0.31**. It remains preview software and
pre-1.0. The first sync/model build can take several minutes on a large library. Its
persistent background tasks can keep recommendations up to date, and you can schedule
library syncs and backups. External discovery needs a configured
StashDB connection. Start with [Getting
started]({{ '/getting-started/' | relative_url }}), then read [Using Curator]({{ '/using-curator/' | relative_url }}).

## Acknowledgements and project provenance

The idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing.
