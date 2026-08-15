from pathlib import Path

import pytest

from curator.storage import MigrationError, MigrationRunner, connect_database


def test_migrate_empty_database_and_rerun_current_version(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    try:
        runner = MigrationRunner(connection)
        before = runner.status()
        assert before.current_version == 0
        assert before.pending_versions == (
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
        )

        after = runner.migrate(applied_at_ms=1234)
        assert after.current_version == 30
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
            "model_update_state",
            "curator_config",
            "curator_job",
            "model_lane_candidate_cache",
            "model_lane_order",
            "model_lane_order_state",
            "direct_tag_preference",
            "direct_tag_preference_history",
        } <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='model_scene_score_prune_idx'"
        ).fetchone()
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='model_lane_order_scene_idx'"
        ).fetchone()
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


def test_feature_count_migration_backfills_existing_builds(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    runner = MigrationRunner(connection)
    original = runner.migrations
    runner.migrations = [migration for migration in original if migration.version < 18]
    runner.migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms
        ) VALUES ('fv-old', 'published', '{}', 'source', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO feature_definition(
            feature_id, feature_version, family, name, provenance
        ) VALUES ('f1', 'fv-old', 'content', 'tag:one', 'test')
        """
    )
    connection.execute(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES ('fv-old', 'scene', 's1', 'f1', 1, 1)
        """
    )

    runner.migrations = original
    runner.migrate(applied_at_ms=2)

    assert tuple(
        connection.execute(
            """
            SELECT scene_count, performer_count, feature_count FROM feature_build
            WHERE feature_version='fv-old'
            """
        ).fetchone()
    ) == (1, 0, 1)


def test_unobserved_penalty_migration_keeps_graded_evidence(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    runner = MigrationRunner(connection)
    original = runner.migrations
    runner.migrations = [migration for migration in original if migration.version < 20]
    runner.migrate(applied_at_ms=1)
    sessions = (
        ("empty", "opened", 0.0, '{"played_ranges":[],"maximum_position_seconds":0.0}'),
        ("watched", "played", 120.0, '{"played_ranges":[],"maximum_position_seconds":120.0}'),
    )
    for _, scene_id, _, _ in sessions:
        connection.execute(
            "INSERT INTO source_scene(scene_id, source_hash) VALUES (?, 'hash')", (scene_id,)
        )
    for session_id, scene_id, active_seconds, summary in sessions:
        connection.execute(
            """
            INSERT INTO play_session(
                session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
                provenance, confidence, summary_json
            ) VALUES (?, ?, 0, 1000, ?, 'direct_player', 1, ?)
            """,
            (session_id, scene_id, active_seconds, summary),
        )
        connection.execute(
            """
            INSERT INTO behavior_event(
                event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
                provenance, session_id
            ) VALUES (?, 'occasion_outcome', ?, 1000, -0.1, 0.8, 'direct_player', ?)
            """,
            (f"{session_id}:view", scene_id, session_id),
        )

    runner.migrations = original
    runner.migrate(applied_at_ms=2)

    assert [
        str(row[0])
        for row in connection.execute("SELECT scene_id FROM behavior_event ORDER BY scene_id")
    ] == ["played"]


def test_purge_orphaned_playback_telemetry_migration_drops_deleted_scenes(
    tmp_path: Path,
) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    runner = MigrationRunner(connection)
    original = runner.migrations
    runner.migrations = [migration for migration in original if migration.version < 22]
    runner.migrate(applied_at_ms=1)
    connection.execute("INSERT INTO source_scene(scene_id, source_hash) VALUES ('kept', 'hash')")
    for scene_id in ("kept", "gone"):
        connection.execute(
            """
            INSERT INTO play_session(session_id, scene_id, started_at_ms, provenance, confidence)
            VALUES (?, ?, 0, 'direct_player', 1)
            """,
            (f"session-{scene_id}", scene_id),
        )
        connection.execute(
            """
            INSERT INTO behavior_event(event_id, event_type, scene_id, occurred_at_ms, confidence,
                provenance)
            VALUES (?, 'play_started', ?, 0, 1, 'direct_player')
            """,
            (f"event-{scene_id}", scene_id),
        )

    runner.migrations = original
    runner.migrate(applied_at_ms=2)

    assert [str(row[0]) for row in connection.execute("SELECT scene_id FROM play_session")] == [
        "kept"
    ]
    assert [str(row[0]) for row in connection.execute("SELECT scene_id FROM behavior_event")] == [
        "kept"
    ]


def test_playback_telemetry_cascades_when_a_scene_is_deleted(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.executemany(
        "INSERT INTO source_scene(scene_id, source_hash) VALUES (?, 'hash')",
        (("kept",), ("gone",)),
    )
    for scene_id in ("kept", "gone"):
        connection.execute(
            """
            INSERT INTO play_session(session_id, scene_id, started_at_ms, provenance, confidence)
            VALUES (?, ?, 0, 'direct_player', 1)
            """,
            (f"session-{scene_id}", scene_id),
        )
        # A behavior_event referencing its session but not carrying scene_id itself must
        # still be caught by the cascade through play_session, not just the direct one.
        connection.execute(
            """
            INSERT INTO behavior_event(event_id, event_type, scene_id, occurred_at_ms,
                confidence, provenance, session_id)
            VALUES (?, 'play_started', ?, 0, 1, 'direct_player', ?)
            """,
            (f"event-{scene_id}", scene_id, f"session-{scene_id}"),
        )
        connection.execute(
            """
            INSERT INTO behavior_event(event_id, event_type, scene_id, occurred_at_ms,
                confidence, provenance, session_id)
            VALUES (?, 'occasion_outcome', NULL, 0, 1, 'direct_player', ?)
            """,
            (f"event-{scene_id}-session-only", f"session-{scene_id}"),
        )

    connection.execute("DELETE FROM source_scene WHERE scene_id='gone'")

    assert [str(row[0]) for row in connection.execute("SELECT scene_id FROM play_session")] == [
        "kept"
    ]
    assert sorted(
        str(row[0]) for row in connection.execute("SELECT event_id FROM behavior_event")
    ) == ["event-kept", "event-kept-session-only"]


def test_cascade_migration_survives_attached_generation_temp_views(tmp_path: Path) -> None:
    # A connection with a published model or feature generation attached creates temp views
    # over table names like entity_feature (see attach_active_artifacts). ALTER TABLE RENAME
    # while any such view exists makes SQLite rescan the whole schema and trip a real SQLite
    # bug ("views may not be indexed") on the shadowed name — unrelated to what is actually
    # being renamed. This reproduces that shadowing directly, without needing a real attached
    # artifact file, to prove migration 23 does not depend on RENAME at all.
    connection = connect_database(tmp_path / "curator.sqlite3")
    runner = MigrationRunner(connection)
    original = runner.migrations
    runner.migrations = [migration for migration in original if migration.version < 23]
    runner.migrate(applied_at_ms=1)
    connection.execute("INSERT INTO source_scene(scene_id, source_hash) VALUES ('s1', 'h')")
    connection.execute(
        "INSERT INTO play_session(session_id, scene_id, started_at_ms, provenance, confidence) "
        "VALUES ('sess1', 's1', 0, 'direct_player', 1)"
    )
    connection.execute(
        """
        INSERT INTO behavior_event(event_id, event_type, scene_id, occurred_at_ms, confidence,
            provenance, session_id)
        VALUES ('e1', 'play_started', 's1', 0, 1, 'direct_player', 'sess1')
        """
    )
    for name in (
        "feature_definition",
        "entity_feature",
        "scene_content_search",
        "model_scene_score",
        "model_scene_reason",
        "feature_affinity",
        "direct_scene_state",
    ):
        connection.execute(f"CREATE TEMP VIEW {name} AS SELECT 1")

    runner.migrations = original
    runner.migrate(applied_at_ms=2)

    ps_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='play_session'"
    ).fetchone()[0]
    be_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='behavior_event'"
    ).fetchone()[0]
    assert "ON DELETE CASCADE" in ps_schema
    assert be_schema.count("ON DELETE CASCADE") == 2
    assert connection.execute("SELECT count(*) FROM play_session").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM behavior_event").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


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


def test_status_stays_read_only_after_migrations(tmp_path: Path) -> None:
    database = tmp_path / "curator.sqlite3"
    writer = connect_database(database)
    MigrationRunner(writer).migrate(applied_at_ms=1234)
    reader = connect_database(database)
    reader.execute("PRAGMA busy_timeout=1")
    try:
        writer.execute("BEGIN IMMEDIATE")
        assert MigrationRunner(reader).status().current_version == 30
    finally:
        writer.rollback()
        reader.close()
        writer.close()


def test_stale_concurrent_migrator_rechecks_after_writer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "curator.sqlite3"
    first = connect_database(database)
    second = connect_database(database)
    second_runner = MigrationRunner(second)
    stale = second_runner.status()
    MigrationRunner(first).migrate(applied_at_ms=1)
    current_status = second_runner.status
    calls = 0

    def status():
        nonlocal calls
        calls += 1
        return stale if calls == 1 else current_status()

    monkeypatch.setattr(second_runner, "status", status)
    try:
        assert second_runner.migrate(applied_at_ms=2).current_version == 30
    finally:
        second.close()
        first.close()
