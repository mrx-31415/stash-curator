"""Slice-3 backend differential harness: the expand-refresh task mode.

expand-refresh runs through the Go binary and plugin/backend.py on fresh
copies of the slice-2 expand sidecar (a real builder-seeded model with
taxonomy and candidate rows). The stub answers the settings / external-links
/ StashDB SCENES queries; the refresh merges fresh recent candidates, ages
out the stale fixture candidates, and rescores the pool when the cached
model differs. Stdout must be byte-identical once job_id is stripped, and
the external_entity / expand_cache sidecar state must match.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR
from tests.core.test_backend_slice2 import (
    LINKED_PERFORMERS,
    LINKED_SCENES,
    LINKED_STUDIOS,
    STASHDB_ENDPOINT,
    _cast,
    make_expand_sidecar,
)

FRESH_SCENES = [
    {
        "id": "fresh-1",
        "title": "Fresh Scene One",
        "release_date": "2026-07-20",
        "production_date": None,
        "duration": 600,
        "details": "A fresh synthetic scene",
        "studio": {"id": "ext-studio-1", "name": "Studio One"},
        "tags": [{"id": "ext-good", "name": "Familiar Scenario"}],
        "images": [],
        "fingerprints": [],
        "performers": _cast("ext-p1", "ext-p2"),
    },
    {
        "id": "fresh-2",
        "title": "Fresh Scene Two",
        "release_date": "2026-08-01",
        "production_date": None,
        "duration": 300,
        "details": "Another fresh synthetic scene",
        "studio": {"id": "ext-studio-2", "name": "Studio Two"},
        "tags": [{"id": "ext-unusual", "name": "Unusual Scenario"}],
        "images": [],
        "fingerprints": [],
        "performers": _cast("ext-p3"),
    },
]


class _StubRefresh(BaseHTTPRequestHandler):
    """Stash + StashDB stub for the refresh flow: settings, boxes, external
    links state/list, and the SCENES query (probe + fetches) returning the
    fresh scenes for any filter input."""

    plugin_settings: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        operation = self._operation_name(body)
        if operation == "CuratorPluginSettings":
            data = {"data": {"configuration": {"plugins": {"stash-curator": self.plugin_settings}}}}
        elif operation == "CuratorStashBoxes":
            data = {
                "data": {
                    "configuration": {
                        "general": {
                            "stashBoxes": [
                                {
                                    "endpoint": STASHDB_ENDPOINT,
                                    "api_key": "stub-key",
                                    "name": "StashDB",
                                }
                            ]
                        }
                    }
                }
            }
        elif operation == "CuratorExternalLinksState":
            data = {
                "data": {
                    "scenes": {
                        "count": len(LINKED_SCENES),
                        "scenes": [{"updated_at": "2026-01-01T00:00:00Z"}],
                    },
                    "performers": {
                        "count": len(LINKED_PERFORMERS),
                        "performers": [{"updated_at": "2026-01-01T00:00:00Z"}],
                    },
                    "studios": {
                        "count": len(LINKED_STUDIOS),
                        "studios": [{"updated_at": "2026-01-01T00:00:00Z"}],
                    },
                }
            }
        elif operation == "CuratorExternalLinks":
            data = {
                "data": {
                    "scenes": {"count": len(LINKED_SCENES), "scenes": LINKED_SCENES},
                    "performers": {
                        "count": len(LINKED_PERFORMERS),
                        "performers": LINKED_PERFORMERS,
                    },
                    "studios": {"count": len(LINKED_STUDIOS), "studios": LINKED_STUDIOS},
                }
            }
        elif operation == "CuratorExpandScenes":
            data = {"data": {"queryScenes": {"count": len(FRESH_SCENES), "scenes": FRESH_SCENES}}}
        else:
            data = {"errors": [{"message": f"no stub for {operation}"}]}
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    @staticmethod
    def _operation_name(body: str) -> str:
        for name in (
            "CuratorPluginSettings",
            "CuratorStashBoxes",
            "CuratorExternalLinksState",
            "CuratorExternalLinks",
            "CuratorExpandScenes",
        ):
            if name in body:
                return name
        return "unknown"

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubRefresh)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_refresh_sidecar(path: Path) -> None:
    """The slice-2 expand sidecar plus a fresh taxonomy-checked stamp (so the
    taxonomy fetch is skipped deterministically)."""
    make_expand_sidecar(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO application_meta(key, value) VALUES ('taxonomy_checked_at_ms', ?)
            """,
            ("9999999999999",),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def refresh_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("refresh-sidecar") / "curator.sqlite3"
    make_refresh_sidecar(path)
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


def _run_refresh_backend(
    binary: Path | None, plugin_dir: Path, raw: bytes, stashdb_override: str
) -> subprocess.CompletedProcess[bytes]:

    env = dict(os.environ)
    env["CURATOR_STASHDB_ENDPOINT"] = stashdb_override
    if binary is None:
        argv = ["uv", "run", "--frozen", "python", str(plugin_dir / "backend.py"), str(plugin_dir)]
    else:
        argv = [str(binary), str(plugin_dir)]
    argv.append("expand-refresh")
    return subprocess.run(argv, input=raw, capture_output=True, timeout=180, env=env)


def assert_refresh_identical(
    binary: Path,
    sidecar: Path,
    stash_url: str,
    *,
    normalize: tuple[str, ...] = ("job_id",),
) -> tuple[subprocess.CompletedProcess[bytes], subprocess.CompletedProcess[bytes]]:
    run_dir = sidecar.parent / f"{sidecar.stem}-refresh-run"
    run_db = run_dir / sidecar.name
    outputs: list[subprocess.CompletedProcess[bytes]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(sidecar, run_db)
        derived_src = sidecar.parent / f"{sidecar.stem}-derived"
        if derived_src.is_dir():
            shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
        try:
            result = _run_refresh_backend(
                runner, PLUGIN_DIR, _with_db(_task_payload(sidecar, stash_url), run_db), stash_url
            )
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
        return outputs
    a, b = py_out["output"], go_out["output"]
    for field in normalize:
        _strip_key(a, field)
        _strip_key(b, field)
    assert json.dumps(a, separators=(",", ":")) == json.dumps(b, separators=(",", ":")), (
        "outputs differ:\n"
        f"python: {json.dumps(a, separators=(',', ':'))}\n"
        f"go:     {json.dumps(b, separators=(',', ':'))}"
    )
    return outputs


def test_expand_refresh_byte_identical(
    refresh_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    assert_refresh_identical(binary, refresh_sidecar, stub_stash)


def test_expand_refresh_state_parity(refresh_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """The refresh leaves identical external_entity / expand_cache state:
    the fresh scenes merged as candidates, the stale 2024 fixture scenes aged
    out, and the pool rescored against the published model."""

    run_dir = refresh_sidecar.parent / f"{refresh_sidecar.stem}-refresh-state"
    states: list[dict[str, object]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / refresh_sidecar.name
        shutil.copy2(refresh_sidecar, run_db)
        derived_src = refresh_sidecar.parent / f"{refresh_sidecar.stem}-derived"
        shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
        result = _run_refresh_backend(
            runner,
            PLUGIN_DIR,
            _with_db(_task_payload(refresh_sidecar, stub_stash), run_db),
            stub_stash,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            states.append(
                {
                    "external_entity": connection.execute(
                        "SELECT entity_type, external_id, score, sources_json, pool"
                        " FROM external_entity ORDER BY entity_type, external_id"
                    ).fetchall(),
                    "expand_cache": connection.execute(
                        "SELECT model_id, scene_count, performer_count FROM expand_cache"
                    ).fetchone(),
                    "job": connection.execute(
                        "SELECT job_type, state FROM curator_job"
                        " ORDER BY started_at_ms DESC LIMIT 1"
                    ).fetchone(),
                }
            )
        finally:
            connection.close()
        shutil.rmtree(run_dir, ignore_errors=True)
    assert states[0] == states[1]
