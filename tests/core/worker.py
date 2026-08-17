"""Shared harness for running Go task modes through the background worker
(docs/decisions/004-background-task-worker.md): the Go binary enqueues, its
spawned daemon executes, and tests poll get_job_status to a terminal state.
The Python backend stays the inline oracle whose job summaries the Go
worker's are compared against.

The worker's pid/state/log files live in the test's temporary plugin dir,
and the sidecar path is passed per-enqueue, so each test gets an isolated
daemon and database.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path


def task_payload(db_path: Path, stash_url: str, operation: str | None = None) -> bytes:
    payload = {
        "server_connection": {
            "Host": "127.0.0.1",
            "Port": int(stash_url.rsplit(":", 1)[1]),
            "Scheme": "http",
            "SessionCookie": {},
        },
        "args": {"database_path": str(db_path)},
    }
    if operation:
        payload["args"]["operation"] = operation
    return json.dumps(payload, separators=(",", ":")).encode()


def run_binary(
    binary: Path,
    plugin_dir: Path,
    raw: bytes,
    mode: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    argv = [str(binary), str(plugin_dir)]
    if mode is not None:
        argv.append(mode)
    return subprocess.run(argv, input=raw, capture_output=True, timeout=300, env=env)


def stop_worker(plugin_dir: Path) -> None:
    """Gracefully stop a daemon spawned for a worker test run."""
    pid_file = plugin_dir / "data" / "curator-daemon.pid"
    with contextlib.suppress(FileNotFoundError, ValueError, ProcessLookupError):
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)


def run_go_task_via_worker(
    binary: Path,
    plugin_dir: Path,
    run_db: Path,
    mode: str,
    stash_url: str,
    timeout: float = 300,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Enqueue a task against the Go binary and let its spawned daemon
    execute it, polling get_job_status to a terminal state. Returns the job
    row, or the raw already_running response when coalescing fired."""
    result = run_binary(binary, plugin_dir, task_payload(run_db, stash_url), mode, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)["output"]
    if out.get("already_running") is True:
        return {"state": "already_running", "output": out}
    assert out.get("queued") is True, out
    job_id = out["job_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = run_binary(
            binary, plugin_dir, task_payload(run_db, stash_url, "get_job_status"), env=env
        )
        assert status.returncode == 0, status.stdout + status.stderr
        jobs = json.loads(status.stdout)["output"]["jobs"]
        row = next((job for job in jobs if job["job_id"] == job_id), None)
        if row and row["state"] in ("complete", "failed", "cancelled"):
            return row
        time.sleep(0.1)
    log = plugin_dir / "data" / "curator-daemon.log"
    raise AssertionError(
        f"task {mode} ({job_id}) did not reach a terminal state; daemon log:\n"
        + (log.read_text()[-2000:] if log.exists() else "(no daemon log)")
    )
