"""Insights -> Your taste: a read-only summary of data Curator already keeps.

Nothing here is a new model. Top tags read the published model's affinities;
trends and the recent shift are a tag's share of the scenes watched in a
window of play history; what sets you apart applies the model's own
watch-lift formula (share of watched scenes over library share, shrunk
toward the library) to every tag; rediscovered scenes, dormant tastes, and
reasons are counts of stored rows. Every window is
anchored at the latest recorded play, not the clock, so the summary describes
the history it was computed from. core/taste_summary.go mirrors this module.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from itertools import pairwise

from curator.features.tag_roles import effective_tag_role_config_version
from curator.model import RecommendationModelStore
from curator.model.builder import WATCH_LIFT_SHRINK
from curator.model.curves import entity_dormancy

DAY_MS = 86_400_000
WINDOW_MS = 90 * DAY_MS
WINDOW_COUNT = 8
# A window with fewer watched scenes says too little to plot.
MIN_WINDOW_SCENES = 5
# Tags on fewer library scenes are flukes in every list.
MIN_TAG_SCENES = 3
# The taste profile's "belief" bar: the model is confident about the tag.
BELIEF_CONFIDENCE = 0.35
BELIEF_AFFINITY = 0.15
TOP_LIKES = 8
TOP_DISLIKES = 4
SHIFT_COUNT = 3
# Share points of watched scenes, and the watched scenes a shift needs.
SHIFT_MIN_DELTA = 0.05
SHIFT_MIN_SCENES = 3
DORMANT_COUNT = 3
REDISCOVER_GAP_MS = 180 * DAY_MS
REDISCOVERED_COUNT = 6
REASON_COUNT = 5
# What sets you apart: tags on at least 1.5% of watched scenes (and five)
# that you watch far more than your library holds, and tags on at least 3%
# of the library you watch at most 0.8 times as often.
APART_COUNT = 6
APART_MIN_WATCHED_SHARE = 0.015
APART_MIN_WATCHED = 5
PASSED_COUNT = 5
PASSED_MIN_LIBRARY_SHARE = 0.03
PASSED_MAX_RATIO = 0.8

AFFINITY_SQL = """
SELECT d.name, a.affinity, a.confidence
FROM feature_definition d
JOIN feature_affinity a ON a.feature_id=d.feature_id AND a.model_id=?
WHERE d.feature_version=? AND d.family='content'
ORDER BY d.name
"""
CONTENT_TAG_SQL = """
SELECT DISTINCT st.scene_id, st.tag_id
FROM scene_tag st
JOIN tag_role r ON r.tag_id=st.tag_id AND r.config_version=? AND r.role='content'
WHERE st.provenance='scene'
ORDER BY st.scene_id, st.tag_id
"""
PLAY_SQL = "SELECT scene_id, played_at_ms FROM source_play ORDER BY scene_id, played_at_ms, ordinal"
DORMANT_SQL = """
SELECT entity_type, entity_id, last_played_at_ms, positive_strength, play_count
FROM model_entity_dormancy
WHERE model_id=? AND play_count>=3 AND distinct_scene_count>=2 AND positive_strength>=0.10
ORDER BY positive_strength DESC, entity_type, entity_id
"""
REASON_SQL = """
SELECT CASE r.subject_type WHEN 'missing_tag' THEN 'tag' ELSE r.subject_type END AS kind,
       r.subject_id, a.polarity, count(DISTINCT a.answer_id) AS answers
FROM scene_reason r JOIN scene_reason_answer a ON a.answer_id=r.answer_id
WHERE r.subject_type<>'scene'
GROUP BY kind, r.subject_id, a.polarity
ORDER BY answers DESC, kind, r.subject_id
"""
NAME_SQL = {
    "tag": "SELECT tag_id, COALESCE(NULLIF(name, ''), tag_id) FROM source_tag",
    "performer": (
        "SELECT performer_id, COALESCE(NULLIF(name, ''), performer_id) FROM source_performer"
    ),
    "studio": "SELECT studio_id, COALESCE(NULLIF(name, ''), studio_id) FROM source_studio",
}


def watch_lift(with_tag: int, watched: int, library: int, total: int) -> float:
    """The model's watch-lift (PreferenceModelBuilder._watch_lift) for one window."""
    base = library / total
    return math.log(((with_tag + WATCH_LIFT_SHRINK * base) / (watched + WATCH_LIFT_SHRINK)) / base)


def taste_summary(connection: sqlite3.Connection) -> dict[str, object]:
    model_id = RecommendationModelStore(connection).current_model_id()
    if model_id is None:
        raise RuntimeError("no published model")
    feature_version = str(
        connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()[0]
    )
    config_version = effective_tag_role_config_version(connection) or ""
    names = {
        kind: {str(row[0]): str(row[1]) for row in connection.execute(sql)}
        for kind, sql in NAME_SQL.items()
    }
    total_scenes = int(connection.execute("SELECT count(*) FROM source_scene").fetchone()[0])

    scene_tags: dict[str, list[str]] = defaultdict(list)
    library: dict[str, int] = defaultdict(int)
    for row in connection.execute(CONTENT_TAG_SQL, (config_version,)):
        scene_tags[str(row[0])].append(str(row[1]))
        library[str(row[1])] += 1

    plays: dict[str, list[int]] = defaultdict(list)
    for row in connection.execute(PLAY_SQL):
        plays[str(row[0])].append(int(row[1]))
    play_count = sum(len(times) for times in plays.values())
    first_ms = min((times[0] for times in plays.values()), default=None)
    anchor_ms = max((times[-1] for times in plays.values()), default=None)

    def watched_between(start_ms: int | None, end_ms: int) -> set[str]:
        return {
            scene
            for scene, times in plays.items()
            if any((start_ms is None or start_ms < at) and at <= end_ms for at in times)
        }

    def tag_counts(scenes: set[str]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for scene in scenes:
            for tag in scene_tags.get(scene, ()):
                counts[tag] += 1
        return counts

    windows: list[dict[str, int]] = []
    window_counts: list[dict[str, int]] = []
    if anchor_ms is not None and first_ms is not None:
        for index in range(WINDOW_COUNT):
            end_ms = anchor_ms - (WINDOW_COUNT - 1 - index) * WINDOW_MS
            start_ms = end_ms - WINDOW_MS
            if end_ms < first_ms:
                continue
            scenes = watched_between(start_ms, end_ms)
            windows.append({"start_ms": start_ms, "end_ms": end_ms, "scenes": len(scenes)})
            window_counts.append(tag_counts(scenes))

    def trend(tag_id: str) -> list[float | None]:
        return [
            counts.get(tag_id, 0) / window["scenes"]
            if window["scenes"] >= MIN_WINDOW_SCENES
            else None
            for window, counts in zip(windows, window_counts, strict=True)
        ]

    all_watched = set(plays)
    watched_counts = tag_counts(all_watched)
    likes: list[dict[str, object]] = []
    dislikes: list[dict[str, object]] = []
    answers = {
        str(row[0]): float(row[1])
        for row in connection.execute("SELECT tag_id, value FROM direct_tag_preference")
    }
    for row in connection.execute(AFFINITY_SQL, (model_id, feature_version)):
        name, affinity = str(row["name"]), float(row["affinity"])
        tag_id = name.removeprefix("tag:")
        if tag_id == name or library.get(tag_id, 0) < MIN_TAG_SCENES:
            continue
        if float(row["confidence"]) < BELIEF_CONFIDENCE or abs(affinity) < BELIEF_AFFINITY:
            continue
        item = {
            "tag_id": tag_id,
            "name": names["tag"].get(tag_id, tag_id),
            "affinity": affinity,
            "confidence": float(row["confidence"]),
            "answer": answers.get(tag_id),
            "watched_scenes": watched_counts.get(tag_id, 0),
        }
        (likes if affinity > 0 else dislikes).append(item)
    # Likes that define what you watch: most-watched first. Dislikes are
    # rarely watched, so they rank by how strongly the model holds them.
    likes.sort(
        key=lambda item: (
            -int(str(item["watched_scenes"])),
            -float(str(item["affinity"])),
            str(item["name"]).lower(),
            str(item["tag_id"]),
        )
    )
    dislikes.sort(
        key=lambda item: (
            float(str(item["affinity"])) * float(str(item["confidence"])),
            str(item["name"]).lower(),
            str(item["tag_id"]),
        )
    )
    likes, dislikes = likes[:TOP_LIKES], dislikes[:TOP_DISLIKES]
    for item in (*likes, *dislikes):
        item["trend"] = trend(str(item["tag_id"]))

    rising: list[dict[str, object]] = []
    fading: list[dict[str, object]] = []
    if anchor_ms is not None:
        recent = watched_between(anchor_ms - WINDOW_MS, anchor_ms)
        before = watched_between(None, anchor_ms - WINDOW_MS)
        if len(recent) >= MIN_WINDOW_SCENES and len(before) >= MIN_WINDOW_SCENES:
            recent_counts, before_counts = tag_counts(recent), tag_counts(before)
            for tag_id in sorted(library):
                if library[tag_id] < MIN_TAG_SCENES:
                    continue
                if recent_counts.get(tag_id, 0) + before_counts.get(tag_id, 0) < SHIFT_MIN_SCENES:
                    continue
                now = recent_counts.get(tag_id, 0) / len(recent)
                then = before_counts.get(tag_id, 0) / len(before)
                delta = now - then
                item = {
                    "tag_id": tag_id,
                    "name": names["tag"].get(tag_id, tag_id),
                    "recent": now,
                    "before": then,
                    "delta": delta,
                }
                if delta >= SHIFT_MIN_DELTA:
                    rising.append(item)
                elif delta <= -SHIFT_MIN_DELTA:
                    fading.append(item)
    rising.sort(
        key=lambda item: (
            -float(str(item["delta"])),
            str(item["name"]).lower(),
            str(item["tag_id"]),
        )
    )
    fading.sort(
        key=lambda item: (float(str(item["delta"])), str(item["name"]).lower(), str(item["tag_id"]))
    )

    dormant: list[dict[str, object]] = []
    if anchor_ms is not None:
        for row in connection.execute(DORMANT_SQL, (model_id,)):
            days = max(0.0, (anchor_ms - int(row["last_played_at_ms"])) / DAY_MS)
            if entity_dormancy(days) < 0.5:
                continue
            kind, entity_id = str(row["entity_type"]), str(row["entity_id"])
            dormant.append(
                {
                    "entity_type": kind,
                    "entity_id": entity_id,
                    "name": names[kind].get(entity_id, entity_id),
                    "last_played_at_ms": int(row["last_played_at_ms"]),
                    "play_count": int(row["play_count"]),
                }
            )
            if len(dormant) == DORMANT_COUNT:
                break

    rediscovered: list[dict[str, object]] = []
    for scene_id, times in plays.items():
        gaps = [later - earlier for earlier, later in pairwise(times)]
        returns = sum(1 for gap in gaps if gap >= REDISCOVER_GAP_MS)
        if returns:
            rediscovered.append(
                {
                    "scene_id": scene_id,
                    "plays": len(times),
                    "returns": returns,
                    "longest_gap_ms": max(gaps),
                    "last_played_at_ms": times[-1],
                }
            )
    rediscovered.sort(
        key=lambda item: (
            -int(str(item["returns"])),
            -int(str(item["longest_gap_ms"])),
            str(item["scene_id"]),
        )
    )
    rediscovered = rediscovered[:REDISCOVERED_COUNT]
    for item in rediscovered:
        title = connection.execute(
            "SELECT COALESCE(title, '') FROM source_scene WHERE scene_id=?", (item["scene_id"],)
        ).fetchone()
        item["title"] = str(title[0]) if title else ""

    def apart_item(tag_id: str, lift: float) -> dict[str, object]:
        return {
            "tag_id": tag_id,
            "name": names["tag"].get(tag_id, tag_id),
            "lift": lift,
            "watched_share": watched_counts.get(tag_id, 0) / len(all_watched),
            "library_share": library[tag_id] / total_scenes,
        }

    apart: list[tuple[float, str]] = []
    passed: list[tuple[float, str]] = []
    if all_watched:
        min_watched = max(APART_MIN_WATCHED, math.ceil(APART_MIN_WATCHED_SHARE * len(all_watched)))
        for tag_id in sorted(library):
            watched = watched_counts.get(tag_id, 0)
            lift = watch_lift(watched, len(all_watched), library[tag_id], total_scenes)
            if watched >= min_watched and lift > 0:
                apart.append((lift, tag_id))
            if library[tag_id] / total_scenes >= PASSED_MIN_LIBRARY_SHARE and lift <= math.log(
                PASSED_MAX_RATIO
            ):
                passed.append((lift, tag_id))
    apart.sort(key=lambda pair: (-pair[0], names["tag"].get(pair[1], pair[1]).lower(), pair[1]))
    passed.sort(key=lambda pair: (pair[0], names["tag"].get(pair[1], pair[1]).lower(), pair[1]))

    reasons: dict[str, list[dict[str, object]]] = {"hits": [], "misses": []}
    for row in connection.execute(REASON_SQL):
        bucket = reasons["hits" if int(row["polarity"]) > 0 else "misses"]
        if len(bucket) == REASON_COUNT:
            continue
        kind, subject_id = str(row["kind"]), str(row["subject_id"])
        bucket.append(
            {
                "subject_type": kind,
                "subject_id": subject_id,
                "name": names[kind].get(subject_id, subject_id),
                "answers": int(row["answers"]),
            }
        )

    return {
        "model_id": model_id,
        "totals": {
            "plays": play_count,
            "scenes_played": len(all_watched),
            "library_scenes": total_scenes,
            "first_played_at_ms": first_ms,
            "as_of_ms": anchor_ms,
            "answered_tags": int(
                connection.execute("SELECT count(*) FROM direct_tag_preference").fetchone()[0]
            ),
            "reason_answers": int(
                connection.execute("SELECT count(*) FROM scene_reason_answer").fetchone()[0]
            ),
        },
        "windows": windows,
        "likes": likes,
        "dislikes": dislikes,
        "shift": {"rising": rising[:SHIFT_COUNT], "fading": fading[:SHIFT_COUNT]},
        "dormant": dormant,
        "rediscovered": rediscovered,
        "apart": {
            "more": [apart_item(tag_id, lift) for lift, tag_id in apart[:APART_COUNT]],
            "passed": [apart_item(tag_id, lift) for lift, tag_id in passed[:PASSED_COUNT]],
        },
        "reasons": reasons,
    }
