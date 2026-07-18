from __future__ import annotations

import importlib.util
import json
import re
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
    } <= names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    index = (tmp_path / "index.yml").read_text(encoding="utf-8")
    assert "id: stash-curator" in index
    assert "sha256:" in index
    assert re.search(r"date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", index)

    installed = tmp_path / "installed"
    assert _run(installed / "backend.py", installed)["round_trips"] == 1
    task = subprocess.run(
        [sys.executable, str(installed / "backend.py"), str(installed), "backup"],
        input=json.dumps(_payload(installed)),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(task.stdout)["output"]["backup"].endswith(".sqlite3.backup")
    assert "Stash Curator backup completed" in task.stderr


def test_backend_module_loads_without_starting(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_backend", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA_VERSION == 1
