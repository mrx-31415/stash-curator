"""Slice-2 backend differential harness: the network-layer ops.

The Slice-2 ops (get_expand, get_performer_hunt, get_external_similar,
send_whisparr) hit StashDB and Whisparr, so the harness extends the
Slice-1 pattern with two stubs: the existing GraphQL stub server answers
the Stash queries (settings, stash boxes, external-links state/scan) and a
StashDB fixture engine serves the expand queries; a second HTTP server
stubs Whisparr's /api/v3. StashDB's endpoint is hardcoded to
https://stashdb.org/graphql in both backends, so the harness redirects it
with the CURATOR_STASHDB_ENDPOINT env override (a test-only seam in
backend.py's _stashdb and the Go client, mirroring the CURATOR_CORE
resolver). Every test runs plugin/backend.py and the built curator-core
binary against identical fresh sidecar copies and asserts byte-identical
outputs per the run-varying-fields contract (timings_ms structural).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from curator.core import core_binary
from curator.model import PreferenceModelBuilder
from tests.core.test_backend import BACKEND, PLUGIN_DIR, payload
from tests.model.test_builder import REFERENCE_MS, _database

STASHDB_ENDPOINT = "https://stashdb.org/graphql"

# ── StashDB fixtures ───────────────────────────────────────────────────────

STASHDB_PERFORMERS = {
    "ext-p1": {
        "id": "ext-p1",
        "name": "Performer One",
        "gender": "FEMALE",
        "birth_date": "1990-05-20",
        "ethnicity": "Caucasian",
        "eye_color": "Blue",
        "hair_color": "Black",
        "height": 170,
        "cup_size": "DD",
        "band_size": "34",
        "waist_size": "24",
        "hip_size": "36",
        "breast_type": "natural",
        "tattoos": [],
        "piercings": [],
        "images": [],
        "scene_count": 40,
    },
    "ext-p2": {
        "id": "ext-p2",
        "name": "Performer Two",
        "gender": "FEMALE",
        "birth_date": "1995-01-10",
        "ethnicity": "Caucasian",
        "eye_color": "Brown",
        "hair_color": "Brown",
        "height": 168,
        "cup_size": "D",
        "band_size": "34",
        "waist_size": "25",
        "hip_size": "36",
        "breast_type": "natural",
        "tattoos": [],
        "piercings": [],
        "images": [],
        "scene_count": 12,
    },
    "ext-p3": {
        "id": "ext-p3",
        "name": "Performer Three",
        "gender": "FEMALE",
        "birth_date": "1985-09-15",
        "ethnicity": "Asian",
        "eye_color": "Hazel",
        "hair_color": "Black",
        "height": 165,
        "cup_size": "C",
        "band_size": "32",
        "waist_size": "23",
        "hip_size": "34",
        "breast_type": "augmented",
        "tattoos": [{"location": "arm"}],
        "piercings": [],
        "images": [],
        "scene_count": 100,
    },
    "ext-p4": {
        "id": "ext-p4",
        "name": "Performer Four",
        "gender": "FEMALE",
        "birth_date": "1998-12-01",
        "ethnicity": "Latina",
        "eye_color": "Green",
        "hair_color": "Brown",
        "height": 172,
        "cup_size": "B",
        "band_size": "34",
        "waist_size": "26",
        "hip_size": "37",
        "breast_type": "natural",
        "tattoos": [],
        "piercings": [{"location": "nose"}],
        "images": [],
        "scene_count": 3,
    },
}


def _cast(*external_ids: str) -> list[dict[str, Any]]:
    return [{"performer": dict(STASHDB_PERFORMERS[external_id])} for external_id in external_ids]


STASHDB_SCENES: list[dict[str, Any]] = [
    {
        "id": "ext-scene-1",
        "title": "StashDB Scene One",
        "release_date": "2024-03-15",
        "production_date": "2024-03-01",
        "duration": 2700,
        "details": "A deterministic fixture scene.",
        "studio": {"id": "ext-studio-1", "name": "Studio One"},
        "tags": [
            {"id": "ext-good", "name": "Familiar Scenario"},
            {"id": "ext-bad", "name": "Challenging Scenario"},
        ],
        "images": [{"url": "https://stashdb.example/1.jpg", "width": 1000, "height": 1500}],
        "fingerprints": [],
        "performers": _cast("ext-p1", "ext-p2"),
    },
    {
        "id": "stashdb-scene-2",
        "title": "StashDB Scene Two",
        "release_date": "2023-11-02",
        "production_date": "2023-11-01",
        "duration": 2400,
        "details": None,
        "studio": {"id": "ext-studio-1", "name": "Studio One"},
        "tags": [{"id": "ext-good", "name": "Familiar Scenario"}],
        "images": [],
        "fingerprints": [{"hash": "0123456789abcdef", "algorithm": "phash", "duration": 2400}],
        "performers": _cast("ext-p1"),
    },
    {
        "id": "stashdb-scene-3",
        "title": "StashDB Scene Three",
        "release_date": None,
        "production_date": "2022-06-20",
        "duration": 1800,
        "details": None,
        "studio": {"id": "ext-studio-2", "name": "Studio Two"},
        "tags": [{"id": "ext-unusual", "name": "Unusual Scenario"}],
        "images": [],
        "fingerprints": [],
        "performers": _cast("ext-p1", "ext-p3"),
    },
    {
        "id": "stashdb-scene-4",
        "title": "StashDB Scene Four",
        "release_date": "2024-08-01",
        "production_date": "2024-07-20",
        "duration": 3200,
        "details": None,
        "studio": {"id": "ext-studio-1", "name": "Studio One"},
        "tags": [
            {"id": "ext-good", "name": "Familiar Scenario"},
            {"id": "ext-bad", "name": "Challenging Scenario"},
        ],
        "images": [],
        "fingerprints": [],
        "performers": _cast("ext-p2", "ext-p3"),
    },
]

STASHDB_PERFORMER_POOL = [
    dict(STASHDB_PERFORMERS["ext-p2"]),
    dict(STASHDB_PERFORMERS["ext-p1"]),
    dict(STASHDB_PERFORMERS["ext-p3"]),
    dict(STASHDB_PERFORMERS["ext-p4"]),
]


def _scene_filter_matches(scene: dict[str, Any], criterion: dict[str, Any]) -> bool:
    modifier = criterion.get("modifier")
    wanted = set(str(value) for value in criterion.get("value", []))
    if "performers" in criterion:
        present = {str(item["performer"]["id"]) for item in scene.get("performers", [])}
    elif "tags" in criterion:
        present = {str(tag["id"]) for tag in scene.get("tags", [])}
    elif "studios" in criterion:
        present = {str(scene.get("studio", {}).get("id"))} if scene.get("studio") else set()
    else:
        return True
    if modifier == "INCLUDES_ALL":
        return wanted <= present
    return bool(wanted & present)


# ── HTTP stubs ─────────────────────────────────────────────────────────────

LINKED_SCENES = [
    {
        "id": "recent-good",
        "stash_ids": [
            {"endpoint": STASHDB_ENDPOINT, "stash_id": "ext-scene-1"},
        ],
        "files": [
            {"fingerprints": [{"type": "phash", "value": "0123456789abcdef"}]},
        ],
    }
]
LINKED_PERFORMERS = [
    {"id": "p1", "stash_ids": [{"endpoint": STASHDB_ENDPOINT, "stash_id": "ext-p1"}]},
    {"id": "p2", "stash_ids": [{"endpoint": STASHDB_ENDPOINT, "stash_id": "ext-p2"}]},
]
LINKED_STUDIOS = [
    {"id": "studio-1", "stash_ids": [{"endpoint": STASHDB_ENDPOINT, "stash_id": "ext-studio-1"}]},
]


class _StubExpand(BaseHTTPRequestHandler):
    """One server answering the Stash GraphQL queries (settings, boxes,
    external links) and the StashDB expand queries from fixed fixtures."""

    plugin_settings: ClassVar[dict[str, object]] = {}

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
        operation = self._operation_name(body)
        # The query document travels JSON-escaped (\n before the keyword), so
        # match on the operation name substring like the Slice-0 stub.
        if operation == "CuratorPluginSettings":
            return {"data": {"configuration": {"plugins": {"stash-curator": self.plugin_settings}}}}
        if operation == "CuratorStashBoxes":
            return {
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
        if operation == "CuratorExternalLinksState":
            return {
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
        if operation == "CuratorExternalLinks":
            return {
                "data": {
                    "scenes": {"count": len(LINKED_SCENES), "scenes": LINKED_SCENES},
                    "performers": {
                        "count": len(LINKED_PERFORMERS),
                        "performers": LINKED_PERFORMERS,
                    },
                    "studios": {"count": len(LINKED_STUDIOS), "studios": LINKED_STUDIOS},
                }
            }
        if operation == "CuratorExpandScenes":
            input_data = json.loads(body)["variables"]["input"]
            filtered = [
                scene
                for scene in STASHDB_SCENES
                if all(
                    _scene_filter_matches(scene, {key: input_data[key]})
                    for key in ("performers", "tags", "studios")
                    if key in input_data
                )
            ]
            page = int(input_data.get("page", 1))
            per_page = int(input_data.get("per_page", 250))
            start = (page - 1) * per_page
            return {
                "data": {
                    "queryScenes": {
                        "count": len(filtered),
                        "scenes": filtered[start : start + per_page],
                    }
                }
            }
        if operation == "CuratorSimilarPerformers":
            input_data = json.loads(body)["variables"]["input"]
            pool = list(STASHDB_PERFORMER_POOL)
            if input_data.get("performed_with"):
                pool = [p for p in pool if p["id"] in {"ext-p1", "ext-p3"}]
            return {"data": {"queryPerformers": {"performers": pool}}}
        if operation == "CuratorPerformerSearch":
            input_data = json.loads(body)["variables"]["input"]
            names = input_data.get("names", "")
            needle = str(names).casefold()
            pool = [
                {
                    "id": performer["id"],
                    "name": performer["name"],
                    "aliases": performer.get("aliases", []),
                    "disambiguation": performer.get("disambiguation"),
                    "scene_count": performer.get("scene_count"),
                    "images": performer.get("images", []),
                }
                for performer in STASHDB_PERFORMER_POOL
                if not needle or needle in str(performer["name"]).casefold()
            ]
            return {"data": {"queryPerformers": {"performers": pool}}}
        return {"errors": [{"message": f"no stub for {operation}"}]}

    @staticmethod
    def _operation_name(body: str) -> str:
        for name in (
            "CuratorPluginSettings",
            "CuratorStashBoxes",
            "CuratorExternalLinksState",
            "CuratorExternalLinks",
            "CuratorExpandScenes",
            "CuratorSimilarPerformers",
            "CuratorPerformerSearch",
        ):
            if name in body:
                return name
        return "unknown"

    def log_message(self, *args: object) -> None:
        pass


class _StubWhisparr(BaseHTTPRequestHandler):
    """A minimal Whisparr /api/v3 stub with deterministic responses."""

    movies: ClassVar[list[dict[str, object]]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/api/v3/movie"):
            data: object = self.movies
        elif self.path.startswith("/api/v3/rootfolder"):
            data = [{"id": 1, "path": "/movies", "name": "Movies"}]
        elif self.path.startswith("/api/v3/qualityprofile"):
            data = [{"id": 2, "name": "Any", "fallback": True}]
        else:
            data = []
        self._respond(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if "/api/v3/movie" in self.path:
            data: object = {"id": 77, "title": "added"}
        elif "/api/v3/command" in self.path:
            data = {"id": 9, "name": "MoviesSearch"}
        else:
            data = {}
        self._respond(data)

    def _respond(self, data: object) -> None:
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

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
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubExpand)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def stub_whisparr() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubWhisparr)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


# ── sidecar seeding ────────────────────────────────────────────────────────


def make_expand_sidecar(path: Path) -> None:
    """A builder-seeded sidecar with the external-discovery state the
    network ops read: a published model, tag→StashDB id mappings, taxonomy,
    and deterministic candidate/shortlist rows."""
    connection = _database(path)
    try:
        PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
        connection.executemany(
            """
            INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id)
            VALUES (?, ?, ?)
            """,
            [
                ("good", STASHDB_ENDPOINT, "ext-good"),
                ("bad", STASHDB_ENDPOINT, "ext-bad"),
                ("unusual", STASHDB_ENDPOINT, "ext-unusual"),
            ],
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference_history(
                preference_id, tag_id, value, occurred_at_ms
            ) VALUES ('pref-slice2', 'good', 0.5, ?)
            """,
            (REFERENCE_MS - 10 * 86_400_000,),
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference(tag_id, preference_id, value, occurred_at_ms)
            VALUES ('good', 'pref-slice2', 0.5, ?)
            """,
            (REFERENCE_MS - 10 * 86_400_000,),
        )
        connection.execute(
            """
            INSERT INTO taxonomy_snapshot(
                snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
            ) VALUES ('tax-slice2', ?, ?, 0, 2)
            """,
            (STASHDB_ENDPOINT, REFERENCE_MS - 2 * 86_400_000),
        )
        connection.executemany(
            """
            INSERT INTO taxonomy_tag(snapshot_id, tag_id, name, category_id)
            VALUES ('tax-slice2', ?, ?, NULL)
            """,
            [("ext-good", "Familiar Scenario"), ("ext-unusual", "Unusual Scenario")],
        )
        connection.executemany(
            """
            INSERT INTO taxonomy_tag_alias(snapshot_id, tag_id, alias)
            VALUES ('tax-slice2', ?, ?)
            """,
            [("ext-good", "Comfy Scenario"), ("ext-unusual", "Strange Scenario")],
        )
        connection.execute(
            "INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', 'tax-slice2')"
        )
        candidate_payloads = [
            {
                "id": "cand-1",
                "title": "Candidate One",
                "release_date": "2024-01-10",
                "studio": {"id": "ext-studio-1", "name": "Studio One"},
                "tags": [{"id": "ext-good", "name": "Familiar Scenario"}],
                "performers": [{"performer": dict(STASHDB_PERFORMERS["ext-p2"])}],
            },
            {
                "id": "cand-2",
                "title": "Candidate Two",
                "release_date": "2024-02-20",
                "studio": {"id": "ext-studio-2", "name": "Studio Two"},
                "tags": [{"id": "ext-unusual", "name": "Unusual Scenario"}],
                "performers": [{"performer": dict(STASHDB_PERFORMERS["ext-p3"])}],
            },
            {
                "id": "cand-3",
                "title": "Candidate Three",
                "release_date": "2024-03-05",
                "studio": {"id": "ext-studio-1", "name": "Studio One"},
                "tags": [{"id": "ext-good", "name": "Familiar Scenario"}],
                "performers": [{"performer": dict(STASHDB_PERFORMERS["ext-p2"])}],
            },
        ]
        connection.executemany(
            """
            INSERT INTO external_entity(
                entity_type, external_id, payload_json, score, sources_json,
                fetched_at_ms, pool
            ) VALUES ('scene', ?, ?, ?, ?, ?, 'candidate')
            """,
            [
                (
                    "cand-1",
                    json.dumps(candidate_payloads[0], separators=(",", ":")),
                    0.42,
                    '["tags"]',
                    REFERENCE_MS - 5 * 86_400_000,
                ),
                (
                    "cand-2",
                    json.dumps(candidate_payloads[1], separators=(",", ":")),
                    0.31,
                    '["performers"]',
                    REFERENCE_MS - 4 * 86_400_000,
                ),
                (
                    "cand-3",
                    json.dumps(candidate_payloads[2], separators=(",", ":")),
                    0.55,
                    '["tags","manual"]',
                    REFERENCE_MS - 3 * 86_400_000,
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO expand_cache(
                singleton, model_id, fetched_at_ms, expires_at_ms,
                scene_count, performer_count
            ) VALUES (1, 'expand-model', ?, ?, 3, 0)
            """,
            (REFERENCE_MS - 2 * 86_400_000, REFERENCE_MS + 10 * 86_400_000),
        )
        connection.executemany(
            """
            INSERT INTO external_shortlist(
                entity_type, external_id, score, sources_json, payload_json, added_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "scene",
                    "cand-2",
                    0.31,
                    '["performers"]',
                    json.dumps(candidate_payloads[1], separators=(",", ":")),
                    REFERENCE_MS - 86_400_000,
                ),
                (
                    "performer",
                    "ext-p3",
                    0.0,
                    '["similar"]',
                    json.dumps(STASHDB_PERFORMERS["ext-p3"], separators=(",", ":")),
                    REFERENCE_MS - 86_400_000,
                ),
            ],
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


@pytest.fixture(scope="module")
def expand_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("expand-sidecar") / "curator.sqlite3"
    make_expand_sidecar(path)
    return path


# ── differential runner ────────────────────────────────────────────────────


def run_backend_env(
    binary: Path | None,
    plugin_dir: Path,
    raw: bytes,
    stashdb_override: str,
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["CURATOR_STASHDB_ENDPOINT"] = stashdb_override
    if binary is None:
        argv = [sys.executable, str(BACKEND), str(plugin_dir)]
    else:
        argv = [str(binary), str(plugin_dir)]
    return subprocess.run(argv, input=raw, capture_output=True, timeout=180, env=env)


def assert_slice2_identical(
    binary: Path,
    plugin_dir: Path,
    raw: bytes,
    same_path: Path,
    stashdb_override: str,
    *,
    timing_fields: tuple[str, ...] = (),
) -> None:
    """Run both backends on fresh sidecar copies (with the model's derived
    artifact directory) and assert byte-identical outputs once the
    run-varying timing fields are compared structurally."""
    run_dir = same_path.parent / f"{same_path.stem}-backend-run"
    run_db = run_dir / same_path.name
    derived_src = same_path.parent / f"{same_path.stem}-derived"
    outputs: list = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        shutil.copy2(same_path, run_db)
        derived_dst = run_dir / f"{run_db.stem}-derived"
        if derived_src.is_dir():
            shutil.copytree(derived_src, derived_dst)
        try:
            result = run_backend_env(
                runner, plugin_dir, _with_db_path(raw, run_db), stashdb_override
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
    from tests.core.compare import assert_equivalent

    if python_result.returncode != 0:
        assert_equivalent(py_out, go_out)
        return
    assert set(py_out) == {"output"} and set(go_out) == {"output"}
    a, b = py_out["output"], go_out["output"]
    for field in timing_fields:
        if isinstance(a[field], dict):
            assert set(a[field]) == set(b[field]), (a[field], b[field])
            for value in (*a[field].values(), *b[field].values()):
                assert isinstance(value, int) and value >= 0
        else:
            assert isinstance(a[field], int) and isinstance(b[field], int)
            assert a[field] >= 0 and b[field] >= 0
        a.pop(field)
        b.pop(field)
    # Stored floats may differ by last bits across libm/CPU environments;
    # compare structure exactly and floats within tolerance.
    assert_equivalent(a, b)


def _with_db_path(raw: bytes, db_path: Path) -> bytes:
    parsed = json.loads(raw)
    parsed["args"]["database_path"] = str(db_path)
    return json.dumps(parsed, separators=(",", ":")).encode()


def _run_once_on_copy(
    binary: Path | None,
    plugin_dir: Path,
    raw: bytes,
    same_path: Path,
    stashdb_override: str,
) -> Path:
    run_dir = same_path.parent / f"{same_path.stem}-write-run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir()
    run_db = run_dir / same_path.name
    shutil.copy2(same_path, run_db)
    derived_src = same_path.parent / f"{same_path.stem}-derived"
    if derived_src.is_dir():
        shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
    result = run_backend_env(binary, plugin_dir, _with_db_path(raw, run_db), stashdb_override)
    assert result.returncode == 0, result.stdout + result.stderr
    return run_db


# ── byte-identical network ops ─────────────────────────────────────────────


def test_get_expand_byte_identical(expand_sidecar: Path, binary: Path, stub_stash: str) -> None:
    raw = payload("get_expand", expand_sidecar, stub_stash, entity_type="scene", page=1, count=10)
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_expand_filters_and_sorts_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_expand",
        expand_sidecar,
        stub_stash,
        entity_type="scene",
        sort="newest",
        page=1,
        count=2,
        gender="FEMALE",
        minimum_score=0.3,
    )
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_expand_performer_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_expand", expand_sidecar, stub_stash, entity_type="performer", page=1, count=10
    )
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_expand_invalid_query_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_expand", expand_sidecar, stub_stash, entity_type="studio", page=1)
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_performer_hunt_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_performer_hunt", expand_sidecar, stub_stash, performer_id="p1")
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_performer_hunt_external_id_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload("get_performer_hunt", expand_sidecar, stub_stash, performer_id="ext-p3")
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_performer_hunt_unlinked_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    # p3 has no StashDB link in the stub; both backends must raise the same
    # "selected performer is not linked to StashDB" error.
    raw = payload("get_performer_hunt", expand_sidecar, stub_stash, performer_id="p3")
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_stashdb_performer_search_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """Issue #218: the StashDB performer name search (Performer Hunt picker)
    answers identically on both backends, including the not-found case."""
    raw = payload("get_stashdb_performer_search", expand_sidecar, stub_stash, query="Performer")
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    raw = payload(
        "get_stashdb_performer_search", expand_sidecar, stub_stash, query="Nobody Named This"
    )
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_get_external_similar_scene_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_external_similar",
        expand_sidecar,
        stub_stash,
        entity_type="scene",
        entity_id="recent-good",
    )
    assert_slice2_identical(
        binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash, timing_fields=("timings_ms",)
    )


def test_get_external_similar_scene_owned_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_external_similar",
        expand_sidecar,
        stub_stash,
        entity_type="scene",
        entity_id="recent-good",
        include_owned=True,
        hide_phash_matches=False,
    )
    assert_slice2_identical(
        binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash, timing_fields=("timings_ms",)
    )


def test_get_external_similar_performer_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_external_similar",
        expand_sidecar,
        stub_stash,
        entity_type="performer",
        entity_id="p1",
    )
    assert_slice2_identical(
        binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash, timing_fields=("timings_ms",)
    )


def test_get_external_similar_performer_owned_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_external_similar",
        expand_sidecar,
        stub_stash,
        entity_type="performer",
        entity_id="p2",
        include_owned=True,
    )
    assert_slice2_identical(
        binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash, timing_fields=("timings_ms",)
    )


def test_get_external_similar_invalid_entity_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    raw = payload(
        "get_external_similar",
        expand_sidecar,
        stub_stash,
        entity_type="studio",
        entity_id="studio-1",
    )
    assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)


def test_send_whisparr_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str, stub_whisparr: str
) -> None:
    _StubWhisparr.movies = []
    _StubExpand.plugin_settings = {
        "whisparrUrl": stub_whisparr,
        "whisparrApiKey": "test-key",
        "whisparrRootFolder": "",
        "whisparrQualityProfileId": 0,
        "whisparrSearchImmediately": True,
    }
    try:
        raw = payload("send_whisparr", expand_sidecar, stub_stash, external_id="cand-2")
        assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    finally:
        _StubExpand.plugin_settings = {}


def test_send_whisparr_already_exists_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str, stub_whisparr: str
) -> None:
    _StubWhisparr.movies = [{"stashId": "cand-2", "foreignId": "cand-2", "id": 55}]
    _StubExpand.plugin_settings = {
        "whisparrUrl": stub_whisparr,
        "whisparrApiKey": "test-key",
        "whisparrRootFolder": "/movies",
        "whisparrQualityProfileId": 2,
        "whisparrSearchImmediately": False,
    }
    try:
        raw = payload("send_whisparr", expand_sidecar, stub_stash, external_id="cand-2")
        assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    finally:
        _StubWhisparr.movies = []
        _StubExpand.plugin_settings = {}


def test_send_whisparr_not_in_expand_byte_identical(
    expand_sidecar: Path, binary: Path, stub_stash: str, stub_whisparr: str
) -> None:
    _StubExpand.plugin_settings = {
        "whisparrUrl": stub_whisparr,
        "whisparrApiKey": "test-key",
    }
    try:
        raw = payload("send_whisparr", expand_sidecar, stub_stash, external_id="missing-scene")
        assert_slice2_identical(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    finally:
        _StubExpand.plugin_settings = {}


# ── read-path write parity ─────────────────────────────────────────────────


def test_external_links_cache_write_parity(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """The external-links cache upsert (application_meta value bytes) must
    match Python exactly: same state hash, same insertion-ordered links."""
    raw = payload("get_performer_hunt", expand_sidecar, stub_stash, performer_id="p1")
    python_db = _run_once_on_copy(None, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    go_db = _run_once_on_copy(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    for db_path in (python_db, go_db):
        connection = sqlite3.connect(db_path)
        try:
            row = connection.execute(
                "SELECT value FROM application_meta WHERE key='external_links'"
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        python_db_value = None
        if db_path == python_db:
            python_db_value = row[0]
        else:
            assert row[0] == python_db_value
    python_value = (
        sqlite3.connect(python_db)
        .execute("SELECT value FROM application_meta WHERE key='external_links'")
        .fetchone()[0]
    )
    go_value = (
        sqlite3.connect(go_db)
        .execute("SELECT value FROM application_meta WHERE key='external_links'")
        .fetchone()[0]
    )
    assert go_value == python_value


def test_external_entity_merge_write_parity(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """The performer hunt's explore-pool merge must leave identical
    external_entity rows on both implementations (fetched_at_ms varies)."""
    raw = payload("get_performer_hunt", expand_sidecar, stub_stash, performer_id="p1")
    python_db = _run_once_on_copy(None, PLUGIN_DIR, raw, expand_sidecar, stub_stash)
    go_db = _run_once_on_copy(binary, PLUGIN_DIR, raw, expand_sidecar, stub_stash)

    def state(path: Path) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(path)
        try:
            return sorted(
                connection.execute(
                    """
                    SELECT entity_type, external_id, payload_json, score,
                           sources_json, pool
                    FROM external_entity
                    WHERE external_id LIKE 'stashdb-%' OR external_id='ext-scene-1'
                    """
                ).fetchall()
            )
        finally:
            connection.close()

    assert state(go_db) == state(python_db)


# ── profiling parity for the Slice-2 ops ───────────────────────────────────


@pytest.mark.parametrize(
    "operation,args",
    [
        ("get_expand", {"entity_type": "scene", "page": 1, "count": 5}),
        ("get_performer_hunt", {"performer_id": "p1"}),
        ("get_external_similar", {"entity_type": "scene", "entity_id": "recent-good"}),
    ],
)
def test_slice2_profiling_trace_parity(
    expand_sidecar: Path,
    binary: Path,
    stub_stash: str,
    operation: str,
    args: dict[str, object],
) -> None:
    """Every Slice-2 op records a profile_trace row when profilingEnabled is
    on, with the same shape on both implementations: root plugin event, a
    stash span for the settings fetch, stashdb spans for the network ops,
    and sqlite spans."""
    import re

    _StubExpand.plugin_settings = {"profilingEnabled": True}
    try:
        sidecar = expand_sidecar
        raw = payload(operation, sidecar, stub_stash, **args)
        rows: dict[str, tuple] = {}
        for runner in (None, binary):
            run_dir = sidecar.parent / f"{sidecar.stem}-trace-{runner is None}"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / sidecar.name
            shutil.copy2(sidecar, run_db)
            derived_src = sidecar.parent / f"{sidecar.stem}-derived"
            if derived_src.is_dir():
                shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            result = run_backend_env(runner, PLUGIN_DIR, _with_db_path(raw, run_db), stub_stash)
            assert result.returncode == 0, result.stdout + result.stderr
            connection = sqlite3.connect(run_db)
            try:
                row = connection.execute(
                    """
                    SELECT trace_id, kind, operation, started_at_ms, duration_us,
                           status, span_count, truncated, trace_json
                    FROM profile_trace
                    """
                ).fetchone()
            finally:
                connection.close()
            rows["python" if runner is None else "go"] = row
    finally:
        _StubExpand.plugin_settings = {}
    python_row, go_row = rows["python"], rows["go"]
    assert python_row is not None and go_row is not None
    for row in (python_row, go_row):
        trace_id, kind, operation_name, _, duration_us, status, span_count, truncated, _ = row
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", trace_id
        )
        assert kind == "operation" and operation_name == operation
        assert status == "ok" and truncated == 0
        assert duration_us >= 0 and span_count > 0
    python_json = json.loads(python_row[8])
    go_json = json.loads(go_row[8])
    assert python_json["displayTimeUnit"] == go_json["displayTimeUnit"] == "ms"
    for events in (python_json["traceEvents"], go_json["traceEvents"]):
        root = events[0]
        assert root["name"] == operation and root["cat"] == "plugin"
        assert root["args"] == {"status": "ok", "kind": "operation"}
        assert any(e["cat"] == "stash" and e["name"] == "CuratorPluginSettings" for e in events)
        assert any(e["cat"] == "sqlite" for e in events)
        for event in events:
            assert {"name", "cat", "ph", "ts", "dur", "pid", "tid"} <= set(event)


def test_slice2_network_ops_record_stashdb_spans(
    expand_sidecar: Path, binary: Path, stub_stash: str
) -> None:
    """The network ops record stashdb spans for their StashDB queries."""
    _StubExpand.plugin_settings = {"profilingEnabled": True}
    try:
        sidecar = expand_sidecar
        raw = payload("get_performer_hunt", sidecar, stub_stash, performer_id="p1")
        categories: dict[str, set[str]] = {}
        for runner in (None, binary):
            run_dir = sidecar.parent / f"{sidecar.stem}-spans-{runner is None}"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir()
            run_db = run_dir / sidecar.name
            shutil.copy2(sidecar, run_db)
            derived_src = sidecar.parent / f"{sidecar.stem}-derived"
            if derived_src.is_dir():
                shutil.copytree(derived_src, run_dir / f"{run_db.stem}-derived")
            result = run_backend_env(runner, PLUGIN_DIR, _with_db_path(raw, run_db), stub_stash)
            assert result.returncode == 0, result.stdout + result.stderr
            connection = sqlite3.connect(run_db)
            try:
                trace_json = connection.execute("SELECT trace_json FROM profile_trace").fetchone()[
                    0
                ]
            finally:
                connection.close()
            events = json.loads(trace_json)["traceEvents"]
            name = "python" if runner is None else "go"
            categories[name] = {
                (event["cat"], event["name"])
                for event in events
                if event["cat"] in {"stash", "stashdb", "sqlite"}
            }
            assert ("stash", "CuratorPluginSettings") in categories[name]
            assert ("stash", "CuratorStashBoxes") in categories[name]
            assert ("stashdb", "CuratorExpandScenes") in categories[name]
    finally:
        _StubExpand.plugin_settings = {}
