"""Command-line entry point for Stash Curator."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from pathlib import Path

from curator import __version__
from curator.graphql import GraphQLClient
from curator.storage import MigrationRunner, backup_database, connect_database
from curator.storage.migrations import MigrationStatus
from curator.sync import SyncService
from curator.sync.repository import SyncRepository
from curator.sync.service import probe_capabilities


def _default_database_path() -> Path:
    return Path(os.environ.get("CURATOR_DB", "data/curator.sqlite3"))


def _default_stash_url() -> str | None:
    return os.environ.get("STASH_URL")


def _status_payload(status: MigrationStatus) -> dict[str, object]:
    return {
        "current_version": status.current_version,
        "latest_version": status.latest_version,
        "applied_versions": list(status.applied_versions),
        "pending_versions": list(status.pending_versions),
    }


def _print_result(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser."""
    parser = argparse.ArgumentParser(
        prog="curator",
        description="Navigate your Stash library, guided by your taste.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db",
        type=Path,
        default=_default_database_path(),
        help="SQLite path (default: CURATOR_DB or data/curator.sqlite3)",
    )
    parser.add_argument(
        "--stash-url",
        default=_default_stash_url(),
        help="Stash base or GraphQL URL (default: STASH_URL)",
    )

    subparsers = parser.add_subparsers(dest="command")
    doctor = subparsers.add_parser("doctor", help="Check the local Curator runtime")
    doctor.add_argument("--json", action="store_true", help="Emit structured JSON")

    sync = subparsers.add_parser("sync", help="Synchronize the read-only Stash cache")
    sync.add_argument("--full", action="store_true", help="Reconcile a complete snapshot")
    sync.add_argument("--page-size", type=int, default=250)
    sync.add_argument("--json", action="store_true", help="Emit structured JSON")

    database = subparsers.add_parser("db", help="Manage Curator's SQLite database")
    db_commands = database.add_subparsers(dest="db_command", required=True)
    status = db_commands.add_parser("status", help="Show schema migration status")
    status.add_argument("--json", action="store_true", help="Emit structured JSON")
    migrate = db_commands.add_parser("migrate", help="Apply pending schema migrations")
    migrate.add_argument("--json", action="store_true", help="Emit structured JSON")
    backup = db_commands.add_parser("backup", help="Create a consistent database backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--overwrite", action="store_true")
    backup.add_argument("--json", action="store_true", help="Emit structured JSON")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        connection = connect_database(args.db)
        try:
            migration_status = MigrationRunner(connection).status()
        finally:
            connection.close()
        result: dict[str, object] = {
            "status": "ok",
            "version": __version__,
            "database": str(args.db),
            "schema_current": migration_status.current_version,
            "schema_latest": migration_status.latest_version,
            "stash": "not_configured",
        }
        if args.stash_url:
            client = GraphQLClient(args.stash_url, api_key=os.environ.get("STASH_API_KEY"))
            capabilities = probe_capabilities(client)
            result["stash"] = "connected"
            result["stash_version"] = capabilities.server_version
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"Stash Curator {__version__}: runtime is ready")
            print(f"Stash: {result['stash']}")
        return 0

    if args.command == "sync":
        if not args.stash_url:
            parser.error("sync requires --stash-url or STASH_URL")
        connection = connect_database(args.db)
        try:
            MigrationRunner(connection).migrate(applied_at_ms=time.time_ns() // 1_000_000)
            client = GraphQLClient(args.stash_url, api_key=os.environ.get("STASH_API_KEY"))
            service = SyncService(
                client,
                SyncRepository(connection),
                page_size=int(args.page_size),
            )
            synced = service.sync(full=bool(args.full))
        finally:
            connection.close()
        _print_result(
            {
                "run_id": synced.run_id,
                "mode": synced.mode,
                "server_version": synced.server_version,
                "resumed": synced.resumed,
                "entity_counts": synced.entity_counts,
            },
            as_json=bool(args.json),
        )
        return 0

    if args.command == "db":
        if args.db_command == "backup":
            connection = connect_database(args.db, readonly=True)
            try:
                destination = backup_database(
                    connection,
                    args.destination,
                    overwrite=bool(args.overwrite),
                )
            finally:
                connection.close()
            _print_result({"backup": str(destination)}, as_json=bool(args.json))
            return 0

        connection = connect_database(args.db)
        try:
            runner = MigrationRunner(connection)
            if args.db_command == "migrate":
                status = runner.migrate(applied_at_ms=time.time_ns() // 1_000_000)
            else:
                status = runner.status()
        finally:
            connection.close()
        _print_result(_status_payload(status), as_json=bool(args.json))
        return 0

    parser.print_help()
    return 0


def main() -> None:
    """Console-script entry point."""
    raise SystemExit(run())
