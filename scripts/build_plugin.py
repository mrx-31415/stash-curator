#!/usr/bin/env python3
"""Build the self-contained Stash Curator plugin archive."""

from __future__ import annotations

import re
import shutil
import tempfile
import tomllib
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "stash-curator.zip"


def version() -> str:
    """Read the single version source (pyproject.toml)."""
    with (ROOT / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]["version"]


def build(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    plugin_version = version()
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
