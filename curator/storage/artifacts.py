"""Immutable feature/model SQLite generation files."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from curator.storage.database import StorageError

ARTIFACT_SCHEMA_VERSION = 3
SUPPORTED_ARTIFACT_SCHEMA_VERSIONS = frozenset({1, 2, 3})
_FINAL_NAME = re.compile(r"(feature-fv-[0-9a-f]{20}|model-[0-9a-f]{20})\.sqlite3")
_TEMP_NAME = re.compile(r"\.(feature-fv-[0-9a-f]{20}|model-[0-9a-f]{20})\.[0-9a-f]{32}\.tmp")
FEATURE_TABLES = ("feature_definition", "entity_feature", "scene_content_search")
MODEL_TABLES = (
    "feature_affinity",
    "direct_scene_state",
    "model_scene_score",
    "model_scene_neighbor",
    "model_performer_edge",
    "model_scene_reason",
    "model_scene_lane",
    "model_lane_candidate_cache",
    "model_lane_order",
    "model_lane_order_state",
)

FEATURE_SCHEMA = """
CREATE TABLE artifact_meta (
    kind TEXT NOT NULL, generation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
) STRICT;
CREATE TABLE feature_definition (
    feature_id TEXT PRIMARY KEY, feature_version TEXT NOT NULL, family TEXT NOT NULL,
    name TEXT NOT NULL, provenance TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE TABLE entity_feature (
    feature_version TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    feature_id TEXT NOT NULL REFERENCES feature_definition(feature_id) ON DELETE CASCADE,
    value REAL NOT NULL, confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (feature_version, entity_type, entity_id, feature_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE scene_content_search (
    feature_version TEXT NOT NULL, feature_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    value REAL NOT NULL, PRIMARY KEY (feature_id, scene_id)
) STRICT, WITHOUT ROWID;
"""

MODEL_SCHEMA = """
CREATE TABLE artifact_meta (
    kind TEXT NOT NULL, generation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
) STRICT;
CREATE TABLE feature_affinity (
    model_id TEXT NOT NULL, feature_id TEXT NOT NULL,
    affinity REAL NOT NULL CHECK (affinity BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    effective_support REAL NOT NULL CHECK (effective_support >= 0),
    distinct_scene_count INTEGER NOT NULL CHECK (distinct_scene_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (model_id, feature_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE direct_scene_state (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    effective_evidence REAL NOT NULL CHECK (effective_evidence >= 0),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    residual REAL NOT NULL CHECK (residual BETWEEN -2 AND 2),
    PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_score (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    general_appeal REAL NOT NULL CHECK (general_appeal BETWEEN -1 AND 1),
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    direct_confidence REAL NOT NULL CHECK (direct_confidence BETWEEN 0 AND 1),
    appeal REAL NOT NULL CHECK (appeal BETWEEN -1 AND 1),
    current_fit REAL NOT NULL CHECK (current_fit BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    metadata_confidence REAL NOT NULL CHECK (metadata_confidence BETWEEN 0 AND 1),
    recovery REAL NOT NULL CHECK (recovery BETWEEN 0 AND 1),
    components_json TEXT NOT NULL,
    classification_json TEXT NOT NULL DEFAULT '{}',
    eligibility_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_neighbor (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 4), neighbor_scene_id TEXT NOT NULL,
    similarity REAL NOT NULL, weight REAL NOT NULL, outcome REAL NOT NULL,
    PRIMARY KEY (model_id, scene_id, rank)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_performer_edge (
    model_id TEXT NOT NULL, performer_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 2),
    similar_performer_id TEXT NOT NULL,
    similarity REAL NOT NULL, affinity REAL NOT NULL, confidence REAL NOT NULL,
    PRIMARY KEY (model_id, performer_id, rank)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_reason (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    reason_index INTEGER NOT NULL CHECK (reason_index >= 0), reason_code TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('positive','negative','unknown','neutral')),
    magnitude REAL NOT NULL CHECK (magnitude BETWEEN 0 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    subject_type TEXT, subject_id TEXT,
    visibility TEXT NOT NULL CHECK (visibility IN ('standard','sensitive','private')),
    provenance TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, scene_id, reason_index)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_lane (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('for_you','best_bets','revisit','stretch','adventure')),
    subtype TEXT, lane_value REAL NOT NULL, qualification_json TEXT NOT NULL DEFAULT '{}',
    appeal REAL, PRIMARY KEY (model_id, scene_id, lane)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_candidate_cache (
    model_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('best_bets','revisit','stretch','adventure')),
    candidates_json TEXT NOT NULL, candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0), PRIMARY KEY (model_id, lane)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_order (
    model_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('for_you','best_bets','revisit','stretch','adventure')),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first','varied')),
    position INTEGER NOT NULL CHECK (position >= 0), scene_id TEXT NOT NULL,
    source_lane TEXT NOT NULL CHECK (
        source_lane IN ('best_bets','revisit','stretch','adventure')
    ),
    utility REAL NOT NULL, ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_order_state (
    model_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
"""


def database_path(connection: sqlite3.Connection) -> Path:
    row = next(row for row in connection.execute("PRAGMA database_list") if row["name"] == "main")
    if not row["file"]:
        raise StorageError("generation artifacts require a file-backed core database")
    return Path(str(row["file"])).resolve()


def cache_directory(core_path: Path) -> Path:
    return core_path.resolve().with_name(f"{core_path.stem}-derived")


def artifact_path(core_path: Path, basename: str, *, temporary: bool = False) -> Path:
    pattern = _TEMP_NAME if temporary else _FINAL_NAME
    if Path(basename).name != basename or not pattern.fullmatch(basename):
        raise StorageError(f"invalid artifact basename: {basename}")
    directory = cache_directory(core_path)
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise StorageError(f"unsafe derived-cache directory: {directory}")
    path = directory / basename
    if path.is_symlink() or path.resolve(strict=False).parent != directory.resolve(strict=False):
        raise StorageError(f"unsafe artifact path: {basename}")
    return path


def _readonly_uri(path: Path, *, immutable: bool = True) -> str:
    suffix = "&immutable=1" if immutable else ""
    return f"{path.as_uri()}?mode=ro{suffix}"


def _attach_readonly(connection: sqlite3.Connection, alias: str, path: Path) -> None:
    """Attach a published artifact read-only, retrying without the lock-free
    immutable flag when the filesystem rejects it.

    The immutable=1 open skips locking entirely, which is normally fine for
    published artifacts, but some filesystems (network mounts, freshly renamed
    files) reject it with SQLITE_CANTOPEN. A plain mode=ro attach is
    equivalent for our purposes (published artifacts are never modified while
    attached) and only takes a shared lock instead.
    """
    try:
        connection.execute(f"ATTACH DATABASE ? AS {alias}", (_readonly_uri(path),))
    except sqlite3.OperationalError as error:
        if "unable to open database" not in str(error):
            raise
        try:
            connection.execute(
                f"ATTACH DATABASE ? AS {alias}", (_readonly_uri(path, immutable=False),)
            )
        except sqlite3.OperationalError:
            # Some filesystems reject file:// URI opens even in plain mode=ro
            # (observed on the CI runner; a plain path open works there). The
            # published artifacts are never modified while attached, so a
            # plain-path attach is functionally identical — it just takes a
            # normal (read-capable) open instead of a URI one.
            connection.execute(f"ATTACH DATABASE ? AS {alias}", (str(path),))


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def create_artifact(
    core: sqlite3.Connection, kind: str, identifier: str
) -> tuple[sqlite3.Connection, Path, Path]:
    if kind not in {"feature", "model"}:
        raise ValueError(f"unknown artifact kind: {kind}")
    expected = f"feature-{identifier}" if kind == "feature" else identifier
    final = artifact_path(database_path(core), f"{expected}.sqlite3")
    directory = final.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = artifact_path(database_path(core), f".{expected}.{uuid4().hex}.tmp", temporary=True)
    connection = sqlite3.connect(temporary.as_uri(), uri=True, isolation_level=None, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA user_version={ARTIFACT_SCHEMA_VERSION}")
    # Publication writes hundreds of thousands of rows and then creates indexes over
    # a file that grows to hundreds of MiB through this connection. SQLite's 2 MiB
    # default cache turns that into cold random I/O; a 256 MiB cache plus memory
    # mapping keeps the index builds and the attached feature-generation reads in
    # memory. The temporary file is exclusively owned by this process, so mapping it
    # is safe: nothing else can modify or replace it while it is open.
    connection.execute("PRAGMA cache_size = -262144")
    connection.execute("PRAGMA mmap_size = 1073741824")
    connection.executescript(FEATURE_SCHEMA if kind == "feature" else MODEL_SCHEMA)
    connection.execute(
        "INSERT INTO artifact_meta(kind, generation_id, schema_version) VALUES (?, ?, ?)",
        (kind, identifier, ARTIFACT_SCHEMA_VERSION),
    )
    return connection, temporary, final


def create_indexes(connection: sqlite3.Connection, kind: str) -> None:
    if kind == "feature":
        connection.executescript(
            """
            CREATE INDEX entity_feature_feature_idx ON entity_feature(feature_id);
            CREATE INDEX scene_content_search_scene_idx
            ON scene_content_search(feature_version, scene_id, feature_id);
            """
        )
    else:
        connection.executescript(
            """
            CREATE INDEX model_scene_score_fit_idx
            ON model_scene_score(model_id, current_fit DESC);
            CREATE INDEX model_scene_score_prune_idx
            ON model_scene_score(model_id, appeal, confidence, scene_id);
            CREATE INDEX model_scene_lane_value_idx
            ON model_scene_lane(model_id, lane, lane_value DESC, scene_id);
            CREATE INDEX model_scene_lane_appeal_idx
            ON model_scene_lane(model_id, scene_id, appeal);
            """
        )


def attach_build_sources(
    connection: sqlite3.Connection, core: sqlite3.Connection, feature_path: Path
) -> None:
    connection.execute(
        "ATTACH DATABASE ? AS core",
        (_readonly_uri(database_path(core), immutable=False),),
    )
    connection.execute("ATTACH DATABASE ? AS feature_generation", (_readonly_uri(feature_path),))
    owned = set(MODEL_TABLES) | set(FEATURE_TABLES)
    for row in connection.execute(
        "SELECT name FROM core.sqlite_master WHERE type='table' ORDER BY name"
    ):
        name = str(row[0])
        if name not in owned and not name.startswith("sqlite_"):
            quoted = _quote(name)
            connection.execute(f"CREATE TEMP VIEW {quoted} AS SELECT * FROM core.{quoted}")
    for name in FEATURE_TABLES:
        quoted = _quote(name)
        connection.execute(
            f"CREATE TEMP VIEW {quoted} AS SELECT * FROM feature_generation.{quoted}"
        )


def validate_artifact(
    connection: sqlite3.Connection,
    kind: str,
    counts: dict[str, int],
    *,
    check_integrity: bool = True,
) -> dict[str, object]:
    integrity = (
        str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if check_integrity
        else "skipped"
    )
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if (check_integrity and integrity != "ok") or schema_version != ARTIFACT_SCHEMA_VERSION:
        raise StorageError(
            f"{kind} artifact validation failed: integrity={integrity}, schema={schema_version}"
        )
    return {
        "integrity": integrity,
        "schema_version": schema_version,
        "counts": counts,
    }


def publish_file(connection: sqlite3.Connection, temporary: Path, final: Path) -> int:
    connection.close()
    os.replace(temporary, final)
    return final.stat().st_size


def discard_artifact(connection: sqlite3.Connection | None, temporary: Path | None) -> None:
    if connection is not None:
        connection.close()
    if temporary is not None:
        temporary.unlink(missing_ok=True)


def _registry_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({_quote(table)})")}


def _artifact_tables(
    connection: sqlite3.Connection, alias: str, tables: tuple[str, ...]
) -> tuple[str, ...]:
    """Only the tables the attached artifact actually has.

    SQLite validates ``CREATE TEMP VIEW ... AS SELECT * FROM alias.table`` lazily,
    so an artifact built by older code would silently produce a view over a missing
    table. That view shadows the core-schema name, so later DDL or queries on the
    name break (a migration's CREATE INDEX fails with "views may not be indexed").
    Filtering to existing tables keeps upgrades safe: names absent from the artifact
    resolve to the core-schema copy instead.
    """
    present = {
        str(row[0])
        for row in connection.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table'")
    }
    return tuple(table for table in tables if table in present)


def attach_active_artifacts(connection: sqlite3.Connection) -> None:
    if "artifact_basename" not in _registry_columns(connection, "feature_build"):
        return
    core = database_path(connection)
    rows = (
        (
            "feature_generation",
            FEATURE_TABLES,
            connection.execute(
                """
                SELECT artifact_basename FROM feature_build
                WHERE status='published' AND validation_status='valid'
                """
            ).fetchone(),
        ),
        (
            "model_generation",
            MODEL_TABLES,
            connection.execute(
                """
                SELECT artifact_basename FROM model_version
                WHERE status='published' AND validation_status='valid'
                """
            ).fetchone(),
        ),
    )
    for alias, tables, row in rows:
        if row is None or not row[0]:
            continue
        path = artifact_path(core, str(row[0]))
        if not path.is_file():
            raise StorageError(f"active artifact is missing: {path.name}")
        _attach_readonly(connection, alias, path)
        if (
            int(connection.execute(f"PRAGMA {alias}.user_version").fetchone()[0])
            not in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS
        ):
            raise StorageError(f"unsupported active artifact schema: {path.name}")
        for table in _artifact_tables(connection, alias, tables):
            quoted = _quote(table)
            connection.execute(f"CREATE TEMP VIEW {quoted} AS SELECT * FROM {alias}.{quoted}")


def activate_artifact(connection: sqlite3.Connection, kind: str, path: Path) -> None:
    alias, tables = (
        ("feature_generation", FEATURE_TABLES)
        if kind == "feature"
        else ("model_generation", MODEL_TABLES)
    )
    for table in tables:
        connection.execute(f"DROP VIEW IF EXISTS temp.{_quote(table)}")
    attached = {str(row["name"]) for row in connection.execute("PRAGMA database_list")}
    if alias in attached:
        connection.execute(f"DETACH DATABASE {alias}")
    _attach_readonly(connection, alias, path)
    if (
        int(connection.execute(f"PRAGMA {alias}.user_version").fetchone()[0])
        not in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS
    ):
        connection.execute(f"DETACH DATABASE {alias}")
        raise StorageError(f"unsupported active artifact schema: {path.name}")
    for table in _artifact_tables(connection, alias, tables):
        quoted = _quote(table)
        connection.execute(f"CREATE TEMP VIEW {quoted} AS SELECT * FROM {alias}.{quoted}")


def artifact_attached(connection: sqlite3.Connection, kind: str) -> bool:
    alias = f"{kind}_generation"
    return alias in {str(row["name"]) for row in connection.execute("PRAGMA database_list")}


def attached_generation_id(connection: sqlite3.Connection, kind: str) -> str | None:
    if not artifact_attached(connection, kind):
        return None
    row = connection.execute(
        f"SELECT generation_id FROM {kind}_generation.artifact_meta"
    ).fetchone()
    return str(row[0]) if row else None


def generation_diagnostics(connection: sqlite3.Connection) -> dict[str, object]:
    result: dict[str, object] = {
        "cleanup_retry_count": sum(
            int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE cleanup_error IS NOT NULL"
                ).fetchone()[0]
            )
            for table in ("feature_build", "model_version")
            if "cleanup_error" in _registry_columns(connection, table)
        )
    }
    for kind, table, identifier in (
        ("feature", "feature_build", "feature_version"),
        ("model", "model_version", "model_id"),
    ):
        if "artifact_basename" not in _registry_columns(connection, table):
            result[kind] = None
            continue
        row = connection.execute(
            f"""
            SELECT {identifier}, artifact_basename, artifact_schema_version, artifact_bytes,
                   validation_status, validation_summary_json, cleanup_error, reuse_count
            FROM {table} WHERE status='published'
            """
        ).fetchone()
        result[kind] = (
            {
                identifier: row[identifier],
                "artifact_basename": row["artifact_basename"],
                "schema_version": row["artifact_schema_version"],
                "bytes": row["artifact_bytes"],
                "validation_status": row["validation_status"],
                "validation": json.loads(row["validation_summary_json"] or "{}"),
                "reuse_count": int(row["reuse_count"]),
                "cleanup_retry": bool(row["cleanup_error"]),
            }
            if row
            else None
        )
    return result


def recognized_artifacts(core_path: Path) -> tuple[Path, ...]:
    directory = cache_directory(core_path)
    if not directory.is_dir() or directory.is_symlink():
        return ()
    return tuple(
        path
        for path in directory.iterdir()
        if not path.is_symlink()
        and path.is_file()
        and (_FINAL_NAME.fullmatch(path.name) or _TEMP_NAME.fullmatch(path.name))
    )
