"""Slice-4 backend differential harness: the last frontend-parity ops and the
entity-sync hook mode.

get_external_tag_choices, get_inspector_entity, get_tag_sentiment_follow_up,
reset, and the entity-sync hook run through the Go binary and
plugin/backend.py on fresh sidecar copies. Stdout must be byte-identical per
the tolerance policy (structure exact, floats within rel 1e-9); the reset and
hook tests also compare the sidecar/artifact state they mutate (modulo run
timestamps), including the hook's no-curator_job-row contract.

Synthetic sidecars only — never a live sidecar.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from curator.config import DEFAULT_CONFIG
from curator.core import core_binary
from tests.core.test_backend import PLUGIN_DIR, make_sidecar, payload, run_backend
from tests.core.test_backend_slice3_backups import assert_slice3_identical

FEATURE_FP = DEFAULT_CONFIG.feature_fingerprint()[:20]
CONFIG_VERSION = f"cfg-{FEATURE_FP}"
FEATURE_VERSION = "fv-x"
MODEL_ID = "model-x"
STASHDB = "https://stashdb.org/graphql"

HOOK_TYPES = {
    "Scene.Create.Post",
    "Scene.Update.Post",
    "Scene.Destroy.Post",
    "Performer.Create.Post",
    "Performer.Update.Post",
    "Performer.Destroy.Post",
    "Studio.Create.Post",
    "Studio.Update.Post",
    "Studio.Destroy.Post",
    "Tag.Create.Post",
    "Tag.Update.Post",
    "Tag.Destroy.Post",
}


class _StubSlice4(BaseHTTPRequestHandler):
    """Stash stub answering the settings query (empty plugin settings)."""

    plugin_settings: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        if "CuratorPluginSettings" in body:
            data: dict[str, object] = {"data": {"configuration": {"plugins": {}}}}
            if self.plugin_settings:
                data = {
                    "data": {"configuration": {"plugins": {"stash-curator": self.plugin_settings}}}
                }
        else:
            data = {"errors": [{"message": f"no stub for {body[:80]}"}]}
        payload_bytes = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload_bytes)))
        self.end_headers()
        self.wfile.write(payload_bytes)

    def log_message(self, *args: object) -> None:  # silence the stub
        pass


@pytest.fixture(scope="module")
def binary() -> Path:
    path = core_binary()
    if path is None:
        pytest.skip("curator-core binary not built; run scripts/verify core")
    return path


@pytest.fixture(scope="module")
def stub_stash() -> str:
    server = HTTPServer(("127.0.0.1", 0), _StubSlice4)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def make_slice4_sidecar(path: Path) -> None:
    """A migrated sidecar exercising every new op: a published model with
    scores and a neighbor, taste-profile affinities, performer profiles,
    tag/stash-id/taxonomy rows, and direct tag preferences."""
    make_sidecar(path, with_jobs=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO source_scene(
                scene_id, title, play_count, play_duration_seconds, updated_at, source_hash
            ) VALUES
                ('s1', 'Scene One', 3, 600, '2026-01-01T00:00:00Z', 'h-s1'),
                ('s2', 'Scene Two', 0, 300, '2026-01-02T00:00:00Z', 'h-s2'),
                ('s3', 'Scene Three', 1, 120, '2026-01-03T00:00:00Z', 'h-s3'),
                ('s5', 'Scene Five', 0, 60, '2026-01-05T00:00:00Z', 'h-s5')
            """
        )
        connection.execute(
            """
            INSERT INTO source_tag(tag_id, name, source_hash)
            VALUES ('t1', 'football', 'a'), ('t2', 'archery', 'b'),
                   ('t3', 'cycling', 'c'), ('t4', 'swimming', 'd'),
                   ('t5', 'archery', 'e')
            """
        )
        connection.execute(
            f"""
            INSERT INTO tag_role(config_version, tag_id, role, resolution_reason)
            VALUES ('{CONFIG_VERSION}', 't1', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't2', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't3', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't4', 'content', 'seeded'),
                   ('{CONFIG_VERSION}', 't5', 'content', 'seeded')
            """
        )
        connection.execute(
            """
            INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id)
            VALUES ('t1', ?, 'stash-t1'), ('t2', ?, 'stash-t2')
            """,
            (STASHDB, STASHDB),
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference_history(
                preference_id, tag_id, value, occurred_at_ms, blocked
            ) VALUES ('pref-t1', 't1', 0.5, 1, 0), ('pref-t3', 't3', 0.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO direct_tag_preference(
                tag_id, preference_id, value, occurred_at_ms, blocked
            ) VALUES ('t1', 'pref-t1', 0.5, 1, 0), ('t3', 'pref-t3', 0.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO scene_tag(scene_id, tag_id, provenance)
            VALUES ('s1', 't1', 'scene'), ('s1', 't2', 'scene'), ('s1', 't4', 'scene'),
                   ('s2', 't1', 'scene'), ('s3', 't3', 'scene')
            """
        )
        connection.execute(
            """
            INSERT INTO source_performer(performer_id, name, source_hash, updated_at)
            VALUES ('p1', 'Alice', 'ph-1', '2026-01-01T00:00:00Z'),
                   ('p2', 'Bob', 'ph-2', '2026-01-01T00:00:00Z'),
                   ('p3', 'Carol', 'ph-3', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO model_version(
                model_id, status, feature_version, config_json, created_at_ms, validation_status
            ) VALUES (?, 'published', ?, '{}', 1, 'valid')
            """,
            (MODEL_ID, FEATURE_VERSION),
        )
        connection.execute(
            """
            INSERT INTO model_scene_score(
                model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
                appeal, current_fit, confidence, metadata_confidence, recovery,
                components_json, eligibility_json
            ) VALUES
                (?, 's1', -0.3, -0.3, 0.9, -0.30, 0.0, 0.90, 0.9, 0.0,
                 '{"baseline": {"raw": 0.2, "value": 0.2}}', '{"eligible": true}'),
                (?, 's2', -0.1, -0.1, 0.4, -0.10, 0.0, 0.40, 0.4, 0.0, '{}', '{}'),
                (?, 's3', 0.2, 0.2, 0.8, 0.20, 0.0, 0.80, 0.8, 0.0, '{}', '{}')
            """,
            (MODEL_ID, MODEL_ID, MODEL_ID),
        )
        connection.execute(
            """
            INSERT INTO model_scene_neighbor(
                model_id, scene_id, neighbor_scene_id, similarity, weight, outcome, rank
            ) VALUES (?, 's1', 's2', 0.45, 0.5, 0.1, 0),
                     (?, 's1', 's3', 0.30, 0.5, 0.05, 1)
            """,
            (MODEL_ID, MODEL_ID),
        )
        connection.execute(
            """
            INSERT INTO feature_definition(
                feature_id, feature_version, family, name, provenance, metadata_json
            ) VALUES
                ('fd-t1', ?, 'content', 'tag:t1', 'seed', '{}'),
                ('fd-t2', ?, 'content', 'tag:t2', 'seed', '{}'),
                ('fd-t3', ?, 'content', 'tag:t3', 'seed', '{}'),
                ('fd-t4', ?, 'content', 'tag:t4', 'seed', '{}'),
                ('pf-meas', ?, 'profile:measurements', 'cup_index', 'seed', '{}'),
                ('pf-aug-nat', ?, 'profile:augmentation', 'natural', 'seed', '{}'),
                ('pf-aug-fake', ?, 'profile:augmentation', 'fake', 'seed', '{}')
            """,
            (
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
            ),
        )
        connection.execute(
            """
            INSERT INTO feature_affinity(
                feature_id, model_id, affinity, confidence, effective_support,
                distinct_scene_count
            ) VALUES
                ('fd-t1', ?, 0.4, 0.8, 0.5, 2),
                ('fd-t2', ?, -0.3, 0.5, 0.3, 1),
                ('fd-t3', ?, 0.1, 0.2, 0.1, 2),
                ('fd-t4', ?, 0.9, 0.9, 0.7, 1)
            """,
            (MODEL_ID, MODEL_ID, MODEL_ID, MODEL_ID),
        )
        connection.execute(
            """
            INSERT INTO feature_definition(
                feature_id, feature_version, family, name, provenance, metadata_json
            ) VALUES
                ('fd-d1', ?, 'content', 'desc:archery', 'seed', '{"document_frequency": 7}'),
                ('fd-d2', ?, 'content', 'desc:football', 'seed', '{"document_frequency": 3}'),
                ('fd-d3', ?, 'content', 'desc:cycling', 'seed', '{"document_frequency": 9}')
            """,
            (FEATURE_VERSION, FEATURE_VERSION, FEATURE_VERSION),
        )
        connection.execute(
            """
            INSERT INTO feature_affinity(
                feature_id, model_id, affinity, confidence, effective_support,
                distinct_scene_count
            ) VALUES
                ('fd-d1', ?, 0.8, 0.9, 0.6, 2),
                ('fd-d2', ?, -0.2, 0.4, 0.2, 1),
                ('fd-d3', ?, 0.5, 0.7, 0.4, 3)
            """,
            (MODEL_ID, MODEL_ID, MODEL_ID),
        )
        connection.execute(
            """
            INSERT INTO entity_feature(
                feature_version, entity_type, entity_id, feature_id, value, confidence
            ) VALUES
                (?, 'scene', 's1', 'fd-d1', 0.9, 1.0),
                (?, 'scene', 's1', 'fd-d3', 0.5, 1.0),
                (?, 'scene', 's2', 'fd-d2', 0.4, 1.0)
            """,
            (FEATURE_VERSION, FEATURE_VERSION, FEATURE_VERSION),
        )
        connection.execute(
            """
            INSERT INTO direct_term_preference_history(
                preference_id, term, value, occurred_at_ms, blocked
            ) VALUES ('pref-d1', 'archery', 0.5, 1, 0), ('pref-d2', 'cycling', 0.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO direct_term_preference(
                term, preference_id, value, occurred_at_ms, blocked
            ) VALUES ('archery', 'pref-d1', 0.5, 1, 0), ('cycling', 'pref-d2', 0.0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO entity_feature(
                feature_version, entity_type, entity_id, feature_id, value, confidence
            ) VALUES
                (?, 'performer', 'p1', 'pf-meas', 3.0, 1.0),
                (?, 'performer', 'p1', 'pf-aug-nat', 1.0, 1.0),
                (?, 'performer', 'p2', 'pf-meas', 3.0, 1.0),
                (?, 'performer', 'p2', 'pf-aug-nat', 1.0, 1.0),
                (?, 'performer', 'p3', 'pf-meas', 6.0, 1.0),
                (?, 'performer', 'p3', 'pf-aug-fake', 1.0, 1.0)
            """,
            (
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
                FEATURE_VERSION,
            ),
        )
        connection.execute(
            """
            INSERT INTO taxonomy_snapshot(
                snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
            ) VALUES ('snap-1', ?, 1, 0, 2)
            """,
            (STASHDB,),
        )
        connection.execute(
            """
            INSERT INTO taxonomy_tag(snapshot_id, tag_id, name)
            VALUES ('snap-1', 'tax-1', 'Swimming Style'), ('snap-1', 'tax-2', 'Cycling')
            """
        )
        connection.execute(
            """
            INSERT INTO taxonomy_tag_alias(snapshot_id, tag_id, alias)
            VALUES ('snap-1', 'tax-1', 'HairStyle')
            """
        )
        connection.execute(
            """
            INSERT INTO tag_taxonomy_match(
                local_tag_id, snapshot_id, external_tag_id, external_category_id,
                match_method, confidence, ambiguity_count
            ) VALUES ('t4', 'snap-1', 'tax-1', NULL, 'name', 0.9, 1),
                     ('t3', 'snap-1', 'tax-2', NULL, 'name', 0.9, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', 'snap-1')
            """
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def slice4_sidecar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("slice4-sidecar") / "curator.sqlite3"
    make_slice4_sidecar(path)
    return path


def assert_slice4_identical(
    binary: Path, raw: bytes, same_path: Path, *, normalize: tuple[str, ...] = ()
) -> None:
    """Run both backends on fresh sidecar copies and compare stdout with the
    tolerance comparator (structure exact, floats within rel 1e-9)."""
    assert_slice3_identical(binary, raw, same_path, normalize=normalize)


# ── get_external_tag_choices ────────────────────────────────────────────────


def test_external_tag_choices_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    raw = payload(
        "get_external_tag_choices",
        slice4_sidecar,
        stub_stash,
        tags=[
            {"id": "stash-t1", "name": "football"},  # stable stash_id match
            {"id": "", "name": "cycling"},  # unique name match
            {"id": "", "name": "HairStyle"},  # taxonomy alias match
            {"id": "", "name": "Swimming Style"},  # taxonomy name match
            {"id": "", "name": "archery"},  # ambiguous name -> skipped
            {"id": "missing", "name": "ghost"},  # unknown -> skipped
            {"id": "stash-t2", "name": "archery"},  # stash_id beats ambiguity
            {"id": "", "name": "football"},  # duplicate tag -> deduped
        ],
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_external_tag_choices_validation_errors(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    assert_slice4_identical(
        binary,
        payload("get_external_tag_choices", slice4_sidecar, stub_stash, tags="nope"),
        slice4_sidecar,
    )
    assert_slice4_identical(
        binary,
        payload(
            "get_external_tag_choices",
            slice4_sidecar,
            stub_stash,
            tags=[{"id": f"x{i}", "name": f"n{i}"} for i in range(101)],
        ),
        slice4_sidecar,
    )
    # Non-dict entries are dropped; blank entries are dropped.
    assert_slice4_identical(
        binary,
        payload(
            "get_external_tag_choices",
            slice4_sidecar,
            stub_stash,
            tags=[
                {"id": "stash-t1", "name": "  football  "},
                "junk",
                {},
                {"id": "", "name": "   "},
            ],
        ),
        slice4_sidecar,
    )


# ── get_scene_tag_choices ───────────────────────────────────────────────────


def test_scene_tag_choices_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # s1 carries t1 (football, direct 0.5), t2 (archery), t4 (swimming): the
    # classified scene tags sorted by name with their direct preferences.
    raw = payload("get_scene_tag_choices", slice4_sidecar, stub_stash, scene_id="s1")
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_scene_tag_choices_unclassified_and_unknown(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # s3 carries only t3 (cycling, blocked) — classified, with its preference.
    raw = payload("get_scene_tag_choices", slice4_sidecar, stub_stash, scene_id="s3")
    assert_slice4_identical(binary, raw, slice4_sidecar)
    # Unknown scene and missing scene_id both error identically.
    raw = payload("get_scene_tag_choices", slice4_sidecar, stub_stash, scene_id="ghost")
    assert_slice4_identical(binary, raw, slice4_sidecar)
    raw = payload("get_scene_tag_choices", slice4_sidecar, stub_stash, scene_id="")
    assert_slice4_identical(binary, raw, slice4_sidecar)


# ── get_scene_description_tokens ────────────────────────────────────────────


def test_scene_description_tokens_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # s1 has desc:archery (df 7, direct 0.5) and desc:cycling (df 9, blocked).
    raw = payload("get_scene_description_tokens", slice4_sidecar, stub_stash, scene_id="s1")
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_scene_description_tokens_empty_and_unknown(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # s3 has no desc features -> empty items.
    raw = payload("get_scene_description_tokens", slice4_sidecar, stub_stash, scene_id="s3")
    assert_slice4_identical(binary, raw, slice4_sidecar)
    raw = payload("get_scene_description_tokens", slice4_sidecar, stub_stash, scene_id="ghost")
    assert_slice4_identical(binary, raw, slice4_sidecar)
    raw = payload("get_scene_description_tokens", slice4_sidecar, stub_stash, scene_id="")
    assert_slice4_identical(binary, raw, slice4_sidecar)


# ── submit_term_preferences ─────────────────────────────────────────────────


def test_submit_term_preferences_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    raw = payload(
        "submit_term_preferences",
        slice4_sidecar,
        stub_stash,
        entries=[
            # overwrite the seeded archery preference
            {"preference_id": "pref-n1", "term": "archery", "value": -0.5, "occurred_at_ms": 200},
            # clear a term with no current preference (no-op upsert path)
            {"preference_id": "pref-n2", "term": "football", "value": None, "occurred_at_ms": 300},
            # term normalization: "Hockey" -> "hockey", a valid token
            {"preference_id": "pref-n3", "term": "Hockey", "value": 1.0, "occurred_at_ms": 400},
        ],
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_submit_term_preferences_blocked_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    raw = payload(
        "submit_term_preferences",
        slice4_sidecar,
        stub_stash,
        entries=[
            {
                "preference_id": "pref-n4",
                "term": "archery",
                "value": 1.0,
                "blocked": True,
                "occurred_at_ms": 250,
            }
        ],
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_submit_term_preferences_validation_errors(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # Off-scale value.
    assert_slice4_identical(
        binary,
        payload(
            "submit_term_preferences",
            slice4_sidecar,
            stub_stash,
            entries=[
                {"preference_id": "pref-n5", "term": "archery", "value": 0.3, "occurred_at_ms": 100}
            ],
        ),
        slice4_sidecar,
    )
    # Non-token term (too short / punctuation).
    assert_slice4_identical(
        binary,
        payload(
            "submit_term_preferences",
            slice4_sidecar,
            stub_stash,
            entries=[
                {"preference_id": "pref-n6", "term": "a!", "value": 0.5, "occurred_at_ms": 100}
            ],
        ),
        slice4_sidecar,
    )
    # Missing preference_id and negative occurred_at_ms.
    assert_slice4_identical(
        binary,
        payload(
            "submit_term_preferences",
            slice4_sidecar,
            stub_stash,
            entries=[{"preference_id": "", "term": "archery", "value": 0.5, "occurred_at_ms": -1}],
        ),
        slice4_sidecar,
    )
    # Non-list entries.
    assert_slice4_identical(
        binary,
        payload("submit_term_preferences", slice4_sidecar, stub_stash, entries="nope"),
        slice4_sidecar,
    )


# ── get_inspector_entity ────────────────────────────────────────────────────


def test_inspector_scene_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    raw = payload(
        "get_inspector_entity", slice4_sidecar, stub_stash, entity_type="scene", entity_id="s1"
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_inspector_scene_error_paths(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    assert_slice4_identical(
        binary,
        payload(
            "get_inspector_entity",
            slice4_sidecar,
            stub_stash,
            entity_type="scene",
            entity_id="missing",
        ),
        slice4_sidecar,
    )


def test_inspector_performer_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    raw = payload(
        "get_inspector_entity", slice4_sidecar, stub_stash, entity_type="performer", entity_id="p1"
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_inspector_performer_error_paths(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    assert_slice4_identical(
        binary,
        payload(
            "get_inspector_entity",
            slice4_sidecar,
            stub_stash,
            entity_type="performer",
            entity_id="p9",
        ),
        slice4_sidecar,
    )
    assert_slice4_identical(
        binary,
        payload(
            "get_inspector_entity", slice4_sidecar, stub_stash, entity_type="studio", entity_id="x"
        ),
        slice4_sidecar,
    )


def test_inspector_requires_published_model(tmp_path: Path, binary: Path, stub_stash: str) -> None:
    sidecar = tmp_path / "nomodel.sqlite3"
    make_sidecar(sidecar, with_jobs=True)
    raw = payload("get_inspector_entity", sidecar, stub_stash, entity_type="scene", entity_id="s1")
    assert_slice4_identical(binary, raw, sidecar)


# ── get_tag_sentiment_follow_up ─────────────────────────────────────────────


def test_tag_sentiment_follow_up_byte_identical(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    # s1 tags: t1 (direct preference -> excluded), t2 (weak negative),
    # t4 (strong positive). limit caps at 3.
    raw = payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s1", limit=3)
    assert_slice4_identical(binary, raw, slice4_sidecar)
    raw = payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s1", limit=1)
    assert_slice4_identical(binary, raw, slice4_sidecar)
    raw = payload(
        "get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s1", limit=99
    )
    assert_slice4_identical(binary, raw, slice4_sidecar)
    # A scene with no tags but present in the library returns an empty list.
    raw = payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s5", limit=3)
    assert_slice4_identical(binary, raw, slice4_sidecar)


def test_tag_sentiment_follow_up_error_paths(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    assert_slice4_identical(
        binary,
        payload(
            "get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="missing", limit=3
        ),
        slice4_sidecar,
    )
    assert_slice4_identical(
        binary,
        payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="", limit=3),
        slice4_sidecar,
    )
    assert_slice4_identical(
        binary,
        payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s1", limit=0),
        slice4_sidecar,
    )
    assert_slice4_identical(
        binary,
        payload("get_tag_sentiment_follow_up", slice4_sidecar, stub_stash, scene_id="s1", limit=-1),
        slice4_sidecar,
    )


def test_tag_sentiment_follow_up_requires_model(
    tmp_path: Path, binary: Path, stub_stash: str
) -> None:
    sidecar = tmp_path / "nomodel2.sqlite3"
    make_sidecar(sidecar, with_jobs=True)
    raw = payload("get_tag_sentiment_follow_up", sidecar, stub_stash, scene_id="s1", limit=3)
    assert_slice4_identical(binary, raw, sidecar)


# ── reset ───────────────────────────────────────────────────────────────────


def _reset_payload(db_path: Path, confirmation: str) -> bytes:
    return json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": 0,
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {
                "operation": "reset",
                "database_path": str(db_path),
                "confirmation": confirmation,
            },
        },
        separators=(",", ":"),
    ).encode()


def test_reset_requires_confirmation(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    assert_slice4_identical(binary, _reset_payload(slice4_sidecar, "NOPE"), slice4_sidecar)


def test_reset_while_job_running_errors(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    sidecar = tmp_path / "running.sqlite3"
    shutil.copy2(slice4_sidecar, sidecar)
    connection = sqlite3.connect(sidecar)
    try:
        connection.execute(
            """
            INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
            VALUES ('job-running', 'sync-build', 'running', 1)
            """
        )
        connection.commit()
    finally:
        connection.close()
    assert_slice4_identical(binary, _reset_payload(sidecar, "RESET"), sidecar)


def test_reset_removes_core_and_artifacts_identically(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    """Reset deletes the database, WAL/SHM sidecars, and recognized artifacts
    (not unrelated files), recreates a migrated sidecar, and both
    implementations agree on every surviving file and the recreated database."""
    run_dir = tmp_path / "reset-run"
    results: list[tuple[bytes, int, list[str], list[str], int, str]] = []
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        db = run_dir / "curator.sqlite3"
        shutil.copy2(slice4_sidecar, db)
        derived = run_dir / "curator-derived"
        derived.mkdir()
        (derived / "model-aaaaaaaaaaaaaaaaaaaa.sqlite3").write_bytes(b"x")
        (derived / "feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3").write_bytes(b"y")
        (derived / ".model-bbbbbbbbbbbbbbbbbbbb.deadbeefdeadbeefdeadbeefdeadbeef.tmp").write_bytes(
            b"t"
        )
        (derived / "junk.txt").write_bytes(b"z")
        (run_dir / "curator.sqlite3-wal").write_bytes(b"w")
        result = run_backend(runner, PLUGIN_DIR, _reset_payload(db, "RESET"))
        remaining = sorted(p.name for p in run_dir.iterdir())
        remaining_derived = sorted(p.name for p in derived.iterdir())
        with sqlite3.connect(db) as connection:
            latest = int(
                connection.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
            )
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        results.append(
            (result.stdout, result.returncode, remaining, remaining_derived, latest, integrity)
        )
        shutil.rmtree(run_dir, ignore_errors=True)
    py, go = results
    assert py[1] == go[1] == 0
    assert py[0] == go[0], f"stdout differs:\npython: {py[0]!r}\ngo:     {go[0]!r}"
    assert py[2] == go[2] == ["curator-derived", "curator.sqlite3"]
    assert py[3] == go[3] == ["junk.txt"]
    assert py[4] == go[4] == 37
    assert py[5] == go[5] == "ok"


# ── entity-sync hook ────────────────────────────────────────────────────────


def _hook_payload(db_path: Path, hook_context: object, port: int) -> bytes:
    return json.dumps(
        {
            "server_connection": {
                "Host": "127.0.0.1",
                "Port": port,
                "Scheme": "http",
                "SessionCookie": {},
            },
            "args": {"hookContext": hook_context, "database_path": str(db_path)},
        },
        separators=(",", ":"),
    ).encode()


def _run_hook(
    binary: Path | None,
    plugin_dir: Path,
    raw: bytes,
    sidecar: Path,
    run_dir: Path,
    port: int,
) -> tuple[bytes, int, list[tuple[str, str, str]], int, tuple[int, int, str | None]]:
    """Run entity-sync against a fresh copy (rewriting the payload's
    database_path and port) and report stdout plus the sidecar state the hook
    mutates: pending_entity_change rows, curator_job count, and the
    coordinator generation/cause."""
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir()
    db = run_dir / "curator.sqlite3"
    shutil.copy2(sidecar, db)
    parsed = json.loads(raw)
    parsed["args"]["database_path"] = str(db)
    parsed["server_connection"]["Port"] = port
    result = run_backend(
        binary, plugin_dir, json.dumps(parsed, separators=(",", ":")).encode(), mode="entity-sync"
    )
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        pending = [
            (row["entity_type"], row["entity_id"], row["operation"])
            for row in connection.execute(
                "SELECT entity_type, entity_id, operation FROM pending_entity_change"
                " ORDER BY entity_type, entity_id"
            )
        ]
        job_count = int(connection.execute("SELECT count(*) FROM curator_job").fetchone()[0])
        state = connection.execute(
            """
            SELECT requested_generation, published_generation, last_cause
            FROM model_update_state WHERE singleton=1
            """
        ).fetchone()
    shutil.rmtree(run_dir, ignore_errors=True)
    return (
        result.stdout,
        result.returncode,
        pending,
        job_count,
        (
            int(state["requested_generation"]),
            int(state["published_generation"]),
            state["last_cause"],
        ),
    )


@pytest.mark.parametrize(
    "hook_context",
    [
        {"type": "Scene.Update.Post", "id": "scene-42"},
        {"type": "Scene.Create.Post", "id": "scene-42"},
        {"type": "Scene.Destroy.Post", "id": "scene-42"},
        {"type": "Performer.Create.Post", "id": "perf-7"},
        {"type": "Studio.Update.Post", "id": "studio-9"},
        {"type": "Tag.Destroy.Post", "id": "tag-1"},
        {"type": "Tag.Merge.Post", "id": "tag-1"},
        {"type": "Something.Else.Post", "id": "x"},
        {"type": "Scene.Update.Post"},
        None,
        {"id": "no-type"},
    ],
)
def test_entity_sync_hook_byte_identical(
    tmp_path: Path,
    binary: Path,
    stub_stash: str,
    slice4_sidecar: Path,
    hook_context: object,
) -> None:
    """The hook output is byte-identical, the enqueued row lands in
    pending_entity_change with the right operation, and — the hook contract —
    no curator_job row is created while the coordinator is signaled."""
    port = int(stub_stash.rsplit(":", 1)[1])
    raw = _hook_payload(slice4_sidecar, hook_context, port)
    results = []
    for runner in (None, binary):
        results.append(
            _run_hook(
                runner,
                PLUGIN_DIR,
                raw,
                slice4_sidecar,
                tmp_path / f"hook-run-{runner is None}",
                port,
            )
        )
    py, go = results
    assert py[1] == go[1] == 0
    assert py[0] == go[0], f"stdout differs:\npython: {py[0]!r}\ngo:     {go[0]!r}"
    assert py[2] == go[2], f"pending_entity_change differs: {py[2]} vs {go[2]}"
    assert py[3] == go[3] == 0, "the hook must not create a curator_job row"
    assert py[4] == go[4], f"coordinator state differs: {py[4]} vs {go[4]}"
    out = json.loads(py[0])["output"]
    known = isinstance(hook_context, dict) and hook_context.get("type") in HOOK_TYPES
    has_id = isinstance(hook_context, dict) and bool(hook_context.get("id"))
    if known and has_id:
        assert out["handled"] is True and out["enqueued"] is True
        entity_type = str(hook_context["type"]).split(".")[0].lower()
        assert out["entity_type"] == entity_type
        assert py[2] == [
            (
                entity_type,
                str(hook_context["id"]),
                "delete" if str(hook_context["type"]).endswith(".Destroy.Post") else "upsert",
            )
        ]
        assert py[4][0] == 1 and py[4][2] == "entity_hook"
    else:
        assert out["handled"] is False
        assert py[2] == []
        assert py[4][0] == 0


def test_entity_sync_hook_updates_existing_row(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    """Two destroys then an upsert leave one row with operation 'upsert'
    (the ON CONFLICT upsert supersedes), identically in both backends."""
    port = int(stub_stash.rsplit(":", 1)[1])
    run_dir = tmp_path / "hook-update"
    rows_by_runner: dict[bool, list[tuple[str, str, str]]] = {}
    for runner in (None, binary):
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir()
        db = run_dir / "curator.sqlite3"
        shutil.copy2(slice4_sidecar, db)
        for hook_context in (
            {"type": "Scene.Destroy.Post", "id": "scene-42"},
            {"type": "Scene.Destroy.Post", "id": "scene-42"},
            {"type": "Scene.Update.Post", "id": "scene-42"},
        ):
            result = run_backend(
                runner,
                PLUGIN_DIR,
                _hook_payload(db, hook_context, port),
                mode="entity-sync",
            )
            assert result.returncode == 0
        with sqlite3.connect(db) as connection:
            connection.row_factory = sqlite3.Row
            rows_by_runner[runner is None] = [
                (row["entity_type"], row["entity_id"], row["operation"])
                for row in connection.execute(
                    "SELECT entity_type, entity_id, operation FROM pending_entity_change"
                )
            ]
        shutil.rmtree(run_dir, ignore_errors=True)
    assert rows_by_runner[True] == rows_by_runner[False]
    assert rows_by_runner[True] == [("scene", "scene-42", "upsert")]


def test_unknown_operation_errors_natively(
    tmp_path: Path, binary: Path, stub_stash: str, slice4_sidecar: Path
) -> None:
    """The Python fallback is retired: unknown operations and task modes error
    with Python's exact messages from the binary itself."""
    raw = payload("not_an_operation", slice4_sidecar, stub_stash)
    direct = run_backend(None, PLUGIN_DIR, raw)
    go = run_backend(binary, PLUGIN_DIR, raw)
    assert go.stdout == direct.stdout
    assert go.returncode == direct.returncode == 1
    assert (
        json.loads(go.stdout)["error"]
        == json.loads(direct.stdout)["error"]
        == ("unknown Curator API operation: not_an_operation")
    )
    raw_task = payload("prepare", slice4_sidecar, stub_stash)
    direct_task = run_backend(None, PLUGIN_DIR, raw_task, mode="bogus-mode")
    go_task = run_backend(binary, PLUGIN_DIR, raw_task, mode="bogus-mode")
    assert go_task.stdout == direct_task.stdout
    assert go_task.returncode == direct_task.returncode == 1
    assert json.loads(go_task.stdout)["error"] == "unknown Curator task: bogus-mode"
