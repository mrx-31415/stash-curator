---
title: Local-first recommendations for Stash
description: Explainable recommendations, discovery, and reversible library review for Stash.
wide: true
---

<section class="hero">
  <div>
    <p class="eyebrow">Preview · local-first · explainable</p>
    <h1>Find the right scene without giving up control.</h1>
    <p class="lede">Stash Curator learns from your library history and feedback, builds varied recommendation lanes, and shows the evidence behind every choice. Your preference model stays on your machine.</p>
    <div class="actions"><a class="button" href="#install">Install the preview</a><a class="button secondary" href="{{ '/recommendations/' | relative_url }}">How it recommends</a></div>
  </div>
  <img class="hero-mark" src="{{ '/assets/stash-curator.svg' | relative_url }}" alt="Blue-violet Stash Curator compass">
</section>

<section class="install" id="install">
  <p class="eyebrow">Install</p>
  <h2>One plugin source</h2>
  <p>Requires Stash v0.31 and Python 3.12+ in Stash's plugin runtime. Add this URL under <strong>Settings → Plugins → Available Plugins</strong>:</p>
  <pre><code>https://mrx-31415.github.io/stash-curator/index.yml</code></pre>
  <p>Install <strong>Stash Curator</strong>, reload plugins, open the compass, and select <strong>Sync library</strong> once. <a href="{{ '/getting-started/' | relative_url }}">Read the setup guide →</a></p>
</section>

## A recommendation you can inspect

<section class="showcase">
  <div class="showcase-copy"><span class="pill">For You</span><h3>Reasons, not mystery scores</h3><p>Every card can open “Why this?” to show Appeal, Current Fit, confidence, supporting evidence, and any timing adjustment.</p></div>
  <div class="recommendation-captures">
    <div class="capture"><img src="{{ '/assets/showcase-recommendations.png' | relative_url }}" alt="Curator For You lane showing varied recommendations and source-lane icons" width="1909" height="730" loading="lazy" decoding="async"></div>
    <div class="capture capture-detail"><img src="{{ '/assets/showcase-explanation.png' | relative_url }}" alt="Why this panel with a plain-language reason and readable model evidence" width="455" height="686" loading="lazy" decoding="async"></div>
  </div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Discover + Expand</span><h3>Explore locally—or look beyond it</h3><p>Discover tests one explainable edge of your learned taste. Optional Expand searches StashDB metadata without uploading preference history.</p></div>
  <div class="capture-pair"><div class="capture"><img src="{{ '/assets/showcase-discover.png' | relative_url }}" alt="Local Discover lane explaining that it gently challenges one learned boundary" width="1919" height="722" loading="lazy" decoding="async"></div><div class="capture"><img src="{{ '/assets/showcase-expand.png' | relative_url }}" alt="External Expand view with locally scored StashDB candidates and a Wildcard result" width="1907" height="934" loading="lazy" decoding="async"></div></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Similar</span><h3>Similarity informed by preference</h3><p>Find related scenes or performers through shared content and missing-aware profiles, with local and StashDB results kept distinct.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-similar.png' | relative_url }}" alt="Similar view comparing a reference scene with preference-aware local matches" width="1919" height="944" loading="lazy" decoding="async"></div>
</section>

<section class="showcase">
  <div class="showcase-copy"><span class="pill">Prune</span><h3>Review, tag, reverse</h3><p>Curator can surface explicit dislikes and uncertain candidates for review. It never deletes media; applying or removing the configured tag is deliberate and reversible.</p></div>
  <div class="capture"><img src="{{ '/assets/showcase-prune.png' | relative_url }}" alt="Prune review queue with reversible tag actions and no delete control" width="1919" height="944" loading="lazy" decoding="async"></div>
</section>

## Local by design

<div class="grid">
  <article class="card"><h3>Your model stays yours</h3><p>History, feedback, features, scores, and explanations live in a plugin-owned SQLite sidecar.</p></article>
  <article class="card"><h3>Remote discovery is optional</h3><p>StashDB access uses bounded read-only metadata queries. It does not receive your learned preferences.</p></article>
  <article class="card"><h3>Library changes stay reversible</h3><p>Prune only adds or removes a configurable tag. Curator never deletes scenes or other media.</p></article>
</div>

## Preview status

Curator targets **Stash v0.31** and **Python 3.12+**. Recommendation lanes, feedback,
Similar, Expand, Prune, backup, and packaging are implemented. It remains pre-1.0
while installed-system compatibility, accessibility, and performance validation
continue. Start with [Using Curator]({{ '/using-curator/' | relative_url }}) or inspect
the [architecture]({{ '/architecture/' | relative_url }}).

## Acknowledgements and project provenance

The idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing.
