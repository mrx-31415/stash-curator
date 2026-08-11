#!/usr/bin/env python3
"""Resolve the platform's curator-core binary and exec it as the backend.

Stash's plugin `exec` list is static and platform-agnostic (one yml per
plugin), so the swap to the compiled backend goes through this tiny shim:
it maps the running platform to the shipped per-arch binary name
(curator-core-<goos>-<goarch>, built by scripts/build_plugin.py), then
execs it with the same argv contract backend.py serves — argv[1] = plugin
dir, argv[2] = optional task/hook mode.

The shim imports only the standard library and does no work beyond the
exec, so its own spawn cost stays in the tens of milliseconds instead of
backend.py's full import (~700 ms). When the binary is absent for this
platform (never in the shipped zip, but possible for hand-installed
plugins), the shim falls back to the bundled backend.py. Every operation,
task mode, and the entity-sync hook mode is native in the binary now (Slice
4); backend.py is retained in the zip purely as this launcher-level
fallback for platforms without a shipped binary, pending a decision to
remove the packaged Python.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

PLUGIN_DIR = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.resolve()


def _binary_name() -> str:
    """The shipped per-arch binary name for this platform (Go GOOS/GOARCH
    naming, mirroring curator/core.py's resolver)."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    suffix = ".exe" if system == "windows" else ""
    return f"curator-core-{system}-{arch}{suffix}"


def main() -> None:
    binary = PLUGIN_DIR / _binary_name()
    args = [str(binary), str(PLUGIN_DIR), *sys.argv[2:]]
    if binary.is_file() and os.access(binary, os.X_OK):
        os.execv(str(binary), args)
    # No binary for this platform: run the Python backend (unported ops,
    # tasks, and hooks all still work through it).
    os.execv(sys.executable, [sys.executable, str(PLUGIN_DIR / "backend.py"), *args[1:]])


if __name__ == "__main__":
    main()
