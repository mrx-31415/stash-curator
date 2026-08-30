#!/usr/bin/env python3
"""Build the self-contained Stash Curator plugin archive.

The compiled core (`curator-core`) ships inside the zip as per-arch
binaries — the binary serves the whole raw-plugin interface (every operation,
task mode, and the entity-sync hook) and the model-build kernels, so no
Python runtime ships. The only non-binary runtime resource is the explanation
catalog (`curator/explanations/realizations.json`, read from disk by the
binary). Go is a build-time dependency for packaging; the binaries use the
native mattn/go-sqlite3 driver (CGO_ENABLED=1, SQLite amalgamation compiled
in), and cross-compile through `zig cc`, so a single machine cross-compiles
every shipped platform. A pinned zig is bootstrapped into `.tmp/zig/` when
none is on PATH (hash-verified download), so packaging needs no manual zig
install — only Go plus the repo's uv environment.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
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

# Pinned C cross-compiler bootstrap. When zig is not on PATH, packaging
# downloads this exact version into the gitignored .tmp/zig/ cache and
# verifies it against the official ziglang.org download index hashes below,
# so a fresh checkout needs only Go and the repo's uv environment. A zig
# already on PATH always wins (including CI's own install step).
ZIG_VERSION = "0.15.2"
ZIG_TARBALLS = {
    ("linux", "x86_64"): (
        "zig-x86_64-linux-0.15.2.tar.xz",
        "02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239",
    ),
    ("linux", "aarch64"): (
        "zig-aarch64-linux-0.15.2.tar.xz",
        "958ed7d1e00d0ea76590d27666efbf7a932281b3d7ba0c6b01b0ff26498f667f",
    ),
    ("macos", "x86_64"): (
        "zig-x86_64-macos-0.15.2.tar.xz",
        "375b6909fc1495d16fc2c7db9538f707456bfc3373b14ee83fdd3e22b3d43f7f",
    ),
    ("macos", "aarch64"): (
        "zig-aarch64-macos-0.15.2.tar.xz",
        "3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b",
    ),
}
ZIG_BASE_URL = "https://ziglang.org/download"
ZIG_CACHE = ROOT / ".tmp" / "zig"


def _host_platform() -> tuple[str, str]:
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("arm64", "aarch64")
    if sys.platform == "darwin":
        return ("macos", machine)
    return (sys.platform, machine)


def bootstrap_zig() -> Path | None:
    """Return the bin dir of a pinned zig, downloading it into .tmp/zig/ when needed.

    Returns None when zig is already on PATH or the host has no pinned tarball
    (packaging then falls through to the zig-on-PATH requirement). The tarball
    is hash-verified against the official ziglang.org index before extraction;
    a corrupted cache entry is re-downloaded.
    """
    if shutil.which("zig") is not None:
        return None
    entry = ZIG_TARBALLS.get(_host_platform())
    if entry is None:
        return None
    tarball_name, expected_sha256 = entry
    cache_dir = ZIG_CACHE / f"zig-{ZIG_VERSION}"
    final = cache_dir / "zig"
    for candidate in (final / "zig", final / "bin" / "zig"):
        if candidate.is_file():
            return candidate.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / tarball_name
    if archive.is_file() and sha256(archive.read_bytes()).hexdigest() != expected_sha256:
        archive.unlink()
    if not archive.is_file():
        print(f"[build_plugin] bootstrapping pinned zig {ZIG_VERSION} into {cache_dir}")
        url = f"{ZIG_BASE_URL}/{ZIG_VERSION}/{tarball_name}"
        with (
            urllib.request.urlopen(url) as response,
            tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".tar.xz", delete=False) as out,
        ):
            shutil.copyfileobj(response, out)
            temporary = Path(out.name)
        if sha256(temporary.read_bytes()).hexdigest() != expected_sha256:
            temporary.unlink()
            raise RuntimeError(f"zig download failed checksum verification: {url}")
        temporary.replace(archive)
    if final.exists():
        shutil.rmtree(final)
    with tempfile.TemporaryDirectory(dir=cache_dir) as extract_dir:
        with tarfile.open(archive) as tar:
            tar.extractall(extract_dir, filter="data")
        extracted = Path(extract_dir) / tarball_name.removesuffix(".tar.xz")
        if not extracted.is_dir():
            extracted = Path(extract_dir)
        shutil.move(str(extracted), str(final))
    for candidate in (final / "zig", final / "bin" / "zig"):
        if candidate.is_file():
            return candidate.parent
    raise RuntimeError(f"unexpected layout in bootstrapped zig: {final}")


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
    plugin_version = version()
    pending: list[tuple[tuple[str, str], Path, dict[str, str]]] = []
    for goos, goarch in SHIPPED_PLATFORMS:
        target = ROOT / "core" / "bin" / core_binary_name(goos, goarch)
        if _core_binary_fresh(target):
            continue
        target_env = dict(
            os.environ,
            CGO_ENABLED="1",
            GOOS=goos,
            GOARCH=goarch,
            CC=ZIG_CC[(goos, goarch)],
        )
        if goos == "darwin":
            target_env["CGO_LDFLAGS"] = f"-L{ZIG_SHIM_DIR} -F{ZIG_SHIM_DIR}"
        pending.append((target, target_env))
    if pending:
        zig_bin = bootstrap_zig()
        if zig_bin is None and shutil.which("zig") is None:
            hosts = ", ".join(f"{goos}-{arch}" for goos, arch in sorted(ZIG_TARBALLS))
            raise RuntimeError(
                "packaging the plugin requires zig (ziglang.org) as the C cross-compiler "
                "for the mattn sqlite driver (CGO_ENABLED=1); install it and put it on PATH, "
                f"or let the bootstrap download it on a supported host ({hosts})"
            )
        if zig_bin is not None:
            prepend = f"{zig_bin}{os.pathsep}"
            for _, target_env in pending:
                target_env["PATH"] = prepend + target_env.get("PATH", "")

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
                "    description: Local recommendations and StashDB discovery "
                "— curated to your taste.",
                "",
            )
        ),
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    print(build())
