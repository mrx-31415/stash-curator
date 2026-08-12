"""Deterministic synthetic production-shape sidecar generator (issue #124).

Dev/bench tooling — not shipped in the plugin zip. Builds a migrated sidecar
whose source tables mirror the model-builder test fixture's shape
(tests/model/test_builder.py::_database) but at production scale — the
phase-0 feature shape (~24k scenes, ~8k tags, ~10k performers, ~33 tags per
scene, ~55% labeled) — so the GOMAXPROCS sweep and the CI perf budget run
against a realistic corpus without touching a live sidecar. Scene performers
are drawn from a small known-performer pool (~2% of performers, like the live
library's ~200 known of ~10k), keeping the performer-similarity kernel at its
real O(performers x known) cost. Fixed seeds make the bytes deterministic for
a given shape; the model-build kernel reads the source tables and migrates
itself, so a migrated-plus-data sidecar is sufficient
(taxonomy_snapshot_id may be absent).

Usage:
  python scripts/synthetic_corpus.py PATH [--shape ci|production] [overrides...]
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path

from curator.storage import MigrationRunner, connect_database

# The model build's fixed clock (matches tests.model.test_builder.REFERENCE_MS
# and the sweep/gate payloads).
REFERENCE_MS = 200 * 86_400_000
DAY_MS = 86_400_000

# Shape presets: production = the phase-0 feature shape; ci = the perf-budget
# shape (a build takes ~10-30 s on a dev machine).
PRODUCTION = dict(seed=124, n_scenes=24_000, n_tags=8_000, n_performers=10_000)
CI = dict(seed=124, n_scenes=6_000, n_tags=2_000, n_performers=2_500)

_HAIR = ("Black", "Blonde", "Brown", "Red", "Auburn", "Gray")
_EYES = ("Blue", "Brown", "Green", "Hazel", "Gray")
_ETHNICITY = ("Caucasian", "Asian", "Latina", "Ebony")
_MEASUREMENTS = ("34D-24-36", "34DD-24-36", "36C-26-38", "32B-24-34", "38DD-28-40", "34C-25-36")


def build_sidecar(
    path: Path | str,
    *,
    seed: int = 124,
    n_scenes: int = 24_000,
    n_tags: int = 8_000,
    n_performers: int = 10_000,
    label_frac: float = 0.55,
    tag_per_scene: int = 33,
    desc_words: int = 30,
    word_pool_size: int = 3_000,
    performers_per_scene: int = 2,
    known_performers: int | None = None,
) -> dict[str, int]:
    """Build a migrated synthetic sidecar at production shape and return the
    inserted row counts. Deterministic for a given seed.

    ``known_performers`` bounds the performer-similarity kernel's "known"
    set (performers with learned identity affinity, |value| >= cutoff): only
    performers from this pool are linked to scenes, so the kernel runs
    O(performers x known) like the live library (~200 known of ~10k) instead
    of degenerating to O(performers^2). Defaults to 2% of n_performers.
    """
    rng = random.Random(seed)
    if known_performers is None:
        known_performers = max(20, round(n_performers * 0.02))
    n_studios = max(1, n_scenes // 240)
    connection = connect_database(Path(path))
    try:
        MigrationRunner(connection).migrate(applied_at_ms=1)
        word_pool = [f"word{i:04d}" for i in range(word_pool_size)]
        tagged = max(1, round(n_scenes * label_frac))
        n_plays = max(1, round(n_scenes * 0.30))

        connection.executemany(
            "INSERT INTO source_studio(studio_id, name, favorite, source_hash) VALUES (?, ?, ?, ?)",
            [
                (f"studio-{i:04d}", f"Studio {i:04d}", rng.randint(0, 1), f"sh{i}")
                for i in range(n_studios)
            ],
        )
        connection.executemany(
            "INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, ?)",
            [(f"tag-{i:06d}", f"Tag {i:06d}", f"th{i}") for i in range(n_tags)],
        )
        performer_rows = []
        for i in range(n_performers):
            measurements = rng.choice(_MEASUREMENTS) if rng.random() < 0.7 else None
            performer_rows.append(
                (
                    f"performer-{i:07d}",
                    f"Performer {i:07d}",
                    rng.randint(0, 1),
                    rng.choice(_HAIR),
                    rng.randint(150, 200),
                    measurements,
                    f"ph{i}",
                )
            )
        connection.executemany(
            """
            INSERT INTO source_performer(
                performer_id, name, favorite, hair_color, height_cm, measurements, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            performer_rows,
        )
        scene_rows = []
        file_rows = []
        for i in range(n_scenes):
            scene_id = f"scene-{i:07d}"
            details = " ".join(rng.sample(word_pool, desc_words))
            scene_rows.append(
                (
                    scene_id,
                    f"Scene {i:07d}",
                    details,
                    f"studio-{rng.randrange(n_studios):04d}",
                    f"sch{i}",
                )
            )
            file_rows.append(
                (f"file-{i:07d}", scene_id, round(rng.uniform(600, 3600), 1), f"fh{i}")
            )
        connection.executemany(
            """
            INSERT INTO source_scene(scene_id, title, details, studio_id, source_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            scene_rows,
        )
        connection.executemany(
            """
            INSERT INTO source_file(file_id, scene_id, duration_seconds, available, source_hash)
            VALUES (?, ?, ?, 1, ?)
            """,
            file_rows,
        )
        # Scene tags: tag_per_scene distinct tags per scene (content features).
        scene_tag_rows = []
        for i in range(n_scenes):
            scene_id = f"scene-{i:07d}"
            for tag_index in rng.sample(range(n_tags), tag_per_scene):
                scene_tag_rows.append((scene_id, f"tag-{tag_index:06d}", "scene"))
        connection.executemany(
            "INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, ?)",
            scene_tag_rows,
        )
        # Scene performers: performers_per_scene distinct performers per
        # scene, drawn from the known-performer pool (the live library has a
        # small known set driving the performer-similarity cost; see the
        # known_performers docstring).
        scene_performer_rows = []
        for i in range(n_scenes):
            scene_id = f"scene-{i:07d}"
            for performer_index in rng.sample(range(known_performers), performers_per_scene):
                scene_performer_rows.append((scene_id, f"performer-{performer_index:07d}", 0))
        connection.executemany(
            "INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, ?)",
            scene_performer_rows,
        )
        # Plays on ~30% of scenes.
        play_rows = []
        for i in rng.sample(range(n_scenes), n_plays):
            play_rows.append(
                (
                    f"scene-{i:07d}",
                    REFERENCE_MS - rng.randint(1, 180) * DAY_MS,
                    0,
                )
            )
        connection.executemany(
            "INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, ?)",
            play_rows,
        )
        # One occasion_outcome event for label_frac of scenes (the label
        # derivation source, mirroring the fixture's event shape).
        event_rows = []
        for i in rng.sample(range(n_scenes), tagged):
            outcome = 1.0 if rng.random() < 0.7 else -1.0
            event_rows.append(
                (
                    f"event-{i:08d}",
                    "occasion_outcome",
                    f"scene-{i:07d}",
                    REFERENCE_MS - rng.randint(1, 180) * DAY_MS,
                    outcome,
                    1,
                    "synthetic",
                    '{"primary_signal":"o"}',
                )
            )
        connection.executemany(
            """
            INSERT INTO behavior_event(
                event_id, event_type, scene_id, occurred_at_ms, outcome,
                confidence, provenance, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            event_rows,
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "scenes": n_scenes,
        "tags": n_tags,
        "performers": n_performers,
        "studios": n_studios,
        "labels": tagged,
        "plays": n_plays,
        "scene_tags": len(scene_tag_rows),
        "scene_performers": len(scene_performer_rows),
        "known_performers": known_performers,
    }


def copy_sidecar(source: Path | str, destination: Path | str) -> None:
    """Crash-safe single-file copy via the sqlite backup API (handles WAL),
    like scripts/benchmark.py::_copy_sidecar. Synthetic sidecars have no
    -derived generation directory yet, so only the database is copied."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="output sidecar path")
    parser.add_argument(
        "--shape",
        choices=("ci", "production"),
        default="production",
        help="shape preset (default production)",
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--scenes", type=int)
    parser.add_argument("--tags", type=int)
    parser.add_argument("--performers", type=int)
    args = parser.parse_args()
    shape = dict(PRODUCTION if args.shape == "production" else CI)
    if args.seed is not None:
        shape["seed"] = args.seed
    if args.scenes is not None:
        shape["n_scenes"] = args.scenes
    if args.tags is not None:
        shape["n_tags"] = args.tags
    if args.performers is not None:
        shape["n_performers"] = args.performers
    counts = build_sidecar(args.path, **shape)
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
