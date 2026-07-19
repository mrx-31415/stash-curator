import json
from collections.abc import Mapping

import pytest

from curator.graphql.client import GraphQLClient, GraphQLError
from curator.graphql.operations import ALL_DOCUMENTS


def test_every_packaged_document_is_an_explicit_query() -> None:
    assert ALL_DOCUMENTS
    assert all(document.lstrip().startswith("query ") for document in ALL_DOCUMENTS)


def test_client_sends_named_query_and_api_key() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> bytes:
        captured.update(url=url, headers=dict(headers), body=json.loads(body), timeout=timeout)
        return b'{"data":{"version":{"version":"v-test"}}}'

    client = GraphQLClient("http://stash.local", api_key="secret", transport=transport)
    result = client.execute("query TestVersion { version { version } }")

    assert result["version"] == {"version": "v-test"}
    assert captured["url"] == "http://stash.local/graphql"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "ApiKey": "secret",
    }
    assert captured["body"] == {
        "query": "query TestVersion { version { version } }",
        "variables": {},
    }


@pytest.mark.parametrize(
    "document",
    ["mutation Unsafe { doSomething }", "subscription Unsafe { events }", "{ version }"],
)
def test_client_rejects_every_non_query_operation(document: str) -> None:
    client = GraphQLClient("http://stash.local", transport=lambda *_: b"{}")
    with pytest.raises(GraphQLError, match="query operations only"):
        client.execute(document)


def test_mutations_require_the_explicit_method() -> None:
    captured: dict[str, object] = {}

    def transport(_url: str, _headers: Mapping[str, str], body: bytes, _timeout: float) -> bytes:
        captured.update(json.loads(body))
        return b'{"data":{"tagCreate":{"id":"7"}}}'

    client = GraphQLClient("http://stash.local", transport=transport)
    result = client.mutate(
        "mutation Create($input: TagCreateInput!) { tagCreate(input: $input) { id } }",
        {"input": {"name": "[Prune]"}},
    )

    assert result["tagCreate"] == {"id": "7"}
    assert captured["variables"] == {"input": {"name": "[Prune]"}}
    with pytest.raises(GraphQLError, match="mutation operations only"):
        client.mutate("query Nope { version { version } }")
