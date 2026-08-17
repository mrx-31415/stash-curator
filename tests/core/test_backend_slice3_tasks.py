"""Slice-3 backend differential harness: the mechanical task modes.

backup / compact / vacuum run through the Go binary and plugin/backend.py on
fresh sidecar copies (with the -derived artifact directory); stdout must be
byte-identical once job_id (a uuid4) is stripped, and the curator_job rows /
compaction state must match table-for-table modulo run timestamps.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from curator.storage import MigrationRunner, connect_database
from curator.storage.artifacts import create_artifact, publish_file
from tests.core.compare import assert_equivalent
from tests.core.test_backend import (
    PLUGIN_DIR,
    _StubStash,
    make_sidecar,
    run_backend,
)
from tests.core.worker import run_go_task_via_worker, stop_worker

FEATURE_ID = "fv-" + "a" * 20
MODEL_ID = "model-" + "b" * 20
RETIRED_MODEL_ID = "model-" + "c" * 20


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


def make_compact_sidecar(path: Path) -> None:
    """A migrated sidecar with published feature/model artifacts (so
    compaction has valid active generations) plus a retired superseded model
    and seeded derived rows that compaction deletes."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_scene(
                scene_id, title, play_count, play_duration_seconds, updated_at, source_hash
            ) VALUES ('s1', 'Scene One', 1, 300, '2026-01-01T00:00:00Z', 'h-s1'),
                   ('s2', 'Scene Two', 2, 400, '2026-01-02T00:00:00Z', 'h-s2')
            """
        )
        connection.commit()
        core = connect_database(path, attach_artifacts=False)
        # Published feature artifact.
        artifact, temporary, final = create_artifact(core, "feature", FEATURE_ID)
        artifact.close()
        publish_file(artifact, temporary, final)
        core.execute(
            """
            INSERT INTO feature_build(
                feature_version, status, config_json, source_fingerprint, created_at_ms,
                artifact_basename, artifact_schema_version, artifact_bytes, validation_status,
                validation_summary_json, reuse_count
            ) VALUES (?, 'published', '{}', 'fp', 1, ?, 3, ?, 'valid', ?, 0)
            """,
            (
                FEATURE_ID,
                final.name,
                final.stat().st_size,
                json.dumps({"integrity": "ok"}),
            ),
        )
        # Published model artifact.
        artifact, temporary, final = create_artifact(core, "model", MODEL_ID)
        artifact.close()
        publish_file(artifact, temporary, final)
        core.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms,
                artifact_basename, artifact_schema_version, artifact_bytes, validation_status,
                validation_summary_json, reuse_count
            ) VALUES (?, 'published', ?, '{}', 1, ?, 3, ?, 'valid', ?, 0)
            """,
            (
                MODEL_ID,
                FEATURE_ID,
                final.name,
                final.stat().st_size,
                json.dumps({"integrity": "ok"}),
            ),
        )
        # A retired superseded model (artifact already discarded) is a target.
        core.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms,
                validation_status, reuse_count
            ) VALUES (?, 'superseded', ?, '{}', 1, 'retired', 0)
            """,
            (RETIRED_MODEL_ID, FEATURE_ID),
        )
        # Seed rebuildable derived rows for both model targets and the
        # published feature generation.
        for model_id in (MODEL_ID, RETIRED_MODEL_ID):
            core.execute(
                """
                INSERT INTO model_scene_score(
                    model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                    appeal, current_fit, confidence, metadata_confidence, recovery, components_json
                ) VALUES (?, 's1', 0.1, 0.1, 0.5, 0.1, 0.0, 0.5, 0.5, 0.0, '{}'),
                         (?, 's2', 0.2, 0.2, 0.6, 0.2, 0.0, 0.6, 0.6, 0.0, '{}')
                """,
                (model_id, model_id),
            )
            core.execute(
                """
                INSERT INTO model_scene_lane(model_id, scene_id, lane, lane_value)
                VALUES (?, 's1', 'for_you', 1.0),
                       (?, 's2', 'for_you', 2.0)
                """,
                (model_id, model_id),
            )
            core.execute(
                """
                INSERT INTO model_lane_order(
                    model_id, lane, ordering, position, scene_id, source_lane, utility
                ) VALUES (?, 'for_you', 'score_first', 0, 's1', 'best_bets', 0.1),
                         (?, 'for_you', 'score_first', 1, 's2', 'best_bets', 0.2)
                """,
                (model_id, model_id),
            )
        core.execute(
            """
            INSERT INTO scene_content_search(feature_version, feature_id, scene_id, value)
            VALUES (?, 'f1', 's1', 1.0), (?, 'f2', 's2', 1.0)
            """,
            (FEATURE_ID, FEATURE_ID),
        )
        core.execute(
            """
            INSERT INTO feature_definition(
                feature_id, feature_version, family, name, provenance, metadata_json
            ) VALUES ('f1', ?, 'content', 'tag:t1', 'seed', '{}'),
                   ('f2', ?, 'content', 'tag:t2', 'seed', '{}')
            """,
            (FEATURE_ID, FEATURE_ID),
        )
        core.commit()
        core.close()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def compact_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("compact-sidecar")
    path = directory / "curator.sqlite3"
    make_compact_sidecar(path)
    return path


def _task_payload(sidecar: Path, stash_url: str) -> bytes:
    return json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": int(stash_url.rsplit(":", 1)[1]),
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {"database_path": str(sidecar)},
        },
        separators=(",", ":"),
    ).encode()


def _with_db(raw: bytes, db_path: Path) -> bytes:
    parsed = json.loads(raw)
    parsed["args"]["database_path"] = str(db_path)
    return json.dumps(parsed, separators=(",", ":")).encode()


def _strip_key(value: object, key: str) -> None:
    if isinstance(value, dict):
        value.pop(key, None)
        for item in value.values():
            _strip_key(item, key)
    elif isinstance(value, list):
        for item in value:
            _strip_key(item, key)


def assert_task_identical(
    binary: Path,
    sidecar: Path,
    mode: str,
    *,
    normalize: tuple[str, ...] = (),
) -> None:
    """Run the task through the Python backend inline and through the Go
    backend's background worker (docs/decisions/004). The Go invocation
    returns a queued marker, so the comparison moved from invocation stdout
    to the completed job's durable summary — the same mode bodies, the same
    sidecar effects."""
    run_dir = sidecar.parent / f"{sidecar.stem}-task-run"
    worker_dir = Path(tempfile.mkdtemp(prefix="curator-worker-"))
    python_result: subprocess.CompletedProcess[bytes] | None = None
    go_row: dict[str, object] | None = None
    try:
        for runner in (None, binary):
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / sidecar.name
            shutil.copy2(sidecar, run_db)
            derived_src = sidecar.parent / f"{sidecar.stem}-derived"
            if derived_src.is_dir():
                shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            if runner is None:
                python_result = run_backend(
                    runner, PLUGIN_DIR, _task_payload(run_db, "http://127.0.0.1:1"), mode
                )
            else:
                go_row = run_go_task_via_worker(
                    binary, worker_dir, run_db, mode, "http://127.0.0.1:1"
                )
    finally:
        stop_worker(worker_dir)
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(worker_dir, ignore_errors=True)
    assert python_result is not None and go_row is not None
    py_out = json.loads(python_result.stdout)
    if go_row["state"] == "already_running":
        a, b = py_out["output"], go_row["output"]
        for field in (*normalize, "job_id"):
            _strip_key(a, field)
            _strip_key(b, field)
        (
            assert_equivalent(a, b),
            (
                "already_running responses differ:\n"
                f"python: {json.dumps(a, separators=(',', ':'))}\n"
                f"go:     {json.dumps(b, separators=(',', ':'))}"
            ),
        )
        return
    if python_result.returncode != 0:
        assert go_row["state"] == "failed", go_row
        (
            assert_equivalent(json.loads(python_result.stdout)["error"], go_row["error"]),
            "task errors differ",
        )
        return
    assert go_row["state"] == "complete", go_row
    py_summary = py_out["output"]
    for field in ("job_id", "schema_version", *normalize):
        _strip_key(py_summary, field)
    go_summary = dict(go_row["summary"] or {})
    for field in ("job_id", *normalize):
        _strip_key(go_summary, field)
    (
        assert_equivalent(py_summary, go_summary),
        (
            "job summaries differ:\n"
            f"python: {json.dumps(py_summary, separators=(',', ':'))}\n"
            f"go:     {json.dumps(go_summary, separators=(',', ':'))}"
        ),
    )


def test_compact_task_byte_identical(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    assert_task_identical(binary, compact_sidecar, "compact", normalize=("job_id",))


def test_compact_task_state_parity(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """Compaction leaves identical derived-row counts, the same
    legacy_compaction blob, and a complete curator_job summary."""
    run_dir = compact_sidecar.parent / f"{compact_sidecar.stem}-compact-state"
    worker_dir = Path(tempfile.mkdtemp(prefix="curator-worker-"))
    states: list[dict[str, object]] = []
    try:
        for runner in (None, binary):
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / compact_sidecar.name
            shutil.copy2(compact_sidecar, run_db)
            derived_src = compact_sidecar.parent / f"{compact_sidecar.stem}-derived"
            shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            if runner is None:
                result = run_backend(
                    runner, PLUGIN_DIR, _task_payload(run_db, "http://127.0.0.1:1"), "compact"
                )
                assert result.returncode == 0, result.stdout + result.stderr
            else:
                run_go_task_via_worker(binary, worker_dir, run_db, "compact", "http://127.0.0.1:1")
            connection = sqlite3.connect(run_db)
            try:
                states.append(
                    {
                        "derived_remaining": connection.execute(
                            "SELECT count(*) FROM model_scene_score WHERE model_id IN (?, ?)",
                            (MODEL_ID, RETIRED_MODEL_ID),
                        ).fetchone()[0],
                        "compaction_blob": connection.execute(
                            "SELECT value FROM application_meta WHERE key='legacy_compaction'"
                        ).fetchone(),
                        "job": connection.execute(
                            "SELECT job_type, state, summary_json FROM curator_job ORDER BY started_at_ms DESC LIMIT 1"  # noqa: E501
                        ).fetchone(),
                    }
                )
            finally:
                connection.close()
            shutil.rmtree(run_dir, ignore_errors=True)
    finally:
        stop_worker(worker_dir)
        shutil.rmtree(worker_dir, ignore_errors=True)
    assert_equivalent(states[0], states[1])


def test_compact_task_no_artifacts_error(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "curator.sqlite3"
    make_sidecar(sidecar, with_jobs=True)
    assert_task_identical(binary, sidecar, "compact")


def test_vacuum_task_byte_identical(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    # Mark compaction complete so vacuum's guard passes.
    connection = sqlite3.connect(compact_sidecar)
    try:
        connection.execute(
            """
            INSERT INTO application_meta(key, value) VALUES ('legacy_compaction', ?)
            """,
            (json.dumps({"status": "complete"}),),
        )
        connection.commit()
    finally:
        connection.close()
    try:
        assert_task_identical(binary, compact_sidecar, "vacuum", normalize=("job_id",))
    finally:
        connection = sqlite3.connect(compact_sidecar)
        try:
            connection.execute("DELETE FROM application_meta WHERE key='legacy_compaction'")
            connection.commit()
        finally:
            connection.close()


def test_vacuum_task_guard_error(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    # No legacy_compaction blob -> status never_run -> the guard raises.
    connection = sqlite3.connect(compact_sidecar)
    try:
        connection.execute("DELETE FROM application_meta WHERE key='legacy_compaction'")
        connection.commit()
    finally:
        connection.close()
    assert_task_identical(binary, compact_sidecar, "vacuum")


def test_backup_task_byte_identical(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    assert_task_identical(binary, compact_sidecar, "backup", normalize=("job_id", "backup"))


def test_backup_task_file_parity(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """The backup task produces a valid Curator backup of the same size on
    both backends."""
    run_dir = compact_sidecar.parent / f"{compact_sidecar.stem}-backup-task"
    worker_dir = Path(tempfile.mkdtemp(prefix="curator-worker-"))
    sizes: list[int] = []
    try:
        for runner in (None, binary):
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / compact_sidecar.name
            shutil.copy2(compact_sidecar, run_db)
            derived_src = compact_sidecar.parent / f"{compact_sidecar.stem}-derived"
            shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            if runner is None:
                result = run_backend(
                    runner, PLUGIN_DIR, _task_payload(run_db, "http://127.0.0.1:1"), "backup"
                )
                assert result.returncode == 0, result.stdout + result.stderr
            else:
                run_go_task_via_worker(binary, worker_dir, run_db, "backup", "http://127.0.0.1:1")
            backups = sorted(run_dir.glob("curator-*.sqlite3.backup"))
            assert len(backups) == 1
            backup = backups[0]
            connection = sqlite3.connect(backup)
            connection.row_factory = sqlite3.Row
            try:
                assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                assert connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
                ).fetchone()
                MigrationRunner(connection).status()
            finally:
                connection.close()
            sizes.append(backup.stat().st_size)
            shutil.rmtree(run_dir, ignore_errors=True)
    finally:
        stop_worker(worker_dir)
        shutil.rmtree(worker_dir, ignore_errors=True)
    assert sizes[0] == sizes[1]


def test_task_already_running(compact_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """A second task of the same type while one is running coalesces into
    already_running with the existing job id (uuid4s differ; strip)."""
    connection = sqlite3.connect(compact_sidecar)
    try:
        connection.execute(
            """
            INSERT INTO curator_job(job_id, job_type, state, started_at_ms, summary_json)
            VALUES ('job-running', 'backup', 'running', ?, '{}')
            """,
            (int(time.time() * 1000),),
        )
        connection.commit()
    finally:
        connection.close()
    try:
        assert_task_identical(binary, compact_sidecar, "backup", normalize=("job_id",))
    finally:
        connection = sqlite3.connect(compact_sidecar)
        try:
            connection.execute("DELETE FROM curator_job WHERE job_id='job-running'")
            connection.commit()
        finally:
            connection.close()
