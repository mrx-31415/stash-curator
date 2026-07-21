"""Disposable cross-library recommendation evaluation against StashDB."""

# ruff: noqa: E501 - GraphQL and self-contained HTML are clearer unwrapped.

from __future__ import annotations

import argparse
import html
import json
import math
import netrc
import os
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from curator.cli import _stashdb_api_key
from curator.config import DEFAULT_CONFIG
from curator.features.measurements import CUP_ALIASES
from curator.features.profiles import PerformerProfile, ProfileValue, performer_similarity
from curator.features.store import FeatureStore
from curator.graphql import GraphQLClient

STASHDB = "https://stashdb.org/graphql"

LOCAL_LINKS = """
query CuratorExternalLinks($page: Int!, $perPage: Int!) {
  scenes: findScenes(
    scene_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count scenes { id stash_ids { endpoint stash_id } } }
  performers: findPerformers(
    performer_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count performers { id stash_ids { endpoint stash_id } } }
  studios: findStudios(
    studio_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count studios { id stash_ids { endpoint stash_id } } }
}
"""

EXTERNAL_SCENES = """
query CuratorExternalScenes($input: SceneQueryInput!) {
  queryScenes(input: $input) {
    count
    scenes {
      id title release_date production_date duration
      studio { id name }
      tags { id name category { id name group } }
      images { url width height }
      performers {
        performer {
          id name gender birth_date ethnicity eye_color hair_color height cup_size band_size
          waist_size hip_size breast_type tattoos { location } piercings { location }
          images { url width height }
        }
      }
    }
  }
}
"""


def _external_id(rows: list[dict[str, object]]) -> str | None:
    for row in rows:
        if str(row.get("endpoint", "")).rstrip("/").casefold() == STASHDB.rstrip("/").casefold():
            value = row.get("stash_id")
            return str(value) if value else None
    return None


def _is_female(performer: dict[str, Any]) -> bool:
    return str(performer.get("gender") or "").casefold() == "female"


def _local_links(client: GraphQLClient, page_size: int = 500) -> dict[str, dict[str, str]]:
    result = {"scenes": {}, "performers": {}, "studios": {}}
    page = 1
    while True:
        data = client.execute(LOCAL_LINKS, {"page": page, "perPage": page_size})
        exhausted = True
        for kind in result:
            collection = data[kind]
            rows = collection[kind]
            for row in rows:
                external = _external_id(row.get("stash_ids", []))
                if external:
                    result[kind][str(row["id"])] = external
            if page * page_size < int(collection["count"]):
                exhausted = False
        if exhausted:
            return result
        page += 1


def _seed_ids(
    connection: sqlite3.Connection,
    model_id: str,
    links: dict[str, dict[str, str]],
    count: int,
) -> tuple[list[str], list[str], list[str]]:
    local_scenes = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT scene_id FROM direct_scene_state WHERE model_id=?
            ORDER BY direct_appeal * confidence DESC, confidence DESC, scene_id
            """,
            (model_id,),
        )
        if str(row[0]) in links["scenes"]
    ][:count]
    performers = (
        {
            links["performers"][str(row[0])]
            for row in connection.execute(
                f"SELECT DISTINCT performer_id FROM scene_performer WHERE scene_id IN "
                f"({','.join('?' for _ in local_scenes)})",
                local_scenes,
            )
            if str(row[0]) in links["performers"]
        }
        if local_scenes
        else set()
    )
    studios = (
        {
            links["studios"][str(row[0])]
            for row in connection.execute(
                f"SELECT DISTINCT studio_id FROM source_scene WHERE scene_id IN "
                f"({','.join('?' for _ in local_scenes)}) AND studio_id IS NOT NULL",
                local_scenes,
            )
            if str(row[0]) in links["studios"]
        }
        if local_scenes
        else set()
    )
    return local_scenes, sorted(performers), sorted(studios)


def _seed_tags(
    connection: sqlite3.Connection, model_id: str, version: str, count: int = 12
) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT ids.stash_id
            FROM feature_affinity affinity
            JOIN feature_definition definition ON definition.feature_id=affinity.feature_id
            JOIN source_tag_stash_id ids
              ON definition.name='tag:' || ids.tag_id
             AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
            WHERE affinity.model_id=? AND definition.feature_version=?
              AND definition.family='content' AND affinity.affinity > 0
            ORDER BY affinity.affinity * affinity.confidence DESC, ids.stash_id
            LIMIT ?
            """,
            (STASHDB, model_id, version, count),
        )
    ]


def _fetch_candidates(
    client: GraphQLClient,
    performers: list[str],
    studios: list[str],
    tags: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    filters = (("performers", performers), ("studios", studios), ("tags", tags))
    per_filter = max(1, math.ceil(limit / max(1, sum(bool(values) for _, values in filters))))
    for source, values in filters:
        if not values:
            continue
        page = 1
        fetched = 0
        while fetched < per_filter:
            page_size = min(250, per_filter - fetched)
            input_data = {
                source: {"value": values, "modifier": "INCLUDES"},
                "page": page,
                "per_page": page_size,
                "sort": "POPULARITY",
                "direction": "DESC",
            }
            data = client.execute(EXTERNAL_SCENES, {"input": input_data})["queryScenes"]
            batch = data["scenes"]
            for scene in batch:
                identifier = str(scene["id"])
                rows.setdefault(identifier, scene)
                sources[identifier].add(source)
            fetched += len(batch)
            if not batch or page * page_size >= int(data["count"]):
                break
            page += 1
    result = []
    for identifier, row in rows.items():
        row["candidate_sources"] = sorted(sources[identifier])
        result.append(row)
    return sorted(result, key=lambda row: str(row["id"]))[:limit]


def _dedupe_candidates(
    candidates: list[dict[str, Any]], local_scene_ids: set[str]
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for scene in candidates:
        identifier = str(scene["id"])
        if identifier not in local_scene_ids:
            result.setdefault(identifier, scene)
    return list(result.values())


def _semantic_key(
    family: str,
    name: str,
    metadata: dict[str, object],
    tag_ids: dict[str, str],
    performer_ids: dict[str, str],
    studio_ids: dict[str, str],
) -> str | None:
    if family == "content":
        external = tag_ids.get(str(metadata.get("tag_id", name.removeprefix("tag:"))))
        return f"tag:{external}" if external else None
    if family == "performer_identity":
        external = performer_ids.get(
            str(metadata.get("performer_id", name.removeprefix("performer:")))
        )
        return f"performer:{external}" if external else None
    if family == "studio":
        external = studio_ids.get(str(metadata.get("studio_id", name.removeprefix("studio:"))))
        return f"studio:{external}" if external else None
    if family == "structure":
        return f"structure:{name}"
    return None


def _profile_features(performer: dict[str, Any], recorded: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for family, prefix, field, confidence in (
        ("ethnicity", "ethnicity", "ethnicity", 0.9),
        ("hair", "hair", "hair_color", 0.65),
        ("eyes", "eye", "eye_color", 0.9),
    ):
        raw = performer.get(field)
        if raw:
            values[f"profile:{family}:{prefix}:{str(raw).casefold()}"] = confidence
    numeric = {
        "band_inches": performer.get("band_size"),
        "waist_inches": performer.get("waist_size"),
        "hip_inches": performer.get("hip_size"),
    }
    if numeric["waist_inches"] and numeric["hip_inches"]:
        numeric["waist_to_hip"] = float(numeric["waist_inches"]) / float(numeric["hip_inches"])
    cup = CUP_ALIASES.get(str(performer.get("cup_size") or "").upper())
    if cup:
        numeric["cup_index"] = cup[0]
    for name, raw in numeric.items():
        if raw is not None:
            values[f"profile:measurements:{name}"] = float(raw)
    if performer.get("height"):
        values["profile:height:height_cm"] = float(performer["height"])
    breast_type = str(performer.get("breast_type") or "").casefold()
    if breast_type in {"natural", "augmented"}:
        values[f"profile:augmentation:{breast_type}"] = 1.0
    if performer.get("tattoos"):
        values["profile:tattoos:present"] = 0.8
    if performer.get("piercings"):
        values["profile:piercings:present"] = 0.8
    if performer.get("birth_date") and recorded:
        try:
            born, scene_date = (
                date.fromisoformat(performer["birth_date"]),
                date.fromisoformat(recorded),
            )
            age = (scene_date - born).days / 365.2425
            if 18 <= age <= 100:
                values["profile:age:age_recording"] = age
        except ValueError:
            pass
    return values


def _external_scene_features(scene: dict[str, Any], allowed: set[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for tag in scene.get("tags", []):
        key = f"tag:{tag['id']}"
        if key in allowed:  # Only locally classified scene-content tags survive.
            values[key] = 1.0
    studio = scene.get("studio")
    if studio and f"studio:{studio['id']}" in allowed:
        values[f"studio:{studio['id']}"] = 1.0
    appearances = scene.get("performers", [])
    profiles: list[dict[str, float]] = []
    recorded = scene.get("production_date") or scene.get("release_date")
    for appearance in appearances:
        performer = appearance["performer"]
        if not _is_female(performer):
            continue
        identity = f"performer:{performer['id']}"
        if identity in allowed:
            values[identity] = 1.0
        profiles.append(_profile_features(performer, recorded))
    for key in set().union(*(profile.keys() for profile in profiles)) if profiles else ():
        if key in allowed:
            present = [profile[key] for profile in profiles if key in profile]
            values[key] = sum(present) / len(present)
    if len(appearances) > 1 and "structure:multiple_performers" in allowed:
        values["structure:multiple_performers"] = min(1.0, (len(appearances) - 1) / 3)
    return values


def _external_profile(identifier: str, values: dict[str, float]) -> PerformerProfile:
    blocks: dict[str, dict[str, ProfileValue]] = defaultdict(dict)
    for key, value in values.items():
        if not key.startswith("profile:"):
            continue
        _, block, name = key.split(":", 2)
        blocks[block][name] = ProfileValue(value, 1.0)
    return PerformerProfile(identifier, dict(blocks))


def _external_profiles(
    scenes: list[dict[str, Any]], external_to_local_tags: dict[str, str]
) -> tuple[dict[str, PerformerProfile], dict[str, dict[str, Any]]]:
    profiles: dict[str, PerformerProfile] = {}
    raw_performers: dict[str, dict[str, Any]] = {}
    content: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    scene_counts: dict[str, int] = defaultdict(int)
    for scene in scenes:
        recorded = scene.get("production_date") or scene.get("release_date")
        tags = [
            f"tag:{external_to_local_tags[str(tag['id'])]}"
            for tag in scene.get("tags", [])
            if str(tag["id"]) in external_to_local_tags
        ]
        for appearance in scene.get("performers", []):
            raw = appearance["performer"]
            if not _is_female(raw):
                continue
            identifier = str(raw["id"])
            raw_performers.setdefault(identifier, raw)
            profiles.setdefault(
                identifier, _external_profile(identifier, _profile_features(raw, recorded))
            )
            scene_counts[identifier] += 1
            for tag in tags:
                content[identifier][tag] += 1.0
    for identifier, values in content.items():
        norm = math.sqrt(sum(value * value for value in values.values())) or 1.0
        confidence = min(1.0, scene_counts[identifier] / 5)
        profiles[identifier] = PerformerProfile(
            identifier,
            {
                **profiles[identifier].blocks,
                "content": {
                    name: ProfileValue(value / norm, confidence) for name, value in values.items()
                },
            },
        )
    return profiles, raw_performers


def _adjusted_similarity(result, block_weights: dict[str, float]) -> float:
    total = sum(weight for block, weight in block_weights.items() if block != "content")
    used = sum(
        result.block_weights[block] for block in result.block_similarities if block != "content"
    )
    content = result.block_weights.get("content", 0.0)
    content_used = content if "content" in result.block_similarities else 0.0
    coverage = (used + content_used) / max(total + content, 1e-9)
    score = result.similarity * math.sqrt(coverage)
    if "measurements" not in result.block_similarities:
        score = min(score, 0.65)
    return score


def _performer_matches(
    connection: sqlite3.Connection,
    version: str,
    model_id: str,
    scenes: list[dict[str, Any]],
    local_external_ids: set[str],
    external_to_local_tags: dict[str, str],
) -> dict[str, dict[str, Any]]:
    profiles = FeatureStore(connection).performer_profiles(version)
    anchor_evidence = {
        str(row[0]): (int(row[1]), float(row[2]), float(row[3]))
        for row in connection.execute(
            """
            SELECT sp.performer_id, count(DISTINCT d.scene_id), sum(d.confidence),
                   sum(d.direct_appeal * d.confidence) / sum(d.confidence)
            FROM scene_performer sp JOIN direct_scene_state d USING(scene_id)
            WHERE d.model_id=? GROUP BY sp.performer_id HAVING sum(d.confidence) > 0
            """,
            (model_id,),
        )
    }
    female_ids = {
        str(row[0])
        for row in connection.execute(
            "SELECT performer_id FROM source_performer WHERE gender='FEMALE'"
        )
    }
    favorites = {
        str(row[0])
        for row in connection.execute("SELECT performer_id FROM source_performer WHERE favorite=1")
    }
    anchors = sorted(
        (
            item
            for item in profiles.values()
            if item.performer_id in female_ids
            and item.performer_id in anchor_evidence
            and anchor_evidence[item.performer_id][2] > 0
            and (
                item.performer_id in favorites
                or (
                    anchor_evidence[item.performer_id][0] >= 5
                    and anchor_evidence[item.performer_id][1] >= 2.5
                )
            )
        ),
        key=lambda item: -anchor_evidence[item.performer_id][2],
    )[:40]
    names = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT performer_id, name FROM source_performer")
    }
    weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
    external_profiles, raw_performers = _external_profiles(scenes, external_to_local_tags)
    local_names = {name.casefold() for name in names.values()}
    candidates: dict[str, dict[str, Any]] = {}
    for identifier, profile in external_profiles.items():
        raw = raw_performers[identifier]
        if identifier in local_external_ids or str(raw.get("name", "")).casefold() in local_names:
            continue
        matches = sorted(
            (
                (_adjusted_similarity(result, weights), result, anchor)
                for anchor in anchors
                if (result := performer_similarity(profile, anchor, weights)).similarity > 0
            ),
            key=lambda item: -item[0],
        )[:5]
        denominator = sum(score**3 for score, _, _ in matches)
        taste = (
            sum(anchor_evidence[anchor.performer_id][2] * score**3 for score, _, anchor in matches)
            / denominator
            if denominator
            else 0.0
        )
        candidates[identifier] = {
            "id": identifier,
            "name": str(raw.get("name") or identifier),
            "image": next(
                (image["url"] for image in raw.get("images", []) if image.get("url")), ""
            ),
            "score": matches[0][0] if matches else 0.0,
            "taste": taste,
            "matches": [
                {
                    "name": names.get(anchor.performer_id, anchor.performer_id),
                    "score": score,
                    "blocks": sorted(
                        result.block_similarities,
                        key=lambda block: (
                            -result.block_weights[block] * result.block_similarities[block]
                        ),
                    )[:4],
                }
                for score, result, anchor in matches[:3]
            ],
        }
    return candidates


def _similar_to(
    connection: sqlite3.Connection,
    version: str,
    name: str,
    scenes: list[dict[str, Any]],
    local_external_ids: set[str],
    external_to_local_tags: dict[str, str],
) -> list[dict[str, Any]]:
    target_row = connection.execute(
        "SELECT performer_id FROM source_performer WHERE lower(name)=lower(?) AND gender='FEMALE'",
        (name,),
    ).fetchone()
    if not target_row:
        raise RuntimeError(f"female local performer not found: {name}")
    target = FeatureStore(connection).performer_profiles(version).get(str(target_row[0]))
    if not target:
        raise RuntimeError(f"performer has no feature profile: {name}")
    profiles, raw_performers = _external_profiles(scenes, external_to_local_tags)
    local_names = {
        str(row[0]).casefold()
        for row in connection.execute("SELECT name FROM source_performer WHERE name IS NOT NULL")
    }
    weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
    rows = []
    for identifier, profile in profiles.items():
        raw = raw_performers[identifier]
        if identifier in local_external_ids or str(raw.get("name", "")).casefold() in local_names:
            continue
        result = performer_similarity(profile, target, weights)
        score = _adjusted_similarity(result, weights)
        rows.append(
            {
                "id": identifier,
                "name": str(raw.get("name") or identifier),
                "image": next(
                    (image["url"] for image in raw.get("images", []) if image.get("url")), ""
                ),
                "score": score,
                "matches": [
                    {
                        "name": name,
                        "blocks": sorted(
                            result.block_similarities,
                            key=lambda block: (
                                -result.block_weights[block] * result.block_similarities[block]
                            ),
                        )[:5],
                    }
                ],
            }
        )
    return sorted(rows, key=lambda row: (-row["score"], row["name"]))


def _clamp(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


def _asymmetric(values: list[float]) -> float:
    positives = sorted((value for value in values if value > 0), reverse=True)
    negatives = [value for value in values if value < 0]
    positive = positives[0] + 0.25 * sum(positives[1:]) if positives else 0.0
    friction = 0.25 * sum(negatives) / len(negatives) if negatives else 0.0
    return positive + friction


def _content_vector(
    scene: dict[str, Any], external_to_local_tags: dict[str, str]
) -> dict[str, float]:
    values = {
        f"tag:{external_to_local_tags[str(tag['id'])]}": 1.0
        for tag in scene.get("tags", [])
        if str(tag["id"]) in external_to_local_tags
    }
    norm = math.sqrt(len(values)) or 1.0
    return {key: value / norm for key, value in values.items()}


def _neighbor_evidence(
    candidate: dict[str, float],
    local_vectors: dict[str, dict[str, float]],
    labels: dict[str, tuple[float, float]],
    strengths: dict[str, float],
) -> tuple[float, list[str]]:
    maximum = max(strengths.values(), default=0.0)

    def weighted(vector: dict[str, float]) -> dict[str, float]:
        values = {
            key: value * strengths.get(key, 0.0) / maximum
            for key, value in vector.items()
            if maximum and strengths.get(key, 0.0) > 0
        }
        norm = math.sqrt(sum(value * value for value in values.values())) or 1.0
        return {key: value / norm for key, value in values.items()}

    target = weighted(candidate)
    evidence = []
    for scene_id, vector in local_vectors.items():
        if scene_id not in labels:
            continue
        other = weighted(vector)
        shared = set(target) & set(other)
        cosine = sum(target[key] * other[key] for key in shared)
        similarity = cosine * (1 - math.exp(-len(shared) / 4))
        if similarity < DEFAULT_CONFIG.model.minimum_neighbor_similarity:
            continue
        outcome, confidence = labels[scene_id]
        evidence.append((similarity**3 * confidence, outcome, scene_id))
    evidence.sort(reverse=True)
    selected = evidence[: DEFAULT_CONFIG.model.neighbor_count]
    denominator = sum(item[0] for item in selected)
    if not denominator:
        return 0.0, []
    label_support = sum(confidence for _, confidence in labels.values())
    label_mean = (
        sum(outcome * confidence for outcome, confidence in labels.values()) / label_support
    )
    outcome = sum(weight * value for weight, value, _ in selected) / denominator
    confidence = 1 - math.exp(-denominator / DEFAULT_CONFIG.model.neighbor_confidence_scale)
    return (outcome - label_mean) * confidence, [item[2] for item in selected[:3]]


def _score_candidates(
    connection: sqlite3.Connection,
    version: str,
    model_id: str,
    scenes: list[dict[str, Any]],
    performer_matches: dict[str, dict[str, Any]],
    affinity_weights: dict[str, float],
    external_to_local_tags: dict[str, str],
) -> list[dict[str, Any]]:
    config = DEFAULT_CONFIG.model
    labels = {
        str(row[0]): (float(row[1]), float(row[2]))
        for row in connection.execute(
            "SELECT scene_id, direct_appeal, confidence FROM direct_scene_state WHERE model_id=?",
            (model_id,),
        )
    }
    support = sum(confidence for _, confidence in labels.values())
    label_mean = sum(value * confidence for value, confidence in labels.values()) / support
    baseline = _clamp(
        label_mean * support / (config.affinity_prior + support), config.baseline_bound
    )
    local_content = FeatureStore(connection).scene_content_vectors(version)
    strengths = {
        str(row[0]): max(0.0, float(row[1]))
        for row in connection.execute(
            """
            SELECT fd.name, fa.affinity * fa.confidence
            FROM feature_affinity fa JOIN feature_definition fd USING(feature_id)
            WHERE fa.model_id=? AND fd.family='content'
            """,
            (model_id,),
        )
    }
    local_titles = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT scene_id, title FROM source_scene")
    }
    allowed = set(affinity_weights)
    results = []
    for scene in scenes:
        features = _external_scene_features(scene, allowed)
        contributions = {
            key: value * affinity_weights.get(key, 0.0) for key, value in features.items()
        }
        content = _clamp(
            sum(value for key, value in contributions.items() if key.startswith("tag:")),
            config.content_bound,
        )
        identities = [value for key, value in contributions.items() if key.startswith("performer:")]
        identity = _clamp(_asymmetric(identities), config.performer_identity_bound)
        studio = _clamp(
            sum(value for key, value in contributions.items() if key.startswith("studio:")),
            config.studio_bound,
        )
        structure = _clamp(
            sum(value for key, value in contributions.items() if key.startswith("structure:")),
            config.structure_bound,
        )
        similarity_values = []
        for appearance in scene.get("performers", []):
            match = performer_matches.get(str(appearance["performer"]["id"]))
            if match:
                similarity_values.append(float(match["taste"]) * float(match["score"]))
        performer = _clamp(_asymmetric(similarity_values), config.performer_similarity_bound)
        neighbor, neighbor_ids = _neighbor_evidence(
            _content_vector(scene, external_to_local_tags), local_content, labels, strengths
        )
        neighbor = _clamp(neighbor, config.neighbor_bound)
        score = baseline + content + identity + performer + studio + structure + neighbor
        evidence = sorted(
            (
                (value, key)
                for key, value in contributions.items()
                if value > 0 and (key.startswith("tag:") or key.startswith("performer:"))
            ),
            reverse=True,
        )[:4]
        display = {
            **{f"tag:{tag['id']}": str(tag["name"]) for tag in scene.get("tags", [])},
            **{
                f"performer:{item['performer']['id']}": str(item["performer"]["name"])
                for item in scene.get("performers", [])
            },
        }
        match_names = [
            match["matches"][0]["name"]
            for appearance in scene.get("performers", [])
            if (match := performer_matches.get(str(appearance["performer"]["id"])))
            and match["matches"]
        ]
        mapped = len(_content_vector(scene, external_to_local_tags))
        results.append(
            {
                "scene": scene,
                "score": score,
                "evidence": [display.get(key, key) for _, key in evidence],
                "anchors": match_names[:2],
                "neighbors": [local_titles[item] for item in neighbor_ids],
                "coverage": mapped / max(1, len(scene.get("tags", []))),
                "components": {
                    "baseline": baseline,
                    "content": content,
                    "neighbor": neighbor,
                    "performer identity": identity,
                    "performer similarity": performer,
                    "studio": studio,
                    "structure": structure,
                },
            }
        )
    return sorted(results, key=lambda item: (-item["score"], str(item["scene"]["id"])))


def _render(
    output: Path,
    metrics: dict[str, object],
    scenes: list[dict[str, Any]],
    performers: list[dict[str, Any]],
    similar_to: str | None,
    targeted: list[dict[str, Any]],
) -> None:
    def scene_cards(rows: list[dict[str, Any]]) -> str:
        cards = []
        for row in rows:
            scene = row["scene"]
            image = next((item["url"] for item in scene.get("images", []) if item.get("url")), "")
            people = ", ".join(item["performer"]["name"] for item in scene.get("performers", []))
            evidence = ", ".join(row["evidence"]) or "limited shared metadata"
            anchors = ", ".join(row["anchors"])
            neighbors = ", ".join(row["neighbors"])
            components = " · ".join(
                f"{name} {value:+.3f}" for name, value in row["components"].items()
            )
            cards.append(f"""<article>{f'<img loading="lazy" src="{html.escape(image, quote=True)}">' if image else ""}
<h3><a href="https://stashdb.org/scenes/{scene["id"]}">{html.escape(scene.get("title") or scene["id"])}</a></h3>
<p class="muted">{html.escape(people)} · {html.escape((scene.get("studio") or {}).get("name", ""))}</p>
<p><b>Score:</b> {row["score"]:+.3f} · <b>Coverage:</b> {row["coverage"]:.0%}</p>
<p><b>Why:</b> {html.escape(evidence)}{html.escape("; similar to " + anchors) if anchors else ""}{html.escape("; supported by " + neighbors) if neighbors else ""}.</p>
<details><summary>Score components</summary><p>{html.escape(components)}</p></details>
<p class="muted">Candidate source: {html.escape(", ".join(scene["candidate_sources"]))}</p></article>""")
        return "".join(cards)

    def performer_cards(rows: list[dict[str, Any]]) -> str:
        return "".join(
            f"""<article>{
                f'<img loading="lazy" src="{html.escape(row["image"], quote=True)}">'
                if row["image"]
                else ""
            }
<h3><a href="https://stashdb.org/performers/{row["id"]}">{html.escape(row["name"])}</a></h3>
<p><b>Similarity:</b> {row["score"]:.2f}</p><p>{
                html.escape(
                    "; ".join(
                        f"Similar to {match['name']} in {', '.join(block.replace('_', ' ') for block in match['blocks'])}"
                        for match in row["matches"][:2]
                    )
                )
            }</p></article>"""
            for row in rows
        )

    metric_rows = "".join(
        f"<tr><th>{html.escape(key.replace('_', ' ').title())}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in metrics.items()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""<!doctype html><meta charset="utf-8"><title>Curator StashDB PoC</title>
<style>body{{font:15px system-ui;background:#151518;color:#eee;margin:2rem}}a{{color:#9cc8ff}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:1rem}}
article{{background:#24242a;border-radius:10px;padding:1rem}}img{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:7px}}
.muted{{color:#aaa}}table{{border-collapse:collapse}}td,th{{padding:.35rem .7rem;border-bottom:1px solid #444;text-align:left}}
body.hide-images img{{display:none}}button{{padding:.5rem .8rem}}</style>
<h1>External StashDB recommendation PoC</h1>
<button onclick="document.body.classList.toggle('hide-images')">Show / hide images</button>
<p>This report extends Curator's v1 appeal signals to external metadata. Diversity is intentionally not applied.</p>
<table>{metric_rows}</table><h2>External v1 recommendations</h2><div class="grid">{scene_cards(scenes)}</div>
<h2>Similar unseen performers</h2><div class="grid">{performer_cards(performers)}</div>
{f'<h2>Similar to {html.escape(similar_to)}</h2><div class="grid">{performer_cards(targeted)}</div>' if similar_to else ""}""",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.count < 1 or args.seed_scenes < 1 or args.candidate_limit < 1:
        raise ValueError("count, seed-scenes, and candidate-limit must be positive")
    try:
        api_key = _stashdb_api_key()
    except netrc.NetrcParseError as error:
        raise RuntimeError("~/.netrc must be readable only by its owner (chmod 600)") from error
    if not api_key:
        raise RuntimeError("set STASHDB_API_KEY or configure a mode-600 stashdb.org ~/.netrc")
    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        model = connection.execute(
            "SELECT model_id, feature_version FROM model_version WHERE status='published'"
        ).fetchone()
        if not model:
            raise RuntimeError("no published model; run build-model first")
        model_id, version = str(model[0]), str(model[1])
        stash = GraphQLClient(args.stash_url, api_key=os.environ.get("STASH_API_KEY"))
        links = _local_links(stash)
        female_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT performer_id FROM source_performer WHERE gender='FEMALE'"
            )
        }
        links["performers"] = {
            local_id: external_id
            for local_id, external_id in links["performers"].items()
            if local_id in female_ids
        }
        seed_scenes, seed_performers, seed_studios = _seed_ids(
            connection, model_id, links, args.seed_scenes
        )
        seed_tags = _seed_tags(connection, model_id, version)
        if not seed_performers and not seed_studios and not seed_tags:
            raise RuntimeError("no linked taste seeds; add StashDB IDs and sync taxonomy first")
        external = GraphQLClient(args.stashdb_url, api_key=api_key)
        fetched = _fetch_candidates(
            external, seed_performers, seed_studios, seed_tags, args.candidate_limit
        )
        candidates = _dedupe_candidates(fetched, set(links["scenes"].values()))
        if len(candidates) < args.count:
            raise RuntimeError(f"only {len(candidates)} unseen candidates were found")

        affinity_weights: dict[str, float] = {}
        tag_ids = {
            str(item[0]): str(item[1])
            for item in connection.execute(
                """
                SELECT tag_id, stash_id FROM source_tag_stash_id
                WHERE lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))
                """,
                (STASHDB,),
            )
        }
        for row in connection.execute(
            """
            SELECT fd.family, fd.name, fd.metadata_json, fa.affinity * fa.confidence
            FROM feature_affinity fa JOIN feature_definition fd USING(feature_id)
            WHERE fa.model_id=?
            """,
            (model_id,),
        ):
            key = _semantic_key(
                str(row[0]),
                str(row[1]),
                json.loads(row[2]),
                tag_ids,
                links["performers"],
                links["studios"],
            )
            if key:
                affinity_weights[key] = float(row[3])
        external_to_local_tags = {external: local for local, external in tag_ids.items()}
        all_performer_matches = _performer_matches(
            connection,
            version,
            model_id,
            candidates,
            set(links["performers"].values()),
            external_to_local_tags,
        )
        performer_rows = sorted(
            all_performer_matches.values(),
            key=lambda item: (-item["taste"] * item["score"], item["name"]),
        )[: args.count]
        ranked = _score_candidates(
            connection,
            version,
            model_id,
            candidates,
            all_performer_matches,
            affinity_weights,
            external_to_local_tags,
        )[: args.count]
        metrics: dict[str, object] = {
            "model": model_id,
            "linked_seed_scenes": len(seed_scenes),
            "candidate_scenes_fetched": len(fetched),
            "unseen_candidates": len(candidates),
            "mapped_content_tags": len(external_to_local_tags),
            "trusted_performer_matches": len(all_performer_matches),
        }
        targeted = (
            _similar_to(
                connection,
                version,
                args.similar_to,
                candidates,
                set(links["performers"].values()),
                external_to_local_tags,
            )[: args.count]
            if args.similar_to
            else []
        )
        _render(args.output, metrics, ranked, performer_rows, args.similar_to, targeted)
        return {"output": str(args.output.resolve()), **metrics}
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/curator.sqlite3"))
    parser.add_argument(
        "--stash-url",
        default=os.environ.get("STASH_URL"),
        required=not bool(os.environ.get("STASH_URL")),
    )
    parser.add_argument("--stashdb-url", default=os.environ.get("STASHDB_URL", STASHDB))
    parser.add_argument("--output", type=Path, default=Path("reports/stashdb-poc.html"))
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed-scenes", type=int, default=25)
    parser.add_argument("--candidate-limit", type=int, default=1000)
    parser.add_argument("--similar-to", help="Add external matches for a local performer name")
    print(json.dumps(run(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
