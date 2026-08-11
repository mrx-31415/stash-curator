"""Slice-3 backend differential harness: the backup write ops.

list_backups / create_backup / delete_backup / restore_backup run through the
Go binary and plugin/backend.py on fresh sidecar copies at the same database
path, and the stdout must be byte-identical once the run-varying fields are
handled: backup filenames embed now_ms (create_backup's backup_path and the
items id/created_at_ms; restore's safety_backup). The created backup file is
itself compared sha256-for-sha256 against the Python-made one — both use the
SQLite online-backup API from byte-identical sources — and the restored
sidecar state (model_version/feature_build superseded, current_model_id
removed) is compared table-for-table.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import (
    PLUGIN_DIR,
    _StubStash,
    make_sidecar,
    payload,
    run_backend,
)

REPO_ROOT = Path(__file__).parents[2]
BACKEND = PLUGIN_DIR / "backend.py"


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


def _with_db_path(raw: bytes, db_path: Path) -> bytes:
    parsed = json.loads(raw)
    parsed["args"]["database_path"] = str(db_path)
    return json.dumps(parsed, separators=(",", ":")).encode()


def _strip_key(value: object, key: str) -> None:
    """Remove every key named `key` at any depth."""
    if isinstance(value, dict):
        value.pop(key, None)
        for item in value.values():
            _strip_key(item, key)
    elif isinstance(value, list):
        for item in value:
            _strip_key(item, key)


def assert_slice3_identical(
    binary: Path,
    raw: bytes,
    same_path: Path,
    *,
    normalize: tuple[str, ...] = (),
    ts_paths: bool = False,
) -> None:
    """Run both backends on fresh sidecar copies and compare stdout, after
    dropping the listed keys anywhere in the output; ts_paths additionally
    rewrites curator-<ms>.sqlite3.backup names to a fixed timestamp so the
    embedded run clock does not leak into backup_path/path fields."""
    run_dir = same_path.parent / f"{same_path.stem}-backend-run"
    run_db = run_dir / same_path.name
    outputs: list[subprocess.CompletedProcess[bytes]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(same_path, run_db)
        for name in same_path.parent.iterdir():
            if (
                name.name.startswith(f"{same_path.name}.backup")
                or name.name == "curator-1000.sqlite3.backup"
            ):
                shutil.copy2(name, run_dir / name.name)
        try:
            result = run_backend(runner, PLUGIN_DIR, _with_db_path(raw, run_db))
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        outputs.append(result)
    python_result, go_result = outputs
    assert go_result.returncode == python_result.returncode, (
        python_result.stdout + python_result.stderr + go_result.stdout + go_result.stderr
    )
    py_out = json.loads(python_result.stdout)
    go_out = json.loads(go_result.stdout)
    if python_result.returncode != 0:
        assert py_out == go_out
        return
    a, b = py_out["output"], go_out["output"]
    for field in normalize:
        _strip_key(a, field)
        _strip_key(b, field)
    if ts_paths:
        a_text = re.sub(
            r"curator-\d+\.sqlite3\.backup",
            "curator-T.sqlite3.backup",
            json.dumps(a, separators=(",", ":")),
        )
        b_text = re.sub(
            r"curator-\d+\.sqlite3\.backup",
            "curator-T.sqlite3.backup",
            json.dumps(b, separators=(",", ":")),
        )
        assert a_text == b_text, f"outputs differ:\npython: {a_text}\ngo:     {b_text}"
        return
    assert json.dumps(a, separators=(",", ":")) == json.dumps(b, separators=(",", ":")), (
        "outputs differ:\n"
        f"python: {json.dumps(a, separators=(',', ':'))}\n"
        f"go:     {json.dumps(b, separators=(',', ':'))}"
    )


def _make_backup_of(db_path: Path, backup_path: Path) -> None:
    """A valid Curator backup of a migrated sidecar, via the SQLite backup API."""
    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


@pytest.fixture(scope="module")
def backup_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A migrated sidecar with a published model and a valid backup beside it."""
    directory = tmp_path_factory.mktemp("backup-sidecar")
    path = directory / "curator.sqlite3"
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms, validation_status
            ) VALUES ('model-published', 'published', 'fv-published', '{}', 1, 'valid')
            """
        )
        connection.execute(
            """
            INSERT INTO feature_build(
                feature_version, status, config_json, source_fingerprint, created_at_ms,
                validation_status, validation_summary_json, reuse_count
            ) VALUES ('fv-published', 'published', '{}', 'fp', 1, 'valid', '{}', 0)
            """
        )
        connection.execute(
            """
            INSERT INTO application_meta(key, value) VALUES ('current_model_id', 'model-published')
            """
        )
        connection.commit()
    finally:
        connection.close()
    _make_backup_of(path, directory / "curator-1000.sqlite3.backup")
    _make_backup_of(path, directory / "curator-before-restore-2000.sqlite3.backup")
    # A decoy that must be ignored by list_backups (no pattern match).
    (directory / "not-a-backup.txt").write_text("x")
    return path


# ── byte-identical backup ops ─────────────────────────────────────────────


def test_list_backups_byte_identical(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("list_backups", backup_sidecar, stub_stash)
    assert_slice3_identical(binary, raw, backup_sidecar)


def test_list_backups_missing_directory(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "curator.sqlite3"
    make_sidecar(sidecar)
    missing = tmp_path / "no-such-backup-dir"
    _StubStash.plugin_settings = {"backupPath": str(missing)}
    try:
        raw = payload("list_backups", sidecar, stub_stash)
        assert_slice3_identical(binary, raw, sidecar)
    finally:
        _StubStash.plugin_settings = {}


def test_create_backup_byte_identical(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("create_backup", backup_sidecar, stub_stash)
    assert_slice3_identical(
        binary, raw, backup_sidecar, normalize=("backup_path", "id", "created_at_ms"), ts_paths=True
    )


def test_create_backup_file_parity(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """The Go-made backup matches the Python-made one: same size, both pass
    SQLite quick_check + migration-status validation, and identical logical
    content (the two SQLite implementations may serialize free pages
    differently, so bytes are compared as a canonical content dump)."""
    run_dir = backup_sidecar.parent / f"{backup_sidecar.stem}-parity-run"
    results: list[dict[str, object]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / backup_sidecar.name
        shutil.copy2(backup_sidecar, run_db)
        result = run_backend(
            runner,
            PLUGIN_DIR,
            _with_db_path(payload("create_backup", backup_sidecar, stub_stash), run_db),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        backups = sorted(run_dir.glob("curator-*.sqlite3.backup"))
        assert len(backups) == 1
        backup = backups[0]
        connection = sqlite3.connect(backup)
        try:
            check = connection.execute("PRAGMA quick_check").fetchone()[0]
            page_count = connection.execute("PRAGMA page_count").fetchone()[0]
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            digest = hashlib.sha256()
            for table in tables:
                digest.update(table.encode())
                for row in connection.execute(f"SELECT * FROM {table}"):
                    digest.update(repr(row).encode())
            results.append(
                {
                    "size": backup.stat().st_size,
                    "quick_check": check,
                    "page_count": page_count,
                    "content_sha256": digest.hexdigest(),
                }
            )
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    assert results[0] == results[1]


def test_create_backup_blocked_by_running_job(
    backup_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    connection = sqlite3.connect(backup_sidecar)
    try:
        connection.execute(
            """
            INSERT INTO curator_job(job_id, job_type, state, started_at_ms, summary_json)
            VALUES ('job-running', 'build', 'running', 1, '{}')
            """
        )
        connection.commit()
    finally:
        connection.close()
    try:
        raw = payload("create_backup", backup_sidecar, stub_stash)
        assert_slice3_identical(binary, raw, backup_sidecar)
    finally:
        connection = sqlite3.connect(backup_sidecar)
        try:
            connection.execute("DELETE FROM curator_job WHERE job_id='job-running'")
            connection.commit()
        finally:
            connection.close()


def test_delete_backup_byte_identical(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload(
        "delete_backup",
        backup_sidecar,
        stub_stash,
        backup_id="curator-1000.sqlite3.backup",
        confirmation="DELETE curator-1000.sqlite3.backup",
    )
    assert_slice3_identical(binary, raw, backup_sidecar)


def test_delete_backup_wrong_confirmation(
    backup_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "delete_backup",
        backup_sidecar,
        stub_stash,
        backup_id="curator-1000.sqlite3.backup",
        confirmation="DELETE curator-9999.sqlite3.backup",
    )
    assert_slice3_identical(binary, raw, backup_sidecar)


def test_delete_backup_unknown_id(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload(
        "delete_backup",
        backup_sidecar,
        stub_stash,
        backup_id="curator-0000.sqlite3.backup",
        confirmation="DELETE curator-0000.sqlite3.backup",
    )
    assert_slice3_identical(binary, raw, backup_sidecar)


def test_restore_backup_byte_identical(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload(
        "restore_backup",
        backup_sidecar,
        stub_stash,
        backup_id="curator-1000.sqlite3.backup",
        confirmation="RESTORE curator-1000.sqlite3.backup",
    )
    assert_slice3_identical(binary, raw, backup_sidecar, normalize=("safety_backup",))


def test_restore_backup_state_parity(backup_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """After restore both implementations leave the same sidecar state:
    published model_version/feature_build rows superseded with
    restore_invalidated, current_model_id removed, and a valid safety
    backup."""
    run_dir = backup_sidecar.parent / f"{backup_sidecar.stem}-restore-state"
    states: list[dict[str, object]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / backup_sidecar.name
        shutil.copy2(backup_sidecar, run_db)
        shutil.copy2(
            backup_sidecar.parent / "curator-1000.sqlite3.backup",
            run_dir / "curator-1000.sqlite3.backup",
        )
        result = run_backend(
            runner,
            PLUGIN_DIR,
            _with_db_path(
                payload(
                    "restore_backup",
                    backup_sidecar,
                    stub_stash,
                    backup_id="curator-1000.sqlite3.backup",
                    confirmation="RESTORE curator-1000.sqlite3.backup",
                ),
                run_db,
            ),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            states.append(
                {
                    "model_version": connection.execute(
                        "SELECT model_id, status, validation_status"
                        " FROM model_version ORDER BY model_id"
                    ).fetchall(),
                    "feature_build": connection.execute(
                        "SELECT feature_version, status, validation_status"
                        " FROM feature_build ORDER BY feature_version"
                    ).fetchall(),
                    "current_model_id": connection.execute(
                        "SELECT value FROM application_meta WHERE key='current_model_id'"
                    ).fetchall(),
                    "schema_migration": connection.execute(
                        "SELECT count(*) FROM schema_migration"
                    ).fetchone(),
                }
            )
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    assert states[0] == states[1]
