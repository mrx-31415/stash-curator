"""Incognito stops this browser's plays reaching Stash's history and Curator.

Plays the seeded scene's synthetic clip to its end through Stash's own player
and watches the network: Stash's activity tracker sends SceneSaveActivity and
SceneAddPlay, and Curator's tracker sends the watch session with submit_events.
With Incognito off all three are sent (the control); with it on, none is.

The lane test covers what Curator learns without playback: cards seen in a lane
(qualified impressions) and a card opened from a lane but not played (a session
credited to the lane). With Incognito on, Curator sends no events at all.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import _gql
from tests.integration.test_lane_filter import _lane_url
from tests.integration.test_patch_composition import _serve_scene_file
from tests.integration.test_smoke import _dismiss_modals

if TYPE_CHECKING:
    from playwright.sync_api import Page, Request, Route

pytestmark = pytest.mark.integration

STASH_TRACKING = ("SceneSaveActivity", "SceneAddPlay")


@pytest.mark.parametrize("incognito", [False, True], ids=["off", "on"])
def test_incognito_stops_play_tracking(
    page: Page, base_url: str, seeded: None, incognito: bool
) -> None:
    from playwright.sync_api import expect

    scene_id = str(
        _gql(base_url, "{findScenes(filter:{per_page:1}){scenes{id}}}")["findScenes"]["scenes"][0][
            "id"
        ]
    )
    sent: list[str] = []

    def record(request: Request) -> None:
        if not request.url.endswith("/graphql") or request.method != "POST":
            return
        payload = request.post_data_json or {}
        variables = payload.get("variables") or {}
        if payload.get("operationName") in STASH_TRACKING and str(variables.get("id")) == scene_id:
            sent.append(payload["operationName"])
        entries = (variables.get("args") or {}).get("entries") or []
        if any(
            entry.get("session_id") and str(entry.get("scene_id")) == scene_id for entry in entries
        ):
            sent.append("submit_events")

    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", record)
    page.add_init_script("delete Navigator.prototype.wakeLock;")
    _serve_scene_file(page, base_url, scene_id)

    page.goto(base_url + "/", wait_until="domcontentloaded")
    _dismiss_modals(page)
    # Stash renders utility buttons in the navbar strip and in the collapsible menu; the
    # switch shows in the strip at every width.
    toggle = page.locator(".navbar-buttons .incognito-toggle")
    expect(toggle).to_be_visible()
    expect(page.locator(".navbar-collapse .incognito-toggle")).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    # Native utility buttons and Curator's navbar entry survive the patch.
    expect(page.locator(".navbar-buttons a[href='/settings']")).to_have_count(1)
    expect(page.get_by_role("link", name="Curator", exact=True)).to_have_count(1)
    if incognito:
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")

    page.goto(f"{base_url}/scenes/{scene_id}", wait_until="domcontentloaded")
    _dismiss_modals(page)
    # The switch persists across page loads in this browser.
    expect(toggle).to_have_attribute("aria-pressed", str(incognito).lower())
    video = page.locator(".video-js video")
    expect(video).to_have_count(1, timeout=30_000)
    video.evaluate("video => { video.muted = true; return video.play(); }")
    page.wait_for_function("() => document.querySelector('.video-js video')?.ended", timeout=30_000)
    page.wait_for_timeout(1500)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    if incognito:
        assert sent == []
    else:
        assert set(sent) == {*STASH_TRACKING, "submit_events"}, sent
    assert errors == []


@pytest.mark.parametrize("incognito", [False, True], ids=["off", "on"])
def test_incognito_hides_lane_views_and_opens(
    page: Page, base_url: str, seeded: None, incognito: bool
) -> None:
    from playwright.sync_api import expect

    scenes = _gql(base_url, '{findScenes(filter:{per_page:2, sort:"title"}){scenes{id}}}')
    lane_page = [scene["id"] for scene in scenes["findScenes"]["scenes"]]
    events: list[dict[str, object]] = []

    def handle(route: Route) -> None:
        body = route.request.post_data or ""
        if '"submit_events"' in body:
            events.extend(json.loads(body)["variables"]["args"]["entries"])
            route.continue_()
            return
        if '"get_lane_scene_page"' not in body:
            route.continue_()
            return
        # The seeded library leaves every lane empty; serve one page of it.
        args = json.loads(body)["variables"]["args"]
        output = {
            "lane": args["lane"],
            "model_id": "integration-model",
            "impression_id": args.get("impression_id"),
            "scene_ids": lane_page,
            "count": len(lane_page),
        }
        route.fulfill(
            content_type="application/json",
            body=json.dumps({"data": {"runPluginOperation": output}}),
        )

    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/graphql", handle)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    _dismiss_modals(page)
    if incognito:
        toggle = page.locator(".navbar-buttons .incognito-toggle")
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")

    page.goto(_lane_url(base_url, "For You", "curator_lane_picks"), wait_until="domcontentloaded")
    _dismiss_modals(page)
    cards = page.locator(".scene-card")
    expect(cards).to_have_count(2, timeout=30_000)
    page.wait_for_timeout(2_500)  # long enough for both cards to count as seen
    cards.nth(0).locator("a").first.click()
    expect(page).to_have_url(re.compile(rf"/scenes/{lane_page[0]}(\?|$)"), timeout=10_000)
    page.wait_for_timeout(1_500)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(2_500)

    if incognito:
        assert events == []
    else:
        seen = {e["scene_id"] for e in events if e.get("event_type") == "qualified_impression"}
        assert seen == set(lane_page), events
        opened = [e for e in events if e.get("session_id") and e.get("lane") == "for_you"]
        assert [str(e["scene_id"]) for e in opened] == [lane_page[0]], events
    assert errors == []
