from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import curator.profiling as profiling
from curator.graphql import GraphQLClient
from curator.profiling import (
    begin_trace,
    clear_traces,
    end_trace,
    get_trace,
    list_traces,
    save_trace,
)
from curator.storage import MigrationRunner, connect_database


def _database(path: Path) -> None:
    connection = connect_database(path)
    try:
        MigrationRunner(connection).migrate(applied_at_ms=1)
    finally:
        connection.close()


def test_trace_records_redacted_sql_graphql_and_standard_export(tmp_path: Path) -> None:
    path = tmp_path / "curator.sqlite3"
    _database(path)
    trace, token = begin_trace("get_similar", "operation")
    connection = connect_database(path)
    try:
        assert (
            connection.execute("SELECT ? AS value", ("private-id",)).fetchone()[0] == "private-id"
        )
        client = GraphQLClient(
            "https://stashdb.org/graphql",
            profile_category="stashdb",
            transport=lambda *_args: json.dumps({"data": {"ping": True}}).encode(),
        )
        assert client.execute("query CuratorProfilePing { ping }")["ping"] is True
    finally:
        connection.close()
        end_trace(trace, token)
    save_trace(path, trace)

    reader = connect_database(path)
    try:
        summary = list_traces(reader)[0]
        stored = get_trace(reader, str(summary["trace_id"]))
    finally:
        reader.close()

    assert summary["operation"] == "get_similar"
    assert summary["status"] == "ok"
    payload = stored["trace"]
    assert isinstance(payload, dict)
    assert payload["displayTimeUnit"] == "ms"
    events = payload["traceEvents"]
    assert events[0]["ph"] == "X"
    assert {event["cat"] for event in events} >= {"plugin", "sqlite", "stashdb"}
    serialized = json.dumps(events)
    assert "private-id" not in serialized
    assert "CuratorProfilePing" in serialized


def test_failed_traces_are_bounded_truncated_and_clearable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "curator.sqlite3"
    _database(path)
    monkeypatch.setattr(profiling, "MAX_EVENTS", 4)
    monkeypatch.setattr(profiling, "MAX_TRACES", 2)

    for index in range(3):
        trace, token = begin_trace(f"operation-{index}", "operation")
        for event in range(5):
            trace.record("python", f"stage-{event}", time.perf_counter_ns(), 1_000)
        error = RuntimeError("private failure value") if index == 2 else None
        end_trace(trace, token, error)
        save_trace(path, trace)

    connection = connect_database(path)
    try:
        items = list_traces(connection, 2)
        assert len(items) == 2
        assert all(item["truncated"] == 1 for item in items)
        failed = next(item for item in items if item["status"] == "error")
        detail = get_trace(connection, str(failed["trace_id"]))
        assert "private failure value" not in json.dumps(detail)
        assert "RuntimeError" in json.dumps(detail)
        assert clear_traces(connection) == 2
        assert list_traces(connection, 2) == []
    finally:
        connection.close()


def test_profile_limit_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "curator.sqlite3"
    _database(path)
    connection = connect_database(path)
    try:
        with pytest.raises(ValueError, match="limit"):
            list_traces(connection, 201)
        with pytest.raises(ValueError, match="unknown"):
            get_trace(connection, "missing")
    finally:
        connection.close()


def test_truncated_trace_keeps_high_level_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiling, "MAX_EVENTS", 5)
    trace, token = begin_trace("update-model", "task")
    try:
        for index in range(4):
            trace.record("sqlite", f"query-{index}", time.perf_counter_ns(), 1_000)
        trace.record("python", "model.scores", time.perf_counter_ns(), 1_000)
    finally:
        end_trace(trace, token)

    assert "model.scores" in {event["name"] for event in trace.events}
    assert trace.dropped_events == 2
