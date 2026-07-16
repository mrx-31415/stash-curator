"""Read the public StashDB tag taxonomy through query-only GraphQL."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from curator.graphql.client import GraphQLClient

CATEGORIES = """
query CuratorTagCategories {
  queryTagCategories {
    count
    tag_categories { id name group description }
  }
}
"""

TAGS = """
query CuratorTaxonomyTags($page: Int!, $perPage: Int!) {
  queryTags(input: {page: $page, per_page: $perPage, sort: NAME, direction: ASC}) {
    count
    tags { id name aliases category { id } }
  }
}
"""


@dataclass(frozen=True)
class TaxonomyCategory:
    category_id: str
    name: str
    group: str
    description: str | None


@dataclass(frozen=True)
class TaxonomyTag:
    tag_id: str
    name: str
    aliases: tuple[str, ...]
    category_id: str | None


@dataclass(frozen=True)
class TaxonomyData:
    endpoint: str
    categories: tuple[TaxonomyCategory, ...]
    tags: tuple[TaxonomyTag, ...]


class StashDBTaxonomyClient:
    def __init__(self, client: GraphQLClient, *, page_size: int = 500) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.client = client
        self.page_size = page_size

    def fetch(self) -> TaxonomyData:
        category_data = _mapping(self.client.execute(CATEGORIES).get("queryTagCategories"))
        category_rows = _list(category_data.get("tag_categories"))
        categories = tuple(
            sorted(
                (
                    TaxonomyCategory(
                        _required(row, "id"),
                        _required(row, "name"),
                        _required(row, "group"),
                        str(row["description"]) if row.get("description") else None,
                    )
                    for row in map(_mapping, category_rows)
                ),
                key=lambda item: item.category_id,
            )
        )

        tags: list[TaxonomyTag] = []
        page = 1
        total = 0
        while True:
            data = _mapping(
                self.client.execute(TAGS, {"page": page, "perPage": self.page_size}).get(
                    "queryTags"
                )
            )
            raw_tags = _list(data.get("tags"))
            total = _integer(data.get("count"), "queryTags.count")
            for raw in map(_mapping, raw_tags):
                category = raw.get("category")
                category_id = _required(_mapping(category), "id") if category is not None else None
                aliases = tuple(
                    sorted(
                        {
                            str(alias).strip()
                            for alias in _list(raw.get("aliases"))
                            if str(alias).strip()
                        },
                        key=str.casefold,
                    )
                )
                tags.append(
                    TaxonomyTag(
                        _required(raw, "id"),
                        _required(raw, "name"),
                        aliases,
                        category_id,
                    )
                )
            if not raw_tags or len(tags) >= total:
                break
            page += 1
        return TaxonomyData(
            self.client.url,
            categories,
            tuple(sorted(tags, key=lambda item: item.tag_id)),
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError("StashDB taxonomy response contains a non-object")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError("StashDB taxonomy response contains a non-list")
    return value


def _required(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"StashDB taxonomy response is missing {key}")
    return item


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"StashDB taxonomy response has invalid {label}")
    return value
