import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from curator.explanations import ExplanationService, Reason, ReasonGraphStore
from curator.ranking import SlateBuilder
from tests.ranking.test_slate import _database


def test_unknown_exploration_subtype_has_no_card_reason() -> None:
    assert ExplanationService._exploration_code(SimpleNamespace(subtype=None)) is None


def _add_explainable_content(connection: sqlite3.Connection) -> None:
    # The ranking fixture deliberately stores precomputed components. Add one
    # inspectable learned contribution so this test controls the exact claim.
    row = connection.execute(
        "SELECT components_json FROM model_scene_score WHERE scene_id='a-best'"
    ).fetchone()
    components = json.loads(row[0])
    components["content"]["top"] = [
        {
            "feature_id": "feature-x",
            "value": 0.20,
            "confidence": 0.80,
            "metadata": {
                "tag_id": "tag-x",
                "tag_name": "Familiar scenario",
                "document_frequency": 4,
            },
        }
    ]
    connection.execute(
        "UPDATE model_scene_score SET components_json=? WHERE scene_id='a-best'",
        (json.dumps(components),),
    )


def test_reason_graph_is_versioned_truthful_and_deterministic(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    _add_explainable_content(connection)
    store = ReasonGraphStore(connection)

    store.ensure("model")
    first = store.reasons("model", "a-best")
    store.ensure("model")
    second = store.reasons("model", "a-best")

    assert first == second
    assert [reason.code for reason in first] == ["appeal.tag_positive"]
    reason = first[0]
    assert reason.provenance == "learned_feature_affinity"
    assert reason.subject_id == "tag-x"
    assert reason.visibility == "standard"
    assert reason.detail["name"] == "Familiar scenario"
    assert reason.model_id == "model"
    assert reason.feature_version == "features"
    assert reason.magnitude == 0.20
    assert reason.confidence == 0.80

    explanation = ExplanationService(connection).explain_scene("model", "a-best")
    assert "Familiar scenario" in explanation.summary
    assert explanation.selected_reasons == (reason,)


def test_recommendation_explanation_names_the_exploration_tradeoff(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    item = next(
        item
        for item in SlateBuilder(connection).recommend("discover", 10).items
        if item.subtype == "stretch"
    )

    explanation = ExplanationService(connection).explain_recommendation(item)

    assert any(reason.code == "eligibility.lane" for reason in explanation.all_reasons)
    challenge = next(
        reason for reason in explanation.all_reasons if reason.code == "explore.challenge"
    )
    assert challenge.provenance == "lane_policy"
    assert challenge.detail["challenged_assumption"] == "studio"
    assert "studio" in explanation.summary
    assert any(
        phrase in explanation.summary
        for phrase in ("less familiar studio", "usual pattern", "outweigh")
    )
    assert any(reason.code.startswith("diversity.") for reason in explanation.all_reasons)
    assert all(not reason.code.startswith("diversity.") for reason in explanation.selected_reasons)


def test_content_neighbor_explanation_keeps_scene_names_in_evidence(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_scene SET title='Known Good Scene' WHERE scene_id='b-best'")
    connection.execute(
        "UPDATE feature_definition SET metadata_json=? WHERE feature_id='feature-x'",
        (json.dumps({"tag_name": "Shared scenario"}),),
    )
    connection.execute(
        "UPDATE feature_definition SET metadata_json=? WHERE feature_id='feature-q'",
        (json.dumps({"tag_name": "Generic metadata"}),),
    )
    connection.executemany(
        """
        INSERT INTO entity_feature(
            feature_version, entity_type, entity_id, feature_id, value, confidence
        ) VALUES ('features', 'scene', ?, 'feature-q', 1, 1)
        """,
        (("a-best",), ("b-best",)),
    )
    connection.executemany(
        """
        INSERT INTO feature_affinity(
            model_id, feature_id, affinity, confidence, effective_support,
            distinct_scene_count, metadata_json
        ) VALUES ('model', ?, ?, 0.8, 2, 2, '{}')
        """,
        (("feature-x", 0.2), ("feature-q", -0.1)),
    )
    connection.execute(
        "UPDATE model_scene_score SET neighbors_json=? WHERE scene_id='a-best'",
        (
            json.dumps(
                [
                    {
                        "scene_id": "b-best",
                        "similarity": 0.72,
                        "weight": 0.31,
                        "outcome": 0.8,
                    }
                ]
            ),
        ),
    )

    explanation = ExplanationService(connection).explain_scene("model", "a-best")
    reason = next(
        reason for reason in explanation.all_reasons if reason.code == "appeal.content_neighbor"
    )
    neighbors = reason.detail["neighbors"]
    assert isinstance(neighbors, list)
    neighbor = neighbors[0]
    assert isinstance(neighbor, dict)

    assert neighbor["title"] == "Known Good Scene"
    assert neighbor["shared_tags"] == ["Shared scenario"]
    assert "Known Good Scene" not in explanation.summary
    assert "Shared scenario" in explanation.summary


def test_neighbor_titles_stay_in_supporting_evidence_not_card_prose(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    service = ExplanationService(connection)

    assert service._prose_precedent("A short scene title") == "an earlier scene"
    assert (
        service._prose_precedent("A deliberately long scene title for report prose")
        == "an earlier scene"
    )


def test_fused_performer_and_neighbor_claim_keeps_scene_name_in_evidence(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_performer SET name='Alex' WHERE performer_id='p1'")
    identity = Reason(
        "appeal.performer_identity",
        "positive",
        0.4,
        0.9,
        "performer",
        "p1",
        "standard",
        "test",
        {},
        "model",
        "features",
    )
    neighbor = Reason(
        "appeal.content_neighbor",
        "positive",
        0.3,
        0.9,
        "scene",
        "scene-neighbor-id",
        "standard",
        "test",
        {
            "neighbors": [
                {
                    "scene_id": "scene-neighbor-id",
                    "title": "Known Scene",
                    "outcome": 0.8,
                    "shared_tags": ["Office", "Stockings"],
                }
            ]
        },
        "model",
        "features",
    )

    explanation = ExplanationService(connection)._render((identity, neighbor), "seed")

    assert "Alex" in explanation.summary
    assert "Known Scene" not in explanation.summary
    assert "Office and Stockings" in explanation.summary
    assert "scene-neighbor-id" not in explanation.summary


def test_direct_outcome_reason_comes_from_exact_scene_evidence(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    ReasonGraphStore(connection).build("model")

    direct = next(
        reason
        for reason in ReasonGraphStore(connection).reasons("model", "d-revisit")
        if reason.code == "direct.positive"
    )

    assert direct.provenance == "exact_scene_outcomes"
    assert direct.visibility == "private"
    assert direct.detail["signals"] == ["o"]
    assert direct.subject_id == "d-revisit"


def test_every_recommended_item_has_versioned_structured_reasons(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    service = ExplanationService(connection)

    for lane in ("for_you", "best_bets", "revisit", "discover", "adventure"):
        for item in SlateBuilder(connection).recommend(lane, 20).items:
            explanation = service.explain_recommendation(item)
            assert explanation.summary
            assert explanation.all_reasons
            assert any(reason.code == "eligibility.lane" for reason in explanation.all_reasons)
            assert all(reason.model_id == "model" for reason in explanation.all_reasons)
            assert all(reason.feature_version == "features" for reason in explanation.all_reasons)


def test_performer_similarity_explains_the_shared_blocks(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_performer SET name='Alex' WHERE performer_id='p1'")
    connection.execute("UPDATE source_performer SET name='Blair' WHERE performer_id='p2'")
    row = connection.execute(
        "SELECT components_json FROM model_scene_score WHERE scene_id='a-best'"
    ).fetchone()
    components = json.loads(row[0])
    components["performer_similarity"] = {
        "raw": 0.12,
        "value": 0.12,
        "performers": [
            {
                "performer_id": "p1",
                "value": 0.12,
                "matches": [
                    {
                        "performer_id": "p2",
                        "similarity": 0.82,
                        "affinity": 0.30,
                        "blocks": {"measurements": 0.91, "content": 0.78, "eyes": 0.25},
                    }
                ],
            }
        ],
    }
    connection.execute(
        "UPDATE model_scene_score SET components_json=? WHERE scene_id='a-best'",
        (json.dumps(components),),
    )

    explanation = ExplanationService(connection).explain_scene("model", "a-best")
    reason = next(
        reason for reason in explanation.all_reasons if reason.code == "appeal.performer_similar"
    )

    assert reason.detail["shared_aspects"] == [
        "body measurements and proportions",
        "the kinds of scenes they appear in",
        "eye color",
    ]
    assert "Alex" in explanation.summary
    assert "Blair" in explanation.summary
    assert "body measurements and proportions" in explanation.summary


def test_known_performer_similarity_remains_inspectable_but_not_narrated(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute("UPDATE source_performer SET name='Alex' WHERE performer_id='p1'")
    connection.execute("UPDATE source_performer SET name='Blair' WHERE performer_id='p2'")
    row = connection.execute(
        "SELECT components_json FROM model_scene_score WHERE scene_id='a-best'"
    ).fetchone()
    components = json.loads(row[0])
    components["performer_identity"] = {
        "raw": 0.2,
        "value": 0.2,
        "performers": [{"performer_id": "p1", "value": 0.2}],
    }
    components["performer_similarity"] = {
        "raw": 0.01,
        "value": 0.01,
        "performers": [
            {
                "performer_id": "p1",
                "value": 0.01,
                "raw_value": 0.1,
                "identity_confidence": 0.9,
                "novelty_weight": 0.1,
                "matches": [
                    {
                        "performer_id": "p2",
                        "similarity": 0.82,
                        "affinity": 0.30,
                        "blocks": {"measurements": 0.91, "content": 0.78},
                    }
                ],
            }
        ],
    }
    connection.execute(
        "UPDATE model_scene_score SET components_json=? WHERE scene_id='a-best'",
        (json.dumps(components),),
    )

    explanation = ExplanationService(connection).explain_scene("model", "a-best")

    similarity = next(
        reason for reason in explanation.all_reasons if reason.code == "appeal.performer_similar"
    )
    assert similarity.detail["novelty_weight"] == 0.1
    assert similarity not in explanation.selected_reasons
    assert "Alex" in explanation.summary
    assert "Blair" not in explanation.summary
