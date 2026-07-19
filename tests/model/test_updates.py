from pathlib import Path

import pytest

from curator.model import ModelBuildResult, ModelUpdateCoordinator, PreferenceModelBuilder
from curator.storage import MigrationRunner, connect_database


def test_coordinator_debounces_and_rebuilds_once_more_for_an_action_during_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    now = [0]
    coordinator = ModelUpdateCoordinator(connection, clock_ms=lambda: now[0])
    coordinator.request("feedback")
    assert coordinator.drain() == ()
    now[0] += 2_000
    calls = 0

    def build(_builder: PreferenceModelBuilder) -> ModelBuildResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            coordinator.request("session_outcome")
        return ModelBuildResult("model", "features", 1, 1, False, {"total": 1})

    monkeypatch.setattr(PreferenceModelBuilder, "build", build)
    results = coordinator.drain(force=True)

    assert len(results) == 2
    assert coordinator.status().pending is False
    assert coordinator.status().requested_generation == 2


def test_failed_update_remains_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    coordinator = ModelUpdateCoordinator(connection, clock_ms=lambda: 1_000)
    coordinator.request("feedback")

    def fail(_builder: PreferenceModelBuilder) -> ModelBuildResult:
        raise RuntimeError("build failed")

    monkeypatch.setattr(PreferenceModelBuilder, "build", fail)
    with pytest.raises(RuntimeError, match="build failed"):
        coordinator.drain(force=True)

    assert coordinator.status().pending is True
    assert coordinator.status().last_error == "build failed"


def test_coordinator_does_not_duplicate_an_active_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    coordinator = ModelUpdateCoordinator(connection, clock_ms=lambda: 2_000)
    coordinator.request("feedback")
    connection.execute(
        "UPDATE model_update_state SET last_started_at_ms=1500, last_finished_at_ms=1000"
    )
    monkeypatch.setattr(
        PreferenceModelBuilder,
        "build",
        lambda *_args: (_ for _ in ()).throw(AssertionError("duplicate build")),
    )

    assert coordinator.drain(force=True) == ()
    assert coordinator.status().pending is True


def test_update_readiness_batches_events_and_limits_rebuild_frequency(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    now = [1_000]
    coordinator = ModelUpdateCoordinator(connection, clock_ms=lambda: now[0])

    coordinator.request("session_outcome")
    first_requested_at = coordinator.status().requested_at_ms
    for _ in range(4):
        now[0] += 1_000
        coordinator.request("session_outcome")

    status = coordinator.status()
    assert status.requested_at_ms == first_requested_at
    assert status.pending_count == 5
    assert status.ready(now[0], event_threshold=5, max_wait_ms=30_000, min_interval_ms=60_000)

    connection.execute(
        "UPDATE model_update_state SET last_finished_at_ms=? WHERE singleton=1", (now[0],)
    )
    assert not coordinator.status().ready(
        now[0], event_threshold=5, max_wait_ms=30_000, min_interval_ms=60_000
    )
