"""get_lane_scene_page: a lane as a Stash scene list, Python and Go identical."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from http.server import HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator.core import core_binary
from curator.model import PreferenceModelBuilder
from curator.storage import connect_database
from scripts import synthetic_corpus
from tests.core.test_backend import (
    PLUGIN_DIR,
    RUNTIME_RESPONSE,
    SETTINGS_RESPONSE,
    _StubStash,
    payload,
    run_backend,
)
from tests.core.test_backend_slice1 import assert_slice1_identical
from tests.model.test_builder import _database

# A small synthetic library whose model fills For You, Best Bets and Revisit
# with dozens of scenes, so pages, draws and narrowing have something to do.
CORPUS = {"seed": 7, "n_scenes": 300, "n_tags": 200, "n_performers": 150}
# Stash's answer to the IDs query: its filter's matches, in its sort order
# (every scene, in reverse ID order, until a test narrows it).
STASH_ORDER: list[str] = []


class _StubLaneScenes(_StubStash):
    matches: ClassVar[list[str]] = STASH_ORDER
    variables: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        request = json.loads(body)
        if "CuratorLaneSceneIds" in request["query"]:
            self.variables.append(request["variables"])
            answer: dict[str, object] = {
                "data": {"findScenes": {"scenes": [{"id": scene} for scene in self.matches]}}
            }
        elif "CuratorPluginRuntime" in request["query"]:
            answer = RUNTIME_RESPONSE
        elif "CuratorPluginSettings" in request["query"]:
            answer = SETTINGS_RESPONSE
        else:
            answer = {"errors": [{"message": "no stub"}]}
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def model_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("lane-scenes") / "curator.sqlite3"
    synthetic_corpus.build_sidecar(path, **CORPUS)
    connection = connect_database(path)
    try:
        PreferenceModelBuilder(connection, clock_ms=lambda: synthetic_corpus.REFERENCE_MS).build()
        scenes = [row[0] for row in connection.execute("SELECT scene_id FROM source_scene")]
    finally:
        connection.close()
    STASH_ORDER[:] = sorted(scenes, reverse=True)
    _StubLaneScenes.matches = STASH_ORDER
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubLaneScenes)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _page(binary: Path, sidecar: Path, stub: str, **args: object) -> dict[str, object]:
    raw = payload("get_lane_scene_page", sidecar, stub, **args)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=sidecar)
    _StubLaneScenes.variables.clear()
    return json.loads(run_backend(binary, PLUGIN_DIR, raw).stdout)["output"]


def _lane_order(binary: Path, sidecar: Path, stub: str, lane: str) -> list[str]:
    output = _page(binary, sidecar, stub, lane=lane, order="rank", per_page=-1)
    assert not _StubLaneScenes.variables, "Rank order without filters needs no Stash query"
    return output["scene_ids"]


@pytest.mark.parametrize(
    "lane", ["for_you", "best_bets", "revisit", "stretch", "blind_spots", "dormant", "new_arrivals"]
)
def test_lane_rank_pages(model_sidecar: Path, binary: Path, stub_stash: str, lane: str) -> None:
    order = _lane_order(binary, model_sidecar, stub_stash, lane)
    first = _page(binary, model_sidecar, stub_stash, lane=lane, order="rank", per_page=2)
    assert first["lane"] == lane
    assert first["scene_ids"] == order[:2]
    assert first["count"] == len(order)
    second = _page(binary, model_sidecar, stub_stash, lane=lane, order="rank", per_page=2, page=2)
    assert second["scene_ids"] == order[2:4]
    reverse = _page(
        binary, model_sidecar, stub_stash, lane=lane, order="rank", direction="ASC", per_page=-1
    )
    assert reverse["scene_ids"] == order[::-1]


@pytest.mark.parametrize("lane", ["for_you", "best_bets", "revisit"])
def test_the_corpus_fills_the_lanes(
    model_sidecar: Path, binary: Path, stub_stash: str, lane: str
) -> None:
    assert len(_lane_order(binary, model_sidecar, stub_stash, lane)) >= 20


def test_stash_filters_narrow_the_lane_and_stash_sorts_it(
    model_sidecar: Path,
    binary: Path,
    stub_stash: str,
) -> None:
    order = _lane_order(binary, model_sidecar, stub_stash, "for_you")
    scene_filter = {"title": {"value": "Good", "modifier": "INCLUDES"}}
    _StubLaneScenes.matches = STASH_ORDER[::2]
    matches = set(_StubLaneScenes.matches)
    try:
        ranked = _page(
            binary,
            model_sidecar,
            stub_stash,
            lane="for_you",
            order="rank",
            per_page=-1,
            scene_filter=scene_filter,
            filter={"q": "", "sort": "curator_lane_rank", "direction": "DESC"},
        )
        assert ranked["scene_ids"] == [scene for scene in order if scene in matches]
        assert 0 < len(ranked["scene_ids"]) < len(order)
        sorted_by_stash = _page(
            binary,
            model_sidecar,
            stub_stash,
            lane="for_you",
            per_page=-1,
            filter={"sort": "date", "direction": "DESC", "per_page": 40},
        )
        assert sorted_by_stash["scene_ids"] == [s for s in _StubLaneScenes.matches if s in order]
        raw = payload(
            "get_lane_scene_page",
            model_sidecar,
            stub_stash,
            lane="for_you",
            filter={"sort": "date", "direction": "DESC", "page": 3, "per_page": 40},
        )
        _StubLaneScenes.variables.clear()
        run_backend(binary, PLUGIN_DIR, raw)
        (variables,) = _StubLaneScenes.variables
        assert variables["filter"] == {
            "sort": "date",
            "direction": "DESC",
            "page": 1,
            "per_page": -1,
        }
        assert variables["scene_filter"] is None and variables["scene_ids"] is None
    finally:
        _StubLaneScenes.matches = STASH_ORDER
        _StubLaneScenes.variables.clear()


@pytest.mark.parametrize(
    "args",
    [
        {"lane": "nope"},
        {"lane": ""},
        {"lane": "for_you", "page": 0},
        {"lane": "for_you", "per_page": -2},
        {"lane": "for_you", "direction": "sideways"},
        {"lane": "for_you", "order": "random"},
    ],
)
def test_lane_scene_page_validation(
    model_sidecar: Path,
    binary: Path,
    stub_stash: str,
    args: dict[str, object],
) -> None:
    raw = payload("get_lane_scene_page", model_sidecar, stub_stash, **args)
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=model_sidecar)
    assert run_backend(binary, PLUGIN_DIR, raw).returncode != 0


def test_lane_scene_page_requires_published_model(
    tmp_path: Path,
    binary: Path,
    stub_stash: str,
) -> None:
    sidecar = tmp_path / "nomodel.sqlite3"
    _database(sidecar).close()
    raw = payload("get_lane_scene_page", sidecar, stub_stash, lane="for_you")
    assert_slice1_identical(binary, PLUGIN_DIR, raw, same_path=sidecar)
    assert run_backend(binary, PLUGIN_DIR, raw).returncode != 0


def _private_copy(model_sidecar: Path, tmp_path: Path) -> Path:
    path = tmp_path / model_sidecar.name
    shutil.copy2(model_sidecar, path)
    shutil.copytree(
        model_sidecar.parent / f"{model_sidecar.stem}-derived",
        tmp_path / f"{path.stem}-derived",
    )
    return path


@pytest.mark.parametrize("lane", ["for_you", "best_bets", "revisit"])
def test_lane_picks_match_the_lane_page_draw(
    model_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path, lane: str
) -> None:
    """Picks is the lane page's draw for the same seed, then the rest of the lane."""
    path = _private_copy(model_sidecar, tmp_path)
    draw = {"draw_seed": "seed-a", "draw_at_ms": synthetic_corpus.REFERENCE_MS}
    picks = _page(binary, path, stub_stash, lane=lane, order="picks", per_page=-1, **draw)
    rank = _lane_order(binary, path, stub_stash, lane)
    assert sorted(picks["scene_ids"]) == sorted(rank)
    raw = payload("get_slate", path, stub_stash, lane=lane, impression_id="fixed-lane-page", **draw)
    slate = json.loads(run_backend(binary, PLUGIN_DIR, raw).stdout)["output"]
    shown = [item["scene_id"] for item in slate["items"]]
    assert shown and picks["scene_ids"][: len(shown)] == shown
    other = _page(binary, path, stub_stash, lane=lane, order="picks", per_page=-1, draw_seed="b")
    assert sorted(other["scene_ids"]) == sorted(rank)
    # Without a seed, picks is the lane's rank order.
    unseeded = _page(binary, path, stub_stash, lane=lane, order="picks", per_page=-1)
    assert unseeded["scene_ids"] == rank


def _impression_rows(path: Path, impression_id: str) -> tuple[list[tuple], list[tuple]]:
    with sqlite3.connect(path) as connection:
        impressions = connection.execute(
            "SELECT lane, model_id, request_context_json FROM impression WHERE impression_id=?",
            (impression_id,),
        ).fetchall()
        items = connection.execute(
            "SELECT scene_id, position, policy_score, reason_snapshot_json FROM impression_item"
            " WHERE impression_id=? ORDER BY position",
            (impression_id,),
        ).fetchall()
    return impressions, items


def test_a_served_page_is_recorded_as_a_lane_impression(
    model_sidecar: Path, binary: Path, stub_stash: str, tmp_path: Path
) -> None:
    rows = []
    for runner in (None, binary):
        run_dir = tmp_path / ("go" if runner else "python")
        run_dir.mkdir()
        path = _private_copy(model_sidecar, run_dir)
        raw = payload(
            "get_lane_scene_page",
            path,
            stub_stash,
            lane="for_you",
            order="rank",
            per_page=2,
            page=2,
            impression_id="stash-list-1",
        )
        output = json.loads(run_backend(runner, PLUGIN_DIR, raw).stdout)["output"]
        assert output["impression_id"] == "stash-list-1"
        impressions, items = _impression_rows(path, "stash-list-1")
        assert [item[0] for item in items] == output["scene_ids"]
        assert [item[1] for item in items] == [2, 3][: len(items)]
        assert impressions[0][2] == '{"order":"rank","surface":"stash_scene_list"}'
        rows.append((impressions, items))
        # Without an impression_id nothing is written.
        raw = payload("get_lane_scene_page", path, stub_stash, lane="for_you", order="rank")
        assert (
            json.loads(run_backend(runner, PLUGIN_DIR, raw).stdout)["output"]["impression_id"]
            is None
        )
    assert rows[0] == rows[1]
