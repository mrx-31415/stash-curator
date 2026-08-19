"""CI perf-budget gate (issue #124).

Builds the CI-shape synthetic sidecar (fixed seed), runs `curator-core
model-build` once at default GOMAXPROCS with a fixed clock, and fails when any
stage or the total exceeds the checked-in baseline (benchmarks/baseline.json)
by more than the multiplier (default 2.5; override PERF_BUDGET_MULTIPLIER).
A missing binary skips with a message, mirroring the core gate's no-Go skip.

Usage:
  python scripts/perf_gate.py                # check against the baseline
  python scripts/perf_gate.py --update-baseline   # rewrite the baseline from this host
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "benchmarks" / "baseline.json"
REFERENCE_MS = 200 * 86_400_000
DEFAULT_MULTIPLIER = 2.5
# Filesystem scheduling noise dominates very short stages. Keep the per-stage
# gate useful for regressions while avoiding failures from sub-500 ms jitter;
# the total budget remains unchanged and still catches aggregate slowdowns.
MIN_STAGE_BUDGET_MS = 500

# The Python-era stage key set (stageTimingOrder in core/tasks.go).
STAGE_ORDER = (
    "feature_lookup",
    "feature_build",
    "feature_database_writing",
    "feature_indexing",
    "feature_validation",
    "feature_publication",
    "feature_total",
    "labels",
    "affinities",
    "similarity",
    "scoring",
    "database_writing",
    "lane_classification",
    "score_first_ordering",
    "varied_ordering",
    "reason_generation",
    "sqlite_index_creation",
    "indexing",
    "validation",
    "publication",
    "cleanup",
    "total",
)


def _build(binary: Path, sidecar: Path) -> tuple[dict[str, object], float]:
    payload = json.dumps(
        {"db": str(sidecar), "now_ms": REFERENCE_MS}, separators=(",", ":")
    ).encode()
    started = time.perf_counter()
    proc = subprocess.run(
        [str(binary), "model-build"], input=payload, capture_output=True, timeout=3600
    )
    wall_ms = (time.perf_counter() - started) * 1000
    if proc.returncode != 0:
        raise SystemExit(f"[perf-gate] model-build failed: {proc.stderr.decode()[-500:]}")
    output = None
    for line in proc.stdout.decode().splitlines():
        parsed = json.loads(line)
        if "result" in parsed:
            output = parsed["result"]
    if output is None:
        raise SystemExit("[perf-gate] model-build produced no result line")
    return output, wall_ms


def _machine() -> dict[str, str]:
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        cpu = platform.processor() or "unknown"
    return {"hostname": socket.gethostname(), "cpu_model": cpu}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite benchmarks/baseline.json from this host's measurement",
    )
    args = parser.parse_args()
    multiplier = float(os.environ.get("PERF_BUDGET_MULTIPLIER", DEFAULT_MULTIPLIER))
    binary = ROOT / "core" / "bin" / "curator-core"
    if not binary.is_file():
        print(
            "[perf-gate] core/bin/curator-core missing; skipping perf budget "
            "(mirrors the core gate's no-Go skip)"
        )
        return 0
    import synthetic_corpus

    tmp = Path(tempfile.mkdtemp(prefix="perf-gate."))
    try:
        sidecar = tmp / "curator.sqlite3"
        print("[perf-gate] building CI-shape synthetic sidecar ...")
        synthetic_corpus.build_sidecar(sidecar, **synthetic_corpus.CI)
        output, wall_ms = _build(binary, sidecar)
        stages = output["stage_timings_ms"]
        if args.update_baseline:
            baseline = {
                "corpus": {
                    **synthetic_corpus.CI,
                    "known_performers": max(20, round(synthetic_corpus.CI["n_performers"] * 0.02)),
                },
                "machine": _machine(),
                "measured_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "multiplier": multiplier,
                "stages": {key: stages[key] for key in STAGE_ORDER if key in stages},
                "total_ms": round(wall_ms),
            }
            BASELINE.parent.mkdir(parents=True, exist_ok=True)
            BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
            print(f"[perf-gate] baseline written: {BASELINE} ({wall_ms:.0f} ms total)")
            return 0
        if not BASELINE.is_file():
            print("[perf-gate] benchmarks/baseline.json missing; run --update-baseline first")
            return 1
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        failures: list[tuple[str, float, float]] = []
        for key in STAGE_ORDER:
            if key not in baseline["stages"] or key not in stages:
                continue
            budget = max(baseline["stages"][key] * multiplier, MIN_STAGE_BUDGET_MS)
            if stages[key] > budget:
                failures.append((key, stages[key], budget))
        total_budget = baseline["total_ms"] * multiplier
        if wall_ms > total_budget:
            failures.append(("total", wall_ms, total_budget))
        if failures:
            print(f"[perf-gate] FAIL: over the {multiplier}x budget:")
            for key, measured, budget in failures:
                print(f"  {key}: {measured:.0f} ms > {budget:.0f} ms")
            return 1
        print(
            f"[perf-gate] OK: {wall_ms:.0f} ms total (baseline "
            f"{baseline['total_ms']:.0f} ms x {multiplier} = {total_budget:.0f} ms)"
        )
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
