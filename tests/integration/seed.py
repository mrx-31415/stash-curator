"""Seed a Stash instance with minimal data for Curator integration tests.

Creates tags, performers, and scenes via Stash's GraphQL API, then
triggers a Curator sync and model build.

Usage:
  python tests/integration/seed.py --stash-url http://localhost:9999
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any, cast

MUTATION_TAG_CREATE = """
mutation TagCreate($input: TagCreateInput!) {
  tagCreate(input: $input) {
    id
    name
  }
}
"""

MUTATION_PERFORMER_CREATE = """
mutation PerformerCreate($input: PerformerCreateInput!) {
  performerCreate(input: $input) {
    id
    name
  }
}
"""

MUTATION_SCENE_CREATE = """
mutation SceneCreate($input: SceneCreateInput!) {
  sceneCreate(input: $input) {
    id
    title
  }
}
"""

QUERY_FIND_TAG = """
query FindTag($name: String!) {
  findTags(tag_filter: {name: {value: $name, modifier: EQUALS}}) {
    tags { id name }
  }
}
"""

QUERY_FIND_PERFORMER = """
query FindPerformer($name: String!) {
  findPerformers(performer_filter: {name: {value: $name, modifier: EQUALS}}) {
    performers { id name }
  }
}
"""

QUERY_FIND_SCENE = """
query FindScene($title: String!) {
  findScenes(
    scene_filter: {title: {value: $title, modifier: EQUALS}}
    filter: {page: 1, per_page: 1}
  ) { scenes { id } }
}
"""

SEED_TAGS = [
    {"name": "Blowjob"},
    {"name": "Anal"},
    {"name": "Outdoor"},
    {"name": "Threesome"},
    {"name": "Creampie"},
    {"name": "Solo"},
    {"name": "Lesbian"},
    {"name": "BDSM"},
    {"name": "Cosplay"},
    {"name": "MILF"},
]

SEED_PERFORMERS = [
    {"name": "Test Performer One", "gender": "FEMALE"},
    {"name": "Test Performer Two", "gender": "FEMALE"},
    {"name": "Test Performer Male", "gender": "MALE"},
]

SEED_SCENES = [
    {
        "title": "Test Scene Outdoor Fun",
        "details": "A test scene filmed outdoors.",
        "date": "2025-01-15",
        "tag_names": ["Blowjob", "Outdoor"],
        "performer_names": ["Test Performer One", "Test Performer Male"],
    },
    {
        "title": "Test Scene Threesome Party",
        "details": "Two performers and a guest star.",
        "date": "2025-02-20",
        "tag_names": ["Threesome", "Creampie"],
        "performer_names": ["Test Performer One", "Test Performer Two", "Test Performer Male"],
    },
    {
        "title": "Test Scene Solo Stretch",
        "details": "Solo performance.",
        "date": "2025-03-10",
        "tag_names": ["Solo", "Cosplay"],
        "performer_names": ["Test Performer Two"],
    },
    {
        "title": "Test Scene Anal Adventure",
        "details": "Anal-focused scene.",
        "date": "2025-04-05",
        "tag_names": ["Anal", "Creampie", "MILF"],
        "performer_names": ["Test Performer One"],
    },
    {
        "title": "Test Scene Lesbian Encounter",
        "details": "Girl-on-girl action.",
        "date": "2025-05-18",
        "tag_names": ["Lesbian", "BDSM"],
        "performer_names": ["Test Performer One", "Test Performer Two"],
    },
]


def stash_request(
    stash_url: str, query: str, variables: dict[str, object] | None = None
) -> dict[str, Any]:
    """Make a GraphQL request to the Stash instance."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"{stash_url}/graphql",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read())
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return cast(dict[str, Any], data["data"])


def create_tags(stash_url: str) -> dict[str, str]:
    """Find-or-create seed tags and return a {name: id} mapping.

    The integration harness reuses the Stash config directory between runs, so the
    database outlives a container teardown; re-seeding must not collide.
    """
    tag_ids: dict[str, str] = {}
    for tag_def in SEED_TAGS:
        existing = stash_request(stash_url, QUERY_FIND_TAG, {"name": tag_def["name"]})["findTags"][
            "tags"
        ]
        match = next((item for item in existing if str(item.get("name")) == tag_def["name"]), None)
        if match is not None:
            tag_id = str(match["id"])
            print(f"  tag: {tag_def['name']} ({tag_id}) [exists]")
        else:
            data = stash_request(stash_url, MUTATION_TAG_CREATE, {"input": tag_def})
            tag_id = data["tagCreate"]["id"]
            print(f"  tag: {tag_def['name']} ({tag_id})")
        tag_ids[tag_def["name"]] = tag_id
    return tag_ids


def create_performers(stash_url: str) -> dict[str, str]:
    """Find-or-create seed performers and return a {name: id} mapping."""
    performer_ids: dict[str, str] = {}
    for perf in SEED_PERFORMERS:
        existing = stash_request(stash_url, QUERY_FIND_PERFORMER, {"name": perf["name"]})[
            "findPerformers"
        ]["performers"]
        match = next((item for item in existing if str(item.get("name")) == perf["name"]), None)
        if match is not None:
            perf_id = str(match["id"])
            print(f"  performer: {perf['name']} ({perf_id}) [exists]")
        else:
            data = stash_request(stash_url, MUTATION_PERFORMER_CREATE, {"input": perf})
            perf_id = data["performerCreate"]["id"]
            print(f"  performer: {perf['name']} ({perf_id})")
        performer_ids[perf["name"]] = perf_id
    return performer_ids


def create_scenes(
    stash_url: str, tag_ids: dict[str, str], performer_ids: dict[str, str]
) -> list[str]:
    """Find-or-create seed scenes with tag and performer links."""
    scene_ids: list[str] = []
    for scene in SEED_SCENES:
        existing = stash_request(
            stash_url,
            QUERY_FIND_SCENE,
            {"title": scene["title"]},
        )["findScenes"]["scenes"]
        if existing:
            scene_id = str(existing[0]["id"])
            scene_ids.append(scene_id)
            print(f"  scene: {scene['title']} ({scene_id}) [exists]")
            continue
        tag_list = [tag_ids[n] for n in scene["tag_names"]]
        perf_list = [performer_ids[n] for n in scene["performer_names"]]
        data = stash_request(
            stash_url,
            MUTATION_SCENE_CREATE,
            {
                "input": {
                    "title": scene["title"],
                    "details": scene["details"],
                    "date": scene["date"],
                    "tag_ids": tag_list,
                    "performer_ids": perf_list,
                }
            },
        )
        scene_id = data["sceneCreate"]["id"]
        scene_ids.append(scene_id)
        print(f"  scene: {scene['title']} ({scene_id})")
    return scene_ids


def trigger_curator_sync(stash_url: str) -> None:
    """Trigger a Curator sync-and-build and wait until a model is published.

    The sync runs as a Stash job; health reports `ready` only after the build
    has published a model, so polling it gives a deterministic "seeded and
    built" environment for the integration suite. Failure is loud: a broken
    env is easier to diagnose at seed time than as a page-render assertion.
    """
    print("  triggering curator sync …")
    stash_request(
        stash_url,
        """
        mutation CuratorSync($args: Map!) {
          runPluginTask(
            plugin_id: "stash-curator"
            task_name: "Sync and build recommendations"
            args_map: $args
          )
        }
        """,
        {"args": {}},
    )

    # Wait for the model to be published by polling the health operation.
    print("  waiting for sync to finish …")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            data = stash_request(
                stash_url,
                """
                mutation Health($args: Map!) {
                  runPluginOperation(
                    plugin_id: "stash-curator"
                    args: $args
                  )
                }
                """,
                {"args": {"operation": "health"}},
            )
            if data.get("runPluginOperation", {}).get("ready"):
                print("  sync complete")
                return
        except Exception:
            pass
        time.sleep(2)

    raise RuntimeError(
        "Curator sync-and-build did not publish a model within 180s; "
        "check the plugin logs and the Stash task queue"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Stash for Curator integration tests")
    parser.add_argument(
        "--stash-url",
        default="http://localhost:9999",
        help="Stash base URL (default: http://localhost:9999)",
    )
    args = parser.parse_args()
    stash_url = args.stash_url.rstrip("/")

    print(f"Seeding {stash_url} …")
    print("Creating tags …")
    tag_ids = create_tags(stash_url)
    print("Creating performers …")
    performer_ids = create_performers(stash_url)
    print("Creating scenes …")
    scene_ids = create_scenes(stash_url, tag_ids, performer_ids)
    print(f"Done — {len(tag_ids)} tags, {len(performer_ids)} performers, {len(scene_ids)} scenes.")
    print("Triggering curator sync …")
    trigger_curator_sync(stash_url)
    print("Seed complete.")


if __name__ == "__main__":
    main()
