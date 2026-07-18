"""Disposable cross-library recommendation evaluation against StashDB."""

# ruff: noqa: E501 - GraphQL and self-contained HTML are clearer unwrapped.

from __future__ import annotations

import argparse
import hashlib
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

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import MaxAbsScaler, normalize

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


def _local_vectors(
    connection: sqlite3.Connection,
    version: str,
    scene_ids: list[str],
    links: dict[str, dict[str, str]],
) -> tuple[list[dict[str, float]], dict[str, str]]:
    connection.execute("DROP TABLE IF EXISTS temp.external_poc_scene")
    connection.execute("CREATE TEMP TABLE external_poc_scene(scene_id TEXT PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO external_poc_scene VALUES (?)", ((item,) for item in scene_ids)
    )
    tag_ids = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT tag_id, stash_id FROM source_tag_stash_id WHERE lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))",
            (STASHDB,),
        )
    }
    names: dict[str, str] = {}
    vectors: dict[str, dict[str, float]] = defaultdict(dict)
    for row in connection.execute(
        """
        SELECT ef.entity_id, fd.family, fd.name, fd.metadata_json,
               ef.value * ef.confidence
        FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
        JOIN external_poc_scene selected ON selected.scene_id=ef.entity_id
        WHERE ef.feature_version=? AND ef.entity_type='scene'
        """,
        (version,),
    ):
        metadata = json.loads(row[3])
        key = _semantic_key(
            str(row[1]),
            str(row[2]),
            metadata,
            tag_ids,
            links["performers"],
            links["studios"],
        )
        if key:
            vectors[str(row[0])][key] = float(row[4])
            names[key] = str(metadata.get("tag_name") or row[2]).replace("_", " ")
    for row in connection.execute(
        """
        SELECT sp.scene_id, fd.family, fd.name, avg(ef.value * ef.confidence)
        FROM scene_performer sp
        JOIN external_poc_scene selected ON selected.scene_id=sp.scene_id
        JOIN source_performer performer ON performer.performer_id=sp.performer_id
        JOIN entity_feature ef ON ef.entity_id=sp.performer_id
        JOIN feature_definition fd USING(feature_id)
        WHERE ef.feature_version=? AND ef.entity_type='performer'
          AND performer.gender='FEMALE'
          AND fd.family LIKE 'profile:%' AND fd.family != 'profile:content'
        GROUP BY sp.scene_id, fd.family, fd.name
        """,
        (version,),
    ):
        key = f"{row[1]}:{row[2]}"
        vectors[str(row[0])][key] = float(row[3])
        names[key] = (
            f"performer {str(row[1]).removeprefix('profile:')}: {str(row[2]).replace('_', ' ')}"
        )
    for local_id, external_id in links["performers"].items():
        row = connection.execute(
            "SELECT name FROM source_performer WHERE performer_id=?", (local_id,)
        ).fetchone()
        if row:
            names[f"performer:{external_id}"] = str(row[0] or local_id)
    for local_id, external_id in links["studios"].items():
        row = connection.execute(
            "SELECT name FROM source_studio WHERE studio_id=?", (local_id,)
        ).fetchone()
        if row:
            names[f"studio:{external_id}"] = str(row[0] or local_id)
    return [vectors[item] for item in scene_ids], names


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


def _matrix(vectors: list[dict[str, float]], keys: list[str]) -> csr_matrix:
    columns = {key: index for index, key in enumerate(keys)}
    rows: list[int] = []
    cols: list[int] = []
    values: list[float] = []
    for row, vector in enumerate(vectors):
        for key, value in vector.items():
            if key in columns and value:
                rows.append(row)
                cols.append(columns[key])
                values.append(value)
    return coo_matrix((values, (rows, cols)), shape=(len(vectors), len(keys))).tocsr()


def _external_profile(identifier: str, values: dict[str, float]) -> PerformerProfile:
    blocks: dict[str, dict[str, ProfileValue]] = defaultdict(dict)
    for key, value in values.items():
        if not key.startswith("profile:"):
            continue
        _, block, name = key.split(":", 2)
        blocks[block][name] = ProfileValue(value, 1.0)
    return PerformerProfile(identifier, dict(blocks))


def _performer_matches(
    connection: sqlite3.Connection,
    version: str,
    model_id: str,
    scenes: list[dict[str, Any]],
    local_external_ids: set[str],
) -> dict[str, dict[str, Any]]:
    profiles = FeatureStore(connection).performer_profiles(version)
    anchor_scores = {
        str(row[0]): float(row[1])
        for row in connection.execute(
            """
            SELECT sp.performer_id, avg(d.direct_appeal * d.confidence)
            FROM scene_performer sp JOIN direct_scene_state d USING(scene_id)
            WHERE d.model_id=? GROUP BY sp.performer_id
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
    anchors = sorted(
        (
            item
            for item in profiles.values()
            if item.performer_id in female_ids and anchor_scores.get(item.performer_id, -1) > 0
        ),
        key=lambda item: -anchor_scores[item.performer_id],
    )[:40]
    names = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT performer_id, name FROM source_performer")
    }
    weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
    weights["content"] = 0.0
    candidates: dict[str, dict[str, Any]] = {}
    for scene in scenes:
        recorded = scene.get("production_date") or scene.get("release_date")
        for appearance in scene.get("performers", []):
            raw = appearance["performer"]
            if not _is_female(raw):
                continue
            identifier = str(raw["id"])
            if identifier in local_external_ids or identifier in candidates:
                continue
            profile = _external_profile(identifier, _profile_features(raw, recorded))
            matches = sorted(
                ((performer_similarity(profile, anchor, weights), anchor) for anchor in anchors),
                key=lambda item: -item[0].similarity,
            )[:3]
            candidates[identifier] = {
                "id": identifier,
                "name": str(raw.get("name") or identifier),
                "image": next(
                    (image["url"] for image in raw.get("images", []) if image.get("url")), ""
                ),
                "score": matches[0][0].similarity if matches else 0.0,
                "matches": [
                    {
                        "name": names.get(anchor.performer_id, anchor.performer_id),
                        "score": result.similarity,
                        "blocks": sorted(
                            result.block_similarities,
                            key=lambda block: (
                                -result.block_weights[block] * result.block_similarities[block]
                            ),
                        )[:4],
                    }
                    for result, anchor in matches
                ],
            }
    return candidates


def _render(
    output: Path,
    metrics: dict[str, object],
    affinity: list[dict[str, Any]],
    latent: list[dict[str, Any]],
    performers: list[dict[str, Any]],
) -> None:
    def scene_cards(rows: list[dict[str, Any]]) -> str:
        cards = []
        for row in rows:
            scene = row["scene"]
            image = next((item["url"] for item in scene.get("images", []) if item.get("url")), "")
            people = ", ".join(item["performer"]["name"] for item in scene.get("performers", []))
            evidence = ", ".join(row["evidence"]) or "limited shared metadata"
            cards.append(f"""<article>{f'<img loading="lazy" src="{html.escape(image, quote=True)}">' if image else ""}
<h3><a href="https://stashdb.org/scenes/{scene["id"]}">{html.escape(scene.get("title") or scene["id"])}</a></h3>
<p class="muted">{html.escape(people)} · {html.escape((scene.get("studio") or {}).get("name", ""))}</p>
<p><b>Score:</b> {row["score"]:+.3f} · <b>Coverage:</b> {row["coverage"]:.0%}</p>
<p><b>Why:</b> {html.escape(evidence)}. It is closest to {html.escape(row["neighbor"])}, which has positive history.</p>
<p class="muted">Candidate source: {html.escape(", ".join(scene["candidate_sources"]))}</p></article>""")
        return "".join(cards)

    performer_cards = "".join(
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
        for row in performers
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
<p>This report compares the same external candidate pool using current feature affinities and a latent taste model. Diversity is intentionally not applied.</p>
<table>{metric_rows}</table><h2>Feature-affinity baseline</h2><div class="grid">{scene_cards(affinity)}</div>
<h2>Latent model</h2><div class="grid">{scene_cards(latent)}</div>
<h2>Similar unseen performers</h2><div class="grid">{performer_cards}</div>""",
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

        raw_labels = [
            (str(row[0]), float(row[1]), float(row[2]))
            for row in connection.execute(
                "SELECT scene_id, direct_appeal, confidence FROM direct_scene_state WHERE model_id=?",
                (model_id,),
            )
        ]
        all_scene_ids = [
            str(row[0]) for row in connection.execute("SELECT scene_id FROM source_scene")
        ]
        labelled = {row[0] for row in raw_labels}
        remaining = sorted(
            (item for item in all_scene_ids if item not in labelled),
            key=lambda item: hashlib.sha256(item.encode()).digest(),
        )
        local_ids = sorted(labelled) + remaining[: max(0, args.max_scenes - len(labelled))]
        local_vectors, names = _local_vectors(connection, version, local_ids, links)
        keys = sorted(set().union(*(vector.keys() for vector in local_vectors)))
        external_vectors = [_external_scene_features(scene, set(keys)) for scene in candidates]
        local_raw, external_raw = _matrix(local_vectors, keys), _matrix(external_vectors, keys)

        scaler = MaxAbsScaler().fit(local_raw)
        tfidf = TfidfTransformer().fit(scaler.transform(local_raw))
        local_matrix = tfidf.transform(scaler.transform(local_raw))
        external_matrix = tfidf.transform(scaler.transform(external_raw))
        dimensions = min(args.dimensions, local_matrix.shape[0] - 1, local_matrix.shape[1] - 1)
        svd = TruncatedSVD(dimensions, random_state=42).fit(local_matrix)
        local_embedding = normalize(svd.transform(local_matrix))
        external_embedding = normalize(svd.transform(external_matrix))
        index = {scene_id: row for row, scene_id in enumerate(local_ids)}
        labels = [
            (index[s], value, confidence) for s, value, confidence in raw_labels if s in index
        ]
        label_rows = np.array([item[0] for item in labels])
        outcomes = np.array([item[1] for item in labels])
        weights = np.array([item[2] for item in labels])
        rng = np.random.default_rng(42)
        order = rng.permutation(len(labels))
        split = max(1, int(len(labels) * 0.8))
        validation = Ridge(alpha=args.alpha).fit(
            local_embedding[label_rows[order[:split]]],
            outcomes[order[:split]],
            sample_weight=weights[order[:split]],
        )
        held_out = validation.predict(local_embedding[label_rows[order[split:]]])
        taste = Ridge(alpha=args.alpha).fit(
            local_embedding[label_rows], outcomes, sample_weight=weights
        )
        latent_scores = taste.predict(external_embedding)

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
        affinity_scores = np.array(
            [
                sum(value * affinity_weights.get(key, 0.0) for key, value in vector.items())
                for vector in external_vectors
            ]
        )
        positive_rows = label_rows[outcomes >= np.quantile(outcomes, 0.75)]
        local_titles = {
            str(row[0]): str(row[1] or row[0])
            for row in connection.execute("SELECT scene_id, title FROM source_scene")
        }
        latent_feature_weights = svd.components_.T @ taste.coef_

        def ranked(scores: np.ndarray, *, latent: bool) -> list[dict[str, Any]]:
            result = []
            for row in np.argsort(-scores)[: args.count]:
                if latent:
                    vector = external_matrix.getrow(int(row))
                    contributions = vector.data * latent_feature_weights[vector.indices]
                    evidence = [
                        names.get(keys[vector.indices[pos]], keys[vector.indices[pos]])
                        for pos in np.argsort(-contributions)[:5]
                        if contributions[pos] > 0
                    ]
                else:
                    contributions = sorted(
                        (
                            (value * affinity_weights.get(key, 0.0), key)
                            for key, value in external_vectors[int(row)].items()
                        ),
                        reverse=True,
                    )
                    evidence = [
                        names.get(key, key) for value, key in contributions[:5] if value > 0
                    ]
                similarities = local_embedding[positive_rows] @ external_embedding[int(row)]
                neighbor_row = int(positive_rows[int(np.argmax(similarities))])
                result.append(
                    {
                        "scene": candidates[int(row)],
                        "score": float(scores[int(row)]),
                        "evidence": evidence,
                        "neighbor": local_titles[local_ids[neighbor_row]],
                        "coverage": min(
                            1.0,
                            len(external_vectors[int(row)])
                            / max(
                                1,
                                len(candidates[int(row)].get("tags", []))
                                + len(candidates[int(row)].get("performers", []))
                                + 1,
                            ),
                        ),
                    }
                )
            return result

        performer_rows = sorted(
            _performer_matches(
                connection, version, model_id, candidates, set(links["performers"].values())
            ).values(),
            key=lambda item: (-item["score"], item["name"]),
        )[: args.count]
        overlap = len(
            {str(item["scene"]["id"]) for item in ranked(affinity_scores, latent=False)}
            & {str(item["scene"]["id"]) for item in ranked(latent_scores, latent=True)}
        )
        metrics: dict[str, object] = {
            "model": model_id,
            "linked_seed_scenes": len(seed_scenes),
            "candidate_scenes_fetched": len(fetched),
            "unseen_candidates": len(candidates),
            "shared_feature_columns": len(keys),
            "top_result_overlap": f"{overlap}/{args.count}",
            "latent_held_out_mae": round(
                float(np.mean(np.abs(outcomes[order[split:]] - held_out))), 4
            ),
            "latent_held_out_spearman": round(
                float(spearmanr(outcomes[order[split:]], held_out).statistic), 4
            ),
        }
        _render(
            args.output,
            metrics,
            ranked(affinity_scores, latent=False),
            ranked(latent_scores, latent=True),
            performer_rows,
        )
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
    parser.add_argument("--max-scenes", type=int, default=6000)
    parser.add_argument("--dimensions", type=int, default=48)
    parser.add_argument("--alpha", type=float, default=10.0)
    print(json.dumps(run(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
