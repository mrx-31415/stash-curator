import sqlite3

from curator.features.profiles import PerformerProfile, ProfileValue
from scripts import stashdb_poc
from scripts.stashdb_poc import (
    _dedupe_candidates,
    _external_scene_features,
    _performer_matches,
)


def test_external_candidates_are_deduplicated_and_use_only_allowed_features() -> None:
    scenes = [
        {
            "id": "external",
            "tags": [{"id": "content"}, {"id": "appearance"}],
            "studio": {"id": "known-studio"},
            "performers": [
                {
                    "performer": {
                        "id": "known-performer",
                        "gender": "FEMALE",
                        "ethnicity": "CAUCASIAN",
                        "height": 170,
                    }
                },
                {
                    "performer": {
                        "id": "male-performer",
                        "gender": "MALE",
                        "ethnicity": "BLACK",
                        "height": 190,
                    }
                },
            ],
        },
        {"id": "external", "tags": [], "performers": []},
        {"id": "local", "tags": [], "performers": []},
    ]

    candidates = _dedupe_candidates(scenes, {"local"})
    features = _external_scene_features(
        candidates[0],
        {
            "tag:content",
            "studio:known-studio",
            "performer:known-performer",
            "profile:ethnicity:ethnicity:caucasian",
            "profile:ethnicity:ethnicity:black",
            "profile:height:height_cm",
        },
    )

    assert [scene["id"] for scene in candidates] == ["external"]
    assert "tag:appearance" not in features
    assert features["tag:content"] == 1.0
    assert features["profile:height:height_cm"] == 170
    assert "profile:ethnicity:ethnicity:black" not in features


def test_performer_matching_uses_profile_values(monkeypatch) -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE scene_performer(scene_id TEXT, performer_id TEXT)")
    connection.execute(
        "CREATE TABLE direct_scene_state("
        "model_id TEXT, scene_id TEXT, direct_appeal REAL, confidence REAL)"
    )
    connection.execute("CREATE TABLE source_performer(performer_id TEXT, name TEXT, gender TEXT)")
    connection.execute("INSERT INTO scene_performer VALUES ('scene', 'anchor')")
    connection.execute("INSERT INTO direct_scene_state VALUES ('model', 'scene', 1, 1)")
    connection.execute(
        "INSERT INTO source_performer VALUES ('anchor', 'Known performer', 'FEMALE')"
    )
    profile = PerformerProfile("anchor", {"height": {"height_cm": ProfileValue(170, 1.0)}})

    class Store:
        def __init__(self, _connection) -> None:
            pass

        def performer_profiles(self, _version):
            return {"anchor": profile}

    monkeypatch.setattr(stashdb_poc, "FeatureStore", Store)
    matches = _performer_matches(
        connection,
        "version",
        "model",
        [
            {
                "performers": [
                    {
                        "performer": {
                            "id": "external",
                            "name": "New performer",
                            "gender": "FEMALE",
                            "height": 170,
                        }
                    }
                ]
            }
        ],
        set(),
    )

    assert matches["external"]["matches"][0]["name"] == "Known performer"
