"""Unit tests for curation.curation_impact: the model-diff impact report."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from curator.curation import curation_impact
from tests.core.test_backend import make_sidecar

MODEL_OLDER = "model-" + "a" * 20
MODEL_NEWER = "model-" + "b" * 20
FEATURE = "fv-" + "1" * 20
ARTIFACT_OLDER = f"{MODEL_OLDER}.sqlite3"
ARTIFACT_NEWER = f"{MODEL_NEWER}.sqlite3"
ARTIFACT_FEATURE = f"feature-{FEATURE}.sqlite3"


def _artifact_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _write_feature_artifact(derived: Path) -> None:
    connection = _artifact_db(derived / ARTIFACT_FEATURE)
    connection.execute("CREATE TABLE feature_definition(feature_id TEXT, name TEXT, family TEXT)")
    connection.executemany(
        "INSERT INTO feature_definition VALUES (?, ?, ?)",
        [
            ("f1", "performer:p1", "performer_identity"),
            ("f2", "performer:p2", "performer_identity"),
            ("f7", "performer:p3", "performer_identity"),
            ("f3", "tag:t1", "content"),
            ("f4", "tag:t2", "content"),
            ("f5", "studio:st1", "studio"),
            ("f6", "desc:thing", "content"),
        ],
    )
    connection.execute(
        "CREATE TABLE entity_feature(feature_version TEXT, entity_id TEXT, feature_id TEXT)"
    )
    connection.executemany(
        "INSERT INTO entity_feature VALUES (?, ?, ?)",
        [
            (FEATURE, "s1", "f3"),
            (FEATURE, "s1", "f1"),
            (FEATURE, "s5", "f4"),
            (FEATURE, "s5", "f2"),
            (FEATURE, "s3", "f6"),
            (FEATURE, "s10", "f7"),
            (FEATURE, "s4", "f2"),
            (FEATURE, "s2", "f1"),
        ],
    )
    connection.commit()
    connection.close()


def _write_model_artifact(
    derived: Path,
    basename: str,
    model_id: str,
    scores: list[tuple[str, str, float]],
    affinities: list[tuple[str, str, float, float]],
) -> None:
    connection = _artifact_db(derived / basename)
    connection.execute(
        "CREATE TABLE model_scene_score("
        "model_id TEXT, scene_id TEXT, general_appeal REAL, direct_appeal REAL)"
    )
    connection.executemany("INSERT INTO model_scene_score VALUES (?, ?, ?, ?)", scores)
    connection.execute(
        "CREATE TABLE feature_affinity("
        "model_id TEXT, feature_id TEXT, affinity REAL, confidence REAL)"
    )
    connection.executemany("INSERT INTO feature_affinity VALUES (?, ?, ?, ?)", affinities)
    connection.commit()
    connection.close()


def make_impact_sidecar(tmp_path: Path, *, n_models: int = 2, with_artifacts: bool = True) -> Path:
    """A migrated sidecar with two model builds and synthetic score artifacts.

    Score deltas (newer minus older):
      s5 +0.375, s1 +0.125, s10 +0.0625, s9 +0.0625 (tie -> s10 before s9),
      s3 +0.03125, s6 +0.0078125 (below threshold), s4 -0.25, s2 -0.125; s7
      only in newer, s8 only in older (both excluded). Effective affinity
      deltas: p1 +0.125, p3 +0.0078125 (below the scene floor but reported),
      p2 -0.125, t1 +0.1875, t2 0. Scene contributors: s1 carries tag:t1 +
      performer:p1; s5 carries tag:t2 (no move) + performer:p2; s3 carries a
      desc feature (not an entity).
    """
    sidecar = tmp_path / "curator.sqlite3"
    make_sidecar(sidecar)
    connection = sqlite3.connect(sidecar)
    connection.row_factory = sqlite3.Row
    connection.executemany(
        "INSERT INTO source_studio(studio_id, name, source_hash) VALUES (?, ?, ?)",
        [("st1", "Studio A", "a"), ("st2", "Studio B", "b")],
    )
    connection.executemany(
        """INSERT INTO source_scene(scene_id, studio_id, title, updated_at, source_hash)
           VALUES (?, ?, ?, '2026-01-01T00:00:00Z', ?)""",
        [
            ("s1", "st1", "One", "h1"),
            ("s2", "st2", "Two", "h2"),
            ("s3", None, "Three", "h3"),
            ("s4", "st1", "Four", "h4"),
            ("s5", None, "Five", "h5"),
            ("s6", None, "Six", "h6"),
            ("s7", None, "Seven", "h7"),
            ("s8", None, "Eight", "h8"),
            ("s9", None, "Nine", "h9"),
            ("s10", None, "Ten", "h10"),
        ],
    )
    connection.executemany(
        "INSERT INTO source_performer(performer_id, name, source_hash) VALUES (?, ?, ?)",
        [("p1", "Alice", "a"), ("p2", "Bob", "b"), ("p3", "Carol", "c")],
    )
    connection.executemany(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
        [("t1", "knitting", "a"), ("t2", "chess", "b")],
    )
    if n_models >= 1:
        connection.execute(
            """INSERT INTO model_version(model_id, status, feature_version, config_json,
                   created_at_ms, published_at_ms, artifact_basename, validation_status)
               VALUES (?, 'superseded', ?, '{}', 1, 1000, ?, 'valid')""",
            (MODEL_OLDER, FEATURE, ARTIFACT_OLDER),
        )
    if n_models >= 2:
        connection.execute(
            """INSERT INTO model_version(model_id, status, feature_version, config_json,
                   created_at_ms, published_at_ms, artifact_basename, validation_status)
               VALUES (?, 'published', ?, '{}', 2, 2000, ?, 'valid')""",
            (MODEL_NEWER, FEATURE, ARTIFACT_NEWER),
        )
    connection.execute(
        """INSERT INTO feature_build(feature_version, status, config_json,
               source_fingerprint, created_at_ms, artifact_basename)
           VALUES (?, 'published', '{}', 'fp', 1, ?)""",
        (FEATURE, ARTIFACT_FEATURE),
    )
    connection.commit()
    connection.close()

    if with_artifacts:
        derived = sidecar.with_name(sidecar.stem + "-derived")
        derived.mkdir()
        _write_feature_artifact(derived)
        _write_model_artifact(
            derived,
            ARTIFACT_OLDER,
            MODEL_OLDER,
            [
                (MODEL_OLDER, "s1", 0.5, 0.25),
                (MODEL_OLDER, "s2", 0.5, 0.25),
                (MODEL_OLDER, "s3", 0.5, 0.1),
                (MODEL_OLDER, "s4", 0.5, 0.25),
                (MODEL_OLDER, "s5", 0.125, 0.25),
                (MODEL_OLDER, "s6", 0.5, 0.25),
                (MODEL_OLDER, "s8", 0.3, 0.25),
                (MODEL_OLDER, "s9", 0.25, 0.25),
                (MODEL_OLDER, "s10", 0.25, 0.25),
            ],
            [
                (MODEL_OLDER, "f1", 0.5, 1.0),
                (MODEL_OLDER, "f2", 0.5, 1.0),
                (MODEL_OLDER, "f7", 0.5, 1.0),
                (MODEL_OLDER, "f3", 0.25, 0.5),
                (MODEL_OLDER, "f4", 0.5, 1.0),
                (MODEL_OLDER, "f5", 0.25, 1.0),
                (MODEL_OLDER, "f6", 0.5, 1.0),
            ],
        )
        _write_model_artifact(
            derived,
            ARTIFACT_NEWER,
            MODEL_NEWER,
            [
                (MODEL_NEWER, "s1", 0.625, 0.5625),
                (MODEL_NEWER, "s2", 0.375, 0.25),
                (MODEL_NEWER, "s3", 0.53125, 0.1),
                (MODEL_NEWER, "s4", 0.25, 0.25),
                (MODEL_NEWER, "s5", 0.5, 0.25),
                (MODEL_NEWER, "s6", 0.5078125, 0.25),
                (MODEL_NEWER, "s7", 0.9, 0.25),
                (MODEL_NEWER, "s9", 0.3125, 0.25),
                (MODEL_NEWER, "s10", 0.3125, 0.25),
            ],
            [
                (MODEL_NEWER, "f1", 0.625, 1.0),
                (MODEL_NEWER, "f2", 0.375, 1.0),
                (MODEL_NEWER, "f7", 0.5078125, 1.0),
                (MODEL_NEWER, "f3", 0.625, 0.5),
                (MODEL_NEWER, "f4", 0.5, 1.0),
                (MODEL_NEWER, "f5", 0.375, 1.0),
                (MODEL_NEWER, "f6", 0.5, 1.0),
            ],
        )
    return sidecar


def _read_impact(tmp_path: Path, **kwargs: object) -> dict[str, object]:
    sidecar = make_impact_sidecar(tmp_path, **kwargs)
    connection = sqlite3.connect(sidecar)
    connection.row_factory = sqlite3.Row
    try:
        return curation_impact(connection)
    finally:
        connection.close()


def test_impact_reports_movers(tmp_path: Path) -> None:
    result = _read_impact(tmp_path)
    assert result["available"] is True
    assert result["newer_model_id"] == MODEL_NEWER
    assert result["older_model_id"] == MODEL_OLDER
    assert result["published_at_ms"] == 2000

    scenes = result["scenes"]
    assert isinstance(scenes, dict)
    promoted = scenes["promoted"]
    demoted = scenes["demoted"]
    assert isinstance(promoted, list) and isinstance(demoted, list)
    # Only feedback-driven movers: s9 and s3 moved purely with the re-sync
    # (no direct feedback, no entity they carry moved) and are excluded.
    assert [(s["scene_id"], s["delta"]) for s in promoted] == [
        ("s5", 0.375),
        ("s1", 0.125),
        ("s10", 0.0625),
    ]
    # s4 -0.25 (carries p2), s2 -0.125 (carries p1).
    assert [(s["scene_id"], s["delta"]) for s in demoted] == [("s4", -0.25), ("s2", -0.125)]
    assert all(s["contributors"] for s in promoted + demoted)
    # Metadata: s1 carries studio/title; s5 has no studio.
    by_id = {s["scene_id"]: s for s in promoted}
    assert by_id["s1"]["title"] == "One"
    assert by_id["s1"]["studio"] == "Studio A"
    assert by_id["s1"]["date"] is None
    assert by_id["s5"]["studio"] is None
    # Sub-threshold (s6 +0.01), single-model (s7), and stale (s8) scenes excluded.
    assert all(s["scene_id"] != "s6" for s in promoted)
    assert all(s["scene_id"] != "s7" for s in promoted + demoted)
    assert all(s["scene_id"] != "s8" for s in promoted + demoted)

    performers = result["performers"]
    assert isinstance(performers, dict)
    assert [(p["performer_id"], p["delta"]) for p in performers["promoted"]] == [
        ("p1", 0.125),
        ("p3", 0.0078125),
    ]
    assert [(p["performer_id"], p["delta"]) for p in performers["demoted"]] == [("p2", -0.125)]
    assert performers["promoted"][0]["name"] == "Alice"

    tags = result["tags"]
    assert isinstance(tags, dict)
    assert [(t["tag_id"], t["delta"]) for t in tags["promoted"]] == [("t1", 0.1875)]
    # t2 did not move; desc:thing is not a tag.
    assert tags["demoted"] == []
    assert tags["promoted"][0]["name"] == "knitting"

    # Scene "why": top entity contributors by |delta| that the scene carries.
    s1 = next(s for s in promoted if s["scene_id"] == "s1")
    assert s1["contributors"] == [
        {"kind": "direct", "id": "s1", "name": "Your direct feedback", "delta": 0.3125},
        {"kind": "tag", "id": "t1", "name": "knitting", "delta": 0.1875},
        {"kind": "performer", "id": "p1", "name": "Alice", "delta": 0.125},
    ]
    s5 = next(s for s in promoted if s["scene_id"] == "s5")
    assert s5["contributors"] == [
        {"kind": "performer", "id": "p2", "name": "Bob", "delta": -0.125},
    ]
    s10 = next(s for s in promoted if s["scene_id"] == "s10")
    assert s10["contributors"] == [
        {"kind": "performer", "id": "p3", "name": "Carol", "delta": 0.0078125},
    ]
    # s3 moved but is excluded entirely (no feedback contribution).
    assert all(s["scene_id"] != "s3" for s in promoted + demoted)


def test_impact_hides_sync_only_movers(tmp_path: Path) -> None:
    """When every scene move is a library re-sync artifact, the scene lists
    are empty but the report is still available."""
    sidecar = make_impact_sidecar(tmp_path)
    derived = sidecar.with_name(sidecar.stem + "-derived")
    feature = derived / ARTIFACT_FEATURE
    connection = sqlite3.connect(feature)
    try:
        connection.execute("DELETE FROM entity_feature")
        connection.commit()
    finally:
        connection.close()
    # Neutralize s1's direct move too, so no scene has any contributor.
    for basename, model_id in ((ARTIFACT_OLDER, MODEL_OLDER), (ARTIFACT_NEWER, MODEL_NEWER)):
        db = sqlite3.connect(derived / basename)
        try:
            db.execute(
                "UPDATE model_scene_score SET direct_appeal=0.25 WHERE model_id=?",
                (model_id,),
            )
            db.commit()
        finally:
            db.close()
    result = (
        _read_impact(tmp_path, n_models=0) if False else curation_impact(_open_sidecar(sidecar))
    )
    assert result["available"] is True
    assert result["scenes"]["promoted"] == []
    assert result["scenes"]["demoted"] == []


def _open_sidecar(sidecar: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(sidecar)
    connection.row_factory = sqlite3.Row
    return connection


def test_impact_requires_two_models(tmp_path: Path) -> None:
    result = _read_impact(tmp_path, n_models=1)
    assert result["available"] is False
    assert result["reason"] == "need two built models to measure impact"


def test_impact_requires_artifacts(tmp_path: Path) -> None:
    result = _read_impact(tmp_path, with_artifacts=False)
    assert result["available"] is False
    assert result["reason"] == "model artifacts unavailable"
