"""Curation batches: hypothesis tests and exploration sampling.

Hypothesis mode draws a stratified 2x2 sample around a (base tag x context
tag) pair with calibration anchors; explore mode greedily maximizes NEW
interactive-tag coverage (rarity-weighted, studio-diversity penalty). Ratings
are stored as ``feedback_type='curation_rating'`` rows carrying the batch and
cell in payload_json; the verdict is computed from a batch's own ratings
only, never merged with other labels.

All selection is deterministic (ORDER BY everywhere, no RNG, explicit
tie-breaks, half-up rounding only) so the compiled core mirrors every
function byte-identically; the differential gates enforce that contract.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from curator.config import DEFAULT_CONFIG, CuratorConfig
from curator.model.builder import PreferenceModelBuilder
from curator.model.updates import ModelUpdateCoordinator
from curator.storage import transaction
from curator.storage.artifacts import artifact_path, database_path

# StashDB taxonomy categories that describe physical appearance: they cannot
# participate in interesting tag interactions, so they are excluded from the
# hypothesis candidate space and from exploration coverage value.
EXCLUDED_CATEGORIES = frozenset(
    {
        "Hair Color",
        "Hair Style",
        "Body Type",
        "Breasts",
        "Face",
        "Skin Tone",
        "Piercings",
        "Ass",
        "Genitals",
        "Height",
        "Tattoos",
        "Race",
    }
)

MIN_BUDGET, MAX_BUDGET = 1, 40
DEFAULT_BUDGET = 20
RATING_MIN, RATING_MAX = 0, 10
REASON_TYPES = frozenset(
    {"metadata_wrong", "not_now", "contradicts_hypothesis", "performer_driven"}
)
CONFIRM_DELTA = 0.15
CONFIRM_MIN_N = 10
ANCHOR_BAND = 200  # scenes each side of the appeal median for calibration anchors
MAX_ITEM_TAGS = 8
DEFAULT_MIN_SUPPORT = 20
CONTRAST_MIN_LABELED = 4  # labeled base scenes needed to rank by outcome contrast
EXPLORE_ANCHORS = 3
HYPOTHESIS_ANCHOR_FRACTION = 0.15
HYPOTHESIS_CONTROL_FRACTION = 0.15
HYPOTHESIS_CELLS = ("L&T", "L&!T", "!L&T", "!L&!T", "anchor")
# Context candidates whose library-wide tag rate is at or above this share are
# ubiquitous (Blowjob, hair colors...): they co-occur with everything and
# cannot discriminate any relationship.
CANDIDATE_MAX_LIBRARY_RATE = 0.30
# Contrast is discounted by label evidence: a candidate's contrast only counts
# fully once min(with, without) labeled scenes reach this count. Prevents a
# handful of near-identical labeled scenes from manufacturing phantom
# relationships (e.g. +0.76 for every co-tag of one rated base tag).
CONTRAST_EVIDENCE_SCALE = 8.0
# Hypothesis suggestions skip weak-interaction categories: clothing, mood,
# location, and technical tags correlate with liked scenes without being
# meaningful relationships (lesbian + Lingerie), burying real hypotheses like
# lesbian + Threesome. Acts/Group Makeup/Relations/Finishers stay.
SUGGESTION_EXCLUDED_CATEGORIES = frozenset(
    {
        "Clothing",
        "Moods",
        "Locations",
        "Shot Type",
        "Surfaces",
        "Misc",
        "Accessories",
    }
)


def _half_up(value: float) -> int:
    return int(value + 0.5)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class CurationContext:
    """Read-only snapshot of everything a selection needs, from one DB."""

    labels: frozenset[str]  # scenes with any label signal (views, thumbs, ratings)
    scene_ids: frozenset[str]  # every source_scene id
    scene_tags: dict[str, frozenset[str]]
    scene_performers: dict[str, frozenset[str]]
    performer_counts: dict[str, int]
    performer_name: dict[str, str]
    studio: dict[str, str]
    scene_title: dict[str, str]
    scene_date: dict[str, str]
    scene_details: dict[str, str]
    tag_cat: dict[str, str]  # local tag id -> StashDB category name ("" if unmatched)
    tag_name: dict[str, str]
    counts: dict[str, int]  # tag id -> library scene count
    appeal: dict[str, float]  # scene id -> current model general_appeal
    blocked_scenes: frozenset[str]
    metadata_wrong: frozenset[str]
    interactive: frozenset[str]  # tags whose category is not excluded

    def rarity(self, tag_id: str) -> float:
        return 1.0 / math.sqrt(max(1, self.counts.get(tag_id, 0)))

    def is_interactive(self, tag_id: str) -> bool:
        return tag_id in self.interactive


def curation_context(
    connection: sqlite3.Connection, config: CuratorConfig = DEFAULT_CONFIG
) -> CurationContext:
    labels = frozenset(PreferenceModelBuilder(connection, config)._scene_labels().keys())
    scene_ids = frozenset(
        str(row["scene_id"])
        for row in connection.execute("SELECT scene_id FROM source_scene ORDER BY scene_id")
    )
    scene_tags: dict[str, frozenset[str]] = defaultdict(frozenset)
    counts: Counter[str] = Counter()
    for row in connection.execute(
        "SELECT scene_id, tag_id FROM scene_tag ORDER BY scene_id, tag_id"
    ):
        scene_id = str(row["scene_id"])
        tag_id = str(row["tag_id"])
        counts[tag_id] += 1
        scene_tags[scene_id] = scene_tags[scene_id] | {tag_id}
    scene_performers: dict[str, frozenset[str]] = defaultdict(frozenset)
    performer_counts: Counter[str] = Counter()
    for row in connection.execute(
        "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"
    ):
        scene_id = str(row["scene_id"])
        performer_id = str(row["performer_id"])
        performer_counts[performer_id] += 1
        scene_performers[scene_id] = scene_performers[scene_id] | {performer_id}
    performer_name: dict[str, str] = {}
    for row in connection.execute(
        "SELECT performer_id, name FROM source_performer ORDER BY performer_id"
    ):
        performer_name[str(row["performer_id"])] = str(row["name"] or row["performer_id"])
    studio: dict[str, str] = {}
    scene_title: dict[str, str] = {}
    scene_date: dict[str, str] = {}
    scene_details: dict[str, str] = {}
    for row in connection.execute(
        """SELECT ss.scene_id, ss.title, ss.scene_date, ss.details, s.name
           FROM source_scene ss
           LEFT JOIN source_studio s ON s.studio_id=ss.studio_id
           ORDER BY ss.scene_id"""
    ):
        scene_id = str(row["scene_id"])
        if row["name"] is not None:
            studio[scene_id] = str(row["name"])
        if row["title"] is not None:
            scene_title[scene_id] = str(row["title"])
        if row["scene_date"] is not None:
            scene_date[scene_id] = str(row["scene_date"])
        if row["details"] is not None:
            scene_details[scene_id] = str(row["details"])
    tag_name: dict[str, str] = {}
    for row in connection.execute("SELECT tag_id, name FROM source_tag ORDER BY tag_id"):
        tag_name[str(row["tag_id"])] = str(row["name"] or row["tag_id"])
    tag_cat: dict[str, str] = {}
    snapshot = connection.execute(
        "SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'"
    ).fetchone()
    if snapshot is not None:
        for row in connection.execute(
            """SELECT ttm.local_tag_id, c.name AS category
               FROM tag_taxonomy_match ttm
               JOIN taxonomy_category c
                 ON c.category_id=ttm.external_category_id
                AND c.snapshot_id=ttm.snapshot_id
               WHERE ttm.snapshot_id=?
               ORDER BY ttm.local_tag_id""",
            (str(snapshot[0]),),
        ):
            tag_cat[str(row["local_tag_id"])] = str(row["category"])
    blocked_tags = [
        str(row["tag_id"])
        for row in connection.execute(
            "SELECT tag_id FROM direct_tag_preference WHERE blocked=1 ORDER BY tag_id"
        )
    ]
    blocked_scenes: frozenset[str] = frozenset()
    if blocked_tags:
        placeholders = ",".join("?" * len(blocked_tags))
        blocked_scenes = frozenset(
            str(row["scene_id"])
            for row in connection.execute(
                f"SELECT DISTINCT scene_id FROM scene_tag WHERE tag_id IN ({placeholders})",
                blocked_tags,
            )
        )
    metadata_wrong = frozenset(
        str(row["scene_id"])
        for row in connection.execute(
            "SELECT DISTINCT scene_id FROM feedback"
            " WHERE feedback_type='metadata_wrong' AND reversed_by_id IS NULL"
        )
    )
    appeal: dict[str, float] = {}
    model = connection.execute(
        "SELECT model_id FROM model_version WHERE status='published'"
        " ORDER BY published_at_ms DESC LIMIT 1"
    ).fetchone()
    if model is not None:
        appeal = {
            str(row["scene_id"]): float(row["general_appeal"])
            for row in connection.execute(
                "SELECT scene_id, general_appeal FROM model_scene_score WHERE model_id=?",
                (str(model["model_id"]),),
            )
        }
    interactive = frozenset(
        tag_id for tag_id, category in tag_cat.items() if category not in EXCLUDED_CATEGORIES
    )
    return CurationContext(
        labels,
        scene_ids,
        dict(scene_tags),
        dict(scene_performers),
        dict(performer_counts),
        performer_name,
        studio,
        scene_title,
        scene_date,
        scene_details,
        tag_cat,
        tag_name,
        dict(counts),
        appeal,
        blocked_scenes,
        metadata_wrong,
        interactive,
    )


def _unlabeled_pool(context: CurationContext, scenes: set[str] | frozenset[str]) -> list[str]:
    return sorted(
        sid
        for sid in scenes
        if sid not in context.labels
        and sid not in context.blocked_scenes
        and sid not in context.metadata_wrong
    )


def _round_robin(pool: list[str], quota: int, studio: dict[str, str]) -> list[str]:
    """One scene per studio before repeats; deterministic order."""
    by_studio: dict[str, deque[str]] = defaultdict(deque)
    for sid in pool:
        by_studio[studio.get(sid, "?")].append(sid)
    chosen: list[str] = []
    for name in sorted(by_studio):
        if len(chosen) >= quota:
            break
        chosen.append(by_studio[name].popleft())
    while len(chosen) < quota:
        progressed = False
        for name in sorted(by_studio):
            if len(chosen) >= quota:
                break
            if by_studio[name]:
                chosen.append(by_studio[name].popleft())
                progressed = True
        if not progressed:
            break
    return chosen


def _anchor_band(pool: list[str], context: CurationContext) -> list[str]:
    """Appeal middle band: calibration anchors should be average scenes."""
    ordered = sorted(pool, key=lambda sid: (context.appeal.get(sid, 0.0), sid))
    mid = len(ordered) // 2
    return ordered[max(0, mid - ANCHOR_BAND) : mid + ANCHOR_BAND]


def _item_tags(context: CurationContext, scene_id: str) -> list[dict[str, str | None]]:
    tags = sorted(
        (t for t in context.scene_tags.get(scene_id, ()) if context.is_interactive(t)),
        key=lambda t: (context.tag_name.get(t, t), t),
    )[:MAX_ITEM_TAGS]
    return [
        {
            "tag_id": t,
            "name": context.tag_name.get(t, t),
            "category": context.tag_cat.get(t, "") or None,
        }
        for t in tags
    ]


def _group_clean_scenes(context: CurationContext, scenes: list[str], tag: str) -> list[str]:
    """Scenes missing `tag` that can serve as clean negative examples.

    For group tags (taxonomy category Group Makeup), a scene with 3+ performers
    is likely the untagged group activity (threesomes often lack the tag), so
    it cannot vouch for "without tag" — exclude it."""
    if context.tag_cat.get(tag) != "Group Makeup":
        return scenes
    return [sid for sid in scenes if len(context.scene_performers.get(sid, ())) < 3]


def select_hypothesis(
    context: CurationContext, base_tag: str, context_tag: str, budget: int
) -> tuple[list[tuple[str, str, bool]], dict[str, int]]:
    base = {sid for sid, tags in context.scene_tags.items() if base_tag in tags}
    ctx = {sid for sid, tags in context.scene_tags.items() if context_tag in tags}
    all_scenes = context.scene_ids
    pools = {
        "L&T": _unlabeled_pool(context, base & ctx),
        "L&!T": _unlabeled_pool(
            context, set(_group_clean_scenes(context, list(base - ctx), context_tag))
        ),
        "!L&T": _unlabeled_pool(context, ctx - base),
        "!L&!T": _unlabeled_pool(context, all_scenes - base - ctx),
    }
    anchors = max(1, _half_up(budget * HYPOTHESIS_ANCHOR_FRACTION))
    controls = min(max(1, _half_up(budget * HYPOTHESIS_CONTROL_FRACTION)), budget - anchors)
    contrast = budget - anchors - controls
    contrast_l_t = contrast // 2 + contrast % 2
    contrast_l_nt = contrast // 2
    items: list[tuple[str, str, bool]] = []
    for cell, quota in (("L&T", contrast_l_t), ("L&!T", contrast_l_nt), ("!L&T", controls)):
        items.extend((sid, cell, False) for sid in _round_robin(pools[cell], quota, context.studio))
    anchor_pool = _anchor_band(pools["!L&!T"], context)
    items.extend(
        (sid, "anchor", True) for sid in _round_robin(anchor_pool, anchors, context.studio)
    )
    items.sort(key=lambda item: (item[1], item[0]))
    return items, {cell: len(pool) for cell, pool in pools.items()}


def select_explore(
    context: CurationContext, budget: int
) -> tuple[list[tuple[str, str, bool]], dict[str, int]]:
    pool = _unlabeled_pool(context, context.scene_ids)
    anchors = min(EXPLORE_ANCHORS, max(0, budget // 2))
    explore_budget = budget - anchors
    tag_scenes: dict[str, list[str]] = defaultdict(list)
    for sid in pool:
        for t in context.scene_tags.get(sid, ()):
            if context.is_interactive(t):
                tag_scenes[t].append(sid)
    value = {
        sid: sum(
            context.rarity(t) for t in context.scene_tags.get(sid, ()) if context.is_interactive(t)
        )
        for sid in pool
    }
    covered: set[str] = set()
    chosen_set: set[str] = set()
    chosen_studios: set[str] = set()
    chosen: list[str] = []
    while len(chosen) < explore_budget:
        best, best_value = None, -1.0
        for sid in sorted(pool):
            if sid in chosen_set:
                continue
            v = value[sid]
            if context.studio.get(sid, "?") in chosen_studios:
                v *= 0.5
            if v > best_value:
                best, best_value = sid, v
        if best is None or best_value <= 0:
            break
        chosen.append(best)
        chosen_set.add(best)
        chosen_studios.add(context.studio.get(best, "?"))
        for t in context.scene_tags.get(best, ()):
            if context.is_interactive(t) and t not in covered:
                covered.add(t)
                for other in tag_scenes[t]:
                    if other in value:
                        value[other] -= context.rarity(t)
    anchor_pool = _anchor_band([sid for sid in pool if sid not in chosen_set], context)
    items = [(sid, "explore", False) for sid in chosen]
    items.extend(
        (sid, "anchor", True) for sid in _round_robin(anchor_pool, anchors, context.studio)
    )
    items.sort(key=lambda item: (item[1], item[0]))
    return items, {"candidates": len(pool), "interactive_tags": len(context.interactive)}


def create_batch(
    connection: sqlite3.Connection,
    mode: str,
    base_tag_id: str | None,
    context_tag_id: str | None,
    budget: int,
    config: CuratorConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    if mode not in ("hypothesis", "explore"):
        raise ValueError("mode must be 'hypothesis' or 'explore'")
    if not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise ValueError(f"budget must be from {MIN_BUDGET} to {MAX_BUDGET}")
    if mode == "hypothesis":
        if not base_tag_id or not context_tag_id:
            raise ValueError("hypothesis mode requires base_tag_id and context_tag_id")
        if base_tag_id == context_tag_id:
            raise ValueError("base_tag_id and context_tag_id must differ")
    for tag_id in (base_tag_id, context_tag_id):
        if (
            tag_id is not None
            and connection.execute("SELECT 1 FROM source_tag WHERE tag_id=?", (tag_id,)).fetchone()
            is None
        ):
            raise ValueError(f"unknown tag: {tag_id}")
    context = curation_context(connection, config)
    if mode == "hypothesis":
        assert base_tag_id is not None and context_tag_id is not None
        items, pool = select_hypothesis(context, base_tag_id, context_tag_id, budget)
        anchors = sum(1 for _, _, anchor in items if anchor)
        policy = (
            f"stratified 2x2, studio round-robin, unlabeled only, {anchors} calibration anchors"
        )
    else:
        items, pool = select_explore(context, budget)
        policy = "max-coverage interactive tags, rarity-weighted, studio penalty, unlabeled only"
    batch_id = str(uuid4())
    now_ms = time.time_ns() // 1_000_000
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO curation_batch(
                batch_id, mode, base_tag_id, context_tag_id, budget, status,
                created_at_ms, payload_json
            ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                batch_id,
                mode,
                base_tag_id,
                context_tag_id,
                budget,
                now_ms,
                json.dumps({"policy": policy, "pool": pool}, sort_keys=True, separators=(",", ":")),
            ),
        )
        connection.executemany(
            """
            INSERT INTO curation_batch_item(batch_id, scene_id, cell, anchor)
            VALUES (?, ?, ?, ?)
            """,
            [(batch_id, sid, cell, 1 if anchor else 0) for sid, cell, anchor in items],
        )
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "mode": mode,
        "base_tag_id": base_tag_id,
        "context_tag_id": context_tag_id,
        "budget": budget,
        "items": [
            {
                "scene_id": sid,
                "cell": cell,
                "anchor": anchor,
                "title": context.scene_title.get(sid),
                "studio": context.studio.get(sid),
                "date": context.scene_date.get(sid),
                "details": context.scene_details.get(sid),
                "tags": _item_tags(context, sid),
            }
            for sid, cell, anchor in items
        ],
        "pool": pool,
        "policy": policy,
    }


def _batch_items(connection: sqlite3.Connection, batch_id: str) -> dict[str, tuple[str, bool]]:
    return {
        str(row["scene_id"]): (str(row["cell"]), bool(row["rated"]))
        for row in connection.execute(
            "SELECT scene_id, cell, rated FROM curation_batch_item WHERE batch_id=?",
            (batch_id,),
        )
    }


def _insert_reason_feedback(
    connection: sqlite3.Connection, now_ms: int, scene_id: str, reason: str
) -> None:
    connection.execute(
        """
        INSERT INTO feedback(
            feedback_id, scene_id, feedback_type, value, occurred_at_ms,
            reversed_by_id, impression_id, payload_json
        ) VALUES (?, ?, ?, NULL, ?, NULL, NULL, '{}')
        """,
        (f"{now_ms}-{uuid4().hex}", scene_id, reason, now_ms),
    )


def submit_ratings(
    connection: sqlite3.Connection, batch_id: str, ratings: list[dict[str, Any]]
) -> dict[str, object]:
    if not batch_id:
        raise ValueError("batch_id is required")
    batch = connection.execute(
        "SELECT status FROM curation_batch WHERE batch_id=?", (batch_id,)
    ).fetchone()
    if batch is None:
        raise ValueError(f"unknown batch: {batch_id}")
    if str(batch["status"]) != "open":
        raise ValueError(f"batch is not open: {batch['status']}")
    items = _batch_items(connection, batch_id)
    if not items:
        raise ValueError(f"unknown batch: {batch_id}")
    seen: set[str] = set()
    normalized: list[tuple[str, int, str | None]] = []
    for entry in ratings:
        if not isinstance(entry, dict):
            raise ValueError("each rating must be an object with scene_id, value, and reason")
        scene_id = str(entry.get("scene_id") or "")
        if scene_id not in items:
            raise ValueError(f"scene is not in this batch: {scene_id}")
        if scene_id in seen:
            raise ValueError(f"duplicate rating for scene: {scene_id}")
        if items[scene_id][1]:
            raise ValueError(f"scene already rated in this batch: {scene_id}")
        raw_value = entry.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError("rating value must be an integer")
        if not RATING_MIN <= raw_value <= RATING_MAX:
            raise ValueError(f"rating value must be from {RATING_MIN} to {RATING_MAX}")
        reason = entry.get("reason")
        if reason is not None and reason not in REASON_TYPES:
            raise ValueError(f"unknown rating reason: {reason}")
        seen.add(scene_id)
        normalized.append((scene_id, raw_value, str(reason) if reason else None))
    if not normalized:
        raise ValueError("ratings must not be empty")
    now_ms = time.time_ns() // 1_000_000
    with transaction(connection):
        for scene_id, value, reason in normalized:
            cell = items[scene_id][0]
            payload = {"batch_id": batch_id, "cell": cell}
            connection.execute(
                """
                INSERT INTO feedback(
                    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                    reversed_by_id, impression_id, payload_json
                ) VALUES (?, ?, 'curation_rating', ?, ?, NULL, NULL, ?)
                """,
                (
                    f"{now_ms}-{uuid4().hex}",
                    scene_id,
                    str(value),
                    now_ms,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
            if reason is not None:
                _insert_reason_feedback(connection, now_ms, scene_id, reason)
            connection.execute(
                "UPDATE curation_batch_item SET rated=1 WHERE batch_id=? AND scene_id=?",
                (batch_id, scene_id),
            )
        remaining = int(
            connection.execute(
                "SELECT count(*) FROM curation_batch_item WHERE batch_id=? AND rated=0",
                (batch_id,),
            ).fetchone()[0]
        )
        status = "open" if remaining else "rated"
        if status == "rated":
            connection.execute(
                "UPDATE curation_batch SET status='rated' WHERE batch_id=?", (batch_id,)
            )
    return {
        "schema_version": 1,
        "accepted": len(normalized),
        "batch_status": status,
    }


def _batch_ratings(connection: sqlite3.Connection, batch_id: str) -> dict[str, float]:
    """This batch's own curation ratings: scene_id -> outcome.

    Ratings marked with a reason are excluded from the tag-level verdict:
    metadata_wrong / contradicts_hypothesis scenes are not valid instances of
    the cell they were sorted into, and performer_driven ratings would spill
    performer preference into every tag's mean. All of them still count as
    model labels (the model wants performer outcomes for performer affinity).
    """
    excluded = {
        str(row["scene_id"])
        for row in connection.execute(
            """SELECT DISTINCT scene_id FROM feedback
               WHERE feedback_type IN
                     ('metadata_wrong', 'contradicts_hypothesis', 'performer_driven')
                 AND reversed_by_id IS NULL"""
        )
    }
    outcomes: dict[str, float] = {}
    for row in connection.execute(
        """SELECT scene_id, value, payload_json FROM feedback
           WHERE feedback_type='curation_rating' AND reversed_by_id IS NULL"""
    ):
        payload = json.loads(str(row["payload_json"]) or "{}")
        if payload.get("batch_id") != batch_id:
            continue
        if str(row["scene_id"]) in excluded:
            continue
        try:
            rating = int(row["value"])
        except (TypeError, ValueError):
            continue
        if not RATING_MIN <= rating <= RATING_MAX:
            continue
        outcomes[str(row["scene_id"])] = (rating - 5) / 5
    return outcomes


def _cell_stats(
    outcomes: dict[str, float], items: dict[str, tuple[str, bool]]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cell in HYPOTHESIS_CELLS:
        values = [outcomes[sid] for sid, (c, _) in items.items() if c == cell and sid in outcomes]
        rows.append(
            {
                "cell": cell,
                "n": len(values),
                "mean_outcome": _mean(values) if values else None,
            }
        )
    return rows


def verdict(connection: sqlite3.Connection, batch_id: str) -> dict[str, object]:
    if not batch_id:
        raise ValueError("batch_id is required")
    batch = connection.execute(
        "SELECT mode, base_tag_id, context_tag_id FROM curation_batch WHERE batch_id=?",
        (batch_id,),
    ).fetchone()
    if batch is None:
        raise ValueError(f"unknown batch: {batch_id}")
    mode = str(batch["mode"])
    items = _batch_items(connection, batch_id)
    outcomes = _batch_ratings(connection, batch_id)
    if mode == "hypothesis":
        cells = _cell_stats(outcomes, items)
        by_cell = {str(c["cell"]): c for c in cells}
        contrast: dict[str, object] = {}
        l_t, l_nt = by_cell["L&T"], by_cell["L&!T"]
        if l_t["n"] and l_nt["n"]:
            mean_lt = cast(float, l_t["mean_outcome"])
            mean_lnt = cast(float, l_nt["mean_outcome"])
            delta = mean_lt - mean_lnt
            n_total = int(cast(int, l_t["n"])) + int(cast(int, l_nt["n"]))
            contrast = {
                "delta": delta,
                "n_total": n_total,
                "confirmed": abs(delta) >= CONFIRM_DELTA and n_total >= CONFIRM_MIN_N,
            }
        suggested: dict[str, object] | None = None
        if l_t["n"]:
            mean_lt = cast(float, l_t["mean_outcome"])
            value = max(-1.0, min(1.0, _half_up(mean_lt * 2) / 2))
            suggested = {
                "base_tag_id": str(batch["base_tag_id"] or ""),
                "context_tag_id": str(batch["context_tag_id"] or ""),
                "value": value,
            }
        return {
            "schema_version": 1,
            "batch_id": batch_id,
            "mode": mode,
            "cells": cells,
            "contrast": contrast,
            "suggested_rule": suggested,
        }
    # explore mode: top/bottom tags by mean outcome across the batch's ratings.
    rated_scenes = set(outcomes)
    tag_rows: dict[str, list[float]] = defaultdict(list)
    if rated_scenes:
        placeholders = ",".join("?" * len(rated_scenes))
        for row in connection.execute(
            f"""SELECT scene_id, tag_id FROM scene_tag
                WHERE scene_id IN ({placeholders}) ORDER BY scene_id, tag_id""",
            tuple(rated_scenes),
        ):
            tag_rows[str(row["tag_id"])].append(outcomes[str(row["scene_id"])])
    tag_names: dict[str, str] = {}
    tag_cats: dict[str, str] = {}
    context = curation_context(connection)
    for tag_id in tag_rows:
        tag_names[tag_id] = context.tag_name.get(tag_id, tag_id)
        tag_cats[tag_id] = context.tag_cat.get(tag_id, "") or ""
    entries = [
        {
            "tag_id": tag_id,
            "name": tag_names[tag_id],
            "category": tag_cats[tag_id] or None,
            "n": len(values),
            "mean_outcome": _mean(values),
        }
        for tag_id, values in tag_rows.items()
        if len(values) >= 2
    ]
    entries.sort(key=lambda item: (-cast(float, item["mean_outcome"]), str(item["tag_id"])))
    values = list(outcomes.values())
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "mode": mode,
        "summary": {"n": len(values), "mean_outcome": _mean(values) if values else None},
        "top_tags": entries[:10],
        "bottom_tags": entries[-10:][::-1],
    }


def tag_context_candidates(
    connection: sqlite3.Connection,
    tag_id: str,
    min_support: int = DEFAULT_MIN_SUPPORT,
    config: CuratorConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    if not tag_id:
        raise ValueError("tag_id is required")
    if connection.execute("SELECT 1 FROM source_tag WHERE tag_id=?", (tag_id,)).fetchone() is None:
        raise ValueError(f"unknown tag: {tag_id}")
    if min_support < 1:
        raise ValueError("min_support must be at least 1")
    context = curation_context(connection, config)
    labels = PreferenceModelBuilder(connection, config)._scene_labels()
    base_scenes = {sid for sid, tags in context.scene_tags.items() if tag_id in tags}
    labeled_base = {sid: labels[sid].outcome for sid in base_scenes if sid in labels}
    cooc: Counter[str] = Counter()
    for sid in base_scenes:
        for t in context.scene_tags.get(sid, ()):
            if t != tag_id and context.is_interactive(t):
                cooc[t] += 1
    rows: list[dict[str, object]] = []
    total_scenes = max(1, len(context.scene_ids))
    for t, n in cooc.items():
        if n < min_support:
            continue
        if context.counts.get(t, 0) / total_scenes >= CANDIDATE_MAX_LIBRARY_RATE:
            continue  # ubiquitous tags cannot discriminate any relationship
        if context.tag_name.get(t, t).startswith("["):
            continue  # sync-artifact tags ([Timestamp: Synced]...) are junk
        if context.tag_cat.get(t, "") in SUGGESTION_EXCLUDED_CATEGORIES:
            continue  # weak-interaction categories are not hypotheses
        with_t = [labeled_base[sid] for sid in labeled_base if t in context.scene_tags.get(sid, ())]
        without_t = [
            labeled_base[sid]
            for sid in _group_clean_scenes(
                context,
                [sid for sid in labeled_base if t not in context.scene_tags.get(sid, ())],
                t,
            )
        ]
        contrast: float | None = None
        if len(labeled_base) >= CONTRAST_MIN_LABELED and with_t and without_t:
            raw = _mean(with_t) - _mean(without_t)
            evidence = min(len(with_t), len(without_t))
            contrast = raw * min(1.0, evidence / CONTRAST_EVIDENCE_SCALE)
        rows.append(
            {
                "tag_id": t,
                "name": context.tag_name.get(t, t),
                "category": context.tag_cat.get(t, "") or None,
                "cooccurrence": n,
                "rate": n / max(1, len(base_scenes)),
                "labeled_n": len(with_t),
                "contrast": contrast,
            }
        )
    rows.sort(
        key=lambda item: (
            # Measured POSITIVE contrasts first (rescue contexts); null and
            # negative contrasts sink below them.
            0 if item["contrast"] is not None and cast(float, item["contrast"]) > 0 else 1,
            -(cast(float, item["contrast"]) if item["contrast"] is not None else 0.0),
            -int(cast(int, item["cooccurrence"])),
            str(item["name"]),
        )
    )
    return {"schema_version": 1, "tag_id": tag_id, "items": rows}


# ── Pairwise picks ───────────────────────────────────────────────────────────

PAIR_DIMENSIONS = ("tag", "performer", "studio", "orthogonal")
PAIR_MIN_BUDGET, PAIR_MAX_BUDGET = 4, 20
PAIR_DEFAULT_BUDGET = 10
MAX_CANDIDATE_PAIRS = 20_000
PAIR_SCENE_CAP = 2  # a scene appears in at most this many pairs per round
PAIR_DIMENSION_FIT_SHARE = 0.5
# Orthogonal candidates are over-generated by this factor so _pair_score has
# real choices to rank between, rather than accepting every candidate because
# there are exactly enough of them to fill the budget.
ORTHOGONAL_CANDIDATE_MULTIPLIER = 10
# Beta prior strength for verdict win rates: 4 pseudo-comparisons split evenly,
# so a 2-of-2 sweep reports 0.67 rather than a meaningless 1.00.
PAIR_VERDICT_PRIOR = 4.0
VERDICT_QUERY_CHUNK = 400
PAIR_PICK_VALUES = ("a", "b", "tie", "skip", "flag")


def _pair_rarity(context: CurationContext, performer_id: str) -> float:
    return 1.0 / math.sqrt(max(1, context.performer_counts.get(performer_id, 0)))


def _scene_coverage(context: CurationContext, scene_id: str) -> float:
    # Capped: the top few rare tags/performers decide coverage, so a scene
    # with 110 common tags does not outrank one with two rare fetish tags.
    tags = sorted(
        (t for t in context.scene_tags.get(scene_id, ()) if context.is_interactive(t)),
        key=lambda t: -context.rarity(t),
    )[:5]
    perfs = sorted(
        context.scene_performers.get(scene_id, ()),
        key=lambda p: -_pair_rarity(context, p),
    )[:3]
    return sum(context.rarity(t) for t in tags) + sum(_pair_rarity(context, p) for p in perfs)


def _pair_score(
    context: CurationContext, a: str, b: str, dimension: str
) -> tuple[float, float, float]:
    """(score, predicted_a, predicted_b): conflict x coverage x dimension-fit.

    Coverage is the *mean* rarity over the symmetric difference, not the sum:
    summing rewards pairs that differ on many features, which spreads a single
    comparison's +-1 signal thin across all of them. Averaging instead favors
    pairs that differ on few but rare features, where one answer resolves
    something concrete.
    """
    pred_a = context.appeal.get(a, 0.0)
    pred_b = context.appeal.get(b, 0.0)
    conflict = 1.0 / (1.0 + abs(pred_a - pred_b))
    tags_a = {t for t in context.scene_tags.get(a, ()) if context.is_interactive(t)}
    tags_b = {t for t in context.scene_tags.get(b, ()) if context.is_interactive(t)}
    tags_diff = tags_a ^ tags_b
    perfs_a = context.scene_performers.get(a, frozenset())
    perfs_b = context.scene_performers.get(b, frozenset())
    perfs_diff = perfs_a ^ perfs_b
    diff_count = len(tags_diff) + len(perfs_diff)
    coverage = (
        (
            sum(context.rarity(t) for t in tags_diff)
            + sum(_pair_rarity(context, p) for p in perfs_diff)
        )
        / diff_count
        if diff_count
        else 0.0
    )
    if dimension == "tag":
        shared = len(perfs_a & perfs_b)
    elif dimension in ("performer", "studio"):
        shared = len(tags_a & tags_b)
    else:
        shared = 0
    fit = 1.0 + PAIR_DIMENSION_FIT_SHARE * shared
    return conflict * coverage * fit, pred_a, pred_b


def _pair_unlabeled(context: CurationContext, seen: frozenset[str]) -> list[str]:
    """Unlabeled, unblocked scenes never shown in any previous round."""
    return [
        sid
        for sid in sorted(context.scene_ids)
        if sid not in context.labels
        and sid not in context.blocked_scenes
        and sid not in context.metadata_wrong
        and sid not in seen
    ]


def _pair_candidates(
    context: CurationContext,
    dimension: str,
    base_tag: str | None,
    context_tag: str | None,
    performer_id: str | None,
    seen: frozenset[str],
) -> list[tuple[str, str]]:
    """Deterministic candidate pairs for the dimension, bounded."""
    unlabeled = _pair_unlabeled(context, seen)
    if dimension == "tag" and base_tag and context_tag:
        cell_a = [
            sid
            for sid in unlabeled
            if base_tag in context.scene_tags.get(sid, ())
            and context_tag in context.scene_tags.get(sid, ())
        ]
        cell_b = [
            sid
            for sid in unlabeled
            if base_tag in context.scene_tags.get(sid, ())
            and context_tag not in context.scene_tags.get(sid, ())
        ]
        cell_b = _group_clean_scenes(context, cell_b, context_tag)
        out: list[tuple[str, str]] = []
        for a in cell_a:
            for b in cell_b:
                if len(out) >= MAX_CANDIDATE_PAIRS:
                    return out
                out.append((a, b))
        return out
    if dimension == "performer" and performer_id:
        cell_a = [sid for sid in unlabeled if performer_id in context.scene_performers.get(sid, ())]
        out = []
        for a in cell_a:
            tags_a = context.scene_tags.get(a, ())
            for b in unlabeled:
                if b == a or performer_id in context.scene_performers.get(b, ()):
                    continue
                if not (set(tags_a) & set(context.scene_tags.get(b, ()))):
                    continue
                if len(out) >= MAX_CANDIDATE_PAIRS:
                    return out
                out.append((a, b))
        return out
    out = []
    n = len(unlabeled)
    for i in range(n):
        a = unlabeled[i]
        tags_a = context.scene_tags.get(a, frozenset())
        perfs_a = context.scene_performers.get(a, frozenset())
        studio_a = context.studio.get(a, "?")
        for j in range(i + 1, n):
            if len(out) >= MAX_CANDIDATE_PAIRS:
                return out
            b = unlabeled[j]
            if dimension == "performer":
                if perfs_a & context.scene_performers.get(b, frozenset()):
                    continue
                if not (tags_a & context.scene_tags.get(b, frozenset())):
                    continue
            elif dimension == "studio":
                if studio_a == context.studio.get(b, "?"):
                    continue
                if not (tags_a & context.scene_tags.get(b, frozenset())):
                    continue
            else:  # tag without explicit cells, or fallback
                if tags_a == context.scene_tags.get(b, frozenset()):
                    continue
            out.append((a, b))
    return out


def _orthogonal_pairs(
    context: CurationContext, budget: int, seen: frozenset[str]
) -> list[tuple[str, str]]:
    """Coverage-ranked adjacency pairing: candidates from the top
    ORTHOGONAL_CANDIDATE_MULTIPLIER x budget scenes, adjacent-paired.

    Deliberately over-generates: create_pair_round's own _pair_score ranking
    then picks the best `budget` of these. Returning exactly `budget` pairs
    here (as this used to) left that ranking step nothing to choose between,
    since every generated pair used each scene exactly once and so always
    passed the per-scene cap.
    """
    unlabeled = _pair_unlabeled(context, seen)
    unlabeled.sort(key=lambda sid: (-_scene_coverage(context, sid), sid))
    take = min(len(unlabeled), ORTHOGONAL_CANDIDATE_MULTIPLIER * budget)
    scenes = unlabeled[:take]
    return [(scenes[i], scenes[i + 1]) for i in range(0, len(scenes) - 1, 2)]


def create_pair_round(
    connection: sqlite3.Connection,
    dimension: str,
    budget: int,
    base_tag_id: str | None = None,
    context_tag_id: str | None = None,
    performer_id: str | None = None,
    config: CuratorConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    if dimension not in PAIR_DIMENSIONS:
        raise ValueError(f"dimension must be one of {', '.join(PAIR_DIMENSIONS)}")
    if not PAIR_MIN_BUDGET <= budget <= PAIR_MAX_BUDGET:
        raise ValueError(f"budget must be from {PAIR_MIN_BUDGET} to {PAIR_MAX_BUDGET}")
    if dimension == "tag" and (base_tag_id or context_tag_id):
        for tag_id in (base_tag_id, context_tag_id):
            if (
                tag_id is not None
                and connection.execute(
                    "SELECT 1 FROM source_tag WHERE tag_id=?", (tag_id,)
                ).fetchone()
                is None
            ):
                raise ValueError(f"unknown tag: {tag_id}")
    if (
        dimension == "performer"
        and performer_id
        and connection.execute(
            "SELECT 1 FROM source_performer WHERE performer_id=?", (performer_id,)
        ).fetchone()
        is None
    ):
        raise ValueError(f"unknown performer: {performer_id}")
    context = curation_context(connection, config)
    # Only answered pairs retire their scenes. Offering a pair used to burn
    # both scenes forever, so an abandoned round — or a stream that prefetches
    # ahead of the user — permanently consumed scenes nobody ever judged.
    seen = frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT scene_a FROM curation_pair WHERE status='answered'"
            " UNION SELECT scene_b FROM curation_pair WHERE status='answered'"
        )
    )
    if dimension == "orthogonal":
        candidates = _orthogonal_pairs(context, budget, seen)
    else:
        candidates = _pair_candidates(
            context, dimension, base_tag_id, context_tag_id, performer_id, seen
        )
    scored: list[tuple[str, str, float, float, float]] = []
    for a, b in candidates:
        score, pred_a, pred_b = _pair_score(context, a, b, dimension)
        if score <= 0:
            continue
        scored.append((a, b, score, pred_a, pred_b))
    if not scored:
        return {
            "schema_version": 1,
            "round_id": str(uuid4()),
            "dimension": dimension,
            "pairs": [],
            "policy": "no candidate pairs above zero information",
        }
    total = sum(entry[2] for entry in scored)
    scored.sort(key=lambda entry: (-entry[2], entry[0], entry[1]))
    selected: list[tuple[str, str, float, float, float]] = []
    scene_uses: dict[str, int] = {}
    for a, b, score, pred_a, pred_b in scored:
        if scene_uses.get(a, 0) >= PAIR_SCENE_CAP or scene_uses.get(b, 0) >= PAIR_SCENE_CAP:
            continue
        selected.append((a, b, score / total, pred_a, pred_b))
        scene_uses[a] = scene_uses.get(a, 0) + 1
        scene_uses[b] = scene_uses.get(b, 0) + 1
        if len(selected) >= budget:
            break
    round_id = str(uuid4())
    with transaction(connection):
        for a, b, probability, pred_a, pred_b in selected:
            payload = {
                "dimension": dimension,
                "predicted_a": pred_a,
                "predicted_b": pred_b,
                "base_tag_id": base_tag_id,
                "context_tag_id": context_tag_id,
                "performer_id": performer_id,
            }
            connection.execute(
                """
                INSERT INTO curation_pair(
                    pair_id, round_id, scene_a, scene_b, dimension,
                    selection_probability, status, winner, occurred_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?)
                """,
                (
                    str(uuid4()),
                    round_id,
                    a,
                    b,
                    dimension,
                    probability,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )

    def scene_meta(sid: str) -> dict[str, object]:
        return {
            "scene_id": sid,
            "title": context.scene_title.get(sid),
            "studio": context.studio.get(sid),
            "date": context.scene_date.get(sid),
            "details": context.scene_details.get(sid),
            "performers": [
                {"performer_id": pid, "name": context.performer_name.get(pid, pid)}
                for pid in sorted(context.scene_performers.get(sid, ()))
            ],
            "tags": _item_tags(context, sid),
        }

    pairs = [
        {
            "pair_id": "",
            "scene_a": scene_meta(a),
            "scene_b": scene_meta(b),
            "predicted_a": pred_a,
            "predicted_b": pred_b,
            "selection_probability": probability,
        }
        for a, b, probability, pred_a, pred_b in selected
    ]
    # pair ids were generated inside the transaction; read them back in order.
    rows = connection.execute(
        "SELECT pair_id FROM curation_pair WHERE round_id=? ORDER BY rowid", (round_id,)
    ).fetchall()
    for item, row in zip(pairs, rows, strict=True):
        item["pair_id"] = str(row["pair_id"])
    base_tag_val: dict[str, object] | None = None
    context_tag_val: dict[str, object] | None = None
    if dimension == "tag" and base_tag_id:
        base_tag_val = {
            "tag_id": base_tag_id,
            "name": context.tag_name.get(base_tag_id, base_tag_id),
        }
    if dimension == "tag" and context_tag_id:
        context_tag_val = {
            "tag_id": context_tag_id,
            "name": context.tag_name.get(context_tag_id, context_tag_id),
        }
    return {
        "schema_version": 1,
        "round_id": round_id,
        "dimension": dimension,
        "base_tag": base_tag_val,
        "context_tag": context_tag_val,
        "pairs": pairs,
        "policy": "conflict-first + coverage, dimension prior, IPS-corrected",
    }


def _pair_rows(connection: sqlite3.Connection, round_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT pair_id, scene_a, scene_b, dimension, selection_probability,
                  status, winner, payload_json
           FROM curation_pair WHERE round_id=? ORDER BY pair_id""",
        (round_id,),
    ).fetchall()


def submit_picks(
    connection: sqlite3.Connection, round_id: str, picks: list[dict[str, Any]]
) -> dict[str, object]:
    if not round_id:
        raise ValueError("round_id is required")
    rows = _pair_rows(connection, round_id)
    if not rows:
        raise ValueError(f"unknown round: {round_id}")
    by_id = {str(row["pair_id"]): row for row in rows}
    seen: set[str] = set()
    normalized: list[tuple[str, str, str | None]] = []
    for entry in picks:
        if not isinstance(entry, dict):
            raise ValueError("each pick must be an object with pair_id and winner")
        pair_id = str(entry.get("pair_id") or "")
        if pair_id not in by_id:
            raise ValueError(f"pair is not in this round: {pair_id}")
        if pair_id in seen:
            raise ValueError(f"duplicate pick for pair: {pair_id}")
        if str(by_id[pair_id]["status"]) != "open":
            raise ValueError(f"pair already answered: {pair_id}")
        winner = entry.get("winner")
        if winner not in PAIR_PICK_VALUES:
            raise ValueError("winner must be 'a', 'b', 'tie', 'skip', or 'flag'")
        scene: str | None = None
        if winner == "flag":
            scene = entry.get("scene")
            if scene not in ("a", "b"):
                raise ValueError("winner 'flag' requires a scene of 'a' or 'b'")
        seen.add(pair_id)
        normalized.append((pair_id, str(winner), scene))
    if not normalized:
        raise ValueError("picks must not be empty")
    now_ms = time.time_ns() // 1_000_000
    accepted = 0
    skipped = 0
    # Picks write feedback rows like every other interaction, so they mark the
    # model dirty too; without this the round never reaches a build and "What
    # your picks moved" keeps reporting the previous build's diff. One request
    # per pick, not per call: the pending count is weighed against the update
    # threshold, and a round is many feedback events, not one.
    coordinator = ModelUpdateCoordinator(connection)
    with transaction(connection):
        for pair_id, winner, scene in normalized:
            row = by_id[pair_id]
            dimension = str(row["dimension"])
            payload = json.loads(str(row["payload_json"]) or "{}")
            if winner in ("skip", "flag"):
                connection.execute(
                    "UPDATE curation_pair SET status='skipped' WHERE pair_id=?", (pair_id,)
                )
                if winner == "flag":
                    assert scene is not None
                    flagged_scene = row["scene_a"] if scene == "a" else row["scene_b"]
                    connection.execute(
                        """
                        INSERT INTO feedback(
                            feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                            reversed_by_id, impression_id, payload_json
                        ) VALUES (?, ?, 'metadata_wrong', NULL, ?, NULL, NULL, '{}')
                        """,
                        (f"{now_ms}-{uuid4().hex}", flagged_scene, now_ms),
                    )
                    coordinator.request("curation_picks")
                skipped += 1
                continue
            scene_a = str(row["scene_a"])
            scene_b = str(row["scene_b"])
            # A tie is "these two are equally appealing" — real Bradley-Terry
            # information that pulls the features which differed toward the
            # mean, so it carries a label like any other answer. It has no
            # winner, so the row keeps winner NULL; every consumer of
            # 'answered' already guards on winner IN ('a', 'b').
            tie = winner == "tie"
            winner_scene = scene_a if winner == "a" else scene_b
            loser_scene = scene_b if winner == "a" else scene_a
            pred_winner = (
                payload.get("predicted_a") if winner != "b" else payload.get("predicted_b")
            )
            pred_loser = payload.get("predicted_b") if winner != "b" else payload.get("predicted_a")
            label_payload = {
                "pair_id": pair_id,
                "round_id": round_id,
                "dimension": dimension,
                "predicted_winner": pred_winner,
                "predicted_loser": pred_loser,
                "selection_probability": float(row["selection_probability"]),
            }
            labels: tuple[tuple[str, str, str], ...] = (
                ((scene_a, "5", "curation_pair_tie"), (scene_b, "5", "curation_pair_tie"))
                if tie
                else (
                    (winner_scene, "10", "curation_pair_winner"),
                    (loser_scene, "0", "curation_pair_loser"),
                )
            )
            for scene_id, value, feedback_type in labels:
                connection.execute(
                    """
                    INSERT INTO feedback(
                        feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                        reversed_by_id, impression_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        f"{now_ms}-{uuid4().hex}",
                        scene_id,
                        feedback_type,
                        value,
                        now_ms,
                        json.dumps(label_payload, sort_keys=True, separators=(",", ":")),
                    ),
                )
            connection.execute(
                "UPDATE curation_pair SET status='answered', winner=?, occurred_at_ms=?"
                " WHERE pair_id=?",
                (None if tie else winner, now_ms, pair_id),
            )
            coordinator.request("curation_picks")
            accepted += 1
    return {
        "schema_version": 1,
        "accepted": accepted,
        "skipped": skipped,
        "round_status": "answered" if accepted + skipped == len(rows) else "open",
    }


def _round_payload(connection: sqlite3.Connection, round_id: str) -> dict[str, object]:
    row = connection.execute(
        """SELECT payload_json FROM curation_pair WHERE round_id=?
           ORDER BY pair_id LIMIT 1""",
        (round_id,),
    ).fetchone()
    if row is None:
        return {}
    return cast(dict[str, object], json.loads(str(row["payload_json"]) or "{}"))


def _shrunk_rate(wins: int, appearances: int) -> float:
    """Win rate pulled toward 0.5 by a symmetric Beta prior.

    A single round answers ~10 comparisons, so raw rates are dominated by
    2-of-2 sweeps that read as "100% preferred" and mean nothing. Shrinking
    makes the number honest at small n and converges on the raw rate as
    comparisons accumulate.
    """
    if appearances <= 0:
        return 0.5
    half = PAIR_VERDICT_PRIOR / 2.0
    return (wins + half) / (appearances + PAIR_VERDICT_PRIOR)


def _answered_pairs(connection: sqlite3.Connection, dimension: str) -> list[sqlite3.Row]:
    """Every answered pair of this dimension, across all rounds.

    Verdicts accumulate: a hypothesis re-tested over several rounds should
    compound rather than restart from zero each time.
    """
    return connection.execute(
        """SELECT pair_id, round_id, scene_a, scene_b, winner, payload_json
           FROM curation_pair
           WHERE dimension=? AND status='answered' AND winner IN ('a', 'b')
           ORDER BY pair_id""",
        (dimension,),
    ).fetchall()


def _scene_tag_map(
    connection: sqlite3.Connection, scene_ids: set[str]
) -> dict[str, frozenset[str]]:
    """Tags for the given scenes, in chunked queries rather than one per scene."""
    collected: dict[str, set[str]] = {sid: set() for sid in scene_ids}
    ordered = sorted(collected)
    for start in range(0, len(ordered), VERDICT_QUERY_CHUNK):
        chunk = ordered[start : start + VERDICT_QUERY_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        for row in connection.execute(
            f"SELECT scene_id, tag_id FROM scene_tag WHERE scene_id IN ({placeholders})"
            " ORDER BY scene_id, tag_id",
            chunk,
        ):
            collected[str(row["scene_id"])].add(str(row["tag_id"]))
    return {sid: frozenset(tags) for sid, tags in collected.items()}


def pair_verdict(connection: sqlite3.Connection, round_id: str) -> dict[str, object]:
    if not round_id:
        raise ValueError("round_id is required")
    rows = _pair_rows(connection, round_id)
    if not rows:
        raise ValueError(f"unknown round: {round_id}")
    round_answered = [
        row for row in rows if str(row["status"]) == "answered" and str(row["winner"]) in ("a", "b")
    ]
    dimension = str(rows[0]["dimension"])
    base_tag = str(_round_payload(connection, round_id).get("base_tag_id") or "")
    context_tag = str(_round_payload(connection, round_id).get("context_tag_id") or "")
    answered = _answered_pairs(connection, dimension)
    if dimension == "tag":
        # Only the pairs testing this same hypothesis accumulate together.
        matching = []
        for row in answered:
            row_payload = json.loads(str(row["payload_json"]) or "{}")
            if (
                str(row_payload.get("base_tag_id") or "") == base_tag
                and str(row_payload.get("context_tag_id") or "") == context_tag
            ):
                matching.append(row)
        answered = matching
    pair_scenes = {str(row["scene_a"]) for row in answered} | {
        str(row["scene_b"]) for row in answered
    }
    scene_tags = _scene_tag_map(connection, pair_scenes)

    def cell_of(scene_id: str) -> str:
        tags = scene_tags.get(scene_id, frozenset())
        has_base = base_tag and base_tag in tags
        has_ctx = context_tag and context_tag in tags
        if has_base and has_ctx:
            return "L&T"
        if has_base:
            return "L&!T"
        if has_ctx:
            return "!L&T"
        return "neither"

    if dimension == "tag":
        wins: dict[str, int] = {}
        for row in answered:
            winner_scene = str(row["scene_a"]) if str(row["winner"]) == "a" else str(row["scene_b"])
            cell = cell_of(winner_scene)
            wins[cell] = wins.get(cell, 0) + 1
        cells = [
            {"cell": cell, "wins": wins.get(cell, 0)} for cell in ("L&T", "L&!T", "!L&T", "neither")
        ]
        contrast: dict[str, object] = {}
        if wins.get("L&T", 0) + wins.get("L&!T", 0) > 0:
            contrast = {
                "delta": wins.get("L&T", 0) - wins.get("L&!T", 0),
                "n": wins.get("L&T", 0) + wins.get("L&!T", 0),
            }
        return {
            "schema_version": 1,
            "round_id": round_id,
            "dimension": dimension,
            "cells": cells,
            "contrast": contrast,
            "n_answered": len(answered),
            "n_round": len(round_answered),
        }

    if dimension == "performer":
        perf_appearances: dict[str, int] = {}
        perf_wins: dict[str, int] = {}
        for row in answered:
            winner_scene = str(row["scene_a"]) if str(row["winner"]) == "a" else str(row["scene_b"])
            for scene_id in (str(row["scene_a"]), str(row["scene_b"])):
                for p in connection.execute(
                    "SELECT performer_id FROM scene_performer WHERE scene_id=?", (scene_id,)
                ):
                    pid = str(p["performer_id"])
                    perf_appearances[pid] = perf_appearances.get(pid, 0) + 1
            for p in connection.execute(
                "SELECT performer_id FROM scene_performer WHERE scene_id=?", (winner_scene,)
            ):
                pid = str(p["performer_id"])
                perf_wins[pid] = perf_wins.get(pid, 0) + 1
        items = [
            {
                "performer_id": pid,
                "wins": perf_wins.get(pid, 0),
                "appearances": perf_appearances[pid],
                "win_rate": _shrunk_rate(perf_wins.get(pid, 0), perf_appearances[pid]),
            }
            for pid in perf_appearances
            if perf_appearances[pid] >= 2
        ]
        items.sort(
            key=lambda item: (
                -float(cast(float, item["win_rate"])),
                str(item["performer_id"]),
            )
        )
        return {
            "schema_version": 1,
            "round_id": round_id,
            "dimension": dimension,
            "items": items,
            "n_answered": len(answered),
            "n_round": len(round_answered),
        }

    if dimension == "studio":
        studio_appearances: dict[str, int] = {}
        studio_wins: dict[str, int] = {}
        for row in answered:
            winner_scene = str(row["scene_a"]) if str(row["winner"]) == "a" else str(row["scene_b"])
            for scene_id in (str(row["scene_a"]), str(row["scene_b"])):
                studio = connection.execute(
                    """SELECT s.name FROM source_scene ss
                       JOIN source_studio s ON s.studio_id=ss.studio_id
                       WHERE ss.scene_id=?""",
                    (scene_id,),
                ).fetchone()
                if studio is None:
                    continue
                name = str(studio["name"])
                studio_appearances[name] = studio_appearances.get(name, 0) + 1
            studio = connection.execute(
                """SELECT s.name FROM source_scene ss
                   JOIN source_studio s ON s.studio_id=ss.studio_id
                   WHERE ss.scene_id=?""",
                (winner_scene,),
            ).fetchone()
            if studio is not None:
                name = str(studio["name"])
                studio_wins[name] = studio_wins.get(name, 0) + 1
        items = [
            {
                "studio": name,
                "wins": studio_wins.get(name, 0),
                "appearances": studio_appearances[name],
                "win_rate": _shrunk_rate(studio_wins.get(name, 0), studio_appearances[name]),
            }
            for name in studio_appearances
            if studio_appearances[name] >= 2
        ]
        items.sort(key=lambda item: (-float(cast(float, item["win_rate"])), str(item["studio"])))
        return {
            "schema_version": 1,
            "round_id": round_id,
            "dimension": dimension,
            "items": items,
            "n_answered": len(answered),
            "n_round": len(round_answered),
        }

    # orthogonal: tag win-share over symmetric-difference appearances.
    orth_appearances: dict[str, int] = {}
    orth_wins: dict[str, int] = {}
    for row in answered:
        winner_scene = str(row["scene_a"]) if str(row["winner"]) == "a" else str(row["scene_b"])
        loser_scene = str(row["scene_b"]) if str(row["winner"]) == "a" else str(row["scene_a"])
        tags_w = scene_tags.get(winner_scene, frozenset())
        tags_l = scene_tags.get(loser_scene, frozenset())
        for tag_id in tags_w - tags_l:
            orth_wins[tag_id] = orth_wins.get(tag_id, 0) + 1
            orth_appearances[tag_id] = orth_appearances.get(tag_id, 0) + 1
        for tag_id in tags_l - tags_w:
            orth_appearances[tag_id] = orth_appearances.get(tag_id, 0) + 1
    names = {
        str(r["tag_id"]): str(r["name"])
        for r in connection.execute("SELECT tag_id, name FROM source_tag")
    }
    items = [
        {
            "tag_id": tag_id,
            "name": names.get(tag_id, tag_id),
            "wins": orth_wins.get(tag_id, 0),
            "appearances": orth_appearances[tag_id],
            "win_rate": _shrunk_rate(orth_wins.get(tag_id, 0), orth_appearances[tag_id]),
        }
        for tag_id in orth_appearances
        if orth_appearances[tag_id] >= 2
    ]
    items.sort(key=lambda item: (-float(cast(float, item["win_rate"])), str(item["tag_id"])))
    return {
        "schema_version": 1,
        "round_id": round_id,
        "dimension": dimension,
        "items": items,
        "n_answered": len(answered),
        "n_round": len(round_answered),
    }


# -- Impact -------------------------------------------------------------------

IMPACT_TOP_SCENES = 5
IMPACT_TOP_ENTITIES = 4
IMPACT_MIN_DELTA = 0.01
IMPACT_MIN_CONTRIBUTION = 0.0005
IMPACT_SCENE_POOL = 20


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
        for name, delta in candidates[: 3 - len(out)]:
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
                }
            )
        return out

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
