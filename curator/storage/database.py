"""Connection, transaction, and backup helpers for SQLite."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self, overload
from uuid import uuid4

from curator.profiling import current_trace, span


class StorageError(RuntimeError):
    """Raised when a storage operation violates a Curator invariant."""


def _sql_details(statement: str) -> tuple[str, dict[str, object]]:
    normalized = " ".join(statement.split())[:1_000]
    command = normalized.partition(" ")[0].upper() or "SQL"
    match = re.search(r"\b(?:FROM|INTO|UPDATE|TABLE)\s+([\w.]+)", normalized, re.IGNORECASE)
    return (f"{command} {match.group(1)}" if match else command, {"statement": normalized})


class ProfiledCursor(sqlite3.Cursor):
    def execute(self, sql: str, parameters: Any = (), /) -> Self:
        name, details = _sql_details(sql)
        with span("sqlite", name, details):
            super().execute(sql, parameters)
        return self

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> Self:
        name, details = _sql_details(sql)
        with span("sqlite", f"{name} many", details):
            super().executemany(sql, seq_of_parameters)
        return self

    def fetchone(self) -> Any:
        with span("sqlite", "fetchone"):
            return super().fetchone()

    def fetchmany(self, size: int | None = None) -> list[Any]:
        with span("sqlite", "fetchmany"):
            return super().fetchmany() if size is None else super().fetchmany(size)

    def fetchall(self) -> list[Any]:
        with span("sqlite", "fetchall"):
            return super().fetchall()


class ProfiledConnection(sqlite3.Connection):
    @overload
    def cursor(self, factory: None = None) -> ProfiledCursor: ...

    @overload
    def cursor[T: sqlite3.Cursor](self, factory: Callable[[sqlite3.Connection], T]) -> T: ...

    def cursor(self, factory: Any = None) -> Any:
        return super().cursor(ProfiledCursor if factory is None else factory)

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> sqlite3.Cursor:
        return self.cursor().executemany(sql, seq_of_parameters)

    def commit(self) -> None:
        with span("sqlite", "COMMIT"):
            super().commit()

    def rollback(self) -> None:
        with span("sqlite", "ROLLBACK"):
            super().rollback()


def connect_database(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Writable databases use WAL mode. Transactions are controlled explicitly rather
    than through sqlite3's legacy implicit transaction behavior.
    """
    path = path.expanduser().resolve()
    if readonly:
        if not path.is_file():
            raise StorageError(f"database does not exist: {path}")
        connection = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=30,
            factory=ProfiledConnection if current_trace() else sqlite3.Connection,
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            path,
            isolation_level=None,
            timeout=30,
            factory=ProfiledConnection if current_trace() else sqlite3.Connection,
        )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if not readonly:
        if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).casefold() != "wal":
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    """Run an explicit transaction and guarantee rollback on failure."""
    if connection.in_transaction:
        raise StorageError("nested transactions are not supported")
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def backup_database(
    source: sqlite3.Connection,
    destination: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Create a consistent backup and publish it atomically."""
    destination = destination.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise StorageError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    target = sqlite3.connect(temporary, isolation_level=None)
    try:
        source.backup(target)
        target.close()
        os.replace(temporary, destination)
    except BaseException:
        target.close()
        temporary.unlink(missing_ok=True)
        raise
    return destination
