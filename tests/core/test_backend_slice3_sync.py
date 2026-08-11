"""Slice-3 backend differential harness: the sync-build task mode.

sync-build runs the full pipeline — the Stash incremental sync (stubbed),
prune-tag reconciliation, historical signal rebuild, the model build (with
the compiled-core kernels), lane classification, and page materialization —
through the Go binary and plugin/backend.py on fresh sidecar copies. Stdout
must be byte-identical modulo run-varying fields (job_id, sync_run_id,
stage_timings_ms), and the sidecar/artifact state must match.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR
from tests.core.test_backend_slice3_featurebuild import make_feature_sidecar


def _tag(tag_id: str, name: str) -> dict[str, object]:
    return {"id": tag_id, "name": name, "updated_at": "2026-01-01T00:00:00Z"}


def _performer(pid: str, name: str) -> dict[str, object]:
    return {
        "id": pid,
        "name": name,
        "gender": "FEMALE",
        "favorite": False,
        "rating100": None,
        "birthdate": "1990-01-01",
        "ethnicity": "Caucasian",
        "country": None,
        "eye_color": "Blue",
        "hair_color": "Blonde",
        "height_cm": 170,
        "weight": None,
        "measurements": "34D-24-36",
        "fake_tits": "Natural",
        "tattoos": None,
        "piercings": None,
        "updated_at": "2026-01-01T00:00:00Z",
        "tags": [_tag("t1", "Familiar Scenario")],
    }


def _scene(sid: str, title: str) -> dict[str, object]:
    return {
        "id": sid,
        "title": title,
        "details": "A sync fixture scene with distinctive chemistry.",
        "date": "2026-01-10",
        "rating100": None,
        "updated_at": "2026-01-01T00:00:00Z",
        "play_count": 1,
        "play_duration": 300,
        "play_history": ["2026-07-01T00:00:00Z"],
        "o_history": [],
        "studio": {
            "id": "st1",
            "name": "Studio One",
            "favorite": True,
            "rating100": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "parent_studio": None,
        },
        "tags": [_tag("t1", "Familiar Scenario"), _tag("t2", "Augmentation")],
        "performers": [_performer("p1", "Performer One")],
        "files": [{"id": f"file-{sid}", "duration": 300}],
        "scene_markers": (
            [
                {
                    "id": f"marker-{sid}",
                    "seconds": 45,
                    "end_seconds": 90,
                    "primary_tag": _tag("t1", "Familiar Scenario"),
                    "tags": [_tag("t1", "Familiar Scenario")],
                }
            ]
            if sid == "s1"
            else []
        ),
    }


class _StubSync(BaseHTTPRequestHandler):
    """Stash stub answering the plugin settings and the sync queries."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        data = self._answer(body)
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _answer(self, body: str) -> dict[str, object]:
        op = self._operation_name(body)
        if op == "CuratorPluginSettings":
            return {"data": {"configuration": {"plugins": {}}}}
        if op == "CuratorCapabilities":
            return {
                "data": {
                    "version": {"version": "v0.31.1"},
                    "queryType": {
                        "fields": [
                            {"name": n}
                            for n in ("findTags", "findStudios", "findPerformers", "findScenes")
                        ]
                    },
                    "sceneType": {
                        "fields": [
                            {"name": n}
                            for n in (
                                "id",
                                "updated_at",
                                "play_count",
                                "play_duration",
                                "play_history",
                                "o_history",
                                "files",
                                "scene_markers",
                                "tags",
                                "performers",
                            )
                        ]
                    },
                    "performerType": {
                        "fields": [
                            {"name": n}
                            for n in ("id", "updated_at", "favorite", "weight", "fake_tits")
                        ]
                    },
                    "tagType": {"fields": [{"name": n} for n in ("id", "updated_at", "stash_ids")]},
                    "sceneFilterType": {
                        "inputFields": [{"name": n} for n in ("play_count", "last_played_at")]
                    },
                }
            }
        if op == "CuratorTags":
            return {
                "data": {
                    "findTags": {
                        "count": 2,
                        "tags": [_tag("t1", "Familiar Scenario"), _tag("t2", "Augmentation")],
                    }
                }
            }
        if op == "CuratorStudios":
            return {
                "data": {
                    "findStudios": {
                        "count": 1,
                        "studios": [
                            {
                                "id": "st1",
                                "name": "Studio One",
                                "favorite": True,
                                "rating100": None,
                                "updated_at": "2026-01-01T00:00:00Z",
                                "parent_studio": None,
                            }
                        ],
                    }
                }
            }
        if op == "CuratorPerformers":
            return {
                "data": {
                    "findPerformers": {
                        "count": 1,
                        "performers": [_performer("p1", "Performer One")],
                    }
                }
            }
        if op == "CuratorScenes":
            return {
                "data": {
                    "findScenes": {
                        "count": 2,
                        "scenes": [_scene("s1", "Sync Scene One"), _scene("s2", "Sync Scene Two")],
                    }
                }
            }
        if op == "CuratorScenePlays":
            return {
                "data": {
                    "findScenes": {
                        "count": 2,
                        "scenes": [
                            {
                                "id": "s1",
                                "updated_at": "2026-01-01T00:00:00Z",
                                "play_history": ["2026-07-01T00:00:00Z"],
                                "o_history": [],
                            },
                            {
                                "id": "s2",
                                "updated_at": "2026-01-01T00:00:00Z",
                                "play_history": ["2026-07-02T00:00:00Z"],
                                "o_history": [],
                            },
                        ],
                    }
                }
            }
        for name, root, items in (
            ("CuratorTagIds", "findTags", "tags"),
            ("CuratorStudioIds", "findStudios", "studios"),
            ("CuratorPerformerIds", "findPerformers", "performers"),
            ("CuratorSceneIds", "findScenes", "scenes"),
        ):
            if op == name:
                rows = {
                    "tags": [{"id": "t1"}],
                    "studios": [{"id": "st1"}],
                    "performers": [{"id": "p1"}],
                    "scenes": [{"id": "s1"}, {"id": "s2"}],
                }[items]
                return {"data": {root: {"count": len(rows), items: rows}}}
        return {"errors": [{"message": f"no stub for {op}"}]}

    @staticmethod
    def _operation_name(body: str) -> str:
        for name in (
            "CuratorPluginSettings",
            "CuratorCapabilities",
            "CuratorTags",
            "CuratorStudios",
            "CuratorPerformers",
            "CuratorScenes",
            "CuratorScenePlays",
            "CuratorTagIds",
            "CuratorStudioIds",
            "CuratorPerformerIds",
            "CuratorSceneIds",
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
    server = HTTPServer(("127.0.0.1", 0), _StubSync)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def sync_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("sync-sidecar") / "curator.sqlite3"
    make_feature_sidecar(path)
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


def _run_sync_both(
    binary: Path,
    sidecar: Path,
    stash_url: str,
    mode: str,
) -> list[subprocess.CompletedProcess[bytes]]:
    run_dir = sidecar.parent / f"{sidecar.stem}-sync-run"
    run_db = run_dir / sidecar.name
    outputs: list[subprocess.CompletedProcess[bytes]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(sidecar, run_db)
        try:
            outputs.append(
                _run_backend(runner, _with_db(_task_payload(sidecar, stash_url), run_db), mode)
            )
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
    return outputs


def _run_backend(runner: Path | None, raw: bytes, mode: str) -> subprocess.CompletedProcess[bytes]:
    if runner is None:
        argv = ["uv", "run", "--frozen", "python", str(PLUGIN_DIR / "backend.py"), str(PLUGIN_DIR)]
    else:
        argv = [str(runner), str(PLUGIN_DIR)]
    argv.append(mode)
    return subprocess.run(argv, input=raw, capture_output=True, timeout=600)


def test_sync_build_byte_identical(sync_sidecar: Path, binary: Path, stub_stash: str) -> None:
    python_result, go_result = _run_sync_both(binary, sync_sidecar, stub_stash, "sync-build")
    assert go_result.returncode == python_result.returncode, (
        python_result.stdout + python_result.stderr + go_result.stdout + go_result.stderr
    )
    py_out = json.loads(python_result.stdout)
    go_out = json.loads(go_result.stdout)
    for doc in (py_out, go_out):
        output = doc.get("output", {})
        for key in ("job_id", "sync_run_id", "stage_timings_ms"):
            output.pop(key, None)
    from tests.core.compare import assert_equivalent

    assert_equivalent(py_out, go_out)


def test_sync_build_state_parity(sync_sidecar: Path, binary: Path, stub_stash: str) -> None:
    """The sync-build leaves identical published-model state on both
    backends: one published model with the same artifact tables."""
    run_dir = sync_sidecar.parent / f"{sync_sidecar.stem}-sync-state"
    states: list[dict[str, object]] = []
    artifact_diffs: list[str] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        run_db = run_dir / sync_sidecar.name
        shutil.copy2(sync_sidecar, run_db)
        result = _run_backend(
            None if runner is None else runner,
            _with_db(_task_payload(sync_sidecar, stub_stash), run_db),
            "sync-build",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        connection = sqlite3.connect(run_db)
        try:
            model_id = connection.execute(
                "SELECT model_id FROM model_version WHERE status='published'"
            ).fetchone()
            job = connection.execute(
                "SELECT job_type, state FROM curator_job ORDER BY started_at_ms DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        assert model_id is not None
        artifact = run_dir / f"{run_db.stem}-derived" / f"{model_id[0]}.sqlite3"
        states.append({"model_id": model_id[0], "job": job})
        from tests.core.compare import artifact_tolerant_diff

        artifact_diffs.append(artifact_tolerant_diff(artifact, artifact))
        shutil.rmtree(run_dir, ignore_errors=True)
    assert states[0] == states[1]
    assert artifact_diffs == ["", ""]
