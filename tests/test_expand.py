from datetime import date
from pathlib import Path

from curator.config import DEFAULT_CONFIG
from curator.expand import ExpandService
from curator.model import PreferenceModelBuilder
from tests.model.test_builder import REFERENCE_MS, _database


class FakeStashDB:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        performer = {
            "id": "external-performer",
            "name": "External Performer",
            "gender": "FEMALE",
            "ethnicity": "Caucasian",
            "hair_color": "Black",
            "eye_color": "Brown",
            "height": 170,
            "cup_size": "DD",
            "band_size": 34,
            "waist_size": 24,
            "hip_size": 36,
            "breast_type": "AUGMENTED",
            "tattoos": [],
            "piercings": [],
            "images": [{"url": "https://example.test/performer.jpg"}],
        }
        known_performer = {**performer, "id": "known-external-performer", "name": "Known"}
        scenes = [
            {
                "id": "owned-external-scene",
                "title": "Already owned",
                "release_date": date.today().isoformat(),
                "studio": {"id": "external-studio", "name": "Studio"},
                "tags": [{"id": "external-tag", "name": "Useful"}],
                "images": [],
                "performers": [{"performer": performer}, {"performer": known_performer}],
            },
            {
                "id": "new-external-scene",
                "title": "A new candidate",
                "release_date": date.today().isoformat(),
                "studio": {"id": "external-studio", "name": "Studio"},
                "tags": [{"id": "external-tag", "name": "Useful"}],
                "images": [{"url": "https://example.test/scene.jpg"}],
                "performers": [{"performer": performer}, {"performer": known_performer}],
            },
        ]
        return {"queryScenes": {"count": len(scenes), "scenes": scenes}}


class PagedStashDB(FakeStashDB):
    def execute(self, document: str, variables: dict[str, object]):
        result = super().execute(document, variables)
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        page = int(input_data["page"])
        scene = result["queryScenes"]["scenes"][1]
        scene = {**scene, "id": f"external-scene-{page}"}
        return {"queryScenes": {"count": 2, "scenes": [scene]}}


class OfflineStashDB:
    def execute(self, _document: str, _variables: dict[str, object]):
        raise RuntimeError("offline")


def test_expand_refresh_is_bounded_owned_filtered_and_cached(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = FakeStashDB()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {"studio-1": "external-studio"},
    }

    refreshed = ExpandService(connection).refresh(
        client, links, now_ms=REFERENCE_MS, candidate_limit=10
    )

    assert refreshed == {"scene_count": 1, "performer_count": 1}
    assert 1 <= len(client.inputs) <= 3
    result = ExpandService(connection).results("scene")
    assert result["ready"] is True
    assert [item["id"] for item in result["items"]] == ["new-external-scene"]
    assert result["items"][0]["payload"]["images"][0]["url"].startswith("https://")
    known = result["items"][0]["payload"]["performers"][1]["performer"]
    assert known["curator_local"] == {"id": "p1", "favorite": True, "play_count": 0}
    assert [
        item["id"]
        for item in ExpandService(connection).results("scene", favorite_only=True)["items"]
    ] == ["new-external-scene"]
    assert result["items"][0]["payload"]["why"][-1] == "a performer you already enjoy"
    assert [
        item["id"]
        for item in ExpandService(connection).results(
            "scene", include_tags=("Useful",), performer_query="External", studio_query="Studio"
        )["items"]
    ] == ["new-external-scene"]
    assert ExpandService(connection).results("scene", exclude_tags=("Useful",))["items"] == []
    assert ExpandService(connection).similar("performer", "p1")["items"][0]["id"] == (
        "external-performer"
    )
    assert (
        ExpandService(connection)
        .results("performer")["items"][0]["payload"]["why"][0]
        .startswith("Similar to Performer One in ")
    )

    ExpandService(connection).shortlist("scene", "new-external-scene", True)
    shortlisted = ExpandService(connection).shortlist_results()["items"]
    assert [item["id"] for item in shortlisted] == ["new-external-scene"]
    ExpandService(connection).shortlist("scene", "new-external-scene", False)
    assert ExpandService(connection).shortlist_results()["items"] == []


def test_expand_wildcard_is_opt_in_and_bad_queries_are_rejected(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = FakeStashDB()
    empty_links = {"scenes": {}, "performers": {}, "studios": {}}

    result = ExpandService(connection).refresh(
        client, empty_links, wildcard=True, now_ms=REFERENCE_MS, candidate_limit=10
    )

    assert result["scene_count"] == 2
    assert client.inputs == [{"page": 1, "per_page": 10, "sort": "TRENDING", "direction": "DESC"}]
    assert all(
        "wildcard" in item["sources"]
        for item in ExpandService(connection).results("scene")["items"]
    )


def test_expand_pages_and_preserves_cache_during_outage(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    client = PagedStashDB()
    service = ExpandService(connection)

    service.refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=2)
    assert [item["id"] for item in service.results("scene")["items"]] == [
        "external-scene-1",
        "external-scene-2",
    ]
    assert len(client.inputs) == 2

    try:
        service.refresh(OfflineStashDB(), links, now_ms=REFERENCE_MS + 1)
    except RuntimeError as error:
        assert str(error) == "offline"
    else:
        raise AssertionError("offline refresh should fail")
    assert [item["id"] for item in service.results("scene")["items"]] == [
        "external-scene-1",
        "external-scene-2",
    ]


def test_expand_avoids_adjacent_repeated_performers() -> None:
    def row(identifier: str, performer: str):
        return {
            "id": identifier,
            "payload": {"performers": [{"performer": {"id": performer}}]},
        }

    ordered = ExpandService._diverse_scenes([row("a", "p1"), row("b", "p1"), row("c", "p2")])
    assert [item["id"] for item in ordered] == ["a", "c", "b"]


def test_external_scene_similarity_requires_shared_content(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    service.refresh(
        FakeStashDB(),
        {
            "scenes": {"old-good": "owned-external-scene"},
            "performers": {"p1": "known-external-performer"},
            "studios": {"studio-1": "external-studio"},
        },
        now_ms=REFERENCE_MS,
        candidate_limit=10,
    )
    connection.execute(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        ("good", "https://stashdb.org/graphql", "external-tag"),
    )

    assert [item["id"] for item in service.similar("scene", "old-good")["items"]] == [
        "new-external-scene"
    ]
    payload = connection.execute(
        "SELECT payload_json FROM external_entity WHERE external_id='new-external-scene'"
    ).fetchone()[0]
    connection.execute(
        "UPDATE external_entity SET payload_json=replace(?, 'external-tag', 'other-tag') "
        "WHERE external_id='new-external-scene'",
        (payload,),
    )
    assert service.similar("scene", "old-good")["items"] == []


def test_sparse_external_performer_profile_has_low_confidence() -> None:
    service = ExpandService
    sparse = service._profile({"id": "sparse", "ethnicity": "Caucasian"})
    complete = service._profile(
        {
            "id": "complete",
            "ethnicity": "Caucasian",
            "hair_color": "Black",
            "eye_color": "Brown",
            "height": 170,
            "cup_size": "DD",
            "band_size": 34,
            "waist_size": 24,
            "hip_size": 36,
            "breast_type": "AUGMENTED",
        }
    )

    similarity, _, coverage = service._profile_match(
        sparse, complete, dict(DEFAULT_CONFIG.feature.performer_block_weights)
    )
    assert coverage < 0.25
    assert similarity < 0.4
