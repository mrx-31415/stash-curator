"""Connection, transaction, and backup helpers for SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self, overload
from uuid import uuid4

from curator.profiling import current_trace, span


class StorageError(RuntimeError):
    """Raised when a storage operation violates a Curator invariant."""


_LEGACY_DERIVED_TABLES = (
    ("model_scene_reason", "model_id", ("model_id", "scene_id", "reason_index")),
    ("model_lane_order", "model_id", ("model_id", "lane", "ordering", "position")),
    ("model_scene_lane", "model_id", ("model_id", "scene_id", "lane")),
    ("model_scene_score", "model_id", ("model_id", "scene_id")),
    ("model_scene_neighbor", "model_id", ("model_id", "scene_id", "rank")),
    ("direct_scene_state", "model_id", ("model_id", "scene_id")),
    ("feature_affinity", "model_id", ("model_id", "feature_id")),
    ("model_lane_candidate_cache", "model_id", ("model_id", "lane")),
    ("model_lane_order_state", "model_id", ("model_id",)),
    ("scene_content_search", "feature_version", ("feature_id", "scene_id")),
    (
        "entity_feature",
        "feature_version",
        ("feature_version", "entity_type", "entity_id", "feature_id"),
    ),
    ("feature_definition", "feature_version", ("feature_id",)),
)


def _sql_details(statement: str) -> tuple[str, dict[str, object]]:
    normalized = " ".join(statement.split())[:1_000]
    command = normalized.partition(" ")[0].upper() or "SQL"
    match = re.search(r"\b(?:FROM|INTO|UPDATE|TABLE)\s+([\w.]+)", normalized, re.IGNORECASE)
    return (f"{command} {match.group(1)}" if match else command, {"statement": normalized})


class ProfiledCursor(sqlite3.Cursor):
    def execute(self, sql: str, parameters: Any = (), /) -> Self:
        name, details = _sql_details(sql)
        with span("sqlite", name, details):
            super().execute(sql, parameters)
        return self

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> Self:
        name, details = _sql_details(sql)
        with span("sqlite", f"{name} many", details):
            super().executemany(sql, seq_of_parameters)
        return self

    def fetchone(self) -> Any:
        with span("sqlite", "fetchone"):
            return super().fetchone()

    def fetchmany(self, size: int | None = None) -> list[Any]:
        with span("sqlite", "fetchmany"):
            return super().fetchmany() if size is None else super().fetchmany(size)

    def fetchall(self) -> list[Any]:
        with span("sqlite", "fetchall"):
            return super().fetchall()


class ProfiledConnection(sqlite3.Connection):
    @overload
    def cursor(self, factory: None = None) -> ProfiledCursor: ...

    @overload
    def cursor[T: sqlite3.Cursor](self, factory: Callable[[sqlite3.Connection], T]) -> T: ...

    def cursor(self, factory: Any = None) -> Any:
        return super().cursor(ProfiledCursor if factory is None else factory)

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> sqlite3.Cursor:
        return self.cursor().executemany(sql, seq_of_parameters)

    def commit(self) -> None:
        with span("sqlite", "COMMIT"):
            super().commit()

    def rollback(self) -> None:
        with span("sqlite", "ROLLBACK"):
            super().rollback()


def connect_database(
    path: Path, *, readonly: bool = False, attach_artifacts: bool = True
) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Writable databases use WAL mode. Transactions are controlled explicitly rather
    than through sqlite3's legacy implicit transaction behavior.
    """
    path = path.expanduser().resolve()
    if readonly:
        if not path.is_file():
            raise StorageError(f"database does not exist: {path}")
        connection = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=30,
            factory=ProfiledConnection if current_trace() else sqlite3.Connection,
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            path.as_uri(),
            uri=True,
            isolation_level=None,
            timeout=30,
            factory=ProfiledConnection if current_trace() else sqlite3.Connection,
        )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    # A 128 MiB page cache turns the repeated full scans of the hundreds-of-MiB
    # generation artifacts during a model build from cold disk reads into page-cache
    # hits. Read-only connections additionally memory-map the file: that is safe and
    # read-only connections see the same coherent pages via the unified OS buffer
    # cache. Writable connections stay on the pager because the sidecar is shared
    # with other processes and the files can be replaced by maintenance operations
    # (for example VACUUM), where a stale mapping could serve obsolete data.
    connection.execute("PRAGMA cache_size = -131072")
    if readonly:
        connection.execute("PRAGMA mmap_size = 536870912")
    if not readonly:
        if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).casefold() != "wal":
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    if attach_artifacts:
        from curator.storage.artifacts import attach_active_artifacts

        attach_active_artifacts(connection)
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    """Run an explicit transaction and guarantee rollback on failure."""
    if connection.in_transaction:
        raise StorageError("nested transactions are not supported")
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def backup_database(
    source: sqlite3.Connection,
    destination: Path,
    *,
    overwrite: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Create a consistent backup and publish it atomically."""
    destination = destination.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise StorageError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    target = sqlite3.connect(temporary, isolation_level=None)
    try:
        source.backup(
            target,
            pages=256,
            progress=(
                lambda _status, remaining, total: (
                    progress(total - remaining, total) if progress else None
                )
            ),
        )
        target.close()
        os.replace(temporary, destination)
    except BaseException:
        target.close()
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _validated_artifact(path: Path, kind: str, generation_id: str) -> None:
    from curator.storage.artifacts import (
        FEATURE_TABLES,
        MODEL_TABLES,
        SUPPORTED_ARTIFACT_SCHEMA_VERSIONS,
    )

    artifact = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        meta = artifact.execute(
            "SELECT kind, generation_id, schema_version FROM artifact_meta"
        ).fetchone()
        tables = {
            str(row[0])
            for row in artifact.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            meta is None
            or tuple(meta[:2]) != (kind, generation_id)
            or int(meta[2]) not in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS
            or not set(FEATURE_TABLES if kind == "feature" else MODEL_TABLES) <= tables
            or str(artifact.execute("PRAGMA quick_check").fetchone()[0]) != "ok"
        ):
            raise StorageError(f"invalid {kind} artifact: {path.name}")
    finally:
        artifact.close()


def _compaction_targets(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    from curator.storage.artifacts import artifact_path, database_path

    core = database_path(connection)
    targets: dict[str, list[str]] = {"feature": [], "model": []}
    validated: dict[str, list[str]] = {"feature": [], "model": []}
    for kind, table, identifier in (
        ("feature", "feature_build", "feature_version"),
        ("model", "model_version", "model_id"),
    ):
        rows = connection.execute(
            f"""
            SELECT {identifier}, status, artifact_basename, validation_summary_json
            FROM {table}
            WHERE status IN ('published', 'superseded')
              AND validation_status='valid' AND artifact_basename IS NOT NULL
            """
        ).fetchall()
        active = False
        for row in rows:
            summary = json.loads(str(row["validation_summary_json"] or "{}"))
            path = artifact_path(core, str(row["artifact_basename"]))
            if summary.get("integrity") != "ok" or not path.is_file():
                continue
            generation_id = str(row[identifier])
            _validated_artifact(path, kind, generation_id)
            targets[kind].append(generation_id)
            validated[kind].append(generation_id)
            active |= str(row["status"]) == "published"
        if not active:
            raise StorageError(f"legacy compaction requires a valid active {kind} artifact")
    targets["model"].extend(
        str(row[0])
        for row in connection.execute(
            """
            SELECT model_id FROM model_version
            WHERE status='superseded' AND validation_status='retired'
              AND artifact_basename IS NULL
            """
        )
    )
    fingerprint = hashlib.sha256(
        "\0".join((*sorted(validated["feature"]), *sorted(validated["model"]))).encode()
    ).hexdigest()
    return tuple(targets["feature"]), tuple(targets["model"]), fingerprint


def _logical_database_bytes(connection: sqlite3.Connection) -> int:
    try:
        return int(
            connection.execute(
                "SELECT coalesce(sum(pgsize-unused), 0) FROM dbstat(?)", ("main",)
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return 0


def compaction_status(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        "SELECT value FROM application_meta WHERE key='legacy_compaction'"
    ).fetchone()
    stored = json.loads(str(row[0])) if row else {}
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    return {
        "status": str(stored.get("status", "never_run")),
        "rows_deleted": int(stored.get("rows_deleted", 0)),
        "logical_bytes_removed": int(stored.get("logical_bytes_removed", 0)),
        "reclaimable_bytes": freelist_count * page_size,
        "vacuum_pending": freelist_count > 0,
    }


def compact_legacy_generations(
    connection: sqlite3.Connection,
    *,
    batch_size: int = 5_000,
    max_batches: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Delete rebuildable core rows in restartable transactions."""
    if not 1 <= batch_size <= 50_000:
        raise ValueError("compaction batch size must be between 1 and 50000")
    if {str(row["name"]) for row in connection.execute("PRAGMA database_list")} & {
        "feature_generation",
        "model_generation",
    }:
        raise StorageError("legacy compaction requires a core-only connection")

    feature_ids, model_ids, fingerprint = _compaction_targets(connection)
    target_ids = {"feature_version": feature_ids, "model_id": model_ids}

    def count_remaining() -> int:
        count = 0
        for table, generation_column, _ in _LEGACY_DERIVED_TABLES:
            ids = target_ids[generation_column]
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            count += int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE {generation_column} IN ({placeholders})",
                    ids,
                ).fetchone()[0]
            )
        return count

    target_row_count = count_remaining()
    if progress:
        progress(0, max(1, target_row_count))
    previous_row = connection.execute(
        "SELECT value FROM application_meta WHERE key='legacy_compaction'"
    ).fetchone()
    previous = json.loads(str(previous_row[0])) if previous_row else {}
    rows_deleted = (
        int(previous.get("rows_deleted", 0)) if previous.get("fingerprint") == fingerprint else 0
    )
    logical_bytes_removed = (
        int(previous.get("logical_bytes_removed", 0))
        if previous.get("fingerprint") == fingerprint
        else 0
    )
    before_bytes = _logical_database_bytes(connection)
    before_freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    batches = 0
    per_table: dict[str, int] = {}

    stopped = False
    for table, generation_column, key_columns in _LEGACY_DERIVED_TABLES:
        for generation_id in target_ids[generation_column]:
            keys = ", ".join(key_columns)
            while True:
                with transaction(connection):
                    cursor = connection.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE {generation_column}=?
                          AND ({keys}) IN (
                            SELECT {keys} FROM {table}
                            WHERE {generation_column}=? LIMIT ?
                          )
                        """,
                        (generation_id, generation_id, batch_size),
                    )
                    deleted = cursor.rowcount
                    if deleted:
                        rows_deleted += deleted
                        per_table[table] = per_table.get(table, 0) + deleted
                        state = {
                            "status": "in_progress",
                            "fingerprint": fingerprint,
                            "rows_deleted": rows_deleted,
                        }
                        connection.execute(
                            """
                            INSERT INTO application_meta(key, value)
                            VALUES ('legacy_compaction', ?)
                            ON CONFLICT(key) DO UPDATE SET value=excluded.value
                            """,
                            (json.dumps(state, sort_keys=True, separators=(",", ":")),),
                        )
                if not deleted:
                    break
                batches += 1
                if progress:
                    progress(sum(per_table.values()), max(1, target_row_count))
                if max_batches is not None and batches >= max_batches:
                    stopped = True
                    break
            if stopped:
                break
        if stopped:
            break

    remaining_rows = count_remaining()
    if progress and not target_row_count:
        progress(1, 1)
    after_bytes = _logical_database_bytes(connection)
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    result: dict[str, object] = {
        "status": "complete" if remaining_rows == 0 else "in_progress",
        "rows_deleted": rows_deleted,
        "rows_deleted_this_run": sum(per_table.values()),
        "rows_remaining": remaining_rows,
        "logical_bytes_removed": logical_bytes_removed + max(0, before_bytes - after_bytes),
        "reclaimable_bytes_added": max(
            0,
            (int(connection.execute("PRAGMA freelist_count").fetchone()[0]) - before_freelist)
            * page_size,
        ),
        "vacuum_required_to_shrink_file": True,
    }
    stored = {**result, "fingerprint": fingerprint}
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO application_meta(key, value) VALUES ('legacy_compaction', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (json.dumps(stored, sort_keys=True, separators=(",", ":")),),
        )
    return result
