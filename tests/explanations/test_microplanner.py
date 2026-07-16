import json
from dataclasses import replace
from pathlib import Path

import pytest

from curator.explanations.catalog import RealizationCatalog
from curator.explanations.planner import Microplanner
from curator.explanations.reasons import Reason


def _reason(
    code: str,
    *,
    direction: str = "positive",
    magnitude: float = 0.5,
    confidence: float = 0.8,
    detail: dict[str, object] | None = None,
) -> Reason:
    return Reason(
        code,
        direction,
        magnitude,
        confidence,
        "scene",
        "scene-1",
        "standard",
        "test",
        detail or {},
        "model-1",
        "features-1",
    )


def _lane(name: str) -> Reason:
    return _reason(
        "eligibility.lane",
        direction="neutral",
        magnitude=0,
        confidence=1,
        detail={"lane": name},
    )


def test_catalog_is_deterministic_and_rejects_unknown_fields(tmp_path: Path) -> None:
    catalog = RealizationCatalog.load()
    slots = {"performer": "Alex"}
    first = catalog.evidence_variant("appeal.performer_identity", "lead", slots, "seed")
    second = catalog.evidence_variant("appeal.performer_identity", "lead", slots, "seed")
    assert first == second
    pairing_slots = {
        "performer": "Alex",
        "precedent": "Known Scene",
        "precedent_outcome": "which worked well for you",
        "tags": "Office and stockings",
    }
    pairing = catalog.pairing_variant(
        "appeal.performer_identity",
        "appeal.content_neighbor",
        pairing_slots,
        "seed",
    )
    assert pairing is not None
    assert "Alex" in pairing
    assert "Known Scene" in pairing
    assert "worked well for you" in pairing

    payload = json.loads(Path("curator/explanations/realizations.json").read_text())
    payload["evidence"]["fallback"]["lead"] = ["invent {unsupported}"]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unknown realization fields"):
        RealizationCatalog.load(invalid)


def test_revisit_leads_with_direct_memory_even_when_model_evidence_is_stronger() -> None:
    direct = _reason("direct.positive", magnitude=0.2)
    performer = _reason("appeal.performer_identity", magnitude=0.9)
    plan = Microplanner().plan((_lane("revisit"), performer, direct))
    assert plan.primary.reason == direct
    assert plan.support is not None
    assert plan.support.reason == performer


def test_neighbor_absorbs_redundant_standalone_tag_evidence() -> None:
    neighbor = _reason("appeal.content_neighbor")
    tag = _reason("appeal.tag_positive")
    studio = _reason("appeal.studio", magnitude=0.2)
    plan = Microplanner().plan((_lane("best_bets"), tag, studio, neighbor))
    assert plan.primary.reason == neighbor
    assert plan.support is not None
    assert plan.support.reason == studio
    assert tag not in plan.selected_reasons


def test_familiar_performer_similarity_stays_out_of_prose_plan() -> None:
    similarity = _reason("appeal.performer_similar", detail={"novelty_weight": 0.1})
    identity = _reason("appeal.performer_identity")
    plan = Microplanner().plan((_lane("best_bets"), similarity, identity))
    assert identity in plan.selected_reasons
    assert similarity not in plan.selected_reasons


def test_exploration_is_mandatory_boundary_in_exploration_lanes() -> None:
    performer = _reason("appeal.performer_identity")
    exploration = _reason("explore.coverage", direction="unknown")
    for lane in ("discover", "adventure"):
        plan = Microplanner().plan((_lane(lane), performer, exploration))
        assert plan.boundary is not None
        assert plan.boundary.reason == exploration


def test_planning_is_independent_of_reason_input_order() -> None:
    reasons = (
        _lane("best_bets"),
        _reason("appeal.studio"),
        _reason("appeal.performer_identity"),
    )
    first = Microplanner().plan(reasons)
    second = Microplanner().plan(tuple(reversed(reasons)))
    assert first == second


def test_strength_breaks_ties_within_one_reason_type() -> None:
    weaker = _reason("appeal.performer_identity", magnitude=0.2)
    stronger = replace(weaker, subject_id="performer-2", magnitude=0.8)
    plan = Microplanner().plan((_lane("best_bets"), weaker, stronger))
    assert plan.primary.reason == stronger
