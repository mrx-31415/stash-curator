"""Curation ops: model impact and impact corrections.

curation_impact diffs the two most recent model builds; an impact correction
is a deliberate "this move is wrong" signal on one scene.

Everything is deterministic (ORDER BY, sorted iteration, no RNG, explicit
tie-breaks) so the compiled core mirrors every function; the differential
gates enforce that contract.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

from curator.model.updates import ModelUpdateCoordinator
from curator.storage import transaction
from curator.storage.artifacts import artifact_path, database_path


def submit_impact_correction(
    connection: sqlite3.Connection, scene_id: str, direction: str
) -> dict[str, object]:
    """Record a deliberate "this impact move is wrong" correction for a scene.

    The impact report shows the scenes a build promoted or demoted. When the
    user disagrees with a move they post a correction in the opposite
    direction: 'up' (a demotion was wrong) writes an outcome +1 signal that
    pulls the scene back up on the next build; 'down' (a promotion was wrong)
    writes -1. Only the latest active correction per scene counts — a new
    correction supersedes the previous one, so correcting twice is not
    additive. Directly feeds the scene's own appeal.
    """
    if not scene_id:
        raise ValueError("scene_id is required")
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    if (
        connection.execute("SELECT 1 FROM source_scene WHERE scene_id=?", (scene_id,)).fetchone()
        is None
    ):
        raise ValueError(f"unknown scene: {scene_id}")
    now_ms = time.time_ns() // 1_000_000
    outcome = "1" if direction == "up" else "-1"
    new_id = f"{now_ms}-{uuid4().hex}"
    coordinator = ModelUpdateCoordinator(connection)
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO feedback(
                feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                reversed_by_id, impression_id, payload_json
            ) VALUES (?, ?, 'impact_correction', ?, ?, NULL, NULL, '{}')
            """,
            (new_id, scene_id, outcome, now_ms),
        )
        # Supersede the earlier active correction: the new row is the reversal
        # target, so only the latest correction per scene is live (idempotent).
        connection.execute(
            "UPDATE feedback SET reversed_by_id=? WHERE scene_id=? AND"
            " feedback_type='impact_correction' AND feedback_id != ? AND"
            " reversed_by_id IS NULL",
            (new_id, scene_id, new_id),
        )
        coordinator.request("impact_correction")
    return {"schema_version": 2, "scene_id": scene_id, "direction": direction}


# -- Impact -------------------------------------------------------------------

IMPACT_TOP_SCENES = 5
IMPACT_TOP_ENTITIES = 4
IMPACT_MIN_DELTA = 0.01
IMPACT_MIN_CONTRIBUTION = 0.0005
IMPACT_SCENE_POOL = 20
IMPACT_MAX_CONTRIBUTORS = 6  # per-scene "Because" entities shown (plus direct)
# Feedback types that teach the model's scene labels; used to tie a scene's
# move back to the user's own feedback on scenes carrying the same entities.
IMPACT_FEEDBACK_TYPES = (
    "thumb_up",
    "thumb_down",
    "curation_rating",
    "impact_correction",
)


def _impact_models(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """The two most recent models with artifacts, newest first."""
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT model_id, artifact_basename, published_at_ms, feature_version
            FROM model_version
            WHERE artifact_basename IS NOT NULL
            ORDER BY published_at_ms DESC
            LIMIT 2
            """
        )
    ]


def _impact_artifact(connection: sqlite3.Connection, basename: object) -> Any | None:
    """Resolve an artifact basename to a readable path, or None."""
    try:
        path = artifact_path(database_path(connection), str(basename))
    except Exception:
        return None
    return path if path.is_file() else None


def _readonly(path: Any) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def curation_impact(connection: sqlite3.Connection) -> dict[str, object]:
    """Diff the two most recent model builds: which scenes, performers, and
    tags the newest inputs promoted or demoted.

    The gap between consecutive builds is exactly the user's own feedback, so
    newest-vs-previous is "what my inputs moved".
    """
    models = _impact_models(connection)
    if len(models) < 2:
        return {"available": False, "reason": "need two built models to measure impact"}
    newer, older = models[0], models[1]
    newer_path = _impact_artifact(connection, newer["artifact_basename"])
    older_path = _impact_artifact(connection, older["artifact_basename"])
    feature_row = connection.execute(
        "SELECT artifact_basename FROM feature_build WHERE feature_version=?",
        (newer["feature_version"],),
    ).fetchone()
    feature_path = _impact_artifact(connection, feature_row[0]) if feature_row is not None else None
    if newer_path is None or older_path is None or feature_path is None:
        return {"available": False, "reason": "model artifacts unavailable"}

    def appeals(path: Any) -> tuple[dict[str, float], dict[str, float]]:
        db = _readonly(path)
        try:
            appeal: dict[str, float] = {}
            direct: dict[str, float] = {}
            for row in db.execute(
                "SELECT scene_id, general_appeal, direct_appeal "
                "FROM model_scene_score WHERE model_id=?",
                (newer["model_id"] if path is newer_path else older["model_id"],),
            ):
                appeal[str(row[0])] = float(row[1])
                if row[2] is not None:
                    direct[str(row[0])] = float(row[2])
            return appeal, direct
        finally:
            db.close()

    new_appeal, new_direct = appeals(newer_path)
    old_appeal, old_direct = appeals(older_path)
    scene_deltas = {
        scene_id: new_appeal[scene_id] - old_appeal[scene_id]
        for scene_id in new_appeal
        if scene_id in old_appeal
        and abs(new_appeal[scene_id] - old_appeal[scene_id]) > IMPACT_MIN_DELTA
    }
    # Candidate pools: the final lists keep only feedback-driven movers, so
    # scan a wider band before filtering.
    promoted_pool = sorted(
        (pair for pair in scene_deltas.items() if pair[1] > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )[:IMPACT_SCENE_POOL]
    demoted_pool = sorted(
        (pair for pair in scene_deltas.items() if pair[1] < 0),
        key=lambda kv: (kv[1], kv[0]),
    )[:IMPACT_SCENE_POOL]

    scene_meta: dict[str, dict[str, str | None]] = {}
    chosen = [scene_id for scene_id, _ in promoted_pool + demoted_pool]
    if chosen:
        marks = ",".join("?" * len(chosen))
        for row in connection.execute(
            f"""
            SELECT ss.scene_id, ss.title, ss.scene_date, s.name
            FROM source_scene ss
            LEFT JOIN source_studio s ON s.studio_id = ss.studio_id
            WHERE ss.scene_id IN ({marks})
            """,
            chosen,
        ):
            scene_meta[str(row[0])] = {
                "title": row[1],
                "studio": row[3],
                "date": row[2],
            }

    # Affinity features are versioned: the two models may build on different
    # feature versions, so each model's affinities resolve through its own
    # feature artifact and are keyed by entity id, not feature_id.
    older_feature_row = connection.execute(
        "SELECT artifact_basename FROM feature_build WHERE feature_version=?",
        (older["feature_version"],),
    ).fetchone()
    older_feature_path = (
        _impact_artifact(connection, older_feature_row[0])
        if older_feature_row is not None
        else None
    )

    def entity_effective(
        path: Any, feature_path: Any, model_id: str
    ) -> tuple[dict[str, float], dict[str, float]]:
        feature_db = _readonly(feature_path)
        try:
            names = {
                str(row[0]): str(row[1])
                for row in feature_db.execute("SELECT feature_id, name FROM feature_definition")
            }
        finally:
            feature_db.close()
        db = _readonly(path)
        try:
            performers: dict[str, float] = {}
            tags: dict[str, float] = {}
            for row in db.execute(
                "SELECT feature_id, affinity, confidence FROM feature_affinity WHERE model_id=?",
                (model_id,),
            ):
                name = names.get(str(row[0]))
                if name is None:
                    continue
                effective = float(row[1]) * float(row[2])
                if name.startswith("performer:"):
                    performers[name[len("performer:") :]] = effective
                elif name.startswith("tag:"):
                    tags[name[len("tag:") :]] = effective
            return performers, tags
        finally:
            db.close()

    newer_performers, newer_tags = entity_effective(
        newer_path, feature_path, str(newer["model_id"])
    )
    if older_feature_path is not None:
        older_performers, older_tags = entity_effective(
            older_path, older_feature_path, str(older["model_id"])
        )
    else:
        older_performers, older_tags = {}, {}

    def deltas_by_id(newer: dict[str, float], older: dict[str, float]) -> dict[str, float]:
        # Entities have no noise floor: the top movers are informative even at
        # small magnitudes, and the UI labels weak signal explicitly.
        return {
            entity_id: value - older[entity_id]
            for entity_id, value in newer.items()
            if entity_id in older and value - older[entity_id] != 0.0
        }

    performer_deltas = deltas_by_id(newer_performers, older_performers)
    tag_deltas = deltas_by_id(newer_tags, older_tags)

    def ranked(
        deltas: dict[str, float], top: int
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        up = sorted(
            (pair for pair in deltas.items() if pair[1] > 0),
            key=lambda kv: (-kv[1], kv[0]),
        )[:top]
        down = sorted(
            (pair for pair in deltas.items() if pair[1] < 0),
            key=lambda kv: (kv[1], kv[0]),
        )[:top]
        return up, down

    performers_up, performers_down = ranked(performer_deltas, IMPACT_TOP_ENTITIES)
    tags_up, tags_down = ranked(tag_deltas, IMPACT_TOP_ENTITIES)

    performer_names = {
        str(row["performer_id"]): str(row["name"])
        for row in connection.execute("SELECT performer_id, name FROM source_performer")
    }
    tag_names = {
        str(row["tag_id"]): str(row["name"])
        for row in connection.execute("SELECT tag_id, name FROM source_tag")
    }

    # Scene "why": the entities whose effective affinity moved and that the
    # scene carries under the newest feature version. Contribution is the
    # entity's effective-affinity delta (presence is 0/1).
    contribution_deltas: dict[str, float] = {
        f"performer:{entity_id}": delta
        for entity_id, delta in performer_deltas.items()
        if abs(delta) > IMPACT_MIN_CONTRIBUTION
    }
    contribution_deltas.update(
        {
            f"tag:{entity_id}": delta
            for entity_id, delta in tag_deltas.items()
            if abs(delta) > IMPACT_MIN_CONTRIBUTION
        }
    )
    feature_db = _readonly(feature_path)
    try:
        scene_feature_names: dict[str, list[str]] = {}
        for scene_id, _delta in promoted_pool + demoted_pool:
            scene_feature_names[scene_id] = [
                str(row[0])
                for row in feature_db.execute(
                    """SELECT fd.name
                       FROM entity_feature ef
                       JOIN feature_definition fd USING(feature_id)
                       WHERE ef.feature_version=? AND ef.entity_id=?""",
                    (newer["feature_version"], scene_id),
                )
            ]
    finally:
        feature_db.close()

    def scene_contributors(scene_id: str) -> list[dict[str, object]]:
        direct_delta = new_direct.get(scene_id, 0.0) - old_direct.get(scene_id, 0.0)
        out: list[dict[str, object]] = []
        if abs(direct_delta) > IMPACT_MIN_CONTRIBUTION:
            out.append(
                {
                    "kind": "direct",
                    "id": scene_id,
                    "name": "Your direct feedback",
                    "delta": direct_delta,
                }
            )
        candidates = [
            (name, contribution_deltas[name])
            for name in scene_feature_names.get(scene_id, [])
            if name in contribution_deltas
        ]
        candidates.sort(key=lambda pair: (-abs(pair[1]), pair[0]))
        # via_feedback counts the user's own model-teaching feedback on scenes
        # that carry the same entity, so the "why" shows whether a move is
        # tied to what was rated/picked (an entity with 0 came only from a
        # pair's differing feature or a tag preference, not a rated scene).
        feedback_placeholders = ", ".join("?" * len(IMPACT_FEEDBACK_TYPES))

        def via_feedback(kind: str, entity_id: str) -> int:
            table = "scene_tag" if kind == "tag" else "scene_performer"
            column = "tag_id" if kind == "tag" else "performer_id"
            row = connection.execute(
                f"""SELECT COUNT(DISTINCT f.scene_id)
                    FROM {table} t
                    JOIN feedback f ON f.scene_id = t.scene_id
                    WHERE t.{column} = ?
                      AND f.reversed_by_id IS NULL
                      AND f.feedback_type IN ({feedback_placeholders})""",
                (entity_id, *IMPACT_FEEDBACK_TYPES),
            ).fetchone()
            return int(row[0])

        for name, delta in candidates[: IMPACT_MAX_CONTRIBUTORS - len(out)]:
            if name.startswith("performer:"):
                kind, entity_id = "performer", name[len("performer:") :]
                label = performer_names.get(entity_id)
            else:
                kind, entity_id = "tag", name[len("tag:") :]
                label = tag_names.get(entity_id)
            out.append(
                {
                    "kind": kind,
                    "id": entity_id,
                    "name": label or entity_id,
                    "delta": delta,
                    "via_feedback": via_feedback(kind, entity_id),
                }
            )
        return out

    def scene_breakdown(scene_id: str, delta: float) -> dict[str, float]:
        """Approximate how much of a scene's move came from each source.

        The model attributes a scene's feedback to every entity it carries, so a
        single rating may nudge many tags. This splits the move into the user's
        own feedback on the scene, the generalization through its tags, through
        its performers, and everything else (content similarity, studio,
        structure — i.e. the scene's theme/neighborhood). The residual absorbs
        the soft-bound nonlinearity, so 'content_similarity' is the catch-all.
        """
        direct_delta = new_direct.get(scene_id, 0.0) - old_direct.get(scene_id, 0.0)
        feature_names = scene_feature_names.get(scene_id, [])
        tag_sum = sum(
            contribution_deltas[name]
            for name in feature_names
            if name.startswith("tag:") and name in contribution_deltas
        )
        performer_sum = sum(
            contribution_deltas[name]
            for name in feature_names
            if name.startswith("performer:") and name in contribution_deltas
        )
        return {
            "your_feedback": direct_delta,
            "tag_preference": tag_sum,
            "performer_preference": performer_sum,
            "content_similarity": delta - direct_delta - tag_sum - performer_sum,
        }

    def scene_entries(pairs: list[tuple[str, float]]) -> list[dict[str, object]]:
        # Only feedback-driven movers are reported: a scene that moved purely
        # with the library re-sync (no direct feedback, no affinity move on
        # entities it carries) carries no signal about the user's taste.
        entries: list[dict[str, object]] = []
        for scene_id, delta in pairs:
            contributors = scene_contributors(scene_id)
            if not contributors:
                continue
            entries.append(
                {
                    "scene_id": scene_id,
                    "title": scene_meta.get(scene_id, {}).get("title"),
                    "studio": scene_meta.get(scene_id, {}).get("studio"),
                    "date": scene_meta.get(scene_id, {}).get("date"),
                    "delta": delta,
                    "contributors": contributors,
                    "breakdown": scene_breakdown(scene_id, delta),
                }
            )
        return entries

    def performer_entries(pairs: list[tuple[str, float]]) -> list[dict[str, object]]:
        return [
            {
                "performer_id": performer_id,
                "name": performer_names.get(performer_id),
                "delta": delta,
            }
            for performer_id, delta in pairs
        ]

    def tag_entries(pairs: list[tuple[str, float]]) -> list[dict[str, object]]:
        return [
            {"tag_id": tag_id, "name": tag_names.get(tag_id), "delta": delta}
            for tag_id, delta in pairs
        ]

    promoted = scene_entries(promoted_pool)[:IMPACT_TOP_SCENES]
    demoted = scene_entries(demoted_pool)[:IMPACT_TOP_SCENES]

    return {
        "available": True,
        "newer_model_id": newer["model_id"],
        "older_model_id": older["model_id"],
        "published_at_ms": int(newer["published_at_ms"]),
        "scenes": {"promoted": promoted, "demoted": demoted},
        "performers": {
            "promoted": performer_entries(performers_up),
            "demoted": performer_entries(performers_down),
        },
        "tags": {"promoted": tag_entries(tags_up), "demoted": tag_entries(tags_down)},
    }
