from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
import tomllib
import zipfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

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
    assert "id: stash-curator" in index
    assert f"sha256: {sha256(archive.read_bytes()).hexdigest()}" in index
    assert re.search(r"date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", index)
    installed = tmp_path / "installed"
    plugin_manifest = (installed / "stash-curator.yml").read_text(encoding="utf-8")
    with (root / "pyproject.toml").open("rb") as source:
        project_version = tomllib.load(source)["project"]["version"]
    assert f"version: {project_version}" in plugin_manifest
    assert "Apply recent Curator feedback" in plugin_manifest
    assert "Prepare recommendation pages" in (installed / "stash-curator.yml").read_text()
    assert "Compact legacy Curator data" in (installed / "stash-curator.yml").read_text()
    assert "Vacuum compacted Curator data" in (installed / "stash-curator.yml").read_text()
    assert "Install optional dependencies" in (installed / "stash-curator.yml").read_text()
    assert "numpy==2.5.1" in (installed / "packages" / "curator-tools.txt").read_text()
    javascript = (installed / "stash-curator.js").read_text()
    assert "data:image/png;base64" in javascript
    assert "curator-whisparr-fallback" in javascript
    assert "curator-whisparr-action" in javascript
    assert "Adding to Whisparr…" in javascript
    assert "Added to Whisparr." in javascript
    assert "Retry sending to Whisparr" in javascript
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
    assert "\x01p\x020.0500" in task.stderr
    assert "\x01p\x020.9500" in task.stderr
    assert "\x01p\x021.0000" in task.stderr
    with sqlite3.connect(installed / "data" / "curator.sqlite3") as connection:
        assert connection.execute("SELECT last_error FROM model_update_state").fetchone()[0]


def test_playback_capture_binds_the_media_element_and_rebinds_when_replaced() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    # A Video.js wrapper resolved once goes stale when Stash rebuilds the player, which
    # silently produced sessions with no observed playback.
    assert "media.addEventListener(event, handler)" in source
    assert "media.removeEventListener(event, handler)" in source
    assert "player.on(event, handler)" not in source
    assert "element.isConnected" in source
    assert "!media.isConnected" in source


def test_backup_management_uses_recognized_ids_and_explicit_confirmation() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert "icon: faDatabase,\n      maintenance: true" in source
    assert 'value: "backups"' in source
    assert 'operation: "list_backups"' in source
    assert 'operation: "create_backup"' in source
    assert 'operation({ operation: "create_backup" }, 120000)' in source
    assert 'operation: "restore_backup"' in source
    assert "backup_id: item.id" in source
    assert "confirmation: `RESTORE ${item.id}`" in source
    assert "Safety backup:" in source
    assert 'operation: "delete_backup"' in source
    assert "confirmation: `DELETE ${item.id}`" in source


def test_backup_controls_validate_ids_refuse_jobs_and_restore_with_safety_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_backups", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "curator.sqlite3"
    backups = tmp_path / "backups"
    payload = {"args": {"database_path": str(database)}}
    settings = {"backupPath": str(backups)}
    connection = module._open(payload, settings)
    module.CuratorAPI(connection).update_config({"page_size": 12}, now_ms=1)
    connection.execute(
        """
        INSERT INTO feature_build(
            feature_version, status, config_json, source_fingerprint, created_at_ms
        ) VALUES ('feature', 'published', '{}', 'source', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO model_version(
            model_id, status, feature_version, config_json, created_at_ms
        ) VALUES ('model', 'published', 'feature', '{}', 1)
        """
    )
    connection.close()

    created = module._backup_control(payload, "create_backup", settings)
    backup_id = Path(str(created["backup_path"])).name
    assert created["items"][0]["id"] == backup_id
    restore_copy = module._backup_control(payload, "create_backup", settings)
    restore_id = Path(str(restore_copy["backup_path"])).name
    safety = backups / "curator-before-job-repair-20260730T060149Z.sqlite3.backup"
    temporary = backups / f".{backup_id}.temporary"
    unrelated = backups / "other.sqlite3.backup"
    linked = backups / "curator-123.sqlite3.backup"
    incomplete = backups / "curator-124.sqlite3.backup"
    safety.touch()
    temporary.touch()
    unrelated.touch()
    linked.symlink_to(created["backup_path"])
    incomplete.touch()

    connection = module._open(payload, settings)
    module.CuratorAPI(connection).update_config({"page_size": 30}, now_ms=2)
    connection.execute(
        """
        INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
        VALUES ('running', 'build', 'running', 3)
        """
    )
    connection.close()
    with pytest.raises(RuntimeError, match="job is running"):
        module._backup_control(payload, "create_backup", settings)
    payload["args"] = {
        "database_path": str(database),
        "backup_id": backup_id,
        "confirmation": f"DELETE {backup_id}",
    }
    with pytest.raises(RuntimeError, match="job is running"):
        module._backup_control(payload, "delete_backup", settings)
    connection = module._open(payload, settings)
    connection.execute("DELETE FROM curator_job WHERE job_id='running'")
    connection.close()

    payload["args"] = {
        "database_path": str(database),
        "backup_id": f"../{backup_id}",
        "confirmation": f"RESTORE ../{backup_id}",
    }
    with pytest.raises(ValueError, match="recognized"):
        module._backup_control(payload, "restore_backup", settings)
    for invalid in (
        f"../{backup_id}",
        str(Path(str(created["backup_path"])).resolve()),
        safety.name,
        temporary.name,
        unrelated.name,
        linked.name,
    ):
        payload["args"] = {
            "database_path": str(database),
            "backup_id": invalid,
            "confirmation": f"DELETE {invalid}",
        }
        with pytest.raises(ValueError, match="recognized"):
            module._backup_control(payload, "delete_backup", settings)
    payload["args"] = {
        "database_path": str(database),
        "backup_id": incomplete.name,
        "confirmation": f"DELETE {incomplete.name}",
    }
    with pytest.raises(ValueError, match="incompatible"):
        module._backup_control(payload, "delete_backup", settings)
    payload["args"] = {
        "database_path": str(database),
        "backup_id": backup_id,
        "confirmation": "DELETE wrong",
    }
    with pytest.raises(ValueError, match="confirmation"):
        module._backup_control(payload, "delete_backup", settings)
    with monkeypatch.context() as patch:
        original_unlink = Path.unlink

        def fail_backup_delete(path: Path, *args: object, **kwargs: object) -> None:
            if path == Path(str(created["backup_path"])):
                raise OSError("busy")
            original_unlink(path, *args, **kwargs)

        patch.setattr(Path, "unlink", fail_backup_delete)
        with pytest.raises(OSError, match="busy"):
            module._backup_control(
                {
                    "args": {
                        "database_path": str(database),
                        "backup_id": backup_id,
                        "confirmation": f"DELETE {backup_id}",
                    }
                },
                "delete_backup",
                settings,
            )
    connection = module._open(payload, settings)
    assert module.CuratorAPI(connection).config()["config"]["page_size"] == 30
    assert connection.execute("SELECT status FROM model_version").fetchone()[0] == "published"
    connection.close()
    deleted = module._backup_control(
        {
            "args": {
                "database_path": str(database),
                "backup_id": backup_id,
                "confirmation": f"DELETE {backup_id}",
            }
        },
        "delete_backup",
        settings,
    )
    assert deleted["deleted"] == backup_id
    assert not Path(str(created["backup_path"])).exists()
    assert (
        safety.is_file()
        and temporary.is_file()
        and unrelated.is_file()
        and linked.is_symlink()
        and incomplete.is_file()
    )
    payload["args"] = {
        "database_path": str(database),
        "backup_id": restore_id,
        "confirmation": f"RESTORE {restore_id}",
    }
    restored = module._backup_control(payload, "restore_backup", settings)

    assert Path(str(restored["restored_from"])).name == restore_id
    assert Path(str(restored["safety_backup"])).is_file()
    assert restored["recommendations_need_rebuilding"] is True
    connection = module._open(payload, settings)
    assert module.CuratorAPI(connection).config()["config"]["page_size"] == 12
    assert (
        connection.execute("SELECT status FROM model_version WHERE model_id='model'").fetchone()[0]
        == "superseded"
    )
    connection.close()


def test_install_optional_deps_creates_venv_and_installs_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_install_deps", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_dir = tmp_path / "stash-curator"
    (plugin_dir / "packages").mkdir(parents=True)
    requirements = plugin_dir / "packages" / "curator-tools.txt"
    requirements.write_text("numpy==2.5.1\n", encoding="utf-8")
    monkeypatch.setattr(module, "PLUGIN_DIR", plugin_dir)
    created: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        module,
        "create_venv",
        lambda path, with_pip: created.append((path, with_pip)),
    )
    installed: list[list[str]] = []
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda command, **_: (
                installed.append(command)
                or SimpleNamespace(returncode=0, stderr="", stdout="installed numpy")
            )
        ),
    )

    result = module._install_optional_deps()

    assert created == [(plugin_dir / "venv", True)]
    assert installed[0][-3:] == ["install", "-r", str(requirements)]
    assert result == {
        "status": "ok",
        "venv": str(plugin_dir / "venv"),
        "requirements": str(requirements),
    }


def test_install_optional_deps_refuses_missing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_install_deps_missing", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PLUGIN_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="missing optional dependency manifest"):
        module._install_optional_deps()


def test_install_optional_deps_surfaces_pip_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_install_deps_failure", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_dir = tmp_path / "stash-curator"
    (plugin_dir / "packages").mkdir(parents=True)
    (plugin_dir / "packages" / "curator-tools.txt").write_text("numpy\n", encoding="utf-8")
    (plugin_dir / "venv").mkdir()
    (plugin_dir / "venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    monkeypatch.setattr(module, "PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(
        module,
        "subprocess",
        SimpleNamespace(
            run=lambda command, **_: SimpleNamespace(
                returncode=1, stderr="no matching distribution", stdout=""
            )
        ),
    )

    with pytest.raises(RuntimeError, match="pip install failed"):
        module._install_optional_deps()


def test_reset_removes_only_core_and_recognized_artifacts(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_reset", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "curator.sqlite3"
    payload = {
        "args": {
            "operation": "reset",
            "database_path": str(database),
            "confirmation": "RESET",
        }
    }
    connection = module._open(payload, {})
    connection.close()
    derived = tmp_path / "curator-derived"
    derived.mkdir()
    artifact = derived / f"model-{'a' * 20}.sqlite3"
    unrelated = derived / "keep-me.txt"
    artifact.touch()
    unrelated.touch()

    assert module.dispatch(payload)["reset"] is True

    assert database.is_file()
    assert not artifact.exists()
    assert unrelated.is_file()


def test_curator_tabs_update_browser_history() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "const routeLocation = useLocation();" in source
    assert "history.push({ pathname: routeLocation.pathname, search: route.toString() });" in source
    assert "onClick: () => openView(option.value)" in source
    # Reference parameters belong to the lane that created them (hunt performer
    # and label, similar id and type); switching lanes must drop them so they
    # cannot leak into another panel, e.g. the expand performer filter.
    assert (
        'for (const param of ["performer", "label", "id", "type"]) route.delete(param);' in source
    )
    assert 'lane === "expand" && React.createElement(ExpandPanel, { key: "expand" }),' in source


def test_recent_recommendations_reuse_qualified_impression_history() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "history"' in source
    assert "icon: faHistory,\n      maintenance: true" in source
    assert 'operation: "get_recommendation_history"' in source
    assert '"Filter recommendation history by lane"' in source
    assert 'className: "form-control form-control-sm", value: laneFilter' in source
    assert '"Scene removed from Stash"' in source
    assert "item.reason_snapshot.map(reasonLabel)" in source
    assert '"Why this now?"' in source


def test_taste_profile_uses_fixed_durable_tag_sentiment_control() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "taste"' in source
    assert 'operation: "get_taste_profile"' in source
    assert 'operation: "submit_tag_preferences"' in source
    assert "TAG_PREFERENCE_QUEUE_KEY" in source
    assert '[-1, "Strong dislike", "curator-sentiment-danger"]' in source
    assert '[1, "Strong like", "curator-sentiment-love"]' in source
    assert '"Clear answer"' in source
    assert '"Search taste profile tags"' in source
    assert '"Filter taste profile tags"' in source
    assert 'value: "answered"' in source
    assert '"Needs answer"' in source
    assert '"Sort taste profile"' in source
    assert 'value: "confidence"' in source
    assert 'value: "scenes"' in source
    assert 'if (sort !== "suggested")' in source


def test_diagnostics_can_be_previewed_copied_and_downloaded_separately_from_traces() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "diagnostics"' in source
    assert "icon: faWrench,\n      maintenance: true" in source
    assert "const PRIMARY_NAV_ITEMS = NAV_ITEMS.filter((item) => !item.maintenance);" in source
    assert "const MAINTENANCE_ITEMS = NAV_ITEMS.filter((item) => item.maintenance);" in source
    assert "icon: faBroom,\n      maintenance: true" in source
    assert "icon: faTag,\n      maintenance: true" in source
    assert 'className: "curator-maintenance-menu"' in source
    assert 'React.createElement("span", null, "Maintenance")' in source
    assert 'operation: "get_diagnostics"' in source
    assert '"Diagnostics copied."' in source
    assert 'link.download = "stash-curator-diagnostics.json"' in source
    assert "Profiling traces are separate and are not included." in source


def test_thumb_down_follow_up_is_optional_and_survives_card_removal() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'operation: "get_tag_sentiment_follow_up"' in source
    assert 'if (feedbackType === "thumb_down" && onThumbDown)' in source
    assert "onThumbDown(followUp);" in source
    assert "onRemove(item.scene_id);" in source
    assert "TagSentimentFollowUp" in source
    assert '"None of these"' in source
    assert '"Something scene-specific"' in source
    assert '"Metadata is wrong"' in source
    assert '"Skip"' in source
    assert "onClick: onDismiss" in source
    assert "submitTagPreference(tag.tag_id, {value, blocked});" in source


def test_feedback_history_can_undo_or_replace_append_only_actions() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "feedback"' in source
    assert 'label: "Feedback history"' in source
    assert 'operation: "get_feedback_history"' in source
    assert 'operation: "correct_feedback"' in source
    assert '"Scene removed from Stash"' in source
    assert '"Replacement feedback"' in source
    assert 'className: "form-control form-control-sm", value: replacement' in source
    assert "icon: faThumbsUp,\n      maintenance: true" in source
    assert "scheduleModelUpdate();" in source


def test_recommendation_grid_hides_scenes_stash_no_longer_has() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert (
        "const resolved = !scenesQuery.loading && !scenesQuery.error && Boolean(scenesQuery.data);"
        in source
    )
    assert "scenes.has(String(item.scene_id))" in source
    assert "visibleItems.map((item) => React.createElement(RecommendationCard" in source
    assert "visibleItems.length === 0 && React.createElement" in source


def test_external_scene_cards_can_rate_matching_local_tags() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'operation: "get_external_tag_choices"' in source
    assert '"Rate matching local tags"' in source
    assert '"No matching local tags."' in source
    assert "submitTagPreference(tag.tag_id, {value, blocked});" in source


def test_curator_external_components_are_public_and_patchable() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert 'Api.register.component("stash-curator.ExternalCard"' in source
    assert 'Api.register.component("stash-curator.SourceReference"' in source
    assert 'transformComponentProps("stash-curator.ExternalCard", props)' in source
    assert 'transformComponentProps("stash-curator.SourceReference", props)' in source


def test_whisparr_button_is_disabled_until_configured() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "disabled: !whisparrEnabled ||" in source
    assert "setWhisparrEnabled(data.whisparr_enabled)" in source
    assert "onWhisparr: sendWhisparr, whisparrEnabled" in source


def test_curator_prefetches_only_the_intended_lane() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "function prefetchLanes" not in source
    assert "if (!laneByValue.has(lane) || cachedConfigUpdatedAtMs === null) return;" in source
    assert "loadSlate(lane, page).then(" in source
    assert "loadSlate(lane, 1, true).catch(" in source
    assert "onMouseEnter: () => prefetchLane(option.value)" in source
    assert "onFocus: () => prefetchLane(option.value)" in source


def test_plugin_pages_generated_results_without_repeating_external_searches() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert "function Pager({ page, total, pageSize, hasMore, loading, onPage, label })" in source
    assert "function useUrlPage(param)" in source
    assert '"aria-current": value === page ? "page" : undefined' in source
    assert "pagerPages(page, totalPages)" in source
    for param in (
        "page_for_you",
        "page_feedback",
        "page_history",
        "page_similar",
        "page_prune_${view}",
        "page_expand_${entityType}",
        "page_hunt",
    ):
        assert param in source
    assert "setPage(last, { replace: true })" in source
    assert "return `${cachedConfigUpdatedAtMs || 0}:${lane}:${page}`" in source
    assert "externalItems.slice((page - 1) * pageSize, page * pageSize)" in source
    assert 'operation: "get_expand", page' in source


def test_recommendation_variety_toggle_updates_native_setting_and_cache() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert 'configurePlugin(plugin_id: "stash-curator", input: $input)' in source
    assert "await configurePlugin({ diversityDisabled: !nextEnabled });" in source
    assert "configUpdatedAtMs: cachedConfigUpdatedAtMs" in source
    assert "laneByValue.has(lane) && diversityEnabled !== null" in source
    assert '"aria-pressed": diversityEnabled' in source
    assert "icon: faBalanceScale" in source
    assert "faRandom" not in source
    assert 'diversityEnabled ? " Balanced" : " Score-first"' in source


def test_plugin_performer_hunt_keeps_results_and_reuses_external_cards() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert 'operation: "get_performer_hunt"' in source
    assert 'value: "hunt"' in source
    assert "icon: faCrosshairs" in source
    assert 'initialType: "hunt", huntOnly: true' in source
    assert '["all", `All ${huntCounts.all}`]' in source
    assert '["linked", `In library ${huntCounts.linked}`]' in source
    assert '["unlinked", `Not linked locally ${huntCounts.unlinked}`]' in source
    assert 'kind: "tag", label: "Include tags"' in source
    assert 'kind: "tag", label: "Exclude tags"' in source
    assert source.count('" Hide exact PHash matches"') == 3
    assert "hide_phash_matches: hidePhashMatches" in source
    assert '"Likely local · exact PHash"' in source
    assert '"Release date"' in source
    assert '"Preference score"' in source
    assert "data?.truncated" in source
    assert "(failure) => active && (setError(failure.message), setLoading(false))" in source
    assert 'entityType === "hunt" ? "scene" : entityType' in source


def test_plugin_reads_local_file_phashes_for_external_matching() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "backend.py").read_text(encoding="utf-8")

    assert "files { fingerprints { type value } }" in source
    assert '"scene_phashes": {}' in source
    assert 'casefold() == "phash"' in source


def test_plugin_ignores_repeated_script_evaluation() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    guard = "if (window.__stashCuratorPluginLoaded) return;"
    assert source.count(guard) == 1
    assert source.index(guard) < source.index("const Api = window.PluginApi;")


def test_custom_cards_follow_native_sfw_contract_and_explain_views() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "grid-card ${kind}-card" in source
    assert (
        "className: `curator-external-thumbnail thumbnail-section "
        '${kind === "scene" ? "video-section" : ""}`' in source
    )
    assert 'className: "card-section-title flex-aligned"' in source
    assert 'metadataPopover("tags", faTag, "Tags", tags.length' in source
    assert 'metadataPopover("performers", faUser, "Performers", cast.length' in source
    assert "React.createElement(\n        HoverPopover," in source
    assert "leaveDelay: 250" in source
    assert 'className: "minimal curator-external-popover-button"' in source
    assert 'className: "performer-tag-container row"' in source
    assert 'className: "image-thumbnail"' in source
    assert 'className: "tag-item tag-link badge badge-secondary"' in source
    assert 'React.createElement("summary", null, "Why this?")' in source
    assert '{ className: "curator-evidence", onToggle: explain }' in source
    assert 'operation({ operation: "get_explanation", scene_id: item.scene_id }, 60000)' in source
    assert '"Explaining…"' in source
    assert 'React.createElement("summary", null, `Score · ${item.score.toFixed(2)}`)' in source
    assert 'React.createElement("summary", null, `Score · ${item.rank_score.toFixed(2)}`)' in source
    assert (
        'className: kind === "scene" ? "scene-card__details" : "curator-external-details"' in source
    )
    assert "className: `${type}-card-image`" in source
    assert 'className: "card-section-title"' in source
    assert "Curator never deletes media; tagging is reversible" in source
    assert "Score is ranking utility, not a probability" in source
    assert '"appeal.performer_identity": "Performer match"' in source
    assert '"appeal.content_neighbor": "Similar content"' in source
    assert "Wildcard items are selected outside preference-derived seeds" in source


def test_similarity_source_switch_visible_before_reference_is_selected() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    tabs = 'className: "btn-group curator-similar-source-tabs"'
    assert tabs in source
    # The Library/StashDB switch must be usable with no reference selected yet.
    assert f'selected && React.createElement("div", {{ {tabs}' not in source
    # Switching the entity type must not silently reset the chosen source.
    assert 'setSource("library")' not in source
    assert 'React.useState("library")' in source


def test_performer_source_reference_uses_portrait_image() -> None:
    css = (Path(__file__).parents[2] / "plugin" / "stash-curator.css").read_text(encoding="utf-8")
    block = css.split(".curator-source-reference-performer img", 1)[1].split("}", 1)[0]
    assert "height: 6rem" in block
    assert "width: 4rem" in block
    assert "min-width: 4rem" in block


def test_backend_module_loads_without_starting(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_backend", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA_VERSION == 1


def test_diagnostics_allowlist_cannot_emit_representative_private_fields(
    tmp_path: Path,
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_diagnostics", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "PRIVATE_DATABASE.sqlite3"
    payload = {"args": {"database_path": str(database)}}
    connection = module._open(payload, {})
    connection.execute(
        "UPDATE curator_config SET config_json=? WHERE singleton=1",
        (
            json.dumps(
                {
                    "url": "PRIVATE_URL",
                    "api_key": "PRIVATE_KEY",
                    "preference": "PRIVATE_PREFERENCE",
                }
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO source_scene(scene_id, title, source_hash)
        VALUES ('PRIVATE_ENTITY_ID', 'PRIVATE_TITLE', 'private')
        """
    )
    connection.execute(
        """
        INSERT INTO source_performer(performer_id, name, source_hash)
        VALUES ('private-performer', 'PRIVATE_PERFORMER', 'private')
        """
    )
    connection.execute(
        """
        INSERT INTO source_tag(tag_id, name, source_hash)
        VALUES ('private-tag', 'PRIVATE_TAG', 'private')
        """
    )
    connection.execute(
        """
        INSERT INTO curator_job(
            job_id, job_type, state, started_at_ms, finished_at_ms, summary_json, error
        ) VALUES (
            'PRIVATE_JOB_ID', 'sync-build', 'failed', 100, 250,
            '{"entity":"PRIVATE_ENTITY_ID"}',
            'PRIVATE_SQL SELECT * FROM feedback at PRIVATE_URL'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO profile_trace(
            trace_id, kind, operation, started_at_ms, duration_us, status,
            span_count, truncated, trace_json
        ) VALUES (
            'PRIVATE_TRACE_ID', 'operation', 'test', 1, 1, 'ok', 1, 0,
            '{"traceEvents":[{"args":{"statement":"PRIVATE_SQL"}}]}'
        )
        """
    )
    connection.close()

    report = module._api(
        payload,
        "get_diagnostics",
        {"whisparrUrl": "PRIVATE_URL", "whisparrApiKey": "PRIVATE_KEY"},
    )
    serialized = json.dumps(report, sort_keys=True)

    assert set(report) == {
        "report_version",
        "generated_at_ms",
        "curator_version",
        "api_schema_version",
        "migration",
        "readiness",
        "generations",
        "compaction",
        "recent_jobs",
        "timing_ms",
    }
    assert report["recent_jobs"][0]["outcome"] == "failed"
    for private in (
        str(database),
        "PRIVATE_URL",
        "PRIVATE_KEY",
        "PRIVATE_PREFERENCE",
        "PRIVATE_ENTITY_ID",
        "PRIVATE_TITLE",
        "PRIVATE_PERFORMER",
        "PRIVATE_TAG",
        "PRIVATE_JOB_ID",
        "PRIVATE_TRACE_ID",
        "PRIVATE_SQL",
    ):
        assert private not in serialized


def test_diagnostics_work_with_an_empty_repaired_job_table(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_empty_jobs", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {"args": {"database_path": str(tmp_path / "curator.sqlite3")}}
    connection = module._open(payload, {})
    connection.execute("DELETE FROM curator_job")
    connection.close()

    report = module._api(payload, "get_diagnostics", {})

    assert report["recent_jobs"] == []
    assert report["migration"]["pending_count"] == 0


def test_external_links_collect_normalized_local_phashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_links", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {
        "scenes": {
            "count": 1,
            "scenes": [
                {
                    "id": "local-scene",
                    "stash_ids": [
                        {
                            "endpoint": "https://stashdb.org/graphql",
                            "stash_id": "external-scene",
                        }
                    ],
                    "files": [
                        {
                            "fingerprints": [
                                {"type": "phash", "value": "D8BC7554C5A178AA"},
                                {"type": "phash", "value": "not-a-phash"},
                            ]
                        }
                    ],
                }
            ],
        },
        "performers": {"count": 0, "performers": []},
        "studios": {"count": 0, "studios": []},
    }
    monkeypatch.setattr(
        module,
        "_client",
        lambda _payload: SimpleNamespace(execute=lambda *_args: data),
    )

    links = module._external_links({})

    assert links["scene_ids"] == {"external-scene": "local-scene"}
    assert links["scene_phashes"] == {"d8bc7554c5a178aa": "local-scene"}


def test_first_run_health_reports_setup_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_health", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = {
        "version": {"version": "0.31.0"},
        "jobQueue": [],
        "configuration": {
            "general": {
                "stashBoxes": [{"endpoint": "https://stashdb.org/graphql", "api_key": "configured"}]
            }
        },
    }
    monkeypatch.setattr(module, "_settings", lambda _payload: {})
    monkeypatch.setattr(
        module,
        "_client",
        lambda _payload: SimpleNamespace(execute=lambda *_args: runtime),
    )

    health = module._health({"args": {"database_path": str(tmp_path / "curator.sqlite3")}})

    assert health["sidecar_ready"] is True
    assert health["database_schema"] == health["database_schema_latest"]
    assert health["sync_ready"] is False
    assert health["ready"] is False
    assert health["stashdb_available"] is True


def test_first_run_checklist_starts_setup_and_shows_actionable_errors() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert "health && !health.ready" in source
    assert "Sidecar and migrations:" in source
    assert '"optional — not configured"' in source
    assert 'start("Sync and build recommendations")' in source
    assert '"Initial sync failed: "' in source
    assert 'to: "/settings?tab=plugins"' in source


def test_health_reports_all_running_curator_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_active_jobs", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = {
        "version": {"version": "0.31.0"},
        "jobQueue": [
            {
                "id": "sync-job",
                "status": "RUNNING",
                "description": "Sync and build recommendations",
                "progress": 0.42,
                "startTime": "2026-08-08T00:00:00Z",
            },
            {
                "id": "expand-job",
                "status": "WAITING",
                "description": "Refresh Expand cache",
                "progress": 0,
                "startTime": "2026-08-08T00:01:00Z",
            },
            {
                "id": "deps-job",
                "status": "RUNNING",
                "description": "Install optional dependencies",
                "progress": 0.3,
                "startTime": "2026-08-08T00:02:00Z",
            },
            {
                "id": "finished-job",
                "status": "FINISHED",
                "description": "Backup Curator data",
                "progress": 1,
                "startTime": "2026-08-07T00:00:00Z",
            },
        ],
        "configuration": {"general": {"stashBoxes": []}},
    }
    monkeypatch.setattr(module, "_settings", lambda _payload: {})
    monkeypatch.setattr(
        module,
        "_client",
        lambda _payload: SimpleNamespace(execute=lambda *_args: runtime),
    )

    health = module._health({"args": {"database_path": str(tmp_path / "curator.sqlite3")}})

    assert [job["id"] for job in health["active_jobs"]] == ["sync-job", "expand-job", "deps-job"]
    assert health["active_job"]["id"] == "sync-job"


def test_task_indicator_and_compact_external_tag_rating_are_shared_ui_contracts() -> None:
    root = Path(__file__).parents[2]
    source = (root / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    css = (root / "plugin" / "stash-curator.css").read_text(encoding="utf-8")

    assert "function CuratorTaskIndicator({ activeJobs, activities, failure })" in source
    assert "health?.active_jobs" in source
    assert 'to: "/settings?tab=tasks"' in source
    assert "curatorTaskStage(job)" in source
    assert '"Synchronizing library metadata"' in source
    assert '"Building the recommendation model"' in source
    assert '"Installing optional dependencies"' in source
    assert "curator-task-progress-indeterminate" in source
    assert "showTaskDetails" in source
    assert 'activeJobs.length > 0 || state === "failed"' in source
    assert '"No active tasks"' not in source
    assert "Querying StashDB" not in source
    assert 'className: "curator-loading", role: "status"' in source
    assert 'className: "curator-progress"' not in source
    assert "Matching local tags (${tagChoices.length})" in source
    assert "Collapse matching local tag ratings" in source
    assert "compact: true" in source
    assert 'const shortLabel = score === -1 ? "--"' in source
    assert "curator-sentiment-compact" in css
    assert ".curator-external-tag-rating-header" in css
    assert ".curator-external-tag-row" in css
    assert ".curator-task-progress-track" in css
    assert ".curator-active-job" not in css
    assert ".curator-task-ring" not in css
    assert ".curator-progress" not in css


def test_reused_model_keeps_existing_lane_classifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_lanes", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.LanePolicy,
        "classify",
        lambda *_args: (_ for _ in ()).throw(AssertionError("reclassified")),
    )
    cursor = SimpleNamespace(fetchone=lambda: (3,))
    connection = SimpleNamespace(execute=lambda *_args: cursor)

    assert module._classify_lanes(connection, "model") == 3


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
            "diversityDisabled": True,
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
        assert config["diversity_enabled"] is False
        assert config["model_update_event_threshold"] == 7
    finally:
        connection.close()
    assert (
        module._api(
            {"args": {"database_path": str(tmp_path / "curator.sqlite3")}},
            "get_config",
            {"whisparrUrl": "http://whisparr.local", "whisparrApiKey": "secret"},
        )["whisparr_enabled"]
        is True
    )
    assert (
        module._api(
            {"args": {"database_path": str(tmp_path / "curator.sqlite3")}},
            "get_config",
            {"whisparrUrl": "http://whisparr.local"},
        )["whisparr_enabled"]
        is False
    )
    code_version = module._api(
        {"args": {"database_path": str(tmp_path / "curator.sqlite3")}},
        "get_config",
        {},
    )["code_version"]
    assert code_version and len(code_version) == 16
    assert (
        module._api(
            {"args": {"database_path": str(tmp_path / "curator.sqlite3")}},
            "get_config",
            {},
        )["code_version"]
        == code_version
    )


def test_model_tasks_prepare_recommendation_pages() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "backend.py").read_text(encoding="utf-8")

    assert source.count("_mapped_progress(0.97, 0.99)") == 2
    assert "_mapped_progress(0.05, 0.99)" in source
    assert '"lane_candidate_caches": lane_caches' in source


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


def test_external_links_reuse_the_last_scan_until_stash_reports_a_change(
    tmp_path: Path,
) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_links", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = module._open({"args": {"database_path": str(tmp_path / "curator.sqlite3")}}, {})

    scanned = 0
    state = {"count": 1, "updated_at": "2026-01-01T00:00:00Z"}

    class FakeClient:
        def execute(self, document: str, variables: object = None) -> dict[str, object]:
            nonlocal scanned
            if "CuratorExternalLinksState" in document:
                return {
                    kind: {"count": state["count"], kind: [{"updated_at": state["updated_at"]}]}
                    for kind in ("scenes", "performers", "studios")
                }
            scanned += 1
            return {
                "scenes": {
                    "count": 1,
                    "scenes": [
                        {
                            "id": "7",
                            "stash_ids": [
                                {"endpoint": module.STASHDB, "stash_id": "external-scene"}
                            ],
                            "files": [
                                {"fingerprints": [{"type": "phash", "value": "0123456789abcdef"}]}
                            ],
                        }
                    ],
                },
                "performers": {"count": 0, "performers": []},
                "studios": {"count": 0, "studios": []},
            }

    module._client = lambda payload: FakeClient()
    first = module._external_links({}, connection)

    assert scanned == 1
    assert first["scenes"] == {"7": "external-scene"}
    assert first["scene_phashes"] == {"0123456789abcdef": "7"}

    assert module._external_links({}, connection) == first
    assert scanned == 1, "an unchanged library must not be walked again"

    module._external_links({}, connection, refresh=True)
    assert scanned == 2, "the refresh task must be able to force a rescan"

    state["updated_at"] = "2026-02-02T00:00:00Z"
    module._external_links({}, connection)
    assert scanned == 3, "an edited library must invalidate the cache"

    state["count"] = 2
    module._external_links({}, connection)
    assert scanned == 4, "an added or deleted link must invalidate the cache"


def test_every_user_visible_empty_and_error_message_is_defensive() -> None:
    """Every empty-state, error, and guidance message must remain in the source.

    These are the strings users see when something is missing, broken, or
    needs action.  Removing or rewording one silently breaks the UX.
    """
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    # ── empty / not-ready states ──
    assert '"No supported tags are available yet."' in source
    assert '"No tags match that search."' in source
    assert '"No matching local tags."' in source
    assert '"No matches found."' in source
    assert '"No feedback has been recorded yet."' in source
    assert '"No qualified recommendations have been recorded yet."' in source
    assert '"Nothing in this view."' in source
    assert '"No Curator backups found."' in source
    assert '"No scenes match this view."' in source
    assert '"No external candidates match these filters."' in source
    assert '"No profiles have been recorded yet."' in source

    # ── guidance prompts ──
    assert '"Select a local performer linked to StashDB."' in source
    assert "Expand has not been prepared yet" in source
    assert '" Prepare now"' in source
    assert '" Sync and build now"' in source
    assert '" Rebuild model"' in source
    assert '"Nothing qualifies for this lane right now."' in source
    assert "no model exists yet" in source

    # ── warnings ──
    assert "Showing the first" in source
    assert "StashDB scenes; the safety cap is" in source
    assert "Profiling is disabled." in source
    assert '"Initial sync failed: "' in source
    assert "Open Tasks for the full log" in source

    # ── external card tag rating states ──
    assert '"Matching local tags…"' in source
    assert '"Rate matching local tags"' in source
    assert '"Configure Whisparr in plugin settings"' in source
    assert '"Retry sending to Whisparr"' in source
    assert '"Send to Whisparr"' in source
