"""Seed a throwaway Stash with the tour library and a fictional viewing history.

Scans the clips from media.py, gives them fictional studios, performers, and
tags, then writes plays, O events, and ratings so every lane has a reason to
exist: an old favourite studio for Dormant and Revisit, a current one for
For You, a disliked one, and an unwatched one for Blind Spots.

Usage:
  python scripts/tour/seed.py --stash-url http://localhost:9998 --media .tmp/tour/media
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# film key -> (studio, film title shown in scene titles, performers, base tags)
FILMS = {
    "bbb": (
        "Meadowlight Pictures",
        "Big Buck Bunny",
        ["Juniper Vale", "Rowan Pike", "Hazel Brook"],
        ["Meadow", "Wildlife", "Slapstick"],
    ),
    "llamigos": (
        "Highland Shorts",
        "Caminandes: Llamigos",
        ["Sierra Moss", "Pip Larkin", "Dax Alder"],
        ["Snow", "Mountains", "Friendship"],
    ),
    "glasshalf": (
        "Frame & Folly",
        "Glass Half",
        ["Ivy Marlowe", "Felix Gray", "Opal Quinn"],
        ["Gallery", "Satire", "Dialogue"],
    ),
    "dweebs": (
        "Pocket Pictures",
        "The Daily Dweebs",
        ["Wren Calloway"],
        ["Pets", "Backyard", "Chase"],
    ),
}
SCENE_WORDS = [
    "Morning", "Hideout", "Detour", "Encore", "Standoff", "Daydream", "Ambush",
    "Overture", "Getaway", "Reunion", "Showdown", "Lookout", "Finale", "Interlude",
]  # fmt: skip
# Similar filters to female performers by default, so most of the cast needs a gender.
MALE = {"Rowan Pike", "Dax Alder", "Felix Gray", "Pip Larkin"}
EXTRA_TAGS = ["Sunlit", "Close-up", "Ensemble", "Golden Hour", "Wide Shot"]

DAY = timedelta(days=1)


class Stash:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def __call__(self, query: str, **variables: object) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.url}/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read())
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        return body["data"]

    def wait_for_jobs(self, label: str) -> None:
        time.sleep(1)
        while self("query { jobQueue { id description progress } }")["jobQueue"]:
            time.sleep(1)
        print(f"  {label} finished")


def scan(stash: Stash) -> None:
    stash(
        "mutation($partial: Map!) { configureUI(partial: $partial) }",
        partial={"lastNoteSeen": 99991231},
    )
    stash(
        """mutation($input: ConfigGeneralInput!) {
            configureGeneral(input: $input) { stashes { path } }
        }""",
        input={"stashes": [{"path": "/media", "excludeImage": True, "excludeVideo": False}]},
    )
    stash(
        """mutation { metadataScan(input: {
            scanGenerateCovers: true, scanGeneratePreviews: true, scanGenerateSprites: true
        }) }"""
    )
    stash.wait_for_jobs("scan and generate")


def create(stash: Stash, kind: str, names: set[str]) -> dict[str, str]:
    ids = {}
    for name in sorted(names):
        fields: dict[str, object] = {"name": name}
        if kind == "performer":
            fields["gender"] = "MALE" if name in MALE else "FEMALE"
        result = stash(
            f"mutation($input: {kind.title()}CreateInput!) "
            f"{{ {kind}Create(input: $input) {{ id }} }}",
            input=fields,
        )
        ids[name] = result[f"{kind}Create"]["id"]
    return ids


def describe(clips: list[dict[str, Any]], stash: Stash) -> dict[str, dict[str, Any]]:
    """Give every scanned clip fictional metadata; return scene info keyed by file."""
    studios = create(stash, "studio", {film[0] for film in FILMS.values()})
    performers = create(stash, "performer", {p for film in FILMS.values() for p in film[2]})
    tags = create(stash, "tag", {t for film in FILMS.values() for t in film[3]} | set(EXTRA_TAGS))
    found = stash(
        "query { findScenes(filter: {per_page: -1}) { scenes { id files { basename } } } }"
    )
    by_file = {
        scene["files"][0]["basename"]: scene["id"] for scene in found["findScenes"]["scenes"]
    }
    rng = random.Random(31415)
    scenes = {}
    for clip in clips:
        studio, title, cast, base_tags = FILMS[clip["film"]]
        index = clip["index"]
        word = SCENE_WORDS[(index - 1) % len(SCENE_WORDS)]
        lineup = rng.sample(cast, k=min(len(cast), rng.choice((1, 2, 2))))
        tag_names = rng.sample(base_tags, k=2) + rng.sample(EXTRA_TAGS, k=1)
        scene_id = by_file[clip["file"]]
        stash(
            "mutation($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }",
            input={
                "id": scene_id,
                "title": f"{title}: {word}",
                "date": f"20{14 + index % 10}-0{1 + index % 9}-1{index % 9}",
                "details": f"A fictional demo scene cut from {title}.",
                "studio_id": studios[studio],
                "performer_ids": [performers[p] for p in lineup],
                "tag_ids": [tags[t] for t in tag_names],
            },
        )
        scenes[clip["file"]] = {"id": scene_id, **clip}
    print(f"  described {len(scenes)} scenes")
    return scenes


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def watch(
    stash: Stash,
    scene_id: str,
    days_ago: list[float],
    *,
    finish: float,
    rating: int | None = None,
    os: int = 0,
) -> None:
    now = datetime.now(UTC)
    times = [now - DAY * days for days in days_ago]
    stash(
        "mutation($id: ID!, $times: [Timestamp!]) "
        "{ sceneAddPlay(id: $id, times: $times) { count } }",
        id=scene_id,
        times=[stamp(t) for t in times],
    )
    stash(
        "mutation($id: ID!, $d: Float) { sceneSaveActivity(id: $id, playDuration: $d) }",
        id=scene_id,
        d=12.0 * finish * len(times),
    )
    if os:
        stash(
            "mutation($id: ID!, $times: [Timestamp!]) "
            "{ sceneAddO(id: $id, times: $times) { count } }",
            id=scene_id,
            times=[stamp(t + timedelta(minutes=8)) for t in times[:os]],
        )
    if rating is not None:
        stash(
            "mutation($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }",
            input={"id": scene_id, "rating100": rating},
        )


def history(stash: Stash, scenes: dict[str, dict[str, Any]]) -> None:
    def scene(film: str, index: int) -> str:
        return scenes[f"{film}-{index:02d}.mp4"]["id"]

    # An old favourite: Meadowlight was watched a lot, then parked (Dormant, Revisit).
    for index in range(1, 9):
        base = 140 + index * 22
        watch(
            stash, scene("bbb", index), [base, base - 30, base - 55][: 1 + index % 3],
            finish=0.9, rating=(90, 80, 100)[index % 3], os=index % 2,
        )  # fmt: skip
    # The current favourite: Frame & Folly, watched recently (For You, Best Bets).
    for index, days in zip(range(1, 6), (2, 5, 9, 14, 21), strict=True):
        watch(stash, scene("glasshalf", index), [days, days + 30], finish=1.0, rating=90, os=1)
    # Highland Shorts: tried and mostly abandoned.
    watch(stash, scene("llamigos", 1), [40], finish=0.15, rating=30)
    watch(stash, scene("llamigos", 2), [33], finish=0.2)
    watch(stash, scene("llamigos", 3), [12], finish=0.8, rating=70)
    # Pocket Pictures stays unwatched for Blind Spots.
    print("  wrote viewing history")


def build(stash: Stash) -> None:
    stash(
        """mutation { runPluginTask(plugin_id: "stash-curator",
            task_name: "Sync and build recommendations", args_map: {}) }"""
    )
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        health = stash(
            """mutation { runPluginOperation(plugin_id: "stash-curator",
                args: {operation: "health"}) }"""
        )["runPluginOperation"]
        if health and health.get("ready"):
            print("  Curator model published")
            return
        time.sleep(2)
    raise SystemExit("Curator did not publish a model within 10 minutes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stash-url", default="http://localhost:9998")
    parser.add_argument("--media", type=Path, default=Path(".tmp/tour/media"))
    args = parser.parse_args()
    stash = Stash(args.stash_url)
    clips = json.loads((args.media / "clips.json").read_text())
    print("Scanning …")
    scan(stash)
    print("Describing …")
    scenes = describe(clips, stash)
    history(stash, scenes)
    print("Building Curator …")
    build(stash)


if __name__ == "__main__":
    main()
