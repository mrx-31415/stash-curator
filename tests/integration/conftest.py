"""Fixtures for Curator browser integration tests.

Lifecycle:
  1. scripts/verify integration     (handles build, start, seed, test, teardown)
  2. pytest --base-url http://localhost:9999 tests/integration/

The `base_url` fixture is provided by pytest-playwright.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = INTEGRATION_DIR.parents[1]


def _gql(stash_url: str, query: str, variables: dict[str, object] | None = None) -> dict[str, Any]:
    """Helper: make a GraphQL request to Stash."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"{stash_url}/graphql",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Stash returned {exc.code}: {body[:500]}") from exc
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return cast(dict[str, Any], data["data"])


def _wait_for_stash(url: str, timeout: float = 120) -> None:
    """Poll until Stash serves HTTP 200."""
    deadline = time.monotonic() + timeout
    last: str = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last = str(exc)
            time.sleep(2)
    raise RuntimeError(f"Stash not ready at {url} after {timeout}s: {last}")


@pytest.fixture(scope="session")
def seeded() -> None:
    """Seed Stash with test data. Uses STASH_URL or defaults to localhost:9999."""
    stash_url = os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")
    _wait_for_stash(stash_url)

    try:
        data = _gql(
            stash_url,
            (
                "query Find($n: String!) { "
                "findTags(tag_filter: {name: {value: $n, modifier: EQUALS}}) "
                "{ count } }"
            ),
            {"n": "Blowjob"},
        )
        if data["findTags"]["count"] > 0 and os.environ.get("FORCE_SEED") != "1":
            return
    except Exception:
        pass

    subprocess.run(
        [sys.executable, str(INTEGRATION_DIR / "seed.py"), "--stash-url", stash_url],
        check=True,
        cwd=PROJECT_ROOT,
    )
