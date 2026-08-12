#!/usr/bin/env python3
"""Build the self-contained Stash Curator plugin archive.

The compiled core (`curator-core`) ships inside the zip as per-arch
binaries — the binary serves the whole raw-plugin interface (every operation,
task mode, and the entity-sync hook) and the model-build kernels, so no
Python runtime ships. The only non-binary runtime resource is the explanation
catalog (`curator/explanations/realizations.json`, read from disk by the
binary). Go is a build-time dependency for packaging; the binaries use the
native mattn/go-sqlite3 driver (CGO_ENABLED=1, SQLite amalgamation compiled
in), and cross-compile through `zig cc`, so a single machine (with Go +
zig on PATH) cross-compiles every shipped platform.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "stash-curator.zip"

# Shipped platforms mirror Stash's own release matrix (no 32-bit, no
# windows-arm64). Binary names use Go's GOOS/GOARCH naming; the resolver in
# curator/core.py picks the matching one at runtime.
SHIPPED_PLATFORMS = (
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("windows", "amd64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
)

# C cross-compiler per target: zig cc with the target triple. Linux builds
# against musl for fully static binaries (no glibc floor); darwin uses zig's
# bundled libSystem plus the tbd stubs under scripts/zig/ (Go's darwin cgo
# runtime links -lresolv and the CoreFoundation/Security frameworks for the
# TLS root store; the stubs satisfy the link, dyld resolves them on the
# user's Mac); windows links mingw statically.
ZIG_CC = {
    ("linux", "amd64"): "zig cc -target x86_64-linux-musl",
    ("linux", "arm64"): "zig cc -target aarch64-linux-musl",
    ("windows", "amd64"): "zig cc -target x86_64-windows-gnu",
    ("darwin", "amd64"): "zig cc -target x86_64-macos",
    ("darwin", "arm64"): "zig cc -target aarch64-macos",
}

# The darwin link shims: -lresolv plus the CoreFoundation/Security framework
# stubs, satisfied from scripts/zig/.
ZIG_SHIM_DIR = ROOT / "scripts" / "zig"


def version() -> str:
    """Read the single version source (pyproject.toml)."""
    with (ROOT / "pyproject.toml").open("rb") as source:
        return str(tomllib.load(source)["project"]["version"])


def core_binary_name(goos: str, goarch: str) -> str:
    suffix = ".exe" if goos == "windows" else ""
    return f"curator-core-{goos}-{goarch}{suffix}"


def _core_binary_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    sources = [
        ROOT / "pyproject.toml",
        ROOT / "core" / "go.mod",
        ROOT / "core" / "go.sum",
        *sorted((ROOT / "core").glob("*.go")),
        *sorted((ROOT / "scripts" / "zig").rglob("*")),
    ]
    newest = max(source.stat().st_mtime for source in sources)
    return path.stat().st_mtime >= newest


def core_binaries() -> list[Path]:
    """Build (or reuse) the shipped curator-core binaries under core/bin/.

    The five targets are independent cgo builds (each compiles the SQLite
    amalgamation for its own target triple), so they run concurrently on a
    small thread pool; the Go build cache is concurrency-safe and dedupes
    the per-target C compile across runs.
    """
    if shutil.which("go") is None:
        raise RuntimeError(
            "packaging the plugin requires the Go toolchain (install Go, then see core/README.md)"
        )
    if shutil.which("zig") is None:
        raise RuntimeError(
            "packaging the plugin requires zig (ziglang.org) as the C cross-compiler "
            "for the mattn sqlite driver (CGO_ENABLED=1); install it and put it on PATH"
        )
    plugin_version = version()
    pending: list[tuple[tuple[str, str], Path, dict[str, str]]] = []
    for goos, goarch in SHIPPED_PLATFORMS:
        target = ROOT / "core" / "bin" / core_binary_name(goos, goarch)
        if _core_binary_fresh(target):
            continue
        env = dict(
            os.environ,
            CGO_ENABLED="1",
            GOOS=goos,
            GOARCH=goarch,
            CC=ZIG_CC[(goos, goarch)],
        )
        if goos == "darwin":
            env["CGO_LDFLAGS"] = f"-L{ZIG_SHIM_DIR} -F{ZIG_SHIM_DIR}"
        pending.append(((goos, goarch), target, env))

    def build_one(item: tuple[Path, dict[str, str]]) -> None:
        target, env = item
        subprocess.run(
            [
                "go",
                "build",
                "-tags",
                "sqlite_dbstat",
                "-trimpath",
                "-ldflags",
                f"-s -w -X main.coreVersion={plugin_version}",
                "-o",
                str(target),
                ".",
            ],
            cwd=ROOT / "core",
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    if pending:
        with ThreadPoolExecutor(max_workers=min(len(pending), os.cpu_count() or 2)) as pool:
            list(pool.map(build_one, pending))

    return [
        ROOT / "core" / "bin" / core_binary_name(goos, goarch) for goos, goarch in SHIPPED_PLATFORMS
    ]


def build(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    plugin_version = version()
    binaries = core_binaries()
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary) / "stash-curator"
        shutil.copytree(
            ROOT / "plugin",
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data", "backend.py"),
        )
        # The binary is self-contained; the only runtime resource from the
        # Python package is the explanation catalog the renderer reads from
        # disk (core/explanations_render.go loadCatalog).
        realizations = ROOT / "curator" / "explanations" / "realizations.json"
        (staging / "curator" / "explanations").mkdir(parents=True)
        shutil.copy2(realizations, staging / "curator" / "explanations" / realizations.name)
        # Keep the plugin definition's version in lockstep with the index.
        manifest = staging / "stash-curator.yml"
        manifest.write_text(
            re.sub(
                r"(?m)^version: .*$",
                f"version: {plugin_version}",
                manifest.read_text(encoding="utf-8"),
                count=1,
            ),
            encoding="utf-8",
        )
        shutil.copy2(ROOT / "LICENSE", staging / "LICENSE")
        for binary in binaries:
            shutil.copy2(binary, staging / binary.name)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging))
    digest = sha256(output.read_bytes()).hexdigest()
    (output.parent / "index.yml").write_text(
        "\n".join(
            (
                "- id: stash-curator",
                "  name: Stash Curator",
                f"  version: {plugin_version}",
                f"  date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}",
                f"  path: {output.name}",
                f"  sha256: {digest}",
                "  metadata:",
                "    description: Navigate your library, guided by your taste.",
                "",
            )
        ),
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    print(build())
