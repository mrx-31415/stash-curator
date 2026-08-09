"""Similar-performers regression coverage.

Regression: StashDB similar results (scenes and performers) used to crash the
page with "Something went wrong." — the backend ranked items carried
`similarity`/`score` but no `appeal`, and the external card called
`item.appeal.toFixed(2)` unconditionally. The backend now includes `appeal`
for every ranked item and the card renders the appeal part defensively.

These tests drive the real browser through the Similar flow and assert that
neither the Stash error boundary ("Something went wrong.") nor a JS error ever
replaces the panel, whether the StashDB operation succeeds (a stash-box is
configured) or fails cleanly (no stash-box in the CI environment).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration

CURATOR_PATH = "/plugins/stash-curator"


def _dismiss_modals(page: Page) -> None:
    """Dismiss Stash release notes and setup modals that block clicks."""
    for _ in range(5):
        for sel in (
            "div.modal.show button.btn-close",
            "div.modal.show .close",
            "div.modal.show [aria-label='Close']",
            "div.modal.show .btn-primary",
        ):
            btn = page.locator(sel)
            if btn.count() > 0:
                with contextlib.suppress(Exception):
                    btn.first.click(force=True, timeout=2000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        if page.locator("div.modal.show").count() == 0:
            break


def _collect_errors(page: Page) -> list[str]:
    """Return JS page errors and error-level console messages seen so far."""
    errors: list[Any] = getattr(page, "_errors", [])
    return [str(e.message) for e in errors]


@pytest.fixture(autouse=True)
def _track_errors(page: Page) -> None:
    """Capture unhandled JS errors and error-level console output."""
    tracked: list[Any] = []
    page.on("pageerror", lambda err: tracked.append(err))
    page.on("console", lambda msg: tracked.append(msg) if msg.type == "error" else None)
    page.__dict__["_errors"] = tracked


def _assert_panel_survived(page: Page, label: str) -> None:
    """The Similar panel must render, never the Stash error boundary."""
    content = page.content()
    assert "Something went wrong." not in content, f"{label}: page crashed"
    assert page.locator(".curator-similar").count() > 0, f"{label}: panel missing"
    errors = _collect_errors(page)
    assert not errors, f"{label}: JS errors: {errors}"


# (entity type, search text, candidate button text)
SIMILAR_CASES = [
    ("performer", "Test Performer", "Test Performer One"),
    ("scene", "Test Scene", "Test Scene Outdoor Fun"),
]


@pytest.mark.parametrize("entity_type,search_text,candidate", SIMILAR_CASES)
def test_similar_stashdb_never_crashes(
    page: Page, base_url: str, entity_type: str, search_text: str, candidate: str
) -> None:
    """StashDB similar results render (or fail cleanly) without crashing the page."""
    page.goto(
        f"{base_url}{CURATOR_PATH}?view=similar&type={entity_type}",
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(1500)
    _dismiss_modals(page)

    search = page.get_by_role("textbox", name=f"Search for a {entity_type}")
    search.fill(search_text)
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(1500)
    candidate_button = page.get_by_role("button", name=candidate).first
    candidate_button.wait_for(state="visible", timeout=10000)
    candidate_button.click()
    # Library similarity runs the backend before the grid renders.
    page.wait_for_timeout(8000)

    # Switch to the StashDB source; this reloads similarity against the remote pool.
    page.get_by_role("button", name="StashDB").click()
    page.wait_for_timeout(10000)

    _assert_panel_survived(page, f"similar {entity_type} StashDB")


def test_similar_library_performers_render_cards(page: Page, base_url: str) -> None:
    """Library performer similarity renders native performer cards without crashing."""
    page.goto(
        f"{base_url}{CURATOR_PATH}?view=similar&type=performer",
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(1500)
    _dismiss_modals(page)

    search = page.get_by_role("textbox", name="Search for a performer")
    search.fill("Test Performer")
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(1500)
    candidate = page.get_by_role("button", name="Test Performer One").first
    candidate.wait_for(state="visible", timeout=10000)
    candidate.click()
    page.wait_for_timeout(8000)

    _assert_panel_survived(page, "similar performer library")
