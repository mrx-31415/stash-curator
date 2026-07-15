import sqlite3
from pathlib import Path

from curator.config import CuratorConfig
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


def test_feature_build_is_deterministic_versioned_and_explainable(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = FeatureBuilder(connection, CuratorConfig(), clock_ms=lambda: 100)

    first = builder.build()
    second = builder.build()

    assert second.feature_version == first.feature_version
    assert second.reused is True
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
    scene_features = FeatureStore(connection).entity_features(first.feature_version, "scene")
    families = {feature.family for feature in scene_features["scene-1"]}
    assert {"content", "performer_identity", "studio"} <= families

    profiles = FeatureStore(connection).performer_profiles(first.feature_version)
    assert {"content", "proportions", "age", "augmentation", "eyes"} <= set(
        profiles["performer-1"].blocks
    )
    assert profiles["performer-2"].blocks.get("proportions") is None


def test_source_change_publishes_new_version_and_supersedes_old(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    builder = FeatureBuilder(connection, clock_ms=lambda: 100)
    first = builder.build()
    connection.execute("UPDATE source_scene SET source_hash='changed' WHERE scene_id='scene-1'")

    second = builder.build()

    assert second.feature_version != first.feature_version
    statuses = {
        row["feature_version"]: row["status"]
        for row in connection.execute("SELECT feature_version, status FROM feature_build")
    }
    assert statuses[first.feature_version] == "superseded"
    assert statuses[second.feature_version] == "published"
