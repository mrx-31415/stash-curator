from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

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
    root = Path(__file__).parents[2]
    archive = build(tmp_path / "stash-curator.zip")
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        package.extractall(tmp_path / "installed")
    expected = {"LICENSE"}
    for directory in ("plugin", "curator"):
        source = root / directory
        for path in source.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                relative = path.relative_to(source)
                if directory != "plugin" or "data" not in relative.parts:
                    expected.add(
                        (Path("curator") / relative).as_posix()
                        if directory == "curator"
                        else relative.as_posix()
                    )
    assert names == expected
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


def test_curator_tabs_update_browser_history() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "const routeLocation = useLocation();" in source
    assert "history.push({ pathname: routeLocation.pathname, search: route.toString() });" in source
    assert "onClick: () => openView(option.value)" in source


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


def test_backend_profiles_only_when_enabled_and_exposes_profile_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_profiling", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "curator.sqlite3"
    payload = {"args": {"database_path": str(database)}}

    def work(settings):
        connection = module._open(payload, settings)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return {"done": True}

    monkeypatch.setattr(module, "_settings", lambda _payload: {"profilingEnabled": True})
    assert module._profiled(payload, "test-work", "operation", work) == {"done": True}
    listed = module._api(payload, "list_profiles", {"profilingEnabled": True})
    assert listed["enabled"] is True
    assert listed["items"][0]["operation"] == "test-work"

    monkeypatch.setattr(module, "_settings", lambda _payload: {"profilingEnabled": False})
    module._profiled(payload, "disabled-work", "operation", work)
    listed = module._api(payload, "list_profiles", {"profilingEnabled": False})
    assert listed["enabled"] is False
    assert [item["operation"] for item in listed["items"]] == ["test-work"]

    with pytest.raises(ValueError, match="confirmation"):
        module._api(payload, "clear_profiles", {"profilingEnabled": False})
    payload["args"] = {"database_path": str(database), "confirmation": "CLEAR"}
    assert module._api(payload, "clear_profiles", {"profilingEnabled": False})["deleted"] == 1
