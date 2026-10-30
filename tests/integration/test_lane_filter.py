"""The Curator lane filter on Stash's own scenes page."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest

from tests.integration.conftest import _gql
from tests.integration.test_smoke import _dismiss_modals

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = pytest.mark.integration


def _lane_url(base_url: str, label: str, sort: str) -> str:
    criterion = f'("type":"curator_lane","modifier":"EQUALS","value":"{label}")'
    return f"{base_url}/scenes?c={quote(criterion)}&sortby={sort}&sortdir=desc"


def _clicked_origin(page: Page, card: object) -> object:
    """Click a card's link without leaving the list; return the stored credit."""
    page.evaluate(
        "sessionStorage.removeItem('stash-curator:origin:v1');"
        "document.addEventListener('click', (event) => event.preventDefault(),"
        " { capture: true, once: true })"
    )
    card.locator("a").first.click()  # type: ignore[attr-defined]
    stored = page.evaluate("sessionStorage.getItem('stash-curator:origin:v1')")
    return json.loads(stored) if stored else None


def test_lane_filter_lists_lane_scenes_natively(page: Page, base_url: str, seeded: None) -> None:
    """The seeded library leaves every lane empty, so Curator's page answer is
    served here; Stash's list, the filter, the sort and the cards are real."""
    from playwright.sync_api import expect

    scenes = _gql(base_url, '{findScenes(filter:{per_page:3, sort:"title"}){scenes{id title}}}')
    first, second, third = scenes["findScenes"]["scenes"]
    lane_page = [third["id"], first["id"]]
    requests: list[dict[str, object]] = []
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
        args = json.loads(body)["variables"]["args"]
        requests.append(args)
        output = {
            "lane": args["lane"],
            "model_id": "integration-model",
            "impression_id": args.get("impression_id"),
            "scene_ids": lane_page,
            "count": len(lane_page),
        }
        response = {"data": {"runPluginOperation": output}}
        route.fulfill(content_type="application/json", body=json.dumps(response))

    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/graphql", handle)
    page.goto(_lane_url(base_url, "For You", "curator_lane_picks"), wait_until="domcontentloaded")
    _dismiss_modals(page)

    cards = page.locator(".scene-card")
    expect(cards).to_have_count(2, timeout=30_000)
    expect(cards.nth(0)).to_contain_text(third["title"])
    expect(cards.nth(1)).to_contain_text(first["title"])
    expect(page.locator(".scene-card", has_text=second["title"])).to_have_count(0)
    expect(page.locator(".filter-tags, .filter-tag-list").first).to_contain_text("Curator Lane")
    expect(page.locator(".filter-tags, .filter-tag-list").first).to_contain_text("For You")
    expect(page.get_by_text("Curator Lane Picks").first).to_be_visible()
    shown = requests[-1]
    assert shown["lane"] == "for_you" and shown["order"] == "picks"
    assert shown["draw_seed"] and shown["impression_id"]

    # A card on screen for a second is a lane view under the page's impression.
    page.wait_for_timeout(2_500)
    viewed = {
        event["scene_id"]
        for event in events
        if event.get("event_type") == "qualified_impression"
        and event.get("impression_id") == shown["impression_id"]
    }
    assert viewed == set(lane_page), events

    # In Curator's order, opening a card credits the play to the lane. The
    # scene page consumes the credit on arrival, so stay on the list to read it.
    assert _clicked_origin(page, cards.nth(0)) == {
        "scene_id": third["id"],
        "impression_id": shown["impression_id"],
        "lane": "for_you",
        "impression_position": 0,
        "model_id": "integration-model",
    }

    # Native selection works on the lane's cards.
    check = cards.nth(0).locator("input.card-check")
    check.check(force=True)
    expect(check).to_be_checked()

    # Any of Stash's sorts orders the lane by that field instead.
    requests.clear()
    page.goto(_lane_url(base_url, "Revisit", "date"), wait_until="domcontentloaded")
    _dismiss_modals(page)
    expect(cards).to_have_count(2, timeout=30_000)
    assert requests[-1]["lane"] == "revisit" and requests[-1]["order"] == "stash"
    assert requests[-1]["filter"]["sort"] == "date"
    # Stash's sort order doesn't credit plays to the lane.
    assert _clicked_origin(page, cards.nth(0)) is None
    expect(page.locator("body")).not_to_contain_text(re.compile("Choose a Curator lane"))
    assert not errors, f"JavaScript errors: {errors}"
