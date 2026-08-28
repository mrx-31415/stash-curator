import json
from datetime import date
from pathlib import Path

import pytest

from curator.config import DEFAULT_CONFIG
from curator.expand import ExpandService, normalize_phash
from curator.features import FeatureStore
from curator.graphql import GraphQLError
from curator.interactions import InteractionStore
from curator.model import PreferenceModelBuilder, RecommendationModelStore
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
                "fingerprints": [
                    {"hash": "d8bc7554c5a178aa", "algorithm": "PHASH", "duration": 120}
                ],
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
        sort = str(input_data.get("sort", "DATE"))
        scene = {**result["queryScenes"]["scenes"][1], "id": f"external-scene-{sort}-{page}"}
        return {"queryScenes": {"count": 2, "scenes": [scene]}}


class OfflineStashDB:
    def execute(self, _document: str, _variables: dict[str, object]):
        raise RuntimeError("offline")


class NoChangeStashDB(FakeStashDB):
    """Serve one refresh, then report nothing changed since the watermark."""

    def __init__(self) -> None:
        super().__init__()
        self.changed = True

    def execute(self, document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        if not self.changed and "updated_at" in input_data:
            self.inputs.append(input_data)
            return {"queryScenes": {"count": 0, "scenes": []}}
        return super().execute(document, variables)


class NoSinceStashDB(FakeStashDB):
    """A StashDB instance without the updated_at criterion: watermark queries fail."""

    def execute(self, document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        if "updated_at" in input_data:
            raise GraphQLError('Stash GraphQL error: Cannot query field "updated_at"')
        return super().execute(document, variables)


class PerformerHuntStashDB(FakeStashDB):
    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        page = int(input_data["page"])
        scenes = [
            {
                "id": identifier,
                "title": identifier,
                "release_date": release_date,
                "fingerprints": (
                    [{"hash": "0123456789abcdef", "algorithm": "PHASH", "duration": 120}]
                    if identifier == "hunt-new"
                    else []
                ),
                "studio": None,
                "tags": [],
                "images": [],
                "performers": [
                    {
                        "performer": {
                            "id": "known-external-performer",
                            "name": "Known",
                            "gender": "FEMALE",
                            "tattoos": [],
                            "piercings": [],
                            "images": [],
                        }
                    }
                ],
            }
            for identifier, release_date in (
                ("hunt-old", "2024-01-01"),
                ("hunt-linked", "2025-01-01"),
                ("hunt-new", "2026-01-01"),
            )
        ]
        start = (page - 1) * 2
        return {"queryScenes": {"count": len(scenes), "scenes": scenes[start : start + 2]}}


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


class PerformerPoolStashDB:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        age = input_data.get("age")
        if age and age["modifier"] == "GREATER_THAN":
            performers = [
                {
                    "id": "mature-lookalike",
                    "name": "Mature Lookalike",
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
                    "scene_count": 600,
                    "tattoos": [],
                    "piercings": [],
                    "images": [],
                }
            ]
        else:
            performers = [
                {
                    "id": "young-popular",
                    "name": "Young Popular",
                    "gender": "FEMALE",
                    "ethnicity": "Caucasian",
                    "hair_color": "Brown",
                    "eye_color": "Blue",
                    "height": 165,
                    "cup_size": "B",
                    "band_size": 32,
                    "waist_size": 24,
                    "hip_size": 34,
                    "breast_type": "NATURAL",
                    "scene_count": 5,
                    "tattoos": [],
                    "piercings": [],
                    "images": [],
                }
            ]
        return {"queryPerformers": {"performers": performers}}


class PopularityPoolStashDB:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        popular = {
            "id": "popular-performer",
            "name": "Popular Performer",
            "gender": "FEMALE",
            "ethnicity": "Caucasian",
            "hair_color": "Brown",
            "eye_color": "Blue",
            "height": 170,
            "cup_size": "D",
            "band_size": 34,
            "waist_size": 25,
            "hip_size": 36,
            "breast_type": "AUGMENTED",
            "scene_count": 600,
            "tattoos": [],
            "piercings": [],
            "images": [],
        }
        obscure = {
            **popular,
            "id": "obscure-performer",
            "name": "Obscure Performer",
            "hair_color": "Black",
            "cup_size": "DD",
            "waist_size": 24,
            "scene_count": 8,
        }
        return {"queryPerformers": {"performers": [popular, obscure]}}


def test_phash_normalization_accepts_only_exact_64_bit_hex() -> None:
    assert normalize_phash(" D8BC7554C5A178AA ") == "d8bc7554c5a178aa"
    assert normalize_phash("shared-phash") is None
    assert normalize_phash("") is None


def test_expand_refresh_is_bounded_owned_filtered_and_cached(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = FakeStashDB()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {"studio-1": "external-studio"},
    }
    progress: list[tuple[int, int]] = []

    refreshed = ExpandService(connection).refresh(
        client,
        links,
        now_ms=REFERENCE_MS,
        candidate_limit=10,
        similar_top_k=0,
        progress=lambda processed, total: progress.append((processed, total)),
    )

    assert refreshed == {
        "scene_count": 1,
        "performer_count": 1,
        "taxonomy_refreshed": False,
        "incremental": False,
    }
    assert len(client.inputs) == 4  # performers + studios x 2 probes each (DATE + POPULARITY)
    assert [processed for processed, _ in progress] == sorted(
        processed for processed, _ in progress
    )
    assert progress[-1] == (1_000, 1_000)
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
    performer_items = ExpandService(connection).similar("performer", "p1")["items"]
    assert performer_items
    assert all(
        0 <= item["appeal"] <= 1
        and item["score"] == pytest.approx(0.7 * item["similarity"] + 0.3 * item["appeal"])
        for item in performer_items
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


def test_expand_hides_exact_local_phash_matches_by_default(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "scene_phashes": {"d8bc7554c5a178aa": "old-good"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }

    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)

    assert service.results("scene")["items"] == []
    visible = service.results("scene", hide_phash_matches=False)["items"]
    assert [item["id"] for item in visible] == ["new-external-scene"]
    assert visible[0]["payload"]["curator_local_match"] == {
        "type": "phash",
        "local_scene_id": "old-good",
    }


def test_results_reannotates_candidates_against_current_links(tmp_path: Path) -> None:
    """Issue #118: a candidate fetched while the local scene had no StashDB
    id keeps its missing curator_local_match annotation, so results() must
    re-derive the exclusion against the current links map at serve time."""
    connection = _database(tmp_path / "curator.sqlite3")
    service = ExpandService(connection)
    candidates = [
        {
            "id": "ext-owned-now",
            "title": "Candidate one",
            "release_date": "2026-01-01",
            "studio": {"id": "ext-studio-1", "name": "Studio One"},
            "tags": [],
            "performers": [],
            "fingerprints": [],
        },
        {
            "id": "ext-phash-owned",
            "title": "Candidate two",
            "release_date": "2026-01-01",
            "studio": {"id": "ext-studio-1", "name": "Studio One"},
            "tags": [],
            "performers": [],
            "fingerprints": [{"algorithm": "phash", "hash": "0123456789abcdef"}],
        },
        {
            "id": "ext-unrelated",
            "title": "Candidate three",
            "release_date": "2026-01-01",
            "studio": {"id": "ext-studio-1", "name": "Studio One"},
            "tags": [],
            "performers": [],
            "fingerprints": [],
        },
    ]
    for index, payload in enumerate(candidates):
        connection.execute(
            """
            INSERT INTO external_entity(
                entity_type, external_id, payload_json, score, sources_json,
                fetched_at_ms, pool
            ) VALUES ('scene', ?, ?, ?, '[]', ?, 'candidate')
            """,
            (
                payload["id"],
                json.dumps(payload, separators=(",", ":")),
                0.5,
                REFERENCE_MS - index,
            ),
        )
    connection.execute(
        """
        INSERT INTO expand_cache(
            singleton, model_id, fetched_at_ms, expires_at_ms, scene_count, performer_count
        ) VALUES (1, 'model', ?, ?, 3, 0)
        """,
        (REFERENCE_MS, REFERENCE_MS + 10 * 86_400_000),
    )
    connection.commit()

    def ids(links, hide_phash_matches=True):
        return [
            item["id"]
            for item in service.results(
                "scene",
                gender="",
                hide_phash_matches=hide_phash_matches,
                links=links,
            )["items"]
        ]

    unlinked = {
        "scenes": {},
        "scene_ids": {},
        "scene_phashes": {},
        "performers": {},
        "studios": {},
    }
    # Fetch time: no local scene carries a StashDB id, all candidates show.
    assert ids(unlinked) == ["ext-owned-now", "ext-phash-owned", "ext-unrelated"]
    # The user adds the stash_id to the local scene (and a second local
    # scene gains the exact phash); browse must now hide both matches.
    linked = {
        "scenes": {"local-1": "ext-owned-now"},
        "scene_ids": {"ext-owned-now": "local-1"},
        "scene_phashes": {"0123456789abcdef": "local-2"},
        "performers": {},
        "studios": {},
    }
    assert ids(linked) == ["ext-unrelated"]
    # hide_phash_matches=False keeps the phash match but not the stash_id one.
    assert ids(linked, hide_phash_matches=False) == ["ext-phash-owned", "ext-unrelated"]
    # Without links (legacy direct callers) the stored annotation applies:
    # nothing is excluded because nothing was annotated at fetch time.
    assert ids(None) == ["ext-owned-now", "ext-phash-owned", "ext-unrelated"]


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


def test_refresh_is_incremental_and_preserves_the_candidate_pool(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    client = NoChangeStashDB()

    first = service.refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=10, similar_top_k=0)
    assert first["incremental"] is False
    assert not any("updated_at" in item for item in client.inputs)

    # Nothing changed on StashDB: the second refresh fetches only entries updated since
    # the previous fetched_at and keeps every existing row.
    client.changed = False
    client.inputs.clear()
    second = service.refresh(
        client, links, now_ms=REFERENCE_MS + 86_400_000, candidate_limit=10, similar_top_k=0
    )
    assert second["incremental"] is True
    assert client.inputs
    assert all("updated_at" in item for item in client.inputs)
    assert all(item["sort"] == "UPDATED_AT" for item in client.inputs)
    assert [item["id"] for item in service.results("scene")["items"]] == ["new-external-scene"]
    cache = connection.execute(
        "SELECT fetched_at_ms, scene_count FROM expand_cache WHERE singleton=1"
    ).fetchone()
    assert cache["fetched_at_ms"] == REFERENCE_MS + 86_400_000
    assert cache["scene_count"] == 1


def test_refresh_preserves_explore_rows_from_hunts_and_similar(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)
    service._merge_external(
        "scene",
        [{"id": "explored-scene", "payload": {}, "score": 0.5, "sources": ["similar"]}],
    )
    assert (
        connection.execute("SELECT count(*) FROM external_entity WHERE pool='explore'").fetchone()[
            0
        ]
        == 1
    )

    client = NoChangeStashDB()
    client.changed = False
    service.refresh(client, links, now_ms=REFERENCE_MS + 86_400_000, candidate_limit=10)

    assert (
        connection.execute("SELECT count(*) FROM external_entity WHERE pool='explore'").fetchone()[
            0
        ]
        == 1
    )


class SeedExpansionStashDB(FakeStashDB):
    """Dispatches the performer-pool popularity query in addition to scene queries."""

    def execute(self, document: str, variables: dict[str, object]):
        input_data = variables["input"]
        if "queryPerformers" in document:
            self.inputs.append(input_data)
            lookalike = {
                "id": "lookalike-performer",
                "name": "Lookalike Performer",
                "gender": "FEMALE",
                "ethnicity": "Caucasian",
                "hair_color": "Brown",
                "eye_color": "Blue",
                "height": 170,
                "scene_count": 200,
                "tattoos": [],
                "piercings": [],
                "images": [],
            }
            return {"queryPerformers": {"performers": [lookalike]}}
        return super().execute(document, variables)


def test_seed_expansion_chases_similar_performers_into_scenes(tmp_path: Path) -> None:
    """A performer StashDB ranks near the user's own favourites is pulled into the
    seed set even though she is not in the local library, and her scenes are then
    fetched (issue: scenes by look-alike performers were invisible to Expand)."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    client = SeedExpansionStashDB()
    ExpandService(connection).refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=100)
    scene_queries = [item for item in client.inputs if item.get("sort") == "DATE"]
    assert scene_queries
    assert any(
        "lookalike-performer" in (item.get("performers", {}).get("value") or [])
        for item in scene_queries
    )


def test_refresh_samples_each_seed_source_by_recency_and_popularity(tmp_path: Path) -> None:
    """A full refresh probes every active seed source by BOTH recency (DATE) and
    popularity, so interesting-but-not-new scenes are not truncated out of the
    cache. Before this, a date-only pool only kept the newest matches."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {"studio-1": "external-studio"},
    }
    client = FakeStashDB()
    ExpandService(connection).refresh(
        client, links, now_ms=REFERENCE_MS, candidate_limit=100, similar_top_k=0
    )
    dates = [item for item in client.inputs if item.get("sort") == "DATE"]
    popular = [item for item in client.inputs if item.get("sort") == "POPULARITY"]
    assert len(dates) == 2  # performers + studios
    assert len(popular) == 2
    assert all(("performers" in item or "studios" in item) for item in client.inputs)


def test_incremental_refresh_keeps_single_probe_per_seed_source(tmp_path: Path) -> None:
    """An incremental refresh walks the updated_at watermark, where the DATE and
    POPULARITY sorts are equivalent, so it issues one UPDATED_AT probe per source
    rather than duplicating the fetch."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {"studio-1": "external-studio"},
    }
    client = FakeStashDB()
    service = ExpandService(connection)
    service.refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=100, similar_top_k=0)
    client.inputs.clear()
    service.refresh(
        client, links, now_ms=REFERENCE_MS + 86_400_000, candidate_limit=100, similar_top_k=0
    )
    incremental = [
        item
        for item in client.inputs
        if item.get("sort") == "UPDATED_AT" and ("performers" in item or "studios" in item)
    ]
    assert len(incremental) == 2  # performers + studios, one probe each
    assert all("updated_at" in item for item in incremental)


def test_refresh_ages_out_explore_rows_but_preserves_shortlisted(tmp_path: Path) -> None:
    """The explore pool ages out with the candidate pool, so on-demand hunts cannot
    grow the sidecar without bound, but anything the user pinned survives."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10, similar_top_k=0)
    service._merge_external(
        "scene",
        [
            {
                "id": "old-explore",
                "payload": {"release_date": "2020-01-01"},
                "score": 0.5,
                "sources": ["similar"],
            },
            {
                "id": "recent-explore",
                "payload": {"release_date": date.today().isoformat()},
                "score": 0.5,
                "sources": ["similar"],
            },
            {
                "id": "shortlisted-old",
                "payload": {"release_date": "2020-01-01"},
                "score": 0.5,
                "sources": ["similar"],
            },
        ],
    )
    connection.execute(
        "INSERT INTO external_shortlist(entity_type, external_id, payload_json, score, "
        "added_at_ms) VALUES ('scene', 'shortlisted-old', '{}', 0.5, 0)"
    )
    connection.commit()

    service.refresh(
        NoChangeStashDB(),
        links,
        now_ms=REFERENCE_MS + 86_400_000,
        candidate_limit=10,
        similar_top_k=0,
    )

    pools = {
        str(row["external_id"]): str(row["pool"])
        for row in connection.execute(
            "SELECT external_id, pool FROM external_entity WHERE external_id IN "
            "('old-explore','recent-explore','shortlisted-old')"
        )
    }
    assert "old-explore" not in pools
    assert pools["recent-explore"] == "explore"
    assert pools["shortlisted-old"] == "explore"


def test_rescore_candidates_refreshes_stored_scores_after_a_model_change(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)
    connection.execute(
        "UPDATE external_entity SET score=0.99 WHERE entity_type='scene' AND external_id=?",
        ("new-external-scene",),
    )
    connection.commit()
    model_id = str(RecommendationModelStore(connection).current_model_id())
    feature_version = str(FeatureStore(connection).current_version())

    service._rescore_candidates(model_id, feature_version, links)

    score = connection.execute(
        "SELECT score FROM external_entity WHERE entity_type='scene' AND external_id=?",
        ("new-external-scene",),
    ).fetchone()
    assert float(score[0]) != 0.99


def test_refresh_purges_candidates_older_than_the_horizon(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)
    connection.execute(
        "UPDATE external_entity SET payload_json=json_set(payload_json, '$.release_date', ?)"
        " WHERE entity_type='scene' AND external_id=?",
        ("2000-01-01", "new-external-scene"),
    )
    connection.commit()

    client = NoChangeStashDB()
    client.changed = False
    service.refresh(client, links, now_ms=REFERENCE_MS + 86_400_000, candidate_limit=10)

    assert (
        connection.execute(
            "SELECT count(*) FROM external_entity WHERE entity_type='scene'"
            " AND pool='candidate' AND external_id='new-external-scene'"
        ).fetchone()[0]
        == 0
    )


def test_refresh_falls_back_to_full_fetch_when_stashdb_rejects_the_watermark(
    tmp_path: Path,
) -> None:
    """An instance without the updated_at criterion keeps refresh working (full fetch)."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)
    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)

    client = NoSinceStashDB()
    result = service.refresh(client, links, now_ms=REFERENCE_MS + 86_400_000, candidate_limit=10)

    assert result["incremental"] is False
    assert not any("updated_at" in item for item in client.inputs)
    assert [item["id"] for item in service.results("scene")["items"]] == ["new-external-scene"]


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

    service.refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=2, similar_top_k=0)
    assert [item["id"] for item in service.results("scene")["items"]] == [
        "external-scene-DATE-1",
        "external-scene-POPULARITY-1",
    ]
    first = service.results("scene", count=1)
    second = service.results("scene", page=2, count=1)
    assert first["has_more"] is True
    assert first["total"] == 2
    assert [first["items"][0]["id"], second["items"][0]["id"]] == [
        "external-scene-DATE-1",
        "external-scene-POPULARITY-1",
    ]
    assert second["has_more"] is False
    assert len(client.inputs) == 2

    try:
        service.refresh(OfflineStashDB(), links, now_ms=REFERENCE_MS + 1)
    except RuntimeError as error:
        assert str(error) == "offline"
    else:
        raise AssertionError("offline refresh should fail")
    assert [item["id"] for item in service.results("scene")["items"]] == [
        "external-scene-DATE-1",
        "external-scene-POPULARITY-1",
    ]


def test_shortlist_pages_report_exact_total(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.executemany(
        """
        INSERT INTO external_shortlist(
            entity_type, external_id, payload_json, score, sources_json, added_at_ms
        ) VALUES ('scene', ?, '{}', 0, '[]', ?)
        """,
        [("first", 1), ("second", 2)],
    )

    service = ExpandService(connection)
    first = service.shortlist_results(page=1, count=1)
    second = service.shortlist_results(page=2, count=1)

    assert first["total"] == 2
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert [item["id"] for item in first["items"] + second["items"]] == ["second", "first"]


def test_performer_hunt_pages_classifies_exact_links_and_discloses_cap(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {"old-good": "hunt-linked"},
        "scene_phashes": {"0123456789abcdef": "old-good"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    client = PerformerHuntStashDB()
    service = ExpandService(connection)

    result = service.performer_hunt(client, links, "p1", limit=10)

    assert [item["id"] for item in result["items"]] == [
        "hunt-new",
        "hunt-linked",
        "hunt-old",
    ]
    assert result["stashdb_total"] == result["fetched_count"] == 3
    assert result["total"] == result["fetched_count"]
    assert result["linked_count"] == 2
    assert result["not_linked_count"] == 1
    assert result["truncated"] is False
    assert [item["id"] for item in result["items"] if not item["linked_locally"]] == ["hunt-old"]
    assert result["items"][0]["match_type"] == "phash"
    assert result["items"][1]["local_scene_id"] == "old-good"
    assert len(client.inputs) == 2
    assert all(
        request["performers"] == {"value": ["known-external-performer"], "modifier": "INCLUDES"}
        for request in client.inputs
    )

    capped = service.performer_hunt(PerformerHuntStashDB(), links, "p1", limit=2)
    assert capped["stashdb_total"] == 3
    assert capped["fetched_count"] == capped["limit"] == 2
    assert capped["truncated"] is True
    assert [item["id"] for item in capped["items"] if not item["linked_locally"]] == ["hunt-old"]


def test_performer_hunt_requires_a_stashdb_link(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()

    try:
        ExpandService(connection).performer_hunt(
            PerformerHuntStashDB(),
            {"scenes": {}, "performers": {}, "studios": {}},
            "p1",
        )
    except ValueError as error:
        assert str(error) == "selected performer is not linked to StashDB"
    else:
        raise AssertionError("unlinked performers must be rejected")


def test_performer_hunt_accepts_an_external_performer_id(tmp_path: Path) -> None:
    """The film action on a similar performer card hunts the external id directly.

    External performers have no source_performer row, so the id must be passed to
    StashDB as-is and the name recovered from the fetched cast.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {"scenes": {}, "scene_phashes": {}, "performers": {}, "studios": {}}
    client = PerformerHuntStashDB()
    service = ExpandService(connection)

    result = service.performer_hunt(client, links, "known-external-performer", limit=10)

    assert result["performer_id"] == "known-external-performer"
    assert result["performer_name"] == "Known"
    assert [item["id"] for item in result["items"]] == [
        "hunt-new",
        "hunt-linked",
        "hunt-old",
    ]
    assert all(
        request["performers"] == {"value": ["known-external-performer"], "modifier": "INCLUDES"}
        for request in client.inputs
    )


def test_performer_hunt_results_stay_out_of_expand(tmp_path: Path) -> None:
    """A performer's whole catalog must not dilute the general Expand browse.

    Hunting one performer used to merge every unowned scene it returned into the
    same pool Expand reads from, so hunting several performers back to back left
    their catalogs mixed into Expand with no way to tell them apart.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {
            "old-good": "owned-external-scene",
            "old-bad": "hunt-linked",
        },
        "scene_phashes": {"0123456789abcdef": "old-good"},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)

    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)
    before = {item["id"] for item in service.results("scene")["items"]}
    service.performer_hunt(PerformerHuntStashDB(), links, "p1", limit=10)

    identifiers = {item["id"] for item in service.results("scene")["items"]}
    assert identifiers == before
    assert "hunt-old" not in identifiers
    assert "hunt-linked" not in identifiers


def test_performer_hunt_results_remain_shortlistable(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "scene_phashes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)

    service.performer_hunt(PerformerHuntStashDB(), links, "p1", limit=10)
    service.shortlist("scene", "hunt-old", True)

    assert [item["id"] for item in service.shortlist_results()["items"]] == ["hunt-old"]


def test_expand_candidate_pool_survives_a_later_explore_merge(tmp_path: Path) -> None:
    """A scene refresh() legitimately placed in Expand must survive a later hunt.

    Both write through the same upsert keyed only by (entity_type, external_id);
    without care, an 'explore' merge that happens to revisit a 'candidate' scene
    would downgrade it out of Expand until the next refresh.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    links = {
        "scenes": {},
        "scene_phashes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }
    service = ExpandService(connection)

    service.refresh(FakeStashDB(), links, now_ms=REFERENCE_MS, candidate_limit=10)
    assert "new-external-scene" in {
        item["id"] for item in service.results("scene", gender="")["items"]
    }

    service._merge_external(
        "scene",
        [{"id": "new-external-scene", "payload": {}, "score": 0.5, "sources": ["performers"]}],
    )

    assert "new-external-scene" in {
        item["id"] for item in service.results("scene", gender="")["items"]
    }


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
    scene_items = service.similar("scene", "old-good")["items"]
    assert scene_items
    assert all(
        0 <= item["appeal"] <= 1
        and item["score"] == pytest.approx(0.7 * item["similarity"] + 0.3 * item["appeal"])
        for item in scene_items
    )
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


def test_external_scene_similarity_gates_performer_credit_on_content(
    tmp_path: Path,
) -> None:
    """Wrong-theme same-performer scenes lose credit in proportion to the gap.

    A scene starring the target performer but sharing no theme used to score
    the full 0.3 performer weight, letting it outrank thematic matches. The
    gate scales the credit by content overlap: zero overlap leaves 0.35 of it
    (0.3 * 0.35 + 0.1 structure = 0.205), full overlap keeps all of it
    (0.5 content + 0.3 performer + 0.1 structure = 0.9).
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    connection.execute(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        ("good", "https://stashdb.org/graphql", "external-good"),
    )
    service = ExpandService(connection)
    performer = {
        "id": "external-p1",
        "gender": "FEMALE",
        "hair_color": "Black",
        "height": 170,
        "cup_size": "DD",
        "band_size": 34,
        "waist_size": 24,
        "hip_size": 36,
        "tattoos": [],
        "piercings": [],
        "curator_local": {"id": "p1", "favorite": True, "play_count": 0},
    }
    service._merge_external(
        "scene",
        (
            {
                "id": "wrong-theme",
                "payload": {"tags": [], "performers": [{"performer": performer}]},
                "score": 0,
                "sources": ["performers"],
            },
            {
                "id": "same-theme",
                "payload": {
                    "tags": [{"id": "external-good", "name": "Familiar Scenario"}],
                    "performers": [{"performer": performer}],
                },
                "score": 0,
                "sources": ["performers"],
            },
        ),
    )

    result = service.similar("scene", "old-good", minimum_similarity=0)
    by_id = {item["id"]: item for item in result["items"]}

    assert abs(by_id["wrong-theme"]["similarity"] - 0.205) < 1e-9
    assert abs(by_id["same-theme"]["similarity"] - 0.9) < 1e-9
    assert by_id["same-theme"]["similarity"] > by_id["wrong-theme"]["similarity"]


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

    hidden = ExpandService(connection).targeted_similar(
        client,
        {
            "scenes": {"old-good": "owned-external-scene"},
            "scene_phashes": {"d8bc7554c5a178aa": "old-good"},
            "performers": {"p1": "known-external-performer"},
            "studios": {},
        },
        "scene",
        "old-good",
    )
    visible = ExpandService(connection).targeted_similar(
        client,
        {
            "scenes": {"old-good": "owned-external-scene"},
            "scene_phashes": {"d8bc7554c5a178aa": "old-good"},
            "performers": {"p1": "known-external-performer"},
            "studios": {},
        },
        "scene",
        "old-good",
        hide_phash_matches=False,
    )

    assert hidden["items"] == []
    assert [item["id"] for item in visible["items"]] == ["new-external-scene"]
    tag_queries = [value for value in client.inputs if "tags" in value]
    assert {value["sort"] for value in tag_queries} == {"DATE", "POPULARITY"}
    assert all(
        value["tags"] == {"value": ["external-tag"], "modifier": "INCLUDES"}
        for value in tag_queries
    )
    assert {"p1"} in requested


def test_targeted_scene_similar_probes_both_sorts_and_tight_tag_sets(
    tmp_path: Path,
) -> None:
    """Targeted scene similar must retrieve both newest and most-viewed matches.

    A single date-sorted probe caps the pool at the latest releases; a popularity
    probe reaches the representative scenes, and an INCLUDES_ALL probe on the
    most distinctive tags pins exact thematic twins.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (
            ("specific-one", "Specific One", "s1"),
            ("specific-two", "Specific Two", "s2"),
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
    connection.executemany(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        (
            ("good", "https://stashdb.org/graphql", "external-good"),
            ("specific-one", "https://stashdb.org/graphql", "external-specific-one"),
            ("specific-two", "https://stashdb.org/graphql", "external-specific-two"),
        ),
    )
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = FakeStashDB()
    service = ExpandService(connection)

    result = service.targeted_similar(
        client,
        {
            "scenes": {"old-good": "owned-external-scene"},
            "scene_phashes": {"d8bc7554c5a178aa": "old-good"},
            "performers": {"p1": "known-external-performer"},
            "studios": {"studio-1": "external-studio"},
        },
        "scene",
        "old-good",
        hide_phash_matches=False,
    )

    tag_queries = [value for value in client.inputs if "tags" in value]
    assert {value["sort"] for value in tag_queries} == {"DATE", "POPULARITY"}
    assert {value["tags"]["modifier"] for value in tag_queries} == {
        "INCLUDES",
        "INCLUDES_ALL",
    }
    broad = [value for value in tag_queries if value["tags"]["modifier"] == "INCLUDES"]
    assert all(value["per_page"] == 250 for value in broad)
    assert all(len(value["tags"]["value"]) == 3 for value in broad)
    tight = [value for value in tag_queries if value["tags"]["modifier"] == "INCLUDES_ALL"]
    assert all(value["per_page"] == 100 for value in tight)
    assert all(len(value["tags"]["value"]) == 3 for value in tight)
    assert [item["id"] for item in result["items"]] == ["new-external-scene"]


def test_probe_tag_ids_orders_by_rarity_then_weight(tmp_path: Path) -> None:
    """Probe tags must be the rarest mapped tags, not the highest-weighted.

    Content weights saturate to near-equal values on well-tagged scenes, so a
    high-frequency tag with a slightly higher weight must not displace the rare
    tags that define the theme from the tight INCLUDES_ALL probe.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (
            ("school", "School", "school"),
            ("teacher", "Teacher", "teacher"),
            ("student", "Student", "student"),
            ("common", "Common", "common"),
        ),
    )
    connection.executemany(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        (
            ("school", "https://stashdb.org/graphql", "ext-school"),
            ("teacher", "https://stashdb.org/graphql", "ext-teacher"),
            ("student", "https://stashdb.org/graphql", "ext-student"),
            ("common", "https://stashdb.org/graphql", "ext-common"),
        ),
    )
    connection.executemany(
        """
        INSERT INTO feature_definition(
            feature_id, feature_version, family, name, provenance, metadata_json
        ) VALUES (?, 'unit', 'content', ?, 'test', ?)
        """,
        (
            ("f-school", "tag:school", '{"document_frequency": 449}'),
            ("f-teacher", "tag:teacher", '{"document_frequency": 295}'),
            ("f-student", "tag:student", '{"document_frequency": 220}'),
            ("f-common", "tag:common", '{"document_frequency": 5000}'),
        ),
    )
    content = {
        "id:ext-school": 0.2813,  # highest weight, but only fourth-rarest
        "id:ext-teacher": 0.2801,
        "id:ext-student": 0.2794,
        "id:ext-common": 0.2790,
    }
    service = ExpandService(connection)

    assert service._probe_tag_ids(content) == [
        "ext-student",
        "ext-teacher",
        "ext-school",
        "ext-common",
    ]


def test_targeted_performer_similar_narrows_retrieval_to_target_age(
    tmp_path: Path,
) -> None:
    """Performer retrieval must add an age floor for mature targets.

    Popularity-ranked pools skew young, so a mature target used to get young
    lookalikes that never matched its age block. The age-constrained query brings
    same-or-older performers into the pool, and the re-ranker ranks them first.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_performer SET birthdate='1969-01-01' WHERE performer_id='p1'")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = PerformerPoolStashDB()
    service = ExpandService(connection)

    result = service.targeted_similar(
        client,
        {
            "scenes": {},
            "scene_phashes": {},
            "performers": {"p1": "known-external-performer"},
            "studios": {},
        },
        "performer",
        "p1",
        gender="FEMALE",
    )

    assert len(client.inputs) == 3
    assert all(value["sort"] == "POPULARITY" for value in client.inputs)
    assert all(value["gender"] == "FEMALE" for value in client.inputs)
    fallback = next(
        value for value in client.inputs if "age" not in value and "performed_with" not in value
    )
    assert fallback["per_page"] == 500
    age_query = next(value for value in client.inputs if "age" in value)
    expected_lower = max(0, int(ExpandService._age("1969-01-01") - 12))
    assert expected_lower >= 25
    assert age_query["age"] == {"value": expected_lower, "modifier": "GREATER_THAN"}
    co_star_query = next(value for value in client.inputs if "performed_with" in value)
    assert co_star_query["performed_with"] == "known-external-performer"
    assert "age" not in co_star_query
    identifiers = [item["id"] for item in result["items"]]
    assert identifiers == ["mature-lookalike"]
    assert "young-popular" not in identifiers


def test_targeted_performer_similar_prefers_established_performers(
    tmp_path: Path,
) -> None:
    """Career size must break similarity ties in the final ranking.

    A perfectly matching obscure performer used to outrank an established one
    with a slightly weaker profile match, because every retrieved candidate had
    the same neutral appeal. Scene count re-orders them: the established
    performer wins even though its raw similarity is lower.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = PopularityPoolStashDB()
    service = ExpandService(connection)

    result = service.targeted_similar(
        client,
        {
            "scenes": {},
            "scene_phashes": {},
            "performers": {"p1": "known-external-performer"},
            "studios": {},
        },
        "performer",
        "p1",
        gender="FEMALE",
    )

    identifiers = [item["id"] for item in result["items"]]
    assert identifiers == ["popular-performer", "obscure-performer"]
    assert result["items"][0]["similarity"] < result["items"][1]["similarity"]
    assert result["items"][0]["score"] > result["items"][1]["score"]


class CoStarPoolStashDB:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        if input_data.get("performed_with"):
            performers = [
                {
                    "id": "co-star-performer",
                    "name": "Co-Star Performer",
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
                    "scene_count": 300,
                    "tattoos": [],
                    "piercings": [],
                    "images": [],
                }
            ]
        else:
            performers = []
        return {"queryPerformers": {"performers": performers}}


def test_targeted_performer_similar_probes_performed_with_co_stars(
    tmp_path: Path,
) -> None:
    """The co-star probe must pull performers who worked with the target.

    Popularity-ranked sweeps and the age floor miss performers who shared scenes
    with the target but are not globally popular. The performed_with query
    reaches that ecosystem, and its results enter the scored pool. Without a
    StashDB mapping for the target, no co-star probe is issued.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    links = {
        "scenes": {},
        "scene_phashes": {},
        "performers": {"p1": "known-external-performer"},
        "studios": {},
    }

    client = CoStarPoolStashDB()
    result = service.targeted_similar(client, links, "performer", "p1", gender="FEMALE")

    assert any(value.get("performed_with") == "known-external-performer" for value in client.inputs)
    assert "co-star-performer" in [item["id"] for item in result["items"]]

    unlinked = CoStarPoolStashDB()
    service.targeted_similar(
        unlinked,
        {**links, "performers": {}},
        "performer",
        "p1",
        gender="FEMALE",
    )
    assert not any(value.get("performed_with") for value in unlinked.inputs)


class OwnedTwinStashDB:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def execute(self, _document: str, variables: dict[str, object]):
        input_data = variables["input"]
        assert isinstance(input_data, dict)
        self.inputs.append(input_data)
        profile = {
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
            "scene_count": 500,
            "tattoos": [],
            "piercings": [],
            "images": [],
        }
        return {
            "queryPerformers": {
                "performers": [
                    {"id": "owned-p2-external", "name": "Owned Twin", **profile},
                    {"id": "known-external-performer", "name": "Target Twin", **profile},
                    {"id": "brand-new", "name": "Brand New", **profile},
                ]
            }
        }


def test_targeted_performer_similar_include_owned_keeps_library_performers(
    tmp_path: Path,
) -> None:
    """include_owned keeps library performers in the remote ranking.

    Owned (already-in-library) performers are fetched by the pool queries but
    dropped before ranking so the tab surfaces only new finds. The comparison
    mode keeps them, excluding only the searched performer herself, so the
    remote ranking can be checked against the local one.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    links = {
        "scenes": {},
        "scene_phashes": {},
        "performers": {
            "p1": "known-external-performer",
            "p2": "owned-p2-external",
        },
        "studios": {},
    }

    excluded = OwnedTwinStashDB()
    result = service.targeted_similar(excluded, links, "performer", "p1", gender="FEMALE")
    identifiers = [item["id"] for item in result["items"]]
    assert "brand-new" in identifiers
    assert "owned-p2-external" not in identifiers
    assert "known-external-performer" not in identifiers

    included = OwnedTwinStashDB()
    result = service.targeted_similar(
        included,
        links,
        "performer",
        "p1",
        gender="FEMALE",
        include_owned=True,
    )
    identifiers = [item["id"] for item in result["items"]]
    assert "owned-p2-external" in identifiers
    assert "brand-new" in identifiers
    assert "known-external-performer" not in identifiers
    owned_twin = next(item for item in result["items"] if item["id"] == "owned-p2-external")
    assert owned_twin["payload"]["curator_local"] == {"id": "p2", "favorite": False}
    brand_new = next(item for item in result["items"] if item["id"] == "brand-new")
    assert "curator_local" not in brand_new["payload"]


class OwnedSceneTwinStashDB:
    """StashDB stub returning both library-owned and new scenes for scene similar."""

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
        scenes = [
            {
                "id": "owned-external-ref",
                "title": "Reference scene (already owned)",
                "release_date": date.today().isoformat(),
                "studio": {"id": "external-studio", "name": "Studio"},
                "tags": [{"id": "external-tag", "name": "Useful"}],
                "images": [],
                "performers": [{"performer": performer}],
            },
            {
                "id": "owned-external-twin",
                "title": "Another owned scene",
                "release_date": date.today().isoformat(),
                "studio": {"id": "external-studio", "name": "Studio"},
                "tags": [{"id": "external-tag", "name": "Useful"}],
                "images": [],
                "performers": [{"performer": performer}],
            },
            {
                "id": "brand-new-scene",
                "title": "Brand new scene",
                "release_date": date.today().isoformat(),
                "studio": {"id": "external-studio", "name": "Studio"},
                "tags": [{"id": "external-tag", "name": "Useful"}],
                "images": [{"url": "https://example.test/scene.jpg"}],
                "performers": [{"performer": performer}],
            },
        ]
        return {"queryScenes": {"count": len(scenes), "scenes": scenes}}


def test_targeted_scene_similar_include_owned_keeps_library_scenes(
    tmp_path: Path,
) -> None:
    """include_owned keeps library scenes in the remote ranking.

    Owned scenes are fetched by the probes but dropped before ranking so the
    tab surfaces only new finds.  Comparison mode keeps them, excluding only
    the reference scene itself, and annotates curator_local for the "In
    library" badge and local-profile link.
    """
    connection = _database(tmp_path / "curator.sqlite3")
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        (("sim-63", "Useful", "hash-sim-63"),),
    )
    connection.execute(
        "INSERT INTO scene_marker(marker_id, scene_id, seconds, primary_tag_id, source_hash) "
        "VALUES ('marker-sim-63', 'old-good', 0, 'sim-63', 'hash-marker-sim-63')"
    )
    connection.executemany(
        "INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id) VALUES (?, ?, ?)",
        (
            ("good", "https://stashdb.org/graphql", "external-good"),
            ("sim-63", "https://stashdb.org/graphql", "external-tag"),
        ),
    )
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    service = ExpandService(connection)
    links = {
        "scenes": {
            "old-good": "owned-external-ref",
            "recent-good": "owned-external-twin",
        },
        "scene_phashes": {},
        "performers": {},
        "studios": {},
    }

    excluded_db = OwnedSceneTwinStashDB()
    result = service.targeted_similar(excluded_db, links, "scene", "old-good", gender="")
    identifiers = [item["id"] for item in result["items"]]
    assert "brand-new-scene" in identifiers
    assert "owned-external-twin" not in identifiers
    assert "owned-external-ref" not in identifiers

    included_db = OwnedSceneTwinStashDB()
    result = service.targeted_similar(
        included_db,
        links,
        "scene",
        "old-good",
        gender="",
        include_owned=True,
    )
    identifiers = [item["id"] for item in result["items"]]
    assert "owned-external-twin" in identifiers
    assert "brand-new-scene" in identifiers
    assert "owned-external-ref" not in identifiers
    owned_twin = next(item for item in result["items"] if item["id"] == "owned-external-twin")
    assert owned_twin["payload"]["curator_local"] == {"id": "recent-good"}
    brand_new = next(item for item in result["items"] if item["id"] == "brand-new-scene")
    assert "curator_local" not in brand_new["payload"]


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


def test_unused_local_tag_preference_scores_matching_external_scenes(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('unused', 'Unused', 'unused')"
    )
    connection.execute(
        """
        INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id)
        VALUES ('unused', 'https://stashdb.org/graphql', 'external-unused')
        """
    )
    model = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    InteractionStore(connection).submit_tag_preferences(
        [{"preference_id": "unused", "tag_id": "unused", "value": -1, "occurred_at_ms": 10}]
    )
    scenes, _ = ExpandService(connection)._score(
        [
            {
                "id": "tagged",
                "tags": [{"id": "external-unused", "name": "Unused"}],
                "performers": [],
            },
            {"id": "plain", "tags": [], "performers": []},
        ],
        {"tagged": {"wildcard"}, "plain": {"wildcard"}},
        model.model_id,
        model.feature_version,
        {"scenes": {}, "performers": {}, "studios": {}},
    )

    scores = {item["id"]: item["score"] for item in scenes}
    assert scores["tagged"] < scores["plain"]


def test_description_term_preference_ranks_matching_external_scenes(
    tmp_path: Path,
) -> None:
    """Remote scenes are ranked by description term affinity: with identical
    tags/performers/studio, the scene whose description carries a positively
    declared term scores higher, and the explanation names the term."""
    connection = _database(tmp_path / "curator.sqlite3")
    model = PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    InteractionStore(connection).submit_term_preferences(
        [{"preference_id": "term-good", "term": "romantic", "value": 1, "occurred_at_ms": 10}]
    )
    scenes, _ = ExpandService(connection)._score(
        [
            {
                "id": "described",
                "details": "A romantic candlelight encounter with intense chemistry.",
                "tags": [],
                "performers": [],
            },
            {
                "id": "plain",
                "details": "An athletic outdoor adventure near the mountains.",
                "tags": [],
                "performers": [],
            },
        ],
        {"described": {"wildcard"}, "plain": {"wildcard"}},
        model.model_id,
        model.feature_version,
        {"scenes": {}, "performers": {}, "studios": {}},
    )

    scores = {item["id"]: item["score"] for item in scenes}
    assert scores["described"] > scores["plain"]
    why = {item["id"]: item["payload"]["why"] for item in scenes}
    assert "romantic" in why["described"]
    assert "romantic" not in why["plain"]


class DescribedStashDB(FakeStashDB):
    """FakeStashDB whose candidates carry a description mentioning 'romantic'."""

    def execute(self, document: str, variables: dict[str, object]):
        result = super().execute(document, variables)
        for scene in result["queryScenes"]["scenes"]:
            scene["details"] = "A romantic candlelight encounter with intense chemistry."
        return result


def test_blocked_term_excludes_remote_pool_scenes(tmp_path: Path) -> None:
    """Blocking a description term removes every remote candidate whose
    description tokens include it from the Expand results, even when the term
    is not part of the built model (the remote mapping tokenizes the
    description; it has no entity_feature join)."""
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    client = DescribedStashDB()
    links = {
        "scenes": {"old-good": "owned-external-scene"},
        "performers": {"p1": "known-external-performer"},
        "studios": {"studio-1": "external-studio"},
    }
    ExpandService(connection).refresh(client, links, now_ms=REFERENCE_MS, candidate_limit=10)
    assert [item["id"] for item in ExpandService(connection).results("scene")["items"]] == [
        "new-external-scene"
    ]

    connection.execute(
        """
        INSERT INTO direct_term_preference_history(
            preference_id, term, value, occurred_at_ms, blocked
        ) VALUES ('pref-block', 'romantic', 0, 1, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO direct_term_preference(
            term, preference_id, value, occurred_at_ms, blocked
        ) VALUES ('romantic', 'pref-block', 0, 1, 1)
        """
    )
    connection.commit()
    assert ExpandService(connection).results("scene")["items"] == []
