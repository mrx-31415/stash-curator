"""Returning to Recommendations after a reload must not rotate the lane."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.integration.test_smoke import _dismiss_modals

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration

SEED = (
    "() => (JSON.parse(localStorage.getItem('stash-curator:rotation:v2') || '{}')"
    ".lanes || {}).for_you?.seed || null"
)


def test_back_to_recommendations_after_reload_keeps_the_draw(
    page: Page, base_url: str, seeded: None
) -> None:
    from playwright.sync_api import expect

    page.goto(base_url + "/plugins/stash-curator", wait_until="domcontentloaded")
    _dismiss_modals(page)
    page.reload(wait_until="domcontentloaded")  # the tab now reports "reload" for good
    _dismiss_modals(page)
    page.wait_for_timeout(1500)
    seeds = [page.evaluate(SEED)]
    for _ in range(3):
        # Leave in-app (the document stays loaded) and come back with Back.
        page.locator(".top-nav a[href='/scenes']").first.click()
        expect(page).to_have_url(re.compile(r"/scenes(\?|$)"), timeout=10_000)
        page.go_back(wait_until="domcontentloaded")
        expect(page).to_have_url(re.compile(r"/plugins/stash-curator(\?|$)"), timeout=10_000)
        page.wait_for_timeout(1000)
        seeds.append(page.evaluate(SEED))
    assert len(set(seeds)) == 1, seeds
