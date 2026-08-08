"""Smoke tests: every Curator page and tab must render without JavaScript errors.

These tests require a Stash instance with the plugin installed.
Start with: docker compose -f tests/integration/docker-compose.yml up -d
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
    ("", ["no published model", "Sync and build now", "Preparing For You"]),
    ("?view=similar", ["Choose a scene or performer", "Library", "StashDB"]),
    ("?view=expand", ["External metadata candidates", "Loading Expand cache"]),
    ("?view=taste", ["Loading taste profile", "No supported tags"]),
    ("?view=hunt", ["Select a local performer linked to StashDB"]),
    ("?view=feedback", ["Loading feedback history", "No feedback has been recorded yet"]),
    ("?view=backups", ["Create backup", "No Curator backups found"]),
]


@pytest.mark.parametrize("view_param,expected_phrases", TABS)
def test_curator_tab_renders_without_errors(
    page: Page, base_url: str, view_param: str, expected_phrases: list[str]
) -> None:
    """Each Curator tab renders its empty-state content without JS errors."""
    page.goto(f"{base_url}{CURATOR_PATH}{view_param}", wait_until="domcontentloaded")
    _wait(page)
    _dismiss_modals(page)

    content = page.content()
    found = any(phrase in content for phrase in expected_phrases)

    if not found:
        body_text = page.locator("body").inner_text()
        assert found, (
            f"View '{view_param or '/'}' missing expected phrases: {expected_phrases}\n"
            f"Body (first 800): {body_text[:800]}"
        )

    errors = _collect_errors(page)
    assert not errors, f"JS errors on '{view_param or '/'}': {errors}"


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
