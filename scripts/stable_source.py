"""Assemble the regular plugin source from the latest release of each plugin.

Curator and Auto Seek are released separately: a Curator release (tag vX.Y.Z)
attaches Curator's archives and indexes, an Auto Seek release (tag
auto-seek-vX.Y.Z) attaches auto-seek.zip and its one entry in
auto-seek-index.yml. The published indexes are Curator's, with their Auto Seek
entry replaced by the latest Auto Seek release's, so each plugin keeps the date
of its own release and Stash offers an update only for the plugin that changed.

Releases from before the split attached auto-seek.zip next to Curator's
archives; until the first Auto Seek release, that copy is used.

usage: stable_source.py OUTPUT_DIR   (needs the gh CLI and GH_TOKEN)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

AUTO_SEEK_PREFIX = "auto-seek-v"
AUTO_SEEK_INDEX = "auto-seek-index.yml"

# download(tag, folder, patterns): fetch a release's matching assets into folder.
Download = Callable[[str, Path, tuple[str, ...]], None]


def entries(index: str) -> list[str]:
    """An index split into its plugin entries, each ending with a newline."""
    parts = re.split(r"(?m)^(?=- id: )", index)
    return [part if part.endswith("\n") else part + "\n" for part in parts if part.strip()]


def field(entry: str, name: str) -> str:
    match = re.search(rf"(?m)^(?:- |  ){name}: (.+)$", entry)
    if match is None:
        raise ValueError(f"index entry has no {name}")
    return match.group(1).strip()


def merge(index: str, auto_seek_entry: str) -> str:
    """Curator's index with its Auto Seek entry replaced."""
    kept = [entry for entry in entries(index) if field(entry, "id") != "auto-seek"]
    return "".join(kept) + entries(auto_seek_entry)[0]


def intact(folder: Path, entry: str) -> bool:
    """The entry's archive is in folder with the checksum the entry names."""
    path = folder / field(entry, "path")
    return path.is_file() and sha256(path.read_bytes()).hexdigest() == field(entry, "sha256")


def curator_release(tags: list[str], download: Download, scratch: Path) -> Path | None:
    """The folder of the newest Curator release whose archives all match its
    indexes (a release whose upload failed half-way is skipped)."""
    for tag in (tag for tag in tags if not tag.startswith(AUTO_SEEK_PREFIX)):
        folder = scratch / tag
        folder.mkdir(parents=True)
        download(tag, folder, ("stash-curator*.zip", "auto-seek*.zip", "index*.yml"))
        indexes = sorted(folder.glob("index*.yml"))
        if (folder / "index.yml").is_file() and all(
            intact(folder, entry)
            for index in indexes
            for entry in entries(index.read_text("utf-8"))
            if field(entry, "id") != "auto-seek"
        ):
            return folder
    return None


def auto_seek_release(
    tags: list[str], download: Download, scratch: Path
) -> tuple[Path, str] | None:
    """The newest intact Auto Seek release: its folder and index entry. Falls
    back to the copy that releases from before the split shipped with Curator."""
    for tag in (tag for tag in tags if tag.startswith(AUTO_SEEK_PREFIX)):
        folder = scratch / tag
        folder.mkdir(parents=True)
        download(tag, folder, ("auto-seek.zip", AUTO_SEEK_INDEX))
        index = folder / AUTO_SEEK_INDEX
        if index.is_file():
            entry = entries(index.read_text("utf-8"))[0]
            if intact(folder, entry):
                return folder, entry
    for tag in (tag for tag in tags if not tag.startswith(AUTO_SEEK_PREFIX)):
        folder = scratch / tag
        if not folder.exists():  # older than the Curator release in use
            folder.mkdir(parents=True)
            download(tag, folder, ("auto-seek*.zip", "index.yml"))
        index = folder / "index.yml"
        if not index.is_file():
            continue
        for entry in entries(index.read_text("utf-8")):
            if field(entry, "id") == "auto-seek" and intact(folder, entry):
                return folder, entry
    return None


def assemble(output: Path, tags: list[str], download: Download) -> str:
    """Write the regular plugin source into output; returns which releases it
    came from."""
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        curator = curator_release(tags, download, scratch)
        if curator is None:
            raise RuntimeError("No recent Curator release has a complete plugin source")
        found = auto_seek_release(tags, download, scratch)
        if found is None:
            raise RuntimeError("No recent release has an intact Auto Seek archive")
        auto_seek, auto_seek_entry = found
        output.mkdir(parents=True, exist_ok=True)
        for archive in curator.glob("stash-curator*.zip"):
            shutil.copy2(archive, output / archive.name)
        shutil.copy2(auto_seek / field(auto_seek_entry, "path"), output)
        for index in curator.glob("index*.yml"):
            (output / index.name).write_text(
                merge(index.read_text("utf-8"), auto_seek_entry), encoding="utf-8"
            )
        return f"Curator from {curator.name}, Auto Seek from {auto_seek.name}"


def gh_download(tag: str, folder: Path, patterns: tuple[str, ...]) -> None:
    arguments = [arg for pattern in patterns for arg in ("--pattern", pattern)]
    # A release lacking some of the patterns is judged by what did arrive.
    subprocess.run(
        ["gh", "release", "download", tag, "--dir", str(folder), *arguments],
        check=False,
        capture_output=True,
    )


def release_tags(limit: int = 30) -> list[str]:
    """Published release tags, newest first."""
    listed = subprocess.run(
        ["gh", "release", "list", "--limit", str(limit), "--json", "tagName,isDraft"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [release["tagName"] for release in json.loads(listed) if not release["isDraft"]]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(assemble(Path(sys.argv[1]), release_tags(), gh_download))
