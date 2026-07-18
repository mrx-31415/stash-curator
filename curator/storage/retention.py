"""Bounded cleanup for immutable model and feature snapshots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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
    models = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT model_id FROM model_version
            WHERE status IN ('superseded', 'failed')
            ORDER BY COALESCE(published_at_ms, created_at_ms), model_id
            """
        )
        if str(row[0]) not in retained_models
    ]
    model_deletes = models if limit is None else models[:limit]

    referenced_features = {
        str(row["feature_version"])
        for row in connection.execute("SELECT model_id, feature_version FROM model_version")
        if str(row["model_id"]) not in model_deletes
    }
    features = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT feature_version FROM feature_build
            WHERE status IN ('superseded', 'failed')
            ORDER BY COALESCE(published_at_ms, created_at_ms), feature_version
            """
        )
        if str(row[0]) not in referenced_features
    ]
    feature_deletes = features if limit is None else features[:limit]
    if not dry_run and (model_deletes or feature_deletes):
        with transaction(connection):
            connection.executemany(
                "DELETE FROM model_version WHERE model_id=?", ((item,) for item in model_deletes)
            )
            for version in feature_deletes:
                connection.execute("DELETE FROM entity_feature WHERE feature_version=?", (version,))
                connection.execute(
                    "DELETE FROM feature_definition WHERE feature_version=?", (version,)
                )
                connection.execute("DELETE FROM feature_build WHERE feature_version=?", (version,))
    return RetentionResult(
        len(models),
        len(features),
        len(model_deletes) if not dry_run else 0,
        len(feature_deletes) if not dry_run else 0,
    )
