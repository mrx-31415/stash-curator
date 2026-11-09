---
title: Contributing
permalink: /contributing/
---

# Contributing

Stash Curator is primarily generated with AI coding agents under human direction,
review, and testing. Contributions—human-written or agent-assisted—must still be
understood, reviewed, and verified by a person responsible for the change.

## Set up and verify

Requirements are Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js for browser
code checks, and Go 1.26.5+ for full verification or packaging. Packaging also uses
Zig; the build script downloads its pinned version if it is not already installed.

```bash
uv sync --locked
scripts/verify changed
```

Use `scripts/verify changed tests/path/to/test_file.py` while implementing a focused
change. For a broad native test pass, run `scripts/verify test`: it builds the host
core and runs lint, type checks, Go tests and Python compatibility tests.
It omits cross-platform packaging and the performance benchmark. Run
`scripts/verify perf` for that benchmark. Focused `verify changed` checks run Go
tests when needed and only the Python tests requested; broad differential coverage
runs in `verify core`, `verify test` and `verify full`.

Before release, run the CI-equivalent suite with all five platform builds:

```bash
scripts/verify full
```

Tests use unique directories in system temporary storage; set `TMPDIR` to override
that location. Prefer local storage for SQLite-heavy tests. Non-integration tests run
on four pytest-xdist workers, keeping each file's fixtures together and limiting
numerical libraries to one thread per worker. Set `CURATOR_TEST_WORKERS=0` for
serial debugging, or another worker count for your machine. The full suite reports
its 20 slowest tests. Test-only Go edits and unchanged generated fingerprints do
not invalidate packaged binaries.
macOS linker stubs use a content-addressed cache, so moving between checkouts does
not invalidate SQLite's C compilation when the stubs are unchanged.

Build the plugin source with `uv run --frozen python scripts/build_plugin.py`. It
writes `dist/stash-curator.zip` and a checksummed `dist/index.yml`. Repository tests
use synthetic data and need no live Stash or StashDB access.

### Windows coverage

The Windows workflow runs `go vet` and `go test` for `core/` on `windows-latest`,
then installs a Windows-only package built from the same commit into native Stash
v0.31.1 (`scripts/windows_smoke.py`). The smoke test seeds a synthetic library,
runs Sync and build, calls the status and connection-check operations, and keeps the
Curator page open. It fails on task failures, browser exceptions, Curator errors in
Stash's log, request failures in the daemon log, or more new TCP connections than its
budget. It runs for pull requests that touch `core/`, `plugin/` or packaging, for
pushes to `main`, nightly, and on demand. Its logs and a page screenshot are
uploaded as artifacts.

### Plugin compatibility coverage

`tests/plugin/test_patch_composition.cjs` exercises every registered Stash patch
with rewritten argument counts and both plugin registration orders. It preserves
renderer context, native content, and element, null and array results. Its surface
inventory must be extended when adding a patch.

`tests/integration/test_patch_composition.py` loads a synthetic companion plugin
before Curator in the isolated Stash browser environment. It checks scene and
performer grids and detail pages, card details/popovers/overlays, player and popover
hook execution, retained navbar entries, and JavaScript errors. Run it through
`scripts/verify integration`; it does not require access to a personal library.
Each run starts from a fresh Stash library. Set `STASH_IMAGE` (default
`stashapp/stash:latest`) to check an upcoming release, for example
`STASH_IMAGE=stashapp/stash:development scripts/verify integration`.
The destructive fresh-install reset test runs last, after pytest groups fixture
parameters, so it cannot invalidate later model-dependent pages or background tasks.

## Code map

| Area | Purpose |
| --- | --- |
| `core/` | Production Go core: Stash integration, SQLite, model, discovery, and tasks |
| `curator/`, `plugin/backend.py` | Development and differential-test oracle; not production runtime |
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

Curator and its companion plugins, Auto Seek and Incognito, are released separately,
each with its own version, tag and changelog. A commit belongs to the plugin whose
files it changes: everything under `auto-seek/`, plus Auto Seek's docs pages, assets
and tests, is Auto Seek's. Everything under `incognito/`, plus its tests, is
Incognito's. The rest is Curator's. A commit that changes several counts for each.
Companions are listed in `COMPANIONS` in `scripts/build_plugin.py` and
`scripts/stable_source.py`.

On every push to `main`, release-please compares the merged commits against each
plugin's last release and opens one release pull request per plugin that has
changes:

- **Curator:** bumps `pyproject.toml` and `curator/__init__.py`, regenerates
  `CHANGELOG.md`, and tags `vX.Y.Z`. A follow-up job builds Curator's archives and
  attaches `dist/stash-curator*.zip` and `dist/index*.yml` to the release.
- **Auto Seek:** bumps the `version:` line in `auto-seek/auto-seek.yml`, regenerates
  `auto-seek/CHANGELOG.md`, and tags `auto-seek-vX.Y.Z`. A follow-up job runs
  `scripts/build_plugin.py --only auto-seek` and attaches `dist/auto-seek.zip` and
  `dist/auto-seek-index.yml`.
- **Incognito:** the same, from `incognito/incognito.yml`, tagging
  `incognito-vX.Y.Z` and attaching `dist/incognito.zip` and `dist/incognito-index.yml`.

Each job then dispatches the Pages workflow.

GitHub Pages rebuilds on every push to `main` and serves two plugin sources. The
development source under `/dev/` is built from `main` by
`scripts/build_plugin.py --dev`, versioned `X.Y.Z+dev.N.<sha>` (N commits after
release X.Y.Z; the release commit itself is plain `X.Y.Z`). The regular source is
assembled by `scripts/stable_source.py`: Curator's archives and indexes from its
latest complete release, with each companion's entry swapped for the one from its
latest release (a companion never released yet is left out). Stash offers a plugin
update only when the index `date` is newer, and each entry keeps its own release's date, so
regular-source users see an update only for the plugin that was released. The development source is for maintainers and is
deliberately not in the user guide.

To test what the next release will contain, point an existing installation's plugin
source at `https://mrx-31415.github.io/stash-curator/dev/index.yml`, keeping its
**Local Path**, and update Curator. Edit the source rather than adding a second one: a
second source with another Local Path installs a second copy of the plugin. The
development source also carries every release, so an installation can stay on it.
To return to the regular source, switch it back and reinstall. Going back to a
release older than a development build that added a migration is not supported, so
back up the plugin folder first.

The version is defined once in `pyproject.toml` (`[project] version`) and again in
`curator/__init__.py`; release-please updates both together. Everything else derives
from `pyproject.toml`: `scripts/build_plugin.py` reads it at build time and injects
the value into the staged `plugin/stash-curator.yml` and the generated `index.yml`.
Never edit those three outputs by hand. `feat:` bumps minor, `fix:`/`docs:` and the
other types bump patch, and a `BREAKING CHANGE:` footer bumps major.
