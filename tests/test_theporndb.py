import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from curator.expand import PERFORMERS, SCENES
from curator.graphql import GraphQLError
from curator.taxonomy.stashdb import StashDBTaxonomyClient
from curator.theporndb import ThePornDBClient, _measurement, _performer, _scene


def fixture() -> dict:
    return json.loads((Path(__file__).parent / "fixtures/theporndb.json").read_text())


def test_normalize_site_performers_to_graphql_ids_and_preserve_missing_data() -> None:
    data = fixture()
    person = {**data["site_performer"], "parent": data["performer"]}
    scene = _scene(
        {
            **data["scene"],
            "performers": [person, person],
            "site": data["site"],
            "tags": data["tags"],
        }
    )
    assert len(scene["performers"]) == 1
    profile = scene["performers"][0]["performer"]
    assert profile["id"] == "parent-performer"
    assert profile["gender"] == "FEMALE"
    assert profile["hair_color"] == "BRUNETTE"
    assert profile["height"] == 160
    assert profile["band_size"] == 34
    assert profile["cup_size"] == "DD"
    assert profile["waist_size"] == 24
    assert profile["hip_size"] == 36
    assert profile["breast_type"] == "NATURAL"
    assert profile["piercings"] == []
    assert scene["studio"]["id"] == "studio-uuid"
    assert scene["tags"][0]["id"] == "tag-uuid"
    assert scene["fingerprints"][0]["algorithm"] == "PHASH"
    missing = _performer(data["site_performer"])
    assert missing["id"] == "site-performer"
    assert missing["height"] is None
    assert missing["breast_type"] is None
    assert missing["gender"] is None
    assert missing["curator_site_performer"] is True
    assert profile["curator_site_performer"] is False
    assert _measurement("1.6m", height=True) == 160
    assert _measurement("61cm") == pytest.approx(24.015748)
    assert _measurement("unknown", height=True) is None
    assert _measurement("999cm", height=True) is None


def test_filters_and_virtual_pages_do_not_drop_constraints() -> None:
    data = fixture()
    scene_requests = []

    def transport(url, headers, timeout):
        assert headers == {"Authorization": "Bearer test-key", "Accept": "application/json"}
        assert timeout == 30
        address = urlparse(url)
        path, query = address.path, parse_qs(address.query)
        rows = {
            "/performers/parent-performer": data["performer"],
            "/performer-sites/site-performer": {
                **data["site_performer"],
                "parent": data["performer"],
            },
            "/sites/studio-uuid": data["site"],
        }
        if path in rows:
            value = {"data": rows[path]}
        elif path == "/tags":
            value = {"data": data["tags"], "meta": {"total": 1, "current_page": 1}}
        elif path == "/scenes":
            scene_requests.append(query)
            assert query["performers[42]"] == ["Example Performer"]
            assert query["sites[9]"] == ["Example Studio"]
            assert query["tags[7]"] == ["Example Tag"]
            assert query["tag_and"] == ["true"]
            page, size = int(query["page"][0]), int(query["per_page"][0])
            assert size <= 100
            value = {
                "data": [
                    {**data["scene"], "id": f"scene-{i:03d}"}
                    for i in range((page - 1) * size, min(page * size, 205))
                ],
                "meta": {"total": 205, "current_page": page},
            }
        else:
            return 404, b"{}"
        return 200, json.dumps(value).encode()

    client = ThePornDBClient("https://theporndb.net/graphql", "test-key", rest_transport=transport)
    query = {
        "page": 2,
        "per_page": 150,
        **{
            source: {"value": [identifier], "modifier": "INCLUDES_ALL"}
            for source, identifier in [
                ("performers", "site-performer"),
                ("studios", "studio-uuid"),
                ("tags", "tag-uuid"),
            ]
        },
    }
    result = client.execute(SCENES, {"input": query})["queryScenes"]
    assert result["count"] == 205
    assert len(result["scenes"]) == 55
    assert result["scenes"][0]["id"] == "scene-150"
    assert result["scenes"][-1]["id"] == "scene-204"
    assert len(scene_requests) == 2
    query["performers"] = {"value": ["missing"], "modifier": "INCLUDES"}
    assert client.execute(SCENES, {"input": query})["queryScenes"] == {"count": 0, "scenes": []}
    assert len(scene_requests) == 2
    with pytest.raises(GraphQLError, match="full discovery refresh"):
        client.execute(SCENES, {"input": {"updated_at": {}}})
    with pytest.raises(GraphQLError, match="read-only"):
        client.mutate("mutation { write }")


def test_flat_taxonomy_and_similar_performer_pool() -> None:
    data = fixture()
    requests = []

    def transport(url, headers, timeout):
        address = urlparse(url)
        query = parse_qs(address.query)
        requests.append(address.path)
        if address.path.startswith("/performers") and "gender" in query:
            assert query["gender"] == ["Female"]
        if address.path == "/tags":
            value = {"data": data["tags"], "meta": {"total": 1, "current_page": 1}}
        elif address.path == "/performers/parent-performer":
            value = {"data": data["performer"]}
        elif address.path.endswith("/similar"):
            value = {"data": [data["performer"]]}
        else:
            assert query["orderBy"] == ["most_relevant"]
            assert query["age_operation"] == [">"]
            value = {"data": [data["performer"]], "meta": {"total": 1, "current_page": 1}}
        return 200, json.dumps(value).encode()

    client = ThePornDBClient("https://theporndb.net/graphql", "key", rest_transport=transport)
    taxonomy = StashDBTaxonomyClient(client).fetch()
    assert taxonomy.categories == ()
    assert taxonomy.tags[0].tag_id == "tag-uuid"
    assert taxonomy.tags[0].category_id is None
    assert requests.count("/tags") == 1
    for extra in [
        {"age": {"value": 30, "modifier": "GREATER_THAN"}},
        {"performed_with": "parent-performer"},
    ]:
        rows = client.execute(
            PERFORMERS, {"input": {"page": 1, "per_page": 2, "gender": "FEMALE", **extra}}
        )["queryPerformers"]["performers"]
        assert rows[0]["id"] == "parent-performer"


@pytest.mark.parametrize(
    "response",
    [
        (429, b"{}"),
        (200, b"not json"),
        (200, b'{"data":{},"meta":{}}'),
        (200, b'{"data":[],"meta":{"total":null}}'),
        (200, b'{"data":[{}],"meta":{"total":1}}'),
    ],
)
def test_bad_responses_fail_clearly(response) -> None:
    client = ThePornDBClient(
        "https://theporndb.net/graphql", "key", rest_transport=lambda *_: response
    )
    with pytest.raises(GraphQLError, match="ThePornDB"):
        client.execute(SCENES, {"input": {"page": 1, "per_page": 1}})
