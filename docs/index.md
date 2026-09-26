---
title: Stash Curator — local recommendations and StashDB discovery
description: Local recommendations and StashDB discovery — curated to your taste.
wide: true
---

<section class="hero">
  <div>
    <p class="eyebrow">Preview · Stash plugin</p>
    <h1>Recommendations from your library, and discovery beyond it.</h1>
    <p class="lede">Stash Curator learns your taste from your library metadata, viewing history, and feedback — then uses that taste to recommend from two places: the scenes already in your library, and the wider catalog on StashDB. Every recommendation is inspectable, and you can correct a belief directly.</p>
    <div class="actions"><a class="button" href="#install">Install the preview</a><a class="button secondary" href="{{ '/recommendations/' | relative_url }}">How it recommends</a></div>
  </div>
  <img class="hero-mark" src="{{ '/assets/stash-curator.svg' | relative_url }}" alt="">
</section>

<section class="install" id="install">
  <p class="eyebrow">Install</p>
  <h2>One plugin source</h2>
  <p>Requires Stash v0.31 and Python 3.12+ in Stash's plugin runtime. Local recommendations do not require StashDB. Add this URL under <strong>Settings → Plugins → Available Plugins</strong>:</p>
  <pre><code>https://mrx-31415.github.io/stash-curator/index.yml</code></pre>
  <p>Install <strong>Stash Curator</strong>, reload plugins, open the compass, and run <strong>Sync library</strong> once to build the first model. <a href="{{ '/getting-started/' | relative_url }}">Read the setup guide →</a></p>
</section>

## Curator in action

<section class="showcase" id="tour">
  <div class="showcase-copy"><span class="pill">Tour</span><h3>See scenes move before you choose</h3><p>Recommendations, Find, and Pair picks move through this eleven-second silent tour. Use the video controls to pause or replay it.</p></div>
  <div class="capture"><video controls autoplay muted loop playsinline poster="{{ '/assets/showcase-tour-poster.jpg' | relative_url }}" aria-label="Stash Curator tour" aria-describedby="tour-description" width="960" height="675"><source src="{{ '/assets/showcase-tour.webm' | relative_url }}" type="video/webm"><source src="{{ '/assets/showcase-tour.mp4' | relative_url }}" type="video/mp4">Your browser cannot play this video. <a href="{{ '/assets/showcase-tour.mp4' | relative_url }}">Download the tour</a>.</video></div>
  <p class="demo-note" id="tour-description">The video opens on For You recommendations with six moving scene previews, switches to Find's Similar results, then shows two scenes in Pair picks and advances to another pair after a choice.</p>
  <p class="demo-credit">Demo excerpts from <a href="https://video.blender.org/videos/watch/6402b77c-b61f-4a06-96ca-c8420a2becf4">Big Buck Bunny</a> and <a href="https://video.blender.org/videos/watch/64222c8a-c4c7-4b3b-9850-7fb2078edcf6">Glass Half</a> (<a href="https://creativecommons.org/licenses/by/3.0/">CC BY 3.0</a>), and <a href="https://video.blender.org/videos/watch/23f3ef79-15dc-44c5-aa45-cf92e78a4509">Caminandes: Llamigos</a> and <a href="https://video.blender.org/videos/watch/7b2eff2a-35f2-4403-9d88-d0dd6e4b5ba1">The Daily Dweebs</a> (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>). © Blender Foundation. Excerpts shortened, muted, and cropped.</p>
</section>

<div class="grid">
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#choose-a-lane">Recommendations →</a></h3><p>For You, Best Bets, Revisit, Stretch, Blind Spots, and Dormant offer distinct ways to explore your library.</p></section>
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#find">Find →</a></h3><p>Similar finds related library scenes and performers. Expand can search StashDB metadata against your local model, while Performer Hunt follows one performer’s external catalog. External results are leads, not proof that a scene is available locally.</p></section>
  <section class="card"><h3><a href="{{ '/using-curator/' | relative_url }}#curate">Curate →</a></h3><p>Pair picks teach shared preferences. Tag sentiment lets you correct a tag belief directly. Impact reports what the next model build changed, while Manage holds review and operational surfaces.</p></section>
</div>

## Privacy and safety

Runs locally. Your history, feedback, and model stay in a SQLite sidecar you control;
StashDB is optional, read-only, and never sees your model. The only Stash mutation is
an explicit, reversible Prune tag — Curator never deletes media. See [Privacy]({{ '/privacy/' | relative_url }}).

## Preview status

Curator targets **Stash v0.31** and **Python 3.12+**. It remains preview software and
pre-1.0. The first sync/model build can take several minutes on a large library. Its
persistent worker can apply automatic model and recent-play updates; scheduled Expand
refresh, sync/build, and backups are configurable. External discovery needs a configured
StashDB connection. Start with [Getting
started]({{ '/getting-started/' | relative_url }}), then read [Using Curator]({{ '/using-curator/' | relative_url }}).

## Acknowledgements and project provenance

The idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing.
