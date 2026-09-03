"""Curation ops: pairwise picks, verdicts, and model impact.

The pair loop surfaces deterministic pairs of unlabeled scenes across the
tag, performer, studio, and orthogonal dimensions; each pick answers one
pair and writes winner/loser labels that feed the model. Pair verdicts
accumulate per dimension across rounds; curation_impact diffs the two most
recent model builds.

Everything is deterministic (ORDER BY, sorted iteration, no RNG, explicit
tie-breaks) so the compiled core mirrors every function byte-identically;
the differential gates enforce that contract.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import Counter, defaultdict
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
# interactive tag space.
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

MAX_ITEM_TAGS = 8


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


# ── Pairwise picks ───────────────────────────────────────────────────────────

PAIR_DIMENSIONS = ("tag", "performer", "studio", "orthogonal")
PAIR_MIN_BUDGET, PAIR_MAX_BUDGET = 4, 20
PAIR_DEFAULT_BUDGET = 10
MAX_CANDIDATE_PAIRS = 20_000
PAIR_SCENE_CAP = 1  # a scene appears in at most this many pairs per round
PAIR_DIMENSION_FIT_SHARE = 0.5
# Discriminability curve for picking pairs at a moderate predicted-appeal gap.
# The old conflict = 1/(1+|predA-predB|) was maximal at a near-tie: the pair
# the model (and the user) are least able to judge, so the pick is close to a
# coin flip and the learned signal is noise. This peaks at a gap the user can
# reliably adjudicate, down-weights exact ties to zero, and decays for
# foregone conclusions (large gaps) instead of rewarding them. Pure
# arithmetic so the Go mirror is bit-identical.
PAIR_CONFLICT_OPTIMAL_GAP = 0.25
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

    Conflict is a discriminability curve peaked at PAIR_CONFLICT_OPTIMAL_GAP
    (a moderate predicted-appeal gap the user can reliably adjudicate), not
    1/(1+|predA-predB|): the old term was maximal at a near-tie, where a human
    pick is close to a coin flip and the learned +-1 label is noise.

    Coverage is the *mean* rarity over the symmetric difference, not the sum:
    summing rewards pairs that differ on many features, which spreads a single
    comparison's +-1 signal thin across all of them. Averaging instead favors
    pairs that differ on few but rare features, where one answer resolves
    something concrete.
    """
    pred_a = context.appeal.get(a, 0.0)
    pred_b = context.appeal.get(b, 0.0)
    gap = abs(pred_a - pred_b)
    # Peak at a moderate, discriminable gap; exact ties (gap 0) are uninformative
    # coin flips and large gaps are foregone conclusions, so both are down-weighted.
    conflict = (2.0 * PAIR_CONFLICT_OPTIMAL_GAP * gap) / (
        gap * gap + PAIR_CONFLICT_OPTIMAL_GAP * PAIR_CONFLICT_OPTIMAL_GAP
    )
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
    # Only answered or skipped pairs retire their scenes. Offering a pair used
    # to burn both scenes forever, so an abandoned round — or a stream that
    # prefetches ahead of the user — permanently consumed scenes nobody ever
    # judged; skipped scenes are retired too so a scene the user already saw
    # and declined is not re-offered round after round.
    seen = frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT scene_a FROM curation_pair WHERE status IN ('answered','skipped')"
            " UNION SELECT scene_b FROM curation_pair WHERE status IN ('answered','skipped')"
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
            "schema_version": 2,
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
        "schema_version": 2,
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
        "schema_version": 2,
        "accepted": accepted,
        "skipped": skipped,
        "round_status": "answered" if accepted + skipped == len(rows) else "open",
    }


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
    additive. Directly feeds the scene's own appeal (the absolute channel),
    not a pairwise comparison.
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
            "schema_version": 2,
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
            "schema_version": 2,
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
            "schema_version": 2,
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
        "schema_version": 2,
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
IMPACT_MAX_CONTRIBUTORS = 6  # per-scene "Because" entities shown (plus direct)
# Feedback types that teach the model's scene labels; used to tie a scene's
# move back to the user's own feedback on scenes carrying the same entities.
IMPACT_FEEDBACK_TYPES = (
    "thumb_up",
    "thumb_down",
    "curation_rating",
    "curation_pair_winner",
    "curation_pair_loser",
    "curation_pair_tie",
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
