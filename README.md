# Stash Curator

**Navigate your library, guided by your taste.**

Stash Curator is a recommendation and discovery engine for
[Stash](https://github.com/stashapp/stash). It learns from viewing behavior and
explicit feedback to offer reliable choices, timely revisits, nearby discoveries,
and deliberate adventures without letting the feed become repetitive.

The read-only validation slice is implemented. It can synchronize Stash metadata,
normalize historical behavior, build a deterministic recommendation model, generate
all five lanes with inspectable reasons, compare performers, and export a
self-contained HTML evaluation report. It can also cache StashDB's public tag
taxonomy so physical-description tags do not masquerade as scene-content matches.
An installable plugin adds the Stash-native page, feedback, direct player-session
collection, persistent jobs, and configuration on top of the validation tools.

## Documentation

- [Product and recommendation design](docs/design.md)
- [Implementation plan](docs/implementation.md)

The design defines user promises and model semantics. The implementation plan defines
component boundaries, delivery gates, work packages, tests, and acceptance criteria.

## Install in Stash

The initial release targets Stash v0.31 and requires Python 3.12 or newer in the
Stash plugin runtime. Add this source under **Settings → Plugins → Available
Plugins**:

```text
https://mrx-31415.github.io/stash-curator/index.yml
```

Install **Stash Curator**, reload plugins, open the compass button in Stash's
top navigation, and run **Sync library** once. Jobs, configuration, backup, and reset are available from the Curator page;
manual and full-reconciliation tasks are also available on Stash's Tasks page.
Curator never mutates library entities: feedback and events remain in its sidecar.

For a nightly background sync, let the host scheduler invoke Stash's task API; no
browser needs to be open. For example, this crontab entry runs at 03:00:

```cron
0 3 * * * curl -fsS -H 'Content-Type: application/json' --data '{"query":"mutation { runPluginTask(plugin_id: \"stash-curator\", task_name: \"Sync and build recommendations\") }"}' http://127.0.0.1:9999/graphql >/dev/null
```

Change the URL when Stash is not reachable on the host loopback interface, and add
an `ApiKey` header when authentication is enabled.

The sidecar defaults to `{pluginDir}/data/curator.sqlite3`. Configure **Sidecar
database path** before first use if plugin updates or uninstallation may replace that
directory. Back up before uninstalling. Removing Curator does not alter Stash-owned
scenes, performers, tags, studios, or history.

Build a local package source with:

```bash
uv run python scripts/build_plugin.py
```

This writes `dist/stash-curator.zip` and its checksummed `dist/index.yml`.

## Development

Requirements:

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

Set up and verify the project:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy curator plugin/backend.py
uv run pytest
```

Synchronize a local validation cache:

```bash
export STASH_URL=http://localhost:9999
# export STASH_API_KEY=...  # only when Stash requires one
uv run curator --db data/curator.sqlite3 doctor
uv run curator --db data/curator.sqlite3 sync
uv run curator --db data/curator.sqlite3 sync --full
```

Normal sync is incremental. A full sync traverses stable IDs and reconciles source
deletions. Both modes resume interrupted page traversal. The validation client
accepts GraphQL `query` operations only; it contains no Stash mutations. Repository
tests use synthetic data and do not require access to a real Stash instance.

Optionally cache StashDB's public tag taxonomy before building the model:

```bash
# Either export STASHDB_API_KEY=... or add a stashdb.org entry to ~/.netrc.
uv run curator --db data/curator.sqlite3 sync-taxonomy --json
```

`sync-taxonomy` sends read-only GraphQL queries for public categories and tags. It
does not upload library metadata or behavior. The immutable snapshot is stored in
Curator's sidecar, so subsequent model builds are offline and reproducible. Local
tags resolve by StashDB ID when available, then by a unique canonical name or alias;
ambiguous matches are retained as provenance but are not guessed. The committed
[category-role policy](curator/taxonomy/stashdb_category_roles.json) classifies body
and appearance categories as performer attributes and treats other categories,
including Clothing, as scene content by default.

Build and inspect recommendations after a sync:

```bash
uv run curator --db data/curator.sqlite3 build-model --json
uv run curator --db data/curator.sqlite3 recommend --lane for_you --count 12
uv run curator --db data/curator.sqlite3 recommend --lane best_bets --count 12
uv run curator --db data/curator.sqlite3 recommend --lane revisit --count 12
uv run curator --db data/curator.sqlite3 recommend --lane discover --count 12
uv run curator --db data/curator.sqlite3 recommend --lane adventure --count 12
```

Sync reconstructs historical evidence only for the scenes it receives and marks the
model dirty. A resident plugin can call the update coordinator after its two-second
quiet period; from the CLI, publish pending work with:

```bash
uv run curator --db data/curator.sqlite3 update-model --force --json
```

Recorded actions only require the faster preference rebuild. For direct maintenance,
`build-model --preferences-only` skips historical reconstruction. Model publication
keeps the current and previous snapshots and removes one older snapshot per build.
Preview or accelerate the backlog cleanup with `db gc`; add `--apply` to delete and
optionally `--vacuum` to reclaim file space. Vacuum is never automatic.

Generate the local evaluation report:

```bash
uv run curator --db data/curator.sqlite3 report \
  --output reports/curator-report.html --count 12
```

The report contains model internals and local entity names by default. Keep it in the
ignored `reports/` directory. Add `--redacted` when producing an artifact suitable
for sharing. When `STASH_URL` or `--stash-url` is set, report covers and titles link
to the corresponding scene in Stash; redacted reports omit those private links. The
report includes an image visibility toggle, supporting evidence, and an expandable
score tree from final utility through lane inputs, Appeal, Current Fit, and individual
model families. Use
`explain --scene-id <id> --json` or
`similar-performers --performer-id <id> --json` for focused inspection.

Run the disposable latent-model experiment without changing production scores:

```bash
uv run --group poc python scripts/latent_poc.py \
  --stash-url http://localhost:9999 --output reports/latent-poc.html
```

The default deterministic 6,000-scene sample includes every labelled scene. Pass
`--max-scenes 0` for the full library.

Evaluate recommendations for StashDB scenes and performers that are not in the local
library:

```bash
chmod 600 ~/.netrc  # once, when using netrc instead of STASHDB_API_KEY
uv run --group poc python scripts/stashdb_poc.py \
  --stash-url http://localhost:9999 --output reports/stashdb-poc.html \
  --similar-to "Example Performer"
```

This disposable report expands a bounded candidate pool from strongly enjoyed linked
scenes, then applies Curator's v1 affinities, content neighbors, bounded components,
and coverage-aware performer similarity. It sends queries only, keeps external
metadata in memory, and does not modify the sidecar schema.

## Privacy

Do not commit library exports, GraphQL responses, SQLite databases, local reports,
real entity IDs, credentials, or personal evaluation notes. See the privacy boundary
in the [design](docs/design.md#appendix-repository-privacy-boundary).

## License

Stash Curator is licensed under the [GNU Affero General Public License v3.0](LICENSE).
