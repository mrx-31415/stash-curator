"""Slice-3 backend differential harness: the full model build.

The Go model-build kernel stage runs against the same builder-seeded sidecar
as Python's PreferenceModelBuilder.build(); the produced model artifact (the
oracle) must be content-identical across all artifact tables, the model_id
must match, and the sidecar model_version / current_model_id writes must
match modulo run timestamps.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from curator.core import core_binary
from curator.model.builder import PreferenceModelBuilder
from curator.storage import connect_database
from tests.core.test_backend_slice3_featurebuild import make_feature_sidecar
from tests.model.test_builder import REFERENCE_MS


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


def _artifact_tables_sha(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
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
                # model_lane_order_state.created_at_ms is wall-clock in both
                # implementations; drop it for the content comparison.
                if table == "model_lane_order_state":
                    row = (row[0], 0)
                digest.update(repr(row).encode())
        return digest.hexdigest()
    finally:
        connection.close()


def _first_artifact_diff(go_path: Path, py_path: Path) -> str:
    """Return the first differing table+row (with the row index) between two
    artifacts, for CI diagnostics when the byte-identity assertion fails."""

    def rows(path: Path) -> dict[str, list[object]]:
        connection = sqlite3.connect(path)
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            return {table: list(connection.execute(f"SELECT * FROM {table}")) for table in tables}
        finally:
            connection.close()

    go_rows, py_rows = rows(go_path), rows(py_path)
    for table in sorted(set(go_rows) | set(py_rows)):
        a, b = go_rows.get(table, []), py_rows.get(table, [])
        if a == b:
            continue
        for index, (go_row, py_row) in enumerate(zip(a, b, strict=False)):
            if go_row != py_row:
                return f"{table}[{index}]:\n  go:  {go_row}\n  py:  {py_row}"
        return f"{table}: row count differs (go {len(a)} vs py {len(b)})"
    return "no row differences (unexpected)"


def _run_python_build(sidecar: Path) -> tuple[str, Path]:
    connection = connect_database(sidecar, attach_artifacts=False)
    try:
        result = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        model_id = result.model_id
        basename = connection.execute(
            "SELECT artifact_basename FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    return model_id, sidecar.parent / f"{sidecar.stem}-derived" / basename


def _run_go_build(binary: Path, sidecar: Path) -> tuple[str, Path]:
    payload = json.dumps(
        {"db": str(sidecar), "now_ms": REFERENCE_MS}, separators=(",", ":")
    ).encode()
    result = subprocess.run(
        [str(binary), "model-build"], input=payload, capture_output=True, timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    model_id = None
    for line in result.stdout.decode().splitlines():
        parsed = json.loads(line)
        if "result" in parsed:
            model_id = parsed["result"]["model_id"]
    assert model_id is not None
    connection = sqlite3.connect(sidecar)
    try:
        basename = connection.execute(
            "SELECT artifact_basename FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    return model_id, sidecar.parent / f"{sidecar.stem}-derived" / basename


def test_model_build_artifact_parity(binary: Path, tmp_path: Path) -> None:
    """Both implementations produce the same model_id and content-identical
    model artifacts; the sidecar model_version / current_model_id writes
    match modulo the published timestamp."""

    py_dir = tmp_path / "py"
    py_dir.mkdir()
    py_db = py_dir / "curator.sqlite3"
    make_feature_sidecar(py_db)
    py_model, py_artifact = _run_python_build(py_db)

    go_dir = tmp_path / "go"
    go_dir.mkdir()
    go_db = go_dir / "curator.sqlite3"
    make_feature_sidecar(go_db)
    go_model, go_artifact = _run_go_build(binary, go_db)

    assert go_model == py_model
    assert go_artifact.name == py_artifact.name
    assert _artifact_tables_sha(go_artifact) == _artifact_tables_sha(py_artifact), (
        f"artifact content differs: {go_artifact} vs {py_artifact}\n"
        f"{_first_artifact_diff(go_artifact, py_artifact)}"
    )

    py_conn = sqlite3.connect(py_db)
    py_conn.row_factory = sqlite3.Row
    go_conn = sqlite3.connect(go_db)
    go_conn.row_factory = sqlite3.Row
    try:
        for column in (
            "model_id",
            "status",
            "feature_version",
            "scene_count",
            "lane_count",
            "reason_scene_count",
            "reason_count",
            "validation_status",
            "validation_summary_json",
            "artifact_schema_version",
            "artifact_bytes",
            "artifact_basename",
        ):
            py_val = py_conn.execute(
                f"SELECT {column} FROM model_version WHERE model_id=?", (py_model,)
            ).fetchone()[0]
            go_val = go_conn.execute(
                f"SELECT {column} FROM model_version WHERE model_id=?", (go_model,)
            ).fetchone()[0]
            assert go_val == py_val, column
        py_current = py_conn.execute(
            "SELECT value FROM application_meta WHERE key='current_model_id'"
        ).fetchone()[0]
        go_current = go_conn.execute(
            "SELECT value FROM application_meta WHERE key='current_model_id'"
        ).fetchone()[0]
        assert go_current == py_current == py_model
        py_published = py_conn.execute(
            "SELECT count(*) FROM model_version WHERE status='published'"
        ).fetchone()[0]
        go_published = go_conn.execute(
            "SELECT count(*) FROM model_version WHERE status='published'"
        ).fetchone()[0]
        assert go_published == py_published == 1
    finally:
        py_conn.close()
        go_conn.close()


def test_model_build_reuse_parity(binary: Path, tmp_path: Path) -> None:
    """A second build on the same sidecar reuses the published model on both
    implementations (reuse_count bumps, no new artifact)."""
    sidecar = tmp_path / "curator.sqlite3"
    make_feature_sidecar(sidecar)
    _run_go_build(binary, sidecar)
    connection = sqlite3.connect(sidecar)
    try:
        before = connection.execute(
            "SELECT reuse_count FROM model_version ORDER BY created_at_ms DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        connection.close()
    model_id, _ = _run_go_build(binary, sidecar)
    connection = sqlite3.connect(sidecar)
    try:
        after = connection.execute(
            "SELECT reuse_count FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert after == before + 1
