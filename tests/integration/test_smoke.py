"""Smoke tests: every Curator page and tab must render without JavaScript errors.

These tests require a Stash instance with the plugin installed.
Start with: docker compose -f tests/integration/docker-compose.yml up -d
"""

from __future__ import annotations

import contextlib
import time
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
    """Return any JS errors that have occurred on the page so far."""
    errors: list[Any] = getattr(page, "_errors", [])
    return [str(e.message) for e in errors]


@pytest.fixture(autouse=True)
def _track_errors(page: Page) -> None:
    """Capture all unhandled JS errors for the lifetime of the page."""
    tracked: list[Any] = []
    page.on("pageerror", lambda err: tracked.append(err))
    page.__dict__["_errors"] = tracked


def _wait(page: Page, ms: int = 2000) -> None:
    page.wait_for_timeout(ms)


def test_curator_page_loads_without_errors(page: Page, base_url: str) -> None:
    """The Curator plugin main page loads without JS errors."""
    page.goto(base_url + CURATOR_PATH, wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)
    errors = _collect_errors(page)
    assert not errors, f"JS errors: {errors}"


# ── Tab URLs → expected content ──

TABS: list[tuple[str, list[str]]] = [
    # The seed runs a sync-and-build and waits for the published model, so the
    # main route shows the ready recommendation UI, not the fresh-install state.
    ("", ["For You", "Best Bets", "Ready"]),
    ("?view=similar", ["Choose a scene or performer", "Library", "StashDB"]),
    ("?view=expand", ["External metadata candidates", "Loading Expand cache"]),
    (
        "?view=taste",
        [
            "Loading taste profile",
            "No supported tags",
            "Declared answers are strong evidence",
        ],
    ),
    ("?view=hunt", ["Select a local performer linked to StashDB"]),
    (
        "?view=feedback",
        [
            "Loading feedback history",
            "No feedback has been recorded yet",
            "Review recent feedback",
        ],
    ),
    (
        "?view=backups",
        [
            "Create backup",
            "No Curator backups found",
            "Create, inspect",
        ],
    ),
    # Canonical Manage-shell URLs (GH #150 Package 3) alongside the legacy
    # ?view=<item> aliases above, which must keep resolving into Manage too.
    (
        "?view=manage&section=sentiment",
        ["Sentiment review", "No scenes below the current appeal threshold."],
    ),
    (
        "?view=manage&section=prune",
        ["Prune", "Nothing in this view."],
    ),
    (
        "?view=manage&section=diagnostics",
        ["Diagnostics", "This allowlisted report excludes library metadata"],
    ),
    (
        "?view=manage&section=profiling",
        ["Profiling", "No profiles have been recorded yet."],
    ),
]


@pytest.mark.parametrize("view_param,expected_phrases", TABS)
def test_curator_tab_renders_without_errors(
    page: Page, base_url: str, view_param: str, expected_phrases: list[str]
) -> None:
    """Each Curator tab renders its empty-state content without JS errors."""
    page.goto(f"{base_url}{CURATOR_PATH}{view_param}", wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)

    # Poll for the expected phrases: some depend on an async health round trip
    # (the ready status), so a fixed wait would be flaky on slow runners.
    found = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        content = page.content()
        if any(phrase in content for phrase in expected_phrases):
            found = True
            break
        page.wait_for_timeout(500)

    if not found:
        body_text = page.locator("body").inner_text()
        assert found, (
            f"View '{view_param or '/'}' missing expected phrases: {expected_phrases}\n"
            f"Body (first 800): {body_text[:800]}"
        )

    errors = _collect_errors(page)
    assert not errors, f"JS errors on '{view_param or '/'}': {errors}"


def test_curator_nav_collapse_and_manage_shell_are_click_driven(page: Page, base_url: str) -> None:
    """Exercise the collapsed nav interactively (GH #150 Package 3).

    URL-only coverage (test_curator_tab_renders_without_errors above) can't
    prove the pill click-branching logic actually works — only that each URL
    renders. This clicks through the lane switcher and the Manage shell, and
    specifically checks that clicking the already-active Recommendations
    pill while on a non-default lane does not reset it back to For You (the
    single riskiest bit of new logic in this package).
    """
    page.goto(base_url + CURATOR_PATH, wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)

    # Lane switcher: click Discover, confirm the URL and active state follow.
    discover_card = page.locator(".curator-lane-card").filter(
        has=page.locator(".curator-lane-card-name", has_text="Discover")
    )
    discover_card.click()
    page.wait_for_timeout(800)
    assert "view=discover" in page.url
    assert discover_card.get_attribute("aria-pressed") == "true"

    # Clicking the already-active Recommendations pill must be a no-op, not
    # a reset to the default "for_you" lane.
    page.locator(".curator-nav-recommendations").click()
    page.wait_for_timeout(500)
    assert "view=discover" in page.url

    # Manage: open it, pick a section, confirm the detail pane swaps.
    page.locator(".curator-nav-manage").click()
    page.wait_for_timeout(800)
    assert "view=manage" in page.url
    backups_item = page.locator(".curator-manage-item").filter(
        has=page.locator(".curator-manage-item-title", has_text="Backups")
    )
    backups_item.click()
    page.wait_for_timeout(800)
    assert "section=backups" in page.url
    assert "Backups" in page.locator(".curator-manage-detail-head").inner_text()

    # Clicking the already-active Manage pill must not drop the section.
    page.locator(".curator-nav-manage").click()
    page.wait_for_timeout(500)
    assert "section=backups" in page.url

    errors = _collect_errors(page)
    assert not errors, f"JS errors during nav-collapse interaction: {errors}"


def test_curator_tasks_page_renders(page: Page, base_url: str) -> None:
    """The Tasks sub-tab renders without errors."""
    page.goto(base_url + CURATOR_PATH, wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)

    tasks_link = page.locator("a.nav-link", has_text="Tasks")
    if tasks_link.count() > 0:
        tasks_link.first.click(force=True)
        _wait(page)
        content = page.content()
        assert "Tasks" in content or "Clone" in content
        errors = _collect_errors(page)
        assert not errors, f"JS errors on Tasks: {errors}"


def test_curator_settings_page_renders(page: Page, base_url: str) -> None:
    """The Settings sub-tab renders without errors."""
    page.goto(base_url + CURATOR_PATH, wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)

    settings_link = page.locator("a.nav-link", has_text="Settings")
    if settings_link.count() > 0:
        settings_link.first.click(force=True)
        _wait(page)
        content = page.content()
        assert "Settings" in content or "Profiling" in content
        errors = _collect_errors(page)
        assert not errors, f"JS errors on Settings: {errors}"
