"""Installed-plugin integration tests: the shipped zip serves the raw-plugin
interface through the launcher -> per-arch binary exec chain.

The byte-level parity of the binary against the Python reference backend is
covered by the repo-level differential harness (`tests/core/test_backend*.py`),
which compares both subprocesses directly; this suite verifies the installed
artifact end to end: the launcher exec line, the per-arch binary, real
model-backed output, and clean failure paths such as an unconfigured StashDB
box.

These tests require a Stash instance with the plugin installed (the zip built
with the launcher exec line). `scripts/verify integration` handles build,
install, seed, and teardown; the seed leaves a published model in the sidecar.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.integration


def _stash_url() -> str:
    return os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")


def _gql(query: str, variables: dict[str, object] | None = None) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"{_stash_url()}/graphql",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Stash returned {exc.code}: {body[:500]}") from exc
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return cast(dict[str, Any], data["data"])


def _plugin_operation(operation: str, **args: object) -> dict[str, Any]:
    return _gql(
        'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator", args: $args) }',
        {"args": {"operation": operation, **args}},
    )["runPluginOperation"]


def _plugin_operation_raw(operation: str, **args: object) -> dict[str, Any]:
    """Invoke the plugin without raising on GraphQL errors, so failing ops
    can be asserted on their error payload."""
    payload = json.dumps(
        {
            "query": (
                'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator",'
                " args: $args) }"
            ),
            "variables": {"args": {"operation": operation, **args}},
        }
    ).encode()
    req = urllib.request.Request(
        f"{_stash_url()}/graphql",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return cast(dict[str, Any], json.loads(resp.read()))
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.read().decode(errors="replace")[:500]}


def _installed_plugin_dir() -> Path:
    """The installed plugin folder on the host (bind-mounted into the
    container at /root/.stash/plugins/stash-curator)."""
    config = os.environ.get("STASH_CONFIG", "/tmp/stash-curator-integration")
    return Path(config) / "plugins" / "stash-curator"


def test_network_op_stashdb_unconfigured_error(seeded: None) -> None:
    """The docker env has no StashDB box, so the network ops fail through the
    installed binary with the unconfigured-StashDB error instead of hanging
    or crashing."""
    plugin = _plugin_operation_raw("get_performer_hunt", performer_id="missing-performer")
    plugin_text = json.dumps(plugin, separators=(",", ":"))
    assert "configure StashDB with an API key in Stash settings" in plugin_text


def test_installed_plugin_serves_through_the_binary(seeded: None) -> None:
    """The installed zip carries the launcher exec line and a binary for this
    platform, and the ported ops produce real model-backed output."""
    plugin_dir = _installed_plugin_dir()
    manifest = (plugin_dir / "stash-curator.yml").read_text(encoding="utf-8")
    assert '"{pluginDir}/launcher.py"' in manifest
    from curator.core import _platform_binary_name

    binary = plugin_dir / _platform_binary_name()
    assert binary.is_file() and binary.stat().st_size > 1_000_000
    diagnostics = _plugin_operation("get_diagnostics")
    assert diagnostics["readiness"]["recommendation_model"] is True
    assert diagnostics["migration"]["pending_count"] == 0
    model_id = diagnostics["generations"]["model"]["model_id"]
    assert model_id
    slate = _plugin_operation(
        "get_slate", lane="for_you", count=5, page=1, impression_id="swap-sanity"
    )
    assert slate["model_id"] == model_id
    assert slate["impression_id"] == "swap-sanity"
    assert isinstance(slate["items"], list) and slate["total"] >= 0
