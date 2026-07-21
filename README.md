<p align="center">
  <img src="docs/assets/stash-curator.svg" alt="Stash Curator compass" width="112">
</p>
<h1 align="center">Stash Curator</h1>
<p align="center"><strong>Navigate your library, guided by your taste.</strong></p>

Stash Curator is a local-first recommendation and discovery plugin for
[Stash](https://github.com/stashapp/stash). It learns from viewing history and direct
feedback, explains why an item appears, and keeps the model in a sidecar SQLite
database you control.

![Stash Curator's For You lane showing varied recommendations](docs/assets/showcase-recommendations.png)

## Install

Preview requirements: **Stash v0.31** and **Python 3.12+** available to Stash's
plugin runtime. Add this source under **Settings → Plugins → Available Plugins**:

```text
https://mrx-31415.github.io/stash-curator/index.yml
```

Install **Stash Curator**, reload plugins, open the compass in Stash's navigation,
then select **Sync library** once. See [Getting started](docs/getting-started.md) for
configuration, updates, and backups.

## What it does

- **Recommendations:** For You balances dependable matches, timely revisits, and a
  little discovery; four dedicated lanes let you choose the mood.
- **Explanations:** “Why this?” shows the evidence, confidence, and timing behind a
  recommendation.
- **Similar:** find related scenes and performers using content and learned preference.
- **Expand:** optionally discover external StashDB candidates scored against your
  local model.
- **Prune:** review poor matches and apply a reversible tag; Curator never deletes media.

Curator separates long-term **Appeal** from **Current Fit**, then builds varied lanes
instead of sorting everything by one opaque score. Read [how recommendations work](docs/recommendations.md)
or browse the complete [documentation site](https://mrx-31415.github.io/stash-curator/).

## Safety and privacy

Preference history, learned weights, and explanations stay local. StashDB discovery
is opt-in and sends bounded read-only metadata queries, never your preference model.
The only intentional Stash mutation is an explicit Prune action that adds or removes
the configured tag. Back up the sidecar before uninstalling; see [Privacy](docs/privacy.md).

## Status

Stash Curator is **Preview / pre-1.0**. Core recommendation, Similar, Expand, Prune,
backup, and packaging flows are implemented; installed-system compatibility and
performance testing continue. The runtime is dependency-free. Development uses
[uv](https://docs.astral.sh/uv/); see [Contributing](docs/contributing.md).

## Project provenance

The idea was inspired by [Restash by Espionage9248](https://github.com/Espionage9248/Restash/tree/main/restash).

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing.

Licensed under [AGPL-3.0](LICENSE).
