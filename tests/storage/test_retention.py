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
