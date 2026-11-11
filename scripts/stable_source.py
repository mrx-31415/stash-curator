"""Assemble Curator's plugin sources, with its companion plugins from their own
repositories.

Curator's releases (tags vX.Y.Z) attach its archives and indexes. Auto Seek
and Incognito are developed and released in their own repositories
(mrx-31415/stash-auto-seek, mrx-31415/stash-incognito), and the plugin hub
(mrx-31415/stash-plugins) serves all of them from one source. Curator's own
sources keep listing both, so installations made from them keep receiving
their updates:

    stable_source.py OUTPUT_DIR
        the regular source: Curator's archives and indexes from its latest
        complete release, plus each companion's latest release (needs the gh
        CLI and GH_TOKEN)

    stable_source.py --dev DIR
        add each companion's dev build to the dev source already built in DIR
        (scripts/build_plugin.py --dev)

Every index lists Curator's entry followed by the companions'; each companion
entry keeps its own release's date, so Stash offers an update only for the
plugin that changed. A companion archive is copied in only when it matches its
index's sha256.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

# Companion plugin id -> (stable index, dev index), in index order.
COMPANIONS = {
    "auto-seek": (
        "https://github.com/mrx-31415/stash-auto-seek/releases/latest/download/auto-seek-index.yml",
        "https://mrx-31415.github.io/stash-auto-seek/dev/index.yml",
    ),
    "incognito": (
        "https://github.com/mrx-31415/stash-incognito/releases/latest/download/incognito-index.yml",
        "https://mrx-31415.github.io/stash-incognito/dev/index.yml",
    ),
}
STABLE, DEV = 0, 1

# download(tag, folder, patterns): fetch a Curator release's matching assets into folder.
Download = Callable[[str, Path, tuple[str, ...]], None]
# fetch(url): the bytes at url.
Fetch = Callable[[str], bytes]


def entries(index: str) -> list[str]:
    """An index split into its plugin entries, each ending with a newline."""
    parts = re.split(r"(?m)^(?=- id: )", index)
    return [part if part.endswith("\n") else part + "\n" for part in parts if part.strip()]


def field(entry: str, name: str) -> str:
    match = re.search(rf"(?m)^(?:- |  ){name}: (.+)$", entry)
    if match is None:
        raise ValueError(f"index entry has no {name}")
    return match.group(1).strip()


def intact(folder: Path, entry: str) -> bool:
    """The entry's archive is in folder with the checksum the entry names."""
    path = folder / field(entry, "path")
    return path.is_file() and sha256(path.read_bytes()).hexdigest() == field(entry, "sha256")


def curator_release(tags: list[str], download: Download, scratch: Path) -> Path | None:
    """The folder of the newest Curator release whose archives all match its
    indexes (a release whose upload failed half-way is skipped). Companion
    entries in its indexes are ignored: Curator releases never attached them."""
    for tag in (tag for tag in tags if re.fullmatch(r"v\d+\.\d+\.\d+", tag)):
        folder = scratch / tag
        folder.mkdir(parents=True)
        download(tag, folder, ("stash-curator*.zip", "index*.yml"))
        indexes = sorted(folder.glob("index*.yml"))
        if (folder / "index.yml").is_file() and all(
            intact(folder, entry)
            for index in indexes
            for entry in entries(index.read_text("utf-8"))
            if field(entry, "id") not in COMPANIONS
        ):
            return folder
    return None


def companion(plugin: str, index_url: str, folder: Path, fetch: Fetch) -> str:
    """Fetch a companion's entry and archive into folder; returns the entry,
    pointing at the archive's name in folder."""
    found = [e for e in entries(fetch(index_url).decode("utf-8")) if field(e, "id") == plugin]
    if not found:
        raise RuntimeError(f"{index_url} lists no {plugin}")
    entry = found[0]
    path = field(entry, "path")
    name = PurePosixPath(path).name
    if not name.endswith(".zip") or name.startswith("stash-curator"):
        raise RuntimeError(f"{index_url}: unexpected archive {path}")
    data = fetch(urljoin(index_url, path))
    if sha256(data).hexdigest() != field(entry, "sha256"):
        raise RuntimeError(f"{plugin}'s archive does not match {index_url}")
    (folder / name).write_bytes(data)
    return re.sub(r"(?m)^  path: .+$", lambda _: f"  path: {name}", entry, count=1)


def add_companions(folder: Path, channel: int, fetch: Fetch) -> str:
    """Replace the companion entries in every index in folder with each
    companion's own, from its latest release (STABLE) or dev build (DEV).
    Returns which versions were added."""
    added = {
        plugin: companion(plugin, urls[channel], folder, fetch)
        for plugin, urls in COMPANIONS.items()
    }
    for index in folder.glob("index*.yml"):
        kept = [e for e in entries(index.read_text("utf-8")) if field(e, "id") not in COMPANIONS]
        index.write_text("".join(kept + list(added.values())), encoding="utf-8")
    return ", ".join(f"{plugin} {field(entry, 'version')}" for plugin, entry in added.items())


def assemble(output: Path, tags: list[str], download: Download, fetch: Fetch) -> str:
    """Write the regular plugin source into output; returns where it came from."""
    with tempfile.TemporaryDirectory() as temporary:
        curator = curator_release(tags, download, Path(temporary))
        if curator is None:
            raise RuntimeError("No recent Curator release has a complete plugin source")
        output.mkdir(parents=True, exist_ok=True)
        for path in [*curator.glob("stash-curator*.zip"), *curator.glob("index*.yml")]:
            shutil.copy2(path, output / path.name)
    return f"Curator from {curator.name}, {add_companions(output, STABLE, fetch)}"


def http_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "stash-curator-pages"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


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
    if len(sys.argv) == 3 and sys.argv[1] == "--dev":
        print(add_companions(Path(sys.argv[2]), DEV, http_fetch))
    elif len(sys.argv) == 2:
        print(assemble(Path(sys.argv[1]), release_tags(), gh_download, http_fetch))
    else:
        sys.exit(__doc__)
