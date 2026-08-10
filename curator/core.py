"""Optional compiled-core acceleration (curator-core subprocess transport).

The Go binary (built from `core/`) is optional acceleration exactly like numpy:
when a compatible binary is available the model build uses it for the
content-neighbor and performer-similarity stages; otherwise the numpy or
pure-Python implementations run unchanged. Discovery order:

1. ``CURATOR_CORE`` environment variable (CI, dev, benchmarks);
2. the installed plugin layout: ``<plugin>/curator-core-<goos>-<goarch>`` (the
   shipped per-arch binary for this platform) or a plain ``<plugin>/curator-core``;
3. the repository dev layout: ``<repo>/core/bin/curator-core``.

A candidate is accepted only when it answers the ``version`` probe with the
matching protocol. Availability is probed once per process and cached. The
binary is never a hard dependency: any probe failure degrades to the numpy /
pure-Python fallback, while a failure during a real stage run propagates (an
available-but-broken binary is a defect, mirroring how numpy errors surface).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

# Wire-contract version; bump in lockstep with core/main.go coreProtocol.
CORE_PROTOCOL = 1
_PROBE_TIMEOUT_S = 10
_RUN_TIMEOUT_S = 1800

_UNSET: object = object()
_binary_cache: Path | None | object = _UNSET


class CoreError(RuntimeError):
    """The compiled core failed while running a stage."""


def _binary_name() -> str:
    return "curator-core.exe" if os.name == "nt" else "curator-core"


def _platform_binary_name() -> str:
    """The shipped per-arch binary name for this platform, e.g.
    curator-core-linux-amd64 (matching Go's GOOS/GOARCH naming)."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    suffix = ".exe" if system == "windows" else ""
    return f"curator-core-{system}-{arch}{suffix}"


def _candidate_paths() -> tuple[Path, ...]:
    override = os.environ.get("CURATOR_CORE")
    if override:
        # Explicit pinning: when CURATOR_CORE is set it is the only candidate,
        # so a broken or mismatched override degrades to the fallback instead of
        # silently switching to a different binary.
        return (Path(override).expanduser(),)
    candidates: list[Path] = []
    # curator/ lives beside backend.py in the installed plugin layout, so
    # parent.parent is the plugin dir; in the repository layout it is the repo
    # root, where the core module's build output lives.
    plugin_dir = Path(__file__).resolve().parent.parent
    candidates.append(plugin_dir / _platform_binary_name())
    candidates.append(plugin_dir / _binary_name())
    candidates.append(plugin_dir / "core" / "bin" / _binary_name())
    return tuple(candidates)


def _probe(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(path), "version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    try:
        message = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(message, dict) and message.get("protocol") == CORE_PROTOCOL


def _clear_cache() -> None:
    """Forget the cached probe result (tests)."""
    global _binary_cache
    _binary_cache = _UNSET


def core_binary() -> Path | None:
    """Resolve the compiled core binary, or None when unavailable.

    The probe result is cached for the process lifetime; env-var changes in
    tests must call ``_clear_cache`` first.
    """
    global _binary_cache
    if _binary_cache is not _UNSET:
        return _binary_cache  # type: ignore[return-value]
    found: Path | None = None
    for candidate in _candidate_paths():
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        if _probe(candidate):
            found = candidate
            break
    _binary_cache = found
    return found


def core_available() -> bool:
    return core_binary() is not None


def run_core(
    mode: str,
    payload: dict[str, object],
    *,
    progress: Callable[[float], None] | None = None,
    profile: bool = False,
) -> dict[str, object]:
    """Run one core stage: JSON payload on stdin, NDJSON on stdout.

    ``progress`` receives raw stage fractions (0..1) as the binary streams
    them; the caller maps them onto the build's own progress scale. When
    ``profile`` is set the binary emits ``core.*`` spans, which are folded
    into the active profiling trace (``curator.profiling``), if any.
    """
    binary = core_binary()
    if binary is None:
        raise CoreError(
            "curator-core is required but missing or incompatible (wrong platform, "
            "version mismatch, or not executable); reinstall the plugin"
        )
    if profile:
        payload = {**payload, "profile": True}
    spawn_started_ns = time.perf_counter_ns()
    proc = subprocess.Popen(
        [str(binary), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, separators=(",", ":")))
    proc.stdin.close()
    result: dict[str, object] | None = None
    spans: list[tuple[str, int, int]] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise CoreError(f"compiled core returned malformed output: {error}") from error
        if not isinstance(message, dict):
            raise CoreError("compiled core returned a non-object message")
        if "result" in message:
            candidate = message["result"]
            if not isinstance(candidate, dict):
                raise CoreError("compiled core result is not an object")
            result = candidate
        elif "span" in message:
            span = message["span"]
            if isinstance(span, dict) and isinstance(span.get("name"), str):
                spans.append(
                    (
                        span["name"],
                        int(span.get("offset_us", 0)),
                        int(span.get("dur_us", 0)),
                    )
                )
        elif "progress" in message and progress is not None:
            progress(float(message["progress"]))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    returncode = proc.wait(timeout=_RUN_TIMEOUT_S)
    if returncode != 0 or result is None:
        raise CoreError(
            f"compiled core failed ({mode}, exit {returncode}): {stderr.strip()[-500:]}"
        )
    if spans:
        from curator.profiling import current_trace

        trace = current_trace()
        if trace is not None:
            # The binary's offsets are from its process start, which is
            # (spawn + a few ms of Go runtime init); record expects absolute
            # perf-counter readings, so convert back from the spawn point.
            for name, offset_us, duration_us in spans:
                trace.record(
                    "core",
                    name,
                    spawn_started_ns + offset_us * 1_000,
                    duration_us * 1_000,
                )
    return result


__all__ = [
    "CORE_PROTOCOL",
    "CoreError",
    "core_available",
    "core_binary",
    "run_core",
]
