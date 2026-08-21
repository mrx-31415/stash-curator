"""Differential gate for the apiSchemaVersion 2 explanation payload.

The Go core and the Python oracle must emit byte-identical v2 explanation
payloads (structure exactly, floats within the shared 1e-9 tolerance), and the
payload must carry the versioned shape: apiSchemaVersion 2, summary,
components[], reasons[], lane_context{}, scores{appeal,current_fit,confidence,
rank}, and evidence_fingerprint{}.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR, _with_db_path, payload, run_backend
from tests.core.test_backend_slice1 import make_model_sidecar
from tests.core.compare import assert_equivalent


@pytest.fixture(scope="module")
def stub_stash() -> str:
    from http.server import HTTPServer

    from tests.core.test_backend import _StubStash

    server = HTTPServer(("127.0.0.1", 0), _StubStash)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def model_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("model-sidecar-v2") / "curator.sqlite3"
    make_model_sidecar(path)
    return path

V2_FIELDS = (
    "apiSchemaVersion",
    "summary",
    "components",
    "reasons",
    "lane_context",
    "scores",
    "evidence_fingerprint",
)


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


def _run_both(binary: Path, raw: bytes, same_path: Path, tmp_path: Path) -> tuple[dict, dict]:
    outputs: list[dict] = []
    for name, runner in (("py", None), ("go", Path(binary))):
        run_dir = tmp_path / f"run-{name}"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        db = run_dir / same_path.name
        shutil.copy2(same_path, db)
        derived_src = same_path.parent / f"{same_path.stem}-derived"
        derived_dst = run_dir / f"{db.stem}-derived"
        if derived_src.is_dir():
            shutil.copytree(derived_src, derived_dst)
        try:
            result = run_backend(runner, PLUGIN_DIR, _with_db_path(raw, db))
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        assert result.returncode == 0, result.stdout
        outputs.append(json.loads(result.stdout)["output"])
    return outputs[0], outputs[1]


def _assert_v2_shape(payload: dict) -> None:
    assert payload["apiSchemaVersion"] == 2
    assert isinstance(payload["summary"], str) and payload["summary"]
    assert isinstance(payload["components"], list) and payload["components"]
    assert isinstance(payload["reasons"], list) and payload["reasons"]
    assert isinstance(payload["lane_context"], dict)
    assert set(payload["scores"]) == {"appeal", "current_fit", "confidence", "rank"}
    for key in ("appeal", "current_fit", "confidence", "rank"):
        assert set(payload["scores"][key]) == {"value", "unit"}
    assert "axes" in payload["evidence_fingerprint"]
    assert set(payload["evidence_fingerprint"]["axes"]) == {
        "content",
        "performers",
        "studios",
        "similar_scenes",
        "direct_history",
        "metadata_coverage",
    }


@pytest.mark.parametrize("scene_id", ["recent-good", "old-good", "disliked", "unusual"])
def test_explanation_v2_byte_identical(
    model_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path, scene_id: str
) -> None:
    raw = payload("get_explanation", model_sidecar, stub_stash, scene_id=scene_id)
    py_out, go_out = _run_both(binary, raw, model_sidecar, tmp_path)
    _assert_v2_shape(py_out)
    _assert_v2_shape(go_out)
    assert_equivalent(py_out, go_out)
