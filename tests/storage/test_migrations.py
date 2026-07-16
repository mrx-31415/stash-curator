from pathlib import Path

import pytest

from curator.storage import MigrationError, MigrationRunner, connect_database


def test_migrate_empty_database_and_rerun_current_version(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        runner = MigrationRunner(connection)
        before = runner.status()
        assert before.current_version == 0
        assert before.pending_versions == (1, 2, 3, 4)

        after = runner.migrate(applied_at_ms=1234)
        assert after.current_version == 4
        assert after.pending_versions == ()
        assert runner.migrate(applied_at_ms=5678) == after

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "source_scene",
            "behavior_event",
            "model_version",
            "sync_run",
            "feature_build",
            "model_scene_score",
            "taxonomy_snapshot",
            "source_tag_stash_id",
        } <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        runner = MigrationRunner(connection)
        runner.migrate(applied_at_ms=1234)
        connection.execute("UPDATE schema_migration SET checksum = 'changed' WHERE version = 1")
        with pytest.raises(MigrationError, match="checksum"):
            runner.status()
    finally:
        connection.close()


def test_unknown_future_migration_is_rejected(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        runner = MigrationRunner(connection)
        runner.migrate(applied_at_ms=1234)
        connection.execute(
            """
            INSERT INTO schema_migration(version, name, checksum, applied_at_ms)
            VALUES (99, 'future', 'unknown', 1234)
            """
        )
        with pytest.raises(MigrationError, match="unknown migration"):
            runner.status()
    finally:
        connection.close()
