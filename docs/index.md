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
  <img class="hero-mark" src="{{ '/assets/stash-curator.svg' | relative_url }}" alt="Blue-violet Stash Curator compass">
</section>

<section class="install" id="install">
  <p class="eyebrow">Install</p>
  <h2>One plugin source</h2>
  <p>Requires Stash v0.31 and Python 3.12+ in Stash's plugin runtime. Local recommendations do not require StashDB. Add this URL under <strong>Settings → Plugins → Available Plugins</strong>:</p>
  <pre><code>https://mrx-31415.github.io/stash-curator/index.yml</code></pre>
  <p>Install <strong>Stash Curator</strong>, reload plugins, open the compass, and run <strong>Sync library</strong> once to build the first model. <a href="{{ '/getting-started/' | relative_url }}">Read the setup guide →</a></p>
</section>

## Recommendations

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Tour</span><h3>Recommendations, Find, and Curate</h3><p>For You, Best Bets, Revisit, Stretch, Blind Spots, and Dormant offer distinct ways to explore. Switch to Find for related scenes, then Curate to teach the model with quick comparisons.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-navigation.gif' | relative_url }}" alt="Curator navigation moving between Recommendations, Find, and Curate with fictional cinematic scene cards" width="1280" height="820" loading="lazy" decoding="async"></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Find</span><h3>Follow a useful lead</h3><p>Similar finds related library scenes and performers. Expand optionally searches StashDB metadata against your local model, while Performer Hunt follows one performer’s external catalog. External results are leads, not proof that a scene is available locally.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-find.png' | relative_url }}" alt="Synthetic Find demo showing Similar, Expand, and Performer Hunt sections" width="1200" height="675" loading="lazy" decoding="async"></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Curate</span><h3>Teach, correct, inspect the change</h3><p>Pair picks teach shared preferences. Tag sentiment lets you correct a tag belief directly. Impact reports what the next model build changed, while Manage holds review and operational surfaces.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-curate.png' | relative_url }}" alt="Synthetic Curate demo with a fictional pair pick, tag sentiment, and compact impact summary" width="1200" height="675" loading="lazy" decoding="async"></div>
</section>

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
