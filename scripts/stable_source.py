"""Assemble the regular plugin source from the latest release of each plugin.

Curator and its companion plugins (Auto Seek, Incognito) are released
separately: a Curator release (tag vX.Y.Z) attaches Curator's archives and
indexes, a companion release (tag <id>-vX.Y.Z) attaches <id>.zip and its one
entry in <id>-index.yml. The published indexes are Curator's, with each
companion entry replaced by that companion's latest release, so each plugin
keeps the date of its own release and Stash offers an update only for the
plugin that changed. A companion that was never released is left out.

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

# Companion plugin ids and names, in index order (scripts/build_plugin.py COMPANIONS).
COMPANIONS = {"auto-seek": "Auto Seek", "incognito": "Incognito"}
# Companions that Curator releases from before the split also attached.
SHIPPED_WITH_CURATOR = ("auto-seek",)

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


def companion_tag(tag: str) -> str | None:
    """The companion a release tag belongs to, or None for Curator's own."""
    return next((plugin for plugin in COMPANIONS if tag.startswith(f"{plugin}-v")), None)


def merge(index: str, companion_entries: dict[str, str]) -> str:
    """Curator's index with its companion entries replaced by the released ones."""
    kept = [entry for entry in entries(index) if field(entry, "id") not in COMPANIONS]
    released = [
        entries(companion_entries[plugin])[0]
        for plugin in COMPANIONS
        if plugin in companion_entries
    ]
    return "".join(kept + released)


def intact(folder: Path, entry: str) -> bool:
    """The entry's archive is in folder with the checksum the entry names."""
    path = folder / field(entry, "path")
    return path.is_file() and sha256(path.read_bytes()).hexdigest() == field(entry, "sha256")


def curator_release(tags: list[str], download: Download, scratch: Path) -> Path | None:
    """The folder of the newest Curator release whose archives all match its
    indexes (a release whose upload failed half-way is skipped)."""
    for tag in (tag for tag in tags if companion_tag(tag) is None):
        folder = scratch / tag
        folder.mkdir(parents=True)
        legacy = tuple(f"{plugin}*.zip" for plugin in SHIPPED_WITH_CURATOR)
        download(tag, folder, ("stash-curator*.zip", *legacy, "index*.yml"))
        indexes = sorted(folder.glob("index*.yml"))
        if (folder / "index.yml").is_file() and all(
            intact(folder, entry)
            for index in indexes
            for entry in entries(index.read_text("utf-8"))
            if field(entry, "id") not in COMPANIONS
        ):
            return folder
    return None


def companion_release(
    plugin: str, tags: list[str], download: Download, scratch: Path
) -> tuple[Path, str] | None:
    """The newest intact release of a companion: its folder and index entry.
    Auto Seek falls back to the copy releases from before the split shipped
    with Curator."""
    index_name = f"{plugin}-index.yml"
    for tag in (tag for tag in tags if companion_tag(tag) == plugin):
        folder = scratch / tag
        folder.mkdir(parents=True)
        download(tag, folder, (f"{plugin}.zip", index_name))
        index = folder / index_name
        if index.is_file():
            entry = entries(index.read_text("utf-8"))[0]
            if intact(folder, entry):
                return folder, entry
    if plugin not in SHIPPED_WITH_CURATOR:
        return None
    for tag in (tag for tag in tags if companion_tag(tag) is None):
        folder = scratch / tag
        if not folder.exists():  # older than the Curator release in use
            folder.mkdir(parents=True)
            download(tag, folder, (f"{plugin}*.zip", "index.yml"))
        index = folder / "index.yml"
        if not index.is_file():
            continue
        for entry in entries(index.read_text("utf-8")):
            if field(entry, "id") == plugin and intact(folder, entry):
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
        found: dict[str, tuple[Path, str]] = {}
        for plugin, name in COMPANIONS.items():
            release = companion_release(plugin, tags, download, scratch)
            if release is not None:
                found[plugin] = release
            elif plugin in SHIPPED_WITH_CURATOR or any(
                companion_tag(tag) == plugin for tag in tags
            ):
                raise RuntimeError(f"No recent release has an intact {name} archive")
        output.mkdir(parents=True, exist_ok=True)
        for archive in curator.glob("stash-curator*.zip"):
            shutil.copy2(archive, output / archive.name)
        for folder, entry in found.values():
            shutil.copy2(folder / field(entry, "path"), output)
        released = {plugin: entry for plugin, (_, entry) in found.items()}
        for index in curator.glob("index*.yml"):
            (output / index.name).write_text(
                merge(index.read_text("utf-8"), released), encoding="utf-8"
            )
        sources = [f"Curator from {curator.name}"]
        sources += [
            f"{COMPANIONS[plugin]} from {folder.name}" for plugin, (folder, _) in found.items()
        ]
        return ", ".join(sources)


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
