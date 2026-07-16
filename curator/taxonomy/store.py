"""Version and resolve cached external tag taxonomy data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from curator.storage import transaction
from curator.taxonomy.stashdb import TaxonomyData

_CATEGORY_ROLE_PATH = Path(__file__).with_name("stashdb_category_roles.json")
CATEGORY_ROLE_FINGERPRINT = hashlib.sha256(_CATEGORY_ROLE_PATH.read_bytes()).hexdigest()


def _load_category_roles() -> tuple[str, dict[str, str]]:
    payload = json.loads(_CATEGORY_ROLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("unsupported StashDB category-role resource")
    default = payload.get("default_role")
    categories = payload.get("categories")
    if default not in {"content", "performer_attribute"} or not isinstance(categories, list):
        raise RuntimeError("invalid StashDB category-role resource")
    roles: dict[str, str] = {}
    for item in categories:
        if not isinstance(item, dict):
            raise RuntimeError("invalid StashDB category-role entry")
        category_id = item.get("id")
        role = item.get("role")
        if not isinstance(category_id, str) or role not in {"content", "performer_attribute"}:
            raise RuntimeError("invalid StashDB category-role entry")
        roles[category_id] = role
    return default, roles


DEFAULT_CATEGORY_ROLE, STASHDB_CATEGORY_ROLES = _load_category_roles()
PERFORMER_ATTRIBUTE_CATEGORY_IDS = frozenset(
    category_id
    for category_id, role in STASHDB_CATEGORY_ROLES.items()
    if role == "performer_attribute"
)


@dataclass(frozen=True)
class TaxonomyPublishResult:
    snapshot_id: str
    category_count: int
    tag_count: int
    reused: bool


@dataclass(frozen=True)
class TaxonomyMatch:
    snapshot_id: str
    role: str | None
    external_tag_id: str | None
    external_category_id: str | None
    method: str
    confidence: float
    ambiguity_count: int = 0


class TaxonomyStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def publish(self, data: TaxonomyData, *, fetched_at_ms: int) -> TaxonomyPublishResult:
        canonical = json.dumps(asdict(data), sort_keys=True, separators=(",", ":"))
        snapshot_id = f"tax-{hashlib.sha256(canonical.encode()).hexdigest()[:20]}"
        reused = (
            self.connection.execute(
                "SELECT 1 FROM taxonomy_snapshot WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            is not None
        )
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT OR IGNORE INTO taxonomy_snapshot(
                    snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    data.endpoint,
                    fetched_at_ms,
                    len(data.categories),
                    len(data.tags),
                ),
            )
            if not reused:
                self.connection.executemany(
                    """
                    INSERT INTO taxonomy_category(
                        snapshot_id, category_id, name, group_name, description
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            snapshot_id,
                            item.category_id,
                            item.name,
                            item.group,
                            item.description,
                        )
                        for item in data.categories
                    ),
                )
                self.connection.executemany(
                    """
                    INSERT INTO taxonomy_tag(snapshot_id, tag_id, name, category_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    ((snapshot_id, item.tag_id, item.name, item.category_id) for item in data.tags),
                )
                self.connection.executemany(
                    """
                    INSERT INTO taxonomy_tag_alias(snapshot_id, tag_id, alias)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (snapshot_id, item.tag_id, alias)
                        for item in data.tags
                        for alias in item.aliases
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (snapshot_id,),
            )
        return TaxonomyPublishResult(snapshot_id, len(data.categories), len(data.tags), reused)


class TaxonomyIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        row = connection.execute(
            "SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'"
        ).fetchone()
        self.snapshot_id = str(row[0]) if row else None
        self.tags: dict[str, tuple[str | None, str]] = {}
        self.names: dict[str, set[str]] = {}
        if self.snapshot_id is None:
            return
        for tag in connection.execute(
            "SELECT tag_id, category_id, name FROM taxonomy_tag WHERE snapshot_id=?",
            (self.snapshot_id,),
        ):
            tag_id = str(tag["tag_id"])
            self.tags[tag_id] = (
                str(tag["category_id"]) if tag["category_id"] else None,
                str(tag["name"]),
            )
            self.names.setdefault(_normalize(str(tag["name"])), set()).add(tag_id)
        for alias in connection.execute(
            "SELECT tag_id, alias FROM taxonomy_tag_alias WHERE snapshot_id=?",
            (self.snapshot_id,),
        ):
            self.names.setdefault(_normalize(str(alias["alias"])), set()).add(str(alias["tag_id"]))

    def resolve(self, local_tag_id: str, name: str | None) -> TaxonomyMatch | None:
        if self.snapshot_id is None:
            return None
        external_ids = {
            str(row["stash_id"])
            for row in self.connection.execute(
                "SELECT endpoint, stash_id FROM source_tag_stash_id WHERE tag_id=?",
                (local_tag_id,),
            )
            if _is_stashdb(str(row["endpoint"]))
        }
        known_ids = sorted(external_ids & self.tags.keys())
        if len(known_ids) == 1:
            return self._match(known_ids[0], "stable_id", 1.0)
        if len(known_ids) > 1:
            return TaxonomyMatch(
                self.snapshot_id, None, None, None, "ambiguous_stable_id", 0.0, len(known_ids)
            )
        candidates = sorted(self.names.get(_normalize(name or ""), set()))
        if len(candidates) == 1:
            return self._match(candidates[0], "unique_name_or_alias", 0.9)
        if len(candidates) > 1:
            return TaxonomyMatch(
                self.snapshot_id, None, None, None, "ambiguous_name", 0.0, len(candidates)
            )
        return TaxonomyMatch(self.snapshot_id, None, None, None, "unmapped", 0.0)

    def _match(self, tag_id: str, method: str, confidence: float) -> TaxonomyMatch:
        if self.snapshot_id is None:
            raise RuntimeError("taxonomy index has no active snapshot")
        category_id, _ = self.tags[tag_id]
        role = STASHDB_CATEGORY_ROLES.get(category_id or "", DEFAULT_CATEGORY_ROLE)
        return TaxonomyMatch(self.snapshot_id, role, tag_id, category_id, method, confidence)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _is_stashdb(endpoint: str) -> bool:
    return (urlparse(endpoint).hostname or "").casefold() == "stashdb.org"
