import sqlite3
from pathlib import Path

import pytest

from curator.storage import StorageError, backup_database, connect_database, transaction


def test_connection_enables_required_pragmas(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_transaction_rolls_back_on_failure(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    connection.execute("CREATE TABLE example(value TEXT NOT NULL) STRICT")
    try:
        with pytest.raises(RuntimeError, match="stop"), transaction(connection):
            connection.execute("INSERT INTO example(value) VALUES ('uncommitted')")
            raise RuntimeError("stop")
        assert connection.execute("SELECT count(*) FROM example").fetchone()[0] == 0
    finally:
        connection.close()


def test_nested_transaction_is_rejected(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(StorageError, match="nested"), transaction(connection):
            pass
    finally:
        connection.rollback()
        connection.close()


def test_backup_is_consistent_and_does_not_overwrite(tmp_path: Path) -> None:
    database = tmp_path / "curator.sqlite3"
    backup = tmp_path / "backups" / "curator.sqlite3"
    connection = connect_database(database)
    connection.execute("CREATE TABLE example(value TEXT NOT NULL) STRICT")
    connection.execute("INSERT INTO example(value) VALUES ('persisted')")
    try:
        assert backup_database(connection, backup) == backup.resolve()
        with pytest.raises(StorageError, match="already exists"):
            backup_database(connection, backup)
    finally:
        connection.close()

    restored = sqlite3.connect(backup)
    try:
        assert restored.execute("SELECT value FROM example").fetchone()[0] == "persisted"
    finally:
        restored.close()
