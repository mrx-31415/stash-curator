"""Named read-only GraphQL operations used by Curator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from curator.graphql.adapters import SourceEntity


def _updated_at(item: SourceEntity) -> str | None:
    return item.updated_at


def _last_played_at(item: SourceEntity) -> str | None:
    """Stash leaves updated_at alone when it records a play, so plays need their own mark."""
    history = getattr(item, "play_history_ms", ())
    if not history:
        return None
    return datetime.fromtimestamp(max(history) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _played_since(watermark: str | None) -> dict[str, object]:
    criteria: dict[str, object] = {"play_count": {"value": 0, "modifier": "GREATER_THAN"}}
    if watermark:
        criteria["last_played_at"] = {"value": watermark, "modifier": "GREATER_THAN"}
    return {"sceneFilter": criteria}


@dataclass(frozen=True)
class EntityOperation:
    """A paginated source entity query and its response keys."""

    entity_type: str
    name: str
    document: str
    root_key: str
    items_key: str
    sort: str = "updated_at"
    watermark_of: Callable[[SourceEntity], str | None] = field(default=_updated_at)
    variables_for: Callable[[str | None], dict[str, object]] | None = None
    incremental_only: bool = False


CAPABILITIES = """
query CuratorCapabilities {
  version { version }
  queryType: __type(name: "Query") { fields { name } }
  sceneType: __type(name: "Scene") { fields { name } }
  performerType: __type(name: "Performer") { fields { name } }
  tagType: __type(name: "Tag") { fields { name } }
  sceneFilterType: __type(name: "SceneFilterType") { inputFields { name } }
}
"""

TAGS = EntityOperation(
    "tag",
    "CuratorTags",
    """
query CuratorTags($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findTags(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    tags {
      id name updated_at stash_ids { endpoint stash_id }
      parents { id name updated_at }
    }
  }
}
""",
    "findTags",
    "tags",
)

STUDIOS = EntityOperation(
    "studio",
    "CuratorStudios",
    """
query CuratorStudios($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findStudios(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    studios {
      id name favorite rating100 updated_at
      parent_studio { id name updated_at }
    }
  }
}
""",
    "findStudios",
    "studios",
)

PERFORMERS = EntityOperation(
    "performer",
    "CuratorPerformers",
    """
query CuratorPerformers(
  $page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!
) {
  findPerformers(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    performers {
      id name gender favorite rating100 birthdate ethnicity country eye_color hair_color
      height_cm weight measurements fake_tits tattoos piercings updated_at
      tags { id name updated_at }
    }
  }
}
""",
    "findPerformers",
    "performers",
)

SCENE_FIELDS = """
      id title details date rating100 updated_at play_count play_duration play_history o_history
      studio { id name favorite rating100 updated_at parent_studio { id name updated_at } }
      tags { id name updated_at }
      performers { id name updated_at }
      files { id duration }
      scene_markers {
        id seconds end_seconds
        primary_tag { id name updated_at }
        tags { id name updated_at }
      }
"""

SCENES = EntityOperation(
    "scene",
    "CuratorScenes",
    f"""
query CuratorScenes($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {{
  findScenes(filter: {{page: $page, per_page: $perPage, sort: $sort, direction: $direction}}) {{
    count
    scenes {{{SCENE_FIELDS}}}
  }}
}}
""",
    "findScenes",
    "scenes",
)

# Stash does not touch scenes.updated_at when it records a play, so the scene pass above can
# never observe one. This pass walks played scenes on their own last_played_at watermark.
SCENE_PLAYS = EntityOperation(
    "scene_play",
    "CuratorScenePlays",
    f"""
query CuratorScenePlays(
  $page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!,
  $sceneFilter: SceneFilterType
) {{
  findScenes(
    filter: {{page: $page, per_page: $perPage, sort: $sort, direction: $direction}}
    scene_filter: $sceneFilter
  ) {{
    count
    scenes {{{SCENE_FIELDS}}}
  }}
}}
""",
    "findScenes",
    "scenes",
    sort="last_played_at",
    watermark_of=_last_played_at,
    variables_for=_played_since,
    incremental_only=True,
)

ENTITY_OPERATIONS = (TAGS, STUDIOS, PERFORMERS, SCENES, SCENE_PLAYS)
ALL_DOCUMENTS = (CAPABILITIES, *(operation.document for operation in ENTITY_OPERATIONS))
