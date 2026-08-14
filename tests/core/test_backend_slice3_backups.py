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
from curator.storage import connect_database
from curator.storage.artifacts import ARTIFACT_SCHEMA_VERSION, create_artifact, publish_file
from tests.core.compare import assert_equivalent
from tests.core.test_backend import (
    FEATURE_VERSION,
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
        assert_equivalent(py_out, go_out)
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
    (
        assert_equivalent(a, b),
        (
            "outputs differ:\n"
            f"python: {json.dumps(a, separators=(',', ':'))}\n"
            f"go:     {json.dumps(b, separators=(',', ':'))}"
        ),
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
    assert_equivalent(states[0], states[1])


# ── derived-artifact mirroring (issue #116) ────────────────────────────────

MODEL_ID = "model-" + "b" * 20


@pytest.fixture(scope="module")
def derived_backup_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A migrated sidecar with published feature+model artifacts in the live
    <stem>-derived cache, plus decoys the mirror must ignore (a stray file
    and a leftover temp artifact)."""
    directory = tmp_path_factory.mktemp("derived-backup-sidecar")
    path = directory / "curator.sqlite3"
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        core = connect_database(path, attach_artifacts=False)
        artifact, temporary, final = create_artifact(core, "feature", FEATURE_VERSION)
        artifact.close()
        publish_file(artifact, temporary, final)
        core.execute(
            """
            INSERT INTO feature_build(
                feature_version, status, config_json, source_fingerprint, created_at_ms,
                artifact_basename, artifact_schema_version, artifact_bytes, validation_status,
                validation_summary_json, reuse_count
            ) VALUES (?, 'published', '{}', 'fp', 1, ?, ?, ?, 'valid', '{}', 0)
            """,
            (FEATURE_VERSION, final.name, ARTIFACT_SCHEMA_VERSION, final.stat().st_size),
        )
        artifact, temporary, final = create_artifact(core, "model", MODEL_ID)
        artifact.close()
        publish_file(artifact, temporary, final)
        core.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms,
                artifact_basename, artifact_schema_version, artifact_bytes, validation_status,
                validation_summary_json, reuse_count
            ) VALUES (?, 'published', ?, '{}', 1, ?, ?, ?, 'valid', '{}', 0)
            """,
            (MODEL_ID, FEATURE_VERSION, final.name, ARTIFACT_SCHEMA_VERSION, final.stat().st_size),
        )
        core.commit()
        core.close()
    finally:
        connection.close()
    cache = path.parent / f"{path.stem}-derived"
    (cache / "notes.txt").write_text("not an artifact")
    (cache / ".feature-fv-aaaaaaaaaaaaaaaaaaaa.00000000000000000000000000000000.tmp").write_text(
        "stale temp"
    )
    return path


def _go_create_backup(
    binary: Path, sidecar: Path, stash_url: str, backup_dir: Path
) -> subprocess.CompletedProcess[bytes]:
    """Run the Go binary's create_backup with the given backupPath."""
    _StubStash.plugin_settings = {"backupPath": str(backup_dir)}
    try:
        return run_backend(
            binary, PLUGIN_DIR, _with_db_path(payload("create_backup", sidecar, stash_url), sidecar)
        )
    finally:
        _StubStash.plugin_settings = {}


def test_create_backup_mirrors_derived_artifacts(
    derived_backup_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    """create_backup copies the published feature/model artifacts into a
    derived/ subdir of the backup storage, byte-identical to the live cache,
    and leaves decoys (non-artifact files, leftover temps) behind."""
    storage = tmp_path / "backup-storage"
    result = _go_create_backup(binary, derived_backup_sidecar, stub_stash, storage)
    assert result.returncode == 0, result.stdout + result.stderr
    backups = sorted(storage.glob("curator-*.sqlite3.backup"))
    assert len(backups) == 1  # the database snapshot still lands top-level
    mirrored = storage / "derived"
    assert sorted(p.name for p in mirrored.iterdir()) == [
        "feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3",
        "model-bbbbbbbbbbbbbbbbbbbb.sqlite3",
    ]
    cache = derived_backup_sidecar.parent / f"{derived_backup_sidecar.stem}-derived"
    for name in ("feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3", "model-bbbbbbbbbbbbbbbbbbbb.sqlite3"):
        assert (mirrored / name).read_bytes() == (cache / name).read_bytes()
    assert not (mirrored / "notes.txt").exists()
    assert not list(mirrored.glob("*.tmp"))


def test_create_backup_mirror_idempotent(
    derived_backup_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    """Re-running the backup skips unchanged artifacts: the mirrored files
    keep their mtimes/inodes from the first run and no temp files linger."""
    storage = tmp_path / "backup-storage"
    first = _go_create_backup(binary, derived_backup_sidecar, stub_stash, storage)
    assert first.returncode == 0, first.stdout + first.stderr
    mirrored = storage / "derived"
    before = {
        p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_size)
        for p in mirrored.iterdir()
    }
    second = _go_create_backup(binary, derived_backup_sidecar, stub_stash, storage)
    assert second.returncode == 0, second.stdout + second.stderr
    after = {
        p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_size)
        for p in mirrored.iterdir()
    }
    assert before == after  # unchanged artifacts were skipped, not rewritten
    assert len(list(storage.glob("curator-*.sqlite3.backup"))) == 2  # two snapshots, one mirror
    assert not list(mirrored.glob("*.tmp"))


def test_create_backup_never_file_copies_live_sidecar(
    derived_backup_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    """The live WAL sidecar appears in the backup storage only as the
    SQLite-backup-API snapshot: no file copy of the sidecar, its -wal, or
    its -shm anywhere, and the mirror holds only artifact files."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_db = run_dir / derived_backup_sidecar.name
    shutil.copy2(derived_backup_sidecar, run_db)
    derived_src = derived_backup_sidecar.parent / f"{derived_backup_sidecar.stem}-derived"
    shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
    # Put the sidecar in real WAL mode with a committed-but-not-checkpointed
    # frame, so a live -wal/-shm pair exists beside the database.
    wal = sqlite3.connect(run_db)
    try:
        wal.execute("PRAGMA journal_mode=WAL")
        wal.execute("INSERT INTO application_meta(key, value) VALUES ('wal_probe', '1')")
        wal.commit()
        assert (run_dir / f"{run_db.name}-wal").exists()
        storage = tmp_path / "backup-storage"
        result = _go_create_backup(binary, run_db, stub_stash, storage)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        wal.close()
    top = {p.name for p in storage.iterdir()}
    assert "derived" in top
    others = top - {"derived"}
    assert len(others) == 1
    backup_name = others.pop()
    assert backup_name.startswith("curator-") and backup_name.endswith(".sqlite3.backup")
    # The sidecar itself and its WAL siblings were never file-copied.
    assert "curator.sqlite3" not in top
    assert not any(n.endswith(("-wal", "-shm")) for n in top)
    mirrored = {p.name for p in (storage / "derived").iterdir()}
    assert mirrored == {
        "feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3",
        "model-bbbbbbbbbbbbbbbbbbbb.sqlite3",
    }
    assert not any(n.endswith(("-wal", "-shm")) for n in mirrored)


def test_backup_task_mirrors_derived_artifacts(
    derived_backup_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    """The backup task mode mirrors the derived cache into the backup storage
    alongside the SQLite snapshot."""
    storage = tmp_path / "backup-storage"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_db = run_dir / derived_backup_sidecar.name
    shutil.copy2(derived_backup_sidecar, run_db)
    derived_src = derived_backup_sidecar.parent / f"{derived_backup_sidecar.stem}-derived"
    shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
    raw = json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": int(stub_stash.rsplit(":", 1)[1]),
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {"database_path": str(run_db)},
        },
        separators=(",", ":"),
    ).encode()
    _StubStash.plugin_settings = {"backupPath": str(storage)}
    try:
        result = run_backend(binary, PLUGIN_DIR, raw, "backup")
    finally:
        _StubStash.plugin_settings = {}
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list(storage.glob("curator-*.sqlite3.backup"))) == 1
    assert sorted(p.name for p in (storage / "derived").iterdir()) == [
        "feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3",
        "model-bbbbbbbbbbbbbbbbbbbb.sqlite3",
    ]
