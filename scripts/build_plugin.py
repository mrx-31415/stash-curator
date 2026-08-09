#!/usr/bin/env python3
"""Build the self-contained Stash Curator plugin archive.

The compiled core (`curator-core`, optional acceleration) ships inside the zip
as per-arch binaries — one zip, the runtime selects the matching binary and
falls back to numpy / pure Python when none exists. Go is a build-time
dependency for packaging; the binaries are static (CGO_ENABLED=0, modernc
sqlite), so a single machine cross-compiles every shipped platform.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
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
    ]
    newest = max(source.stat().st_mtime for source in sources)
    return path.stat().st_mtime >= newest


def core_binaries() -> list[Path]:
    """Build (or reuse) the shipped curator-core binaries under core/bin/."""
    if shutil.which("go") is None:
        raise RuntimeError(
            "packaging the plugin requires the Go toolchain (install Go, then see core/README.md)"
        )
    plugin_version = version()
    binaries: list[Path] = []
    for goos, goarch in SHIPPED_PLATFORMS:
        target = ROOT / "core" / "bin" / core_binary_name(goos, goarch)
        if not _core_binary_fresh(target):
            env = dict(
                os.environ,
                CGO_ENABLED="0",
                GOOS=goos,
                GOARCH=goarch,
            )
            subprocess.run(
                [
                    "go",
                    "build",
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
        binaries.append(target)
    return binaries


def build(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    plugin_version = version()
    binaries = core_binaries()
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary) / "stash-curator"
        shutil.copytree(
            ROOT / "plugin",
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data"),
        )
        shutil.copytree(
            ROOT / "curator",
            staging / "curator",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
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
