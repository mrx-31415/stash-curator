from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
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
    source = root / "plugin"
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            relative = path.relative_to(source)
            # The zip ships no Python backend; the only curator-package
            # resource is the explanation catalog the binary reads at runtime.
            if "data" not in relative.parts and relative.as_posix() != "backend.py":
                expected.add(relative.as_posix())
    expected.add("curator/explanations/realizations.json")
    # The compiled core ships as per-arch binaries; every shipped platform must
    # be present (the runtime selects one and falls back to numpy / pure Python).
    from scripts.build_plugin import SHIPPED_PLATFORMS, core_binary_name

    for goos, goarch in SHIPPED_PLATFORMS:
        expected.add(core_binary_name(goos, goarch))
    assert names == expected
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    extracted = tmp_path / "installed"
    from curator.core import _platform_binary_name

    current_platform = _platform_binary_name()
    for goos, goarch in SHIPPED_PLATFORMS:
        name = core_binary_name(goos, goarch)
        binary = extracted / name
        assert binary.is_file() and binary.stat().st_size > 1_000_000
        if goos != "windows":
            # The archive must carry the exec bit (Stash's Go extraction honors
            # it). Python 3.14's zipfile masks extracted permissions, so restore
            # them here; run the probe for this host's binary to prove the
            # shipped artifact works (other arches cannot execute here).
            assert (package.getinfo(name).external_attr >> 16) & 0o111
            binary.chmod(binary.stat().st_mode | 0o111)
            if name == current_platform:
                probe = subprocess.run(
                    [str(binary), "version"], capture_output=True, text=True, check=True
                )
                assert '"protocol":1' in probe.stdout
    index = (tmp_path / "index.yml").read_text(encoding="utf-8")
    assert "id: stash-curator" in index
    assert f"sha256: {sha256(archive.read_bytes()).hexdigest()}" in index
    assert re.search(r"date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", index)
    host_binary = extracted / current_platform
    assert host_binary.is_file()
    installed = tmp_path / "installed"
    plugin_manifest = (installed / "stash-curator.yml").read_text(encoding="utf-8")
    with (root / "pyproject.toml").open("rb") as source:
        project_version = tomllib.load(source)["project"]["version"]
    assert f"version: {project_version}" in plugin_manifest
    assert "Apply recent Curator feedback" in plugin_manifest
    assert "Prepare recommendation pages" in (installed / "stash-curator.yml").read_text()
    assert "Compact legacy Curator data" in (installed / "stash-curator.yml").read_text()
    assert "Vacuum compacted Curator data" in (installed / "stash-curator.yml").read_text()
    # The exec line resolves the per-arch binary through the launcher shim, so
    # the shipped manifest must point at launcher.py and the shim must exec
    # the same binary the resolver probes.
    exec_lines = [
        line.strip() for line in plugin_manifest.splitlines() if line.strip().startswith("- ")
    ]
    assert '"{pluginDir}/launcher.py"' in "\n".join(exec_lines)
    launcher = (installed / "launcher.py").read_text(encoding="utf-8")
    assert "curator-core-" in launcher
    assert "backend.py" not in launcher
    assert "reinstall the plugin" in launcher
    javascript = (installed / "stash-curator.js").read_text()
    assert "data:image/png;base64" in javascript
    assert "curator-whisparr-fallback" in javascript
    assert "curator-whisparr-action" in javascript
    assert "Adding to Whisparr…" in javascript
    assert "Added to Whisparr." in javascript
    assert "Retry sending to Whisparr" in javascript
    assert _run(installed / "launcher.py", installed)["round_trips"] == 1
    # The zip carries no Python backend; a platform without a shipped binary
    # makes the launcher fail with a clear reinstall message instead of
    # half-running.
    assert "backend.py" not in names
    bare = tmp_path / "bare-plugin"
    shutil.copytree(installed, bare)
    (bare / current_platform).unlink()
    missing = subprocess.run(
        [sys.executable, str(bare / "launcher.py"), str(bare)],
        input=json.dumps(_payload(bare)),
        text=True,
        capture_output=True,
    )
    assert missing.returncode == 1
    assert "no curator-core binary for this platform" in missing.stderr
    with sqlite3.connect(installed / "data" / "curator.sqlite3") as connection:
        connection.execute(
            "UPDATE model_update_state SET last_started_at_ms=2, "
            "last_finished_at_ms=1, last_error=NULL"
        )
    # The shipped binary enqueues tasks to its own daemon (decision 004):
    # prove the extracted artifact spawns the worker and completes a real
    # backup through it, with progress in the daemon log.
    from tests.core.worker import run_go_task_via_worker, stop_worker

    worker_dir = Path(tempfile.mkdtemp(prefix="curator-worker-"))
    try:
        row = run_go_task_via_worker(
            host_binary,
            worker_dir,
            installed / "data" / "curator.sqlite3",
            "backup",
            "http://127.0.0.1:1",
        )
        assert row["state"] == "complete", row
        assert row["summary"]["backup"].endswith(".sqlite3.backup")
        log = (worker_dir / "data" / "curator-daemon.log").read_text(encoding="utf-8")
        assert "Stash Curator backup completed" in log
        assert "\x01p\x020.0500" in log
        assert "\x01p\x020.9500" in log
        assert "\x01p\x021.0000" in log
    finally:
        stop_worker(worker_dir)
        shutil.rmtree(worker_dir, ignore_errors=True)
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
    assert ": () => openView(option.value);" in source
    # The Recommendations and Manage pills must no-op when a lane/section
    # under them is already active, or clicking the parent pill while on
    # e.g. Best Bets would wrongly reset to For You (GH #150 Package 3).
    assert '? () => { if (!laneByValue.has(lane)) openView("for_you"); }' in source
    assert (
        'if (lane !== "manage") openManage(currentSection || MAINTENANCE_ITEMS[0].value)' in source
    )
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

    # One control, two homes: Manage > Taste Profile shows the full list, and
    # Curate > Tag sentiment mounts the same panel as a "Needs answer" queue.
    assert 'function TasteProfilePanel({ embedded = false, initialStatus = "all" } = {})' in source
    assert (
        'React.createElement(TasteProfilePanel, { embedded: true, initialStatus: "unanswered" })'
        in source
    )
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


def test_curate_lane_renders_sectioned_stream() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "curate"' in source
    # Curate is a sectioned view now: the old landing screen forced a choice
    # between "Random round" and "Pick-test a hypothesis", which are the same
    # activity with a different pair-selection filter.
    assert "const CURATE_SECTIONS = [" in source
    for section in ("stream", "hypothesis", "sentiment", "progress"):
        assert f'value: "{section}"' in source
    assert 'React.createElement("strong", null, "Random round")' not in source
    assert 'variant: "primary", disabled: picksBusy, onClick: () => generatePicks' not in source
    assert "curateTab" not in source
    assert "function SectionShell(" in source
    assert 'navLabel: "Curate sections"' in source
    assert 'navLabel: "Manage sections"' in source
    assert 'lane === "curate" && React.createElement(CuratePanel,' in source
    assert "section: curateSection, onSelectSection: openCurate" in source
    assert "function openCurate(section)" in source
    # Curate and Manage share ?section=, so switching views must clear it.
    assert '["performer", "label", "id", "type", "section"]' in source

    # The stream: answers post as they happen, with one buffered for undo.
    assert "function CurateStream()" in source
    assert "function usePickAnswers(" in source
    assert "CURATE_COMMIT_IDLE_MS" in source
    assert "CURATE_PREFETCH_MARGIN" in source
    assert "Submit picks" not in source
    assert "picksUndo" not in source
    assert "forwardPicks" not in source
    assert 'event.key === "Backspace"' in source
    assert "curator-pick-prefetch" in source

    assert "PickSceneCard" in source
    assert "function PickStage(" in source
    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"):
        assert f'{key}: "' in source
    assert "← Left" in source
    assert "Equal ↑" in source
    assert "Skip ↓" in source
    assert "CURATE_FLASH_MS" in source
    assert "setFlash" in source
    assert "curator-pick-video" in source
    assert "curator-pick-info" in source
    assert "curator-pick-cover" in source
    assert "poster: `/scene/${meta.scene_id}/screenshot`" in source
    assert "meta.performers" in source
    assert "Metadata wrong" in source
    assert "curator-pick-flag" in source
    assert 'winner: "flag"' in source
    assert "curator-pick-selected" in source

    # A tie is an answer, not a discard.
    assert 'onAnswer("tie")' in source
    assert '{ ArrowUp: "tie"' not in source or 'ArrowUp: "tie"' in source

    # In-context tag sentiment on the comparison screen (GH #153 problem 2).
    assert "function PairTagSentiment(" in source
    assert "curator-pick-tag-strip" in source
    assert "TagSentimentControl" in source

    assert 'operation: "get_curation_picks"' in source
    assert 'operation: "submit_curation_picks"' in source
    assert 'operation: "get_curation_pair_verdict"' in source
    assert 'operation: "get_tag_context_candidates"' in source
    assert 'operation: "get_curation_impact"' in source
    assert "ImpactReport" in source
    assert "loadSuggestions" in source
    # Hypothesis candidates come from tags the model is unsure about, not the
    # ones already rated low.
    assert "Ideas Curator is unsure about" in source
    assert "left.confidence - right.confidence" in source

    assert "CurateNudge" in source
    assert "CURATE_NUDGE_KEY" in source
    assert "MAX_NUDGE_ROUNDS" in source
    assert "curator-curate-nudge-dismiss" in source

    # The scene-batch rating flow stays retired, and the round-scoped picks
    # cache is gone with the submit gate.
    assert "get_curation_batch" not in source
    assert "submit_curation_ratings" not in source
    assert "CurationSceneCard" not in source
    assert "CURATION_STATE_KEY" not in source
    assert "PICKS_STATE_KEY" not in source


def test_diagnostics_can_be_previewed_copied_and_downloaded_separately_from_traces() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "diagnostics"' in source
    assert "icon: faWrench,\n      maintenance: true" in source
    assert "const PRIMARY_NAV_ITEMS = NAV_ITEMS.filter((item) => !item.maintenance);" in source
    assert "const MAINTENANCE_ITEMS = NAV_ITEMS.filter((item) => item.maintenance);" in source
    assert "icon: faBroom,\n      maintenance: true" in source
    assert 'value: "curate",\n      label: "Curate",\n      icon: faBullseye' in source
    # Diagnostics is a maintenance item folded into the Manage shell rather
    # than the old flat maintenance dropdown (GH #150 Package 3).
    assert 'className: "curator-manage-shell"' in source
    assert "function ManagePanel(" in source
    assert "diagnostics: () => React.createElement(DiagnosticsPanel)," in source
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
    assert '"Rate tags & terms"' in source
    assert '"No matching local tags."' in source
    assert "submitTagPreference(tag.tag_id, {value, blocked});" in source


def test_recommendation_and_similar_cards_can_rate_local_tags_and_terms() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert "function LocalRatingPanel" in source
    assert 'operation: "get_scene_tag_choices"' in source
    assert "React.createElement(LocalRatingPanel, { sceneId: item.scene_id })" in source
    assert "React.createElement(LocalRatingPanel, { sceneId: item.entity_id })" in source
    assert "submitTagPreference(row.tag_id, {value, blocked});" in source
    assert "submitTermPreference(row.term, {value, blocked});" in source
    assert "TERM_PREFERENCE_QUEUE_KEY" in source
    assert "localStorage.setItem(TERM_PREFERENCE_QUEUE_KEY" in source


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
    assert "loadSlate(lane, page, false, slateFilters).then(" in source
    assert "loadSlate(lane, 1, true).catch(" in source
    # Prefetch now hangs off the lane-switcher cards inside the collapsed
    # Recommendations tab, not the (now removed) flat per-lane nav pills
    # (GH #150 Package 3).
    assert "onMouseEnter: () => prefetchLane(laneItem.value)" in source
    assert "onFocus: () => prefetchLane(laneItem.value)" in source


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
        "page_prune_",
        "page_expand_",
        "page_hunt",
        "page_sentiment",
    ):
        assert param in source
    # The URL-backed page keys stay canonical: prune/expand derive theirs from
    # the current view/entity type exactly as the fixed keys used to.
    assert "page: urlPageSpec((state) => `page_prune_${state.view}`)" in source
    assert "page: urlPageSpec((state) => `page_expand_${state.entityType}`)" in source
    assert "updateUrl((s) => ({ ...s, page: last }), { replace: true })" in source
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


def test_settings_panel_reads_and_saves_every_configured_field() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    # Manage-shell wiring (GH #151): a maintenance nav entry plus a
    # MANAGE_BODIES factory, following the same three-touch-point pattern
    # as every other maintenance panel.
    assert 'value: "settings"' in source
    assert "icon: faCog,\n      maintenance: true" in source
    assert "settings: (extra) => React.createElement(SettingsPanel, extra)," in source
    assert (
        "function SettingsPanel({ diversityEnabled, diversitySaving, onToggleDiversity })" in source
    )
    assert (
        'configKey: "auto_tasks_enabled", type: "BOOLEAN", label: "Automatic background tasks"'
        in source
    )
    assert 'title: "Scheduling"' in source
    assert (
        'configKey: "schedule_expand_refresh_enabled", type: "BOOLEAN", '
        'label: "Scheduled Expand refresh"' in source
    )
    assert "curator-switch" in source and 'role: "switch"' in source
    assert "schedule_expand_refresh_at_hour" in source
    assert "body && body({ diversityEnabled, diversitySaving, onToggleDiversity })" in source
    assert (
        "React.createElement(ManagePanel, { section: currentSection, "
        "onSelectSection: openManage, diversityEnabled, diversitySaving, "
        "onToggleDiversity: toggleDiversity })" in source
    )

    # Raw plugin settings (Whisparr fields) aren't in curator_config, so the
    # panel reads them straight from Stash rather than through get_config.
    assert (
        'query CuratorPluginSettings { configuration { plugins(include: ["stash-curator"]) } }'
        in source
    )
    assert 'payload.data.configuration.plugins["stash-curator"] || {}' in source

    # One configurePlugin call per field, on change, matching the
    # toggleDiversity precedent this panel reuses for the diversity toggle
    # instead of re-implementing its cache-busting side effects.
    assert "await configurePlugin({ [field.key]: value });" in source

    # Every setting the issue calls out as in scope for v1 is represented,
    # with the config-backed ones mapped to their curator_config key and the
    # Whisparr-only ones left to read back via getPluginSettings().
    expected_fields = {
        "pageSize": "page_size",
        "syncPageSize": "sync_page_size",
        "modelUpdateEventThreshold": "model_update_event_threshold",
        "modelUpdateMaxWaitMinutes": "model_update_max_wait_minutes",
        "modelUpdateMinIntervalMinutes": "model_update_min_interval_minutes",
        "expandWildcard": "expand_wildcard",
        "expandGender": "expand_gender",
        "expandHorizonDays": "expand_horizon_days",
        "pruneTagName": "prune_tag_name",
    }
    for key, config_key in expected_fields.items():
        assert f'key: "{key}", configKey: "{config_key}"' in source
    for key in (
        "whisparrUrl",
        "whisparrApiKey",
        "whisparrRootFolder",
        "whisparrQualityProfileId",
        "whisparrSearchImmediately",
    ):
        assert f'key: "{key}"' in source

    # whisparrApiKey renders as a masked input, matching the issue's "mask
    # like a password field" requirement; nothing else in the panel does.
    assert '{ key: "whisparrApiKey", type: "PASSWORD"' in source
    assert 'field.type === "PASSWORD" ? "password"' in source

    # GH #188: the Storage and Development groups surface the remaining
    # plugin settings with the exact stash-curator.yml displayName/type text.
    # Like the Whisparr fields they are raw plugin settings (no configKey),
    # read back via getPluginSettings() rather than curator_config.
    assert 'title: "Storage"' in source
    assert 'title: "Development"' in source
    for key, field_type, label in (
        ("databasePath", "STRING", "Sidecar database path"),
        ("backupPath", "STRING", "Backup directory"),
        ("profilingEnabled", "BOOLEAN", "Enable profiling"),
        ("pprofEnabled", "BOOLEAN", "Capture CPU profiles"),
    ):
        assert f'key: "{key}", type: "{field_type}", label: "{label}"' in source


def test_settings_panel_mirrors_plugin_settings_schema() -> None:
    """The Manage → Settings panel and the plugin settings view cannot drift:
    every settings key in stash-curator.yml has a SETTINGS_FIELD_GROUPS entry
    and vice versa. diversityDisabled is the one documented exception — it is
    surfaced through the panel's own recommendation-variety toggle.
    """
    root = Path(__file__).parents[2]
    manifest = (root / "plugin" / "stash-curator.yml").read_text(encoding="utf-8")
    settings_block = manifest.split("settings:", 1)[1].split("\ntasks:", 1)[0]
    manifest_keys = {
        match.group(1)
        for line in settings_block.splitlines()
        if (match := re.match(r"^  ([A-Za-z][A-Za-z0-9]*):$", line))
    }

    source = (root / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    start = source.index("const SETTINGS_FIELD_GROUPS = [")
    end = source.index("function SettingsField({")
    panel_keys = set(re.findall(r'key: "([A-Za-z][A-Za-z0-9]*)"', source[start:end]))

    assert manifest_keys - panel_keys == {"diversityDisabled"}
    assert panel_keys - manifest_keys == set()


def test_plugin_performer_hunt_keeps_results_and_reuses_external_cards() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert 'operation: "get_performer_hunt"' in source
    assert 'value: "hunt"' in source
    # Issue #218: the picker can search StashDB performers directly; the
    # checkbox keeps local completions off the network.
    assert 'operation: "get_stashdb_performer_search"' in source
    assert '" Search StashDB"' in source
    assert "external: huntExternal" in source
    assert "icon: faCrosshairs" in source
    assert 'initialType: "hunt", huntOnly: true' in source
    assert '["all", `All ${huntCounts.all}`]' in source
    assert '["linked", `In library ${huntCounts.linked}`]' in source
    assert '["unlinked", `Not linked locally ${huntCounts.unlinked}`]' in source
    assert 'kind: "tag", label: "Include tags"' in source
    assert 'kind: "tag", label: "Exclude tags"' in source
    # Similar/Expand/Hunt share one FilterBar component (variant-gated), so
    # this markup now appears once in FilterBar's definition rather than
    # once per hand-duplicated filter panel.
    assert source.count('"Hide exact PHash matches"') == 1
    assert "function FilterBar({" in source
    assert 'React.createElement(FilterBar, {\n        variant: "similar"' in source
    assert 'React.createElement(FilterBar, {\n        variant: "hunt"' in source
    assert 'React.createElement(FilterBar, {\n        variant: "expand"' in source
    assert "hide_phash_matches: hidePhashMatches" in source
    assert '"Likely local · exact PHash"' in source
    assert '"Release date"' in source
    assert '"Preference score"' in source
    assert "data?.truncated" in source
    assert "(failure) => active && (setError(failure.message), setLoading(false))" in source
    assert 'entityType === "hunt" ? "scene" : entityType' in source


def test_recommendations_filter_bar_wired() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    # Recommendations is FilterBar's 4th call site, alongside similar/hunt/expand.
    assert 'React.createElement(FilterBar, {\n        variant: "recommendations"' in source
    assert 'const rankingOnly = variant !== "recommendations";' in source
    # get_slate gets the same filter arg shape as get_similar/get_expand —
    # FilterTokens stores {id, name} objects for chip display, so these
    # must extract the field the backend actually wants (tag name, or
    # performer/studio id as a string), not pass the object through raw.
    assert "include_tags: (filters.includeTags || []).map((item) => item.name)" in source
    assert "exclude_tags: (filters.excludeTags || []).map((item) => item.name)" in source
    assert "performer_ids: (filters.performers || []).map((item) => String(item.id))" in source
    assert "studio_ids: (filters.studios || []).map((item) => String(item.id))" in source
    assert 'gender: filters.gender || ""' in source
    # Filtered slates bypass the persistent lane+page cache rather than
    # polluting it with a filter-blind key.
    assert "const hasFilters = Boolean(filters &&" in source
    assert "if (!hasFilters) slateRequests.set(key, request);" in source
    assert 'scope: "recommendations"' in source


def test_panels_serialize_full_view_state_to_the_url() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert "function useUrlState(spec)" in source
    assert "function parseUrlState(search, spec)" in source
    # Similarity panel namespace: filters, source, exclusions, and the selected
    # source entity (type/id/label stay the shared-link params).
    for param in (
        'urlStringField("sim_source"',
        'urlStringField("sim_gender"',
        'urlBoolField("sim_favorite"',
        'urlListField("sim_include_tags"',
        'urlListField("sim_exclude_tags"',
        'urlListField("sim_performers"',
        'urlListField("sim_studios"',
        'urlNumberField("sim_min_sim"',
        'urlBoolField("sim_hide_phash"',
        'urlBoolField("sim_include_owned"',
        'param: "sim_excluded"',
    ):
        assert param in source
    assert 'urlStringField("type"' in source
    assert 'param: "id"' in source
    # Expand panel namespace.
    for param in (
        'urlStringField("exp_type"',
        'urlStringField("exp_sort"',
        'urlStringField("exp_performer"',
        'urlStringField("exp_gender"',
        'urlBoolField("exp_favorite"',
        'urlListField("exp_include_tags"',
        'urlListField("exp_exclude_tags"',
        'urlListField("exp_performers"',
        'urlListField("exp_studios"',
        'urlNumberField("exp_min_score"',
        'urlBoolField("exp_hide_phash"',
    ):
        assert param in source
    # Hunt panel namespace: performer/label stay the shared-link params.
    for param in (
        'param: "performer"',
        'urlStringField("hunt_view"',
        'urlStringField("hunt_sort"',
        'urlListField("hunt_include_tags"',
        'urlListField("hunt_exclude_tags"',
        'urlBoolField("hunt_hide_phash"',
    ):
        assert param in source
    # History lane filter and prune view/aggressiveness.
    assert 'urlStringField("hist_lane"' in source
    assert 'urlStringField("prn_view"' in source
    assert 'urlNumberField("prn_aggr"' in source
    # URL writes are batched into one history push per user action.
    assert "const search = route.toString();" in source
    assert 'history[options.replace ? "replace" : "push"]' in source


def test_score_review_view_is_a_maintenance_nav_item_and_uses_the_slate_card() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert 'value: "sentiment"' in source
    assert 'label: "Sentiment review"' in source
    assert "icon: faBalanceScale" in source
    assert "maintenance: true" in source
    assert "function ScoreReviewPanel" in source
    assert 'operation: "get_score_review"' in source
    assert 'urlPageSpec("page_sentiment")' in source
    # Sentiment review mounts through the Manage shell's MANAGE_BODIES lookup
    # rather than its own top-level lane branch (GH #150 Package 3).
    assert "sentiment: () => React.createElement(ScoreReviewPanel)," in source
    # The review surface reuses the slate card (Score, Why this?, thumbs) and
    # the pager, mirroring CuratorPage's slate rendering.
    assert (
        "React.createElement(RecommendationCard, { key: `${item.impression_id}:${item.scene_id}`"
        in source
    )
    assert "source_lane: item.lane || item.source_lane" in source
    assert "model_id: data.model_version" in source
    # The review direction and the appeal threshold are URL-backed state and
    # flow into the op.
    assert 'urlStringField("sent_order", "asc"' in source
    assert 'urlNumberField("sent_max", 0)' in source
    assert "max_appeal: threshold, order" in source
    assert 'label: "Sentiment review pages"' in source


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
    # RecommendationCard, ExternalCard, and SimilarityPanel share the same
    # progressive explanation shell and the named, unit-bearing breakdown.
    assert "function EvidenceScore({ evidenceProps, evidenceContent," in source
    assert (
        'scoreBarContent, scoreSummary, scoreLabel = "Match", scoreHeadline, '
        "scoreHeadlineValue, scoreHeadlineBar, scoreContent })" in source
    )
    assert 'React.createElement("summary", null, "Why this?")' in source
    assert 'className: "curator-evidence", ...evidenceProps' in source
    assert "evidenceProps: { onToggle: explain }" in source
    assert 'operation({ operation: "get_explanation", scene_id: item.scene_id }, 60000)' in source
    assert '"Explaining…"' in source
    assert "function ScoreBreakdown({ explanation, item })" in source
    assert "function ExplanationView({ explanation, item })" in source
    assert 'className: "curator-evidence-fingerprint"' in source
    assert 'className: "curator-fingerprint-svg"' in source
    assert "curator-metadata-status" in source
    assert "Metadata covered" in source
    assert "function fingerprintPoint(" in source
    assert 'scoreLabel: hasLaneRank ? `Rank in ${laneLabel}` : "Appeal"' in source
    assert "scoreHeadlineValue: formatAppealValue(item.appeal)" in source
    assert "function clamp01(value)" in source
    assert (
        "scoreSummary: hasLaneRank ? item.lane_value.toFixed(2) : formatAppealValue(item.appeal)"
        in source
    )
    assert 'scoreLabel: "Match"' in source or "scoreLabel: label" in source
    assert "Appeal is the model's estimate" in source
    assert '"appeal.performer_identity": "Performer match"' in source
    assert '"appeal.content_neighbor": "Similar scenes"' in source
    assert "Wildcard items are selected outside preference-derived seeds" in source


def test_external_card_actions_are_a_named_shared_component() -> None:
    """ExternalActions is the "external" action-set variant, sibling to
    Feedback's "local" variant (thumbs up/down + More menu) — Package 2's
    two-variant Card split (GH #150)."""
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")

    assert "function ExternalActions({" in source
    assert "React.createElement(ExternalActions, {" in source
    assert 'className: "curator-prune-actions"' in source
    assert '"Open on StashDB"' in source
    assert "onCopy" in source
    assert "onAddToWhisparr" in source
    assert "tagsAvailable: tags.length > 0" in source
    assert "tagsActive: tagChoices !== null" in source
    # Feedback (thumbs up/down + More menu) is the other variant; still its
    # own function, untouched by this extraction.
    assert "function Feedback({ item, onRemove, onThumbDown })" in source
    assert 'className: "curator-more-menu"' in source


def test_similarity_source_switch_visible_before_reference_is_selected() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    tabs = 'className: "btn-group curator-similar-source-tabs"'
    assert tabs in source
    # The Library/StashDB switch must be usable with no reference selected yet.
    assert f'selected && React.createElement("div", {{ {tabs}' not in source
    # Switching the entity type must not silently reset the chosen source.
    assert 'setSource("library")' not in source
    assert 'urlStringField("sim_source", "library"' in source


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
    assert module.SCHEMA_VERSION == 2


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
        "configuration": {"general": {"stashBoxes": []}},
    }
    monkeypatch.setattr(module, "_settings", lambda _payload: {})
    monkeypatch.setattr(
        module,
        "_client",
        lambda _payload: SimpleNamespace(execute=lambda *_args: runtime),
    )

    sidecar = tmp_path / "curator.sqlite3"
    now_ms = int(time.time() * 1000)
    connection = sqlite3.connect(sidecar)
    try:
        connection.row_factory = sqlite3.Row
        from curator.storage import MigrationRunner

        MigrationRunner(connection).migrate(applied_at_ms=1)
        connection.execute(
            """
            INSERT INTO curator_job(
                job_id, job_type, state, started_at_ms, heartbeat_at_ms, progress
            )
            VALUES ('job-queued', 'sync-build', 'queued', ?, NULL, NULL),
                   ('job-running', 'expand-refresh', 'running', ?, ?, 0.42)
            """,
            (now_ms - 10, now_ms - 5, now_ms),
        )
        connection.commit()
    finally:
        connection.close()

    # active_jobs comes from the worker-owned curator_job rows (decision 004),
    # not Stash's job queue: queued + running, newest first, with the
    # Stash-style description the frontend stage mapping matches.
    health = module._health({"args": {"database_path": str(sidecar)}})

    assert [job["id"] for job in health["active_jobs"]] == ["job-running", "job-queued"]
    assert health["active_job"]["id"] == "job-running"
    assert (
        health["active_jobs"][1]["description"]
        == "Running plugin task: Sync and build recommendations"
    )
    assert health["active_jobs"][0]["progress"] == 0.42


def test_task_indicator_and_compact_external_tag_rating_are_shared_ui_contracts() -> None:
    root = Path(__file__).parents[2]
    source = (root / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    css = (root / "plugin" / "stash-curator.css").read_text(encoding="utf-8")

    assert (
        "function CuratorTaskIndicator({ activeJobs, activities, failure, doneJob, tasksHref })"
        in source
    )
    assert "curator-task-indicator-done" in css
    assert "health?.active_jobs" in source
    assert "?view=manage&section=tasks" in source
    assert "curatorTaskStage(job)" in source
    assert '"Synchronizing library metadata"' in source
    assert '"Building the recommendation model"' in source
    assert '"Installing optional dependencies"' in source
    assert "curator-task-progress-indeterminate" in source
    assert "showTaskDetails" in source
    assert 'running || state === "failed" || state === "done"' in source
    assert '"No active tasks"' not in source
    # Worker-owned task status surface (decision 004): the Manage Tasks
    # section is where task feedback lives, since Stash's own Tasks tab only
    # ever sees the instant enqueue jobs.
    assert "function TasksPanel" in source
    assert 'value: "tasks"' in source
    assert "tasks: () => React.createElement(TasksPanel)" in source
    assert "Manage → Tasks" in source
    assert "curator-tasks-list" in source
    assert "Querying StashDB" not in source
    assert 'className: "curator-loading", role: "status"' in source
    assert 'className: "curator-progress"' not in source
    assert '"Rate tags & terms"' in source
    assert "RatingSection" in source
    assert "Collapse matching local tag ratings" in source
    assert "compact: true" in source
    # Tag sentiment is a single 6-stop control: "Never" is stop 0 on the same
    # range input as the 5-point spectrum (set apart visually, not pulled out
    # into a separate button), shared by every call site (compact or not).
    assert "function TagSentimentControl({ tag, value, blocked, onChange, compact = false" in source
    assert "= false, inferredValue = null })" in source
    assert 'type: "range"' in source
    assert 'min: "0"' in source
    assert 'max: "5"' in source
    assert 'step: "1"' in source
    assert "curator-sentiment-compact" in css
    assert ".curator-sentiment-input" in css
    assert ".curator-sentiment-rail" in css
    assert ".curator-sentiment-stop" in css
    assert ".curator-sentiment-thumb" in css
    assert ".curator-sentiment-model-dot" in css
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
    from curator.ranking import LanePolicy

    # Existing lanes are reported as-is; classification is never re-run on the core
    # connection, whose model tables are shadowed by the attached artifact's views.
    monkeypatch.setattr(
        LanePolicy,
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
    assert '"Rate tags & terms"' in source
    assert '"Description terms"' in source
    assert '"No description terms in the model."' in source
    assert "TERM_PREFERENCE_QUEUE_KEY" in source
    assert 'operation: "get_scene_description_tokens"' in source
    assert 'operation: "submit_term_preferences"' in source
    assert '"Configure Whisparr in plugin settings"' in source
    assert '"Retry sending to Whisparr"' in source
    assert '"Send to Whisparr"' in source


def test_entity_hook_enqueues_and_drain_imports_or_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stash entity hooks enqueue the change; the rebuild drain applies it."""
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_entity_hook", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = tmp_path / "curator.sqlite3"

    def scene() -> dict[str, object]:
        return {
            "id": "1",
            "title": "Hooked Scene",
            "details": None,
            "date": "2025-01-01",
            "rating100": None,
            "updated_at": "2026-01-01T00:00:00Z",
            "play_count": 0,
            "play_duration": 0.0,
            "play_history": [],
            "o_history": [],
            "studio": None,
            "tags": [],
            "performers": [],
            "files": [],
            "scene_markers": [],
        }

    class FakeClient:
        def execute(self, document: str, variables: object = None) -> dict[str, object]:
            assert "CuratorFindScene" in document
            return {"findScene": scene()}

    monkeypatch.setattr(module, "_settings", lambda _payload: {})
    monkeypatch.setattr(module, "_client", lambda _payload: FakeClient())

    def hook_payload(hook_type: str) -> dict[str, object]:
        return {
            "args": {
                "database_path": str(database),
                "hookContext": {"id": 1, "type": hook_type, "input": {}, "inputFields": []},
            }
        }

    updated = module._run_entity_hook(hook_payload("Scene.Update.Post"))
    assert updated == {
        "handled": True,
        "hook_type": "Scene.Update.Post",
        "entity_type": "scene",
        "entity_id": "1",
        "enqueued": True,
    }

    connection = module._open(hook_payload("Scene.Update.Post"), {})
    try:
        # The hook only records the change; the entity is not imported yet.
        assert connection.execute("SELECT count(*) FROM source_scene").fetchone()[0] == 0
        pending = connection.execute(
            "SELECT entity_type, entity_id, operation FROM pending_entity_change"
        ).fetchall()
        assert [tuple(row) for row in pending] == [("scene", "1", "upsert")]
        state = connection.execute(
            "SELECT requested_generation, published_generation FROM model_update_state"
            " WHERE singleton=1"
        ).fetchone()
        assert state["requested_generation"] > state["published_generation"]
    finally:
        connection.close()

    # The preference-rebuild drain applies the queued change.
    connection = module._open(hook_payload("Scene.Update.Post"), {})
    try:
        drained = module._drain_pending_entity_changes(
            hook_payload("Scene.Update.Post"), connection
        )
        assert drained == 1
        assert connection.execute("SELECT count(*) FROM pending_entity_change").fetchone()[0] == 0
        assert (
            connection.execute("SELECT title FROM source_scene WHERE scene_id='1'").fetchone()[0]
            == "Hooked Scene"
        )
    finally:
        connection.close()

    # A destroy after an update flips the queued operation to delete.
    destroyed = module._run_entity_hook(hook_payload("Scene.Destroy.Post"))
    assert destroyed["handled"] is True
    connection = module._open(hook_payload("Scene.Update.Post"), {})
    try:
        assert (
            connection.execute(
                "SELECT operation FROM pending_entity_change WHERE entity_type='scene'"
                " AND entity_id='1'"
            ).fetchone()[0]
            == "delete"
        )
        drained = module._drain_pending_entity_changes(
            hook_payload("Scene.Update.Post"), connection
        )
        assert drained == 1
        assert connection.execute("SELECT count(*) FROM source_scene").fetchone()[0] == 0
    finally:
        connection.close()

    # A recognized-but-unhandled hook type (tag merges are deferred) is a no-op.
    unknown = module._run_entity_hook(hook_payload("Tag.Merge.Post"))
    assert unknown == {"handled": False, "hook_type": "Tag.Merge.Post"}

    # A malformed payload never raises (hooks run inline inside Stash mutations).
    malformed = module._run_entity_hook({"args": {"hookContext": {"type": "Scene.Update.Post"}}})
    assert malformed["handled"] is False


def test_classify_lanes_reports_zero_without_writing_the_shadowed_core_table(
    tmp_path: Path,
) -> None:
    """A sparse library (no qualifying lanes) must not make the rebuild fail.

    The model build classifies into the artifact and then attaches it to the task
    connection as read-only views. Re-classifying on the core connection would try to
    write through those views and fail; the count is authoritative instead.
    """
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_classify_lanes", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from curator.events import HistoricalEventStore
    from curator.model import PreferenceModelBuilder
    from curator.storage import MigrationRunner, connect_database
    from curator.sync import SyncService
    from curator.sync.repository import SyncRepository
    from tests.integration.test_sync import SyntheticClient, _entities

    database = tmp_path / "curator.sqlite3"
    connection = connect_database(database)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    entities = _entities()
    # A fileless scene is ineligible for every lane, so the build publishes zero lanes
    # (the same state a sparse fresh library reaches).
    scene = entities["scene"][0]
    scene["files"] = []
    entities["scene"] = [scene]
    SyncService(
        SyntheticClient(entities),
        SyncRepository(connection),
        page_size=1,
        clock_ms=lambda: 1_800_000_000_000,
    ).sync(full=True)
    HistoricalEventStore(connection).rebuild()
    model = PreferenceModelBuilder(connection, clock_ms=lambda: 1_800_000_000_000).build()

    # Regression: before the fix this raised "cannot modify model_scene_lane because
    # it is a view" on the same connection the build just attached the artifact to.
    assert model.scene_count == 1
    assert connection.execute("SELECT count(*) FROM main.model_scene_lane").fetchone()[0] == 0
    assert module._classify_lanes(connection, model.model_id) == 0
    connection.close()
