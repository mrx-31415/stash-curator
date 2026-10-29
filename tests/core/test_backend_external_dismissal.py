"""External scene dismissals: Go/Python parity and Find filtering.

update_external_dismissal and get_external_dismissals run through both
backends; get_expand, get_performer_hunt and get_external_similar must drop
dismissed scenes identically, and an expired Not now must reappear. Synthetic
sidecars only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from curator.core import core_binary
from tests.core.test_backend import payload
from tests.core.test_backend_slice2 import (
    PLUGIN_DIR,
    _StubExpand,
    assert_slice2_identical,
    make_expand_sidecar,
    run_backend_env,
)

DAY_MS = 86_400_000
FAR_FUTURE_MS = 4_000_000_000_000


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


@pytest.fixture
def sidecar(tmp_path: Path) -> Path:
    path = tmp_path / "curator.sqlite3"
    make_expand_sidecar(path)
    return path


def _output(binary: Path, raw: bytes, stub: str) -> dict:
    result = run_backend_env(binary, PLUGIN_DIR, raw, stub)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)["output"]


def _expand_ids(binary: Path, sidecar: Path, stub: str) -> list[str]:
    raw = payload("get_expand", sidecar, stub, gender="", hide_phash_matches=False)
    return [item["id"] for item in _output(binary, raw, stub)["items"]]


def _dismiss(sidecar: Path, rows: list[tuple[str, str, int, int | None]]) -> None:
    with sqlite3.connect(sidecar) as connection:
        connection.executemany(
            """
            INSERT INTO external_dismissal(
              endpoint, external_id, kind, created_at_ms, expires_at_ms, payload_json
            ) VALUES ('https://stashdb.org/graphql', ?, ?, ?, ?, '{"title": "Hidden"}')
            """,
            rows,
        )


def test_update_external_dismissal_matches(binary: Path, stub_stash: str, sidecar: Path) -> None:
    for args in [
        {"external_id": "cand-1", "kind": "not_interested"},
        {"external_id": "cand-1", "kind": "not_now"},
        {"external_id": "cand-1", "kind": None},
        {"external_id": "cand-1", "kind": "never"},
        {"external_id": "not-in-cache", "kind": "not_now"},
    ]:
        raw = payload("update_external_dismissal", sidecar, stub_stash, **args)
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)


def test_dismissal_hides_scene_until_undone(binary: Path, stub_stash: str, sidecar: Path) -> None:
    before = _expand_ids(binary, sidecar, stub_stash)
    assert "cand-1" in before
    # The first query caches Expand's ordering; the dismissal must invalidate it.
    raw = payload(
        "update_external_dismissal", sidecar, stub_stash, external_id="cand-1", kind="not_now"
    )
    assert _output(binary, raw, stub_stash)["kind"] == "not_now"
    assert _expand_ids(binary, sidecar, stub_stash) == [id for id in before if id != "cand-1"]
    with sqlite3.connect(sidecar) as connection:
        created, expires, stored = connection.execute(
            "SELECT created_at_ms, expires_at_ms, payload_json FROM external_dismissal"
        ).fetchone()
    assert expires - created == 30 * DAY_MS
    assert json.loads(stored)["title"]

    history = _output(binary, payload("get_external_dismissals", sidecar, stub_stash), stub_stash)
    assert history["total"] == 1
    assert history["items"][0]["id"] == "cand-1"
    # Card-shaped: the cached candidate still supplies its score and sources.
    assert history["ready"] is True
    assert history["items"][0]["score"] > 0
    assert history["items"][0]["sources"]
    raw_history = payload("get_external_dismissals", sidecar, stub_stash)
    assert_slice2_identical(binary, PLUGIN_DIR, raw_history, sidecar, stub_stash)

    raw = payload("update_external_dismissal", sidecar, stub_stash, external_id="cand-1")
    _output(binary, raw, stub_stash)
    assert _expand_ids(binary, sidecar, stub_stash) == before


def test_find_views_skip_active_dismissals(binary: Path, stub_stash: str, sidecar: Path) -> None:
    similar_args = {"entity_type": "scene", "entity_id": "recent-good"}
    hunt = payload("get_performer_hunt", sidecar, stub_stash, performer_id="ext-p3")
    similar = payload("get_external_similar", sidecar, stub_stash, **similar_args)
    hunt_ids = [item["id"] for item in _output(binary, hunt, stub_stash)["items"]]
    similar_ids = [item["id"] for item in _output(binary, similar, stub_stash)["items"]]
    assert hunt_ids and similar_ids
    expand_ids = _expand_ids(binary, sidecar, stub_stash)
    hidden = {expand_ids[0], hunt_ids[0], similar_ids[0]}
    expired = next(id for id in expand_ids if id not in hidden)
    _dismiss(
        sidecar,
        [(id, "not_interested", 1, None) for id in sorted(hidden)]
        + [(expired, "not_now", 1, 1 + DAY_MS)],
    )
    # One active Not now as well, to cover the expiry comparison's other side.
    with sqlite3.connect(sidecar) as connection:
        connection.execute(
            "UPDATE external_dismissal SET kind='not_now', expires_at_ms=? WHERE external_id=?",
            (FAR_FUTURE_MS, sorted(hidden)[0]),
        )

    expand = payload("get_expand", sidecar, stub_stash, gender="", hide_phash_matches=False)
    for raw in (expand, hunt):
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)
    assert_slice2_identical(
        binary, PLUGIN_DIR, similar, sidecar, stub_stash, timing_fields=("timings_ms",)
    )
    # Removing a scene may change the performer-diversity order, so compare sets.
    expand_after = {item["id"] for item in _output(binary, expand, stub_stash)["items"]}
    assert expand_after == set(expand_ids) - hidden
    assert expired in expand_after
    # Hunt keeps dismissed scenes and marks them; the client filters them
    # like PHash matches.
    hunt_after = {
        item["id"]: item["dismissed"] for item in _output(binary, hunt, stub_stash)["items"]
    }
    assert set(hunt_after) == set(hunt_ids)
    assert {id for id, kind in hunt_after.items() if kind} == hidden & set(hunt_ids)
    similar_after = {item["id"] for item in _output(binary, similar, stub_stash)["items"]}
    assert not similar_after & hidden

    # With hide_dismissed off, Expand and Similar return them, marked by kind.
    shown_expand = payload(
        "get_expand", sidecar, stub_stash, gender="", hide_phash_matches=False, hide_dismissed=False
    )
    shown_similar = payload(
        "get_external_similar", sidecar, stub_stash, hide_dismissed=False, **similar_args
    )
    assert_slice2_identical(binary, PLUGIN_DIR, shown_expand, sidecar, stub_stash)
    assert_slice2_identical(
        binary, PLUGIN_DIR, shown_similar, sidecar, stub_stash, timing_fields=("timings_ms",)
    )
    marked = {
        item["id"]: item["dismissed"] for item in _output(binary, shown_expand, stub_stash)["items"]
    }
    assert set(marked) == set(expand_ids)
    assert {id for id, kind in marked.items() if kind} == hidden & set(expand_ids)
    assert marked[sorted(hidden)[0]] in {"not_now", "not_interested"}
    assert marked[expired] is None
    shown = {item["id"] for item in _output(binary, shown_similar, stub_stash)["items"]}
    assert similar_ids[0] in shown

    history = payload("get_external_dismissals", sidecar, stub_stash, page_size=2)
    assert_slice2_identical(binary, PLUGIN_DIR, history, sidecar, stub_stash)
    result = _output(binary, history, stub_stash)
    assert result["total"] == len(hidden)
    assert result["has_more"] is (len(hidden) > 2)
    assert expired not in {item["id"] for item in result["items"]}
    for bad in (0, 101):
        raw = payload("get_external_dismissals", sidecar, stub_stash, page_size=bad)
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)


def _reason(**extra: object) -> dict[str, object]:
    return {
        "answer_id": "x-1",
        "external_id": "cand-1",
        "polarity": -1,
        "reasons": [{"subject_type": "performer", "subject_id": "p1"}],
        "occurred_at_ms": 5,
        **extra,
    }


def test_submit_external_scene_reasons_matches(
    binary: Path, stub_stash: str, sidecar: Path
) -> None:
    for entries in [
        [
            _reason(
                reasons=[
                    {"subject_type": "studio", "subject_id": "studio-1"},
                    {"subject_type": "tag", "subject_id": "good"},
                ]
            )
        ],
        [_reason(), _reason()],
        [_reason(reasons=[])],
        [_reason(reasons=[{"subject_type": "scene", "subject_id": ""}])],
        [_reason(polarity=True)],
        [_reason(external_id="")],
        "not-a-list",
    ]:
        raw = payload("submit_external_scene_reasons", sidecar, stub_stash, entries=entries)
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)
    raw = payload("submit_external_scene_reasons", sidecar, stub_stash, entries=[_reason()])
    assert _output(binary, raw, stub_stash)["accepted"] == 1
    assert _output(binary, raw, stub_stash)["accepted"] == 0
    with sqlite3.connect(sidecar) as connection:
        assert connection.execute(
            "SELECT a.endpoint, a.external_id, r.subject_type, r.subject_id"
            " FROM external_scene_reason r JOIN external_scene_reason_answer a USING(answer_id)"
        ).fetchall() == [("https://stashdb.org/graphql", "cand-1", "performer", "p1")]


def test_performer_dislike_ops_match(binary: Path, stub_stash: str, sidecar: Path) -> None:
    for args in [
        {"performer_id": "ext-p3", "name": "Performer Three", "disliked": True},
        {"performer_id": "ext-p3", "disliked": False},
        {"performer_id": "", "disliked": True},
    ]:
        raw = payload("update_external_performer_dislike", sidecar, stub_stash, **args)
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)
    raw = payload(
        "update_external_performer_dislike",
        sidecar,
        stub_stash,
        performer_id="ext-p3",
        name="Performer Three",
        disliked=True,
    )
    _output(binary, raw, stub_stash)
    listing = payload("get_external_performer_dislikes", sidecar, stub_stash)
    assert_slice2_identical(binary, PLUGIN_DIR, listing, sidecar, stub_stash)
    items = _output(binary, listing, stub_stash)["items"]
    assert [(item["performer_id"], item["name"]) for item in items] == [
        ("ext-p3", "Performer Three")
    ]
    for bad in (0, 101):
        raw = payload("get_external_performer_dislikes", sidecar, stub_stash, page_size=bad)
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)


def test_disliked_performer_lowers_find_scores(
    binary: Path, stub_stash: str, sidecar: Path
) -> None:
    def scores(raw: bytes) -> dict[str, dict]:
        return {item["id"]: item for item in _output(binary, raw, stub_stash)["items"]}

    expand = payload("get_expand", sidecar, stub_stash, gender="", hide_phash_matches=False)
    hunt = payload("get_performer_hunt", sidecar, stub_stash, performer_id="ext-p3")
    similar = payload(
        "get_external_similar", sidecar, stub_stash, entity_type="scene", entity_id="recent-good"
    )
    # The first Expand query caches its ordering; a dislike must invalidate it.
    before = {name: scores(raw) for name, raw in (("expand", expand), ("hunt", hunt))}
    before_similar = scores(similar)
    with sqlite3.connect(sidecar) as connection:
        connection.execute(
            "INSERT INTO external_performer_dislike VALUES"
            " ('https://stashdb.org/graphql', 'ext-p3', 'Performer Three', 1)"
        )
    for raw in (expand, hunt):
        assert_slice2_identical(binary, PLUGIN_DIR, raw, sidecar, stub_stash)
    assert_slice2_identical(
        binary, PLUGIN_DIR, similar, sidecar, stub_stash, timing_fields=("timings_ms",)
    )
    after = {name: scores(raw) for name, raw in (("expand", expand), ("hunt", hunt))}
    # cand-2's only cast member is ext-p3: a full cast weight at strength 0.5.
    penalty = 0.25 * 0.5 / 0.90
    expand_item = after["expand"]["cand-2"]
    assert expand_item["score"] == pytest.approx(before["expand"]["cand-2"]["score"] - penalty)
    assert expand_item["payload"]["curator_performer_dislike"]["names"] == ["Performer Three"]
    assert after["expand"]["cand-1"]["score"] == before["expand"]["cand-1"]["score"]
    assert "curator_performer_dislike" not in after["expand"]["cand-1"]["payload"]
    assert after["hunt"]
    assert all(item["payload"].get("curator_performer_dislike") for item in after["hunt"].values())
    for scene_id, item in after["hunt"].items():
        assert item["score"] < before["hunt"][scene_id]["score"]
    after_similar = scores(similar)
    with_her = [
        id for id, item in after_similar.items() if item["payload"].get("curator_performer_dislike")
    ]
    for scene_id in with_her:
        assert after_similar[scene_id]["score"] < before_similar[scene_id]["score"]
