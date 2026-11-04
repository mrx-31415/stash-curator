"""get_taste_profile's describes_performer flag: Go/Python parity and rules.

The flag marks tags about who is in a scene (a performer_attribute role, a
StashDB PEOPLE-group category other than Clothing, or a listed nationality
tag). It is display-only, so tag roles and the model must not change.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.api import CuratorAPI
from curator.core import core_binary
from curator.model import PreferenceModelBuilder
from curator.storage import connect_database
from curator.taxonomy import store
from tests.core.test_backend import PLUGIN_DIR, _StubStash, payload
from tests.core.test_backend_slice1 import assert_slice1_identical
from tests.model.test_builder import REFERENCE_MS, _database

ROOT = Path(__file__).resolve().parents[2]
STASHDB_ENDPOINT = "https://stashdb.org/graphql"
CLOTHING_CATEGORY = "dc566ccc-0584-41d8-b9f5-4d8680b890c1"
NATIONALITY_TAG = "86d1e01d-5a9a-4086-99cf-4af68b369ab8"

# (local tag, name, StashDB stash_id or None to resolve by name)
EXTRA_TAGS = (
    ("t-attribute", "Big Tits", None),
    ("t-age", "Age Theme", None),
    ("t-clothing", "Clothing Theme", "ext-clothing"),
    ("t-nation", "Nation Theme", NATIONALITY_TAG),
    ("t-misc", "Misc Theme", "ext-misc"),
)


def _make_sidecar(path: Path) -> None:
    connection = _database(path)
    try:
        connection.executemany(
            "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
            ((tag, name, tag) for tag, name, _ in EXTRA_TAGS),
        )
        connection.executemany(
            "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
            (("old-good", tag) for tag, _, _ in EXTRA_TAGS),
        )
        connection.executemany(
            "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
            ((tag, STASHDB_ENDPOINT, stash_id) for tag, _, stash_id in EXTRA_TAGS if stash_id),
        )
        connection.execute(
            """INSERT INTO taxonomy_snapshot(
                snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
            ) VALUES ('tax-people', ?, 1, 3, 4)""",
            (STASHDB_ENDPOINT,),
        )
        connection.executemany(
            """INSERT INTO taxonomy_category(snapshot_id, category_id, name, group_name)
            VALUES ('tax-people', ?, ?, ?)""",
            (
                ("cat-age", "Age Theme Group", "PEOPLE"),
                (CLOTHING_CATEGORY, "Clothing", "PEOPLE"),
                ("cat-misc", "Misc", "OTHER"),
            ),
        )
        connection.executemany(
            """INSERT INTO taxonomy_tag(snapshot_id, tag_id, name, category_id)
            VALUES ('tax-people', ?, ?, ?)""",
            (
                ("ext-age", "Age Theme", "cat-age"),
                ("ext-clothing", "Clothing Theme", CLOTHING_CATEGORY),
                (NATIONALITY_TAG, "Nation Theme", "cat-misc"),
                ("ext-misc", "Misc Theme", "cat-misc"),
            ),
        )
        connection.execute(
            "INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', 'tax-people')"
        )
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        connection.commit()
    finally:
        connection.close()


def _profile(path: Path) -> dict[str, dict[str, object]]:
    connection = connect_database(path)
    try:
        items = CuratorAPI(connection).taste_profile()["items"]
    finally:
        connection.close()
    return {str(item["tag_id"]): item for item in items}


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubStash)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_describes_performer_matches_and_leaves_roles_alone(
    binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    sidecar = tmp_path / "curator.sqlite3"
    _make_sidecar(sidecar)
    raw = payload("get_taste_profile", sidecar, stub_stash)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, sidecar)
    items = _profile(sidecar)
    flags = {tag: items[tag]["describes_performer"] for tag, _, _ in EXTRA_TAGS}
    assert flags == {
        "t-attribute": True,
        "t-age": True,
        "t-clothing": False,
        "t-nation": True,
        "t-misc": False,
    }
    assert items["good"]["describes_performer"] is False
    # The flag is descriptive: the matched tags keep the roles the model uses.
    roles = {tag: items[tag]["role"] for tag, _, _ in EXTRA_TAGS}
    assert roles == {
        "t-attribute": "performer_attribute",
        "t-age": "content",
        "t-clothing": "content",
        "t-nation": "content",
        "t-misc": "content",
    }

    # Without a taxonomy snapshot only the role-based flag remains.
    connection = connect_database(sidecar)
    try:
        connection.execute("DELETE FROM application_meta WHERE key='taxonomy_snapshot_id'")
        connection.commit()
    finally:
        connection.close()
    assert_slice1_identical(binary, PLUGIN_DIR, raw, sidecar)
    flagged = {tag for tag, item in _profile(sidecar).items() if item["describes_performer"]}
    assert flagged == {"t-attribute"}


def test_embedded_taxonomy_resources_byte_identical() -> None:
    for name in ("stashdb_category_roles.json", "stashdb_performer_tags.json"):
        python_copy = ROOT / "curator" / "taxonomy" / name
        assert (ROOT / "core" / name).read_bytes() == python_copy.read_bytes()


def test_performer_tags_stay_out_of_the_role_fingerprint() -> None:
    """The role fingerprint feeds the feature version, so the performer-tag
    list must live outside the category-role resource it hashes."""
    roles_path = ROOT / "curator" / "taxonomy" / "stashdb_category_roles.json"
    digest = hashlib.sha256(roles_path.read_bytes()).hexdigest()
    assert digest == store.CATEGORY_ROLE_FINGERPRINT
    role_categories = {item["id"] for item in json.loads(roles_path.read_text())["categories"]}
    assert not role_categories & store.NATIONALITY_TAG_IDS
    assert not role_categories & store.PEOPLE_EXCLUDED_CATEGORY_IDS
    assert len(store.NATIONALITY_TAG_IDS) == 82
