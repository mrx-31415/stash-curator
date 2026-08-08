"""Smoke tests: every Curator page and tab must render without JavaScript errors.

These tests require a Stash instance with the plugin installed.
Start with: docker compose -f tests/integration/docker-compose.yml up -d
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration


CURATOR_PATH = "/plugins/stash-curator"


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


def _wait_stable(page: Page, ms: int = 1500) -> None:
    """Wait for React rendering to settle."""
    page.wait_for_timeout(ms)


def test_curator_page_loads_without_errors(page: Page) -> None:
    """The Curator plugin main page loads without JS errors."""
    page.goto(CURATOR_PATH, wait_until="domcontentloaded")
    _wait_stable(page)
    errors = _collect_errors(page)
    assert not errors, f"JS errors on page load: {errors}"


# ── Tab names and expected content ──

TABS = [
    ("For You", ["No qualified recommendations"]),
    ("Similar", ["No scenes cross this prediction threshold"]),
    ("Expand", ["Expand has not been prepared yet", "Prepare now"]),
    ("Taste Profile", ["No supported tags"]),
    ("Performer Hunt", ["Select a local performer linked to StashDB"]),
    ("Feedback", ["No feedback has been recorded yet"]),
    ("Backups", ["No Curator backups found"]),
]


@pytest.mark.parametrize("tab_name,expected_phrases", TABS)
def test_curator_tab_renders_without_errors(
    page: Page, tab_name: str, expected_phrases: list[str]
) -> None:
    """Each Curator tab renders its empty-state content without JS errors."""
    page.goto(CURATOR_PATH, wait_until="domcontentloaded")
    _wait_stable(page)

    # Click the tab
    link = page.locator("a.nav-link", has_text=re.compile(tab_name))
    if link.count() > 0:
        link.first.click()
    else:
        # Tab may be directly accessible
        tab_id = tab_name.lower().replace(" ", "-")
        page.click(f"#{tab_id}")

    _wait_stable(page)

    # Verify at least one expected phrase is visible
    content = page.content()
    found = any(phrase in content for phrase in expected_phrases)
    assert found, f"Tab '{tab_name}' did not show expected content: {expected_phrases}"

    errors = _collect_errors(page)
    assert not errors, f"JS errors on tab '{tab_name}': {errors}"


def test_curator_tasks_page_renders(page: Page) -> None:
    """The Tasks sub-tab renders without errors."""
    page.goto(CURATOR_PATH, wait_until="domcontentloaded")
    _wait_stable(page)

    tasks_link = page.locator("a.nav-link", has_text="Tasks")
    if tasks_link.count() > 0:
        tasks_link.first.click()
        _wait_stable(page)

        content = page.content()
        assert "Tasks" in content or "Clone" in content or "Downloads" in content

        errors = _collect_errors(page)
        assert not errors, f"JS errors on Tasks: {errors}"


def test_curator_settings_page_renders(page: Page) -> None:
    """The Settings sub-tab renders without errors."""
    page.goto(CURATOR_PATH, wait_until="domcontentloaded")
    _wait_stable(page)

    settings_link = page.locator("a.nav-link", has_text="Settings")
    if settings_link.count() > 0:
        settings_link.first.click()
        _wait_stable(page)

        content = page.content()
        assert "Settings" in content or "Profiling" in content

        errors = _collect_errors(page)
        assert not errors, f"JS errors on Settings: {errors}"
