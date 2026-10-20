"""Exercise the native Stash player with synthetic scenes; block every live mutation."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
CLIP = Path(__file__).with_name("fixtures") / "roulette.mp4"


def _install(page: Page, base_url: str, count: int = 32, rating_type: str = "stars") -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
    page.add_init_script(
        # Avoid unsupported wake locks; slow the short fixture until advancement is requested.
        "delete Navigator.prototype.wakeLock;"
        "document.addEventListener('play', e => {"
        "if (e.target instanceof HTMLVideoElement) e.target.playbackRate = .1; }, true);"
    )
    scenes = [
        {
            "__typename": "Scene",
            "id": str(900000 + i),
            "title": f"Roulette fixture {i + 1}",
            "code": "",
            "details": "",
            "director": "",
            "urls": [],
            "date": None,
            "rating100": None,
            "o_counter": 0,
            "organized": False,
            "interactive": False,
            "interactive_speed": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "resume_time": 3,
            "last_played_at": None,
            "play_duration": 0,
            "play_count": 0,
            "play_history": [],
            "o_history": [],
            "custom_fields": {},
            "captions": [],
            "files": [
                {
                    "__typename": "VideoFile",
                    "id": str(900000 + i),
                    "path": "/synthetic/roulette.mp4",
                    "size": 2000,
                    "mod_time": "2026-01-01T00:00:00Z",
                    "duration": 10,
                    "video_codec": "h264",
                    "audio_codec": "",
                    "width": 160,
                    "height": 90,
                    "frame_rate": 5,
                    "bit_rate": 1000,
                    "fingerprints": [],
                }
            ],
            "paths": {
                "__typename": "ScenePathsType",
                "screenshot": base_url + "/roulette-test/poster.svg",
                "preview": None,
                "stream": base_url + "/roulette-test/stream",
                "webp": None,
                "vtt": None,
                "sprite": None,
                "funscript": None,
                "interactive_heatmap": None,
                "caption": None,
            },
            "scene_markers": [],
            "galleries": [],
            "studio": None,
            "groups": [],
            "tags": [],
            "performers": [],
            "stash_ids": [],
            "sceneStreams": [
                {
                    "__typename": "SceneStreamEndpoint",
                    "url": base_url + "/roulette-test/stream",
                    "mime_type": "video/mp4",
                    "label": "MP4",
                }
            ],
        }
        for i in range(count)
    ]
    by_id = {scene["id"]: scene for scene in scenes}
    injection = """
      const fixtures = FIXTURES;
      window.__rouletteEvents = [];
      window.__rouletteFeedback = [];
      window.__rouletteSounds = [];
      window.__roulettePlaybackStarts = [];
      document.addEventListener("playing", event => {
        if (event.target instanceof HTMLVideoElement &&
            event.target.closest(".curator-roulette-player")) {
          window.__roulettePlaybackStarts.push(event.target.currentTime);
        }
      }, true);
      window.__rouletteSoundFactory = createRouletteSound;
      createRouletteSound = (audio) => {
        const sound = window.__rouletteSoundFactory(audio);
        for (const name of ["gather", "spin", "progress", "tick", "land", "reveal",
                            "mute", "stop"]) {
          const original = sound[name];
          sound[name] = function(...args) {
            window.__rouletteSounds.push({name, args, at: audio.currentTime});
            return original.apply(this, args);
          };
        }
        return sound;
      };
      enqueue = (entry) => window.__rouletteEvents.push(entry);
      getPluginSettings = async () => ({});
      getStashBoxEndpoints = async () => [];
      operation = async (request) => {
        if (request.operation === "get_config") return {config: {moods: []}};
        if (request.operation === "submit_feedback") {
          window.__rouletteFeedback.push(request);
          return {};
        }
        if (request.operation !== "get_slate") return {};
        const items = fixtures.filter(s => !window.__rouletteEmpty &&
          !request.exclude_scene_ids.includes(s.id))
          .slice(0, request.count).map((s, i) => ({ scene_id: s.id, position: i }));
        return { lane: "best_bets", page_size: 24, items, model_id: "fixture-model",
          impression_id: "fixture-refill", total: items.length };
      };
      Api.patch.before("ScenePlayer", (props, ...args) => [props, ...args, { companion: true }]);
      Api.patch.instead("ScenePlayer", function(props, ...args) {
        const next = args.pop();
        return React.createElement(React.Fragment, null, next.call(this, props, ...args),
          React.createElement("span", { "data-roulette-companion": "true" }));
      });
      Api.register.route("/plugins/curator-roulette-test", function() {
        const [session, setSession] = React.useState(null);
        const [settings, setSettings] = React.useState(false);
        const close = React.useCallback(() => setSession(null), []);
        return React.createElement(React.Fragment, null,
          React.createElement("button", { id: "open-settings",
            onClick: () => setSettings(!settings) }, "Settings"),
          settings && React.createElement(SettingsPanel, {}),
          React.createElement("button", { id: "launch-roulette", onClick: () => {
            const slate = { lane: "best_bets", page_size: 24, model_id: "fixture-model",
              impression_id: "fixture-first", items: fixtures.slice(0, 24)
                .map((s, i) => ({ scene_id: s.id, position: i })) };
            window.__rouletteSession = createRouletteSession(slate, slate.items, {},
              new Map(fixtures.map(s => [s.id, s])));
            setSession(window.__rouletteSession);
          } }, "Roulette"),
          React.createElement("div", { className: "curator-page", style: {
            display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12,
          } }, fixtures.slice(0, 6).map(scene => React.createElement("article", {
            key: scene.id, "data-endless-item": scene.id,
          }, React.createElement("img", { src: scene.paths.screenshot, alt: "",
            style: { width: "100%", aspectRatio: "16 / 9" } })))),
          session && React.createElement(RoulettePlayer, { session, onClose: close }));
      });
    """.replace("FIXTURES", json.dumps(scenes))
    source = (ROOT / "plugin/stash-curator.js").read_text()
    source = source.removesuffix("})();\n") + injection + "\n})();\n"
    page.route(
        "**/plugin/stash-curator/javascript*",
        lambda route: route.fulfill(content_type="application/javascript", body=source),
    )
    page.route(
        "**/plugin/stash-curator/css*",
        lambda route: route.fulfill(
            content_type="text/css", body=(ROOT / "plugin/stash-curator.css").read_text()
        ),
    )
    page.route(
        "**/roulette-test/stream*",
        lambda route: route.fulfill(content_type="video/mp4", body=CLIP.read_bytes()),
    )
    page.route(
        "**/roulette-test/poster.svg",
        lambda route: route.fulfill(
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90">'
            '<rect width="160" height="90" fill="#69a9c8"/>'
            '<circle cx="120" cy="24" r="12" fill="#ffe1a0"/>'
            '<path d="M0 90V70L45 28 100 90M65 90L125 42 160 75V90" fill="#375e54"/>'
            '<text x="8" y="82" fill="white" font-size="10">16:9 preview</text></svg>',
        ),
    )

    def graphql(route: Route) -> None:
        payload = route.request.post_data_json
        query = payload.get("query", "")
        variables = payload.get("variables", {})
        if payload.get("operationName") == "Configuration":
            response = route.fetch()
            data = response.json()
            # Keep native controls deterministic without changing the host's settings.
            if "ui" in data["data"]["configuration"]:
                data["data"]["configuration"]["ui"]["ratingSystemOptions"] = {
                    "type": rating_type,
                    "starPrecision": "full",
                }
            route.fulfill(response=response, json=data)
        elif "RouletteScenes" in query:
            route.fulfill(
                json={"data": {key: by_id.get(value) for key, value in variables.items()}}
            )
        elif "FindScene" in query and str(variables.get("id")) in by_id:
            route.fulfill(json={"data": {"findScene": by_id[str(variables["id"])]}})
        elif query.lstrip().startswith("mutation"):
            # The app may persist native activity/volume settings; nothing leaves this test.
            if "sceneUpdate" in query and str(variables.get("input", {}).get("id")) in by_id:
                scene = by_id[str(variables["input"]["id"])]
                scene["rating100"] = variables["input"]["rating100"]
                route.fulfill(json={"data": {"sceneUpdate": scene}})
            elif "sceneAddO" in query and str(variables.get("id")) in by_id:
                scene = by_id[str(variables["id"])]
                scene["o_counter"] += 1
                scene["o_history"].append("2026-01-01T00:00:00Z")
                route.fulfill(
                    json={
                        "data": {
                            "sceneAddO": {
                                "__typename": "HistoryMutationResult",
                                "history": scene["o_history"],
                            }
                        }
                    }
                )
            elif "sceneSaveActivity" in query:
                route.fulfill(json={"data": {"sceneSaveActivity": True}})
            elif "sceneIncrementPlayCount" in query:
                route.fulfill(json={"data": {"sceneIncrementPlayCount": 1}})
            elif "sceneAddPlay" in query:
                route.fulfill(
                    json={
                        "data": {
                            "sceneAddPlay": {
                                "__typename": "HistoryMutationResult",
                                "history": ["2026-01-01T00:00:00Z"],
                            }
                        }
                    }
                )
            else:
                route.fulfill(json={"data": {}})
        else:
            route.continue_()

    page.route("**/graphql", graphql)
    page.goto(base_url + "/plugins/curator-roulette-test")
    page.locator("#launch-roulette").wait_for(timeout=30000)
    return errors


def test_roulette_animation_settings_and_simple_mode(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=4)
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#open-settings").click()
    normal = page.locator(".curator-settings-panel").get_by_role("switch", name="Animate roulette")
    expect(normal).to_have_attribute("aria-checked", "true")
    normal.click()
    expect(normal).to_have_attribute("aria-checked", "false")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    expect(stage).to_have_attribute("data-animated", "false")
    expect(page.locator(".curator-roulette-spinner")).to_be_hidden()
    expect(page.get_by_role("group", name="Scene actions")).to_be_visible()
    assert page.evaluate("__rouletteSounds.length") == 0
    first = page.evaluate("__rouletteSession.history[0].origin.scene_id")
    page.wait_for_function("document.querySelector('video').currentTime >= .5")
    saved_position = page.locator(".curator-roulette-player video").evaluate(
        "video => { video.pause(); return video.currentTime; }"
    )
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    assert page.evaluate("__rouletteSession.index") == 1
    assert abs(page.evaluate("__rouletteSession.history[0].time") - saved_position) < 0.1
    assert page.evaluate("__rouletteSession.history[1].origin.scene_id") != first
    page.get_by_role("button", name="Back", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    assert page.evaluate("__rouletteSession.index") == 0
    assert page.evaluate("__rouletteSession.history[0].origin.scene_id") == first
    assert abs(page.evaluate("__rouletteSession.history[0].time") - saved_position) < 0.1
    page.locator(".curator-roulette-player video").evaluate("video => video.pause()")
    page.mouse.move(20, 400)
    assert page.evaluate("__rouletteSounds.length") == 0

    gear = page.get_by_role("button", name="Roulette settings", exact=True)
    gear.click()
    stage.evaluate("node => node.classList.add('curator-roulette-quiet')")
    expect(page.locator(".curator-roulette-hud")).to_have_css("opacity", "1")
    popup = page.locator(".curator-roulette-settings").get_by_role(
        "switch", name="Animate roulette"
    )
    expect(popup).to_have_attribute("aria-checked", "false")
    popup.click()
    expect(normal).to_have_attribute("aria-checked", "true")
    expect(stage).to_have_attribute("data-animated", "false")
    assert popup.evaluate("node => node.getBoundingClientRect().right <= innerWidth")
    popup.press("Escape")
    expect(popup).to_be_hidden()
    expect(page.locator(".curator-roulette-dialog")).to_be_visible()
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "spinning", timeout=15000)
    expect(stage).to_have_attribute("data-animated", "true")
    gear.click()
    popup.click()
    expect(normal).to_have_attribute("aria-checked", "false")
    expect(stage).to_have_attribute("data-animated", "true")
    popup.press("Escape")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    assert page.evaluate("__rouletteSounds.some(cue => cue.name === 'land')")
    sound_offset = page.evaluate("__rouletteSounds.length")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    expect(stage).to_have_attribute("data-animated", "false")
    assert not page.evaluate(
        "start => __rouletteSounds.slice(start).some("
        "cue => ['gather', 'spin', 'tick', 'land', 'reveal'].includes(cue.name))",
        arg=sound_offset,
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    page.reload()
    page.locator("#open-settings").click()
    expect(normal).to_have_attribute("aria-checked", "false")
    page.locator("#launch-roulette").click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    expect(stage).to_have_attribute("data-animated", "false")
    assert page.evaluate("__rouletteSounds.length") == 0
    page.get_by_role("button", name="Exit", exact=True).click()
    assert not errors


def test_roulette_simple_fade_keeps_letterboxing(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    page.add_init_script("localStorage.setItem('stash-curator:roulette-animation:v1', 'false')")
    errors = _install(page, base_url, count=3)
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#launch-roulette").click()
    page.wait_for_function("""() => {
      const stage = document.querySelector('.curator-roulette-stage');
      if (stage?.dataset.phase !== 'revealing') return false;
      const animation = stage.querySelector('.curator-roulette-player').getAnimations()[0];
      if (!animation) return false;
      animation.pause(); return true;
    }""")
    frames = page.locator(".curator-roulette-player").evaluate("""host => {
      const animation = host.getAnimations()[0], video = host.querySelector('video');
      return [0, 110, 219].map(time => {
        animation.currentTime = time;
        return {opacity:Number(getComputedStyle(host).opacity),
          fit:getComputedStyle(video).objectFit, background:getComputedStyle(host).backgroundColor,
          width:host.getBoundingClientRect().width, height:host.getBoundingClientRect().height};
      });
    }""")
    assert frames[0]["opacity"] == 0
    assert 0 < frames[1]["opacity"] < frames[2]["opacity"] <= 1
    assert all(frame["fit"] == "contain" for frame in frames)
    assert all(frame["background"] == "rgb(6, 6, 9)" for frame in frames)
    assert all(frame["width"] == 390 and frame["height"] == 844 for frame in frames)
    page.locator(".curator-roulette-player").evaluate("host => host.getAnimations()[0].finish()")
    expect(page.locator(".curator-roulette-stage")).to_have_attribute("data-phase", "playing")
    expect(page.locator("video")).to_have_css("object-fit", "contain")
    expect(page.locator(".curator-roulette-player")).to_have_css("opacity", "1")
    page.get_by_role("button", name="Exit", exact=True).click()
    assert not errors


@pytest.mark.parametrize("rating_type", ["stars", "decimal"])
def test_roulette_scene_actions_and_statistics(page: Page, base_url: str, rating_type: str) -> None:
    from playwright.sync_api import expect

    mutations = []
    page.on(
        "request",
        lambda request: (
            mutations.append(request.post_data_json)
            if request.url.endswith("/graphql")
            and request.method == "POST"
            and request.post_data_json.get("query", "").lstrip().startswith("mutation")
            else None
        ),
    )
    errors = _install(page, base_url, count=3, rating_type=rating_type)
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    actions = page.get_by_role("group", name="Scene actions")
    expect(actions).to_be_visible()
    page.get_by_role("button", name="Next", exact=True).hover()
    assert page.get_by_role("button", name="Next", exact=True).evaluate(
        "n => getComputedStyle(n).transform === 'none'"
    )
    scene_id = page.evaluate("__rouletteSession.history[0].origin.scene_id")
    page.get_by_role("button", name="Useful", exact=True).click()
    expect(actions.get_by_role("status")).to_have_text("Saved")
    page.get_by_role("button", name="Not for me", exact=True).click()
    page.wait_for_function("__rouletteFeedback.length === 2")
    assert page.evaluate("__rouletteFeedback.map(r => r.entries[0])") == [
        {**entry, "scene_id": scene_id, "impression_id": "fixture-first", "feedback_type": kind}
        for entry, kind in zip(
            page.evaluate("__rouletteFeedback.map(r => r.entries[0])"),
            ["thumb_up", "thumb_down"],
            strict=True,
        )
    ]
    o_button = page.get_by_role("button", name="Increment O counter")
    expect(o_button).to_have_text("0")
    o_button.click()
    expect(o_button).to_have_text("1")
    expect(page.locator(".curator-roulette-o-burst i")).to_have_count(3)
    assert page.get_by_role("button", name="Not for me").evaluate(
        "n => n.closest('.curator-feedback').dataset.reaction === 'thumb_down'"
    )
    rating = page.locator(".curator-roulette-rating")
    if rating_type == "stars":
        rating.get_by_role("button").nth(3).click()
        o_button.focus()
        expect(rating.locator(".star-rating-number")).to_have_text("4")
    else:
        rating.locator(".edit-rating-button").click()
        rating.locator("input").fill("8.0")
        o_button.focus()
        expect(rating).to_contain_text("8.0")
    assert any(
        r["variables"].get("input") == {"id": scene_id, "rating100": 80}
        for r in mutations
        if "sceneUpdate" in r["query"]
    )
    # Make the native activity threshold independent of this host's configuration.
    page.evaluate("""() => { const player = PluginApi.utils.InteractiveUtils.getPlayer();
      player.trackActivity().minimumPlayPercent = 0; player.trackActivity().setEnabled(true); }""")
    page.wait_for_function(
        "document.querySelector('.curator-roulette-player video').currentTime >= .5"
    )
    page.locator("video").evaluate("v => v.pause()")
    page.wait_for_function("document.querySelector('video').paused")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    saved = [
        r["variables"]
        for r in mutations
        if "sceneSaveActivity" in r["query"] and r["variables"].get("id") == scene_id
    ]
    assert any(r["playDuration"] > 0 and r["resume_time"] > 0 for r in saved)
    counts = [
        r
        for r in mutations
        if ("sceneIncrementPlayCount" in r["query"] or "sceneAddPlay" in r["query"])
        and r["variables"].get("id") == scene_id
    ]
    assert len(counts) == 1
    link = page.get_by_role("link", name="Open scene")
    current_id = page.evaluate("__rouletteSession.history[1].origin.scene_id")
    expect(link).to_have_attribute("href", f"/scenes/{current_id}")
    # Suppress navigation; the real click handler must still pause and preserve history.
    link.evaluate("n => n.addEventListener('click', e => e.preventDefault())")
    link.click()
    assert page.locator("video").evaluate("v => v.paused")
    assert page.evaluate("__rouletteSession.index") == 1
    assert actions.evaluate("n => n.getBoundingClientRect().right <= innerWidth")
    page.get_by_role("button", name="Exit", exact=True).click()
    assert not errors


def test_roulette_sound_build_resolution_and_mute(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=3)
    intro = page.evaluate("""async () => {
      const audio = new OfflineAudioContext(1, 44100 * 2.4, 44100);
      const sound = __rouletteSoundFactory(audio);
      sound.gather(1.5);
      const cancellation = audio.suspend(1.8), rendering = audio.startRendering();
      await cancellation; sound.stop(); await audio.resume();
      const samples = (await rendering).getChannelData(0);
      const peak = (from, to) => samples.slice(from * 44100, to * 44100)
        .reduce((maximum, value) => Math.max(maximum, Math.abs(value)), 0);
      const body = samples.slice(0, 1.6 * 44100);
      return {early:peak(.05, .4), late:peak(1.1, 1.6), swoosh:peak(1.65, 1.75),
        rms:Math.sqrt(body.reduce((sum, value) => sum + value * value, 0) / body.length),
        peak:peak(0, 2.4), tail:peak(2, 2.4)};
    }""")
    assert intro["early"] > 0.01 and intro["late"] > 0.01
    assert intro["swoosh"] > 0.001
    assert intro["rms"] > 0.015
    assert intro["peak"] < 0.5 and intro["tail"] == 0
    rendered = page.evaluate("""async () => {
      const audio = new OfflineAudioContext(1, 44100 * 8, 44100);
      const sound = __rouletteSoundFactory(audio);
      sound.spin(2.6);
      sound.progress(0);
      const steps = [.65, 1.3, 1.95, 2.6].map(time => audio.suspend(time));
      const reveal = audio.suspend(3.25);
      const rendering = audio.startRendering();
      for (let i = 0; i < steps.length; i++) {
        await steps[i]; sound.progress((i + 1) / 4);
        if (i === steps.length - 1) sound.land();
        await audio.resume();
      }
      await reveal; sound.reveal(); await audio.resume();
      const buffer = await rendering, samples = buffer.getChannelData(0);
      const peak = (from, to) => samples.slice(from * 44100, to * 44100)
        .reduce((maximum, value) => Math.max(maximum, Math.abs(value)), 0);
      const rms = (from, to) => {
        const part = samples.slice(from * 44100, to * 44100);
        return Math.sqrt(part.reduce((sum, value) => sum + value * value, 0) / part.length);
      };
      return {spin:peak(.2, 2.5), early:peak(.8, 1.2), late:peak(2.1, 2.5),
        landing:peak(2.6, 3.1), landingBody:rms(2.6, 3),
        sustainedBody:rms(3, 3.4), buildBody:rms(2.1, 2.5),
        firstBeat:rms(2.68, 2.78), secondBeat:rms(2.91, 3.01),
        reveal:peak(3.3, 3.6), decay:rms(3.6, 4), lateDecay:rms(4.4, 4.8),
        tail:peak(6.8, 8), peak:peak(0, 8)};
    }""")
    assert all(rendered[phase] > 0.005 for phase in ["spin", "landing", "reveal"])
    assert rendered["peak"] < 0.95
    assert rendered["landingBody"] > max(0.08, rendered["buildBody"] * 2)
    assert min(rendered["firstBeat"], rendered["secondBeat"]) > 0.06
    assert rendered["sustainedBody"] > 0.006
    assert rendered["late"] > rendered["early"] * 1.5
    assert rendered["decay"] > 0.001
    assert 0 < rendered["lateDecay"] < rendered["decay"]
    assert rendered["tail"] == 0
    # Reproduce an intro cue racing the audio context's startup.
    page.evaluate("""() => {
      const NativeAudio = window.AudioContext;
      window.AudioContext = class extends NativeAudio {
        get state() {
          return window.__rouletteSession?.phase === 'assembling' && !this.introResumed
            ? 'suspended' : super.state;
        }
        resume() {
          if (window.__rouletteSession?.phase === 'assembling') {
            this.introResumed = true; window.__introAudioResumed = true;
          }
          return super.resume();
        }
      };
    }""")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "spinning", timeout=15000)
    assert page.evaluate("window.__introAudioResumed === true")
    assert page.evaluate("__rouletteSounds.some(c => c.name === 'gather')")
    page.get_by_role("button", name="Mute", exact=True).click()
    muted_at = page.evaluate("__rouletteSounds.length")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    assert not page.evaluate(
        "start => __rouletteSounds.slice(start).some("
        "c => ['land', 'reveal', 'tick'].includes(c.name))",
        arg=muted_at,
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    page.locator("#launch-roulette").click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    unmute = page.locator(".curator-roulette-hud").get_by_role("button", name="Unmute", exact=True)
    expect(unmute).to_have_attribute("aria-pressed", "true")
    unmute.click()
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    assert page.evaluate(
        "start => __rouletteSounds.slice(start).some(c => c.name === 'land')", arg=muted_at
    )
    resolution = page.evaluate("""() => {
      const events = __rouletteSounds, landing = events.findLastIndex(c => c.name === 'land');
      const progress = events.slice(0, landing).findLast(c => c.name === 'progress');
      return {progress:progress.args[0], interruptions:events.slice(landing + 2).filter(
        c => c.name === 'stop' && c.at < events[landing].at + 4),
        landing:events[landing].at, cues:events.slice(landing)};
    }""")
    assert resolution["progress"] == 1 and not resolution["interruptions"], resolution
    expect(
        page.locator(".curator-roulette-hud").get_by_role("button", name="Mute", exact=True)
    ).to_be_visible()
    assert page.locator(".curator-roulette-player video").evaluate("video => !video.muted")
    # Once playback is ready, the native mute control still updates Roulette.
    page.locator(".curator-roulette-player video").evaluate("video => { video.muted = true; }")
    expect(
        page.locator(".curator-roulette-hud").get_by_role("button", name="Unmute", exact=True)
    ).to_be_visible()
    page.locator(".curator-roulette-player video").evaluate("video => { video.muted = false; }")
    expect(
        page.locator(".curator-roulette-hud").get_by_role("button", name="Mute", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "spinning", timeout=15000)
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable:true, value:true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    assert page.evaluate("__rouletteSounds.at(-1).name") == "stop"
    page.get_by_role("button", name="Exit", exact=True).click()
    expect(page.locator(".curator-roulette-dialog")).to_have_count(0)
    assert not errors


def test_native_roulette_transitions(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "assembling")
    expect(page.locator(".curator-roulette-flight")).to_have_count(24)
    assert page.locator(".curator-roulette-flight img").first.evaluate(
        "node => getComputedStyle(node).padding === '0px'"
    )
    assert page.evaluate(
        """() => {
          const tile = document.querySelector('.curator-page [data-endless-item]');
          const source = tile.querySelector('img').getBoundingClientRect();
          const index = __rouletteSession.slots.findIndex(
            entry => entry.origin.scene_id === tile.dataset.endlessItem);
          if (index < 0) return false;
          const card = document.querySelectorAll('.curator-roulette-flight')[index];
          const frame = card.getAnimations()[0].effect.getKeyframes()[0];
          const matrix = new DOMMatrix(frame.transform), width = parseFloat(card.style.width);
          return Math.abs(matrix.e + width / 2 - source.left - source.width / 2) < 1 &&
            Math.abs(matrix.a * width - source.width) < 1;
        }"""
    )
    expect(stage).to_have_attribute("data-phase", "spinning", timeout=20000)
    assert page.locator(".curator-roulette-aura i").count() == 3
    assert page.locator(".curator-roulette-aura i").first.evaluate(
        "n => getComputedStyle(n).animationName === 'curator-roulette-converge'"
    )
    expect(page.locator(".curator-roulette-flight")).to_have_count(0)
    assert page.locator(".curator-roulette-wheel-wrap svg").evaluate(
        "node => getComputedStyle(node).padding === '0px'"
    )
    expect(page.locator(".curator-roulette-wedge")).to_have_count(24)
    assert page.locator(".curator-roulette-wheel-wrap").evaluate(
        "node => parseFloat(getComputedStyle(node).width) > innerWidth * 2"
    )
    assert page.locator(".curator-roulette-wedge").evaluate_all(
        "nodes => nodes.every(node => node.tagName === 'rect')"
    )
    assert page.locator(".curator-roulette-wheel-wrap image").evaluate_all(
        "nodes => nodes.every(node => Math.abs("
        "Number(node.getAttribute('width')) / Number(node.getAttribute('height')) - 16 / 9"
        ") < .001)"
    )
    expect(stage).to_have_attribute("data-phase", "celebrating", timeout=15000)
    expect(page.locator(".curator-roulette-slot.winning")).to_have_count(1)
    assert page.locator(".curator-roulette-hit").evaluate("node => node.getAnimations().length > 0")
    page.wait_for_function("window.__rouletteSession.phase === 'revealing'", timeout=30000)
    assert page.evaluate(
        """() => {
          const entry = __rouletteSession.history[__rouletteSession.index];
          const image = document.querySelectorAll('.curator-roulette-wheel-wrap image')[entry.slot];
          const wheel = document.querySelector('.curator-roulette-wheel-wrap');
          const matrix = image.getScreenCTM();
          const width = Number(image.getAttribute('width'));
          return Math.abs(matrix.b) < .001 && Math.abs(matrix.c) < .001 && matrix.a > 0 &&
            width * parseFloat(getComputedStyle(wheel).width) / 600 >= 350;
        }"""
    )
    video = page.locator(".curator-roulette-player video").element_handle()
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    sounds = page.evaluate("__rouletteSounds.map(cue => cue.name)")
    assert all(name in sounds for name in ["gather", "spin", "tick", "land", "reveal"])
    assert sounds.index("spin") < sounds.index("land") < sounds.index("reveal")
    assert page.evaluate("__roulettePlaybackStarts[0] < 1")
    assert video.evaluate("node => node.isConnected")
    expect(page.locator("[data-roulette-companion]")).to_have_count(1)
    page.wait_for_function("document.querySelector('video').currentTime >= .4")
    saved_position = page.locator("video").evaluate(
        "video => { video.pause(); return video.currentTime; }"
    )
    first = page.evaluate("__rouletteSession.history[0].origin.scene_id")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    assert video.evaluate("node => node.isConnected")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=30000)
    expect(page.locator(".curator-roulette-flight")).to_have_count(0)
    expect(page.locator(".curator-roulette-hit")).to_have_count(0)
    assert page.evaluate("__rouletteSession.history[1].origin.scene_id") != first
    outgoing = page.locator(".curator-roulette-player video").element_handle()
    page.get_by_role("button", name="Back", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    assert outgoing.evaluate("node => node.isConnected")
    expect(stage).to_have_attribute("data-phase", "rewinding")
    assert page.locator(".curator-roulette-wheel-wrap svg").evaluate(
        """node => {
          const frames = node.getAnimations()[0].effect.getKeyframes();
          const angles = frames.map(frame => parseFloat(frame.transform.slice(7)));
          return Math.abs(angles[1] - angles[0]) <= 180;
        }"""
    )
    expect(stage).to_have_attribute("data-phase", "revealing", timeout=30000)
    page.wait_for_function(
        "saved => Math.abs(document.querySelector('video').currentTime - saved) < .1",
        arg=saved_position,
    )
    page.locator("video").evaluate("video => video.pause()")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=5000)
    assert (
        page.evaluate("__rouletteSession.history[__rouletteSession.index].origin.scene_id") == first
    )
    assert abs(page.locator("video").evaluate("video => video.currentTime") - saved_position) < 0.1
    page.mouse.move(20, 400)
    page.get_by_role("button", name="Fullscreen", exact=True).click()
    page.wait_for_function(
        "document.fullscreenElement?.classList.contains('curator-roulette-stage')"
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    expect(page.locator(".curator-roulette-dialog")).to_have_count(0)
    page.wait_for_function("!document.fullscreenElement")
    expect(page.locator("#launch-roulette")).to_be_focused()
    events = page.evaluate("__rouletteEvents")
    assert events and all(event["origin"] == "curator" for event in events)
    assert all(event["model_id"] == "fixture-model" for event in events)
    assert not errors, errors


def test_mobile_roulette_continuous_rounds_and_cancel(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=3)
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    assert page.locator(".curator-roulette-aura").evaluate(
        "n => getComputedStyle(n).display === 'none'"
    )
    page.locator(".curator-roulette-hud").get_by_role("button", name="Mute", exact=True).click()
    expect(
        page.locator(".curator-roulette-hud").get_by_role("button", name="Unmute", exact=True)
    ).to_have_attribute("aria-pressed", "true")
    for _ in range(2):
        page.get_by_role("button", name="Next", exact=True).click()
        expect(stage).to_have_attribute("data-phase", "playing")
    assert page.evaluate("__rouletteSession.seen.size") == 3
    for _ in range(4):
        page.get_by_role("button", name="Next", exact=True).click()
        expect(stage).to_have_attribute("data-phase", "playing")
    ids = page.evaluate("__rouletteSession.history.map(entry => entry.origin.scene_id)")
    assert len(ids) == 7
    assert len(set(ids[:3])) == len(set(ids[3:6])) == 3
    assert all(first != second for first, second in pairwise(ids))
    page.get_by_role("button", name="Back", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    assert page.evaluate("__rouletteSession.index") == 5
    assert page.locator(".curator-roulette-wheel-wrap svg").evaluate(
        "node => node.getAnimations().length === 0"
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    page.emulate_media(reduced_motion="no-preference")
    page.locator("#launch-roulette").click()
    expect(stage).to_have_attribute("data-phase", "spinning")
    expect(
        page.locator(".curator-roulette-hud").get_by_role("button", name="Unmute", exact=True)
    ).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Escape")
    expect(page.locator(".curator-roulette-dialog")).to_have_count(0)
    page.wait_for_timeout(4200)
    assert page.evaluate("__rouletteSession.closed")
    assert page.locator("video").count() == 0
    assert not errors, errors


def test_roulette_back_cancel_during_rewind(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=3)
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    outgoing = page.locator("video").element_handle()
    page.evaluate("__rouletteSession.pool = []")
    page.emulate_media(reduced_motion="no-preference")
    page.get_by_role("button", name="Back", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    assert outgoing.evaluate("node => node.isConnected")
    expect(stage).to_have_attribute("data-phase", "rewinding")
    assert page.evaluate(
        """() => {
          const entry = __rouletteSession.history[__rouletteSession.index];
          return !!entry.frame && entry.slots[entry.slot].frame === entry.frame;
        }"""
    )
    expect(page.get_by_role("button", name="Back", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Next", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Exit", exact=True).click()
    page.wait_for_timeout(1500)
    assert page.evaluate("__rouletteSession.closed")
    assert page.evaluate("__rouletteSession.index") == 1
    assert page.locator("video").count() == 0
    expect(page.locator("#launch-roulette")).to_be_focused()
    assert not errors, errors


def test_roulette_single_scene_continues_and_empty_pool_recovers(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=1)
    page.emulate_media(reduced_motion="reduce")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    for _ in range(3):
        page.get_by_role("button", name="Next", exact=True).click()
        expect(stage).to_have_attribute("data-phase", "playing")
        assert page.locator("video").evaluate("v => v.currentTime < 1")
    assert page.evaluate("__rouletteSession.history.length") == 4
    page.evaluate("window.__rouletteEmpty = true")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "exhausted")
    expect(page.get_by_role("status")).to_contain_text("No recommendations qualify")
    page.evaluate("window.__rouletteEmpty = false")
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    assert page.evaluate("__rouletteSession.history.length") == 5
    page.get_by_role("button", name="Exit", exact=True).click()
    assert not errors, errors


def test_roulette_overlays_hide_and_wake(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=3)
    page.emulate_media(reduced_motion="reduce")
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    page.mouse.move(20, 400)
    hidden = "getComputedStyle(document.querySelector('.curator-roulette-hud')).opacity === '0'"
    page.wait_for_function(hidden)
    assert page.locator(".curator-roulette-status").evaluate(
        "node => getComputedStyle(node).opacity === '0'"
    )
    assert page.get_by_role("button", name="Next", exact=True).evaluate(
        "node => getComputedStyle(node).pointerEvents === 'none'"
    )
    stage.dispatch_event("pointerdown", {"pointerType": "touch"})
    page.wait_for_function("!(" + hidden + ")")
    page.wait_for_function(hidden)
    page.mouse.move(40, 400)
    page.wait_for_function("!(" + hidden + ")")
    page.locator("video").evaluate("video => video.pause()")
    page.wait_for_timeout(3000)
    assert page.locator(".curator-roulette-hud").evaluate(
        "node => getComputedStyle(node).opacity === '1'"
    )
    page.keyboard.press("Tab")
    page.get_by_role("button", name="Next", exact=True).focus()
    page.locator("video").evaluate("video => video.play()")
    page.wait_for_timeout(3000)
    expect(page.get_by_role("button", name="Next", exact=True)).to_be_focused()
    assert page.locator(".curator-roulette-hud").evaluate(
        "node => getComputedStyle(node).opacity === '1'"
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    assert not errors, errors


def test_roulette_retry_completion_and_return_cancel(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url, count=20)
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")

    def unavailable(route: Route) -> None:
        route.abort()

    page.route("**/roulette-test/stream*", unavailable)
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "error", timeout=15000)
    expect(page.locator(".curator-roulette-wedge")).to_have_count(16)
    page.unroute("**/roulette-test/stream*", unavailable)
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    page.locator("video").evaluate("v => { v.currentTime = v.duration - .01; v.playbackRate = 1; }")
    page.wait_for_function("__rouletteSession.history.length === 2")
    expect(stage).to_have_attribute("data-phase", "playing")
    assert page.evaluate("__rouletteEvents.some(event => event.natural_completion)")
    page.emulate_media(reduced_motion="no-preference")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    page.get_by_role("button", name="Exit", exact=True).click()
    page.wait_for_timeout(1500)
    assert page.locator("video").count() == 0
    assert page.evaluate("__rouletteSession.closed")
    assert not errors, errors


def test_roulette_cancel_during_reveal(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url)
    page.locator("#launch-roulette").click()
    expect(page.locator(".curator-roulette-stage")).to_have_attribute(
        "data-phase", "spinning", timeout=20000
    )
    page.wait_for_function("__rouletteSession.phase === 'revealing'", timeout=30000)
    page.get_by_role("button", name="Exit", exact=True).click()
    page.wait_for_timeout(1500)
    assert page.locator("video").count() == 0
    assert page.evaluate("__rouletteSession.closed")
    assert not errors, errors


@pytest.mark.parametrize("phase", ["assembling", "celebrating"])
def test_roulette_cancel_visual_intro(page: Page, base_url: str, phase: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url)
    page.locator("#launch-roulette").click()
    expect(page.locator(".curator-roulette-stage")).to_have_attribute(
        "data-phase", phase, timeout=30000
    )
    page.get_by_role("button", name="Exit", exact=True).click()
    page.wait_for_timeout(2500)
    expect(page.locator(".curator-roulette-dialog")).to_have_count(0)
    expect(page.locator(".curator-roulette-flight")).to_have_count(0)
    expect(page.locator("#launch-roulette")).to_be_focused()
    assert page.evaluate("__rouletteSession.closed")
    assert page.locator("video").count() == 0
    assert not errors, errors


def test_roulette_highlight_and_reveal_ignore_loose_svg_bounds(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    page.set_viewport_size({"width": 390, "height": 844})
    page.add_init_script(
        """const bounds = SVGImageElement.prototype.getBoundingClientRect;
        SVGImageElement.prototype.getBoundingClientRect = function() {
          const rect = bounds.call(this), side = Math.max(rect.width, rect.height) * 1.5;
          return new DOMRect(rect.x - (side - rect.width) / 2,
            rect.y - (side - rect.height) / 2, side, side);
        };"""
    )
    errors = _install(page, base_url)
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "celebrating", timeout=15000)
    size = page.locator(".curator-roulette-hit").evaluate(
        """node => {
          const animation = node.getAnimations().find(a => !a.animationName);
          animation.pause(); animation.currentTime = 0;
          const entry = __rouletteSession.history[__rouletteSession.index];
          const image = document.querySelectorAll('.curator-roulette-wheel-wrap image')[entry.slot];
          const matrix = image.getScreenCTM(), box = image.getBBox();
          const width = box.width * Math.hypot(matrix.a, matrix.b);
          const height = box.height * Math.hypot(matrix.c, matrix.d);
          const card = image.getBoundingClientRect(), frame = node.getBoundingClientRect();
          return {width, height, frameWidth: parseFloat(node.style.width),
            frameHeight: parseFloat(node.style.height), cardX: card.x + card.width / 2,
            cardY: card.y + card.height / 2, frameX: frame.x + frame.width / 2,
            frameY: frame.y + frame.height / 2};
        }"""
    )
    assert abs(size["frameWidth"] - size["width"]) < 1
    assert abs(size["frameHeight"] - size["height"]) < 1
    assert abs(size["frameWidth"] / size["frameHeight"] - 16 / 9) < 0.001
    assert abs(size["frameX"] - size["cardX"]) < 1
    assert abs(size["frameY"] - size["cardY"]) < 1
    page.locator(".curator-roulette-hit").evaluate(
        "node => node.getAnimations().find(a => !a.animationName).finish()"
    )
    expect(stage).to_have_attribute("data-phase", "revealing", timeout=30000)
    frames = page.locator(".curator-roulette-player").evaluate(
        """host => {
          const animation = host.getAnimations()[0]; animation.pause();
          return [0, 325, 650, 975, 1290].map(time => {
            animation.currentTime = time;
            const rect = host.getBoundingClientRect();
            return {width: rect.width, height: rect.height,
              x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
          });
        }"""
    )
    assert abs(frames[0]["width"] - size["width"]) < 1
    assert abs(frames[0]["height"] - size["height"]) < 1
    assert abs(frames[0]["x"] - size["cardX"]) < 1
    assert abs(frames[0]["y"] - size["cardY"]) < 1
    assert all(abs(frame["width"] / frame["height"] - 16 / 9) < 0.001 for frame in frames)
    assert all(first["width"] < second["width"] for first, second in pairwise(frames))
    wheel_fade = page.locator(".curator-roulette-spinner").evaluate("""node => {
      const animation = node.getAnimations()[0]; animation.pause();
      return [0, 650, 1300].map(time => {
        animation.currentTime = time; return Number(getComputedStyle(node).opacity);
      });
    }""")
    assert wheel_fade[0] == 1 and 0 < wheel_fade[1] < 1 and wheel_fade[2] == 0
    assert stage.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(6, 6, 9)"
    page.wait_for_function("""getComputedStyle(
      document.querySelector('.curator-roulette-stage'), '::before').opacity === '0'""")
    page.locator(".curator-roulette-player").evaluate("node => node.getAnimations()[0].finish()")
    expect(stage).to_have_attribute("data-phase", "playing")
    page.locator("video").evaluate("video => video.pause()")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    returned = page.locator(".curator-roulette-player").evaluate(
        """host => {
          const spinner = document.querySelector('.curator-roulette-spinner');
          [host, spinner].forEach(node => node.getAnimations().forEach(animation => {
            animation.pause(); animation.currentTime = 1099;
          }));
          const entry = __rouletteSession.history[__rouletteSession.index];
          const image = document.querySelectorAll('.curator-roulette-wheel-wrap image')[entry.slot];
          const matrix = image.getScreenCTM(), box = image.getBBox();
          const rect = host.getBoundingClientRect(), card = image.getBoundingClientRect();
          return {width: rect.width, height: rect.height,
            cardWidth: box.width * Math.hypot(matrix.a, matrix.b),
            cardHeight: box.height * Math.hypot(matrix.c, matrix.d),
            x: rect.x + rect.width / 2, y: rect.y + rect.height / 2,
            cardX: card.x + card.width / 2, cardY: card.y + card.height / 2};
        }"""
    )
    assert abs(returned["width"] - returned["cardWidth"]) < 1
    assert abs(returned["height"] - returned["cardHeight"]) < 1
    assert abs(returned["x"] - returned["cardX"]) < 1
    assert abs(returned["y"] - returned["cardY"]) < 1
    page.get_by_role("button", name="Exit", exact=True).click()
    expect(page.locator(".curator-roulette-dialog")).to_have_count(0)
    assert not errors, errors
