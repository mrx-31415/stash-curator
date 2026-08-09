"""Fresh-install (no published model) UI coverage, run last.

The seeded environment builds a model before the suite starts, so the no-model
state cannot be observed during the normal run. This test runs after everything
else (test_z_* ordering): it resets the plugin's sidecar database through the
plugin's own reset operation, then asserts the fresh-install page renders the
setup checklist and the no-model recommendation state without JS errors.

The reset is safe here because no later test needs the sidecar.
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import TYPE_CHECKING, Any

import pytest

from tests.integration.conftest import _gql

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.integration

CURATOR_PATH = "/plugins/stash-curator"


def _stash_url() -> str:
    return os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")


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
    tracked: list[Any] = getattr(page, "_errors", [])
    return [str(e.message) for e in tracked]


@pytest.fixture(autouse=True)
def _track_errors(page: Page) -> None:
    tracked: list[Any] = []
    page.on("pageerror", lambda err: tracked.append(err))
    page.__dict__["_errors"] = tracked


def _wait_for_phrase(page: Page, phrase: str, timeout_s: float = 20) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if phrase in page.content():
            return True
        page.wait_for_timeout(500)
    return False


def test_fresh_install_after_reset_renders_without_errors(page: Page, base_url: str) -> None:
    """After a plugin reset the main route shows the no-model state cleanly."""
    # The reset operation requires no running job; wait until Curator is idle.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = _gql(
            _stash_url(),
            (
                "mutation JobStatus($args: Map!) { "
                'runPluginOperation(plugin_id: "stash-curator", args: $args) }'
            ),
            {"args": {"operation": "get_job_status"}},
        )["runPluginOperation"]["jobs"]
        if not any(job["state"] == "running" for job in jobs):
            break
        time.sleep(2)

    result = _gql(
        _stash_url(),
        (
            "mutation Reset($args: Map!) { "
            'runPluginOperation(plugin_id: "stash-curator", args: $args) }'
        ),
        {"args": {"operation": "reset", "confirmation": "RESET"}},
    )["runPluginOperation"]
    assert result.get("reset") is True

    page.goto(base_url + CURATOR_PATH, wait_until="domcontentloaded")
    _dismiss_modals(page)

    # The fresh-install page shows the setup checklist and the no-model state.
    for phrase in ("no published model", "Sync and build now", "Finish Curator setup"):
        assert _wait_for_phrase(page, phrase), f"missing fresh-install phrase: {phrase!r}"

    errors = _collect_errors(page)
    assert not errors, f"JS errors on fresh-install page: {errors}"
