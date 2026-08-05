"""Characterization tests for LanePolicy._percentiles()'s tie-handling and
_component_value()'s defensive fallbacks.
"""

import pytest

from curator.model import ModelSceneScore
from curator.ranking.policy import _component_value, _percentiles


def _synthetic_score(components: dict[str, object]) -> ModelSceneScore:
    return ModelSceneScore(
        model_id="model",
        scene_id="scene",
        general_appeal=0.0,
        direct_appeal=0.0,
        direct_confidence=0.0,
        appeal=0.0,
        current_fit=0.0,
        confidence=0.0,
        metadata_confidence=0.0,
        recovery=0.0,
        components=components,
        neighbors=(),
        eligibility={},
    )


def test_empty_input_returns_empty() -> None:
    assert _percentiles({}) == {}


def test_single_item_gets_zero() -> None:
    assert _percentiles({"a": 5.0}) == {"a": 0.0}


def test_all_equal_values_get_midpoint() -> None:
    assert _percentiles({"a": 1.0, "b": 1.0, "c": 1.0}) == {"a": 0.5, "b": 0.5, "c": 0.5}


def test_distinct_values_spread_evenly() -> None:
    assert _percentiles({"a": 1.0, "b": 2.0, "c": 3.0}) == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_tied_group_gets_averaged_rank_not_first_of_group() -> None:
    # Two scenes tied at the low end share the AVERAGE of the positions they occupy
    # (0 and 1, averaged to 0.5), not the position of the first member of the tie (0).
    result = _percentiles({"a": 1.0, "b": 1.0, "c": 2.0})
    assert result == {"a": 0.25, "b": 0.25, "c": 1.0}


def test_multiple_tied_groups() -> None:
    # positions: a,b -> 0,1 (avg 0.5); c -> 2; d,e -> 3,4 (avg 3.5). denominator = 4.
    result = _percentiles({"a": 1.0, "b": 1.0, "c": 2.0, "d": 3.0, "e": 3.0})
    assert result == {"a": 0.125, "b": 0.125, "c": 0.5, "d": 0.875, "e": 0.875}


def test_tie_break_by_scene_id_does_not_affect_percentile() -> None:
    # scene_id only orders which member of a tied group is visited first; the percentile
    # value itself must be identical for every member of the tie regardless of scene_id.
    result = _percentiles({"z": 1.0, "a": 1.0, "m": 1.0})
    assert result["z"] == result["a"] == result["m"]


def test_numpy_and_python_percentiles_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from curator import optional_deps

    values = {
        "a": 1.0,
        "b": 1.0,
        "c": 2.0,
        "d": 3.0,
        "e": 3.0,
        "f": -0.5,
        "g": 0.0,
        "h": 0.0,
    }
    if optional_deps.NUMPY_AVAILABLE:
        accelerated = _percentiles(values)
        monkeypatch.setattr(optional_deps, "NUMPY_AVAILABLE", False)
        monkeypatch.setattr(optional_deps, "np", None)
        fallback = _percentiles(values)
        assert accelerated == fallback


def test_component_value_missing_family_is_zero() -> None:
    assert _component_value(_synthetic_score({}), "content") == 0.0


def test_component_value_non_dict_family_is_zero() -> None:
    assert _component_value(_synthetic_score({"content": [1, 2, 3]}), "content") == 0.0
    assert _component_value(_synthetic_score({"content": "not a dict"}), "content") == 0.0


def test_component_value_missing_value_key_is_zero() -> None:
    assert _component_value(_synthetic_score({"content": {"raw": 0.5}}), "content") == 0.0


def test_component_value_non_numeric_value_is_zero() -> None:
    assert (
        _component_value(_synthetic_score({"content": {"value": "not a number"}}), "content") == 0.0
    )
    assert _component_value(_synthetic_score({"content": {"value": None}}), "content") == 0.0


def test_component_value_true_zero_and_missing_are_indistinguishable() -> None:
    present_zero = _component_value(_synthetic_score({"content": {"value": 0.0}}), "content")
    absent = _component_value(_synthetic_score({}), "content")
    assert present_zero == absent == 0.0
