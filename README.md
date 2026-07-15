# Stash Curator

**Navigate your library, guided by your taste.**

Stash Curator is a planned recommendation and discovery plugin for
[Stash](https://github.com/stashapp/stash). It learns from viewing behavior and
explicit feedback to offer reliable choices, timely revisits, nearby discoveries,
and deliberate adventures without letting the feed become repetitive.

The project is in its foundation and validation phase. The read-only sidecar cache
can synchronize Stash metadata and normalize historical behavior into conservative
training evidence, but Curator does not yet build recommendations or provide an
installable Stash plugin.

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

## Privacy

Do not commit library exports, GraphQL responses, SQLite databases, local reports,
real entity IDs, credentials, or personal evaluation notes. See the privacy boundary
in the [design](docs/design.md#appendix-repository-privacy-boundary).

## License

Stash Curator is licensed under the [GNU Affero General Public License v3.0](LICENSE).
