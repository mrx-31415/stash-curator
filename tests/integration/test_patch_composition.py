"""Patched Stash pages must retain native content with a second plugin loaded."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import _gql
from tests.integration.test_smoke import _dismiss_modals

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = pytest.mark.integration
COMPANION = Path(__file__).with_name("patch_companion.js").read_text()


@pytest.mark.parametrize("extra_context", [False, True], ids=["props-only", "extra-arguments"])
@pytest.mark.parametrize("surface", ["scenes", "performers", "scene", "performer", "home"])
def test_patched_stash_page_with_companion(
    page: Page, base_url: str, seeded: None, surface: str, extra_context: bool
) -> None:
    from playwright.sync_api import expect

    data = _gql(
        base_url,
        "{findScenes(filter:{per_page:1}){scenes{id title}} "
        "findPerformers(filter:{per_page:1}){performers{id name}}}",
    )
    scene = data["findScenes"]["scenes"][0]
    performer = data["findPerformers"]["performers"][0]
    cases = {
        "scenes": (
            "/scenes",
            scene["title"],
            [
                "FilteredSceneList",
                "SceneList",
                "SceneCard.Details",
                "SceneCard.Overlays",
                "HoverPopover",
            ],
        ),
        "performers": (
            "/performers",
            performer["name"],
            ["FilteredPerformerList", "PerformerCard.Overlays"],
        ),
        "scene": (f"/scenes/{scene['id']}", scene["title"], ["ScenePage", "ScenePlayer"]),
        "performer": (f"/performers/{performer['id']}", performer["name"], ["PerformerPage"]),
        "home": ("/", scene["title"], ["FrontPage", "SceneCard.Overlays"]),
    }
    route, title, patched = cases[surface]
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.add_init_script(
        # Screen wake locks are unavailable here; use Stash's unsupported-API path.
        "delete Navigator.prototype.wakeLock;\n"
        f"window.__curatorExtraContext = {json.dumps(extra_context)};\n{COMPANION}"
    )
    if surface == "home":
        _serve_home_slate(page, scene["id"])
    page.goto(base_url + route, wait_until="domcontentloaded")
    _dismiss_modals(page)
    expect(page.locator("body")).to_contain_text(title)
    expect(page.locator('[data-patch-companion="navbar"]')).to_have_count(1)
    expect(page.get_by_role("link", name="Curator", exact=True)).to_have_count(1)
    page.wait_for_function(
        "names => names.every(name => window.__curatorPatchCounts?.[name] > 0)",
        arg=["MainNavBar.MenuItems", *patched],
    )
    for name in patched:
        if "Card." in name:
            assert page.locator(f'[data-patch-native="{name}"]').count() > 0, name
            assert page.locator(f'[data-patch-companion="{name}"]').count() > 0, name
    if surface in ("scene", "performer"):
        panel = page.get_by_label("Curator affinity details")
        expect(panel).to_have_count(1)
        expect(
            panel.get_by_role("link", name=f"Find similar {surface}s with Curator", exact=True)
        ).to_have_count(1)
    if surface == "home":
        # Curator's For You row (on by default) comes before Stash's own rows.
        rows = page.locator(".recommendations-container .recommendation-row")
        expect(page.locator(".curator-home-row-for_you .scene-card").first).to_be_visible(
            timeout=30_000
        )
        expect(page.locator(".curator-home-row-for_you")).to_contain_text(scene["title"])
        expect(
            page.locator(".curator-home-row-for_you").get_by_role("link", name="View All")
        ).to_have_attribute("href", "/plugins/stash-curator?view=for_you")
        expect(rows.first).to_have_class(re.compile(r"\bcurator-home-row-for_you\b"))
        expect(page.locator(".recommendation-row:not(.curator-home-row)").first).to_be_visible()
        expect(page.locator(".curator-home-row-for_you h2")).to_contain_text("For You")
    expect(page.locator("body")).not_to_contain_text("Something went wrong")
    assert not errors, f"{surface}: JavaScript errors: {errors}"


def test_home_rows_follow_customize(page: Page, base_url: str, seeded: None) -> None:
    """Curator's rows sit in Stash's own home page list: moving the entry moves
    the row, Customize labels it, and deleting it there turns the lane off."""
    from playwright.sync_api import expect

    query = '{configuration{ui plugins(include:["stash-curator"])}}'
    original = _gql(base_url, query)["configuration"]
    original_settings = original["plugins"].get("stash-curator") or {}
    scene = _gql(base_url, "{findScenes(filter:{per_page:1}){scenes{id}}}")["findScenes"]
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve_home_slate(page, scene["scenes"][0]["id"])
    curator_row = ".curator-home-row-for_you"
    rows = page.locator(".recommendations-container .recommendation-row")
    try:
        page.goto(base_url + "/", wait_until="domcontentloaded")
        _dismiss_modals(page)
        expect(page.locator(f"{curator_row} .scene-card").first).to_be_visible(timeout=30_000)
        content = _gql(base_url, query)["configuration"]["ui"]["frontPageContent"]
        assert content[0] == {"__typename": "CuratorLane", "lane": "for_you"}

        # Moved below Stash's rows (as Customize saves it), it renders there.
        ui = _gql(base_url, query)["configuration"]["ui"]
        moved = [*content[1:], content[0]]
        _gql(
            base_url,
            "mutation($input: Map!){configureUI(input:$input)}",
            {"input": {**ui, "frontPageContent": moved}},
        )
        page.reload(wait_until="domcontentloaded")
        _dismiss_modals(page)
        expect(page.locator(f"{curator_row} .scene-card").first).to_be_visible(timeout=30_000)
        expect(rows.first).not_to_have_class(re.compile(r"\bcurator-home-row\b"))
        expect(rows.last).to_have_class(re.compile(r"\bcurator-home-row-for_you\b"))
        assert _gql(base_url, query)["configuration"]["ui"]["frontPageContent"] == moved

        # Customize labels the row Stash leaves blank; deleting it turns For You off.
        page.get_by_role("button", name=re.compile("^Customi[sz]e$")).click()
        label = page.locator('h2[data-curator-label="Curator: For You"]')
        expect(label).to_have_count(1)
        assert "Curator: For You" in label.evaluate(
            "node => getComputedStyle(node, '::before').content"
        )
        page.locator(".recommendation-row", has=label).get_by_role("button", name="Delete").click()
        page.get_by_role("button", name="Save").click()
        # Back on the rows view once Stash has saved the list.
        customize = page.get_by_role("button", name=re.compile("^Customi[sz]e$"))
        expect(customize).to_be_visible(timeout=30_000)
        expect(page.locator(".recommendations-container-edit")).to_have_count(0)
        expect(page.locator(curator_row)).to_have_count(0)
        state = _gql(base_url, query)["configuration"]
        assert state["plugins"]["stash-curator"]["homeForYou"] is False
        assert not [
            e for e in state["ui"]["frontPageContent"] if e.get("__typename") == "CuratorLane"
        ]
        assert not errors, f"JavaScript errors: {errors}"
    finally:
        _gql(
            base_url,
            "mutation($input: Map!){configureUI(input:$input)}",
            {"input": original["ui"]},
        )
        _gql(
            base_url,
            'mutation($input: Map!){configurePlugin(plugin_id:"stash-curator", input:$input)}',
            {"input": original_settings},
        )


def _serve_home_slate(page: Page, scene_id: str) -> None:
    """The seeded library leaves every lane empty, so serve For You one seeded
    scene; the rest of the front page path (settings, rows, cards) is real."""
    slate = {
        "lane": "for_you",
        "model_id": "integration-model",
        "config_updated_at_ms": 1,
        "impression_id": "integration-home",
        "items": [{"scene_id": scene_id, "impression_id": "integration-home", "position": 0}],
    }

    def handle(route: Route) -> None:
        if '"get_slates"' not in (route.request.post_data or ""):
            route.continue_()
            return
        body = {"data": {"runPluginOperation": {"slates": [slate]}}}
        route.fulfill(content_type="application/json", body=json.dumps(body))

    page.route("**/graphql", handle)


def test_card_affinity_survives_replaced_popovers(page: Page, base_url: str, seeded: None) -> None:
    from playwright.sync_api import expect

    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"window.__curatorReplacePopovers = true;\n{COMPANION}")
    # Recommendation cards pass curatorAppeal to Stash's SceneCard; use seeded
    # scenes directly so this check does not depend on lane eligibility.
    page.goto(base_url + "/scenes", wait_until="domcontentloaded")
    _dismiss_modals(page)
    expect(page.locator("[data-patch-companion='footer']").first).to_be_visible(timeout=30_000)
    expect(page.locator(".curator-card-affinity .curator-score-scale").first).to_be_visible()
    expect(page.locator(".scene-card .card-section-title").first).to_be_visible()
    assert not errors, f"Scene cards: JavaScript errors: {errors}"
