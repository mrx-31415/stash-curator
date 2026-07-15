import json
import sqlite3
from pathlib import Path

from curator.explanations import ExplanationService, ReasonGraphStore
from curator.ranking import SlateBuilder
from tests.ranking.test_slate import _database


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

    store.build("model")
    first = store.reasons("model", "a-best")
    store.build("model")
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
    assert explanation.summary == (
        "The tag evidence around Familiar scenario lines up well with your past choices."
    )


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
    assert explanation.summary == (
        "This is a deliberate stretch: it challenges studio while retaining a positive anchor. "
        "Its position was adjusted to keep the page varied."
    )


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
                        "blocks": {"proportions": 0.91, "content": 0.78, "eyes": 0.25},
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
        "body proportions",
        "the kinds of scenes they appear in",
        "eye color",
    ]
    assert "Alex" in explanation.summary
    assert "Blair" in explanation.summary
    assert "body proportions" in explanation.summary
