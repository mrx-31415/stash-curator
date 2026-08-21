"""Unit tests for the apiSchemaVersion 2 explanation payload builder."""

from __future__ import annotations

import sqlite3

from curator.api import CuratorAPI
from curator.model import PreferenceModelBuilder
from tests.model.test_builder import REFERENCE_MS, _database


def _build(tmp_path) -> tuple[sqlite3.Connection, CuratorAPI]:
    connection = _database(tmp_path / "curator.sqlite3")
    PreferenceModelBuilder(connection, clock_ms=lambda: REFERENCE_MS).build()
    return connection, CuratorAPI(connection)


def test_v2_payload_has_exact_shape(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        payload = api.explanation("recent-good")
        assert payload["apiSchemaVersion"] == 2
        assert isinstance(payload["summary"], str) and payload["summary"]
        assert isinstance(payload["components"], list)
        assert payload["components"]
        assert isinstance(payload["reasons"], list)
        assert payload["reasons"]
        assert isinstance(payload["lane_context"], dict)
        assert isinstance(payload["scores"], dict)
        assert set(payload["scores"]) == {"appeal", "current_fit", "confidence", "rank"}
        assert isinstance(payload["evidence_fingerprint"], dict)
        assert "axes" in payload["evidence_fingerprint"]
    finally:
        connection.close()


def test_v2_components_are_named_scaled_rows_with_units(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        payload = api.explanation("recent-good")
        rows = payload["components"]
        assert {row["key"] for row in rows} == {
            "content_similarity",
            "performer_match",
            "studio_appeal",
            "direct_feedback",
            "right_now_fit",
            "confidence",
        }
        for row in rows:
            assert row["label"]
            assert row["unit"] in {"similarity", "appeal", "percent"}
            assert -1.0 <= row["value"] <= 1.0
        # Novelty is NOT a model component — it must never appear.
        assert not any("novelty" in row["key"] for row in rows)
    finally:
        connection.close()


def test_v2_evidence_fingerprint_has_six_fixed_axes(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        payload = api.explanation("recent-good")
        axes = payload["evidence_fingerprint"]["axes"]
        assert set(axes) == {
            "content",
            "performers",
            "studios",
            "similar_scenes",
            "direct_history",
            "metadata_coverage",
        }
        for key, axis in axes.items():
            assert 0.0 <= axis["strength"] <= 1.0
            assert axis["tone"] in {"support", "caution", "neutral"}
            assert isinstance(axis["present"], bool)
        # Metadata coverage is always neutral, not a preference axis.
        assert axes["metadata_coverage"]["tone"] == "neutral"
        assert axes["metadata_coverage"]["present"] is True
    finally:
        connection.close()


def test_v2_scores_carry_units(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        payload = api.explanation("recent-good")
        scores = payload["scores"]
        assert scores["appeal"]["unit"] == "signed"
        assert scores["current_fit"]["unit"] == "signed"
        assert scores["confidence"]["unit"] == "percent"
        assert scores["rank"]["unit"] == "percent"
        assert -1.0 <= scores["appeal"]["value"] <= 1.0
        assert 0.0 <= scores["confidence"]["value"] <= 1.0
    finally:
        connection.close()


def test_v2_lane_context_is_typed_union_when_lane_exists(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        # old-good qualifies for the revisit lane.
        payload = api.explanation("old-good")
        context = payload["lane_context"]
        assert context["lane"] == "revisit"
        assert context["intent"] == "revisit"
        assert context["subtype"] is None
        assert "facets" in context
        assert "durable_signals" in context["facets"]
        # A scene with no lane gets an empty (not fabricated) lane_context.
        payload = api.explanation("unlabeled")
        assert payload["lane_context"] == {}
    finally:
        connection.close()


def test_v2_reasons_are_backend_ranked_support_first(tmp_path) -> None:
    connection, api = _build(tmp_path)
    try:
        payload = api.explanation("recent-good")
        reasons = payload["reasons"]
        assert reasons
        # The first reason must be a support (positive-direction) fact.
        assert reasons[0]["direction"] == "positive"
        # Supports are ordered by descending signed strength.
        directions = [reason["direction"] for reason in reasons]
        first_negative = next(
            (index for index, direction in enumerate(directions) if direction == "negative"),
            len(directions),
        )
        assert all(d == "positive" for d in directions[:first_negative])
    finally:
        connection.close()
