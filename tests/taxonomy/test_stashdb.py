import json
from collections.abc import Mapping

from curator.graphql import GraphQLClient
from curator.taxonomy import StashDBTaxonomyClient


def test_fetches_categories_and_paginated_tags_with_queries_only() -> None:
    operations: list[tuple[str, dict[str, object]]] = []

    def transport(_url: str, _headers: Mapping[str, str], body: bytes, _timeout: float) -> bytes:
        request = json.loads(body)
        document = request["query"]
        variables = request["variables"]
        operations.append((document, variables))
        if "queryTagCategories" in document:
            data = {
                "queryTagCategories": {
                    "count": 1,
                    "tag_categories": [
                        {
                            "id": "body",
                            "name": "Body Type",
                            "group": "PEOPLE",
                            "description": "Appearance",
                        }
                    ],
                }
            }
        elif variables["page"] == 1:
            data = {
                "queryTags": {
                    "count": 2,
                    "tags": [
                        {
                            "id": "athletic",
                            "name": "Athletic",
                            "aliases": ["Athletic Body"],
                            "category": {"id": "body"},
                        }
                    ],
                }
            }
        else:
            data = {
                "queryTags": {
                    "count": 2,
                    "tags": [
                        {
                            "id": "office",
                            "name": "Office",
                            "aliases": [],
                            "category": None,
                        }
                    ],
                }
            }
        return json.dumps({"data": data}).encode()

    client = GraphQLClient("https://stashdb.org/graphql", transport=transport)
    result = StashDBTaxonomyClient(client, page_size=1).fetch()

    assert result.endpoint == "https://stashdb.org/graphql"
    assert [tag.tag_id for tag in result.tags] == ["athletic", "office"]
    assert result.tags[0].aliases == ("Athletic Body",)
    assert len(operations) == 3
    assert all(document.lstrip().startswith("query") for document, _ in operations)
