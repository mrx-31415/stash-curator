from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from scripts import stable_source


def entry(plugin: str, folder: Path, name: str, body: bytes, date: str) -> str:
    (folder / name).write_bytes(body)
    return (
        f"- id: {plugin}\n  name: {plugin}\n  version: 1\n  date: {date}\n"
        f"  path: {name}\n  sha256: {sha256(body).hexdigest()}\n  metadata:\n"
        '    description: "a: b"\n'
    )


@pytest.fixture
def releases(tmp_path: Path):
    """Fake GitHub releases: tag -> folder of assets."""
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


def test_indexes_carry_the_latest_auto_seek_release(tmp_path, releases) -> None:
    release, download = releases
    seek = release("auto-seek-v0.3.0")
    seek_entry = entry("auto-seek", seek, "auto-seek.zip", b"seek 3", "2026-01-03")
    (seek / "auto-seek-index.yml").write_text(seek_entry)
    curator = release("v0.57.0")
    curator_entry = entry("stash-curator", curator, "stash-curator.zip", b"c57", "2026-01-05")
    unreleased = (curator / "auto-seek-next.zip", b"main's unreleased auto seek")
    (curator / "index.yml").write_text(
        curator_entry + entry("auto-seek", curator, unreleased[0].name, unreleased[1], "2026-01-05")
    )
    unreleased[0].unlink()  # Curator releases no longer attach Auto Seek

    source = stable_source.assemble(tmp_path / "out", ["v0.57.0", "auto-seek-v0.3.0"], download)

    out = tmp_path / "out"
    assert source == "Curator from v0.57.0, Auto Seek from auto-seek-v0.3.0"
    assert (out / "index.yml").read_text() == curator_entry + seek_entry
    assert (out / "auto-seek.zip").read_bytes() == b"seek 3"
    assert (out / "stash-curator.zip").read_bytes() == b"c57"


def test_before_any_auto_seek_release_the_copy_shipped_with_curator_is_used(
    tmp_path, releases
) -> None:
    release, download = releases
    newest = release("v0.57.0")  # after the split: no auto-seek.zip attached
    curator_entry = entry("stash-curator", newest, "stash-curator.zip", b"c57", "2026-01-05")
    (newest / "index.yml").write_text(curator_entry)
    older = release("v0.56.0")  # before the split: both plugins attached
    old_seek = entry("auto-seek", older, "auto-seek.zip", b"seek in 56", "2026-01-01")
    (older / "index.yml").write_text(
        entry("stash-curator", older, "stash-curator.zip", b"c56", "2026-01-01") + old_seek
    )

    stable_source.assemble(tmp_path / "out", ["v0.57.0", "v0.56.0"], download)

    out = tmp_path / "out"
    assert (out / "index.yml").read_text() == curator_entry + old_seek
    assert (out / "auto-seek.zip").read_bytes() == b"seek in 56"


def test_a_release_still_uploading_is_skipped(tmp_path, releases) -> None:
    release, download = releases
    partial = release("v0.58.0")
    (partial / "index.yml").write_text(
        entry("stash-curator", partial, "stash-curator.zip", b"c58", "2026-01-09")
    )
    (partial / "stash-curator.zip").unlink()
    seek = release("auto-seek-v0.4.0")
    (seek / "auto-seek-index.yml").write_text(
        entry("auto-seek", seek, "auto-seek.zip", b"seek 4", "2026-01-08")
    )
    (seek / "auto-seek.zip").write_bytes(b"truncated")
    good_seek = release("auto-seek-v0.3.0")
    good_entry = entry("auto-seek", good_seek, "auto-seek.zip", b"seek 3", "2026-01-03")
    (good_seek / "auto-seek-index.yml").write_text(good_entry)
    curator = release("v0.57.0")
    curator_entry = entry("stash-curator", curator, "stash-curator.zip", b"c57", "2026-01-05")
    (curator / "index.yml").write_text(curator_entry)

    source = stable_source.assemble(
        tmp_path / "out",
        ["v0.58.0", "auto-seek-v0.4.0", "auto-seek-v0.3.0", "v0.57.0"],
        download,
    )

    assert source == "Curator from v0.57.0, Auto Seek from auto-seek-v0.3.0"
    assert (tmp_path / "out" / "index.yml").read_text() == curator_entry + good_entry
