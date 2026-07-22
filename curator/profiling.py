"""Dependency-free structured profiling for plugin operations."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

# ponytail: fixed caps keep profiling bounded; make configurable only if real traces need it.
MAX_EVENTS = 10_000
MAX_TRACES = 200

_current_trace: ContextVar[Trace | None] = ContextVar("curator_trace", default=None)


@dataclass
class Trace:
    name: str
    kind: str
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    started_at_ns: int = field(default_factory=time.time_ns)
    started_ns: int = field(default_factory=time.perf_counter_ns)
    events: list[dict[str, object]] = field(default_factory=list)
    dropped_events: int = 0
    status: str = "ok"
    error_type: str | None = None
    duration_us: int = 0
    _threads: dict[int, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _thread_id(self) -> int:
        native = threading.get_ident()
        if native not in self._threads:
            self._threads[native] = len(self._threads)
        return self._threads[native]

    def record(
        self,
        category: str,
        name: str,
        started_ns: int,
        duration_ns: int,
        details: Mapping[str, object] | None = None,
    ) -> None:
        with self._lock:
            if len(self.events) >= MAX_EVENTS - 2:
                self.dropped_events += 1
                if category == "sqlite":
                    return
                try:
                    index = next(
                        i for i, event in enumerate(self.events) if event["cat"] == "sqlite"
                    )
                    del self.events[index]
                except StopIteration:
                    return
            event: dict[str, object] = {
                "name": name,
                "cat": category,
                "ph": "X",
                "ts": (self.started_at_ns + started_ns - self.started_ns) // 1_000,
                "dur": max(0, duration_ns // 1_000),
                "pid": 1,
                "tid": self._thread_id(),
            }
            if details:
                event["args"] = dict(details)
            self.events.append(event)

    def finish(self, error: BaseException | None = None) -> None:
        self.duration_us = max(0, (time.perf_counter_ns() - self.started_ns) // 1_000)
        if error is not None:
            self.status = "error"
            self.error_type = type(error).__name__

    def payload(self) -> dict[str, object]:
        root_args: dict[str, object] = {"status": self.status, "kind": self.kind}
        if self.error_type:
            root_args["error_type"] = self.error_type
        events: list[dict[str, object]] = [
            {
                "name": self.name,
                "cat": "plugin",
                "ph": "X",
                "ts": self.started_at_ns // 1_000,
                "dur": self.duration_us,
                "pid": 1,
                "tid": 0,
                "args": root_args,
            },
            *self.events,
        ]
        if self.dropped_events:
            events.append(
                {
                    "name": "trace truncated",
                    "cat": "plugin",
                    "ph": "i",
                    "s": "t",
                    "ts": self.started_at_ns // 1_000 + self.duration_us,
                    "pid": 1,
                    "tid": 0,
                    "args": {"dropped_events": self.dropped_events},
                }
            )
        return {"traceEvents": events, "displayTimeUnit": "ms"}


def current_trace() -> Trace | None:
    return _current_trace.get()


def record_duration(category: str, name: str, duration_ms: int) -> None:
    trace = current_trace()
    if trace is None:
        return
    ended_ns = time.perf_counter_ns()
    started_ns = max(trace.started_ns, ended_ns - max(0, duration_ms) * 1_000_000)
    trace.record(category, name, started_ns, ended_ns - started_ns)


def begin_trace(name: str, kind: str) -> tuple[Trace, Token[Trace | None]]:
    trace = Trace(name[:100], kind)
    return trace, _current_trace.set(trace)


def end_trace(trace: Trace, token: Token[Trace | None], error: BaseException | None = None) -> None:
    trace.finish(error)
    _current_trace.reset(token)


@contextmanager
def span(category: str, name: str, details: Mapping[str, object] | None = None) -> Iterator[None]:
    trace = current_trace()
    if trace is None:
        yield
        return
    started = time.perf_counter_ns()
    try:
        yield
    finally:
        trace.record(category, name, started, time.perf_counter_ns() - started, details)


def save_trace(database: Path, trace: Trace) -> None:
    connection = sqlite3.connect(database, isolation_level=None, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO profile_trace(
                trace_id, kind, operation, started_at_ms, duration_us, status,
                span_count, truncated, trace_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.trace_id,
                trace.kind,
                trace.name,
                trace.started_at_ns // 1_000_000,
                trace.duration_us,
                trace.status,
                len(trace.events),
                int(trace.dropped_events > 0),
                json.dumps(trace.payload(), separators=(",", ":")),
            ),
        )
        connection.execute(
            """
            DELETE FROM profile_trace WHERE trace_id IN (
                SELECT trace_id FROM profile_trace
                ORDER BY started_at_ms DESC, rowid DESC LIMIT -1 OFFSET ?
            )
            """,
            (MAX_TRACES,),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_traces(connection: sqlite3.Connection, limit: int = 50) -> list[dict[str, object]]:
    if not 1 <= limit <= MAX_TRACES:
        raise ValueError(f"limit must be between 1 and {MAX_TRACES}")
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT trace_id, kind, operation, started_at_ms, duration_us, status,
                   span_count, truncated
            FROM profile_trace ORDER BY started_at_ms DESC, rowid DESC LIMIT ?
            """,
            (limit,),
        )
    ]


def get_trace(connection: sqlite3.Connection, trace_id: str) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT trace_id, kind, operation, started_at_ms, duration_us, status,
               span_count, truncated, trace_json
        FROM profile_trace WHERE trace_id=?
        """,
        (trace_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown profile trace: {trace_id}")
    result = dict(row)
    result["trace"] = json.loads(str(result.pop("trace_json")))
    return result


def clear_traces(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM profile_trace")
    return cursor.rowcount
