"""Slice-3 backend differential harness: the feature build stage.

The Go feature-build kernel stage runs against the same builder-seeded
sidecar as Python's FeatureBuilder.build(); the produced feature artifact
(the oracle) must be content-identical, the feature_version must match, and
the sidecar tag_role / tag_taxonomy_match / feature_build writes must match
modulo run timestamps.

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
from curator.features.builder import FeatureBuilder
from tests.core.compare import artifact_tolerant_diff
from tests.core.test_backend_slice2 import STASHDB_ENDPOINT
from tests.model.test_builder import DAY_MS, REFERENCE_MS, _database


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


def make_feature_sidecar(path: Path) -> None:
    """The model-builder synthetic library plus scene details (for the
    description-term features) and a small taxonomy snapshot (for the
    tag-role resolution path)."""
    connection = _database(path)
    try:
        connection.executemany(
            "UPDATE source_scene SET details=? WHERE scene_id=?",
            [
                ("A romantic candlelight encounter with intense chemistry.", "recent-good"),
                ("An athletic outdoor adventure near the mountains at sunset.", "unseen-good"),
                ("A quiet introspective morning routine.", "unlabeled"),
            ],
        )
        connection.execute(
            """
            INSERT INTO taxonomy_snapshot(
                snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
            ) VALUES ('tax-feature', ?, ?, 0, 3)
            """,
            (STASHDB_ENDPOINT, REFERENCE_MS - 2 * DAY_MS),
        )
        connection.executemany(
            """
            INSERT INTO taxonomy_tag(snapshot_id, tag_id, name, category_id)
            VALUES ('tax-feature', ?, ?, NULL)
            """,
            [
                ("ext-good", "Familiar Scenario"),
                ("ext-bad", "Challenging Scenario"),
                ("ext-unusual", "Unusual Scenario"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO taxonomy_tag_alias(snapshot_id, tag_id, alias)
            VALUES ('tax-feature', ?, ?)
            """,
            [
                ("ext-good", "Comfy Scenario"),
                ("ext-unusual", "Strange Scenario"),
            ],
        )
        connection.execute(
            "INSERT INTO application_meta(key, value)"
            " VALUES ('taxonomy_snapshot_id', 'tax-feature')"
        )
        connection.commit()
    finally:
        connection.close()


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
                digest.update(repr(row).encode())
        return digest.hexdigest()
    finally:
        connection.close()


def _run_python_build(sidecar: Path) -> tuple[str, Path]:
    """Run Python's FeatureBuilder and return (feature_version, artifact path)."""
    from curator.storage import connect_database

    connection = connect_database(sidecar, attach_artifacts=False)
    try:
        result = FeatureBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        feature_version = result.feature_version
        basename = connection.execute(
            "SELECT artifact_basename FROM feature_build WHERE feature_version=?",
            (feature_version,),
        ).fetchone()[0]
    finally:
        connection.close()
    return feature_version, sidecar.parent / f"{sidecar.stem}-derived" / basename


def _run_go_build(binary: Path, sidecar: Path) -> tuple[str, Path]:
    payload = json.dumps(
        {"db": str(sidecar), "now_ms": REFERENCE_MS}, separators=(",", ":")
    ).encode()
    result = subprocess.run(
        [str(binary), "feature-build"], input=payload, capture_output=True, timeout=180
    )
    assert result.returncode == 0, result.stdout + result.stderr
    version = None
    for line in result.stdout.decode().splitlines():
        parsed = json.loads(line)
        if "result" in parsed:
            version = parsed["result"]["feature_version"]
    assert version is not None
    connection = sqlite3.connect(sidecar)
    try:
        basename = connection.execute(
            "SELECT artifact_basename FROM feature_build WHERE feature_version=?",
            (version,),
        ).fetchone()[0]
    finally:
        connection.close()
    return version, sidecar.parent / f"{sidecar.stem}-derived" / basename


def test_feature_build_artifact_parity(binary: Path, tmp_path: Path) -> None:
    """Both implementations produce the same feature_version and a
    content-identical feature artifact; the sidecar writes match modulo the
    published timestamp."""
    py_dir = tmp_path / "py"
    py_dir.mkdir()
    py_db = py_dir / "curator.sqlite3"
    make_feature_sidecar(py_db)
    py_version, py_artifact = _run_python_build(py_db)

    go_dir = tmp_path / "go"
    go_dir.mkdir()
    go_db = go_dir / "curator.sqlite3"
    make_feature_sidecar(go_db)
    go_version, go_artifact = _run_go_build(binary, go_db)

    assert go_version == py_version
    assert go_artifact.name == py_artifact.name
    assert artifact_tolerant_diff(go_artifact, py_artifact) == ""

    for label, db in (("python", py_db), ("go", go_db)):
        connection = sqlite3.connect(db)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT tag_id, config_version, role, resolution_reason
                FROM tag_role ORDER BY tag_id
                """
            ).fetchall()
            assert rows, label
            matches = connection.execute(
                """
                SELECT local_tag_id, snapshot_id, external_tag_id, external_category_id,
                       match_method, confidence, ambiguity_count
                FROM tag_taxonomy_match ORDER BY local_tag_id
                """
            ).fetchall()
            assert matches, label
            build = connection.execute(
                """
                SELECT feature_version, status, source_fingerprint, scene_count,
                       performer_count, feature_count, artifact_basename,
                       artifact_schema_version, artifact_bytes, validation_status,
                       validation_summary_json, error
                FROM feature_build WHERE feature_version=?
                """,
                (py_version,),
            ).fetchone()
            assert build is not None, label
        finally:
            connection.close()

    py_conn = sqlite3.connect(py_db)
    py_conn.row_factory = sqlite3.Row
    go_conn = sqlite3.connect(go_db)
    go_conn.row_factory = sqlite3.Row
    try:
        for table, order in (
            ("tag_role", "tag_id"),
            ("tag_taxonomy_match", "local_tag_id, snapshot_id"),
        ):
            py_rows = py_conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            go_rows = go_conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            assert [dict(row) for row in go_rows] == [dict(row) for row in py_rows], table
        for column in (
            "feature_version",
            "status",
            "source_fingerprint",
            "scene_count",
            "performer_count",
            "feature_count",
            "artifact_basename",
            "artifact_schema_version",
            "artifact_bytes",
            "validation_status",
            "validation_summary_json",
            "error",
        ):
            py_val = py_conn.execute(
                f"SELECT {column} FROM feature_build WHERE feature_version=?", (py_version,)
            ).fetchone()[0]
            go_val = go_conn.execute(
                f"SELECT {column} FROM feature_build WHERE feature_version=?", (go_version,)
            ).fetchone()[0]
            assert go_val == py_val, column
    finally:
        py_conn.close()
        go_conn.close()


def test_feature_build_reuse_parity(binary: Path, tmp_path: Path) -> None:
    """A second build on the same sidecar reuses the published feature on
    both implementations (reuse_count bumps, no new artifact)."""
    sidecar = tmp_path / "curator.sqlite3"
    make_feature_sidecar(sidecar)
    _run_go_build(binary, sidecar)
    connection = sqlite3.connect(sidecar)
    try:
        before = connection.execute(
            "SELECT reuse_count FROM feature_build ORDER BY created_at_ms DESC LIMIT 1"
        ).fetchone()[0]
        artifacts = list((tmp_path / "curator-derived").glob("feature-*.sqlite3"))
    finally:
        connection.close()
    version, artifact = _run_go_build(binary, sidecar)
    connection = sqlite3.connect(sidecar)
    try:
        after = connection.execute(
            "SELECT reuse_count FROM feature_build WHERE feature_version=?", (version,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert after == before + 1
    assert artifact in artifacts
