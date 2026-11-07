---
title: Plugins for Stash
description: Stash Curator makes plugins for Stash. Curator recommends scenes from your library; Auto Seek skips every intro. Both run locally.
wide: true
---

<section class="hub-hero">
  <p class="eyebrow">Stash Curator · plugins for Stash</p>
  <h1>Get more out of your <span>Stash library.</span></h1>
  <p class="lede">Two plugins that learn from your library and do the tedious part for you: one finds what to watch next, the other skips straight to where the action starts. Both run on your own server, and you can install either one, or both, from one plugin source.</p>
  <div class="actions"><a class="button" href="#install">Install</a><a class="button secondary" href="#plugins">Meet the plugins</a></div>
</section>

<div class="hub-plugins" id="plugins">
  <a class="hub-plugin curator" href="{{ '/curator/' | relative_url }}">
    <div class="hub-visual"><img src="{{ '/assets/showcase-tour-poster.jpg' | relative_url }}" alt="" loading="lazy"></div>
    <div class="hub-body">
      <div class="hub-title"><img src="{{ '/assets/stash-curator.svg' | relative_url }}" alt="" width="52" height="52"><div><h2>Curator</h2><p>Rediscover scenes you already have.</p></div></div>
      <ul>
        <li>Seven lanes of recommendations, from For You to Blind Spots</li>
        <li><strong>Why this?</strong> on every pick, and you can correct it</li>
        <li>Roulette, playlists and optional StashDB discovery</li>
      </ul>
      <span class="hub-more">Explore Curator →</span>
    </div>
  </a>
  <a class="hub-plugin auto-seek" href="{{ '/auto-seek/' | relative_url }}">
    <div class="hub-visual"><img src="{{ '/assets/auto-seek-demo.gif' | relative_url }}" alt="" loading="lazy"></div>
    <div class="hub-body">
      <div class="hub-title"><img src="{{ '/assets/auto-seek.svg' | relative_url }}" alt="" width="52" height="52"><div><h2>Auto Seek <span class="hub-new">New</span></h2><p>Skip the intro. Every scene.</p></div></div>
      <ul>
        <li>An image model finds where the action starts</li>
        <li><strong>Skip intro</strong> on the player, or skip automatically</li>
        <li>Worked out in the background, ready on every device</li>
      </ul>
      <span class="hub-more">Explore Auto Seek →</span>
    </div>
  </a>
</div>

<section class="install" id="install">
  <p class="eyebrow">Install</p>
  <h2>One plugin source, install what you like</h2>
  <p>In Stash, open <strong>Settings → Plugins → Available Plugins</strong>, select <strong>Add Source</strong>, and add:</p>
  <pre><code>https://mrx-31415.github.io/stash-curator/index.yml</code></pre>
  <p>Then install <strong>Stash Curator</strong>, <strong>Auto Seek</strong> or both, and reload plugins. They work independently. Both need Stash v0.31 and the <code>python</code> Stash already uses for plugins. Next steps: <a href="{{ '/getting-started/' | relative_url }}">getting started with Curator</a> · <a href="{{ '/auto-seek-guide/' | relative_url }}">the Auto Seek guide</a>.</p>
</section>

<section class="card hub-principle"><h3>Runs on your server</h3><p>Your library, history and feedback stay in files you control. Nothing is uploaded. The only network use is Curator's optional StashDB lookups and Auto Seek's one-off model download.</p></section>

## About

Stash Curator is open source under the AGPL-3.0 and is preview software, pre-1.0.
Demo footage comes from Blender Foundation films under Creative Commons Attribution:
[Big Buck Bunny](https://peach.blender.org) (CC BY 3.0) for Auto Seek, and the films
credited on the [Curator page]({{ '/curator/' | relative_url }}#tour).
Curator's idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).
The plugins are primarily generated with AI coding agents under human direction,
review, and testing. Issues and ideas are welcome on
[GitHub](https://github.com/mrx-31415/stash-curator).
