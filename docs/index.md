---
title: Local-first recommendations for Stash
description: A local Stash plugin for personalized recommendations, discovery, and reversible library review.
wide: true
---

<section class="hero">
  <div>
    <p class="eyebrow">Preview · Stash plugin · local-first</p>
    <h1>Personalized recommendations for your Stash library.</h1>
    <p class="lede">Curator uses your library metadata, viewing history, and feedback to recommend scenes from your library. Each recommendation includes a reason. Similar, optional StashDB discovery, and reversible Prune review help you explore without giving up control.</p>
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

## A recommendation you can inspect

<section class="showcase">
  <div class="showcase-copy"><span class="pill">For You</span><h3>Reasons, not mystery scores</h3><p>Open “Why this?” to see why a scene fits your taste, how well-supported the estimate is, and whether timing or recent repetition changed its place.</p></div>
  <div class="recommendation-captures">
    <div class="capture"><img src="{{ '/assets/showcase-recommendations.png' | relative_url }}" alt="Curator For You lane showing varied recommendations and source-lane icons" width="1909" height="730" loading="lazy" decoding="async"></div>
    <div class="capture capture-detail"><img src="{{ '/assets/showcase-explanation.png' | relative_url }}" alt="Why this panel with a plain-language reason and readable model evidence" width="455" height="686" loading="lazy" decoding="async"></div>
  </div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Discover + Expand</span><h3>Explore locally—or look beyond it</h3><p>Discover stays inside your library while testing one explained boundary of your taste. Optional Expand browses StashDB metadata and scores candidates locally; external results are leads, not proof that a scene is available to you.</p></div>
  <div class="capture-pair"><div class="capture"><img src="{{ '/assets/showcase-discover.png' | relative_url }}" alt="Local Discover lane explaining that it gently challenges one learned boundary" width="1919" height="722" loading="lazy" decoding="async"></div><div class="capture"><img src="{{ '/assets/showcase-expand.png' | relative_url }}" alt="External Expand view with locally scored StashDB candidates and a Wildcard result" width="1907" height="934" loading="lazy" decoding="async"></div></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Similar</span><h3>Find related scenes and performers</h3><p>Compare preference-aware matches from your library or separate StashDB results. Missing metadata is treated as unknown, not as a dislike.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-similar.png' | relative_url }}" alt="Similar view comparing a reference scene with preference-aware local matches" width="1919" height="944" loading="lazy" decoding="async"></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Prune</span><h3>Review, tag, reverse</h3><p>Review explicit dislikes, suspected poor fits, and exploration candidates. Prune only adds or removes a configurable Stash tag; it never deletes media.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-prune.png' | relative_url }}" alt="Prune review queue with reversible tag actions and no delete control" width="1919" height="944" loading="lazy" decoding="async"></div>
</section>

## Local by design

<div class="grid">
  <article class="card"><h3>Private by default</h3><p>Your history, feedback, and preference model stay in a separate plugin-owned SQLite database.</p></article>
  <article class="card"><h3>Remote discovery is optional</h3><p>StashDB receives only bounded, read-only metadata queries. Your learned preferences are scored locally.</p></article>
  <article class="card"><h3>No delete action</h3><p>Prune changes only the configured tag, and you can remove that tag from Curator or Stash.</p></article>
</div>

## What Curator does not do

- It does not delete scenes or other media.
- It does not upload your viewing history, feedback, or preference model to StashDB.
- It does not require StashDB for local recommendations.
- It does not synchronize automatically in the background; use the Stash task or a host scheduler.

## Preview status

Curator targets **Stash v0.31** and **Python 3.12+**. It remains preview software and
pre-1.0. The first sync/model build can take several minutes on a large library;
NumPy acceleration is optional. External discovery needs a configured StashDB
connection, and Curator has no built-in background scheduler. Start with [Getting
started]({{ '/getting-started/' | relative_url }}), then read [Using Curator]({{ '/using-curator/' | relative_url }}).

## Acknowledgements and project provenance

The idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing.
