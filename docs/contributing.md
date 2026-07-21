---
title: Contributing
permalink: /contributing/
---

# Contributing

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing. Contributions—human-written or agent-assisted—must still be
understood, reviewed, and verified by a person responsible for the change.

## Set up and verify

Requirements are Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
scripts/verify changed
```

Use `scripts/verify changed tests/path/to/test_file.py` while implementing a focused
change. Before push, run the CI-equivalent suite once:

```bash
scripts/verify full
```

Build the plugin source with `uv run --frozen python scripts/build_plugin.py`. It
writes `dist/stash-curator.zip` and a checksummed `dist/index.yml`. Repository tests
use synthetic data and need no live Stash or StashDB access.

## Code map

| Area | Purpose |
| --- | --- |
| `curator/sync/`, `curator/graphql/` | Stash ingestion |
| `curator/events/` | Outcome normalization and durable events |
| `curator/features/`, `curator/taxonomy/` | Sparse features and tag roles |
| `curator/model/`, `curator/ranking/` | Preference estimates and varied slates |
| `curator/similarity.py`, `curator/expand.py` | Local and external discovery |
| `curator/explanations/` | Structured reasons and deterministic wording |
| `curator/storage/sql/` | Immutable SQLite migrations |
| `plugin/` | Stash backend bridge and browser UI |
| `tests/` | Synthetic unit and integration coverage |

## Privacy rules

Never commit databases, reports, GraphQL payloads, local URLs, credentials, real
entity IDs, library facts, or personal evaluation notes. Live Stash and StashDB
access is read-only unless a user explicitly authorizes testing the reversible Prune
tag mutation. Curator must never delete media.

## Migrations and packaging

SQLite migrations are ordered, immutable, checksummed, and transactional. Add a new
migration; never edit one that may have been applied, reset a sidecar to hide a
migration defect, or expose readers to partially published model state.

The plugin archive contains `plugin/`, `curator/`, and the license. Documentation is
built independently from `docs/` with GitHub Pages' native Jekyll action, then the
archive and index are copied into the same deployment so docs and install source go
live atomically. Historical design and research live in `docs/archive/` and are
excluded from the public build.

See the retained [backend runtime decision](https://github.com/mrx-31415/stash-curator/blob/main/docs/decisions/001-backend-runtime.md)
for the deployment rationale.
