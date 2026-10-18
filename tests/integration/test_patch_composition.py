"""Patched Stash pages must retain native content with a second plugin loaded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import _gql
from tests.integration.test_smoke import _dismiss_modals

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration
COMPANION = Path(__file__).with_name("patch_companion.js").read_text()


@pytest.mark.parametrize("extra_context", [False, True], ids=["props-only", "extra-arguments"])
@pytest.mark.parametrize("surface", ["scenes", "performers", "scene", "performer"])
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
                "SceneCard.Popovers",
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
    expect(page.locator("body")).not_to_contain_text("Something went wrong")
    assert not errors, f"{surface}: JavaScript errors: {errors}"
