from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
SOURCE = (ROOT / "showcase-mocks.html").as_uri()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 675}, device_scale_factor=1)
    page.goto(SOURCE)
    for name in ("recommendations", "find", "curate"):
        page.locator(f"#{name}").screenshot(path=ROOT / f"showcase-{name}.png")
    browser.close()
