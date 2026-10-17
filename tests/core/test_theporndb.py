"""Exercise REST retrieval through both complete discovery backends."""

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import pytest

from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR, payload
from tests.core.test_backend_slice2 import (
    STASHDB_ENDPOINT,
    _StubExpand,
    assert_slice2_identical,
    make_expand_sidecar,
    run_backend_env,
)
from tests.core.test_backend_slice3_refresh import assert_refresh_identical
from tests.test_theporndb import fixture

ENDPOINT = "https://theporndb.net/graphql"


class RestStub(_StubExpand):
    plugin_settings: ClassVar[dict[str, object]] = {"stashBoxEndpoint": ENDPOINT}

    def _answer(self, body):
        # Copy the shared Stash fixtures without changing other differential tests.
        return json.loads(json.dumps(super()._answer(body)).replace(STASHDB_ENDPOINT, ENDPOINT))

    def do_GET(self):
        assert self.headers["Authorization"] == "Bearer stub-key"
        address = urlparse(self.path)
        query = parse_qs(address.query)
        if "gender" in query:
            assert query["gender"] == ["Female"]
        if "ethnicity" in query:
            assert query["ethnicity"] == ["Caucasian"]
        data = fixture()
        parent = {**data["performer"], "id": "ext-p1"}
        other = {**parent, "id": "external-only", "_id": 43, "name": "Another Performer"}
        site = {**data["site"], "uuid": "ext-studio-1"}
        tags = [{**data["tags"][0], "uuid": "ext-good", "name": "Familiar Scenario"}]
        scene = {
            **data["scene"],
            "performers": [{**data["site_performer"], "parent": parent}],
            "tags": tags,
            "site": site,
            "hashes": [],
        }
        details = {"/performers/ext-p1": parent, "/sites/ext-studio-1": site}
        if address.path in details:
            result = {"data": details[address.path]}
        else:
            rows = None
            if address.path == "/tags":
                rows = tags
            elif address.path == "/scenes":
                rows = [scene]
            elif address.path == "/performers":
                rows = [parent, other]
                if query.get("q"):
                    rows = [r for r in rows if query["q"][0].casefold() in r["name"].casefold()]
            elif address.path == "/performers/ext-p1/similar":
                rows = [other]
            if rows is None:
                self.send_error(404)
                return
            page = int(query.get("page", [1])[0])
            size = int(query.get("per_page", [100])[0])
            result = {
                "data": rows[(page - 1) * size : page * size],
                "meta": {"total": len(rows), "current_page": page},
            }
        raw = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture(scope="module")
def rest_stash():
    server = ThreadingHTTPServer(("127.0.0.1", 0), RestStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("operation", "args"),
    [
        ("get_stashdb_performer_search", {"query": "Example"}),
        ("get_performer_hunt", {"performer_id": "ext-p1"}),
        ("get_external_similar", {"entity_type": "scene", "entity_id": "recent-good"}),
        ("get_external_similar", {"entity_type": "performer", "entity_id": "p1"}),
    ],
)
def test_rest_discovery_parity(tmp_path: Path, rest_stash: str, operation: str, args: dict):
    binary = core_binary()
    assert binary is not None
    database = tmp_path / "curator.sqlite3"
    make_expand_sidecar(database)
    raw = payload(operation, database, rest_stash, **args)
    timings = ("timings_ms",) if operation == "get_external_similar" else ()
    assert_slice2_identical(binary, PLUGIN_DIR, raw, database, rest_stash, timing_fields=timings)
    result = run_backend_env(binary, PLUGIN_DIR, raw, rest_stash)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)["output"]
    if operation == "get_stashdb_performer_search":
        assert output["items"][0]["id"] == "ext-p1"
        return
    assert output["ready"], output
    assert output["items"], output
    assert all(item["payload"]["curator_endpoint"] == ENDPOINT for item in output["items"])


def test_rest_refresh_parity(tmp_path: Path, rest_stash: str):
    binary = core_binary()
    assert binary is not None
    database = tmp_path / "curator.sqlite3"
    make_expand_sidecar(database)
    assert_refresh_identical(binary, database, rest_stash)
