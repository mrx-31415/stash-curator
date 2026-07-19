from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.build_plugin import build


def _payload(plugin_dir: Path) -> dict[str, object]:
    return {
        "server_connection": {
            "Scheme": "http",
            "Host": "127.0.0.1",
            "Port": 1,
            "PluginDir": str(plugin_dir),
        },
        "args": {"operation": "round_trip"},
    }


def _run(backend: Path, plugin_dir: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(backend), str(plugin_dir)],
        input=json.dumps(_payload(plugin_dir)),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["output"]


def test_plugin_round_trip_survives_process_restart(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    assert _run(backend, tmp_path)["round_trips"] == 1
    assert _run(backend, tmp_path)["round_trips"] == 2


def test_plugin_archive_contains_runtime_and_core(tmp_path: Path) -> None:
    archive = build(tmp_path / "stash-curator.zip")
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        package.extractall(tmp_path / "installed")
    assert {
        "LICENSE",
        "stash-curator.yml",
        "stash-curator.js",
        "stash-curator.css",
        "backend.py",
        "curator/__init__.py",
        "curator/storage/sql/0006_plugin_product.sql",
        "curator/storage/sql/0007_qualified_impressions.sql",
        "curator/storage/sql/0008_lane_candidate_cache.sql",
    } <= names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    index = (tmp_path / "index.yml").read_text(encoding="utf-8")
    assert (tmp_path / "index.html").is_file()
    assert "id: stash-curator" in index
    assert "sha256:" in index
    assert re.search(r"date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", index)
    installed = tmp_path / "installed"
    assert "Apply recent Curator feedback" in (installed / "stash-curator.yml").read_text()
    assert "Prepare recommendation pages" in (installed / "stash-curator.yml").read_text()
    assert _run(installed / "backend.py", installed)["round_trips"] == 1
    with sqlite3.connect(installed / "data" / "curator.sqlite3") as connection:
        connection.execute(
            "UPDATE model_update_state SET last_started_at_ms=2, "
            "last_finished_at_ms=1, last_error=NULL"
        )
    task = subprocess.run(
        [sys.executable, str(installed / "backend.py"), str(installed), "backup"],
        input=json.dumps(_payload(installed)),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(task.stdout)["output"]["backup"].endswith(".sqlite3.backup")
    assert "Stash Curator backup completed" in task.stderr
    assert "\x01p\x021.0000" in task.stderr
    with sqlite3.connect(installed / "data" / "curator.sqlite3") as connection:
        assert connection.execute("SELECT last_error FROM model_update_state").fetchone()[0]


def test_backend_module_loads_without_starting(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_backend", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA_VERSION == 1


def test_plugin_settings_are_applied_to_sidecar_config(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_settings", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = module._open(
        {"args": {}},
        {
            "databasePath": str(tmp_path / "curator.sqlite3"),
            "pageSize": 12,
            "modelUpdateEventThreshold": 7,
        },
    )
    try:
        config = json.loads(
            connection.execute(
                "SELECT config_json FROM curator_config WHERE singleton=1"
            ).fetchone()[0]
        )
        assert config["page_size"] == 12
        assert config["model_update_event_threshold"] == 7
    finally:
        connection.close()
