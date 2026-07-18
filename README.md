# Stash Curator

**Navigate your library, guided by your taste.**

Stash Curator is a recommendation and discovery engine intended to become a
[Stash](https://github.com/stashapp/stash) plugin. It learns from viewing behavior and
explicit feedback to offer reliable choices, timely revisits, nearby discoveries,
and deliberate adventures without letting the feed become repetitive.

The read-only validation slice is implemented. It can synchronize Stash metadata,
normalize historical behavior, build a deterministic recommendation model, generate
all five lanes with inspectable reasons, compare performers, and export a
self-contained HTML evaluation report. It can also cache StashDB's public tag
taxonomy so physical-description tags do not masquerade as scene-content matches.
The Stash-native page and event collection are later work packages; no installable
plugin is provided yet.

## Documentation

- [Product and recommendation design](docs/design.md)
- [Implementation plan](docs/implementation.md)

The design defines user promises and model semantics. The implementation plan defines
component boundaries, delivery gates, work packages, tests, and acceptance criteria.

## Development

Requirements:

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

Set up and verify the project:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy curator tests
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
  --stash-url http://localhost:9999 --output reports/stashdb-poc.html
```

This disposable report expands a bounded candidate pool from strongly enjoyed linked
scenes, then compares feature-affinity and latent rankings. It sends queries only,
keeps external metadata in memory, and does not modify the sidecar schema.

## Privacy

Do not commit library exports, GraphQL responses, SQLite databases, local reports,
real entity IDs, credentials, or personal evaluation notes. See the privacy boundary
in the [design](docs/design.md#appendix-repository-privacy-boundary).

## License

Stash Curator is licensed under the [GNU Affero General Public License v3.0](LICENSE).
