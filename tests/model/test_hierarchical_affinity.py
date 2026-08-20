"""A tag borrows its prior from its siblings rather than from zero.

Affinities were learned per flat feature and shrunk toward a global zero, so a
thin tag meant "no opinion" no matter how much its category was known. Measured
on a real library the taxonomy carries real signal: predicting a held-out tag's
affinity from its siblings beats predicting zero by about 15% of squared error
(r = +0.33 over 333 tags with support), and shuffling the parent assignments
destroys the effect (permutation p = 0.0025).

The safety property is that nothing without a parent can move.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from curator.config import DEFAULT_CONFIG
from curator.features.store import StoredFeature
from curator.model.builder import PreferenceModelBuilder
from tests.model.test_builder import _database


def _content(feature_id: str, tag_id: str) -> StoredFeature:
    return StoredFeature(feature_id, "content", f"tag:{tag_id}", 1.0, 1.0, {"tag_id": tag_id})


def _builder(tmp_path: Path, hierarchy: tuple[tuple[str, str], ...]) -> PreferenceModelBuilder:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.executemany(
        "INSERT OR IGNORE INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        tuple((parent, parent.title(), f"h-{parent}") for _, parent in hierarchy),
    )
    connection.executemany("INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES (?, ?)", hierarchy)
    connection.commit()
    return PreferenceModelBuilder(connection)


SCENE_FEATURES = {
    "s1": (_content("f-good", "good"), _content("f-bad", "bad"), _content("f-thin", "unusual")),
}


def test_a_tag_with_no_parent_borrows_nothing(tmp_path: Path) -> None:
    builder = _builder(tmp_path, ())

    priors = builder._sibling_priors(
        SCENE_FEATURES, {"f-good": 10.0, "f-bad": 10.0}, {"f-good": 5.0, "f-bad": -5.0}
    )

    assert priors == {}


def test_prior_is_the_support_weighted_mean_of_siblings(tmp_path: Path) -> None:
    builder = _builder(
        tmp_path, (("good", "scenario"), ("bad", "scenario"), ("unusual", "scenario"))
    )
    supports = {"f-good": 9.0, "f-bad": 1.0, "f-thin": 0.5}
    numerators = {"f-good": 9.0, "f-bad": -1.0, "f-thin": 0.0}

    priors = builder._sibling_priors(SCENE_FEATURES, supports, numerators)

    # Unsmoothed affinities: good 9/(1+9) = 0.9 at support 9,
    # bad -1/(1+1) = -0.5 at support 1, thin 0/(1+0.5) = 0.0 at support 0.5.
    assert priors["f-thin"] == pytest.approx((0.9 * 9.0 - 0.5 * 1.0) / 10.0)
    # Each tag's own value is excluded from its own prior, and every other
    # sibling is included -- thin counts toward good's and bad's priors.
    assert priors["f-good"] == pytest.approx((-0.5 * 1.0 + 0.0 * 0.5) / 1.5)
    assert priors["f-bad"] == pytest.approx((0.9 * 9.0 + 0.0 * 0.5) / 9.5)


def test_siblings_without_support_are_ignored(tmp_path: Path) -> None:
    builder = _builder(tmp_path, (("good", "scenario"), ("bad", "scenario")))

    priors = builder._sibling_priors(
        SCENE_FEATURES, {"f-good": 9.0, "f-bad": 0.0}, {"f-good": 9.0, "f-bad": 0.0}
    )

    assert "f-good" not in priors, "a zero-support sibling must not create a prior"
    assert priors["f-bad"] == pytest.approx(0.9)


def test_disabling_the_prior_restores_the_previous_behaviour(tmp_path: Path) -> None:
    builder = _builder(tmp_path, (("good", "scenario"), ("bad", "scenario")))
    builder.config = replace(
        DEFAULT_CONFIG, model=replace(DEFAULT_CONFIG.model, affinity_sibling_prior=0.0)
    )

    priors = builder._sibling_priors(
        SCENE_FEATURES, {"f-good": 9.0, "f-bad": 9.0}, {"f-good": 9.0, "f-bad": -9.0}
    )

    assert priors == {}


def test_hierarchy_moves_a_thin_tag_and_leaves_orphans_alone(tmp_path: Path) -> None:
    """End to end: the same corpus with and without a taxonomy."""
    flat = _database(tmp_path / "flat.sqlite3")
    flat_result = PreferenceModelBuilder(flat).build()

    nested_path = tmp_path / "nested.sqlite3"
    nested = _database(nested_path)
    nested.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('scenario', 'Scenario', 'h')"
    )
    nested.executemany(
        "INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES (?, ?)",
        (("good", "scenario"), ("bad", "scenario"), ("unusual", "scenario")),
    )
    nested.commit()
    nested_result = PreferenceModelBuilder(nested).build()

    assert nested_result.model_id != flat_result.model_id


def test_affinities_are_unchanged_without_any_taxonomy(tmp_path: Path) -> None:
    """The safety claim: a library with no tag parents is bit-identical to
    what it produced before the sibling prior existed."""
    connection = _database(tmp_path / "curator.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM tag_parent").fetchone()[0] == 0
    builder = PreferenceModelBuilder(connection)

    priors = builder._sibling_priors(
        SCENE_FEATURES, {"f-good": 9.0, "f-bad": 9.0}, {"f-good": 9.0, "f-bad": -9.0}
    )

    assert priors == {}
