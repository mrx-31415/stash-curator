# Stash Curator

**Navigate your library, guided by your taste.**

Stash Curator is a planned recommendation and discovery plugin for
[Stash](https://github.com/stashapp/stash). It learns from viewing behavior and
explicit feedback to offer reliable choices, timely revisits, nearby discoveries,
and deliberate adventures without letting the feed become repetitive.

The project is in its foundation and validation phase. It does not yet provide an
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

The initial validation client will use read-only Stash GraphQL queries. Repository
tests use synthetic data and must not require access to a real Stash instance.

## Privacy

Do not commit library exports, GraphQL responses, SQLite databases, local reports,
real entity IDs, credentials, or personal evaluation notes. See the privacy boundary
in the [design](docs/design.md#appendix-repository-privacy-boundary).

## License

Stash Curator is licensed under the [GNU Affero General Public License v3.0](LICENSE).
