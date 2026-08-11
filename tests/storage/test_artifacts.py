import sqlite3
from pathlib import Path

import pytest

from curator.features import FeatureBuilder, FeatureStore
from curator.storage import MigrationRunner, StorageError, connect_database, prune_snapshots
from curator.storage.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    artifact_path,
    cache_directory,
    create_artifact,
    publish_file,
    validate_artifact,
)


def _database(path: Path):
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    return connection


def test_artifact_connection_uses_build_sized_cache_and_mmap(tmp_path: Path) -> None:
    core = _database(tmp_path / "curator.sqlite3")
    artifact, temporary, _ = create_artifact(core, "feature", "fv-" + "a" * 20)
    try:
        assert artifact.execute("PRAGMA cache_size").fetchone()[0] == -262144
        assert artifact.execute("PRAGMA mmap_size").fetchone()[0] == 1073741824
    finally:
        artifact.close()
        temporary.unlink(missing_ok=True)


def test_artifact_paths_reject_escape_and_symlinks(tmp_path: Path) -> None:
    core = tmp_path / "curator.sqlite3"
    for basename in ("/tmp/feature-fv-" + "a" * 20 + ".sqlite3", "../model-" + "a" * 20):
        with pytest.raises(StorageError, match="invalid artifact basename"):
            artifact_path(core, basename)

    directory = cache_directory(core)
    directory.mkdir()
    linked = directory / f"model-{'a' * 20}.sqlite3"
    linked.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StorageError, match="unsafe artifact path"):
        artifact_path(core, linked.name)


def test_rebuildable_artifact_validation_can_skip_full_file_scan() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(f"PRAGMA user_version={ARTIFACT_SCHEMA_VERSION}")
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    result = validate_artifact(connection, "model", {"scenes": 2}, check_integrity=False)

    assert result == {
        "integrity": "skipped",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "counts": {"scenes": 2},
    }
    assert "PRAGMA quick_check" not in statements


def test_reader_keeps_attached_feature_generation_across_publication(
    tmp_path: Path,
) -> None:
    database = tmp_path / "curator.sqlite3"
    writer = _database(database)
    first = FeatureBuilder(writer, clock_ms=lambda: 1).build()
    reader = connect_database(database)

    writer.execute("INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('tag', 'Tag', 'tag')")
    writer.execute(
        """
        INSERT INTO source_scene(scene_id, title, source_hash)
        VALUES ('scene', 'Scene', 'scene')
        """
    )
    writer.execute(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES ('scene', 'tag', 'scene')"
    )
    second = FeatureBuilder(writer, clock_ms=lambda: 2).build()
    fresh = connect_database(database)
    try:
        assert first.feature_version != second.feature_version
        assert FeatureStore(reader).current_version() == first.feature_version
        assert FeatureStore(fresh).current_version() == second.feature_version
    finally:
        fresh.close()
        reader.close()
        writer.close()


def test_schema_two_capable_reader_keeps_schema_one_artifacts_read_only(tmp_path: Path) -> None:
    database = tmp_path / "curator.sqlite3"
    writer = _database(database)
    built = FeatureBuilder(writer, clock_ms=lambda: 1).build()
    artifact = artifact_path(database, f"feature-{built.feature_version}.sqlite3")
    writer.close()

    connection = connect_database(database)
    try:
        assert FeatureStore(connection).current_version() == built.feature_version
        with pytest.raises(sqlite3.OperationalError, match="view"):
            connection.execute("DELETE FROM entity_feature")
    finally:
        connection.close()

    raw = sqlite3.connect(artifact)
    raw.execute("PRAGMA user_version=2")
    raw.execute("UPDATE artifact_meta SET schema_version=2")
    raw.close()
    connection = connect_database(database)
    try:
        assert FeatureStore(connection).current_version() == built.feature_version
    finally:
        connection.close()


def test_failed_artifact_unlink_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "curator.sqlite3"
    connection = _database(database)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms
        ) VALUES ('feature', 'published', '{}', 'source', 1)
        """
    )
    models = (
        ("model-" + "1" * 20, "superseded", 1),
        ("model-" + "2" * 20, "superseded", 2),
        ("model-" + "3" * 20, "published", 3),
    )
    connection.executemany(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms,
            published_at_ms, artifact_basename, validation_status
        ) VALUES (?, ?, 'feature', '{}', ?, ?, ?, 'valid')
        """,
        (
            (model_id, status, created, created, f"{model_id}.sqlite3")
            for model_id, status, created in models
        ),
    )
    target = artifact_path(database, f"{models[0][0]}.sqlite3")
    target.parent.mkdir()
    target.touch()
    original_unlink = Path.unlink
    attempts = 0

    def flaky_unlink(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal attempts
        if path == target and attempts == 0:
            attempts += 1
            raise OSError("busy")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    assert prune_snapshots(connection).deleted_models == 0
    assert connection.execute(
        "SELECT cleanup_error FROM model_version WHERE model_id=?", (models[0][0],)
    ).fetchone()[0]

    assert prune_snapshots(connection).deleted_models == 1
    row = connection.execute(
        """
        SELECT artifact_basename, validation_status, cleanup_error
        FROM model_version WHERE model_id=?
        """,
        (models[0][0],),
    ).fetchone()
    assert tuple(row) == (None, "retired", None)


def test_attach_skips_tables_missing_from_older_artifact(tmp_path: Path) -> None:
    """Attaching an artifact built by older code must not shadow new table names.

    SQLite validates CREATE TEMP VIEW lazily, so a model artifact that predates a
    newly added MODEL_TABLES entry used to produce a temp view over the missing
    name. That view shadowed the core-schema name, so a pending migration's CREATE
    INDEX on it failed with "views may not be indexed". Attach must create views
    only for tables the artifact actually has.
    """
    core = connect_database(tmp_path / "curator.sqlite3")
    runner = MigrationRunner(core)
    original = runner.migrations
    runner.migrations = [migration for migration in original if migration.version < 25]
    runner.migrate(applied_at_ms=1)
    runner.migrations = original

    model_id = "model-" + "a" * 20
    artifact, temporary, final = create_artifact(core, "model", model_id)
    try:
        # Simulate an artifact built by code that predates model_performer_edge.
        artifact.execute("DROP TABLE model_performer_edge")
    finally:
        publish_file(artifact, temporary, final)
    core.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms,
            artifact_basename, validation_status
        ) VALUES (?, 'published', 'fv', '{}', 1, ?, 'valid')
        """,
        (model_id, final.name),
    )

    attached = connect_database(tmp_path / "curator.sqlite3", attach_artifacts=True)
    try:
        views = {
            str(row[0])
            for row in attached.execute("SELECT name FROM sqlite_temp_master WHERE type='view'")
        }
        assert "model_performer_edge" not in views
        # Migration 25 creates and indexes model_performer_edge; the shadowing view
        # used to make its CREATE INDEX fail with "views may not be indexed".
        assert MigrationRunner(attached).migrate(applied_at_ms=2).current_version == 28
    finally:
        attached.close()
