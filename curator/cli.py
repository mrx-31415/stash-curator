"""Command-line entry point for Stash Curator."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from curator import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser."""
    parser = argparse.ArgumentParser(
        prog="curator",
        description="Navigate your Stash library, guided by your taste.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    doctor = subparsers.add_parser("doctor", help="Check the local Curator runtime")
    doctor.add_argument("--json", action="store_true", help="Emit structured JSON")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        result = {"status": "ok", "version": __version__}
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"Stash Curator {__version__}: foundation runtime is ready")
        return 0

    parser.print_help()
    return 0


def main() -> None:
    """Console-script entry point."""
    raise SystemExit(run())
