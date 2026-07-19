"""Bounded, locally scored StashDB discovery cache."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from curator.config import DEFAULT_CONFIG
from curator.features import FeatureStore, PerformerProfile, performer_similarity
from curator.features.measurements import CUP_ALIASES, augmentation_category
from curator.features.profiles import ProfileValue
from curator.features.profiles import SimilarityResult as ProfileSimilarityResult
from curator.graphql import GraphQLClient
from curator.model import RecommendationModelStore
from curator.storage import transaction

STASHDB = "https://stashdb.org/graphql"
SCENES = """
query CuratorExpandScenes($input: SceneQueryInput!) {
  queryScenes(input: $input) {
    count
    scenes {
      id title release_date production_date duration
      studio { id name }
      tags { id name }
      images { url width height }
      performers { performer {
        id name gender birth_date ethnicity eye_color hair_color height cup_size band_size
        waist_size hip_size breast_type tattoos { location } piercings { location }
        images { url width height }
      } }
    }
  }
}
"""
PERFORMERS = """
query CuratorSimilarPerformers($input: PerformerQueryInput!) {
  queryPerformers(input: $input) {
    performers {
      id name gender birth_date ethnicity eye_color hair_color height cup_size band_size
      waist_size hip_size breast_type tattoos { location } piercings { location }
      images { url width height }
    }
  }
}
"""


class ExpandService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def refresh(
        self,
        client: GraphQLClient,
        links: dict[str, dict[str, str]],
        *,
        horizon_days: int = 90,
        gender: str = "FEMALE",
        wildcard: bool = False,
        candidate_limit: int = 1_000,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        model_store = RecommendationModelStore(self.connection)
        model_id = model_store.current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        model = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        feature_version = str(model[0])
        seeds = self._seeds(model_id, feature_version, links)
        rows: dict[str, dict[str, Any]] = {}
        sources: dict[str, set[str]] = defaultdict(set)
        filters = (
            ("performers", seeds["performers"]),
            ("studios", seeds["studios"]),
            ("tags", seeds["tags"]),
        )
        active = sum(bool(values) for _, values in filters) + int(wildcard)
        per_source = max(1, math.ceil(candidate_limit / max(1, active)))
        for source, values in filters:
            if values:
                self._fetch(client, rows, sources, source, values, per_source)
        if wildcard:
            self._fetch(client, rows, sources, "wildcard", [], min(100, per_source))
        cutoff = date.today() - timedelta(days=horizon_days)
        owned = set(links["scenes"].values())
        candidates = [
            row
            for identifier, row in rows.items()
            if identifier not in owned
            and self._recent(row, cutoff)
            and self._matches_gender(row, gender)
        ]
        scenes, performers = self._score(candidates, sources, model_id, feature_version, links)
        fetched_at_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        with transaction(self.connection):
            self.connection.execute("DELETE FROM external_entity")
            self.connection.executemany(
                """
                INSERT INTO external_entity(
                  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        kind,
                        str(item["id"]),
                        json.dumps(item["payload"], separators=(",", ":")),
                        item["score"],
                        json.dumps(item["sources"], separators=(",", ":")),
                        fetched_at_ms,
                    )
                    for kind, items in (("scene", scenes), ("performer", performers))
                    for item in items
                ),
            )
            self.connection.execute(
                """
                INSERT INTO expand_cache(
                  singleton, model_id, fetched_at_ms, expires_at_ms, scene_count, performer_count
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET model_id=excluded.model_id,
                  fetched_at_ms=excluded.fetched_at_ms, expires_at_ms=excluded.expires_at_ms,
                  scene_count=excluded.scene_count, performer_count=excluded.performer_count
                """,
                (
                    model_id,
                    fetched_at_ms,
                    fetched_at_ms + 12 * 3_600_000,
                    len(scenes),
                    len(performers),
                ),
            )
        return {"scene_count": len(scenes), "performer_count": len(performers)}

    def results(
        self,
        entity_type: str,
        *,
        sort: str = "match",
        performer_id: str | None = None,
        favorite_only: bool = False,
        gender: str = "FEMALE",
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_query: str = "",
        studio_query: str = "",
        performer_names: tuple[str, ...] = (),
        studio_names: tuple[str, ...] = (),
        count: int = 50,
    ) -> dict[str, object]:
        if entity_type not in {"scene", "performer"} or sort not in {"match", "newest"}:
            raise ValueError("invalid Expand query")
        cache = self.connection.execute("SELECT * FROM expand_cache WHERE singleton=1").fetchone()
        if cache is None:
            return {"ready": False, "items": []}
        shortlisted = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT external_id FROM external_shortlist WHERE entity_type=?",
                (entity_type,),
            )
        }
        rows = []
        for row in self.connection.execute(
            "SELECT * FROM external_entity WHERE entity_type=?", (entity_type,)
        ):
            payload = json.loads(row["payload_json"])
            if (
                performer_id
                and entity_type == "scene"
                and performer_id
                not in {str(item["performer"]["id"]) for item in payload.get("performers", [])}
            ):
                continue
            if (
                favorite_only
                and entity_type == "scene"
                and not any(
                    item.get("performer", {}).get("curator_local", {}).get("favorite")
                    for item in payload.get("performers", [])
                )
            ):
                continue
            if gender and not self._payload_matches_gender(payload, entity_type, gender):
                continue
            if entity_type == "scene":
                tags = {str(item.get("name") or "").casefold() for item in payload.get("tags", [])}
                if include_tags and not all(value.casefold() in tags for value in include_tags):
                    continue
                if exclude_tags and any(value.casefold() in tags for value in exclude_tags):
                    continue
                if performer_query and performer_query.casefold() not in " ".join(
                    str(item.get("performer", {}).get("name") or "").casefold()
                    for item in payload.get("performers", [])
                ):
                    continue
                cast_names = {
                    str(item.get("performer", {}).get("name") or "").casefold()
                    for item in payload.get("performers", [])
                }
                if performer_names and not all(
                    value.casefold() in cast_names for value in performer_names
                ):
                    continue
                if (
                    studio_query
                    and studio_query.casefold()
                    not in str((payload.get("studio") or {}).get("name") or "").casefold()
                ):
                    continue
                if studio_names and str(
                    (payload.get("studio") or {}).get("name") or ""
                ).casefold() not in {value.casefold() for value in studio_names}:
                    continue
            rows.append(
                {
                    "id": str(row["external_id"]),
                    "score": float(row["score"]),
                    "sources": json.loads(row["sources_json"]),
                    "payload": payload,
                    "shortlisted": str(row["external_id"]) in shortlisted,
                }
            )
        if sort == "newest" and entity_type == "scene":
            rows.sort(
                key=lambda item: (str(item["payload"].get("release_date") or ""), item["score"]),
                reverse=True,
            )
        else:
            rows.sort(key=lambda item: (-item["score"], item["id"]))
            if entity_type == "scene":
                rows = self._diverse_scenes(rows)
        return {
            "ready": True,
            "fetched_at_ms": int(cache["fetched_at_ms"]),
            "expires_at_ms": int(cache["expires_at_ms"]),
            "items": rows[:count],
        }

    @staticmethod
    def _diverse_scenes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        remaining = rows[:]
        while remaining:
            previous = (
                {
                    str(item["performer"]["id"])
                    for item in selected[-1]["payload"].get("performers", [])
                }
                if selected
                else set()
            )
            index = next(
                (
                    i
                    for i, row in enumerate(remaining)
                    if not previous
                    & {
                        str(item["performer"]["id"])
                        for item in row["payload"].get("performers", [])
                    }
                ),
                0,
            )
            selected.append(remaining.pop(index))
        return selected

    def shortlist(self, entity_type: str, external_id: str, selected: bool) -> None:
        if entity_type not in {"scene", "performer"}:
            raise ValueError("invalid shortlist entity type")
        with transaction(self.connection):
            if not selected:
                self.connection.execute(
                    "DELETE FROM external_shortlist WHERE entity_type=? AND external_id=?",
                    (entity_type, external_id),
                )
                return
            row = self.connection.execute(
                "SELECT * FROM external_entity WHERE entity_type=? AND external_id=?",
                (entity_type, external_id),
            ).fetchone()
            if row is None:
                raise ValueError("external entity is not in the current Expand cache")
            self.connection.execute(
                """
                INSERT INTO external_shortlist(
                  entity_type, external_id, payload_json, score, sources_json, added_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, external_id) DO UPDATE SET
                  payload_json=excluded.payload_json, score=excluded.score,
                  sources_json=excluded.sources_json
                """,
                (
                    entity_type,
                    external_id,
                    row["payload_json"],
                    row["score"],
                    row["sources_json"],
                    time.time_ns() // 1_000_000,
                ),
            )

    def shortlist_results(self) -> dict[str, object]:
        items = [
            {
                "entity_type": str(row["entity_type"]),
                "id": str(row["external_id"]),
                "score": float(row["score"]),
                "sources": json.loads(row["sources_json"]),
                "payload": json.loads(row["payload_json"]),
                "shortlisted": True,
                "added_at_ms": int(row["added_at_ms"]),
            }
            for row in self.connection.execute(
                "SELECT * FROM external_shortlist ORDER BY added_at_ms DESC"
            )
        ]
        return {"ready": True, "items": items}

    def similar(
        self,
        entity_type: str,
        entity_id: str,
        count: int = 50,
        *,
        candidate_ids: set[str] | None = None,
    ) -> dict[str, object]:
        shortlisted = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT external_id FROM external_shortlist WHERE entity_type=?", (entity_type,)
            )
        }
        if entity_type == "scene":
            target_tags = self._external_content(entity_id)
            target_performers = [
                str(row[0])
                for row in self.connection.execute(
                    "SELECT performer_id FROM scene_performer WHERE scene_id=?", (entity_id,)
                )
            ]
            feature_version = FeatureStore(self.connection).current_version()
            profiles = (
                FeatureStore(self.connection).performer_profiles(feature_version)
                if feature_version
                else {}
            )
            targets = [profiles[value] for value in target_performers if value in profiles]
            weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
            items = []
            for row in self.connection.execute(
                "SELECT * FROM external_entity WHERE entity_type='scene'"
            ):
                if candidate_ids is not None and str(row["external_id"]) not in candidate_ids:
                    continue
                payload = json.loads(row["payload_json"])
                tags = {
                    key: str(tag["name"])
                    for tag in payload.get("tags", [])
                    for key in (
                        f"id:{tag['id']}",
                        f"name:{str(tag['name']).casefold()}",
                    )
                }
                shared = set(target_tags) & set(tags)
                content = (
                    sum(target_tags[value] for value in shared)
                    / sum(target_tags.values())
                    * (1 - math.exp(-len(shared) / 2))
                    if target_tags
                    else 0.0
                )
                performer = max(
                    (
                        self._profile_match(
                            self._profile(
                                item["performer"],
                                payload.get("production_date") or payload.get("release_date"),
                            ),
                            target,
                            weights,
                        )[0]
                        for item in payload.get("performers", [])
                        for target in targets
                    ),
                    default=0,
                )
                similarity = (0.85 * content + 0.15 * performer) if target_tags else performer
                if similarity < 0.15 or (target_tags and not shared):
                    continue
                appeal = max(0.0, min(1.0, (float(row["score"]) + 1) / 2))
                items.append(
                    {
                        "id": str(row["external_id"]),
                        "entity_type": "scene",
                        "similarity": similarity,
                        "score": 0.7 * similarity + 0.3 * appeal,
                        "sources": json.loads(row["sources_json"]),
                        "shortlisted": str(row["external_id"]) in shortlisted,
                        "payload": {
                            **payload,
                            "why": [
                                (
                                    f"Shares {', '.join(tags[value] for value in sorted(shared))}"
                                    if shared
                                    else "Similar performer profile"
                                )
                            ],
                        },
                    }
                )
        elif entity_type == "performer":
            feature_version = FeatureStore(self.connection).current_version()
            target = (
                FeatureStore(self.connection).performer_profiles(feature_version).get(entity_id)
                if feature_version
                else None
            )
            if target is None:
                raise ValueError(f"unknown performer: {entity_id}")
            birthdate = self.connection.execute(
                "SELECT birthdate FROM source_performer WHERE performer_id=?", (entity_id,)
            ).fetchone()
            target = self._with_age(target, birthdate[0] if birthdate else None)
            weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
            items = []
            for row in self.connection.execute(
                "SELECT * FROM external_entity WHERE entity_type='performer'"
            ):
                if candidate_ids is not None and str(row["external_id"]) not in candidate_ids:
                    continue
                payload = json.loads(row["payload_json"])
                candidate = self._profile(payload)
                similarity, match, coverage = self._profile_match(candidate, target, weights)
                if similarity < 0.25 or coverage < 0.25:
                    continue
                appeal = max(0.0, min(1.0, (float(row["score"]) + 1) / 2))
                blocks = sorted(
                    match.block_similarities,
                    key=lambda block: -match.block_similarities[block] * match.block_weights[block],
                )[:3]
                conflicts = self._profile_conflicts(candidate, target)
                items.append(
                    {
                        "id": str(row["external_id"]),
                        "entity_type": "performer",
                        "similarity": similarity,
                        "score": 0.7 * similarity + 0.3 * appeal,
                        "sources": json.loads(row["sources_json"]),
                        "shortlisted": str(row["external_id"]) in shortlisted,
                        "payload": {
                            **payload,
                            "why": [
                                "Closest on "
                                + ", ".join(
                                    block.replace("augmentation", "breast type") for block in blocks
                                )
                            ]
                            + (["Differs in " + ", ".join(conflicts)] if conflicts else []),
                        },
                    }
                )
        else:
            raise ValueError("invalid external similarity entity type")
        items.sort(key=lambda item: (-item["score"], item["id"]))
        return {"ready": bool(items), "items": items[:count]}

    def targeted_similar(
        self,
        client: GraphQLClient,
        links: dict[str, dict[str, str]],
        entity_type: str,
        entity_id: str,
        *,
        gender: str = "FEMALE",
        count: int = 50,
    ) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        feature_version = FeatureStore(self.connection).current_version()
        if model_id is None or feature_version is None:
            raise RuntimeError("no published model")
        candidate_ids: set[str]
        if entity_type == "scene":
            rows: dict[str, dict[str, Any]] = {}
            sources: dict[str, set[str]] = defaultdict(set)
            content = self._external_content(entity_id)
            performers = [
                links["performers"][str(row[0])]
                for row in self.connection.execute(
                    "SELECT performer_id FROM scene_performer WHERE scene_id=?", (entity_id,)
                )
                if str(row[0]) in links["performers"]
            ]
            if content:
                tag_ids = sorted(content, key=content.__getitem__, reverse=True)[:20]
                self._fetch(client, rows, sources, "tags", tag_ids, 500)
            if performers:
                self._fetch(client, rows, sources, "performers", performers, 250)
            candidates = [
                value
                for key, value in rows.items()
                if key not in set(links["scenes"].values()) and self._matches_gender(value, gender)
            ]
            candidate_ids = {str(value["id"]) for value in candidates}
            scenes, _ = self._score(candidates, sources, model_id, feature_version, links)
            self._merge_external("scene", scenes)
        elif entity_type == "performer":
            target_row = self.connection.execute(
                "SELECT gender, ethnicity FROM source_performer WHERE performer_id=?",
                (entity_id,),
            ).fetchone()
            if target_row is None:
                raise ValueError(f"unknown performer: {entity_id}")
            query: dict[str, object] = {
                "page": 1,
                "per_page": 500,
                "sort": "POPULARITY",
                "direction": "DESC",
            }
            selected_gender = gender or str(target_row["gender"] or "")
            if selected_gender:
                query["gender"] = selected_gender
            ethnicity = str(target_row["ethnicity"] or "").upper().replace(" ", "_")
            if ethnicity in {
                "CAUCASIAN",
                "BLACK",
                "ASIAN",
                "INDIAN",
                "LATIN",
                "MIDDLE_EASTERN",
                "MIXED",
                "OTHER",
            }:
                query["ethnicity"] = ethnicity
            candidates = client.execute(PERFORMERS, {"input": query})["queryPerformers"][
                "performers"
            ]
            owned = set(links["performers"].values())
            candidate_ids = {
                str(payload["id"]) for payload in candidates if str(payload["id"]) not in owned
            }
            self._merge_external(
                "performer",
                (
                    {
                        "id": str(payload["id"]),
                        "payload": payload,
                        "score": 0.0,
                        "sources": ["similar"],
                    }
                    for payload in candidates
                    if str(payload["id"]) not in owned
                ),
            )
        else:
            raise ValueError("invalid external similarity entity type")
        result = self.similar(entity_type, entity_id, count=count * 2, candidate_ids=candidate_ids)
        raw_items = result["items"]
        assert isinstance(raw_items, list)
        result["items"] = [
            item
            for item in raw_items
            if not gender or self._payload_matches_gender(item["payload"], entity_type, gender)
        ][:count]
        result["ready"] = bool(result["items"])
        return result

    def _merge_external(self, entity_type: str, items: Iterable[dict[str, Any]]) -> None:
        now_ms = time.time_ns() // 1_000_000
        with transaction(self.connection):
            self.connection.executemany(
                """
                INSERT INTO external_entity(
                  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, external_id) DO UPDATE SET
                  payload_json=excluded.payload_json, score=excluded.score,
                  sources_json=excluded.sources_json, fetched_at_ms=excluded.fetched_at_ms
                """,
                (
                    (
                        entity_type,
                        str(item["id"]),
                        json.dumps(item["payload"], separators=(",", ":")),
                        float(item["score"]),
                        json.dumps(item["sources"], separators=(",", ":")),
                        now_ms,
                    )
                    for item in items
                ),
            )

    def _external_content(self, scene_id: str) -> dict[str, float]:
        feature_version = FeatureStore(self.connection).current_version()
        if not feature_version:
            return {}
        vector = (
            FeatureStore(self.connection)
            .scene_content_vectors(feature_version, [scene_id])
            .get(scene_id, {})
        )
        external = {
            str(row["tag_id"]): (
                f"id:{row['stash_id']}"
                if row["stash_id"]
                else f"name:{str(row['name']).casefold()}"
            )
            for row in self.connection.execute(
                """
                SELECT t.tag_id, t.name, ids.stash_id FROM source_tag t
                LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
                  AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
                """,
                (STASHDB,),
            )
        }
        return {
            external[name.removeprefix("tag:")]: value
            for name, value in vector.items()
            if name.removeprefix("tag:") in external
        }

    def _seeds(
        self, model_id: str, feature_version: str, links: dict[str, dict[str, str]]
    ) -> dict[str, list[str]]:
        top = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT scene_id FROM model_scene_score WHERE model_id=?
                ORDER BY appeal * confidence DESC LIMIT 100
                """,
                (model_id,),
            )
        ]
        evidence = self._performer_evidence(model_id, links)
        performers = [
            external_id
            for external_id, item in sorted(
                evidence.items(), key=lambda value: (-float(value[1]["strength"]), value[0])
            )
            if float(item["strength"]) > 0
        ]
        studios = {
            links["studios"][str(row[0])]
            for row in self.connection.execute(
                f"SELECT DISTINCT studio_id FROM source_scene WHERE scene_id IN "
                f"({','.join('?' for _ in top)}) AND studio_id IS NOT NULL",
                top,
            )
            if str(row[0]) in links["studios"]
        }
        tags = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT ids.stash_id FROM feature_affinity a
                JOIN feature_definition d USING(feature_id)
                JOIN source_tag_stash_id ids ON d.name='tag:' || ids.tag_id
                WHERE a.model_id=? AND d.feature_version=? AND d.family='content'
                  AND a.affinity > 0 AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
                ORDER BY a.affinity * a.confidence DESC LIMIT 20
                """,
                (model_id, feature_version, STASHDB),
            )
        ]
        return {
            "performers": performers[:50],
            "studios": sorted(studios)[:30],
            "tags": tags,
        }

    @staticmethod
    def _fetch(
        client: GraphQLClient,
        rows: dict[str, dict[str, Any]],
        sources: dict[str, set[str]],
        source: str,
        values: list[str],
        limit: int,
    ) -> None:
        fetched = 0
        page = 1
        while fetched < limit:
            page_size = min(250, limit - fetched)
            query: dict[str, object] = {
                "page": page,
                "per_page": page_size,
                "sort": "DATE" if source != "wildcard" else "TRENDING",
                "direction": "DESC",
            }
            if source != "wildcard":
                query[source] = {"value": values, "modifier": "INCLUDES"}
            data = client.execute(SCENES, {"input": query})["queryScenes"]
            batch = data["scenes"]
            for scene in batch:
                identifier = str(scene["id"])
                rows.setdefault(identifier, scene)
                sources[identifier].add(source)
            fetched += len(batch)
            if not batch or fetched >= int(data["count"]):
                break
            page += 1

    @staticmethod
    def _recent(scene: dict[str, Any], cutoff: date) -> bool:
        raw = scene.get("release_date") or scene.get("production_date")
        if not raw:
            return True
        try:
            return date.fromisoformat(str(raw)) >= cutoff
        except ValueError:
            return True

    @staticmethod
    def _matches_gender(scene: dict[str, Any], gender: str) -> bool:
        if not gender:
            return True
        return any(
            str(item.get("performer", {}).get("gender") or "").casefold() == gender.casefold()
            for item in scene.get("performers", [])
        )

    @staticmethod
    def _payload_matches_gender(payload: dict[str, Any], entity_type: str, gender: str) -> bool:
        if entity_type == "performer":
            return str(payload.get("gender") or "").casefold() == gender.casefold()
        return ExpandService._matches_gender(payload, gender)

    def _score(
        self,
        scenes: list[dict[str, Any]],
        sources: dict[str, set[str]],
        model_id: str,
        feature_version: str,
        links: dict[str, dict[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tag_affinity: dict[str, float] = {}
        for row in self.connection.execute(
            """
            SELECT ids.stash_id, t.name, a.affinity * a.confidence AS value
            FROM feature_affinity a JOIN feature_definition d USING(feature_id)
            JOIN source_tag t ON d.name='tag:' || t.tag_id
            LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
              AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
            WHERE a.model_id=? AND d.feature_version=? AND d.family='content'
            """,
            (STASHDB, model_id, feature_version),
        ):
            value = float(row["value"])
            tag_affinity[f"name:{str(row['name']).casefold()}"] = value
            if row["stash_id"]:
                tag_affinity[f"id:{row['stash_id']}"] = value
        external_studio_appeal = {
            links["studios"][str(row["studio_id"])]: float(row["appeal"])
            for row in self.connection.execute(
                """
                SELECT s.studio_id, AVG(m.appeal) AS appeal
                FROM source_scene s JOIN model_scene_score m USING(scene_id)
                WHERE m.model_id=? AND s.studio_id IS NOT NULL GROUP BY s.studio_id
                """,
                (model_id,),
            )
            if str(row["studio_id"]) in links["studios"]
        }
        profiles = FeatureStore(self.connection).performer_profiles(feature_version)
        evidence = self._performer_evidence(model_id, links)
        evidence_by_local = {str(item["local_id"]): item for item in evidence.values()}
        anchors = [
            (profiles[key], item)
            for key, item in evidence_by_local.items()
            if key in profiles and float(item["strength"]) > 0
        ]
        weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
        performer_rows: dict[str, dict[str, Any]] = {}
        scene_rows = []
        for scene in scenes:
            tag_value = math.tanh(
                sum(self._tag_value(tag, tag_affinity) for tag in scene.get("tags", []))
            )
            cast = [item["performer"] for item in scene.get("performers", [])]
            identity_evidence = max(
                (evidence.get(str(item["id"]), {}) for item in cast),
                default={},
                key=lambda item: float(item.get("strength", 0)),
            )
            identity = float(identity_evidence.get("strength", 0))
            studio = scene.get("studio") or {}
            studio_value = external_studio_appeal.get(str(studio.get("id") or ""), 0)
            similarity_value = 0.0
            for performer in cast:
                external_id = str(performer["id"])
                local = evidence.get(external_id)
                profile = self._profile(
                    performer, scene.get("production_date") or scene.get("release_date")
                )
                matches = (
                    [
                        (*self._profile_match(profile, anchor, weights), anchor_evidence)
                        for anchor, anchor_evidence in anchors
                    ]
                    if local is None
                    else []
                )
                match = max(matches, key=lambda item: item[0]) if matches else None
                strength = float(match[3].get("strength", 0)) if match else 0.0
                similarity_value = max(similarity_value, (match[0] if match else 0.0) * strength)
                performer_payload = {**performer}
                if local:
                    performer_payload["curator_local"] = {
                        "id": local["local_id"],
                        "favorite": local["favorite"],
                        "play_count": local["play_count"],
                    }
                if match and match[0] > 0:
                    blocks = sorted(
                        match[1].block_similarities,
                        key=lambda block: (
                            -match[1].block_similarities[block] * match[1].block_weights[block]
                        ),
                    )[:3]
                    attributes = ", ".join(
                        block.replace("augmentation", "breast type") for block in blocks
                    )
                    performer_payload["why"] = [
                        f"Similar to {match[3].get('name', 'a performer you enjoy')}"
                        f" in {attributes}"
                    ]
                performer_rows.setdefault(
                    external_id,
                    {
                        "id": external_id,
                        "payload": performer_payload,
                        "score": 0.0,
                        "sources": set(),
                    },
                )
                performer_rows[external_id]["score"] = max(
                    performer_rows[external_id]["score"],
                    (match[0] if match else 0.0) * (0.7 + 0.3 * strength),
                )
                performer_rows[external_id]["sources"].update(sources[str(scene["id"])])
            score = (
                0.45 * tag_value + 0.25 * identity + 0.10 * studio_value + 0.20 * similarity_value
            )
            payload = {
                **scene,
                "performers": [
                    {"performer": performer_rows[str(item["id"])]["payload"]} for item in cast
                ],
                "why": self._why(scene, tag_affinity, identity, similarity_value),
            }
            scene_rows.append(
                {
                    "id": str(scene["id"]),
                    "payload": payload,
                    "score": score,
                    "sources": sorted(sources[str(scene["id"])]),
                }
            )
        owned_performers = set(links["performers"].values())
        performers = [
            {**item, "sources": sorted(item["sources"])}
            for identifier, item in performer_rows.items()
            if identifier not in owned_performers
        ]
        return scene_rows, performers

    def _performer_evidence(
        self, model_id: str, links: dict[str, dict[str, str]]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in self.connection.execute(
            """
            SELECT p.performer_id, p.name, p.favorite,
              COALESCE(SUM(s.play_count), 0) AS play_count,
              COALESCE(SUM(CASE WHEN s.play_count > 0 THEN m.appeal * s.play_count END)
                / NULLIF(SUM(CASE WHEN s.play_count > 0 THEN s.play_count END), 0), 0)
                AS observed_appeal
            FROM source_performer p
            LEFT JOIN scene_performer sp USING(performer_id)
            LEFT JOIN source_scene s USING(scene_id)
            LEFT JOIN model_scene_score m ON m.scene_id=s.scene_id AND m.model_id=?
            GROUP BY p.performer_id
            """,
            (model_id,),
        ):
            local_id = str(row["performer_id"])
            external_id = links["performers"].get(local_id)
            if not external_id:
                continue
            plays = int(row["play_count"])
            observed_appeal = float(row["observed_appeal"])
            strength = min(
                1.0,
                (0.55 if row["favorite"] else 0.0)
                + min(0.35, 0.12 * math.log1p(plays))
                * max(0.0, min(1.0, (observed_appeal + 1) / 2))
                + 0.10 * max(0.0, observed_appeal),
            )
            result[external_id] = {
                "local_id": local_id,
                "name": str(row["name"] or local_id),
                "favorite": bool(row["favorite"]),
                "play_count": plays,
                "strength": strength,
            }
        return result

    @staticmethod
    def _profile_match(
        left: PerformerProfile, right: PerformerProfile, weights: dict[str, float]
    ) -> tuple[float, ProfileSimilarityResult, float]:
        match = performer_similarity(left, right, weights)
        relevant = sum(value for key, value in weights.items() if key != "content")
        coverage = min(1.0, sum(match.block_weights.values()) / relevant) if relevant else 0.0
        return match.similarity * math.sqrt(coverage), match, coverage

    @staticmethod
    def _profile_conflicts(left: PerformerProfile, right: PerformerProfile) -> list[str]:
        conflicts: list[str] = []
        left_cup = left.blocks.get("measurements", {}).get("cup_index")
        right_cup = right.blocks.get("measurements", {}).get("cup_index")
        if left_cup and right_cup and abs(left_cup.value - right_cup.value) >= 2:
            conflicts.append("cup size")
        left_aug = set(left.blocks.get("augmentation", {}))
        right_aug = set(right.blocks.get("augmentation", {}))
        if left_aug and right_aug and not left_aug & right_aug:
            conflicts.append("augmentation")
        left_age = left.blocks.get("age", {}).get("age_recording")
        right_age = right.blocks.get("age", {}).get("age_recording")
        if left_age and right_age and abs(left_age.value - right_age.value) >= 12:
            conflicts.append("age")
        return conflicts

    @staticmethod
    def _age(value: object, recorded: object = None) -> float | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parts = [int(part) for part in raw.split("-")]
            born = date(
                parts[0], parts[1] if len(parts) > 1 else 7, parts[2] if len(parts) > 2 else 1
            )
            reference = date.fromisoformat(str(recorded)) if recorded else date.today()
        except (ValueError, IndexError):
            return None
        return max(0.0, (reference - born).days / 365.2425)

    @staticmethod
    def _with_age(profile: PerformerProfile, birthdate: object) -> PerformerProfile:
        age = ExpandService._age(birthdate)
        if age is None:
            return profile
        blocks = {name: dict(values) for name, values in profile.blocks.items()}
        blocks["age"] = {"age_recording": ProfileValue(age, 0.9)}
        return PerformerProfile(profile.performer_id, blocks)

    @staticmethod
    def _profile(raw: dict[str, Any], recorded: object = None) -> PerformerProfile:
        blocks: dict[str, dict[str, ProfileValue]] = defaultdict(dict)
        for block, prefix, field, confidence in (
            ("ethnicity", "ethnicity", "ethnicity", 0.9),
            ("hair", "hair", "hair_color", 0.65),
            ("eyes", "eye", "eye_color", 0.9),
        ):
            if raw.get(field):
                blocks[block][f"{prefix}:{str(raw[field]).casefold()}"] = ProfileValue(
                    1, confidence
                )
        numeric = {
            "band_inches": raw.get("band_size"),
            "waist_inches": raw.get("waist_size"),
            "hip_inches": raw.get("hip_size"),
        }
        cup = CUP_ALIASES.get(str(raw.get("cup_size") or "").upper())
        if cup:
            numeric["cup_index"] = cup[0]
        if numeric["waist_inches"] and numeric["hip_inches"]:
            numeric["waist_to_hip"] = float(numeric["waist_inches"]) / float(numeric["hip_inches"])
        for name, value in numeric.items():
            if value is not None:
                blocks["measurements"][name] = ProfileValue(float(value), 1)
        if raw.get("height"):
            blocks["height"]["height_cm"] = ProfileValue(float(raw["height"]), 1)
        if (age := ExpandService._age(raw.get("birth_date"), recorded)) is not None:
            blocks["age"]["age_recording"] = ProfileValue(age, 0.9)
        if augmentation := augmentation_category(str(raw.get("breast_type") or "")):
            blocks["augmentation"][augmentation] = ProfileValue(1, 1)
        if raw.get("tattoos"):
            blocks["tattoos"]["present"] = ProfileValue(1, 0.8)
        if raw.get("piercings"):
            blocks["piercings"]["present"] = ProfileValue(1, 0.8)
        return PerformerProfile(str(raw["id"]), dict(blocks))

    @staticmethod
    def _tag_value(tag: dict[str, Any], affinities: dict[str, float]) -> float:
        return affinities.get(
            f"id:{tag.get('id')}",
            affinities.get(f"name:{str(tag.get('name') or '').casefold()}", 0.0),
        )

    @staticmethod
    def _why(
        scene: dict[str, Any], tag_affinity: dict[str, float], identity: float, similarity: float
    ) -> list[str]:
        tags = sorted(
            (
                (ExpandService._tag_value(tag, tag_affinity), str(tag["name"]))
                for tag in scene.get("tags", [])
                if ExpandService._tag_value(tag, tag_affinity) > 0
            ),
            reverse=True,
        )[:3]
        reasons = [name for _, name in tags]
        if identity > 0:
            reasons.append("a performer you already enjoy")
        elif similarity > 0:
            reasons.append("a performer close to your preferences")
        return reasons
