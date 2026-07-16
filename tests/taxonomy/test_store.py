import sqlite3
from pathlib import Path

from curator.storage import MigrationRunner, connect_database
from curator.taxonomy import (
    TaxonomyCategory,
    TaxonomyData,
    TaxonomyIndex,
    TaxonomyStore,
    TaxonomyTag,
)
from curator.taxonomy.store import PERFORMER_ATTRIBUTE_CATEGORY_IDS

BODY_TYPE_ID = "20c82f8a-4f2b-412a-8047-934eeb6c32e7"
GENITALS_ID = "9bd1d55e-d7c4-4b7c-a66f-96ec52b7af08"
CLOTHING_ID = "clothing-category"


def _taxonomy() -> TaxonomyData:
    return TaxonomyData(
        endpoint="https://stashdb.org/graphql",
        categories=(
            TaxonomyCategory(BODY_TYPE_ID, "Body Type", "PEOPLE", None),
            TaxonomyCategory(GENITALS_ID, "Genitals", "PEOPLE", None),
            TaxonomyCategory(CLOTHING_ID, "Clothing", "PEOPLE", None),
        ),
        tags=(
            TaxonomyTag("athletic", "Athletic", ("Athletic Body",), BODY_TYPE_ID),
            TaxonomyTag("trimmed", "Trimmed Pussy", ("Trimmed",), GENITALS_ID),
            TaxonomyTag("clothing", "Stockings", (), CLOTHING_ID),
            TaxonomyTag("shared-a", "Shared A", ("Ambiguous",), CLOTHING_ID),
            TaxonomyTag("shared-b", "Shared B", ("Ambiguous",), CLOTHING_ID),
        ),
    )


def _database(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (
            ("local-id", "Wrong Local Name", "1"),
            ("local-alias", "Athletic Body", "2"),
            ("local-clothing", "Stockings", "3"),
            ("local-trimmed", "Trimmed", "4"),
            ("local-ambiguous", "Ambiguous", "5"),
            ("local-unmapped", "Bubble Butt", "6"),
        ),
    )
    connection.execute(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        ("local-id", "https://stashdb.org/graphql", "athletic"),
    )
    return connection


def test_snapshot_is_immutable_reusable_and_resolves_by_id_then_unique_alias(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    try:
        store = TaxonomyStore(connection)
        first = store.publish(_taxonomy(), fetched_at_ms=10)
        second = store.publish(_taxonomy(), fetched_at_ms=20)
        index = TaxonomyIndex(connection)

        assert first.snapshot_id == second.snapshot_id
        assert first.reused is False
        assert second.reused is True
        stable = index.resolve("local-id", "Wrong Local Name")
        alias = index.resolve("local-alias", "Athletic Body")
        clothing = index.resolve("local-clothing", "Stockings")
        trimmed = index.resolve("local-trimmed", "Trimmed")
        ambiguous = index.resolve("local-ambiguous", "Ambiguous")
        unmapped = index.resolve("local-unmapped", "Bubble Butt")

        assert stable is not None and stable.method == "stable_id"
        assert stable.role == "performer_attribute"
        assert alias is not None and alias.method == "unique_name_or_alias"
        assert alias.role == "performer_attribute"
        assert clothing is not None and clothing.role == "content"
        assert trimmed is not None and trimmed.role == "performer_attribute"
        assert ambiguous is not None and ambiguous.method == "ambiguous_name"
        assert ambiguous.role is None and ambiguous.ambiguity_count == 2
        assert unmapped is not None and unmapped.method == "unmapped"
        assert unmapped.role is None
    finally:
        connection.close()


def test_physical_category_allowlist_is_stable() -> None:
    assert BODY_TYPE_ID in PERFORMER_ATTRIBUTE_CATEGORY_IDS
    assert CLOTHING_ID not in PERFORMER_ATTRIBUTE_CATEGORY_IDS
