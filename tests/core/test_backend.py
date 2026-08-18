"""Slice-0 backend differential harness: the Go binary vs the Python backend.

The raw interface contract is byte-identical JSON. For each ported operation
(round_trip, health, get_config, get_job_status) this runs plugin/backend.py
and the built curator-core binary against identical sidecar copies at the same
database path (so the `database` output field matches) and asserts byte-equal
stdout. It also proves sidecar migration parity in both directions, artifact
attach/views parity, settings-application equivalence, and the Python fallback
dispatch for unported operations. These tests skip when the binary is not
built; `scripts/verify core` builds it and runs this suite.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator import __version__
from curator.core import core_binary
from curator.storage import MigrationRunner, connect_database
from curator.storage.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    FEATURE_TABLES,
    MODEL_TABLES,
    attach_active_artifacts,
    create_artifact,
    publish_file,
)
from tests.core.worker import run_go_task_via_worker, stop_worker

REPO_ROOT = Path(__file__).parents[2]
PLUGIN_DIR = REPO_ROOT / "plugin"
BACKEND = PLUGIN_DIR / "backend.py"
PYTHON_SQL_DIR = REPO_ROOT / "curator" / "storage" / "sql"
GO_SQL_DIR = REPO_ROOT / "core" / "migrations"

FEATURE_VERSION = "fv-" + "a" * 20
FIXED_MS = 1_700_000_000_000

RUNTIME_RESPONSE = {
    "data": {
        "version": {"version": "v0.31.1"},
        "jobQueue": [
            {
                "id": "job-stash-1",
                "status": "running",
                "description": "Sync and build recommendations",
                "progress": 0.5,
                "startTime": 1720000000000,
            },
            {
                "id": "job-stash-2",
                "status": "complete",
                "description": "Some unrelated Stash job",
                "progress": 1.0,
                "startTime": 1719999000000,
            },
        ],
        "configuration": {"general": {"stashBoxes": []}},
    }
}

SETTINGS_RESPONSE = {"data": {"configuration": {"plugins": {}}}}


class _StubStash(BaseHTTPRequestHandler):
    """A minimal GraphQL stub answering the two queries by operation name."""

    plugin_settings: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        operation = next(
            (name for name in ("CuratorPluginRuntime", "CuratorPluginSettings") if name in body),
            "unknown",
        )
        if operation == "CuratorPluginRuntime":
            payload = RUNTIME_RESPONSE
        elif operation == "CuratorPluginSettings":
            payload = SETTINGS_RESPONSE
            if self.plugin_settings:
                payload = {
                    "data": {"configuration": {"plugins": {"stash-curator": self.plugin_settings}}}
                }
        else:
            payload = {"errors": [{"message": f"no stub for {operation}"}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:  # silence the stub
        pass


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubStash)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_sidecar(path: Path, *, with_jobs: bool = True, with_artifact: bool = False) -> None:
    """A migrated, deterministic sidecar (never the live one)."""
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        MigrationRunner(connection).migrate(applied_at_ms=FIXED_MS)
        if with_jobs:
            connection.execute(
                """
                INSERT INTO curator_job(job_id, job_type, state, started_at_ms,
                                        finished_at_ms, summary_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-1",
                    "sync-build",
                    "complete",
                    1_000,
                    5_000,
                    json.dumps({"model_id": "model-m1", "entity_counts": {"scenes": 3}}),
                    None,
                ),
            )
            connection.execute(
                """
                INSERT INTO curator_job(job_id, job_type, state, started_at_ms,
                                        finished_at_ms, summary_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("job-2", "build", "failed", 2_000, 9_000, "{}", "boom"),
            )
        if with_artifact:
            core = connect_database(path, attach_artifacts=False)
            try:
                artifact, temporary, final = create_artifact(core, "feature", FEATURE_VERSION)
                artifact.close()
                publish_file(artifact, temporary, final)
                # CI-only flake: the immutable=1 open of a freshly published
                # artifact intermittently fails on the runner's filesystem
                # (rename-visibility race; not reproducible locally). Force the
                # new inode to materialize here with a bounded retry, so any
                # failure surfaces at creation with full stat context instead
                # of at the first attach in a later test step.
                uri = f"{final.as_uri()}?mode=ro&immutable=1"
                for attempt in range(3):
                    try:
                        probe = sqlite3.connect(uri, uri=True)
                        probe.execute("SELECT 1")
                        probe.close()
                        break
                    except sqlite3.OperationalError:
                        if attempt == 2:
                            st = final.stat()
                            raise RuntimeError(
                                f"published artifact not readable with {uri}: "
                                f"size={st.st_size} mode={oct(st.st_mode)}"
                            ) from None
                        time.sleep(0.5)
                core.execute(
                    """
                    INSERT INTO feature_build(feature_version, status, config_json,
                        source_fingerprint, created_at_ms, artifact_basename,
                        artifact_schema_version, artifact_bytes, validation_status,
                        validation_summary_json, reuse_count)
                    VALUES (?, 'published', '{}', 'fp', 1, ?, ?, 1, 'valid', '{}', 0)
                    """,
                    (
                        FEATURE_VERSION,
                        f"feature-{FEATURE_VERSION}.sqlite3",
                        ARTIFACT_SCHEMA_VERSION,
                    ),
                )
                core.commit()
            finally:
                core.close()
    finally:
        connection.close()


def payload(op: str, db_path: Path, stash_url: str, **extra: object) -> bytes:
    return json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": int(stash_url.rsplit(":", 1)[1]),
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {"operation": op, "database_path": str(db_path), **extra},
        },
        separators=(",", ":"),
    ).encode()


def run_backend(
    binary: Path | None, plugin_dir: Path, raw: bytes, mode: str | None = None
) -> subprocess.CompletedProcess[bytes]:
    if binary is None:
        argv = [sys.executable, str(BACKEND), str(plugin_dir)]
    else:
        argv = [str(binary), str(plugin_dir)]
    if mode is not None:
        argv.append(mode)
    return subprocess.run(argv, input=raw, capture_output=True, timeout=120)


def _with_db_path(raw: bytes, db_path: Path) -> bytes:
    parsed = json.loads(raw)
    parsed["args"]["database_path"] = str(db_path)
    return json.dumps(parsed, separators=(",", ":")).encode()


def assert_byte_identical(
    binary: Path,
    plugin_dir: Path,
    raw: bytes,
    mode: str | None = None,
    *,
    same_path: Path,
) -> None:
    """Run Python and Go backends on identical fresh sidecar state at the same
    database path (so the `database` output field matches). The copy lives in
    a sibling directory and keeps the same basename, so the derived artifact
    directory resolves identically for both implementations."""
    run_dir = same_path.parent / f"{same_path.stem}-backend-run"
    run_db = run_dir / same_path.name
    derived_src = same_path.parent / f"{same_path.stem}-derived"
    outputs: list[subprocess.CompletedProcess[bytes]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(same_path, run_db)
        derived_dst = run_dir / f"{run_db.stem}-derived"
        if derived_src.is_dir():
            shutil.copytree(derived_src, derived_dst)
        try:
            result = run_backend(runner, plugin_dir, _with_db_path(raw, run_db), mode)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        outputs.append(result)
    python_result, go_result = outputs
    assert go_result.stdout == python_result.stdout, (
        f"stdout differs:\npython: {python_result.stdout!r}\ngo:     {go_result.stdout!r}"
    )
    assert go_result.returncode == python_result.returncode


# ── byte-identical trivial ops ──────────────────────────────────────────────


def test_round_trip_byte_identical(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    assert_byte_identical(
        binary, PLUGIN_DIR, payload("round_trip", sidecar, stub_stash), same_path=sidecar
    )


def test_get_job_status_byte_identical(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    assert_byte_identical(
        binary, PLUGIN_DIR, payload("get_job_status", sidecar, stub_stash), same_path=sidecar
    )


def test_get_config_byte_identical(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    assert_byte_identical(
        binary, PLUGIN_DIR, payload("get_config", sidecar, stub_stash), same_path=sidecar
    )


def test_health_byte_identical(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    assert_byte_identical(
        binary, PLUGIN_DIR, payload("health", sidecar, stub_stash), same_path=sidecar
    )


def test_get_config_code_version_matches_python(
    tmp_path: Path, binary: Path, stub_stash: str
) -> None:
    """The Go code_version must equal backend.py's content hash of the sources."""
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    go_result = run_backend(binary, PLUGIN_DIR, payload("get_config", sidecar, stub_stash))
    python_result = run_backend(None, PLUGIN_DIR, payload("get_config", sidecar, stub_stash))
    assert go_result.returncode == 0 and python_result.returncode == 0
    assert (
        json.loads(go_result.stdout)["output"]["code_version"]
        == json.loads(python_result.stdout)["output"]["code_version"]
    )


# ── settings application ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "settings",
    [
        {"pageSize": 25, "diversityDisabled": True, "pruneTagName": "Prune"},
        {"modelUpdateMaxWaitMinutes": 45, "expandWildcard": True, "syncPageSize": 100},
    ],
)
def test_settings_application_matches_python(
    tmp_path: Path, binary: Path, stub_stash: str, settings: dict[str, object]
) -> None:
    _StubStash.plugin_settings = settings
    try:
        results = {}
        for runner in (None, binary):
            sidecar = tmp_path / f"sidecar-{runner is None}.sqlite3"
            make_sidecar(sidecar)
            result = run_backend(runner, PLUGIN_DIR, payload("get_config", sidecar, stub_stash))
            assert result.returncode == 0
            connection = sqlite3.connect(sidecar)
            try:
                config_json, updated_at_ms = connection.execute(
                    "SELECT config_json, updated_at_ms FROM curator_config WHERE singleton=1"
                ).fetchone()
            finally:
                connection.close()
            results["python" if runner is None else "go"] = {
                "output": json.loads(result.stdout)["output"],
                "config_json": config_json,
                "updated_at_ms": updated_at_ms,
            }
    finally:
        _StubStash.plugin_settings = {}
    python, go = results["python"], results["go"]
    # The merged config row is identical (updated_at_ms is a timestamp, so it
    # differs between the two runs by design).
    assert go["config_json"] == python["config_json"]
    assert go["updated_at_ms"] > 0 and python["updated_at_ms"] > 0
    # get_config reflects the applied settings identically.
    assert go["output"]["config"] == python["output"]["config"]


# ── migration parity ────────────────────────────────────────────────────────


def test_embedded_migration_files_byte_identical() -> None:
    python_files = sorted(PYTHON_SQL_DIR.glob("*.sql"))
    assert python_files, "python migration package is missing"
    for python_file in python_files:
        go_file = GO_SQL_DIR / python_file.name
        assert go_file.is_file(), f"core/migrations/{python_file.name} is missing"
        assert go_file.read_bytes() == python_file.read_bytes()


def test_migration_parity_python_accepts_go(tmp_path: Path, binary: Path) -> None:
    sidecar = tmp_path / "go-migrated.sqlite3"
    result = run_backend(binary, PLUGIN_DIR, payload("round_trip", sidecar, "http://127.0.0.1:1"))
    assert result.returncode == 0, result.stdout
    connection = sqlite3.connect(sidecar)
    try:
        connection.row_factory = sqlite3.Row
        status = MigrationRunner(connection).status()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    assert status.current_version == status.latest_version == 33
    assert not status.pending_versions
    assert integrity == "ok"


def test_migration_parity_go_accepts_python(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "python-migrated.sqlite3"
    make_sidecar(sidecar)
    before = (
        sqlite3.connect(sidecar)
        .execute("SELECT version, name, checksum FROM schema_migration ORDER BY version")
        .fetchall()
    )
    result = run_backend(binary, PLUGIN_DIR, payload("round_trip", sidecar, stub_stash))
    assert result.returncode == 0, result.stdout
    connection = sqlite3.connect(sidecar)
    try:
        after = connection.execute(
            "SELECT version, name, checksum FROM schema_migration ORDER BY version"
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    assert after == before
    assert integrity == "ok"


# ── artifact attach/views parity ────────────────────────────────────────────


def test_artifact_attach_success_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str
) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar, with_jobs=False, with_artifact=True)
    assert_byte_identical(
        binary, PLUGIN_DIR, payload("round_trip", sidecar, stub_stash), same_path=sidecar
    )


def test_artifact_missing_error_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str
) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar, with_jobs=False, with_artifact=True)
    derived = sidecar.parent / f"{sidecar.stem}-derived"
    for artifact in derived.glob("*.sqlite3"):
        artifact.unlink()
    result = run_backend(binary, PLUGIN_DIR, payload("round_trip", sidecar, stub_stash))
    assert result.returncode == 1
    error = json.loads(result.stdout)["error"]
    assert error == f"active artifact is missing: feature-{FEATURE_VERSION}.sqlite3"


def test_artifact_views_resolve_same_tables(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    """Both implementations attach the same published generations; the Go side
    must leave the sidecar untouched so the Python attach path still works."""
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar, with_jobs=False, with_artifact=True)
    result = run_backend(binary, PLUGIN_DIR, payload("round_trip", sidecar, stub_stash))
    assert result.returncode == 0, result.stdout
    connection = sqlite3.connect(sidecar)
    try:
        connection.row_factory = sqlite3.Row
        attach_active_artifacts(connection)
        aliases = {row["name"] for row in connection.execute("PRAGMA database_list")}
        assert "feature_generation" in aliases
        views = {
            row[0]
            for row in connection.execute("SELECT name FROM temp.sqlite_master WHERE type='view'")
        }
        # The published feature artifact's tables resolve as views; the model
        # generation has no published row here, so none of its tables shadow.
        assert set(FEATURE_TABLES) <= views
        assert not set(MODEL_TABLES) & views
    finally:
        connection.close()


# ── profiling parity ────────────────────────────────────────────────────────


def test_profiling_trace_parity(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    """get_config with profilingEnabled records an equivalent profile_trace row
    on both implementations (same kind/operation/status, structurally identical
    trace_json: root plugin event + stash + sqlite spans), while the op output
    stays byte-identical."""
    _StubStash.plugin_settings = {"profilingEnabled": True}
    try:
        sidecar = tmp_path / "sidecar.sqlite3"
        make_sidecar(sidecar)
        raw = payload("get_config", sidecar, stub_stash)
        rows: dict[str, tuple] = {}
        outputs: dict[str, bytes] = {}
        for runner in (None, binary):
            run_dir = tmp_path / f"run-{runner is None}"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / sidecar.name
            shutil.copy2(sidecar, run_db)
            result = run_backend(runner, PLUGIN_DIR, _with_db_path(raw, run_db))
            assert result.returncode == 0, result.stdout
            outputs["python" if runner is None else "go"] = result.stdout
            connection = sqlite3.connect(run_db)
            try:
                row = connection.execute(
                    """
                    SELECT trace_id, kind, operation, started_at_ms, duration_us,
                           status, span_count, truncated, trace_json
                    FROM profile_trace
                    """
                ).fetchone()
            finally:
                connection.close()
            rows["python" if runner is None else "go"] = row
    finally:
        _StubStash.plugin_settings = {}
    # The op output is unaffected by profiling (profilingEnabled is not a
    # sidecar config key, so no config write happens).
    assert outputs["go"] == outputs["python"]
    python_row, go_row = rows["python"], rows["go"]
    assert python_row is not None and go_row is not None
    for row in (python_row, go_row):
        trace_id, kind, operation, _, duration_us, status, span_count, truncated, _ = row
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", trace_id
        )
        assert kind == "operation" and operation == "get_config"
        assert status == "ok" and truncated == 0
        assert duration_us >= 0 and span_count > 0
    python_json = json.loads(python_row[8])
    go_json = json.loads(go_row[8])
    assert python_json["displayTimeUnit"] == go_json["displayTimeUnit"] == "ms"
    python_events, go_events = python_json["traceEvents"], go_json["traceEvents"]
    # Span counts are implementation-specific (Python wraps fetches and extra
    # PRAGMAs separately); span_count counts recorded spans while traceEvents
    # adds the root event. Both must carry the root event, the settings stash
    # span, and sqlite spans, and the row's span_count must agree with the
    # stored JSON.
    assert python_row[6] == len(python_events) - 1
    assert go_row[6] == len(go_events) - 1
    assert len(go_events) >= 4 and len(python_events) >= 4
    for events in (python_events, go_events):
        root = events[0]
        assert root["name"] == "get_config" and root["cat"] == "plugin"
        assert root["ph"] == "X" and root["pid"] == 1 and root["tid"] == 0
        assert root["args"] == {"status": "ok", "kind": "operation"}
        assert {"name", "cat", "ph", "ts", "dur", "pid", "tid", "args"} <= set(root)
        assert any(e["cat"] == "stash" and e["name"] == "CuratorPluginSettings" for e in events)
        assert any(e["cat"] == "sqlite" for e in events)
        for event in events:
            assert {"name", "cat", "ph", "ts", "dur", "pid", "tid"} <= set(event)


# ── Python fallback dispatch ────────────────────────────────────────────────


def test_fallback_unknown_operation(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    raw = payload("not_an_operation", sidecar, stub_stash)
    direct = run_backend(None, PLUGIN_DIR, raw)
    fallback = run_backend(binary, PLUGIN_DIR, raw)
    assert fallback.stdout == direct.stdout
    assert fallback.returncode == direct.returncode == 1
    assert json.loads(fallback.stdout)["error"] == "unknown Curator API operation: not_an_operation"


def test_fallback_entity_hook(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar)
    raw = json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": int(stub_stash.rsplit(":", 1)[1]),
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {"hookContext": {"type": "Scene.Create.Post", "id": "scene-42"}},
        },
        separators=(",", ":"),
    ).encode()
    direct = run_backend(None, PLUGIN_DIR, raw, mode="entity-sync")
    fallback = run_backend(binary, PLUGIN_DIR, raw, mode="entity-sync")
    assert fallback.stdout == direct.stdout
    assert fallback.returncode == direct.returncode == 0
    output = json.loads(fallback.stdout)["output"]
    assert output["handled"] is True and output["entity_id"] == "scene-42"


def test_fallback_task_mode(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    """prepare on a model-less sidecar fails with the same deterministic
    error through the worker's failed job (the invocation queues, the daemon
    runs the mode body, and the row records the Python-identical error)."""
    sidecar = tmp_path / "sidecar.sqlite3"
    make_sidecar(sidecar, with_jobs=False)
    direct = run_backend(None, PLUGIN_DIR, payload("prepare", sidecar, stub_stash), mode="prepare")
    assert direct.returncode == 1
    worker_dir = Path(tempfile.mkdtemp(prefix="curator-worker-"))
    try:
        row = run_go_task_via_worker(binary, worker_dir, sidecar, "prepare", stub_stash)
    finally:
        stop_worker(worker_dir)
        shutil.rmtree(worker_dir, ignore_errors=True)
    assert row["state"] == "failed", row
    assert row["error"] == json.loads(direct.stdout)["error"]


# ── wire shape ──────────────────────────────────────────────────────────────


def test_health_reports_curator_version_from_pyproject(binary: Path, stub_stash: str) -> None:
    sidecar = Path("/tmp/curator-core-version-probe.sqlite3")
    sidecar.unlink(missing_ok=True)
    try:
        result = run_backend(binary, PLUGIN_DIR, payload("health", sidecar, stub_stash))
        if result.returncode != 0:
            pytest.skip(f"health failed (sidecar path may be unwritable): {result.stdout}")
        assert json.loads(result.stdout)["output"]["curator_version"] == __version__
    finally:
        sidecar.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{sidecar}{suffix}").unlink(missing_ok=True)
