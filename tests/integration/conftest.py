"""Fixtures for Curator browser integration tests.

Lifecycle:
  1. docker compose -f tests/integration/docker-compose.yml up -d
  2. python tests/integration/seed.py --stash-url http://localhost:9999
  3. pytest tests/integration/ --stash-url http://localhost:9999

The plugin must be pre-installed into the Stash config volume before start:
  scripts/build_plugin.py
  unzip -oq dist/stash-curator.zip -d <stash-config>/plugins/stash-curator/
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


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--stash-url",
        default=os.environ.get("STASH_URL", "http://localhost:9999"),
        help="Stash base URL for integration tests",
    )


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


# ── session-scoped fixtures ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def stash_url(request: pytest.FixtureRequest) -> str:
    url: str = request.config.getoption("--stash-url").rstrip("/")
    _wait_for_stash(url)
    return url


@pytest.fixture(scope="session")
def seeded(stash_url: str) -> str:
    """Ensure Stash has seed data. Idempotent — skips if already present."""
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
            print("[conftest] seed data already present, skipping")
            return stash_url
    except Exception:
        pass

    print("[conftest] seeding Stash …")
    subprocess.run(
        [sys.executable, str(INTEGRATION_DIR / "seed.py"), "--stash-url", stash_url],
        check=True,
        cwd=PROJECT_ROOT,
    )
    return stash_url
