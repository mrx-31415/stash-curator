import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from curator.storage import MigrationRunner, ModelStore, StorageError, connect_database


@pytest.fixture
def model_database(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    yield connection
    connection.close()


def test_publish_and_supersede_model_atomically(model_database: sqlite3.Connection) -> None:
    store = ModelStore(model_database)
    first = store.start_build(
        feature_version="features-1",
        config={"seed": 1},
        sync_watermark="sync-1",
        created_at_ms=10,
    )
    assert store.publish(first.model_id, published_at_ms=20).status == "published"

    second = store.start_build(
        feature_version="features-2",
        config={"seed": 2},
        sync_watermark="sync-2",
        created_at_ms=30,
    )
    published = store.publish(second.model_id, published_at_ms=40)

    assert published.status == "published"
    assert store.current() == published
    assert store.get(first.model_id).status == "superseded"
    assert (
        model_database.execute(
            "SELECT value FROM application_meta WHERE key = 'current_model_id'"
        ).fetchone()[0]
        == second.model_id
    )


def test_interrupted_publish_preserves_current_model(model_database: sqlite3.Connection) -> None:
    store = ModelStore(model_database)
    first = store.start_build(
        feature_version="features-1",
        config={},
        sync_watermark=None,
        created_at_ms=10,
    )
    store.publish(first.model_id, published_at_ms=20)
    second = store.start_build(
        feature_version="features-2",
        config={},
        sync_watermark=None,
        created_at_ms=30,
    )
    model_database.execute(
        f"""
        CREATE TRIGGER reject_test_publish
        BEFORE UPDATE ON model_version
        WHEN NEW.model_id = '{second.model_id}' AND NEW.status = 'published'
        BEGIN
            SELECT RAISE(ABORT, 'simulated interruption');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated interruption"):
        store.publish(second.model_id, published_at_ms=40)

    assert store.current() == store.get(first.model_id)
    assert store.get(first.model_id).status == "published"
    assert store.get(second.model_id).status == "building"


def test_only_building_models_can_publish_or_fail(model_database: sqlite3.Connection) -> None:
    store = ModelStore(model_database)
    model = store.start_build(
        feature_version="features-1",
        config={},
        sync_watermark=None,
        created_at_ms=10,
    )
    failed = store.fail(model.model_id)
    assert failed.status == "failed"
    with pytest.raises(StorageError, match="not publishable"):
        store.publish(model.model_id, published_at_ms=20)
