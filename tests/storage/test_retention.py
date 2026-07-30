from pathlib import Path

from curator.storage import MigrationRunner, connect_database, prune_snapshots


def test_retention_keeps_current_and_previous_snapshots(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.executemany(
        """
        INSERT INTO feature_build(feature_version, status, config_json, source_fingerprint,
                                  created_at_ms, published_at_ms)
        VALUES (?, ?, '{}', ?, ?, ?)
        """,
        (
            ("f1", "superseded", "f1", 1, 1),
            ("f2", "superseded", "f2", 2, 2),
            ("f3", "published", "f3", 3, 3),
        ),
    )
    connection.executemany(
        """
        INSERT INTO model_version(model_id, status, feature_version, config_json,
                                  created_at_ms, published_at_ms)
        VALUES (?, ?, ?, '{}', ?, ?)
        """,
        (
            ("m1", "superseded", "f1", 1, 1),
            ("m2", "superseded", "f2", 2, 2),
            ("m3", "published", "f3", 3, 3),
        ),
    )

    result = prune_snapshots(connection)

    assert result.deleted_models == 1
    assert result.deleted_features == 1
    assert [row[0] for row in connection.execute("SELECT model_id FROM model_version")] == [
        "m2",
        "m3",
    ]


def test_retention_removes_abandoned_build_and_its_features(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms
        ) VALUES ('orphan-feature', 'superseded', '{}', 'orphan', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint,
            created_at_ms, published_at_ms
        ) VALUES ('current-feature', 'published', '{}', 'current', 2, 2)
        """
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms
        ) VALUES ('orphan-model', 'building', 'orphan-feature', '{}', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms, published_at_ms
        ) VALUES ('current-model', 'published', 'current-feature', '{}', 2, 2)
        """
    )

    result = prune_snapshots(connection)

    assert result.deleted_models == 1
    assert result.deleted_features == 1
    assert connection.execute("SELECT count(*) FROM model_version").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM feature_build").fetchone()[0] == 1
