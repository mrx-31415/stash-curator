"""Connection, transaction, and backup helpers for SQLite."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class StorageError(RuntimeError):
    """Raised when a storage operation violates a Curator invariant."""


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
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, isolation_level=None, timeout=30)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if not readonly:
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
