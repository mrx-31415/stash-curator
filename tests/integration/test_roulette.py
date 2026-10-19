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


def _install(page: Page, base_url: str, count: int = 32) -> list[str]:
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
      enqueue = (entry) => window.__rouletteEvents.push(entry);
      operation = async (request) => {
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
        const close = React.useCallback(() => setSession(null), []);
        return React.createElement(React.Fragment, null,
          React.createElement("button", { id: "launch-roulette", onClick: () => {
            const slate = { lane: "best_bets", page_size: 24, model_id: "fixture-model",
              impression_id: "fixture-first", items: fixtures.slice(0, 24)
                .map((s, i) => ({ scene_id: s.id, position: i })) };
            window.__rouletteSession = createRouletteSession(slate, slate.items, {},
              new Map(fixtures.map(s => [s.id, s])));
            setSession(window.__rouletteSession);
          } }, "Roulette"),
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
        if "RouletteScenes" in query:
            route.fulfill(
                json={"data": {key: by_id.get(value) for key, value in variables.items()}}
            )
        elif "FindScene" in query and str(variables.get("id")) in by_id:
            route.fulfill(json={"data": {"findScene": by_id[str(variables["id"])]}})
        elif query.lstrip().startswith("mutation"):
            # The app may persist native activity/volume settings; nothing leaves this test.
            if "sceneSaveActivity" in query:
                route.fulfill(json={"data": {"sceneSaveActivity": True}})
            elif "sceneIncrementPlayCount" in query:
                route.fulfill(json={"data": {"sceneIncrementPlayCount": 1}})
            else:
                route.fulfill(json={"data": {}})
        else:
            route.continue_()

    page.route("**/graphql", graphql)
    page.goto(base_url + "/plugins/curator-roulette-test")
    page.locator("#launch-roulette").wait_for(timeout=30000)
    return errors


def test_native_roulette_transitions(page: Page, base_url: str) -> None:
    from playwright.sync_api import expect

    errors = _install(page, base_url)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.locator("#launch-roulette").click()
    stage = page.locator(".curator-roulette-stage")
    expect(stage).to_have_attribute("data-phase", "spinning")
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
    page.wait_for_function("window.__rouletteSession.phase === 'revealing'", timeout=15000)
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
    expect(stage).to_have_attribute("data-phase", "playing", timeout=5000)
    assert page.locator("video").evaluate("v => v.currentTime < 1")
    assert video.evaluate("node => node.isConnected")
    expect(page.locator("[data-roulette-companion]")).to_have_count(1)
    page.locator("video").evaluate("v => { v.pause(); v.currentTime = .4; }")
    first = page.evaluate("__rouletteSession.history[0].origin.scene_id")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "returning")
    assert video.evaluate("node => node.isConnected")
    expect(stage).to_have_attribute("data-phase", "playing", timeout=15000)
    assert page.evaluate("__rouletteSession.history[1].origin.scene_id") != first
    page.get_by_role("button", name="Back", exact=True).click()
    expect(stage).to_have_attribute("data-phase", "playing")
    assert (
        page.evaluate("__rouletteSession.history[__rouletteSession.index].origin.scene_id") == first
    )
    page.wait_for_function("Math.abs(document.querySelector('video').currentTime - .4) < .1")
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
    errors = _install(page, base_url)
    page.locator("#launch-roulette").click()
    page.wait_for_function("__rouletteSession.phase === 'revealing'", timeout=15000)
    page.get_by_role("button", name="Exit", exact=True).click()
    page.wait_for_timeout(1500)
    assert page.locator("video").count() == 0
    assert page.evaluate("__rouletteSession.closed")
    assert not errors, errors
