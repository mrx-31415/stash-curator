from __future__ import annotations

import os
from pathlib import Path

from scripts import build_plugin


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
