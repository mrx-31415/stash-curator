from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
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
    assert "Apply recent Curator feedback" in (installed / "stash-curator.yml").read_text()
    assert "Prepare recommendation pages" in (installed / "stash-curator.yml").read_text()
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
    assert "\x01p\x021.0000" in task.stderr
    with sqlite3.connect(installed / "data" / "curator.sqlite3") as connection:
        assert connection.execute("SELECT last_error FROM model_update_state").fetchone()[0]


def test_curator_tabs_update_browser_history() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text(encoding="utf-8")
    assert "const routeLocation = useLocation();" in source
    assert "history.push({ pathname: routeLocation.pathname, search: route.toString() });" in source
    assert "onClick: () => openView(option.value)" in source


def test_taste_profile_uses_fixed_durable_tag_sentiment_control() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'value: "taste"' in source
    assert 'operation: "get_taste_profile"' in source
    assert 'operation: "submit_tag_preferences"' in source
    assert "TAG_PREFERENCE_QUEUE_KEY" in source
    assert '[-1, "Strong dislike"]' in source
    assert '[1, "Strong like"]' in source
    assert '"Clear answer"' in source
    assert '"Search taste profile tags"' in source
    assert '"Filter taste profile tags"' in source
    assert 'value: "answered"' in source
    assert '"Needs answer"' in source
    assert '"Sort taste profile"' in source
    assert 'value: "confidence"' in source
    assert 'value: "scenes"' in source
    assert 'if (sort !== "suggested")' in source


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
    assert "submitTagPreference(tag.tag_id, value);" in source


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


def test_external_scene_cards_can_rate_matching_local_tags() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "stash-curator.js").read_text()

    assert 'operation: "get_external_tag_choices"' in source
    assert '"Rate matching local tags"' in source
    assert '"No matching local tags."' in source
    assert "submitTagPreference(tag.tag_id, value);" in source


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

    assert "function Pager({ page, hasMore, loading, onPage, label })" in source
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


def test_backend_module_loads_without_starting(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2] / "plugin" / "backend.py"
    spec = importlib.util.spec_from_file_location("curator_plugin_backend", backend)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA_VERSION == 1


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

    assert module._classify_lanes(connection, SimpleNamespace(model_id="model", reused=True)) == 3


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


def test_model_tasks_prepare_recommendation_pages() -> None:
    source = (Path(__file__).parents[2] / "plugin" / "backend.py").read_text(encoding="utf-8")

    assert source.count("_prepare_lanes(connection, model.model_id)") == 2
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
