---
title: Contributing
permalink: /contributing/
---

# Contributing

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing. Contributions—human-written or agent-assisted—must still be
understood, reviewed, and verified by a person responsible for the change.

## Set up and verify

Requirements are Python 3.12+, [uv](https://docs.astral.sh/uv/), and Go for full
verification or packaging.

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
| `core/` | Production Go core: Stash integration, SQLite, model, discovery, and tasks |
| `curator/`, `backend.py` | Development and differential-test oracle; not production runtime |
| `curator/explanations/realizations.json` | Explanation catalog included with the plugin |
| `plugin/` | Launcher, manifest, and browser UI |
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

The plugin archive contains the plugin UI and launcher, explanation realization catalog,
per-platform Go binaries, manifest, and license—not the full Python `curator` package
or `plugin/backend.py`. Documentation is
built independently from `docs/` with GitHub Pages' native Jekyll action, then the
archive and index are copied into the same deployment so docs and install source go
live atomically.

See the retained [backend runtime decision](https://github.com/mrx-31415/stash-curator/blob/main/docs/decisions/001-backend-runtime.md)
for the deployment rationale.

## Releases

Releases are automated with [release-please](https://github.com/googleapis/release-please)
and Conventional Commits. The one thing to keep consistent is **commit subjects**:
prefix them with a conventional type (`feat:`, `fix:`, `docs:`, `perf:`, `chore:`, ...)
and merge with squash so the PR title becomes the commit subject. A workflow checks
every PR title, and a local `.githooks/commit-msg` hook checks commits before they
are made (the same hook directory as the pre-push verifier; enable it with
`git config core.hooksPath .githooks`). Use `--no-verify` only when a subject is
truly exempt.

On every push to `main`, release-please compares the merged commits against the last
release, opens a `chore(main): release vX.Y.Z` pull request that bumps
`pyproject.toml` and `curator/__init__.py`, and regenerates `CHANGELOG.md`. Merging
that pull request creates the version tag and the GitHub Release; a follow-up job
builds the plugin archive and attaches `dist/stash-curator.zip` and `dist/index.yml`
to the release. GitHub Pages already rebuilds on every push to `main`, so the new
version becomes the update available in Stash's plugin manager the moment the
release pull request lands.

The version is defined once in `pyproject.toml` (`[project] version`) and again in
`curator/__init__.py`; release-please updates both together. Everything else derives
from `pyproject.toml`: `scripts/build_plugin.py` reads it at build time and injects
the value into the staged `plugin/stash-curator.yml` and the generated `index.yml`.
Never edit those three outputs by hand. `feat:` bumps minor, `fix:`/`docs:` and the
other types bump patch, and a `BREAKING CHANGE:` footer bumps major.
