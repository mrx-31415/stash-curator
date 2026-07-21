"""Ordered, checksummed SQLite migrations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from importlib import resources

from curator.storage.database import transaction

MIGRATION_PACKAGE = "curator.storage.sql"


class MigrationError(RuntimeError):
    """Raised when migration history is incompatible or corrupt."""


@dataclass(frozen=True)
class Migration:
    """One immutable packaged migration."""

    version: int
    name: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationStatus:
    """Current and available migration state."""

    current_version: int
    latest_version: int
    applied_versions: tuple[int, ...]
    pending_versions: tuple[int, ...]


def _load_migrations() -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    root = resources.files(MIGRATION_PACKAGE)
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name.startswith("_") or not entry.name.endswith(".sql"):
            continue
        prefix, separator, name = entry.name.partition("_")
        if not separator or not prefix.isdigit():
            raise MigrationError(f"invalid migration filename: {entry.name}")
        sql = entry.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(prefix),
                name=name.removesuffix(".sql"),
                sql=sql,
                checksum=hashlib.sha256(sql.encode()).hexdigest(),
            )
        )

    versions = [migration.version for migration in migrations]
    if not migrations or versions != list(range(1, len(migrations) + 1)):
        raise MigrationError(f"migration versions must be contiguous from 1: {versions}")
    return tuple(migrations)


def _statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")
    return tuple(statements)


class MigrationRunner:
    """Inspect and apply the packaged migration chain."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.migrations = _load_migrations()

    def _ensure_history(self) -> None:
        if self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        ).fetchone():
            return
        with transaction(self.connection):
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at_ms INTEGER NOT NULL
                ) STRICT
                """
            )

    def _applied(self) -> dict[int, sqlite3.Row]:
        self._ensure_history()
        rows = self.connection.execute(
            "SELECT version, name, checksum, applied_at_ms FROM schema_migration ORDER BY version"
        )
        return {int(row["version"]): row for row in rows}

    def status(self) -> MigrationStatus:
        """Validate migration history and return current status."""
        applied = self._applied()
        known = {migration.version: migration for migration in self.migrations}
        unknown = sorted(set(applied) - set(known))
        if unknown:
            raise MigrationError(f"database contains unknown migration versions: {unknown}")

        for version, row in applied.items():
            expected = known[version]
            if row["name"] != expected.name or row["checksum"] != expected.checksum:
                raise MigrationError(f"migration {version} does not match the packaged checksum")

        applied_versions = tuple(sorted(applied))
        pending = tuple(
            migration.version for migration in self.migrations if migration.version not in applied
        )
        return MigrationStatus(
            current_version=max(applied_versions, default=0),
            latest_version=self.migrations[-1].version,
            applied_versions=applied_versions,
            pending_versions=pending,
        )

    def migrate(self, *, applied_at_ms: int) -> MigrationStatus:
        """Apply every pending migration transactionally."""
        status = self.status()
        pending = set(status.pending_versions)
        for migration in self.migrations:
            if migration.version not in pending:
                continue
            with transaction(self.connection):
                # Another plugin operation may have applied it while this one waited
                # for SQLite's writer lock.
                if self.connection.execute(
                    "SELECT 1 FROM schema_migration WHERE version=?", (migration.version,)
                ).fetchone():
                    continue
                for statement in _statements(migration.sql):
                    self.connection.execute(statement)
                self.connection.execute(
                    """
                    INSERT INTO schema_migration(version, name, checksum, applied_at_ms)
                    VALUES (?, ?, ?, ?)
                    """,
                    (migration.version, migration.name, migration.checksum, applied_at_ms),
                )
        return self.status()
