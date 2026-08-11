#!/usr/bin/env python3
"""Resolve the platform's curator-core binary and exec it as the backend.

Stash's plugin `exec` list is static and platform-agnostic (one yml per
plugin), so the compiled backend goes through this tiny shim: it maps the
running platform to the shipped per-arch binary name
(curator-core-<goos>-<goarch>, built by scripts/build_plugin.py), then
execs it with the same argv contract the binary serves — argv[1] = plugin
dir, argv[2] = optional task/hook mode.

The shim imports only the standard library and does no work beyond the
exec, so its own spawn cost stays in the tens of milliseconds. Every
operation, task mode, and the entity-sync hook mode is native in the
binary; no Python runtime ships in the plugin. If the binary is absent for
this platform (never in the shipped zip, but possible for hand-installed
plugins), the shim fails with a clear reinstall message instead of
half-running.
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
    sys.stderr.write(
        f"stash-curator: no curator-core binary for this platform ({_binary_name()}); "
        "reinstall the plugin from the index\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
