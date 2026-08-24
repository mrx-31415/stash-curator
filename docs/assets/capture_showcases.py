#!/usr/bin/env python3
"""Capture docs screenshots from the packaged Curator UI with fixture responses.

Start the disposable integration Stash first, then run this script.  Native Stash
queries are forwarded unchanged; only Curator plugin operations and scene stills
are fulfilled from the deterministic fixture below.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
COVERS = ASSETS / "showcase-covers"
SCENES = {
    "1": ("Rain Signal", "A wet midnight street beneath a flickering marquee."),
    "2": ("Northbound", "A quiet platform just before the last train leaves."),
    "3": ("The Long Hall", "A motel corridor, a suitcase, and one lit room."),
    "4": ("Still Water", "Blue tile, reflected light, and an empty night pool."),
    "5": ("Glass Hours", "A greenhouse after dark, warm light against the rain."),
}
COVER_NAMES = {
    "1": "01-rainy-street.png",
    "2": "05-train-platform.png",
    "3": "03-motel-hallway.png",
    "4": "08-night-pool.png",
    "5": "07-greenhouse.png",
}


def slate_item(scene_id: str, lane: str, appeal: float, rank: float) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "source_lane": lane,
        "subtype": "fresh match",
        "appeal": appeal,
        "lane_value": rank,
        "position": int(scene_id) - 1,
        "impression_id": "docs-fixture",
        "explanation": {
            "summary": "A strong fit for the patterns you have rated highly.",
            "evidence_rows": [
                {
                    "code": "tag.affinity",
                    "label": "Night settings",
                    "direction": "positive",
                    "confidence": 0.82,
                },
                {
                    "code": "recency",
                    "label": "Fresh in your library",
                    "direction": "context",
                    "confidence": 0.7,
                },
            ],
        },
    }


def operation(args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("operation")
    if name == "get_config":
        return {
            "updated_at_ms": 1,
            "code_version": "docs-fixture",
            "whisparr_enabled": False,
            "config": {"page_size": 20, "expand_gender": "", "diversity_enabled": True},
        }
    if name == "health":
        return {
            "last_sync_at_ms": 1_775_000_000_000,
            "model_update_ready": False,
            "model_rebuilding": False,
            "model_id": "docs-fixture",
            "ready": True,
            "sidecar_ready": True,
            "sync_ready": True,
            "stashdb_available": False,
            "active_jobs": [],
        }
    if name == "get_slate":
        items = [
            slate_item("1", "for_you", 0.81, 1.0),
            slate_item("2", "best_bets", 0.72, 0.92),
            slate_item("3", "discover", 0.61, 0.86),
            slate_item("4", "ready", 0.54, 0.77),
            slate_item("5", "for_you", 0.47, 0.68),
        ]
        return {
            "model_id": "docs-fixture",
            "lane": args.get("lane", "for_you"),
            "page": 1,
            "page_size": 20,
            "total": len(items),
            "has_more": False,
            "items": items,
        }
    if name == "get_similar":
        items = []
        for position, scene_id in enumerate(("2", "3", "4", "5")):
            items.append(
                {
                    "entity_id": scene_id,
                    "position": position,
                    "similarity": 0.91 - position * 0.09,
                    "appeal": 0.78 - position * 0.08,
                    "relationships": ["similar_structure", "shared_content"],
                    "details": {"shared_tags": ["Night", "Atmosphere"]},
                }
            )
        return {
            "model_id": "docs-fixture",
            "impression_id": "docs-similar",
            "page": 1,
            "page_size": 20,
            "total": len(items),
            "has_more": False,
            "items": items,
        }
    if name == "get_curation_picks":

        def scene(scene_id: str, tags: list[str]) -> dict[str, Any]:
            title, details = SCENES[scene_id]
            return {
                "scene_id": scene_id,
                "title": title,
                "details": details,
                "studio": "Northstar Archive",
                "date": "2026-08-24",
                "performers": [{"performer_id": "1", "name": "Ari Vale"}],
                "tags": [{"tag_id": tag.lower(), "name": tag} for tag in tags],
            }

        return {
            "round_id": "docs-round",
            "pairs": [
                {
                    "pair_id": "docs-pair-1",
                    "scene_a": scene("1", ["Night", "Rain"]),
                    "scene_b": scene("5", ["Night", "Glass"]),
                }
            ],
        }
    return {"accepted": 1, "items": [], "jobs": []}


def patch_stash_response(payload: dict[str, Any]) -> dict[str, Any]:
    scenes = payload.get("data", {}).get("findScenes", {}).get("scenes", [])
    for scene in scenes:
        title, details = SCENES.get(str(scene.get("id")), (None, None))
        if title:
            scene["title"], scene["details"] = title, details
    scene = payload.get("data", {}).get("findScene")
    if scene:
        title, details = SCENES.get(str(scene.get("id")), (None, None))
        if title:
            scene["title"], scene["details"] = title, details
    return payload


def install_fixture_routes(page: Page) -> None:
    def graphql(route: Route) -> None:
        request = route.request
        try:
            payload = json.loads(request.post_data or "{}")
        except json.JSONDecodeError:
            route.continue_()
            return
        if 'runPluginOperation(plugin_id: "stash-curator"' in payload.get("query", ""):
            result = operation(payload.get("variables", {}).get("args", {}))
            route.fulfill(
                content_type="application/json",
                body=json.dumps({"data": {"runPluginOperation": result}}),
            )
            return
        response = route.fetch()
        try:
            data = patch_stash_response(response.json())
        except Exception:
            route.fulfill(response=response)
            return
        route.fulfill(response=response, body=json.dumps(data), content_type="application/json")

    def still(route: Route) -> None:
        scene_id = route.request.url.split("/scene/", 1)[1].split("/", 1)[0]
        route.fulfill(
            path=COVERS / COVER_NAMES.get(scene_id, COVER_NAMES["1"]), content_type="image/png"
        )

    page.route("**/graphql", graphql)
    page.route("**/scene/*/screenshot**", still)


def capture(page: Page, base_url: str, query: str, filename: str) -> None:
    page.goto(f"{base_url}/plugins/stash-curator{query}", wait_until="domcontentloaded")
    page.locator("main.curator-page").wait_for(state="visible")
    page.wait_for_timeout(1_500)
    # The Pair picks videos never become "stable", so element screenshots wait
    # for their timeout. The viewport is the intended docs framing anyway.
    page.screenshot(path=ASSETS / filename)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:9998")
    args = parser.parse_args()
    missing = [name for name in COVER_NAMES.values() if not (COVERS / name).is_file()]
    if missing:
        raise SystemExit(f"missing showcase covers: {', '.join(missing)}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
        install_fixture_routes(page)
        capture(page, args.base_url.rstrip("/"), "?view=for_you", "showcase-recommendations.png")
        capture(
            page,
            args.base_url.rstrip("/"),
            "?view=similar&id=1&label=Rain+Signal",
            "showcase-find.png",
        )
        capture(
            page, args.base_url.rstrip("/"), "?view=curate&section=stream", "showcase-curate.png"
        )
        browser.close()


if __name__ == "__main__":
    main()
