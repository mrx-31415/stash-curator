"""End-to-end tests for the Sync recent plays task and its browser trigger.

These exercise the real plugin against live Stash and the sidecar database:

- test_sync_recent_plays_task_imports_a_stash_recorded_play: the task imports a
  play Stash recorded (via sceneAddPlay) into source_play and advances the play
  watermark, without running any other sync pass.
- test_playing_a_scene_schedules_the_automatic_play_sync: visiting a scene page
  finishes a tracker session, and the resident plugin then fires the Sync recent
  plays task on its own.

Each test is self-sufficient: it records a play through Stash's own play API and
runs the play sync, so the scene exists in the sidecar without depending on the
seed-time sync/build having completed. The tests never trigger a model build, so
they do not disturb the no-model state the smoke suite expects. The sidecar lives
in the bind-mounted plugin directory, so the host can read it.

Start with: scripts/verify integration
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from curator.storage import connect_database
from tests.integration.conftest import _gql

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration

CURATOR_TASK = "Sync recent plays"


def _stash_url() -> str:
    return os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")


def _sidecar_path() -> Path:
    config = os.environ.get("STASH_CONFIG", "/tmp/stash-curator-integration")
    return Path(config) / "plugins" / "stash-curator" / "data" / "curator.sqlite3"


def _plugin_operation(operation: str, **args: object) -> dict[str, Any]:
    # runPluginOperation is a mutation, matching the plugin frontend's own usage.
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


def _first_scene_id() -> str:
    data = _gql(
        _stash_url(),
        "query Scenes { findScenes(filter: {page: 1, per_page: 1}) { scenes { id } } }",
    )
    return str(data["findScenes"]["scenes"][0]["id"])


def _wait_curator_idle(timeout: float = 180) -> None:
    """Wait until no Curator job is running (e.g. a seed-time sync/build)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = _plugin_operation("get_job_status")["jobs"]
        if not any(job["state"] == "running" for job in jobs):
            return
        time.sleep(2)
    raise RuntimeError("Curator jobs did not finish within the timeout")


def _wait_sync_plays_job(after_ms: int, timeout: float = 60) -> dict[str, Any]:
    """Wait for a completed sync-plays job started after the given time."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for job in _plugin_operation("get_job_status")["jobs"]:
            if (
                job["job_type"] == "sync-plays"
                and int(job["started_at_ms"]) >= after_ms
                and job["state"] == "complete"
            ):
                return job
        time.sleep(2)
    raise AssertionError("Sync recent plays job did not complete")


def _import_play(scene_id: str) -> dict[str, Any]:
    """Record a play in Stash and import it through the play sync.

    Also populates the scene in source_scene (the play pass upserts full scene
    data), which play_session rows need to satisfy their foreign key.
    """
    played_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _gql(
        _stash_url(),
        (
            "mutation Play($id: ID!, $times: [Timestamp!]) { "
            "sceneAddPlay(id: $id, times: $times) { count } }"
        ),
        {"id": scene_id, "times": [played_at]},
    )
    started_ms = time.time_ns() // 1_000_000
    _run_task(CURATOR_TASK)
    job = _wait_sync_plays_job(started_ms)
    assert int(job["summary"]["changed_play_scenes"]) >= 1
    return job


def _open_sidecar() -> Any:
    return connect_database(_sidecar_path(), readonly=True, attach_artifacts=False)


def test_sync_recent_plays_task_imports_a_stash_recorded_play() -> None:
    """The task imports a Stash-recorded play into source_play and advances the watermark."""
    _wait_curator_idle()
    scene_id = _first_scene_id()
    _import_play(scene_id)

    connection = _open_sidecar()
    try:
        rows = connection.execute(
            "SELECT played_at_ms FROM source_play WHERE scene_id=?", (scene_id,)
        ).fetchall()
        assert rows, "the recorded play was not imported into source_play"
        latest = max(int(row[0]) for row in rows)
        assert abs(time.time_ns() // 1_000_000 - latest) < 5 * 60_000
        watermark = connection.execute(
            "SELECT watermark FROM sync_cursor WHERE entity_type='scene_play'"
        ).fetchone()
        assert watermark and watermark[0], "the play pass did not advance its watermark"
        # Plays-only runs never record a full-snapshot seen set.
        assert connection.execute("SELECT count(*) FROM sync_seen").fetchone()[0] == 0
    finally:
        connection.close()


def test_playing_a_scene_schedules_the_automatic_play_sync(page: Page, base_url: str) -> None:
    """Visiting a scene page and leaving it triggers the play sync on its own."""
    _wait_curator_idle()
    scene_id = _first_scene_id()
    _import_play(scene_id)
    started_ms = time.time_ns() // 1_000_000

    # The resident tracker attaches on the scene page and finishes on navigation away,
    # which flushes the session and schedules the automatic play sync.
    page.goto(f"{base_url}/scenes/{scene_id}", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    job = _wait_sync_plays_job(started_ms)
    assert "changed_play_scenes" in job["summary"], "the completed job was not a plays-only sync"

    connection = _open_sidecar()
    try:
        session = connection.execute(
            """
            SELECT session_id FROM play_session
            WHERE scene_id=? AND provenance='direct_player' AND started_at_ms>=?
            LIMIT 1
            """,
            (scene_id, started_ms),
        ).fetchone()
        assert session, "the tracker session was not ingested into play_session"
    finally:
        connection.close()
