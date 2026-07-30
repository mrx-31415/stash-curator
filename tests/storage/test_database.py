import json
import sqlite3
from pathlib import Path

import pytest

from curator.storage import (
    MigrationRunner,
    StorageError,
    backup_database,
    compact_legacy_generations,
    connect_database,
    transaction,
)
from curator.storage.artifacts import create_artifact, publish_file
from curator.storage.database import _LEGACY_DERIVED_TABLES


def test_connection_enables_required_pragmas(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
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
    derived = database.with_name("curator-derived")
    derived.mkdir()
    (derived / f"model-{'a' * 20}.sqlite3").touch()
    try:
        assert backup_database(connection, backup) == backup.resolve()
        assert not backup.with_name("curator-derived").exists()
        with pytest.raises(StorageError, match="already exists"):
            backup_database(connection, backup)
    finally:
        connection.close()

    restored = sqlite3.connect(backup)
    try:
        assert restored.execute("SELECT value FROM example").fetchone()[0] == "persisted"
    finally:
        restored.close()


def _publish_artifact(connection: sqlite3.Connection, kind: str, identifier: str) -> str:
    artifact, temporary, final = create_artifact(connection, kind, identifier)
    publish_file(artifact, temporary, final)
    return final.name


def test_legacy_compaction_is_validated_batched_restartable_and_preserves_durable_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "curator.sqlite3"
    connection = connect_database(database, attach_artifacts=False)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    feature_id = "fv-" + "a" * 20
    model_ids = ("model-" + "b" * 20, "model-" + "c" * 20)
    retired_model_id = "model-" + "d" * 20
    feature_artifact = _publish_artifact(connection, "feature", feature_id)
    model_artifacts = {
        model_id: _publish_artifact(connection, "model", model_id) for model_id in model_ids
    }
    valid = json.dumps({"integrity": "ok", "schema_version": 1, "counts": {}})
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms,
            published_at_ms, artifact_basename, artifact_schema_version,
            validation_status, validation_summary_json
        ) VALUES (?, 'published', '{}', 'source', 1, 1, ?, 1, 'valid', ?)
        """,
        (feature_id, feature_artifact, valid),
    )
    connection.executemany(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms,
            published_at_ms, artifact_basename, artifact_schema_version,
            validation_status, validation_summary_json
        ) VALUES (?, ?, ?, '{}', 1, 1, ?, 1, 'valid', ?)
        """,
        (
            (model_id, status, feature_id, model_artifacts[model_id], valid)
            for model_id, status in zip(model_ids, ("superseded", "published"), strict=True)
        ),
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms,
            validation_status
        ) VALUES (?, 'superseded', ?, '{}', 1, 'retired')
        """,
        (retired_model_id, feature_id),
    )
    connection.execute(
        """
        INSERT INTO feature_definition(
            feature_id, feature_version, family, name, provenance
        ) VALUES ('feature', ?, 'content', 'tag:test', 'test')
        """,
        (feature_id,),
    )
    connection.execute(
        """
        INSERT INTO feature_affinity(
            model_id, feature_id, affinity, confidence, effective_support,
            distinct_scene_count
        ) VALUES (?, 'feature', 0, 0, 0, 0)
        """,
        (retired_model_id,),
    )
    connection.execute(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES (?, 'scene', 'scene', 'feature', 1, 1)
        """,
        (feature_id,),
    )
    connection.execute(
        """
        INSERT INTO source_scene(scene_id, title, source_hash)
        VALUES ('scene', 'Durable scene', 'scene')
        """
    )
    connection.execute(
        """
        INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms)
        VALUES ('feedback', 'scene', 'thumb_up', 1)
        """
    )
    connection.executemany(
        """
        INSERT INTO model_scene_score(
            model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
            appeal, current_fit, confidence, metadata_confidence, recovery,
            components_json, neighbors_json, eligibility_json
        ) VALUES (?, 'scene', 0, 0, 0, 0, 0, 0, 0, 1, '{}', '[]', '{}')
        """,
        ((model_id,) for model_id in model_ids),
    )
    derived = {table for table, _, _ in _LEGACY_DERIVED_TABLES}
    durable_counts = {
        str(row[0]): int(connection.execute(f"SELECT count(*) FROM {row[0]}").fetchone()[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if str(row[0]) not in derived | {"application_meta"}
    }

    partial = compact_legacy_generations(connection, batch_size=1, max_batches=1)
    assert partial["status"] == "in_progress"
    assert partial["rows_deleted_this_run"] == 1
    complete = compact_legacy_generations(connection, batch_size=1)
    assert complete["status"] == "complete"
    assert complete["rows_deleted"] == 5
    assert complete["rows_remaining"] == 0
    assert connection.execute("SELECT count(*) FROM model_scene_score").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM entity_feature").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM feature_definition").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM feature_affinity").fetchone()[0] == 0
    assert connection.execute("SELECT title FROM source_scene").fetchone()[0] == "Durable scene"
    assert connection.execute("SELECT feedback_type FROM feedback").fetchone()[0] == "thumb_up"
    assert durable_counts == {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in durable_counts
    }
    assert database.is_file()
    connection.close()


def test_legacy_compaction_refuses_missing_active_artifacts(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3", attach_artifacts=False)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    with pytest.raises(StorageError, match="valid active feature artifact"):
        compact_legacy_generations(connection)
    connection.close()
