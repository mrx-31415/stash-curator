"""Named read-only GraphQL operations used by Curator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntityOperation:
    """A paginated source entity query and its response keys."""

    entity_type: str
    name: str
    document: str
    root_key: str
    items_key: str


CAPABILITIES = """
query CuratorCapabilities {
  version { version }
  queryType: __type(name: "Query") { fields { name } }
  sceneType: __type(name: "Scene") { fields { name } }
  performerType: __type(name: "Performer") { fields { name } }
}
"""

TAGS = EntityOperation(
    "tag",
    "CuratorTags",
    """
query CuratorTags($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findTags(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    tags { id name updated_at parents { id name updated_at } }
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

SCENES = EntityOperation(
    "scene",
    "CuratorScenes",
    """
query CuratorScenes($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findScenes(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    scenes {
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
    }
  }
}
""",
    "findScenes",
    "scenes",
)

ENTITY_OPERATIONS = (TAGS, STUDIOS, PERFORMERS, SCENES)
ALL_DOCUMENTS = (CAPABILITIES, *(operation.document for operation in ENTITY_OPERATIONS))
