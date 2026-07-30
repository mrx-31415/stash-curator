"""SQLite storage primitives for Stash Curator."""

from curator.storage.artifacts import generation_diagnostics, recognized_artifacts
from curator.storage.database import (
    StorageError,
    backup_database,
    compact_legacy_generations,
    compaction_status,
    connect_database,
    transaction,
)
from curator.storage.migrations import MigrationError, MigrationRunner
from curator.storage.models import ModelStore, ModelVersion
from curator.storage.retention import RetentionResult, prune_snapshots

__all__ = [
    "MigrationError",
    "MigrationRunner",
    "ModelStore",
    "ModelVersion",
    "RetentionResult",
    "StorageError",
    "backup_database",
    "compact_legacy_generations",
    "compaction_status",
    "connect_database",
    "generation_diagnostics",
    "prune_snapshots",
    "recognized_artifacts",
    "transaction",
]
