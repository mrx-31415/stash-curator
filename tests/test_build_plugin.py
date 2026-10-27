from __future__ import annotations

import os
import subprocess
import zipfile
from hashlib import sha256
from pathlib import Path

from scripts import build_plugin


def test_single_platform_build_packages_only_that_binary(tmp_path: Path, monkeypatch) -> None:
    requested = []

    def binaries(platforms):
        requested.append(platforms)
        paths = []
        for goos, goarch in platforms:
            path = tmp_path / build_plugin.core_binary_name(goos, goarch)
            path.write_bytes(b"core")
            paths.append(path)
        return paths

    monkeypatch.setattr(build_plugin, "core_binaries", binaries)
    output = build_plugin.build(
        tmp_path / "dist" / "stash-curator.zip", platforms=(("linux", "amd64"),)
    )
    assert requested == [(("linux", "amd64"),)]
    with zipfile.ZipFile(output) as archive:
        cores = [name for name in archive.namelist() if name.startswith("curator-core-")]
    assert cores == [build_plugin.core_binary_name("linux", "amd64")]
    assert sorted(path.name for path in output.parent.glob("index*.yml")) == [
        "index-linux-amd64.yml",
        "index.yml",
    ]


def test_platform_archives_keep_runtime_files_and_only_the_matching_binary(
    tmp_path: Path, monkeypatch
) -> None:
    binaries = []
    for goos, goarch in build_plugin.SHIPPED_PLATFORMS:
        binary = tmp_path / build_plugin.core_binary_name(goos, goarch)
        binary.write_bytes(f"{goos}-{goarch}".encode())
        binary.chmod(0o755)
        binaries.append(binary)
    monkeypatch.setattr(build_plugin, "core_binaries", lambda platforms: binaries)
    output = build_plugin.build(tmp_path / "dist" / "stash-curator.zip")
    binary_names = {binary.name for binary in binaries}
    with zipfile.ZipFile(output) as multi:
        common = set(multi.namelist()) - binary_names
        assert {"launcher.py", "stash-curator.yml", "stash-curator.js", "LICENSE"} <= common
        for (goos, goarch), binary in zip(build_plugin.SHIPPED_PLATFORMS, binaries, strict=True):
            archive = output.with_name(f"stash-curator-{goos}-{goarch}.zip")
            with zipfile.ZipFile(archive) as package:
                assert set(package.namelist()) == common | {binary.name}
                for name in common | {binary.name}:
                    assert package.read(name) == multi.read(name)
                    assert package.getinfo(name).external_attr == multi.getinfo(name).external_attr
            index = (output.parent / f"index-{goos}-{goarch}.yml").read_text()
            assert "- id: stash-curator\n" in index
            assert f"  version: {build_plugin.version()}\n" in index
            assert f"  path: {archive.name}\n" in index
            assert f"  sha256: {sha256(archive.read_bytes()).hexdigest()}\n" in index
    index = (output.parent / "index.yml").read_text()
    assert "  path: stash-curator.zip\n" in index
    assert f"sha256: {sha256(output.read_bytes()).hexdigest()}" in index


def test_binary_freshness_ignores_tests_but_tracks_embedded_migrations(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(build_plugin, "ROOT", tmp_path)
    sources = [
        "pyproject.toml",
        "core/go.mod",
        "core/go.sum",
        "core/main.go",
        "core/migrations/0001.sql",
        "scripts/build_plugin.py",
    ]
    for relative in sources:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source")
        os.utime(path, (100, 100))
    binary = tmp_path / "binary"
    binary.write_text("compiled")
    os.utime(binary, (200, 200))
    test = tmp_path / "core/main_test.go"
    test.write_text("test")
    os.utime(test, (300, 300))
    assert build_plugin._core_binary_fresh(binary)

    migration = tmp_path / "core/migrations/0001.sql"
    os.utime(migration, (400, 400))
    assert not build_plugin._core_binary_fresh(binary)


def test_link_shims_share_cache_across_checkouts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    first = tmp_path / "first" / "scripts" / "zig"
    second = tmp_path / "second" / "scripts" / "zig"
    for directory in (first, second):
        directory.mkdir(parents=True)
        (directory / "libresolv.tbd").write_text("same stub")
    monkeypatch.setattr(build_plugin, "ZIG_SHIM_DIR", first)
    cached = build_plugin.cached_link_shims()
    stub = cached / "libresolv.tbd"
    os.utime(stub, ns=(1, 1))
    monkeypatch.setattr(build_plugin, "ZIG_SHIM_DIR", second)
    assert build_plugin.cached_link_shims() == cached
    assert stub.stat().st_mtime_ns == 1
    (second / "libresolv.tbd").write_text("changed stub")
    updated = build_plugin.cached_link_shims()
    assert updated != cached
    assert (updated / "libresolv.tbd").read_text() == "changed stub"


def test_dev_version_counts_commits_since_the_last_release(tmp_path: Path, monkeypatch) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    (tmp_path / ".release-please-manifest.json").write_text('{".": "1.2.3"}\n')
    git("add", ".")
    git("commit", "-qm", "chore(main): release 1.2.3")
    monkeypatch.setattr(build_plugin, "ROOT", tmp_path)
    assert build_plugin.dev_version() == "1.2.3"
    for change in ("a", "b"):
        (tmp_path / change).write_text(change)
        git("add", change)
        git("commit", "-qm", f"fix: {change}")
    assert build_plugin.dev_version() == f"1.2.3+dev.2.{git('rev-parse', '--short', 'HEAD')}"
