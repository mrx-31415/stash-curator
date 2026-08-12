#!/usr/bin/env python3
"""Automated Phase 0 benchmark: drive a live Stash running Curator, collect traces.

Runs a battery of plugin operations and tasks against a Stash that has Curator
installed, pulls the profiling traces from the sidecar copy, and writes a scrubbed
report (JSON + Markdown) with per-operation latency statistics, the spawn/import
component, and the stage-level span breakdowns for tasks.

Everything is stdlib-only. The sidecar under test is always copied first (sqlite
backup API) and the benchmark never touches the original. The report contains only
operation names, aggregate statistics, and span categories/names - no entity ids or
library data.

Usage:
  python scripts/benchmark.py --db /path/to/curator.sqlite3 [--url URL] [--ops ...]
  python scripts/benchmark.py core-sweep [--reps N]   # GOMAXPROCS sweep (1/2/4/8)

Options:
  --db PATH        Sidecar to benchmark against (copied before use). Default:
                   $STASH_CURATOR_DB, else the first candidate found under
                   data/ and .tmp/.
  --url URL        Stash base URL. Default http://localhost:PORT with
                   --port (default 9998; 9999 is often the UI-dev mock).
  --port PORT      Host port to publish Stash on when starting it.
  --ops LIST       Comma-separated operations; "all" for the full battery.
  --tasks LIST     Comma-separated task display names from stash-curator.yml;
                   "all" for prepare, backup, build.
  --reps N         Repetitions per operation (default 4).
  --workspace DIR  Scratch dir for the Stash install + sidecar copy (default
                   .tmp/benchmark).
  --report-dir DIR Report output dir (default .tmp/benchmark-report).
  --keep-stash     Do not tear down Stash after the run.
  --no-stash       Do not start/stop Stash; use whatever answers at --url.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import statistics
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "tests" / "integration" / "docker-compose.yml"
PLUGIN_ZIP = ROOT / "dist" / "stash-curator.zip"
PLUGIN_ID = "stash-curator"

# Task display names from plugin/stash-curator.yml (what runPluginTask expects).
TASK_NAMES = {
    "prepare": "Prepare recommendation pages",
    "backup": "Backup Curator data",
    "build": "Rebuild recommendation model",
    "update-model": "Apply recent Curator feedback",
    "sync-plays": "Sync recent plays",
    "compact": "Compact legacy Curator data",
    "vacuum": "Vacuum compacted Curator data",
}

OPERATIONS = {
    "round_trip": {},
    "health": {},
    "get_config": {},
    "get_slate": {"operation": "get_slate", "lane": "for_you", "count": 20, "page": 1},
    "get_slate_page2": {"operation": "get_slate", "lane": "for_you", "count": 20, "page": 2},
    "replace_item": {"operation": "replace_item", "exclude_scene_ids": []},
    "get_similar_scene": {"operation": "get_similar", "entity_type": "scene", "count": 20},
    "get_similar_performer": {
        "operation": "get_similar",
        "entity_type": "performer",
        "count": 20,
    },
    "get_explanation": {"operation": "get_explanation"},
    "get_expand": {"operation": "get_expand", "entity_type": "performer", "page": 1},
    "get_shortlist": {"operation": "get_shortlist", "page": 1},
    "get_taste_profile": {"operation": "get_taste_profile"},
    "get_feedback_history": {"operation": "get_feedback_history", "page": 1},
    "get_recommendation_history": {"operation": "get_recommendation_history", "page": 1},
    "get_job_status": {"operation": "get_job_status"},
    "get_diagnostics": {"operation": "get_diagnostics"},
}

# Operations that need a published model in the sidecar.
MODEL_OPS = {
    "get_slate",
    "get_slate_page2",
    "replace_item",
    "get_similar_scene",
    "get_similar_performer",
    "get_explanation",
    "get_expand",
    "get_shortlist",
    "get_taste_profile",
    "get_recommendation_history",
}


def _gql(url: str, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"{url}/graphql", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Stash returned {exc.code}: {body[:500]}") from exc
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return dict(data["data"])


def _wait_for_stash(url: str, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Stash not ready at {url} after {timeout}s")


# --------------------------------------------------------------------------- sidecar


_cold_cache_warned = False


def _drop_caches() -> None:
    """Drop the OS page cache (root only) for cold-cache measurement; warn
    once and continue warm otherwise."""
    global _cold_cache_warned
    if os.geteuid() != 0:
        if not _cold_cache_warned:
            _cold_cache_warned = True
            print("[benchmark] WARNING: not root; --cold-cache ignored (warm cache)")
        return
    subprocess.run(["sync"], check=True)
    try:
        with open("/proc/sys/vm/drop_caches", "w", encoding="utf-8") as handle:
            handle.write("3\n")
    except OSError as error:
        print(f"[benchmark] WARNING: drop_caches failed: {error}")


def _find_sidecar() -> Path | None:
    """Pick the first usable sidecar (published model + profiling) under data/ and .tmp/."""
    candidates = [ROOT / "data"]
    tmp = ROOT / ".tmp"
    if tmp.is_dir():
        candidates.append(tmp)
    found: list[tuple[float, Path]] = []
    for base in candidates:
        for path in sorted(base.rglob("*.sqlite3")):
            try:
                con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    tables = {
                        row[0]
                        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if "profile_trace" not in tables:
                        continue
                    model = con.execute(
                        "SELECT count(*) FROM model_version WHERE status='published'"
                    ).fetchone()[0]
                    if model == 0:
                        continue
                finally:
                    con.close()
            except Exception:
                continue
            # Prefer cores with their generation-artifact directory present.
            derived = path.resolve().with_name(f"{path.stem}-derived")
            if not derived.is_dir():
                continue
            found.append((path.stat().st_mtime, path))
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def _copy_sidecar(source: Path, destination: Path) -> None:
    """Crash-safe single-file copy via the sqlite backup API (handles WAL).

    Also copies the `<stem>-derived` generation-artifact directory beside the
    destination, so the copy is self-contained: `attach_active_artifacts`
    requires the active feature/model artifacts to exist there.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    derived = source.resolve().with_name(f"{source.stem}-derived")
    if derived.is_dir():
        target = destination.resolve().with_name(f"{destination.stem}-derived")
        shutil.copytree(derived, target, dirs_exist_ok=True)


def _sidecar_state(path: Path) -> dict[str, object]:
    """Counts only - never values. Used for the report header."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # A pre-profiling sidecar copy legitimately lacks these tables until the
        # plugin migrates it inside the container; report zero instead of failing.
        traces = (
            con.execute("SELECT count(*) FROM profile_trace").fetchone()[0]
            if "profile_trace" in tables
            else 0
        )
        jobs = (
            con.execute("SELECT count(*) FROM curator_job").fetchone()[0]
            if "curator_job" in tables
            else 0
        )
        model = (
            con.execute("SELECT count(*) FROM model_version WHERE status='published'").fetchone()[0]
            if "model_version" in tables
            else 0
        )
    finally:
        con.close()
    return {"published_models": model, "profile_traces": traces, "curator_jobs": jobs}


def _sample_ids(path: Path) -> tuple[str | None, str | None]:
    """One scene id and one performer id from the copy (used in requests only)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        scene = con.execute("SELECT scene_id FROM source_scene ORDER BY rowid LIMIT 1").fetchone()
        performer = con.execute(
            "SELECT performer_id FROM source_performer ORDER BY rowid LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return (
        str(scene[0]) if scene else None,
        str(performer[0]) if performer else None,
    )


# --------------------------------------------------------------------------- Stash


def _ensure_plugin_built() -> None:
    if PLUGIN_ZIP.is_file():
        return
    subprocess.run(
        ["uv", "run", "--frozen", "python", "scripts/build_plugin.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _clean_workspace_plugin(workspace: Path) -> None:
    """Remove the installed plugin tree, falling back to a root container.

    The Stash container runs Python as root and writes __pycache__ into the
    mounted plugin dir; host removal then hits permission errors. A throwaway
    alpine container removes those files when plain shutil.rmtree fails.
    """
    plugin_dir = workspace / "plugins"
    if not plugin_dir.exists():
        return
    try:
        shutil.rmtree(plugin_dir)
        return
    except PermissionError:
        pass
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{plugin_dir.resolve()}:/clean",
            "alpine",
            "sh",
            "-c",
            "rm -rf /clean/*",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.rmtree(plugin_dir, ignore_errors=True)


def _install_plugin(workspace: Path) -> None:
    plugin_dir = workspace / "plugins" / PLUGIN_ID
    _clean_workspace_plugin(workspace)
    plugin_dir.mkdir(parents=True)
    with zipfile.ZipFile(PLUGIN_ZIP) as archive:
        archive.extractall(plugin_dir)
    # Python's zipfile does not restore the executable bit from the archive
    # entries; the launcher requires the per-arch binaries to be executable.
    for binary in plugin_dir.glob("curator-core*"):
        binary.chmod(binary.stat().st_mode | 0o111)
    data_dir = plugin_dir / "data"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir()
    os.chmod(data_dir, 0o777)  # container writes WAL as root; host reads read-only
    # The container runs Python as root and writes __pycache__ into the mounted
    # plugin dir; make the tree writable so host cleanup (and the next install)
    # can remove it without root.
    for root, dirs, _ in os.walk(plugin_dir):
        os.chmod(root, 0o777)
        for name in dirs:
            os.chmod(Path(root) / name, 0o777)
    (workspace / "config.yml").write_text(
        "\n".join(
            (
                "generated: /root/.stash/generated",
                "cache: /root/.stash/cache",
                "blobs:",
                "  path: /root/.stash/blobs",
                "  storage: FILESYSTEM",
                "database: /root/.stash/stash-go.sqlite",
                "dangerous_allow_public_without_auth: true",
                "plugins:",
                f"  {PLUGIN_ID}:",
                "    enabled: true",
                "    profilingEnabled: true",
                "",
            )
        ),
        encoding="utf-8",
    )
    return data_dir


def _compose(action: str, workspace: Path, port: int) -> None:
    env = dict(os.environ, STASH_CONFIG=str(workspace), STASH_PORT=str(port))
    command = ["docker", "compose", "-f", str(COMPOSE_FILE), action]
    if action == "up":
        command += ["-d", "--wait"]
    else:
        command += ["--volumes"]
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _introspect(url: str) -> tuple[bool, bool, bool]:
    data = _gql(url, '{ __type(name: "Mutation") { fields { name } } }')
    fields = {str(item["name"]) for item in data["__type"]["fields"]}
    return (
        "runPluginOperation" in fields,
        "runPluginTask" in fields,
        "configurePlugin" in fields,
    )


def _run_operation(url: str, args: dict[str, object]) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    data = _gql(
        url,
        f'mutation($args: Map!) {{ runPluginOperation(plugin_id: "{PLUGIN_ID}", args: $args) }}',
        {"args": args},
    )
    return (time.perf_counter() - started) * 1000, dict(data["runPluginOperation"])


def _wait_for_task(
    sidecar: Path, job_type: str, after_ms: int, timeout_s: float = 3600
) -> dict[str, object]:
    """Poll the sidecar copy until a fresh curator_job row for job_type finishes.

    Rows are filtered to those started after the submission timestamp: the
    source sidecar already contains historical rows for the same job types, and
    matching those would report instant completion for a task that never ran.
    Stash's jobQueue query returns null in some versions even while plugin
    tasks run, so the sidecar row (written by the task itself) is the
    completion ground truth; it also carries the exact duration and error text.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        con = sqlite3.connect(f"file:{sidecar}?mode=ro", uri=True)
        try:
            row = con.execute(
                """
                SELECT state, started_at_ms, finished_at_ms, error
                FROM curator_job
                WHERE job_type=? AND started_at_ms>?
                ORDER BY started_at_ms DESC LIMIT 1
                """,
                (job_type, after_ms),
            ).fetchone()
        finally:
            con.close()
        if row is not None and str(row[0]) != "running":
            result: dict[str, object] = {"state": str(row[0])}
            if row[1] is not None and row[2] is not None:
                result["job_duration_ms"] = int(row[2]) - int(row[1])
            if row[3] is not None:
                result["error"] = str(row[3])
            return result
        if time.monotonic() > deadline:
            raise RuntimeError(f"task {job_type} did not finish within {timeout_s}s")
        time.sleep(2)


def _run_task(
    url: str,
    sidecar: Path,
    mode: str,
    display_name: str,
    after_ms: int,
    timeout_s: float = 3600,
) -> tuple[float, dict[str, object]]:
    """Start a plugin task and wait for its fresh curator_job row to finish.

    runPluginTask returns the Stash job id immediately; the plugin task runs in
    Stash's job queue. The returned wall time spans submission to completion.
    """
    started = time.perf_counter()
    data = _gql(
        url,
        "mutation($task_name: String!) {"
        f' runPluginTask(plugin_id: "{PLUGIN_ID}", task_name: $task_name) }}',
        {"task_name": display_name},
    )
    job_id = str(data["runPluginTask"])
    result = _wait_for_task(sidecar, mode, after_ms, timeout_s)
    wall_ms = (time.perf_counter() - started) * 1000
    return wall_ms, {"job_id": job_id, **result}


# --------------------------------------------------------------------------- traces


def _invalidate_model(sidecar: Path) -> None:
    """Force a full cold rebuild by dropping the published generations in the copy.

    Deletes the published feature_build and model_version rows (no FK constraints
    block this) and removes the derived artifact files, so the next build task
    regenerates features, similarity, and publication from the synced source data.
    """
    con = sqlite3.connect(sidecar)
    try:
        con.execute("DELETE FROM feature_build")
        con.execute("DELETE FROM model_version")
        con.commit()
    finally:
        con.close()
    derived = sidecar.resolve().with_name(f"{sidecar.stem}-derived")
    if derived.is_dir():
        shutil.rmtree(derived, ignore_errors=True)


def _install_deps(url: str, workspace: Path, timeout_s: float = 900) -> bool:
    """Run the plugin's optional-deps task and wait for the venv pip to appear.

    The task creates a venv beside the plugin; the host sees it through the
    bind mount. Returns False on timeout (the cold build then runs pure Python).
    """
    print("[benchmark] installing optional dependencies (numpy/networkx) ...")
    _gql(
        url,
        'mutation { runPluginTask(plugin_id: "stash-curator", '
        'task_name: "Install optional dependencies") }',
    )
    marker = workspace / "plugins" / PLUGIN_ID / "venv" / "bin" / "pip"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if marker.is_file():
            print("[benchmark] optional dependencies installed")
            return True
        time.sleep(3)
    print(f"[benchmark] WARNING: optional deps did not install within {timeout_s}s")
    return False


def _pull_traces(sidecar: Path, after_ms: int) -> list[dict]:
    con = sqlite3.connect(f"file:{sidecar}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """
            SELECT trace_id, kind, operation, started_at_ms, duration_us, status,
                   span_count, truncated, trace_json
            FROM profile_trace
            WHERE started_at_ms >= ?
            ORDER BY started_at_ms ASC
            """,
            (after_ms,),
        ).fetchall()
    finally:
        con.close()
    traces = []
    for row in rows:
        payload = json.loads(row[8])
        events = payload.get("traceEvents") if isinstance(payload, dict) else None
        traces.append(
            {
                "trace_id": str(row[0]),
                "kind": str(row[1]),
                "operation": str(row[2]),
                "started_at_ms": int(row[3]),
                "duration_us": int(row[4]),
                "status": str(row[5]),
                "spans": [
                    {
                        "category": str(event.get("cat", "")),
                        "name": str(event.get("name", "")),
                        "duration_us": int(event.get("dur", 0)),
                        "args": event.get("args") if isinstance(event.get("args"), dict) else None,
                    }
                    for event in (events or [])
                    if isinstance(event, dict)
                ],
            }
        )
    return traces


def _span_aggregate(traces: list[dict]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], list[int]] = {}
    peaks: dict[tuple[str, str], list[float]] = {}
    for trace in traces:
        for span in trace["spans"]:
            key = (span["category"], span["name"])
            buckets.setdefault(key, []).append(span["duration_us"])
            args = span.get("args") or {}
            peak = args.get("peak_rss_kb") if isinstance(args, dict) else None
            if isinstance(peak, (int, float)) and peak > 0:
                peaks.setdefault(key, []).append(float(peak))
    rows = [
        {
            "category": cat,
            "name": name,
            "count": len(values),
            "median_ms": round(statistics.median(values) / 1000, 1),
            "total_ms": round(sum(values) / 1000, 1),
        }
        for (cat, name), values in sorted(buckets.items(), key=lambda item: -sum(item[1]))
    ]
    for row in rows:
        key = (row["category"], row["name"])
        if key in peaks:
            row["max_peak_rss_kb"] = round(max(peaks[key]))
    return rows


def _job_summary(sidecar: Path, job_type: str, after_ms: int) -> dict[str, object] | None:
    con = sqlite3.connect(f"file:{sidecar}?mode=ro", uri=True)
    try:
        row = con.execute(
            """
            SELECT summary_json, started_at_ms, finished_at_ms
            FROM curator_job
            WHERE job_type=? AND state='complete' AND started_at_ms>?
            ORDER BY started_at_ms DESC LIMIT 1
            """,
            (job_type, after_ms),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    summary = json.loads(row[0])
    summary["job_duration_ms"] = int(row[2]) - int(row[1]) if row[2] is not None else None
    return summary


# --------------------------------------------------------------------------- report


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min_ms": round(min(values), 1),
        "median_ms": round(statistics.median(values), 1),
        "p95_ms": round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 1),
        "max_ms": round(max(values), 1),
    }


def _write_report(report_dir: Path, report: dict[str, object]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_dir = report_dir.resolve()
    json_path = report_dir / "benchmark-report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Curator Phase 0 benchmark",
        "",
        f"- date: {report['generated_at']}",
        f"- stash: {report.get('stash_version', 'unknown')}",
        f"- plugin: {report.get('plugin_version', 'unknown')}",
        f"- sidecar: {report.get('sidecar_state')}",
        "",
        "## Operations (client wall time, ms)",
        "",
        "| operation | n | min | median | p95 | max | trace median | est spawn |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, data in sorted(report["operations"].items()):
        s = data["wall"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                name,
                s["n"],
                s["min_ms"],
                s["median_ms"],
                s["p95_ms"],
                s["max_ms"],
                data["trace_median_ms"] or "-",
                data["spawn_estimate_ms"] or "-",
            )
        )
    lines.append("")
    lines.append("## Tasks")
    lines.append("")
    for name, data in sorted(report["tasks"].items()):
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- wall: {data['wall_ms']} ms")
        lines.append(f"- trace: {data['trace_ms']} ms")
        if data.get("job_summary"):
            lines.append(f"- job duration: {data['job_summary'].get('job_duration_ms')} ms")
            stages = data["job_summary"].get("stage_timings_ms") or {}
            if stages:
                lines.append("- model stages (ms):")
                for stage, ms in sorted(stages.items()):
                    lines.append(f"  - {stage}: {ms}")
            if data["job_summary"].get("peak_rss_kb"):
                lines.append(f"- peak RSS: {data['job_summary']['peak_rss_kb']} kB")
        lines.append("- spans:")
        for span in data["spans"]:
            memory = (
                f" max_peak={span['max_peak_rss_kb']} kB" if span.get("max_peak_rss_kb") else ""
            )
            lines.append(
                f"  - {span['category']}.{span['name']}: count={span['count']} "
                f"median={span['median_ms']} ms total={span['total_ms']} ms{memory}"
            )
        lines.append("")
    markdown = report_dir / "benchmark-report.md"
    markdown.write_text("\n".join(lines), encoding="utf-8")
    return json_path


# --------------------------------------------------------------------------- main


def _select_ops(names: str, has_model: bool) -> dict[str, dict[str, object]]:
    if names == "all":
        chosen = set(OPERATIONS)
    else:
        chosen = {name.strip() for name in names.split(",") if name.strip()}
        unknown = chosen - set(OPERATIONS)
        if unknown:
            raise SystemExit(f"unknown operations: {sorted(unknown)}")
    if not has_model:
        chosen -= MODEL_OPS
    return {name: OPERATIONS[name] for name in sorted(chosen)}


def _select_tasks(names: str) -> list[str]:
    if names == "all":
        return ["prepare", "backup", "build"]
    chosen = [name.strip() for name in names.split(",") if name.strip()]
    unknown = set(chosen) - set(TASK_NAMES)
    if unknown:
        raise SystemExit(f"unknown tasks: {sorted(unknown)}")
    return chosen


# --------------------------------------------------------------------------- core sweep


def _write_core_sweep_report(report: dict[str, object]) -> Path:
    out_dir = ROOT / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "core-sweep-report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    runs = report["runs"]
    threads_order = (1, 2, 4, 8)
    stage_order = sorted({key for run in runs for key in run["stage_timings_ms"]})
    # Determinism: the model id and scene count must be identical across
    # thread counts (the kernel is cross-thread deterministic).
    outputs = {
        (run["gomaxprocs"], run["rep"]): (run["model_id"], run["scene_count"]) for run in runs
    }
    distinct = {value for value in outputs.values()}
    determinism = (
        f"OK ({len(distinct)} identical build outputs)"
        if len(distinct) == 1
        else f"MISMATCH: {distinct}"
    )
    lines = [
        "# Core GOMAXPROCS sweep",
        "",
        f"- date: {report['generated_at']}",
        f"- host: {report['hostname']}",
        f"- corpus: {report['corpus']}",
        f"- determinism: {determinism}",
        "",
        "## Wall time scaling",
        "",
        "| GOMAXPROCS | reps | median wall (ms) | min | max | median peak RSS (kB) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for threads in threads_order:
        rows = [run for run in runs if run["gomaxprocs"] == threads]
        if not rows:
            continue
        walls = [run["wall_ms"] for run in rows]
        peaks = [run["peak_rss_kb"] for run in rows]
        wall_line = (
            f"| {threads} | {len(rows)} | "
            f"{round(statistics.median(walls), 1)} | {round(min(walls), 1)} | "
            f"{round(max(walls), 1)} | {round(statistics.median(peaks), 1)} |"
        )
        lines.append(wall_line)
    lines.append("")
    lines.append("## Per-stage timings (median ms by GOMAXPROCS)")
    lines.append("")
    lines.append("| stage | 1 | 2 | 4 | 8 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for stage in stage_order:
        cells = []
        for threads in threads_order:
            values = [
                run["stage_timings_ms"][stage]
                for run in runs
                if run["gomaxprocs"] == threads and stage in run["stage_timings_ms"]
            ]
            cells.append(str(round(statistics.median(values), 1)) if values else "-")
        lines.append("| {} | {} |".format(stage, " | ".join(cells)))
    lines.append("")
    lines.append("## Per-stage peak RSS (median kB by GOMAXPROCS)")
    lines.append("")
    lines.append("| stage | 1 | 2 | 4 | 8 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for stage in stage_order:
        cells = []
        for threads in threads_order:
            values = [
                run["stage_memory"][stage]["peak_rss_kb"]
                for run in runs
                if run["gomaxprocs"] == threads
                and stage in run["stage_memory"]
                and run["stage_memory"][stage].get("peak_rss_kb")
            ]
            cells.append(str(round(statistics.median(values), 1)) if values else "-")
        lines.append("| {} | {} |".format(stage, " | ".join(cells)))
    lines.append("")
    lines.append("## Build outputs (determinism check)")
    lines.append("")
    lines.append("| GOMAXPROCS | rep | model_id | scene_count | peak RSS (kB) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for run in sorted(runs, key=lambda item: (item["gomaxprocs"], item["rep"])):
        lines.append(
            "| {} | {} | {} | {} | {} |".format(
                run["gomaxprocs"],
                run["rep"],
                run["model_id"],
                run["scene_count"],
                run["peak_rss_kb"],
            )
        )
    lines.append("")
    (out_dir / "core-sweep-report.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path


def _run_core_sweep(args: argparse.Namespace) -> Path:
    """GOMAXPROCS sweep over the model-build kernel on a synthetic
    production-shape sidecar. Each rep gets a fresh copy (the kernel reuses
    the published model on a second run against the same sidecar and returns
    near-zero timings); stage timings + memory come from the result line."""
    import synthetic_corpus

    binary = ROOT / "core" / "bin" / "curator-core"
    if not binary.is_file():
        raise SystemExit("core/bin/curator-core missing; run scripts/build_core.sh first")
    reps = args.reps if args.reps is not None else 3
    workspace = Path(args.workspace).resolve() / "core-sweep"
    workspace.mkdir(parents=True, exist_ok=True)
    base = workspace / "base.sqlite3"
    if not base.is_file():
        print("[benchmark] building production-shape synthetic sidecar ...")
        synthetic_corpus.build_sidecar(base, **synthetic_corpus.PRODUCTION)
    counts = {
        **synthetic_corpus.PRODUCTION,
        "known_performers": max(20, round(synthetic_corpus.PRODUCTION["n_performers"] * 0.02)),
    }
    runs: list[dict[str, object]] = []
    for threads in (1, 2, 4, 8):
        for rep in range(reps):
            run_db = workspace / f"run-{threads}-{rep}.sqlite3"
            print(f"[benchmark] GOMAXPROCS={threads} rep {rep + 1}/{reps} ...")
            synthetic_corpus.copy_sidecar(base, run_db)
            payload = json.dumps(
                {"db": str(run_db), "now_ms": synthetic_corpus.REFERENCE_MS},
                separators=(",", ":"),
            ).encode()
            started = time.perf_counter()
            env = dict(os.environ, GOMAXPROCS=str(threads))
            proc = subprocess.run(
                [str(binary), "model-build"],
                input=payload,
                capture_output=True,
                env=env,
                timeout=7200,
            )
            wall_ms = (time.perf_counter() - started) * 1000
            derived = run_db.resolve().with_name(f"{run_db.stem}-derived")
            shutil.rmtree(derived, ignore_errors=True)
            run_db.unlink(missing_ok=True)
            if proc.returncode != 0:
                detail = proc.stderr.decode()[-400:]
                print(f"[benchmark] GOMAXPROCS={threads} rep {rep} failed: {detail}")
                continue
            output = None
            for line in proc.stdout.decode().splitlines():
                parsed = json.loads(line)
                if "result" in parsed:
                    output = parsed["result"]
            if output is None:
                print(f"[benchmark] GOMAXPROCS={threads} rep {rep}: no result line")
                continue
            print(
                f"[benchmark] GOMAXPROCS={threads} rep {rep}: {wall_ms:.0f} ms wall, "
                f"model {output['model_id'][:24]}, scenes {output['scene_count']}, "
                f"reused {output['reused']}"
            )
            runs.append(
                {
                    "gomaxprocs": threads,
                    "rep": rep,
                    "wall_ms": round(wall_ms, 1),
                    "model_id": output["model_id"],
                    "scene_count": output["scene_count"],
                    "stage_timings_ms": output["stage_timings_ms"],
                    "stage_memory": output["stage_memory"],
                    "peak_rss_kb": output["peak_rss_kb"],
                }
            )
    if not runs:
        raise SystemExit("core-sweep: no successful runs")
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "hostname": socket.gethostname(),
        "corpus": counts,
        "runs": runs,
    }
    return _write_core_sweep_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default=None, help="core-sweep")
    parser.add_argument("--db", help="sidecar to benchmark (copied first)")
    parser.add_argument("--url", help="Stash base URL")
    parser.add_argument("--port", type=int, default=9998, help="host port (default 9998)")
    parser.add_argument("--ops", default="all")
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--reps", type=int, default=None)
    parser.add_argument("--workspace", default=str(ROOT / ".tmp" / "benchmark"))
    parser.add_argument("--report-dir", default=str(ROOT / ".tmp" / "benchmark-report"))
    parser.add_argument("--keep-stash", action="store_true")
    parser.add_argument("--no-stash", action="store_true")
    parser.add_argument("--cold-build", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--cold-cache",
        action="store_true",
        help="drop the OS page cache before each op rep and task run (root)",
    )
    parser.add_argument(
        "--skip-install-deps",
        action="store_true",
        help="skip the optional-deps (numpy/networkx) venv task; cold builds then run pure Python",
    )
    args = parser.parse_args()

    if args.mode == "core-sweep":
        report_path = _run_core_sweep(args)
        print(f"[benchmark] core-sweep report: {report_path}")
        return
    if args.mode is not None:
        parser.error(f"unknown mode: {args.mode}")
    if args.reps is None:
        args.reps = 4

    source: Path | None = None
    if args.db:
        source = Path(args.db)
    elif os.environ.get("STASH_CURATOR_DB"):
        source = Path(os.environ["STASH_CURATOR_DB"])
    if source is None or not source.is_file():
        source = _find_sidecar()
        if source is None:
            raise SystemExit("no sidecar found; pass --db PATH or set STASH_CURATOR_DB")
    print(f"[benchmark] sidecar source: {source}")

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not args.no_stash:
        _ensure_plugin_built()
        print(f"[benchmark] installing plugin + config into {workspace}")
        _install_plugin(workspace)
    sidecar = workspace / "plugins" / PLUGIN_ID / "data" / "curator.sqlite3"
    print("[benchmark] copying sidecar (backup API) ...")
    _copy_sidecar(source, sidecar)
    state = _sidecar_state(sidecar)
    print(f"[benchmark] copy state: {state}")
    scene_id, performer_id = _sample_ids(sidecar)
    has_model = bool(state["published_models"])

    url = args.url or f"http://localhost:{args.port}"
    if not args.no_stash:
        print(f"[benchmark] starting Stash on :{args.port} ...")
        _compose("up", workspace, args.port)
        try:
            _wait_for_stash(url)
            _run(url, args, workspace, sidecar, state, scene_id, performer_id, has_model)
        finally:
            if not args.keep_stash:
                print("[benchmark] tearing down Stash ...")
                _compose("down", workspace, args.port)
                _clean_workspace_plugin(workspace)
    else:
        _wait_for_stash(url)
        _run(url, args, workspace, sidecar, state, scene_id, performer_id, has_model)


def _run(
    url: str,
    args: argparse.Namespace,
    workspace: Path,
    sidecar: Path,
    state: dict[str, object],
    scene_id: str | None,
    performer_id: str | None,
    has_model: bool,
) -> None:
    has_operation, has_task, has_configure = _introspect(url)
    if not has_operation:
        raise SystemExit("Stash does not expose runPluginOperation")
    health = _gql(url, "{ version { version } }")
    stash_version = health["version"]["version"]
    _, health_output = _run_operation(url, {"operation": "health"})
    plugin_version = str(health_output.get("curator_version", "unknown"))
    if has_configure:
        _gql(
            url,
            'mutation { configurePlugin(plugin_id: "stash-curator", '
            "input: {profilingEnabled: true}) }",
        )
    # Self-check: a profiled operation must record a trace (round_trip and
    # health are intentionally not profiled).
    _, _ = _run_operation(url, {"operation": "get_config"})
    if not _pull_traces(sidecar, int(time.time() * 1000) - 60_000):
        print(
            "[benchmark] WARNING: no profiling traces recorded; is "
            "profilingEnabled: true set under plugins.stash-curator in config.yml?"
        )
    if not args.skip_install_deps:
        _install_deps(url, workspace)

    ops = _select_ops(args.ops, has_model)
    print(f"[benchmark] operations: {sorted(ops)} (reps={args.reps})")
    op_results: dict[str, dict[str, object]] = {}
    for name in sorted(ops):
        base = dict(ops[name])
        if name == "get_similar_scene" and scene_id is not None:
            base["entity_id"] = scene_id
        elif name == "get_similar_performer" and performer_id is not None:
            base["entity_id"] = performer_id
        elif name == "get_explanation" and scene_id is not None:
            base["scene_id"] = scene_id
        if name in MODEL_OPS and not has_model:
            continue
        wall: list[float] = []
        traces: list[dict] = []
        for rep in range(args.reps):
            if args.cold_cache:
                _drop_caches()
            before = int(time.time() * 1000)
            try:
                elapsed, output = _run_operation(url, base)
            except RuntimeError as error:
                print(f"[benchmark] {name} rep {rep} failed: {error}")
                break
            wall.append(elapsed)
            traces.extend(_pull_traces(sidecar, before))
            if "error" in output:
                print(f"[benchmark] {name} returned error: {output['error']}")
                break
            time.sleep(0.2)
        op_results[name] = {
            "wall": _stats(wall),
            "trace_median_ms": (
                round(statistics.median(t["duration_us"] for t in traces) / 1000, 1)
                if traces
                else None
            ),
            "spawn_estimate_ms": (
                round(
                    statistics.median(wall)
                    - statistics.median(t["duration_us"] for t in traces) / 1000,
                    1,
                )
                if traces and wall
                else None
            ),
            "spans": _span_aggregate(traces),
        }
        print(f"  {name}: median {op_results[name]['wall']['median_ms']} ms")

    tasks = _select_tasks(args.tasks)
    if not has_task:
        print("[benchmark] Stash does not expose runPluginTask; skipping tasks")
        tasks = []
    print(f"[benchmark] tasks: {tasks}")
    task_results: dict[str, dict[str, object]] = {}
    for name in tasks:
        before = int(time.time() * 1000)
        if args.cold_cache:
            _drop_caches()
        if args.cold_build and name == "build":
            print("[benchmark] invalidating published model for a cold rebuild ...")
            _invalidate_model(sidecar)
        print(f"[benchmark] running task '{TASK_NAMES[name]}' ...")
        try:
            wall_ms, output = _run_task(url, sidecar, name, TASK_NAMES[name], before)
        except RuntimeError as error:
            print(f"[benchmark] task {name} failed: {error}")
            task_results[name] = {"error": str(error)}
            continue
        traces = _pull_traces(sidecar, before)
        if str(output.get("state")) == "failed":
            print(f"[benchmark] task {name} failed: {output.get('error')}")
        task_results[name] = {
            "wall_ms": round(wall_ms, 1),
            "trace_ms": (
                round(statistics.median(t["duration_us"] for t in traces) / 1000, 1)
                if traces
                else None
            ),
            "spans": _span_aggregate(traces),
            "job_summary": _job_summary(sidecar, name, before),
        }
        print(f"  {name}: {task_results[name]['wall_ms']} ms wall")
        time.sleep(0.5)

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "stash_version": stash_version,
        "plugin_version": plugin_version,
        "cold_build": bool(args.cold_build),
        "cold_cache": bool(args.cold_cache),
        "optional_deps_installed": not args.skip_install_deps,
        "sidecar_state": state,
        "operations": op_results,
        "tasks": task_results,
    }
    report_path = _write_report(Path(args.report_dir), report)
    print(f"[benchmark] report: {report_path}")


if __name__ == "__main__":
    main()
