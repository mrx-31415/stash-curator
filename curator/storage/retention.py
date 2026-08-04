"""Bounded cleanup for immutable model and feature snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from curator.storage.artifacts import artifact_path, database_path
from curator.storage.database import transaction


@dataclass(frozen=True)
class RetentionResult:
    model_candidates: int
    feature_candidates: int
    deleted_models: int
    deleted_features: int


def prune_snapshots(
    connection: sqlite3.Connection, *, limit: int | None = 1, dry_run: bool = False
) -> RetentionResult:
    retained_models = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT model_id FROM model_version
            WHERE status IN ('published', 'superseded')
            ORDER BY COALESCE(published_at_ms, created_at_ms) DESC LIMIT 2
            """
        )
    }
    model_rows = [
        (str(row["model_id"]), str(row["artifact_basename"]) if row["artifact_basename"] else None)
        for row in connection.execute(
            """
            SELECT model_id, artifact_basename FROM model_version
            WHERE status IN ('superseded', 'failed') OR (
                status='building' AND created_at_ms < COALESCE(
                    (SELECT max(created_at_ms) FROM model_version WHERE status='published'),
                    created_at_ms
                )
            )
            ORDER BY COALESCE(published_at_ms, created_at_ms), model_id
            """
        )
        if str(row["model_id"]) not in retained_models
    ]
    model_deletes = model_rows if limit is None else model_rows[:limit]

    referenced_features = {
        str(row["feature_version"])
        for row in connection.execute("SELECT model_id, feature_version FROM model_version")
        if str(row["model_id"]) not in {model_id for model_id, _ in model_deletes}
    }
    feature_rows = [
        (
            str(row["feature_version"]),
            str(row["artifact_basename"]) if row["artifact_basename"] else None,
        )
        for row in connection.execute(
            """
            SELECT feature_version, artifact_basename FROM feature_build
            WHERE status IN ('superseded', 'failed')
            ORDER BY COALESCE(published_at_ms, created_at_ms), feature_version
            """
        )
        if str(row["feature_version"]) not in referenced_features
    ]
    feature_deletes = feature_rows if limit is None else feature_rows[:limit]
    if not dry_run and (model_deletes or feature_deletes):
        successful_models: list[tuple[str, str | None]] = []
        successful_features: list[tuple[str, str | None]] = []
        core_path = database_path(connection)
        for table, identifier, rows, successful in (
            ("model_version", "model_id", model_deletes, successful_models),
            ("feature_build", "feature_version", feature_deletes, successful_features),
        ):
            for item, basename in rows:
                if basename:
                    try:
                        artifact_path(core_path, basename).unlink(missing_ok=True)
                    except OSError as error:
                        with transaction(connection):
                            connection.execute(
                                f"UPDATE {table} SET cleanup_error=? WHERE {identifier}=?",
                                (str(error)[:2000], item),
                            )
                        continue
                successful.append((item, basename))
        with transaction(connection):
            for model_id, basename in successful_models:
                if basename:
                    connection.execute(
                        """
                        UPDATE model_version SET artifact_basename=NULL,
                            validation_status='retired', cleanup_error=NULL
                        WHERE model_id=?
                        """,
                        (model_id,),
                    )
                else:
                    connection.execute("DELETE FROM model_version WHERE model_id=?", (model_id,))
            for version, basename in successful_features:
                if basename:
                    connection.execute(
                        """
                        UPDATE feature_build SET artifact_basename=NULL,
                            validation_status='retired', cleanup_error=NULL
                        WHERE feature_version=?
                        """,
                        (version,),
                    )
                else:
                    # An attached artifact shadows these names with a temp view, and a view
                    # cannot be deleted from; the rows being retired are the core ones.
                    connection.execute(
                        "DELETE FROM main.entity_feature WHERE feature_version=?", (version,)
                    )
                    connection.execute(
                        "DELETE FROM main.feature_definition WHERE feature_version=?", (version,)
                    )
                    connection.execute(
                        "DELETE FROM feature_build WHERE feature_version=?", (version,)
                    )
        model_deletes = successful_models
        feature_deletes = successful_features
    return RetentionResult(
        len(model_rows),
        len(feature_rows),
        len(model_deletes) if not dry_run else 0,
        len(feature_deletes) if not dry_run else 0,
    )
