"""Record the docs tour from a Stash started by up.sh and encode the docs assets.

Captures Chromium's screencast frames over CDP. Capture pauses while a page loads,
so the tour has no spinners, then ffmpeg rebuilds a constant-rate video from the
frame timestamps. A drawn cursor shows where each click lands.

Usage:
  python scripts/tour/record.py --stash-url http://localhost:9998
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import CDPSession, Locator, Page, sync_playwright

CURATOR = "/plugins/stash-curator"
VIEWPORT = {"width": 1280, "height": 900}  # docs pages show it at 960x675

CURSOR_SCRIPT = """
addEventListener("DOMContentLoaded", () => {
  const cursor = document.createElement("div");
  cursor.id = "tour-cursor";
  cursor.innerHTML = `<svg width="22" height="22" viewBox="0 0 22 22">
    <path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z"
    fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  Object.assign(cursor.style, {position: "fixed", left: "0", top: "0", zIndex: 2147483647,
    pointerEvents: "none", transform: "translate(-100px, -100px)",
    filter: "drop-shadow(0 1px 2px #0008)"});
  document.documentElement.appendChild(cursor);
  const at = sessionStorage.getItem("tour-cursor");
  if (at) cursor.style.transform = at;
  addEventListener("mousemove", (event) => {
    cursor.style.transform = `translate(${event.clientX - 3}px, ${event.clientY - 2}px)`;
    sessionStorage.setItem("tour-cursor", cursor.style.transform);
  }, true);
  addEventListener("mousedown", (event) => {
    const ring = document.createElement("div");
    Object.assign(ring.style, {position: "fixed",
      left: `${event.clientX - 18}px`, top: `${event.clientY - 18}px`,
      width: "36px", height: "36px", borderRadius: "50%", border: "3px solid #f5c542",
      zIndex: 2147483646,
      pointerEvents: "none", transition: "transform .45s ease-out, opacity .45s ease-out"});
    document.documentElement.appendChild(ring);
    requestAnimationFrame(() => { ring.style.transform = "scale(1.8)"; ring.style.opacity = "0"; });
    setTimeout(() => ring.remove(), 500);
  }, true);
});
"""


class Recorder:
    """Collects screencast frames into segments; paused time is cut from the video."""

    def __init__(self, page: Page, cdp: CDPSession, frames: Path) -> None:
        self.page, self.cdp, self.frames = page, cdp, frames
        self.timeline: list[tuple[float, Path]] = []
        self.offset = 0.0  # video time where the current segment starts
        self.rolled_at: float | None = None  # wall time the current segment started
        self.markers: dict[str, float] = {}
        cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, event: dict) -> None:
        self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        if self.rolled_at is None:
            return  # a frame still in flight from before the cut
        at = self.now(event["metadata"]["timestamp"])
        path = self.frames / f"{len(self.timeline):06d}.jpg"
        path.write_bytes(base64.b64decode(event["data"]))
        self.timeline.append((max(at, self.offset), path))

    def now(self, wall: float | None = None) -> float:
        assert self.rolled_at is not None, "not recording"
        return self.offset + (wall or time.time()) - self.rolled_at

    def roll(self) -> None:
        self.rolled_at = time.time()
        self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 92, "maxWidth": VIEWPORT["width"],
             "maxHeight": VIEWPORT["height"], "everyNthFrame": 1},
        )  # fmt: skip

    def cut(self) -> None:
        # Frames arrive only when pixels change, so repeat the last one to keep
        # a still ending on screen until the cut.
        if self.rolled_at is None:
            return
        end = self.now()
        self.rolled_at = None
        self.cdp.send("Page.stopScreencast")
        self.page.wait_for_timeout(100)
        if self.timeline:
            self.timeline.append((end, self.timeline[-1][1]))
        self.offset = end

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def mark(self, name: str) -> None:
        self.markers[name] = self.now()


def glide(page: Page, target: Locator, *, steps: int = 24) -> None:
    box = target.bounding_box()
    if box is None:
        raise RuntimeError(f"{target} is not visible")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)
    page.wait_for_timeout(180)


def click(page: Page, target: Locator) -> None:
    target.scroll_into_view_if_needed()
    glide(page, target)
    page.mouse.down()
    page.mouse.up()


def settle(rec: Recorder, page: Page, ready: Locator, count: int = 1) -> None:
    """Wait off camera until `count` matches of `ready` render and media settle."""
    rec.cut()
    ready.nth(count - 1).wait_for(timeout=60000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    rec.roll()


def open_page(rec: Recorder, page: Page, url: str, ready: Locator, count: int = 1) -> None:
    rec.cut()
    page.goto(url)
    settle(rec, page, ready, count)


def storyboard(rec: Recorder, page: Page, base: str, similar_id: str) -> None:
    # 1. Curator's lanes inside Stash's own home page.
    open_page(rec, page, base + "/", page.locator("text=View in Curator"))
    page.mouse.move(640, 300)
    rec.hold(0.8)
    glide(page, page.locator(".scene-card").first)  # hover plays the preview
    rec.hold(1.4)
    click(page, page.get_by_text("View in Curator").first)
    rec.hold(0.4)  # let the click ring finish before cutting the load

    # 2. For You cards, an explanation, then the moving Wall.
    settle(rec, page, page.locator(".scene-card"), 3)
    page.mouse.move(1000, 250, steps=12)  # clear of the controls for the poster frame
    rec.hold(1.0)
    rec.mark("poster")
    click(page, page.get_by_text("Why this?").first)
    rec.hold(2.6)
    click(page, page.get_by_role("button", name="Wall"))
    rec.hold(2.8)

    # 3. Roulette spins the lane and lands in Stash's player.
    page.mouse.wheel(0, -2000)
    click(page, page.get_by_role("button", name="Roulette"))
    page.locator(".curator-roulette-player video").first.wait_for(timeout=30000)
    rec.hold(2.5)

    # 4. Similar scenes from the library.
    open_page(
        rec, page, f"{base}{CURATOR}?view=similar&id={similar_id}",
        page.locator(".scene-card"), 6,
    )  # fmt: skip
    page.mouse.move(900, 200, steps=10)
    rec.hold(1.0)
    rec.mark("find")
    rec.hold(1.8)

    # 5. Curate: one tag question with preview clips.
    open_page(
        rec, page, f"{base}{CURATOR}?view=curate",
        page.get_by_text("Tag questions").first,
    )  # fmt: skip
    rec.hold(1.0)
    glide(page, page.get_by_text("Slight like", exact=True).first)
    rec.hold(1.6)
    rec.cut()


def gql(base: str, query: str) -> dict:
    request = urllib.request.Request(
        base + "/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())["data"]


def encode(
    timeline: list[tuple[float, Path]], markers: dict[str, float], work: Path, assets: Path
) -> None:
    listing = work / "frames.txt"
    lines = []
    for (at, path), (next_at, _) in zip(
        timeline, [*timeline[1:], (timeline[-1][0] + 0.5, None)], strict=True
    ):
        lines += [f"file '{path.resolve()}'", f"duration {max(next_at - at, 0.001):.4f}"]
    listing.write_text("\n".join([*lines, f"file '{timeline[-1][1].resolve()}'"]) + "\n")
    master = work / "tour-master.mp4"
    ffmpeg = ["ffmpeg", "-v", "error", "-y"]
    subprocess.run(
        [*ffmpeg, "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "fps=30", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
         str(master)],
        check=True,
    )  # fmt: skip
    subprocess.run(
        [*ffmpeg, "-i", str(master), "-c:v", "libx264", "-crf", "24", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(assets / "showcase-tour.mp4")],
        check=True,
    )  # fmt: skip
    subprocess.run(
        [*ffmpeg, "-i", str(master), "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0",
         "-row-mt", "1", str(assets / "showcase-tour.webm")],
        check=True,
    )  # fmt: skip
    subprocess.run(
        [*ffmpeg, "-i", str(master), "-vf",
         "fps=8,scale=760:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
         "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
         str(assets / "showcase-tour.gif")],
        check=True,
    )  # fmt: skip
    for name, asset in (
        ("poster", "showcase-tour-poster.jpg"),
        ("find", "showcase-find-poster.jpg"),
    ):
        subprocess.run(
            [*ffmpeg, "-ss", f"{markers[name]:.2f}", "-i", str(master), "-frames:v", "1",
             "-q:v", "3", str(assets / asset)],
            check=True,
        )  # fmt: skip
    print(f"{timeline[-1][0]:.1f}s tour written to {assets}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stash-url", default="http://localhost:9998")
    parser.add_argument("--work", type=Path, default=Path(".tmp/tour"))
    parser.add_argument("--assets", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    base = args.stash_url.rstrip("/")
    frames = args.work / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    args.assets.mkdir(parents=True, exist_ok=True)
    scenes = gql(
        base,
        """{ findScenes(
            scene_filter: {title: {value: "Big Buck Bunny", modifier: INCLUDES}}
            filter: {per_page: 1, sort: "title"}
        ) { scenes { id } } }""",
    )
    similar_id = scenes["findScenes"]["scenes"][0]["id"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        context = browser.new_context(viewport=VIEWPORT, reduced_motion="no-preference")
        context.add_init_script(CURSOR_SCRIPT)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        recorder = Recorder(page, context.new_cdp_session(page), frames)
        started = time.monotonic()
        storyboard(recorder, page, base, similar_id)
        browser.close()
    if errors:
        raise SystemExit(f"page errors during the tour: {errors}")
    print(f"captured {len(recorder.timeline)} frames in {time.monotonic() - started:.0f}s")
    encode(recorder.timeline, recorder.markers, args.work, args.assets)


if __name__ == "__main__":
    main()
