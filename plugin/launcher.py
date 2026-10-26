#!/usr/bin/env python3
"""Resolve the platform's curator-core binary and exec it as the backend.

Stash's plugin `exec` list is static and platform-agnostic (one yml per
plugin), so the compiled backend goes through this tiny shim: it maps the
running platform to the shipped per-arch binary name
(curator-core-<goos>-<goarch>, built by scripts/build_plugin.py), then
execs it with the same argv contract the binary serves — argv[1] = plugin
dir, argv[2] = optional task/hook mode.

Every call pays the interpreter's startup before the binary runs, so the
shim runs with `-S` and imports nothing beyond os and sys (the platform
module alone used to cost more than the rest of the shim). If the binary is
absent for this platform (never in the shipped zip, but possible for
hand-installed plugins), the shim fails with a clear reinstall message
instead of half-running.
"""

import os
import sys

PLUGIN_DIR = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(__file__))


def _binary_name() -> str:
    """The shipped per-arch binary name for this platform (Go GOOS/GOARCH
    naming, mirroring curator/core.py's resolver)."""
    if sys.platform == "win32":
        system = "windows"
        machine = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get(
            "PROCESSOR_ARCHITECTURE", ""
        )
    else:
        system = "darwin" if sys.platform == "darwin" else sys.platform.rstrip("0123456789")
        machine = os.uname().machine
    machine = machine.lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    suffix = ".exe" if system == "windows" else ""
    return f"curator-core-{system}-{arch}{suffix}"


def main() -> None:
    binary = os.path.join(PLUGIN_DIR, _binary_name())
    args = [binary, PLUGIN_DIR, *sys.argv[2:]]
    if os.path.isfile(binary) and os.access(binary, os.X_OK):
        os.execv(binary, args)
    sys.stderr.write(
        f"stash-curator: no curator-core binary for this platform ({_binary_name()}); "
        "reinstall the plugin from the index\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
