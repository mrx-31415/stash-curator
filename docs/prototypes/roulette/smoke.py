"""Browser checks for the standalone prototype; requires Playwright Chromium."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def run():
    root = Path(__file__).parent
    output = Path("/tmp/curator-roulette-preview")
    output.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            # Leave time for screenshots on busy hosts before a sample auto-advances.
            page.add_init_script(
                "document.addEventListener('play', event => {"
                "if (event.target instanceof HTMLVideoElement) event.target.playbackRate = .1;"
                "}, true)"
            )
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator(".card")).to_have_count(24)
            page.screenshot(path=str(output / "desktop.png"))
            page.locator("#launch").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "spinning")
            page.wait_for_timeout(600)
            transforms = page.locator("#wheel image").evaluate_all(
                "images => images.map(image => getComputedStyle(image).transform)"
            )
            for _ in range(3):
                assert (
                    page.locator("#wheel image").evaluate_all(
                        "images => images.map(image => getComputedStyle(image).transform)"
                    )
                    == transforms
                )
                page.wait_for_timeout(120)
            page.screenshot(path=str(output / "wheel.png"))
            expect(page.locator(".wedge")).to_have_count(24)
            expect(page.locator(".hub")).to_have_count(0)
            assert page.locator(".wheel-wrap").bounding_box()["width"] > 900
            page.wait_for_function("state.phase === 'revealing'", timeout=8000)
            video = page.locator("#video").element_handle()
            assert (
                page.locator("#wheel image").evaluate_all(
                    "images => images.map(image => getComputedStyle(image).transform)"
                )
                == transforms
            )
            assert page.evaluate(
                "(() => { const image = document.querySelectorAll('#wheel image')"
                "[Array.from(document.querySelectorAll('.wedge'))"
                ".indexOf(document.querySelector('.winner'))];"
                "const m = image.getScreenCTM();"
                "return Math.abs(m.b) < .001 && Math.abs(m.c) < .001 && m.a > 0 && m.d > 0;"
                "})()"
            )
            assert page.locator("#wheel image").evaluate_all(
                "images => images.every(image => image.getAnimations().length === 0)"
            )
            page.wait_for_function("document.getElementById('video').currentTime > 0")
            assert video.evaluate("element => !element.paused")
            assert video.evaluate("element => getComputedStyle(element).opacity") == "1"
            assert video.evaluate("element => getComputedStyle(element).clipPath").startswith(
                "polygon"
            )
            assert video.evaluate("element => element.getAnimations().length") == 1
            assert video.evaluate(
                "element => { const m = new DOMMatrix(getComputedStyle(element).transform);"
                "return Math.abs(m.b) < .001 && Math.abs(m.c) < .001 && m.a > 0 && m.d > 0; }"
            )
            page.screenshot(path=str(output / "morph.png"))
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing", timeout=8000)
            assert video.evaluate("element => element === document.getElementById('video')")
            assert video.evaluate("element => getComputedStyle(element).clipPath") == "none"
            page.wait_for_function("document.getElementById('video').currentTime > 0.1")
            assert page.evaluate("document.getElementById('video').paused") is False
            winner = page.evaluate("state.history[state.index].scene.id")
            selected = page.locator(".wedge.winner")
            assert int(selected.get_attribute("data-scene")) == winner
            assert page.evaluate(
                "Math.abs((state.rotation + "
                "Array.from(document.querySelectorAll('.wedge'))"
                ".indexOf(document.querySelector('.winner')) * 360 / "
                "document.querySelectorAll('.wedge').length) % 360) < .001"
            )
            page.screenshot(path=str(output / "playing.png"))
            # Reveal the fading controls the same way a viewer would.
            page.mouse.move(720, 500)
            page.locator("#pause").click()
            page.evaluate("document.getElementById('video').currentTime = 2")
            original_slots = page.locator(".wedge").evaluate_all(
                "slots => slots.map(slot => Number(slot.dataset.scene))"
            )
            current_slot = original_slots.index(winner)
            page.locator("#next-scene").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "returning")
            assert video.evaluate("element => element === document.getElementById('video')")
            assert video.evaluate("element => getComputedStyle(element).opacity") == "1"
            page.wait_for_timeout(400)
            returned_tile = page.locator("#wheel image").nth(current_slot).element_handle()
            page.screenshot(path=str(output / "return-to-wheel.png"))
            page.wait_for_function("state.phase === 'spinning'", timeout=6000, polling=20)
            assert returned_tile.evaluate("element => element.isConnected")
            assert returned_tile.evaluate(
                "element => (window.heldTileFrame = element.getAttribute('href'))"
                ".startsWith('data:image/png')"
            )
            assert (
                page.locator(".wedge").evaluate_all(
                    "slots => slots.map(slot => Number(slot.dataset.scene))"
                )
                == original_slots
            )
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing", timeout=8000)
            assert returned_tile.evaluate("element => element.isConnected")
            assert returned_tile.evaluate(
                "element => element.getAttribute('href') === window.heldTileFrame"
            )
            assert (
                page.locator(".wedge").evaluate_all(
                    "slots => slots.map(slot => Number(slot.dataset.scene))"
                )
                == original_slots
            )
            assert page.evaluate("state.history[state.index].scene.id") != winner
            page.locator("#previous").click()
            assert page.evaluate("state.history[state.index].scene.id") == winner
            page.wait_for_function(
                "document.getElementById('video').currentTime >= 1.9", timeout=3000
            )
            page.mouse.move(721, 501)
            page.locator("#mute").click()
            expect(page.locator("#mute")).to_have_attribute("aria-pressed", "true")
            page.locator("#exit").click()
            expect(page.locator("#experience")).not_to_be_visible()
            page.reload()
            expect(page.locator("#mute")).to_have_attribute("aria-pressed", "true")

            page.emulate_media(reduced_motion="reduce")
            page.locator('[data-lane="Best Bets"]').click()
            expect(page.locator(".card")).to_have_count(8)
            page.locator("#launch").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing")
            # Actual media-ended path advances without a button click.
            page.wait_for_function("document.getElementById('video').readyState >= 2")
            page.evaluate("document.getElementById('video').currentTime = 9.99")
            page.wait_for_function("state.seen.size === 2 && state.phase === 'playing'")
            for _ in range(6):
                page.locator("#next-scene").click()
                expect(page.locator("#stage")).to_have_attribute("data-phase", "playing")
            assert page.evaluate("state.seen.size") == 8
            ids = page.evaluate("state.history.map(entry => entry.scene.id)")
            assert len(set(ids)) == 8 and all(scene_id < 8 for scene_id in ids)
            page.locator("#next-scene").click()
            expect(page.locator("#exhausted")).to_be_visible()
            page.screenshot(path=str(output / "exhausted.png"))
            page.locator("#restart").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing")
            assert page.evaluate("state.seen.size") == 1
            page.locator("#exit").click()

            page.emulate_media(reduced_motion="no-preference")
            page.locator("#launch").click()
            page.locator("#exit").click()
            page.wait_for_timeout(3100)
            expect(page.locator("#experience")).not_to_be_visible()
            assert page.evaluate("state.phase") == "idle"
            assert page.evaluate("document.getElementById('video').paused")
            page.locator("#launch").click()
            page.wait_for_function("state.phase === 'revealing'", timeout=12000, polling=50)
            page.locator("#exit").click()
            page.wait_for_timeout(1500)
            assert page.evaluate("state.phase") == "idle"
            assert page.evaluate("document.getElementById('video').getAnimations().length") == 0
            page.emulate_media(reduced_motion="reduce")
            page.locator("#launch").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing")
            page.emulate_media(reduced_motion="no-preference")
            page.locator("#next-scene").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "returning")
            page.locator("#exit").click()
            page.wait_for_timeout(1300)
            assert page.evaluate("state.phase") == "idle"
            expect(page.locator("#experience")).not_to_be_visible()
            # The player container owns fullscreen, so overlay controls stay inside.
            page.emulate_media(reduced_motion="reduce")
            page.locator("#play-lane").click()
            expect(page.locator("#stage")).to_have_attribute("data-phase", "playing")
            page.locator("#fullscreen").click()
            page.wait_for_function("document.fullscreenElement?.id === 'stage'")
            expect(page.locator("#next-scene")).to_be_visible()
            page.locator("#exit").click()
            page.wait_for_function("!document.fullscreenElement")

            mobile = browser.new_page(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
            )
            mobile.on("pageerror", lambda error: errors.append(str(error)))
            mobile.goto(url)
            mobile.screenshot(path=str(output / "mobile.png"))
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
            mobile.locator("#launch").click()
            mobile.wait_for_timeout(600)
            expect(mobile.locator(".wedge")).to_have_count(16)
            mobile.screenshot(path=str(output / "mobile-wheel.png"))
            expect(mobile.locator("#stage")).to_have_attribute(
                "data-phase", "playing", timeout=8000
            )
            mobile.screenshot(path=str(output / "mobile-playing.png"))
            initial_slots = mobile.locator(".wedge").evaluate_all(
                "slots => slots.map(slot => Number(slot.dataset.scene))"
            )
            mobile.emulate_media(reduced_motion="reduce")
            mobile.touchscreen.tap(195, 422)
            mobile.locator("#next-scene").click()
            expect(mobile.locator("#stage")).to_have_attribute("data-phase", "playing")
            protected_id = mobile.evaluate("state.history[state.index].scene.id")
            protected_slot = initial_slots.index(protected_id)
            mobile.evaluate(
                "window.slotChanges = []; window.spinStart = state.rotation;"
                "new MutationObserver(records => records.forEach(record => {"
                "window.slotChanges.push({phase:state.phase, delta:state.rotation-window.spinStart,"
                "slot:Array.from(document.querySelectorAll('.wedge')).indexOf(record.target)});"
                "})).observe(document.getElementById('wheel'),"
                "{subtree:true,attributes:true,attributeFilter:['data-scene']})"
            )
            mobile.locator("#next-scene").click()
            expect(mobile.locator("#stage")).to_have_attribute("data-phase", "playing")
            updated_slots = mobile.locator(".wedge").evaluate_all(
                "slots => slots.map(slot => Number(slot.dataset.scene))"
            )
            assert updated_slots[protected_slot] == protected_id
            assert len(set(updated_slots)) == 16
            assert set(updated_slots) - set(initial_slots)
            assert (
                mobile.evaluate("state.history[0].wheel.contenders.map(scene => scene.id)")
                == initial_slots
            )
            changes = mobile.evaluate("window.slotChanges")
            assert changes and all(
                change["phase"] == "spinning"
                and change["delta"] >= 360 / 16
                and change["slot"] != protected_slot
                for change in changes
            )
            assert mobile.evaluate("state.seen.size") == 3
            mobile.keyboard.press("Escape")
            expect(mobile.locator("#experience")).not_to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(
        "PASS: selection, playback, back/resume, no repeats, lane scope, auto-next, "
        "exhaustion, restart, cancellation, mute persistence, fullscreen and mobile. "
        f"Screenshots: {output}"
    )


if __name__ == "__main__":
    run()
