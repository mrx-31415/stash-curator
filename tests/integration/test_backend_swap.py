"""Exec-swap integration tests: ported ops run natively through the installed
zip, unported ops fall back, and both stay byte-identical to the Python
backend on the same sidecar.

These tests require a Stash instance with the plugin installed (the zip built
with the launcher exec line). `scripts/verify integration` handles build,
install, seed, and teardown; the seed leaves a published model in the sidecar,
which the byte-parity assertions read through the real plugin invocation
(runPluginOperation) and compare against a direct backend.py run inside the
container (docker exec) against the same sidecar.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.integration

INTEGRATION_DIR = Path(__file__).resolve().parent


def _stash_url() -> str:
    return os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")


def _scene_id(title: str) -> str:
    data = _gql(
        "query Find($title: String!) { findScenes(scene_filter: {title: {value: $title, "
        "modifier: EQUALS}}) { scenes { id } } }",
        {"title": title},
    )
    scenes = data["findScenes"]["scenes"]
    assert scenes, f"seeded scene {title!r} not found"
    return str(scenes[0]["id"])


def _performer_id(name: str) -> str:
    data = _gql(
        "query Find($name: String!) { findPerformers(performer_filter: {name: {value: $name, "
        "modifier: EQUALS}}) { performers { id } } }",
        {"name": name},
    )
    performers = data["findPerformers"]["performers"]
    assert performers, f"seeded performer {name!r} not found"
    return str(performers[0]["id"])


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


_COMPOSE = str(Path(__file__).parent / "docker-compose.yml")


def _plugin_operation(operation: str, **args: object) -> dict[str, Any]:
    return _gql(
        'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator", args: $args) }',
        {"args": {"operation": operation, **args}},
    )["runPluginOperation"]


def _stash_port() -> int:
    url = os.environ.get("STASH_URL", "http://localhost:9999")
    return int(url.rsplit(":", 1)[1])


def _installed_plugin_dir() -> Path:
    """The installed plugin folder on the host (bind-mounted into the
    container at /root/.stash/plugins/stash-curator)."""
    config = os.environ.get("STASH_CONFIG", "/tmp/stash-curator-integration")
    return Path(config) / "plugins" / "stash-curator"


def _container_id() -> str:
    """The running stash container (the integration suite's docker compose)."""
    out = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(INTEGRATION_DIR / "docker-compose.yml"),
            "ps",
            "-q",
            "stash",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out, "no running stash container; run scripts/verify integration"
    return out


def _direct_backend(operation: str, **args: object) -> dict[str, object]:
    """Run backend.py inside the container against the same sidecar the plugin
    uses, with the same args the plugin call received.

    Running inside the container (via docker exec) is required for parity:
    the model build creates the artifact directory as root:700, which the
    host user cannot read, and the plugin's server_connection points at the
    host-published port, which is unreachable from inside the container (the
    settings fetch then degrades to empty settings exactly like the plugin's
    own fetch). Both sides therefore observe the same files and the same
    empty settings."""
    stash_url = _stash_url().rsplit(":", 1)
    port = int(stash_url[1]) if len(stash_url) == 2 else 9999
    plugin_dir = "/root/.stash/plugins/stash-curator"
    payload = {
        "server_connection": {"Host": "localhost", "Port": port, "Scheme": "http"},
        "args": {
            "operation": operation,
            "database_path": plugin_dir + "/data/curator.sqlite3",
            **args,
        },
    }
    completed = subprocess.run(
        ["docker", "exec", "-i", _container_id(), "python", plugin_dir + "/backend.py", plugin_dir],
        input=json.dumps(payload, separators=(",", ":")).encode(),
        capture_output=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return cast(dict[str, object], json.loads(completed.stdout)["output"])


def _strip_key(value: object, key: str) -> None:
    if isinstance(value, dict):
        value.pop(key, None)
        for item in value.values():
            _strip_key(item, key)
    elif isinstance(value, list):
        for item in value:
            _strip_key(item, key)


def _assert_plugin_matches_direct(
    operation: str,
    args: dict[str, object],
    *,
    timing_fields: tuple[str, ...],
    normalize: tuple[str, ...] = (),
) -> None:
    plugin = _plugin_operation(operation, **args)
    direct = _direct_backend(operation, **args)
    for field in timing_fields:
        assert isinstance(plugin[field], (dict, int)) and isinstance(direct[field], (dict, int))
        if isinstance(plugin[field], dict):
            assert set(plugin[field]) == set(direct[field])
            for value in (*plugin[field].values(), *direct[field].values()):
                assert isinstance(value, int) and value >= 0
        else:
            assert plugin[field] >= 0 and direct[field] >= 0
        plugin.pop(field)
        direct.pop(field)
    for field in normalize:
        _strip_key(plugin, field)
        _strip_key(direct, field)
    # Stash re-marshals plugin stdout through a Go struct, which re-sorts JSON
    # keys, so through the plugin interface the comparison is value equality.
    # Byte-level key order is already covered by the stdout differential
    # harness (tests/core) where the raw output is compared directly.
    assert plugin == direct, (
        f"plugin output for {operation} differs from the direct backend:\n"
        f"plugin: {json.dumps(plugin, separators=(',', ':'))}\n"
        f"direct: {json.dumps(direct, separators=(',', ':'))}"
    )


PORTED_OPS: list[tuple[str, dict[str, object], tuple[str, ...], tuple[str, ...]]] = [
    (
        "get_slate",
        {"lane": "for_you", "count": 5, "page": 1, "impression_id": "swap-slate"},
        ("timings_ms", "ranking_timings_ms"),
        (),
    ),
    (
        "replace_item",
        {"lane": "for_you", "exclude_scene_ids": []},
        ("timings_ms", "ranking_timings_ms"),
        ("impression_id",),
    ),
    ("get_recommendation_history", {"page": 1, "page_size": 10}, (), ()),
    ("get_shortlist", {"page": 1, "page_size": 10}, (), ()),
    ("get_feedback_history", {"page": 1, "page_size": 10}, (), ()),
    ("get_taste_profile", {}, (), ()),
    ("get_diagnostics", {}, ("generated_at_ms",), ()),
]


@pytest.mark.parametrize(
    "operation,args,timing_fields,normalize",
    PORTED_OPS,
    ids=[case[0] for case in PORTED_OPS],
)
def test_ported_op_byte_identical_through_plugin(
    seeded: None,
    operation: str,
    args: dict[str, object],
    timing_fields: tuple[str, ...],
    normalize: tuple[str, ...],
) -> None:
    """Every ported op served through the installed zip (launcher -> binary)
    matches the direct Python backend byte for byte on the same sidecar."""
    _assert_plugin_matches_direct(operation, args, timing_fields=timing_fields, normalize=normalize)


def _entity_ops() -> list[tuple[str, dict[str, object], tuple[str, ...], tuple[str, ...]]]:
    """The similar/explanation cases need real seeded entity ids."""
    scene_id = _scene_id("Test Scene Outdoor Fun")
    performer_id = _performer_id("Test Performer One")
    return [
        (
            "get_similar",
            {
                "entity_type": "scene",
                "entity_id": scene_id,
                "count": 5,
                "page": 1,
                "impression_id": "swap-similar",
            },
            ("timings_ms",),
            (),
        ),
        (
            "get_similar",
            {"entity_type": "performer", "entity_id": performer_id, "count": 5, "page": 1},
            ("timings_ms",),
            (),
        ),
        ("get_explanation", {"scene_id": scene_id}, (), ()),
    ]


def test_entity_ops_byte_identical_through_plugin(seeded: None) -> None:
    for operation, args, timing_fields, normalize in _entity_ops():
        _assert_plugin_matches_direct(
            operation, args, timing_fields=timing_fields, normalize=normalize
        )


def test_unported_op_falls_back_byte_identical(seeded: None) -> None:
    """An unported op still works through the same zip via the Python
    fallback, byte-identical to the direct backend."""
    _assert_plugin_matches_direct("get_pruning_queue", {}, timing_fields=())


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
