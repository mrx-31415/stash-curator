"""End-to-end tests for Stash entity hooks: enqueue-then-drain syncs.

Stash runs plugin hooks inline after every scene/performer/studio/tag
create, update, and destroy. The Curator hook handler only records the change
in the sidecar; the preference-rebuild task drains the queue (fetching each
changed entity by id, or removing it on destroy) before rebuilding, so the
model always sees fresh source data and bulk edits pay no inline fetch cost.

The sidecar lives in the bind-mounted plugin directory, so the host can read it.

Start with: scripts/verify integration
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Any

import pytest

from curator.storage import connect_database
from tests.integration.conftest import _gql

pytestmark = pytest.mark.integration

REBUILD_TASK = "Apply recent Curator feedback"


def _stash_url() -> str:
    return os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")


def _sidecar_path() -> Path:
    config = os.environ.get("STASH_CONFIG", "/tmp/stash-curator-integration")
    return Path(config) / "plugins" / "stash-curator" / "data" / "curator.sqlite3"


def _open_sidecar() -> Any:
    return connect_database(_sidecar_path(), readonly=True, attach_artifacts=False)


def _plugin_operation(operation: str, **args: object) -> dict[str, Any]:
    return _gql(
        _stash_url(),
        'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator", args: $args) }',
        {"args": {"operation": operation, **args}},
    )["runPluginOperation"]


def _run_task(name: str) -> str:
    return str(
        _gql(
            _stash_url(),
            (
                "mutation Task($task: String!, $args: Map!) { "
                'runPluginTask(plugin_id: "stash-curator", task_name: $task, args_map: $args) }'
            ),
            {"task": name, "args": {}},
        )["runPluginTask"]
    )


def _wait_curator_idle(timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = _plugin_operation("get_job_status")["jobs"]
        if not any(job["state"] == "running" for job in jobs):
            return
        time.sleep(2)
    raise RuntimeError("Curator jobs did not finish within the timeout")


def _wait_job(job_type: str, after_ms: int, timeout: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for job in _plugin_operation("get_job_status")["jobs"]:
            if (
                job["job_type"] == job_type
                and int(job["started_at_ms"]) >= after_ms
                and job["state"] == "complete"
            ):
                return job
        time.sleep(2)
    raise AssertionError(f"{job_type} job did not complete")


def _run_rebuild() -> None:
    """Run the preference rebuild, which drains the entity-change queue first."""
    started_ms = time.time_ns() // 1_000_000
    _run_task(REBUILD_TASK)
    _wait_job("update-model", started_ms)


def test_scene_changes_reach_the_sidecar_through_the_rebuild_drain() -> None:
    """Create, update, and destroy each enqueue a change that the rebuild applies."""
    _wait_curator_idle()
    stash = _stash_url()

    created = _gql(
        stash,
        ("mutation Create($input: SceneCreateInput!) { sceneCreate(input: $input) { id title } }"),
        {"input": {"title": "Hook Test Scene", "details": "created by hook test"}},
    )
    scene_id = str(created["sceneCreate"]["id"])
    try:
        _run_rebuild()
        connection = _open_sidecar()
        try:
            title = connection.execute(
                "SELECT title FROM source_scene WHERE scene_id=?", (scene_id,)
            ).fetchone()
            assert title and title[0] == "Hook Test Scene"
        finally:
            connection.close()

        _gql(
            stash,
            ("mutation Update($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }"),
            {"input": {"id": scene_id, "title": "Hook Test Scene Renamed"}},
        )
        _run_rebuild()
        connection = _open_sidecar()
        try:
            title = connection.execute(
                "SELECT title FROM source_scene WHERE scene_id=?", (scene_id,)
            ).fetchone()
            assert title and title[0] == "Hook Test Scene Renamed"
        finally:
            connection.close()

        _gql(
            stash,
            "mutation Destroy($input: SceneDestroyInput!) { sceneDestroy(input: $input) }",
            {"input": {"id": scene_id}},
        )
        _run_rebuild()
        connection = _open_sidecar()
        try:
            assert (
                connection.execute(
                    "SELECT count(*) FROM source_scene WHERE scene_id=?", (scene_id,)
                ).fetchone()[0]
                == 0
            )
        finally:
            connection.close()
    finally:
        # Keep Stash's own database tidy across runs (only the sidecar is reset each run).
        with contextlib.suppress(Exception):
            _gql(
                stash,
                "mutation Destroy($input: SceneDestroyInput!) { sceneDestroy(input: $input) }",
                {"input": {"id": scene_id}},
            )


def test_tag_hook_enqueues_and_links_through_the_rebuild_drain() -> None:
    """A tag created and attached to a scene reaches the sidecar via the drain."""
    _wait_curator_idle()
    stash = _stash_url()

    # Stash's own database persists across integration runs, so find-or-create.
    existing = _gql(
        stash,
        (
            "query Find($name: String!) { "
            "findTags(tag_filter: {name: {value: $name, modifier: EQUALS}}) { tags { id } } }"
        ),
        {"name": "Hook Test Tag"},
    )["findTags"]["tags"]
    if existing:
        tag_id = str(existing[0]["id"])
    else:
        created = _gql(
            stash,
            "mutation Create($input: TagCreateInput!) { tagCreate(input: $input) { id } }",
            {"input": {"name": "Hook Test Tag"}},
        )
        tag_id = str(created["tagCreate"]["id"])

    scenes = _gql(
        stash,
        "query Scenes { findScenes(filter: {page: 1, per_page: 1}) { scenes { id } } }",
    )
    scene_id = str(scenes["findScenes"]["scenes"][0]["id"])
    _gql(
        stash,
        ("mutation Tag($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }"),
        {"input": {"id": scene_id, "tag_ids": [tag_id]}},
    )
    _run_rebuild()

    connection = _open_sidecar()
    try:
        row = connection.execute("SELECT name FROM source_tag WHERE tag_id=?", (tag_id,)).fetchone()
        assert row and row[0] == "Hook Test Tag"
        assert (
            connection.execute(
                "SELECT count(*) FROM scene_tag WHERE scene_id=? AND tag_id=?", (scene_id, tag_id)
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()
