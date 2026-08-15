"""Slice-7 backend differential harness: the model impact op.

get_curation_impact runs through the Go binary and plugin/backend.py on fresh
sidecar copies; stdout must be byte-identical per the tolerance policy
(structure exact, floats within rel 1e-9). The impact report has no
per-run identifiers, so no normalization is needed.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import payload
from tests.core.test_backend_slice3_backups import assert_slice3_identical
from tests.curation.test_impact import (
    make_impact_sidecar,
)


class _StubSlice7(BaseHTTPRequestHandler):
    """Stash stub answering the settings query (empty plugin settings)."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        if "CuratorPluginSettings" in body:
            data: dict[str, object] = {"data": {"configuration": {"plugins": {}}}}
        else:
            data = {"errors": [{"message": f"no stub for {body[:80]}"}]}
        payload_bytes = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload_bytes)))
        self.end_headers()
        self.wfile.write(payload_bytes)

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
    server = HTTPServer(("127.0.0.1", 0), _StubSlice7)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_curation_impact_byte_identical(binary: Path, stub_stash: str, tmp_path: Path) -> None:
    sidecar = make_impact_sidecar(tmp_path)
    raw = payload("get_curation_impact", sidecar, stub_stash)
    assert_slice3_identical(binary, raw, sidecar)


def test_curation_impact_unavailable_byte_identical(
    binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    sidecar = make_impact_sidecar(tmp_path, n_models=1)
    raw = payload("get_curation_impact", sidecar, stub_stash)
    assert_slice3_identical(binary, raw, sidecar)


def test_curation_impact_missing_artifacts_byte_identical(
    binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    sidecar = make_impact_sidecar(tmp_path, with_artifacts=False)
    raw = payload("get_curation_impact", sidecar, stub_stash)
    assert_slice3_identical(binary, raw, sidecar)
