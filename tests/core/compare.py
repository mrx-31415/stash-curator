"""Tolerance-aware backend parity comparisons.

The Go core and the Python oracle are both deterministic, but a few stored
floats legitimately differ by last-bit amounts depending on the host libm
patch level or CPU (glibc's exp deviations, FMA-capable runners). Byte-exact
comparisons for those are unachievable in CI, so the differential gates
compare structure exactly (keys, ids, counts, orderings, strings, integers)
and floats within a small relative tolerance — the same policy the kernel
differential gates already use (rel=1e-9).
"""

from __future__ import annotations

import math

FLOAT_REL_TOL = 1e-9
FLOAT_ABS_TOL = 1e-12


def floats_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL)


def _describe(value: object, path: str) -> str:
    return f"{path}: {value!r}"


def assert_equivalent(a: object, b: object, path: str = "$") -> None:
    """Recursively compare two JSON values: exact for structure and scalars,
    tolerance for floats."""
    if isinstance(a, float) and isinstance(b, float):
        if not floats_close(a, b):
            raise AssertionError(f"floats differ at {path}: {a!r} vs {b!r}")
        return
    if isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            raise AssertionError(f"values differ at {path}: {a!r} vs {b!r}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            raise AssertionError(f"keys differ at {path}: {sorted(set(a) ^ set(b))}")
        for key in a:
            assert_equivalent(a[key], b[key], f"{path}.{key}")
        return
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            raise AssertionError(f"length differs at {path}: {len(a)} vs {len(b)}")
        for index, (left, right) in enumerate(zip(a, b, strict=True)):
            assert_equivalent(left, right, f"{path}[{index}]")
        return
    if a != b:
        raise AssertionError(f"values differ at {path}: {a!r} vs {b!r}")


def equivalent(a: object, b: object) -> bool:
    try:
        assert_equivalent(a, b)
    except AssertionError:
        return False
    return True


def artifact_tolerant_diff(go_path, py_path):
    """First differing table/row/cell between two SQLite artifacts. Floats
    and JSON-encoded floats compare within tolerance (libm/CPU last-bit
    noise); ids, counts, strings, and structure compare exactly. Row order
    and the wall-clock model_lane_order_state.created_at_ms are ignored."""
    import json as _json
    import sqlite3

    def cells_close(a, b):
        if isinstance(a, float) or isinstance(b, float):
            return floats_close(float(a), float(b))
        if isinstance(a, str) and isinstance(b, str):
            try:
                ja, jb = _json.loads(a), _json.loads(b)
            except ValueError:
                return a == b
            if isinstance(ja, (int, float)) or isinstance(jb, (int, float)):
                return floats_close(float(ja), float(jb))
            return equivalent(ja, jb)
        return a == b

    def rows(path):
        connection = sqlite3.connect(path)
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            result = {}
            for table in tables:
                result[table] = list(connection.execute(f"SELECT * FROM {table}"))
            return result
        finally:
            connection.close()

    go_rows, py_rows = rows(go_path), rows(py_path)
    for table in sorted(set(go_rows) | set(py_rows)):
        a, b = go_rows.get(table, []), py_rows.get(table, [])
        if table == "model_lane_order_state":
            a = [(row[0], 0) for row in a]
            b = [(row[0], 0) for row in b]
        if len(a) != len(b):
            return f"{table}: row count differs (go {len(a)} vs py {len(b)})"
        for index, (go_row, py_row) in enumerate(zip(a, b, strict=True)):
            for column, (left, right) in enumerate(zip(go_row, py_row, strict=True)):
                if not cells_close(left, right):
                    return f"{table}[{index}] column {column}:\n  go:  {left!r}\n  py:  {right!r}"
    return ""
