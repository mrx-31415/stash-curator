# Stash Curator

**Navigate your library, guided by your taste.**

Stash Curator is a recommendation and discovery engine intended to become a
[Stash](https://github.com/stashapp/stash) plugin. It learns from viewing behavior and
explicit feedback to offer reliable choices, timely revisits, nearby discoveries,
and deliberate adventures without letting the feed become repetitive.

The read-only validation slice is implemented. It can synchronize Stash metadata,
normalize historical behavior, build a deterministic recommendation model, generate
all five lanes with inspectable reasons, compare performers, and export a
self-contained HTML evaluation report. The Stash-native page and event collection
are later work packages; no installable plugin is provided yet.

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
for sharing, and use `explain --scene-id <id> --json` or
`similar-performers --performer-id <id> --json` for focused inspection.

## Privacy

Do not commit library exports, GraphQL responses, SQLite databases, local reports,
real entity IDs, credentials, or personal evaluation notes. See the privacy boundary
in the [design](docs/design.md#appendix-repository-privacy-boundary).

## License

Stash Curator is licensed under the [GNU Affero General Public License v3.0](LICENSE).
