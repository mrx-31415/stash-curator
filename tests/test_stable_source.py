from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from scripts import stable_source

SEEK, INCOGNITO = (urls for urls in stable_source.COMPANIONS.values())


def entry(plugin: str, path: str, body: bytes, date: str, version: str = "1") -> str:
    return (
        f"- id: {plugin}\n  name: {plugin}\n  version: {version}\n  date: {date}\n"
        f"  path: {path}\n  sha256: {sha256(body).hexdigest()}\n  metadata:\n"
        '    description: "a: b"\n'
    )


def write(folder: Path, plugin: str, name: str, body: bytes, date: str) -> str:
    (folder / name).write_bytes(body)
    return entry(plugin, name, body, date)


@pytest.fixture
def releases(tmp_path: Path):
    """Fake Curator GitHub releases: tag -> folder of assets."""
    store = tmp_path / "releases"

    def release(tag: str) -> Path:
        folder = store / tag
        folder.mkdir(parents=True)
        return folder

    def download(tag: str, folder: Path, patterns: tuple[str, ...]) -> None:
        for path in (store / tag).iterdir():
            if any(path.match(pattern) for pattern in patterns):
                shutil.copy2(path, folder / path.name)

    return release, download


def web(files: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url not in files:
            raise OSError(f"404 {url}")
        return files[url]

    return fetch


def companions(channel: int) -> tuple[dict[str, bytes], str]:
    """Both companions published at their channel's URLs; returns the files and
    the entries Curator's indexes should end with."""
    seek_index, incognito_index = SEEK[channel], INCOGNITO[channel]
    seek = entry("auto-seek", "auto-seek.zip", b"seek", "2026-01-03", "0.3.0")
    incognito = entry("incognito", "incognito.zip", b"inc", "2026-01-04", "1.1.0")
    files = {
        seek_index: seek.encode(),
        seek_index.rsplit("/", 1)[0] + "/auto-seek.zip": b"seek",
        incognito_index: incognito.encode(),
        incognito_index.rsplit("/", 1)[0] + "/incognito.zip": b"inc",
    }
    return files, seek + incognito


def test_regular_source_is_curators_release_plus_each_companions_latest(tmp_path, releases) -> None:
    release, download = releases
    curator = release("v0.58.0")
    curator_entry = write(curator, "stash-curator", "stash-curator.zip", b"c58", "2026-01-05")
    # Curator's index from before the split lists companions it never attached.
    stale = entry("auto-seek", "auto-seek.zip", b"main's", "2026-01-05")
    (curator / "index.yml").write_text(curator_entry + stale)
    files, released = companions(stable_source.STABLE)

    source = stable_source.assemble(
        tmp_path / "out", ["auto-seek-v0.2.0", "v0.58.0"], download, web(files)
    )

    out = tmp_path / "out"
    assert source == "Curator from v0.58.0, auto-seek 0.3.0, incognito 1.1.0"
    assert (out / "index.yml").read_text() == curator_entry + released
    assert (out / "auto-seek.zip").read_bytes() == b"seek"
    assert (out / "incognito.zip").read_bytes() == b"inc"
    assert (out / "stash-curator.zip").read_bytes() == b"c58"


def test_a_curator_release_still_uploading_is_skipped(tmp_path, releases) -> None:
    release, download = releases
    partial = release("v0.58.0")
    (partial / "index.yml").write_text(
        write(partial, "stash-curator", "stash-curator.zip", b"c58", "2026-01-09")
    )
    (partial / "stash-curator.zip").unlink()
    curator = release("v0.57.0")
    curator_entry = write(curator, "stash-curator", "stash-curator.zip", b"c57", "2026-01-05")
    (curator / "index.yml").write_text(curator_entry)
    files, released = companions(stable_source.STABLE)

    source = stable_source.assemble(tmp_path / "out", ["v0.58.0", "v0.57.0"], download, web(files))

    assert source.startswith("Curator from v0.57.0, ")
    assert (tmp_path / "out" / "index.yml").read_text() == curator_entry + released


def test_a_companion_archive_that_does_not_match_fails_the_build(tmp_path) -> None:
    files, _ = companions(stable_source.DEV)
    files[SEEK[stable_source.DEV].rsplit("/", 1)[0] + "/auto-seek.zip"] = b"truncated"
    (tmp_path / "index.yml").write_text(entry("stash-curator", "x.zip", b"x", "2026-01-01"))
    with pytest.raises(RuntimeError, match="does not match"):
        stable_source.add_companions(tmp_path, stable_source.DEV, web(files))


def test_dev_source_gets_each_companions_dev_build_in_every_index(tmp_path) -> None:
    curator_entry = entry("stash-curator", "stash-curator.zip", b"dev", "2026-01-06")
    for name in ("index.yml", "index-linux-amd64.yml"):
        (tmp_path / name).write_text(curator_entry)
    files, released = companions(stable_source.DEV)

    added = stable_source.add_companions(tmp_path, stable_source.DEV, web(files))

    assert added == "auto-seek 0.3.0, incognito 1.1.0"
    for name in ("index.yml", "index-linux-amd64.yml"):
        assert (tmp_path / name).read_text() == curator_entry + released
