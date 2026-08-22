"""Shared curation sidecar fixture for the backend differential harnesses.

make_slice5_sidecar builds a migrated sidecar with the base curation data
the pair-picks differential (slice 6) runs against: taxonomy-matched tags, a
published model with scores, a labeled scene, a blocked tag, and a published
taxonomy snapshot. The old curation-batch fixture rows were removed with the
batch ops (issue #191).

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.core.test_backend import make_sidecar

FEATURE_VERSION = "fv-x"
MODEL_ID = "model-m1"


def make_slice5_sidecar(path: Path) -> None:
    """A migrated sidecar exercising the curation selection surface:
    taxonomy-matched tags, a published model with scores, a labeled scene,
    and a blocked tag."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_studio(studio_id, name, source_hash) VALUES
                ('st1', 'Studio A', 'a'), ('st2', 'Studio B', 'b'),
                ('st3', 'Studio C', 'c')
            """
        )
        connection.execute(
            """
            INSERT INTO source_scene(scene_id, studio_id, title, updated_at, source_hash)
            VALUES
                ('s1', 'st1', 'One', '2026-01-01T00:00:00Z', 'h1'),
                ('s2', 'st2', 'Two', '2026-01-01T00:00:00Z', 'h2'),
                ('s3', 'st3', 'Three', '2026-01-01T00:00:00Z', 'h3'),
                ('s4', 'st1', 'Four', '2026-01-01T00:00:00Z', 'h4'),
                ('s5', 'st2', 'Five', '2026-01-01T00:00:00Z', 'h5'),
                ('s6', 'st3', 'Six', '2026-01-01T00:00:00Z', 'h6'),
                ('s7', 'st1', 'Seven', '2026-01-01T00:00:00Z', 'h7'),
                ('s8', 'st2', 'Eight', '2026-01-01T00:00:00Z', 'h8'),
                ('s9', NULL, 'Nine', '2026-01-01T00:00:00Z', 'h9'),
                ('s10', NULL, 'Ten', '2026-01-01T00:00:00Z', 'h10'),
                ('s11', NULL, 'Eleven', '2026-01-01T00:00:00Z', 'h11'),
                ('s12', NULL, 'Twelve', '2026-01-01T00:00:00Z', 'h12'),
                ('s13', NULL, 'Thirteen', '2026-01-01T00:00:00Z', 'h13'),
                ('s14', NULL, 'Fourteen', '2026-01-01T00:00:00Z', 'h14'),
                ('s15', NULL, 'Fifteen', '2026-01-01T00:00:00Z', 'h15'),
                ('s16', NULL, 'Sixteen', '2026-01-01T00:00:00Z', 'h16'),
                ('s17', NULL, 'Seventeen', '2026-01-01T00:00:00Z', 'h17'),
                ('s18', NULL, 'Eighteen', '2026-01-01T00:00:00Z', 'h18'),
                ('s19', NULL, 'Nineteen', '2026-01-01T00:00:00Z', 'h19'),
                ('s20', NULL, 'Twenty', '2026-01-01T00:00:00Z', 'h20')
            """
        )
        connection.execute(
            """
            INSERT INTO source_tag(tag_id, name, source_hash) VALUES
                ('t1', 'lesbian', 'a'), ('t2', 'threesome', 'b'),
                ('t3', 'anal', 'c'), ('t4', 'red hair', 'd'),
                ('t6', 'never', 'f')
            """
        )
        connection.execute(
            """
            INSERT INTO taxonomy_snapshot(snapshot_id, endpoint, fetched_at_ms,
                category_count, tag_count)
            VALUES ('tax-1', 'https://stashdb.org/graphql', 1, 3, 4)
            """
        )
        connection.execute(
            """
            INSERT INTO taxonomy_category(snapshot_id, category_id, name, group_name)
            VALUES
                ('tax-1', 'cat-act', 'Acts', 'ACTION'),
                ('tax-1', 'cat-grp', 'Group Makeup', 'SCENE'),
                ('tax-1', 'cat-hair', 'Hair Color', 'PEOPLE')
            """
        )
        connection.execute(
            """
            INSERT INTO tag_taxonomy_match(local_tag_id, snapshot_id, external_tag_id,
                external_category_id, match_method, confidence, ambiguity_count)
            VALUES
                ('t1', 'tax-1', 'e1', 'cat-grp', 'stable_id', 1, 0),
                ('t2', 'tax-1', 'e2', 'cat-grp', 'stable_id', 1, 0),
                ('t3', 'tax-1', 'e3', 'cat-act', 'stable_id', 1, 0),
                ('t4', 'tax-1', 'e4', 'cat-hair', 'stable_id', 1, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO scene_tag(scene_id, tag_id) VALUES
                ('s1', 't1'), ('s1', 't2'),
                ('s2', 't1'), ('s2', 't3'),
                ('s3', 't1'),
                ('s4', 't2'),
                ('s5', 't3'), ('s5', 't6'),
                ('s7', 't1'), ('s7', 't2'),
                ('s8', 't2'), ('s8', 't3')
            """
        )
        connection.execute(
            "INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', 'tax-1')"
        )
        connection.execute(
            """
            INSERT INTO feedback(feedback_id, scene_id, feedback_type, value,
                occurred_at_ms, payload_json)
            VALUES ('fb-1', 's3', 'thumb_up', NULL, 1, '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference_history(preference_id, tag_id, value,
                occurred_at_ms, blocked)
            VALUES ('pref-1', 't6', -1.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference(tag_id, preference_id, value,
                occurred_at_ms, blocked)
            VALUES ('t6', 'pref-1', -1.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO model_version(model_id, status, feature_version, config_json,
                created_at_ms, validation_status)
            VALUES (?, 'published', ?, '{}', 1, 'valid')
            """,
            (MODEL_ID, FEATURE_VERSION),
        )
        connection.execute(
            """
            INSERT INTO model_scene_score(model_id, scene_id, general_appeal,
                direct_appeal, direct_confidence, appeal, current_fit, confidence,
                metadata_confidence, recovery, components_json, eligibility_json)
            VALUES
                (?, 's1', 0.30, 0.0, 0.0, 0.30, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's2', -0.10, 0.0, 0.0, -0.10, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's3', 0.00, 0.0, 0.0, 0.00, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's4', 0.20, 0.0, 0.0, 0.20, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's5', 0.10, 0.0, 0.0, 0.10, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's6', 0.05, 0.0, 0.0, 0.05, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's7', -0.20, 0.0, 0.0, -0.20, 0.0, 0.5, 0.5, 1.0, '{}', '{}'),
                (?, 's8', 0.15, 0.0, 0.0, 0.15, 0.0, 0.5, 0.5, 1.0, '{}', '{}')
            """,
            (MODEL_ID,) * 8,
        )
        connection.commit()
    finally:
        connection.close()
