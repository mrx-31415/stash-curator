import json
from datetime import date
from pathlib import Path

from curator.config import DEFAULT_CONFIG
from curator.expand import ExpandService
from curator.features import FeatureStore
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


class TaxonomyStashDB(FakeStashDB):
    url = "https://stashdb.org/graphql"

    def execute(self, document: str, variables: dict[str, object] | None = None):
        if "queryTagCategories" in document:
            return {"queryTagCategories": {"count": 0, "tag_categories": []}}
        if "queryTags" in document:
            return {
                "queryTags": {
                    "count": 1,
                    "tags": [
                        {
                            "id": "external-tag",
                            "name": "Familiar Scenario",
                            "aliases": [],
                            "category": None,
                        }
                    ],
                }
            }
        return super().execute(document, variables or {})


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

    assert refreshed == {
        "scene_count": 1,
        "performer_count": 1,
        "taxonomy_refreshed": False,
    }
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
    assert ExpandService(connection).results("scene", minimum_score=1)["items"] == []
    assert [
        item["id"]
        for item in ExpandService(connection).results(
            "scene",
            include_tags=("Useful",),
            performer_names=("External Performer",),
            studio_names=("Studio",),
        )["items"]
    ] == ["new-external-scene"]
    assert ExpandService(connection).results("scene", exclude_tags=("Useful",))["items"] == []
    connection.execute(
        "INSERT INTO taxonomy_snapshot VALUES ('tax', 'https://stashdb.org/graphql', 1, 0, 1)"
    )
    connection.execute("INSERT INTO taxonomy_tag VALUES ('tax', 'external-tag', 'Useful', NULL)")
    connection.execute("INSERT INTO taxonomy_tag_alias VALUES ('tax', 'external-tag', 'Handy')")
    connection.execute(
        "INSERT INTO application_meta(key, value) VALUES "
        "('taxonomy_snapshot_id', 'tax') ON CONFLICT(key) DO UPDATE SET value='tax'"
    )
    assert ExpandService(connection).results("scene", exclude_tags=("Handy",))["items"] == []
    assert ExpandService(connection).similar("performer", "p1")["items"][0]["id"] == (
        "external-performer"
    )
    assert (
        ExpandService(connection).similar("performer", "p1", candidate_ids={"not-in-this-search"})[
            "items"
        ]
        == []
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


def test_refresh_resolves_local_tag_names_from_stashdb_taxonomy(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)

    result = service.refresh(TaxonomyStashDB(), {"scenes": {}, "performers": {}, "studios": {}})

    assert result["taxonomy_refreshed"] is True
    assert "id:external-tag" in service._external_content("old-good")


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


def test_external_scene_similarity_rejects_compilation_tag_bags(tmp_path: Path) -> None:
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
    assert service.similar("scene", "old-good", exclude_tags=("Useful",))["items"] == []
    assert service.similar("scene", "old-good", minimum_similarity=1)["items"] == []
    payload = connection.execute(
        "SELECT payload_json FROM external_entity WHERE external_id='new-external-scene'"
    ).fetchone()[0]
    compilation = json.loads(payload)
    compilation["tags"].append({"id": "compilation", "name": "Compilation"})
    connection.execute(
        "UPDATE external_entity SET payload_json=? WHERE external_id='new-external-scene'",
        (json.dumps(compilation),),
    )
    assert service.similar("scene", "old-good")["items"] == []

    connection.execute(
        "UPDATE external_entity SET payload_json=replace(?, 'external-tag', 'other-tag') "
        "WHERE external_id='new-external-scene'",
        (payload,),
    )
    exact = service.similar("scene", "old-good")["items"]
    assert [item["id"] for item in exact] == ["new-external-scene"]
    assert exact[0]["payload"]["why"] == ["Same performer"]


def test_external_content_similarity_normalizes_candidate_mapped_tags(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    tags = (
        ("generic", "Generic Scenario"),
        ("specific-one", "Specific One"),
        ("specific-two", "Specific Two"),
        *((f"unrelated-{value}", f"Unrelated {value}") for value in range(8)),
    )
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        ((tag_id, name, f"hash-{tag_id}") for tag_id, name in tags),
    )
    connection.executemany(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
        (
            (scene_id, "generic")
            for scene_id in (
                "old-good",
                "recent-good",
                "unseen-good",
                "disliked",
                "unlabeled",
                "unusual",
            )
        ),
    )
    connection.executemany(
        "INSERT INTO scene_marker(marker_id, scene_id, seconds, primary_tag_id, source_hash) "
        "VALUES (?, 'old-good', 0, ?, ?)",
        (
            ("marker-specific-one", "specific-one", "marker-hash-one"),
            ("marker-specific-two", "specific-two", "marker-hash-two"),
        ),
    )
    scenes = ("recent-good", "unseen-good", "disliked", "unlabeled", "unusual")
    connection.executemany(
        "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')",
        ((scenes[value % len(scenes)], f"unrelated-{value}") for value in range(8)),
    )
    connection.executemany(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        ((tag_id, "https://stashdb.org/graphql", f"external-{tag_id}") for tag_id, _ in tags),
    )
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    service._merge_external(
        "scene",
        (
            {
                "id": "generic-with-noise",
                "payload": {
                    "tags": [
                        {"id": f"external-{tag_id}", "name": name}
                        for tag_id, name in tags
                        if tag_id == "generic" or tag_id.startswith("unrelated")
                    ],
                    "performers": [],
                },
                "score": 0,
                "sources": ["tags"],
            },
            {
                "id": "specific-match",
                "payload": {
                    "tags": [
                        {"id": f"external-{tag_id}", "name": name}
                        for tag_id, name in tags
                        if tag_id.startswith("specific")
                    ],
                    "performers": [],
                },
                "score": 0,
                "sources": ["tags"],
            },
        ),
    )

    result = service.similar("scene", "old-good", minimum_similarity=0)
    old_target = service._external_content("old-good")

    assert old_target["id:external-generic"] ** 2 > sum(
        old_target[f"id:external-specific-{value}"] ** 2 for value in ("one", "two")
    )
    assert [item["id"] for item in result["items"]] == [
        "specific-match",
        "generic-with-noise",
    ]
    assert result["items"][0]["similarity"] > result["items"][1]["similarity"]


def test_external_similarity_loads_only_positive_anchor_profiles(
    tmp_path: Path, monkeypatch
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    connection.execute(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        ("good", "https://stashdb.org/graphql", "external-tag"),
    )
    client = FakeStashDB()
    requested: list[object] = []
    performer_profiles = FeatureStore.performer_profiles

    def capture_profiles(store, feature_version, performer_ids=None):
        requested.append(performer_ids)
        return performer_profiles(store, feature_version, performer_ids)

    monkeypatch.setattr(FeatureStore, "performer_profiles", capture_profiles)

    ExpandService(connection).targeted_similar(
        client,
        {"scenes": {}, "performers": {"p1": "known-external-performer"}, "studios": {}},
        "scene",
        "old-good",
    )

    tag_query = next(value for value in client.inputs if "tags" in value)
    assert tag_query["tags"] == {"value": ["external-tag"], "modifier": "INCLUDES"}
    assert {"p1"} in requested


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


def test_external_profile_normalizes_age_augmentation_and_tag_names() -> None:
    profile = ExpandService._profile(
        {
            "id": "performer",
            "birth_date": "1985-04-07",
            "breast_type": "FAKE",
        }
    )

    assert "age_recording" in profile.blocks["age"]
    assert "augmented" in profile.blocks["augmentation"]
    recorded = ExpandService._profile({"id": "performer", "birth_date": "1985-04-07"}, "2020-04-07")
    assert round(recorded.blocks["age"]["age_recording"].value) == 35
    assert (
        ExpandService._tag_value({"id": "unmapped", "name": "Useful"}, {"name:useful": 0.4}) == 0.4
    )
    assert ExpandService._cast_weight(4) == 1
    assert ExpandService._cast_weight(100) == 0.2
