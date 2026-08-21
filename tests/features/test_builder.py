import sqlite3
from pathlib import Path

from curator.config import CuratorConfig, FeatureConfig
from curator.features import FeatureBuilder, FeatureStore
from curator.storage import MigrationRunner, connect_database


def _database(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        """
        INSERT INTO source_studio(studio_id, name, source_hash)
        VALUES ('studio-1', 'Studio One', 'studio-hash')
        """
    )
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (
            ("parent", "Scenario", "tag-parent"),
            ("content", "Specific Scenario", "tag-content"),
            ("admin", "[Hide]", "tag-admin"),
            ("aug", "Breast Augmentation", "tag-aug"),
        ),
    )
    connection.execute("INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES ('content', 'parent')")
    connection.executemany(
        """
        INSERT INTO source_performer(
            performer_id, name, favorite, birthdate, ethnicity, eye_color, hair_color,
            height_cm, weight_kg, measurements, augmentation, tattoos, piercings,
            source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                "performer-1",
                "Performer One",
                1,
                "1990-01-01",
                "Example",
                "Blue",
                "Black",
                170,
                55,
                "34DD-24-36",
                "Natural",
                "None",
                "Ears",
                "p1-hash",
            ),
            (
                "performer-2",
                "Performer Two",
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "p2-hash",
            ),
        ),
    )
    connection.executemany(
        """
        INSERT INTO source_scene(
            scene_id, title, scene_date, studio_id, source_hash
        ) VALUES (?, ?, ?, 'studio-1', ?)
        """,
        (
            ("scene-1", "Scene One", "2020-01-01", "scene-1-hash"),
            ("scene-2", "Scene Two", "2021-01-01", "scene-2-hash"),
        ),
    )
    connection.executemany(
        "INSERT INTO source_file(file_id, scene_id, available, source_hash) VALUES (?, ?, 1, ?)",
        (("file-1", "scene-1", "f1"), ("file-2", "scene-2", "f2")),
    )
    connection.executemany(
        "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, 0)",
        (("scene-1", "performer-1"), ("scene-2", "performer-2")),
    )
    connection.executemany(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
        (
            ("scene-1", "content"),
            ("scene-1", "admin"),
            ("scene-2", "parent"),
        ),
    )
    return connection


def test_fingerprint_table_is_deterministic_and_change_sensitive(tmp_path: Path) -> None:
    import hashlib

    from curator.features.builder import _fingerprint_table

    connection = _database(tmp_path / "curator.sqlite3")

    def fingerprint() -> str:
        digest = hashlib.sha256()
        _fingerprint_table(
            connection,
            digest,
            "source_tag",
            "SELECT tag_id, name FROM source_tag ORDER BY tag_id",
        )
        return digest.hexdigest()

    first = fingerprint()
    assert fingerprint() == first
    connection.execute("UPDATE source_tag SET name='Changed' WHERE tag_id='parent'")
    assert fingerprint() != first


def test_feature_build_is_deterministic_versioned_and_explainable(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    progress: list[tuple[int, int]] = []
    builder = FeatureBuilder(
        connection,
        CuratorConfig(),
        clock_ms=lambda: 100,
        progress=lambda processed, total: progress.append((processed, total)),
    )

    first = builder.build()
    first_progress = tuple(progress)
    progress.clear()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    second = builder.build()
    connection.set_trace_callback(None)

    assert second.feature_version == first.feature_version
    assert second.reused is True
    assert {50, 100, 450, 600, 750, 850, 930, 980, 1_000} <= {
        processed for processed, total in first_progress if total == 1_000
    }
    assert [processed for processed, _ in first_progress] == sorted(
        processed for processed, _ in first_progress
    )
    assert progress[-1] == (1_000, 1_000)
    assert not any("FROM entity_feature" in statement for statement in statements)
    assert set(first.stage_timings_ms) == {
        "lookup",
        "build",
        "database_writing",
        "indexing",
        "validation",
        "publication",
        "total",
    }
    assert set(second.stage_timings_ms) == {"lookup", "total"}
    admin_role = connection.execute(
        "SELECT role, resolution_reason FROM tag_role WHERE tag_id='admin'"
    ).fetchone()
    assert tuple(admin_role) == (
        "workflow_administrative",
        "bracketed_automation_default",
    )
    vectors = FeatureStore(connection).scene_content_vectors(first.feature_version)
    assert "tag:content" in vectors["scene-1"]
    assert "tag:parent" in vectors["scene-1"]
    assert "tag:admin" not in vectors["scene-1"]
    statements = []
    connection.set_trace_callback(statements.append)
    assert (
        FeatureStore(connection).scene_content_overlaps(first.feature_version, "scene-1")["scene-2"]
        > 0
    )
    connection.set_trace_callback(None)
    overlap_query = next(statement for statement in statements if "WITH target AS" in statement)
    plan = connection.execute(f"EXPLAIN QUERY PLAN {overlap_query}")
    assert any("feature_id=?" in row["detail"] for row in plan)
    scene_features = FeatureStore(connection).entity_features(first.feature_version, "scene")
    families = {feature.family for feature in scene_features["scene-1"]}
    assert {"content", "performer_identity", "studio"} <= families

    statements = []
    connection.set_trace_callback(statements.append)
    profiles = FeatureStore(connection).performer_profiles(first.feature_version)
    connection.set_trace_callback(None)
    profile_query = next(
        statement for statement in statements if "fd.family LIKE 'profile:%'" in statement
    )
    plan = connection.execute(f"EXPLAIN QUERY PLAN {profile_query}")
    assert not any("USE TEMP B-TREE" in row["detail"] for row in plan)
    assert {"content", "measurements", "height", "age", "augmentation", "eyes"} <= set(
        profiles["performer-1"].blocks
    )
    assert profiles["performer-2"].blocks.get("measurements") is None


def test_ignored_tags_exclude_scene_tags_from_features(tmp_path: Path) -> None:
    """Issue #190: a tag whose exact name is in FeatureConfig.ignored_tags is
    dropped before feature construction, so it produces no entity_feature rows
    and no content vector entry. Exact-name match only — a bracketed tag not
    in the list still resolves via the existing role rules."""
    connection = _database(tmp_path / "curator.sqlite3")
    config = CuratorConfig(feature=FeatureConfig(ignored_tags=("Specific Scenario",)))
    builder = FeatureBuilder(
        connection,
        config,
        clock_ms=lambda: 100,
        progress=lambda processed, total: None,
    )
    result = builder.build()
    vectors = FeatureStore(connection).scene_content_vectors(result.feature_version)
    # scene-1 carries tag 'content' (name "Specific Scenario") and 'admin'
    # (bracketed, so never content anyway). With 'content' ignored, scene-1 has
    # no content tags; its parent "Scenario" only appears where a scene tags it
    # directly (scene-2).
    assert "tag:content" not in vectors.get("scene-1", {})
    assert "tag:parent" not in vectors.get("scene-1", {})
    assert "tag:parent" in vectors["scene-2"]
    # The ignored tag must not have produced any entity_feature rows.
    scene_features = FeatureStore(connection).entity_features(result.feature_version, "scene")
    for features in scene_features.values():
        for feature in features:
            if feature.family == "content":
                assert feature.metadata.get("tag_id") != "content"


def test_ignored_tags_match_exact_name_only(tmp_path: Path) -> None:
    """A partial / substring name does not match: only an exact name in the
    list excludes the tag."""
    connection = _database(tmp_path / "curator.sqlite3")
    config = CuratorConfig(feature=FeatureConfig(ignored_tags=("Scenario",)))
    builder = FeatureBuilder(connection, config, clock_ms=lambda: 100)
    result = builder.build()
    vectors = FeatureStore(connection).scene_content_vectors(result.feature_version)
    # "Scenario" is the parent tag's name, not the 'content' tag's name
    # ("Specific Scenario"), so 'content' is still a content feature on scene-1.
    assert "tag:content" in vectors["scene-1"]


def test_only_feature_source_changes_publish_new_version(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = FeatureBuilder(connection, clock_ms=lambda: 100)
    first = builder.build()
    connection.execute("UPDATE source_scene SET source_hash='changed' WHERE scene_id='scene-1'")

    second = builder.build()
    connection.execute("UPDATE source_scene SET scene_date='2025-01-01' WHERE scene_id='scene-1'")
    third = builder.build()

    assert second.feature_version == first.feature_version
    assert second.reused is True
    assert third.feature_version != first.feature_version
    statuses = {
        row["feature_version"]: row["status"]
        for row in connection.execute("SELECT feature_version, status FROM feature_build")
    }
    assert statuses[first.feature_version] == "superseded"
    assert statuses[third.feature_version] == "published"
    indexed_versions = {
        str(row[0])
        for row in connection.execute("SELECT feature_version FROM scene_content_search")
    }
    assert indexed_versions == {third.feature_version}
