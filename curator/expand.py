"""Bounded, locally scored StashDB discovery cache."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from curator.config import DEFAULT_CONFIG
from curator.features import FeatureStore, PerformerProfile, performer_similarity
from curator.features.measurements import CUP_ALIASES, augmentation_category
from curator.features.profiles import (
    ProfileValue,
    block_similarities,
    block_similarity,
    combine_similarities,
    similarity_penalty,
)
from curator.features.profiles import SimilarityResult as ProfileSimilarityResult
from curator.graphql import GraphQLClient, GraphQLError
from curator.model import ModelUpdateCoordinator, RecommendationModelStore
from curator.model.builder import LINKED_PERFORMERS
from curator.model.multi_hop import MultiHopAffinity
from curator.profiling import record_duration
from curator.storage import transaction
from curator.taxonomy import (
    StashDBTaxonomyClient,
    TaxonomyIndex,
    TaxonomyStore,
    equivalent_tag_names,
)
from curator.theporndb import is_theporndb

STASHDB = "https://stashdb.org/graphql"
# Incremental Expand refresh state (mirrors core/expand_incremental.go). StashDB has no
# updated_at scene filter, but it sorts by UPDATED_AT, so an incremental refresh walks
# each seed probe newest-update-first and stops at the previous refresh. Seeds outside
# the last refresh still get the full sample, and a weekly full fetch renews the
# popularity sample a watermark cannot see. The look-alike chase is reused for a week
# while its inputs stay the same.
EXPAND_SEED_STATE_KEY = "expand_seed_state"
EXPAND_LOOKALIKE_KEY = "expand_lookalike_cache"
EXPAND_FULL_FETCH_INTERVAL_MS = 7 * 24 * 3_600_000
# Re-read an hour before the previous refresh so StashDB/host clock skew cannot drop
# an update.
EXPAND_WATERMARK_SLACK_MS = 3_600_000
EXPAND_LOOKALIKE_TTL_MS = 7 * 24 * 3_600_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
PERFORMER_HUNT_LIMIT = 1_000
EXTERNAL_DISMISSAL_KINDS = frozenset({"not_interested", "not_now"})
# A StashDB performer the user is not into counts in Find like a local
# performer with this (negative) identity strength.
DISLIKED_PERFORMER_STRENGTH = 0.5


SCENES = """
query CuratorExpandScenes($input: SceneQueryInput!) {
  queryScenes(input: $input) {
    count
    scenes {
      id title release_date production_date duration details updated
      studio { id name images { url width height } }
      tags { id name }
      images { url width height }
      fingerprints { hash algorithm duration }
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
      waist_size hip_size breast_type scene_count tattoos { location } piercings { location }
      images { url width height }
    }
  }
}
"""

PERFORMER_SEARCH = """
query CuratorPerformerSearch($input: PerformerQueryInput!) {
  queryPerformers(input: $input) {
    performers {
      id name aliases disambiguation scene_count
      images { url width height }
    }
  }
}
"""


def normalize_phash(value: object) -> str | None:
    normalized = str(value or "").strip().casefold()
    if len(normalized) != 16:
        return None
    try:
        int(normalized, 16)
    except ValueError:
        return None
    return normalized


@dataclass(frozen=True)
class _AnchorTerms:
    """One anchor comparison with everything that does not vary by scene already measured."""

    anchor: PerformerProfile
    evidence: dict[str, Any]
    similarities: dict[str, float]
    weights: dict[str, float]
    numerator: float
    denominator: float
    penalty: float


class _AnchorMatcher:
    """Match external performers against local anchors, reusing work across their scenes.

    A performer appears in many of the scenes a hunt returns, and only their age at recording
    differs between those appearances. Measuring every block for every appearance repeats the
    same comparisons hundreds of times, so the scene-independent blocks are measured once per
    performer and combined with a fresh age term for each scene.
    """

    def __init__(
        self,
        anchors: list[tuple[PerformerProfile, dict[str, Any]]],
        weights: dict[str, float],
    ) -> None:
        self.anchors = anchors
        self.weights = weights
        self.age_weight = weights.get("age", 0.0)
        self.relevant = sum(value for key, value in weights.items() if key != "content")
        self._terms: dict[str, tuple[_AnchorTerms, ...]] = {}

    def _timeless(self, performer: dict[str, Any]) -> tuple[_AnchorTerms, ...]:
        external_id = str(performer["id"])
        cached = self._terms.get(external_id)
        if cached is not None:
            return cached
        profile = ExpandService._profile(performer)
        undated = PerformerProfile(
            profile.performer_id,
            {block: values for block, values in profile.blocks.items() if block != "age"},
        )
        terms = []
        for anchor, evidence in self.anchors:
            similarities, used = block_similarities(undated, anchor, self.weights)
            terms.append(
                _AnchorTerms(
                    anchor,
                    evidence,
                    similarities,
                    used,
                    sum(similarities[block] * used[block] for block in similarities),
                    sum(used.values()),
                    similarity_penalty(undated, anchor),
                )
            )
        self._terms[external_id] = tuple(terms)
        return self._terms[external_id]

    def best(
        self, performer: dict[str, Any], recorded: object
    ) -> tuple[float, ProfileSimilarityResult, float, dict[str, Any]] | None:
        terms = self._timeless(performer)
        if not terms:
            return None
        profile = ExpandService._profile(performer, recorded)
        chosen: _AnchorTerms | None = None
        chosen_age: float | None = None
        best_value = -1.0
        for term in terms:
            age = block_similarity(profile, term.anchor, "age") if self.age_weight > 0 else None
            numerator = term.numerator + (age * self.age_weight if age is not None else 0.0)
            denominator = term.denominator + (self.age_weight if age is not None else 0.0)
            similarity = (numerator / denominator if denominator else 0.0) * term.penalty
            coverage = min(1.0, denominator / self.relevant) if self.relevant else 0.0
            value = similarity * math.sqrt(coverage)
            if value > best_value:
                best_value, chosen, chosen_age = value, term, age
        if chosen is None:
            return None
        similarities = dict(chosen.similarities)
        weights = dict(chosen.weights)
        if chosen_age is not None:
            similarities["age"] = chosen_age
            weights["age"] = self.age_weight
        result = combine_similarities(profile, chosen.anchor, similarities, weights)
        coverage = min(1.0, sum(weights.values()) / self.relevant) if self.relevant else 0.0
        return result.similarity * math.sqrt(coverage), result, coverage, chosen.evidence


class ExpandService:
    def __init__(self, connection: sqlite3.Connection, stashbox_endpoint: str = STASHDB) -> None:
        self.connection = connection
        self.stashbox_endpoint = stashbox_endpoint

    def _cached_endpoint(self, key: str) -> str:
        row = self.connection.execute(
            "SELECT value FROM application_meta WHERE key=?", (key,)
        ).fetchone()
        return str(row[0]).rstrip("/") if row else STASHDB

    def ensure_endpoint(self, payload: dict[str, Any]) -> bool:
        endpoint = self.stashbox_endpoint.rstrip("/")
        if self._cached_endpoint("expand_cache_endpoint").casefold() == endpoint.casefold():
            return True
        latest = self.connection.execute(
            "SELECT state, COALESCE(error,''), "
            "COALESCE(json_extract(payload_json,'$.args.expand_endpoint'),''), "
            "started_at_ms, job_id "
            "FROM curator_job WHERE job_type IN ('expand-refresh','expand-rebuild') "
            "ORDER BY started_at_ms DESC, rowid DESC LIMIT 1"
        ).fetchone()
        now_ms = time.time_ns() // 1_000_000
        if latest and latest[0] in {"queued", "running"} and latest[3] > now_ms - 6 * 3_600_000:
            if latest[0] == "queued":
                with transaction(self.connection):
                    self.connection.execute(
                        "UPDATE curator_job SET payload_json=json_set(payload_json,"
                        "'$.args.automatic',json('false')) WHERE job_id=? AND state='queued'",
                        (latest[4],),
                    )
            return False
        if (
            latest
            and latest[0] in {"failed", "cancelled"}
            and latest[2].casefold() == endpoint.casefold()
        ):
            raise RuntimeError(
                f"Preparing the selected endpoint failed: {latest[1]}. "
                "Retry Refresh Expand cache in Manage > Tasks"
            )
        request = {**payload, "args": {**(payload.get("args") or {}), "expand_endpoint": endpoint}}
        with transaction(self.connection):
            self.connection.execute(
                "INSERT INTO curator_job(job_id,job_type,state,started_at_ms,"
                "queued_at_ms,payload_json) "
                "VALUES (?,'expand-refresh','queued',?,?,?)",
                (str(uuid4()), now_ms, now_ms, json.dumps(request, separators=(",", ":"))),
            )
        return False

    def _expand_meta(self, key: str) -> dict[str, Any] | None:
        """One JSON application_meta value; missing or unreadable reads as None."""
        row = self.connection.execute(
            "SELECT value FROM application_meta WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row[0]))
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def _write_expand_meta(self, key: str, value: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO application_meta(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, separators=(",", ":"))),
        )

    def _validate_scene_filters(self, client: GraphQLClient) -> None:
        if self.stashbox_endpoint.rstrip("/").casefold() == STASHDB.casefold():
            return
        try:
            data = client.execute(
                'query CuratorSceneFilterSchema { __type(name:"SceneQueryInput") '
                "{ inputFields { name type { kind name } } } }",
                {},
            )
        except (KeyError, RuntimeError, TypeError):
            return  # Introspection may be disabled; let the normal query report errors.
        for field in (data.get("__type") or {}).get("inputFields", []):
            name = field["name"]
            if name in {"performers", "studios", "tags"} and field["type"]["name"] == "String":
                raise RuntimeError(
                    f"Curator does not yet support Expand with this endpoint: its {name} filter "
                    "expects text instead of StashDB's filter object. "
                    "Choose a compatible Stash-box endpoint"
                )

    def _refresh_taxonomy(self, client: GraphQLClient, now_ms: int) -> bool:
        if (
            self._cached_endpoint("taxonomy_checked_endpoint").casefold()
            != self.stashbox_endpoint.casefold()
        ):
            with transaction(self.connection):
                self.connection.execute(
                    "DELETE FROM application_meta "
                    "WHERE key IN ('taxonomy_checked_at_ms','taxonomy_snapshot_id')"
                )
        checked = self.connection.execute(
            "SELECT value FROM application_meta WHERE key='taxonomy_checked_at_ms'"
        ).fetchone()
        current = self.connection.execute(
            """
            SELECT s.fetched_at_ms FROM application_meta m
            JOIN taxonomy_snapshot s ON s.snapshot_id=m.value
            WHERE m.key='taxonomy_snapshot_id'
            """
        ).fetchone()
        last_checked = int(checked[0]) if checked else (int(current[0]) if current else 0)
        if now_ms - last_checked < 30 * 86_400_000:
            return False
        try:
            data = StashDBTaxonomyClient(client).fetch()
        except (KeyError, RuntimeError, TypeError):
            return False
        published = TaxonomyStore(self.connection).publish(data, fetched_at_ms=now_ms)
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO application_meta(key, value)
                VALUES ('taxonomy_checked_at_ms', ?), ('taxonomy_checked_endpoint', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(now_ms), self.stashbox_endpoint),
            )
        if not published.reused:
            ModelUpdateCoordinator(self.connection).request("taxonomy_sync")
        return not published.reused

    def refresh(
        self,
        client: GraphQLClient,
        links: dict[str, dict[str, str]],
        *,
        horizon_days: int = 90,
        gender: str = "FEMALE",
        wildcard: bool = False,
        candidate_limit: int = 1_000,
        similar_top_k: int = 20,
        similar_per_favorite: int = 5,
        ethnicity: str = "",
        force_full: bool = False,
        now_ms: int | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, object]:
        fetched_at_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        started = time.monotonic()
        self._validate_scene_filters(client)
        endpoint_changed = (
            self._cached_endpoint("expand_cache_endpoint").casefold()
            != self.stashbox_endpoint.casefold()
        )
        timings: dict[str, int] = {}
        # The taxonomy check and seed load used to be markerless: on a large
        # library the bar sat at 5% for the whole stretch. The 50/150 ticks
        # bracket both phases (issue #110).
        if progress:
            progress(50, 1_000)
        phase = time.monotonic()
        taxonomy_refreshed = self._refresh_taxonomy(client, fetched_at_ms)
        timings["taxonomy"] = round((time.monotonic() - phase) * 1_000)
        if progress:
            progress(100, 1_000)
        model_store = RecommendationModelStore(self.connection)
        model_id = model_store.current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        model = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        feature_version = str(model[0])
        if progress:
            progress(150, 1_000)
        lookalike: dict[str, Any] = self._expand_meta(EXPAND_LOOKALIKE_KEY) or {}
        phase = time.monotonic()
        seeds = self._seeds(
            client,
            model_id,
            feature_version,
            links,
            similar_top_k=similar_top_k,
            similar_per_favorite=similar_per_favorite,
            gender=gender,
            ethnicity=ethnicity,
            timings=timings,
            lookalike=lookalike,
            now_ms=fetched_at_ms,
        )
        timings["seeds"] = round((time.monotonic() - phase) * 1_000)
        if progress:
            progress(200, 1_000)
        cache = self.connection.execute(
            "SELECT model_id, fetched_at_ms FROM expand_cache WHERE singleton=1"
        ).fetchone()
        cached_model_id = None
        if cache is not None:
            cached_model_id = str(cache["model_id"])
        previous = self._expand_meta(EXPAND_SEED_STATE_KEY)
        # An incremental refresh needs a previous refresh to walk back to and the seed set
        # it covered. A force rebuild is the escape hatch for scenes a watermark could
        # never surface, and ThePornDB has no update sort.
        since_ms = 0
        if (
            not force_full
            and not endpoint_changed
            and not is_theporndb(self.stashbox_endpoint)
            and cache is not None
            and previous is not None
            and 0
            <= fetched_at_ms - int(previous.get("full_fetch_at_ms") or 0)
            < EXPAND_FULL_FETCH_INTERVAL_MS
        ):
            since_ms = max(1, int(cache["fetched_at_ms"]) - EXPAND_WATERMARK_SLACK_MS)
        seed_state: dict[str, Any] = {"performers": [], "studios": [], "tags": []}
        filters = (
            ("performers", seeds["performers"]),
            ("studios", seeds["studios"]),
            ("tags", seeds["tags"]),
        )
        active = sum(bool(values) for _, values in filters) + int(wildcard)
        per_source = max(1, math.ceil(candidate_limit / max(1, active)))

        def probes(since_ms: int) -> list[tuple[str, list[str], int, str, int]]:
            seed_state["full_fetch_at_ms"] = (
                int(previous["full_fetch_at_ms"]) if since_ms and previous else fetched_at_ms
            )
            queries: list[tuple[str, list[str], int, str, int]] = []
            for source, values in filters:
                if not values:
                    continue
                known: list[str] = []
                fresh = list(values)
                if since_ms and previous is not None:
                    covered = set(previous.get(source) or [])
                    known = [value for value in values if value in covered]
                    fresh = [value for value in values if value not in covered]
                # Seeds the cached pool already covers only need what changed since the last
                # refresh: one probe newest-update-first, stopped at the watermark.
                if known:
                    queries.append((source, known, per_source, "UPDATED_AT", since_ms))
                # A full fetch samples each seed source by recency AND by popularity so
                # interesting scenes older than the newest N are not truncated out (a date-only
                # pool is recency-biased); new seeds get the same sample.
                if fresh:
                    half = max(1, per_source // 2)
                    queries.append((source, fresh, half, "DATE", 0))
                    queries.append((source, fresh, half, "POPULARITY", 0))
                seed_state[source] = sorted(values)
            if wildcard:
                queries.append(("wildcard", [], min(100, per_source), "TRENDING", 0))
            return queries

        def fetch(
            queries: list[tuple[str, list[str], int, str, int]],
        ) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
            rows: dict[str, dict[str, Any]] = {}
            sources: dict[str, set[str]] = defaultdict(set)
            for position, (source, values, limit, sort, probe_since_ms) in enumerate(queries, 1):
                if probe_since_ms:
                    self._fetch_since(client, rows, sources, source, values, limit, probe_since_ms)
                else:
                    self._fetch(client, rows, sources, source, values, limit, sort=sort)
                if progress:
                    progress(200 + round(450 * position / max(1, len(queries))), 1_000)
            return rows, sources

        queries = probes(since_ms)
        fetch_phase = time.monotonic()
        try:
            rows, sources = fetch(queries)
        except (GraphQLError, RuntimeError, KeyError, TypeError):
            if not since_ms:
                raise
            # A stash-box without the UPDATED_AT sort rejects the incremental probes; the
            # full fetch still works there.
            since_ms = 0
            queries = probes(0)
            rows, sources = fetch(queries)
        timings["fetch"] = round((time.monotonic() - fetch_phase) * 1_000)
        if progress and not queries:
            progress(650, 1_000)
        cutoff = date.today() - timedelta(days=horizon_days)
        candidates = []
        for row in rows.values():
            candidate = self._annotate_local_match(row, links)
            match = candidate.get("curator_local_match") or {}
            if (
                match.get("type") != "stashdb_id"
                and self._recent(candidate, cutoff)
                and self._matches_gender(candidate, gender)
            ):
                candidates.append(candidate)
        if progress:
            progress(750, 1_000)
        phase = time.monotonic()
        scenes, performers = self._score(candidates, sources, model_id, feature_version, links)
        timings["score"] = round((time.monotonic() - phase) * 1_000)
        if progress:
            progress(900, 1_000)
        phase = time.monotonic()
        with transaction(self.connection):
            # Merge the newly fetched candidates instead of wiping the pool, so unchanged
            # entries and the explore rows from hunts and similar probes survive a refresh.
            if endpoint_changed:
                self.connection.execute("DELETE FROM external_entity")
            self.connection.executemany(
                """
                INSERT INTO external_entity(
                  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool
                ) VALUES (?, ?, ?, ?, ?, ?, 'candidate')
                ON CONFLICT(entity_type, external_id) DO UPDATE SET
                  payload_json=excluded.payload_json, score=excluded.score,
                  sources_json=excluded.sources_json, fetched_at_ms=excluded.fetched_at_ms,
                  pool=CASE WHEN external_entity.pool='candidate'
                    THEN 'candidate' ELSE excluded.pool END
                """,
                (
                    (
                        kind,
                        str(item["id"]),
                        json.dumps(self._external_payload(item["payload"]), separators=(",", ":")),
                        item["score"],
                        json.dumps(item["sources"], separators=(",", ":")),
                        fetched_at_ms,
                    )
                    for kind, items in (("scene", scenes), ("performer", performers))
                    for item in items
                ),
            )
            # Scenes fetched while recent age out of the discovery window; drop them so an
            # incremental refresh cannot grow the pool without bound. The explore rows from
            # hunts and similar probes age out the same way (they re-fetch on demand), but
            # anything the user shortlisted is preserved.
            cutoff_iso = cutoff.isoformat()
            self.connection.execute(
                """
                DELETE FROM external_entity
                WHERE entity_type='scene' AND pool IN ('candidate', 'explore') AND (
                    (json_extract(payload_json, '$.release_date') IS NOT NULL
                     AND json_extract(payload_json, '$.release_date') < ?)
                    OR (json_extract(payload_json, '$.release_date') IS NULL
                        AND json_extract(payload_json, '$.production_date') IS NOT NULL
                        AND json_extract(payload_json, '$.production_date') < ?)
                ) AND external_id NOT IN (
                    SELECT external_id FROM external_shortlist WHERE entity_type='scene'
                )
                """,
                (cutoff_iso, cutoff_iso),
            )
            pool_counts = {
                str(row["entity_type"]): int(row["count"])
                for row in self.connection.execute(
                    "SELECT entity_type, count(*) AS count FROM external_entity"
                    " WHERE pool='candidate' GROUP BY entity_type"
                )
            }
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
                    pool_counts.get("scene", 0),
                    pool_counts.get("performer", 0),
                ),
            )
            self.connection.execute(
                "INSERT INTO application_meta(key,value) VALUES ('expand_cache_endpoint',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self.stashbox_endpoint,),
            )
            self._write_expand_meta(EXPAND_SEED_STATE_KEY, seed_state)
            if lookalike.get("key"):
                self._write_expand_meta(EXPAND_LOOKALIKE_KEY, lookalike)
        if cached_model_id is not None and cached_model_id != model_id:
            # The affinities and seeds changed with the model, so every surviving candidate's
            # score is stale; rescore the whole candidate pool in place.
            self._rescore_candidates(model_id, feature_version, links)
        timings["database_writing"] = round((time.monotonic() - phase) * 1_000)
        timings["total"] = round((time.monotonic() - started) * 1_000)
        if progress:
            progress(1_000, 1_000)
        return {
            "scene_count": len(scenes),
            "performer_count": len(performers),
            "taxonomy_refreshed": taxonomy_refreshed,
            "incremental": since_ms > 0,
            "stage_timings_ms": timings,
        }

    def _rescore_candidates(
        self, model_id: str, feature_version: str, links: dict[str, dict[str, str]]
    ) -> None:
        """Re-score the surviving candidate pool after the model changed.

        The candidate pool is model-driven: seeds and affinities come from the published
        model, so scores computed against an older model are stale once a new one lands.
        """
        rows = list(
            self.connection.execute(
                "SELECT external_id, payload_json, sources_json FROM external_entity"
                " WHERE entity_type='scene' AND pool='candidate'"
            )
        )
        if not rows:
            return
        scenes = [json.loads(str(row["payload_json"])) for row in rows]
        sources = {
            str(row["external_id"]): set(json.loads(str(row["sources_json"]))) for row in rows
        }
        rescored, performers = self._score(scenes, sources, model_id, feature_version, links)
        scene_scores = {str(item["id"]): float(item["score"]) for item in rescored}
        with transaction(self.connection):
            self.connection.executemany(
                "UPDATE external_entity SET score=? WHERE entity_type='scene' AND external_id=?",
                (
                    (scene_scores[str(row["external_id"])], str(row["external_id"]))
                    for row in rows
                    if str(row["external_id"]) in scene_scores
                ),
            )
            self.connection.executemany(
                "UPDATE external_entity SET score=? WHERE entity_type='performer'"
                " AND external_id=?",
                ((float(item["score"]), str(item["id"])) for item in performers),
            )

    def stashdb_performer_search(
        self, client: GraphQLClient, query: str, *, limit: int = 8
    ) -> dict[str, object]:
        """Name search over StashDB performers for the Performer Hunt picker
        (issue #218): lets the user hunt scenes for a performer that is not in
        the local library."""
        limit = max(1, min(50, limit))
        data = client.execute(
            PERFORMER_SEARCH,
            {
                "input": {
                    "page": 1,
                    "per_page": limit,
                    "names": query,
                }
            },
        )["queryPerformers"]["performers"]
        return {
            "items": [
                {
                    "id": performer["id"],
                    "name": performer["name"],
                    "aliases": performer.get("aliases", []),
                    "disambiguation": performer.get("disambiguation"),
                    "scene_count": performer.get("scene_count"),
                    "images": performer.get("images", []),
                }
                for performer in data
            ]
        }

    def performer_hunt(
        self,
        client: GraphQLClient,
        links: dict[str, dict[str, str]],
        performer_id: str,
        *,
        limit: int = PERFORMER_HUNT_LIMIT,
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
    ) -> dict[str, object]:
        local = self.connection.execute(
            "SELECT name FROM source_performer WHERE performer_id=?", (performer_id,)
        ).fetchone()
        if local is not None:
            external_performer_id = links["performers"].get(performer_id)
            if not external_performer_id:
                raise ValueError("selected performer is not linked to StashDB")
            performer_name = str(local["name"] or performer_id)
        else:
            # No local performer carries this id, so it is an external StashDB
            # performer, e.g. a similar-performer card the user wants to browse.
            # Hunt her scenes directly and take the name from the fetched cast.
            external_performer_id = performer_id
            performer_name = performer_id
        model_id = RecommendationModelStore(self.connection).current_model_id()
        feature_version = FeatureStore(self.connection).current_version()
        if model_id is None or feature_version is None:
            raise RuntimeError("no published model")

        rows: dict[str, dict[str, Any]] = {}
        sources: dict[str, set[str]] = defaultdict(set)
        total_count, truncated = self._fetch(
            client,
            rows,
            sources,
            "performers",
            [external_performer_id],
            limit,
        )
        if local is None:
            for scene in rows.values():
                name = next(
                    (
                        str(item["performer"].get("name") or "")
                        for item in scene.get("performers", [])
                        if str(item["performer"]["id"]) == external_performer_id
                    ),
                    "",
                )
                if name:
                    performer_name = name
                    break
        scenes, _ = self._score(
            [self._annotate_local_match(row, links) for row in rows.values()],
            sources,
            model_id,
            feature_version,
            links,
            multi_hop_seed=performer_id,
        )
        self._merge_external("scene", scenes)
        include_groups = equivalent_tag_names(self.connection, include_tags)
        exclude_groups = equivalent_tag_names(self.connection, exclude_tags)
        blocked_groups = self._blocked_tag_name_groups()
        shortlisted = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT external_id FROM external_shortlist "
                "WHERE entity_type='scene' AND endpoint=?",
                (self.stashbox_endpoint.casefold(),),
            )
        }
        dismissed = self.dismissed_scenes()
        disliked = self.disliked_performers()
        scenes = [self._with_performer_dislike(scene, disliked) for scene in scenes]
        items = [
            {
                **scene,
                "linked_locally": bool(scene["payload"].get("curator_local_match")),
                "local_scene_id": (scene["payload"].get("curator_local_match") or {}).get(
                    "local_scene_id"
                ),
                "match_type": (scene["payload"].get("curator_local_match") or {}).get("type"),
                "shortlisted": scene["id"] in shortlisted,
                "dismissed": dismissed.get(scene["id"]),
            }
            for scene in scenes
            if self._scene_matches(
                scene["payload"],
                include_tags,
                exclude_tags,
                include_groups=include_groups,
                exclude_groups=exclude_groups,
                blocked_groups=blocked_groups,
            )
        ]
        items.sort(
            key=lambda item: (
                -int(bool(item.get("multi_hop_reach", 0))),
                str(
                    item["payload"].get("release_date")
                    or item["payload"].get("production_date")
                    or ""
                ),
                item["id"],
            ),
            reverse=True,
        )
        linked_count = sum(bool(item["linked_locally"]) for item in items)
        return {
            "ready": True,
            "performer_id": performer_id,
            "performer_name": performer_name,
            "stashdb_total": total_count,
            "fetched_count": len(items),
            "total": len(items),
            "linked_count": linked_count,
            "not_linked_count": len(items) - linked_count,
            "truncated": truncated,
            "limit": limit,
            "items": items,
        }

    def results(
        self,
        entity_type: str,
        *,
        page: int = 1,
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
        hide_phash_matches: bool = True,
        hide_dismissed: bool = True,
        minimum_score: float = -1.0,
        count: int = 50,
        links: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, object]:
        if entity_type not in {"scene", "performer"} or sort not in {"match", "newest"}:
            raise ValueError("invalid Expand query")
        if page < 1 or not 1 <= count <= 500:
            raise ValueError("invalid Expand page")
        if not -1 <= minimum_score <= 1:
            raise ValueError("minimum_score must be between -1 and 1")
        cache = self.connection.execute("SELECT * FROM expand_cache WHERE singleton=1").fetchone()
        if cache is None or (
            self._cached_endpoint("expand_cache_endpoint").casefold()
            != self.stashbox_endpoint.casefold()
        ):
            return {
                "ready": False,
                "page": page,
                "page_size": count,
                "total": 0,
                "has_more": False,
                "items": [],
            }
        shortlisted = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT external_id FROM external_shortlist WHERE entity_type=? AND endpoint=?",
                (entity_type, self.stashbox_endpoint.casefold()),
            )
        }
        rows = []
        include_groups = equivalent_tag_names(self.connection, include_tags)
        exclude_groups = equivalent_tag_names(self.connection, exclude_tags)
        blocked_groups = self._blocked_tag_name_groups()
        dismissed = self.dismissed_scenes() if entity_type == "scene" else {}
        disliked = self.disliked_performers() if entity_type == "scene" else {}
        for row in self.connection.execute(
            "SELECT * FROM external_entity WHERE entity_type=? AND pool='candidate' "
            "AND lower(rtrim(COALESCE(json_extract(payload_json,'$.curator_endpoint'),"
            "'https://stashdb.org/graphql'),'/'))=lower(?) "
            "AND lower(rtrim(COALESCE((SELECT value FROM application_meta "
            "WHERE key='expand_cache_endpoint'),'https://stashdb.org/graphql'),'/'))=lower(?)",
            (entity_type, self.stashbox_endpoint.rstrip("/"), self.stashbox_endpoint.rstrip("/")),
        ):
            if hide_dismissed and str(row["external_id"]) in dismissed:
                continue
            payload = json.loads(row["payload_json"])
            score = float(row["score"])
            if entity_type == "scene":
                adjusted = self._with_performer_dislike(
                    {"payload": payload, "score": score}, disliked
                )
                payload, score = adjusted["payload"], adjusted["score"]
            if score < minimum_score:
                continue
            # Issue #118: the stored annotation can be stale (the candidate
            # was fetched before the local scene gained its StashDB id).
            # Re-derive it against the current links map; the serve-time
            # match is authoritative for the exclusion and the served payload.
            if links is not None and entity_type == "scene":
                payload = self._annotate_local_match(payload, links)
            match_type = (payload.get("curator_local_match") or {}).get("type")
            if entity_type == "scene" and (
                match_type == "stashdb_id" or (hide_phash_matches and match_type == "phash")
            ):
                continue
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
            if entity_type == "scene" and not self._scene_matches(
                payload,
                include_tags,
                exclude_tags,
                performer_names,
                studio_names,
                performer_query,
                studio_query,
                include_groups,
                exclude_groups,
                blocked_groups=blocked_groups,
            ):
                continue
            rows.append(
                {
                    "id": str(row["external_id"]),
                    "score": score,
                    "sources": json.loads(row["sources_json"]),
                    "payload": payload,
                    "shortlisted": str(row["external_id"]) in shortlisted,
                    **(
                        {"dismissed": dismissed.get(str(row["external_id"]))}
                        if entity_type == "scene"
                        else {}
                    ),
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
        start = (page - 1) * count
        end = page * count
        return {
            "ready": True,
            "fetched_at_ms": int(cache["fetched_at_ms"]),
            "expires_at_ms": int(cache["expires_at_ms"]),
            "page": page,
            "page_size": count,
            "total": len(rows),
            "has_more": len(rows) > end,
            "items": rows[start:end],
        }

    @staticmethod
    def _scene_matches(
        payload: dict[str, Any],
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_names: tuple[str, ...] = (),
        studio_names: tuple[str, ...] = (),
        performer_query: str = "",
        studio_query: str = "",
        include_groups: tuple[frozenset[str], ...] = (),
        exclude_groups: tuple[frozenset[str], ...] = (),
        blocked_groups: tuple[frozenset[str], ...] = (),
    ) -> bool:
        tags = {str(item.get("name") or "").casefold() for item in payload.get("tags", [])}
        cast = {
            str(item.get("performer", {}).get("name") or "").casefold()
            for item in payload.get("performers", [])
        }
        studio = str((payload.get("studio") or {}).get("name") or "").casefold()
        return (
            not any(group & tags for group in blocked_groups)
            and (not include_tags or all(group & tags for group in include_groups))
            and not any(group & tags for group in exclude_groups)
            and (not performer_names or all(value.casefold() in cast for value in performer_names))
            and (not studio_names or studio in {value.casefold() for value in studio_names})
            and (not performer_query or performer_query.casefold() in " ".join(cast))
            and (not studio_query or studio_query.casefold() in studio)
        )

    def _blocked_tag_name_groups(self) -> tuple[frozenset[str], ...]:
        """Resolve every blocked local tag to its local name and taxonomy aliases."""
        blocked_ids = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT tag_id FROM direct_tag_preference WHERE blocked=1"
            )
        }
        if not blocked_ids:
            return ()
        return equivalent_tag_names(
            self.connection,
            tuple(
                str(row[0])
                for row in self.connection.execute(
                    f"""SELECT name FROM source_tag WHERE tag_id IN
                    ({",".join("?" for _ in blocked_ids)})""",
                    sorted(blocked_ids),
                )
            ),
        )

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
                    "DELETE FROM external_shortlist "
                    "WHERE entity_type=? AND external_id=? AND endpoint=?",
                    (entity_type, external_id, self.stashbox_endpoint.casefold()),
                )
                return
            row = self.connection.execute(
                "SELECT * FROM external_entity WHERE entity_type=? AND external_id=?",
                (entity_type, external_id),
            ).fetchone()
            if row is None:
                raise ValueError("external entity is not in the current Expand cache")
            source = str(json.loads(row["payload_json"]).get("curator_endpoint") or STASHDB)
            if source.rstrip("/").casefold() != self.stashbox_endpoint.casefold():
                raise ValueError("external entity is not in the selected endpoint's cache")
            self.connection.execute(
                """
                INSERT INTO external_shortlist(
                  entity_type, external_id, payload_json, score, sources_json, added_at_ms, endpoint
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint, entity_type, external_id) DO UPDATE SET
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
                    self.stashbox_endpoint.casefold(),
                ),
            )

    def dismissed_scenes(self) -> dict[str, str]:
        """External scenes hidden from Find, by kind: Not interested, or an unexpired Not now."""
        return {
            str(row[0]): str(row[1])
            for row in self.connection.execute(
                "SELECT external_id, kind FROM external_dismissal WHERE endpoint=? "
                "AND (expires_at_ms IS NULL OR expires_at_ms>?)",
                (self.stashbox_endpoint.casefold(), time.time_ns() // 1_000_000),
            )
        }

    def disliked_performers(self) -> dict[str, str]:
        """StashDB performers the user is not into: name by StashDB id."""
        return {
            str(row[0]): str(row[1])
            for row in self.connection.execute(
                "SELECT performer_id, name FROM external_performer_dislike WHERE endpoint=?",
                (self.stashbox_endpoint.casefold(),),
            )
        }

    @classmethod
    def _with_performer_dislike(
        cls, scene: dict[str, Any], disliked: dict[str, str]
    ) -> dict[str, Any]:
        """Lower a scene's score for a cast member the user is not into.

        Only performers without a local profile count: a linked performer's
        dislike reaches the model as a reason instead. The penalty mirrors the
        identity term of _score at DISLIKED_PERFORMER_STRENGTH, and the
        payload names the performers so the card can say why.
        """
        payload = scene["payload"]
        cast = [item.get("performer") or {} for item in payload.get("performers", [])]
        names = [
            str(performer.get("name") or disliked[str(performer.get("id"))])
            for performer in cast
            if str(performer.get("id")) in disliked and not performer.get("curator_local")
        ]
        if not names:
            return scene
        penalty = 0.25 * DISLIKED_PERFORMER_STRENGTH * cls._cast_weight(len(cast)) / 0.90
        return {
            **scene,
            "payload": {
                **payload,
                "curator_performer_dislike": {"names": names, "penalty": penalty},
            },
            "score": float(scene["score"]) - penalty,
        }

    def update_performer_dislike(self, performer_id: str, name: str, disliked: bool) -> None:
        if not performer_id:
            raise ValueError("performer_id is required")
        endpoint = self.stashbox_endpoint.casefold()
        with transaction(self.connection):
            if disliked:
                changed = self.connection.execute(
                    """
                    INSERT INTO external_performer_dislike(
                        endpoint, performer_id, name, created_at_ms
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(endpoint, performer_id) DO UPDATE SET name=excluded.name
                    """,
                    (endpoint, performer_id, name or performer_id, time.time_ns() // 1_000_000),
                ).rowcount
            else:
                changed = self.connection.execute(
                    "DELETE FROM external_performer_dislike WHERE endpoint=? AND performer_id=?",
                    (endpoint, performer_id),
                ).rowcount
            # A performer already linked to the library is model evidence.
            if (
                changed
                and self.connection.execute(
                    f"SELECT 1 FROM ({LINKED_PERFORMERS}) WHERE stash_id=?", (performer_id,)
                ).fetchone()
            ):
                ModelUpdateCoordinator(self.connection).request("scene_reason")

    def performer_dislike_results(self, *, page: int = 1, count: int = 20) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 100:
            raise ValueError("invalid performer dislike page")
        endpoint = self.stashbox_endpoint.casefold()
        total = int(
            self.connection.execute(
                "SELECT count(*) FROM external_performer_dislike WHERE endpoint=?", (endpoint,)
            ).fetchone()[0]
        )
        items = [
            {
                "performer_id": str(row["performer_id"]),
                "name": str(row["name"]),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in self.connection.execute(
                "SELECT * FROM external_performer_dislike WHERE endpoint=?"
                " ORDER BY created_at_ms DESC, performer_id DESC LIMIT ? OFFSET ?",
                (endpoint, count, (page - 1) * count),
            )
        ]
        return {
            "page": page,
            "page_size": count,
            "total": total,
            "has_more": page * count < total,
            "items": items,
        }

    def dismiss(self, external_id: str, kind: str | None) -> None:
        """Hide an external scene from Find, or clear its dismissal when kind is None."""
        if kind is not None and kind not in EXTERNAL_DISMISSAL_KINDS:
            raise ValueError("invalid dismissal kind")
        endpoint = self.stashbox_endpoint.casefold()
        with transaction(self.connection):
            if kind is None:
                self.connection.execute(
                    "DELETE FROM external_dismissal WHERE endpoint=? AND external_id=?",
                    (endpoint, external_id),
                )
                return
            row = self.connection.execute(
                "SELECT payload_json FROM external_entity "
                "WHERE entity_type='scene' AND external_id=?",
                (external_id,),
            ).fetchone()
            if row is None:
                raise ValueError("external entity is not in the current Expand cache")
            source = str(json.loads(row["payload_json"]).get("curator_endpoint") or STASHDB)
            if source.rstrip("/").casefold() != endpoint:
                raise ValueError("external entity is not in the selected endpoint's cache")
            now_ms = time.time_ns() // 1_000_000
            expires_at_ms = (
                now_ms + int(DEFAULT_CONFIG.model.not_now_days * 86_400_000)
                if kind == "not_now"
                else None
            )
            self.connection.execute(
                """
                INSERT INTO external_dismissal(
                  endpoint, external_id, kind, created_at_ms, expires_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint, external_id) DO UPDATE SET
                  kind=excluded.kind, created_at_ms=excluded.created_at_ms,
                  expires_at_ms=excluded.expires_at_ms, payload_json=excluded.payload_json
                """,
                (endpoint, external_id, kind, now_ms, expires_at_ms, row["payload_json"]),
            )

    def dismissal_results(self, *, page: int = 1, count: int = 20) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 100:
            raise ValueError("invalid dismissal page")
        active = "d.endpoint=? AND (d.expires_at_ms IS NULL OR d.expires_at_ms>?)"
        parameters = (self.stashbox_endpoint.casefold(), time.time_ns() // 1_000_000)
        total = int(
            self.connection.execute(
                "SELECT count(*) FROM external_dismissal d WHERE " + active, parameters
            ).fetchone()[0]
        )
        # Card-shaped like Expand items; the score and sources come from the
        # candidate cache while the scene is still in it.
        items = [
            {
                "id": str(row["external_id"]),
                "score": float(row["score"]) if row["score"] is not None else 0.0,
                "sources": json.loads(row["sources_json"]) if row["sources_json"] else [],
                "payload": json.loads(row["payload_json"]),
                "kind": str(row["kind"]),
                "created_at_ms": int(row["created_at_ms"]),
                "expires_at_ms": (
                    int(row["expires_at_ms"]) if row["expires_at_ms"] is not None else None
                ),
            }
            for row in self.connection.execute(
                "SELECT d.external_id, d.kind, d.created_at_ms, d.expires_at_ms, d.payload_json,"
                " e.score, e.sources_json FROM external_dismissal d"
                " LEFT JOIN external_entity e"
                " ON e.entity_type='scene' AND e.external_id=d.external_id WHERE "
                + active
                + " ORDER BY d.created_at_ms DESC, d.external_id DESC LIMIT ? OFFSET ?",
                (*parameters, count, (page - 1) * count),
            )
        ]
        return {
            "ready": True,
            "page": page,
            "page_size": count,
            "total": total,
            "has_more": page * count < total,
            "items": items,
        }

    def shortlist_results(self, *, page: int = 1, count: int = 20) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 500:
            raise ValueError("invalid shortlist page")
        source_filter = "endpoint=lower(?)"
        total = int(
            self.connection.execute(
                "SELECT count(*) FROM external_shortlist WHERE " + source_filter,
                (self.stashbox_endpoint,),
            ).fetchone()[0]
        )
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
                "SELECT * FROM external_shortlist WHERE "
                + source_filter
                + " ORDER BY added_at_ms DESC LIMIT ? OFFSET ?",
                (self.stashbox_endpoint, count, (page - 1) * count),
            )
        ]
        return {
            "ready": True,
            "page": page,
            "page_size": count,
            "total": total,
            "has_more": page * count < total,
            "items": items,
        }

    def similar(
        self,
        entity_type: str,
        entity_id: str,
        count: int = 50,
        *,
        candidate_ids: set[str] | None = None,
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_names: tuple[str, ...] = (),
        studio_names: tuple[str, ...] = (),
        favorite_only: bool = False,
        minimum_similarity: float = 0.15,
        hide_dismissed: bool = True,
    ) -> dict[str, object]:
        if not 0 <= minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be between 0 and 1")
        shortlisted = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT external_id FROM external_shortlist WHERE entity_type=? AND endpoint=?",
                (entity_type, self.stashbox_endpoint.casefold()),
            )
        }
        if entity_type == "scene":
            include_groups = equivalent_tag_names(self.connection, include_tags)
            exclude_groups = equivalent_tag_names(self.connection, exclude_tags)
            target_tags = self._external_content(entity_id)
            feature_version = FeatureStore(self.connection).current_version()
            target_content = (
                FeatureStore(self.connection)
                .scene_content_vectors(feature_version, [entity_id])
                .get(entity_id, {})
                if feature_version
                else {}
            )
            content_space = (
                self._external_content_space(feature_version) if feature_version else None
            )
            target_performers = [
                str(row[0])
                for row in self.connection.execute(
                    "SELECT performer_id FROM scene_performer WHERE scene_id=?", (entity_id,)
                )
            ]
            target_studio = self.connection.execute(
                "SELECT studio_id FROM source_scene WHERE scene_id=?", (entity_id,)
            ).fetchone()
            target_studio_id = str(target_studio[0]) if target_studio and target_studio[0] else None
            target_structure = min(1.0, max(0, len(target_performers) - 1) / 3)
            target_is_compilation = bool(
                self.connection.execute(
                    """
                    SELECT 1 FROM scene_tag st JOIN source_tag t USING(tag_id)
                    WHERE st.scene_id=? AND lower(t.name)='compilation' LIMIT 1
                    """,
                    (entity_id,),
                ).fetchone()
            )
            profiles = (
                FeatureStore(self.connection).performer_profiles(feature_version)
                if feature_version
                else {}
            )
            targets = [profiles[value] for value in target_performers if value in profiles]
            weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
            dismissed = self.dismissed_scenes()
            disliked = self.disliked_performers()
            items = []
            for row in self.connection.execute(
                "SELECT * FROM external_entity WHERE entity_type='scene' "
                "AND lower(rtrim(COALESCE(json_extract(payload_json,'$.curator_endpoint'),"
                "'https://stashdb.org/graphql'),'/'))=lower(?)",
                (self.stashbox_endpoint,),
            ):
                if candidate_ids is not None and str(row["external_id"]) not in candidate_ids:
                    continue
                if hide_dismissed and str(row["external_id"]) in dismissed:
                    continue
                adjusted = self._with_performer_dislike(
                    {"payload": json.loads(row["payload_json"]), "score": float(row["score"])},
                    disliked,
                )
                payload, base_score = adjusted["payload"], adjusted["score"]
                if not target_is_compilation and any(
                    str(tag.get("name", "")).casefold() == "compilation"
                    for tag in payload.get("tags", [])
                ):
                    continue
                if not self._scene_matches(
                    payload,
                    include_tags,
                    exclude_tags,
                    performer_names,
                    studio_names,
                    include_groups=include_groups,
                    exclude_groups=exclude_groups,
                ):
                    continue
                if favorite_only and not any(
                    item.get("performer", {}).get("curator_local", {}).get("favorite")
                    for item in payload.get("performers", [])
                ):
                    continue
                tags = {
                    key: str(tag["name"])
                    for tag in payload.get("tags", [])
                    for key in (
                        f"id:{tag['id']}",
                        f"name:{str(tag['name']).casefold()}",
                    )
                }
                shared = set(target_tags) & set(tags)
                candidate_content = (
                    self._external_candidate_content(payload.get("tags", []), content_space)
                    if content_space
                    else {}
                )
                content = sum(
                    value * candidate_content.get(name, 0.0)
                    for name, value in target_content.items()
                )
                exact_performer = any(
                    str(item.get("performer", {}).get("curator_local", {}).get("id"))
                    in target_performers
                    for item in payload.get("performers", [])
                )
                performer = (
                    1.0
                    if exact_performer
                    else max(
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
                )
                # Same-performer scenes carry the full performer bonus even when
                # they share no theme, so wrong-theme scenes crowd the top. Scale
                # the credit by how much content the candidate actually shares:
                # a 0.35 floor at zero overlap, full credit only when the theme
                # overlaps too.
                performer *= 0.35 + 0.65 * content
                structure = 1 - abs(
                    target_structure - min(1.0, max(0, len(payload.get("performers", [])) - 1) / 3)
                )
                candidate_studio = payload.get("studio") or {}
                same_studio = bool(
                    target_studio_id
                    and str(candidate_studio.get("curator_local", {}).get("id")) == target_studio_id
                )
                similarity = (
                    0.5 * content + 0.3 * performer + 0.1 * structure + 0.1 * float(same_studio)
                )
                if similarity < minimum_similarity:
                    continue
                appeal = max(0.0, min(1.0, (base_score + 1) / 2))
                items.append(
                    {
                        "id": str(row["external_id"]),
                        "entity_type": "scene",
                        "similarity": similarity,
                        "appeal": appeal,
                        "score": 0.7 * similarity + 0.3 * appeal,
                        "sources": json.loads(row["sources_json"]),
                        "shortlisted": str(row["external_id"]) in shortlisted,
                        "dismissed": dismissed.get(str(row["external_id"])),
                        "payload": {
                            **payload,
                            "why": [
                                (
                                    f"Shares {', '.join(tags[value] for value in sorted(shared))}"
                                    if shared
                                    else (
                                        "Same performer"
                                        if exact_performer
                                        else (
                                            "Similar performer profile"
                                            if performer > 0
                                            else (
                                                "Same studio"
                                                if same_studio
                                                else "Similar cast structure"
                                            )
                                        )
                                    )
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
                "SELECT * FROM external_entity WHERE entity_type='performer' "
                "AND lower(rtrim(COALESCE(json_extract(payload_json,'$.curator_endpoint'),"
                "'https://stashdb.org/graphql'),'/'))=lower(?)",
                (self.stashbox_endpoint,),
            ):
                if candidate_ids is not None and str(row["external_id"]) not in candidate_ids:
                    continue
                payload = json.loads(row["payload_json"])
                candidate = self._profile(payload)
                similarity, match, coverage = self._profile_match(candidate, target, weights)
                if similarity < 0.25 or coverage < 0.25:
                    continue
                scene_count = payload.get("scene_count")
                if scene_count is not None:
                    # Rank by career size as well as profile closeness, so the
                    # perfectly-matching obscure performer does not crowd out the
                    # established one the user is likely to know.
                    appeal = min(1.0, math.log1p(int(scene_count)) / math.log1p(500))
                else:
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
                        "appeal": appeal,
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
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_names: tuple[str, ...] = (),
        studio_names: tuple[str, ...] = (),
        favorite_only: bool = False,
        include_owned: bool = False,
        hide_phash_matches: bool = True,
        hide_dismissed: bool = True,
        minimum_similarity: float = 0.15,
    ) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        feature_version = FeatureStore(self.connection).current_version()
        if model_id is None or feature_version is None:
            raise RuntimeError("no published model")
        started = time.perf_counter()
        timings: dict[str, int] = {}
        candidate_ids: set[str]
        if entity_type == "scene":
            content = self._external_content(entity_id)
            performers = [
                links["performers"][str(row[0])]
                for row in self.connection.execute(
                    "SELECT performer_id FROM scene_performer WHERE scene_id=?", (entity_id,)
                )
                if str(row[0]) in links["performers"]
            ]
            studios = [
                links["studios"][str(row[0])]
                for row in self.connection.execute(
                    "SELECT studio_id FROM source_scene WHERE scene_id=?", (entity_id,)
                )
                if row[0] and str(row[0]) in links["studios"]
            ]
            tag_ids = self._probe_tag_ids(content)
            tight_tag_ids = tag_ids[:3]
            probes = [
                ("tags", tag_ids, 250, "INCLUDES", "DATE"),
                ("tags", tag_ids, 250, "INCLUDES", "POPULARITY"),
                ("performers", performers, 150, "INCLUDES", "DATE"),
                ("performers", performers, 150, "INCLUDES", "POPULARITY"),
                ("studios", studios, 150, "INCLUDES", "DATE"),
                ("studios", studios, 150, "INCLUDES", "POPULARITY"),
            ]
            if len(tight_tag_ids) >= 2:
                probes.extend(
                    (
                        ("tags", tight_tag_ids, 100, "INCLUDES_ALL", "DATE"),
                        ("tags", tight_tag_ids, 100, "INCLUDES_ALL", "POPULARITY"),
                    )
                )
            rows, sources = self._fetch_probes(
                client,
                [probe for probe in probes if probe[1]],
            )
            timings["retrieval"] = round((time.perf_counter() - started) * 1000)
            record_duration("python", "external_similar.retrieval", timings["retrieval"])
            stage_started = time.perf_counter()
            candidates = []
            for value in rows.values():
                candidate = self._annotate_local_match(value, links)
                match_type = (candidate.get("curator_local_match") or {}).get("type")
                if (
                    (include_owned or match_type != "stashdb_id")
                    and (not hide_phash_matches or match_type != "phash")
                    and self._matches_gender(candidate, gender)
                ):
                    # In comparison mode keep library scenes except the
                    # reference scene itself (a trivial self-match).
                    if (
                        include_owned
                        and (candidate.get("curator_local_match") or {}).get("local_scene_id")
                        == entity_id
                    ):
                        continue
                    candidates.append(candidate)
            candidate_ids = {str(value["id"]) for value in candidates}
            scenes, _ = self._score(
                candidates, sources, model_id, feature_version, links, multi_hop_seed=entity_id
            )
            self._merge_external("scene", scenes)
            timings["scoring"] = round((time.perf_counter() - stage_started) * 1000)
            record_duration("python", "external_similar.scoring", timings["scoring"])
        elif entity_type == "performer":
            target_row = self.connection.execute(
                "SELECT gender, ethnicity, birthdate FROM source_performer WHERE performer_id=?",
                (entity_id,),
            ).fetchone()
            if target_row is None:
                raise ValueError(f"unknown performer: {entity_id}")
            selected_gender = gender or str(target_row["gender"] or "")
            ethnicity = str(target_row["ethnicity"] or "").upper().replace(" ", "_")
            if ethnicity not in {
                "CAUCASIAN",
                "BLACK",
                "ASIAN",
                "INDIAN",
                "LATIN",
                "MIDDLE_EASTERN",
                "MIXED",
                "OTHER",
            }:
                ethnicity = ""
            target = (
                FeatureStore(self.connection).performer_profiles(feature_version).get(entity_id)
            )
            if target is not None:
                target = self._with_age(target, target_row["birthdate"])
            candidates = self._fetch_performer_pool(
                client,
                target,
                selected_gender,
                ethnicity,
                performed_with=links["performers"].get(entity_id),
            )
            if include_owned:
                # Comparison mode: keep library performers in the results so the
                # remote ranking can be checked against the local one. Only the
                # searched performer herself is excluded (a trivial self-match).
                excluded = (
                    {links["performers"][entity_id]} if entity_id in links["performers"] else set()
                )
            else:
                excluded = set(links["performers"].values())
            candidate_ids = {
                str(payload["id"]) for payload in candidates if str(payload["id"]) not in excluded
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
                    if str(payload["id"]) not in excluded
                ),
            )
            timings["retrieval"] = round((time.perf_counter() - started) * 1000)
            record_duration("python", "external_similar.retrieval", timings["retrieval"])
        else:
            raise ValueError("invalid external similarity entity type")
        stage_started = time.perf_counter()
        result = self.similar(
            entity_type,
            entity_id,
            count=count * 2,
            candidate_ids=candidate_ids,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            performer_names=performer_names,
            studio_names=studio_names,
            favorite_only=favorite_only,
            minimum_similarity=minimum_similarity,
            hide_dismissed=hide_dismissed,
        )
        raw_items = result["items"]
        assert isinstance(raw_items, list)
        blocked_groups = self._blocked_tag_name_groups()
        filtered_items = [
            item
            for item in raw_items
            if not gender or self._payload_matches_gender(item["payload"], entity_type, gender)
        ]
        if entity_type == "scene":
            filtered_items = [
                item
                for item in filtered_items
                if self._scene_matches(item["payload"], blocked_groups=blocked_groups)
            ]
        filtered_items = filtered_items[:count]
        if entity_type == "performer":
            # Mark results that are already in the library so the cards can
            # badge them and link to the local profile instead of StashDB.
            local_by_external = {external: local for local, external in links["performers"].items()}
            for item in filtered_items:
                local_id = local_by_external.get(str(item["id"]))
                if local_id is None:
                    continue
                favorite = bool(
                    self.connection.execute(
                        "SELECT favorite FROM source_performer WHERE performer_id=?", (local_id,)
                    ).fetchone()[0]
                )
                item["payload"]["curator_local"] = {"id": local_id, "favorite": favorite}
        elif entity_type == "scene":
            local_by_external = links.get("scene_ids", {})
            if not local_by_external:
                local_by_external = {
                    external: local for local, external in links.get("scenes", {}).items()
                }
            for item in filtered_items:
                local_id = local_by_external.get(str(item["id"]))
                if local_id is None:
                    continue
                item["payload"]["curator_local"] = {"id": local_id}
        result["items"] = filtered_items
        result["total"] = len(filtered_items)
        result["ready"] = bool(filtered_items)
        timings["ranking"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "external_similar.filter_and_rank", timings["ranking"])
        timings["total"] = round((time.perf_counter() - started) * 1000)
        result["timings_ms"] = timings
        return result

    def _probe_tag_ids(self, content: dict[str, float]) -> list[str]:
        """Mapped tag ids ordered by rarity, the tags that define a theme.

        Normalized content weights saturate to near-equal values on well-tagged
        scenes, so weight ordering is effectively noise. Document frequency is
        the stable signal: the rarest mapped tags (Student, Teacher, School)
        are the distinctive ones, while common tags (Fingering, All Sex) only
        dilute the candidate pool. Missing frequencies fall back to weight.
        """
        ids = [
            key.removeprefix("id:")
            for key in sorted(content, key=content.__getitem__, reverse=True)
            if key.startswith("id:")
        ]
        if not ids:
            return []
        local_ids = {
            str(row["stash_id"]): str(row["tag_id"])
            for row in self.connection.execute(
                f"""
                SELECT tag_id, stash_id FROM source_tag_stash_id
                WHERE lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))
                  AND stash_id IN ({",".join("?" for _ in ids)})
                """,
                (self.stashbox_endpoint, *ids),
            )
        }
        frequencies: dict[str, int] = {}
        if local_ids:
            for row in self.connection.execute(
                f"""
                SELECT replace(name, 'tag:', '') AS local_id, metadata_json
                FROM feature_definition
                WHERE family='content' AND name IN ({",".join("?" for _ in local_ids.values())})
                """,
                [f"tag:{identifier}" for identifier in local_ids.values()],
            ):
                try:
                    frequencies[str(row["local_id"])] = int(
                        json.loads(str(row["metadata_json"]))["document_frequency"]
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        return sorted(
            ids,
            key=lambda identifier: (
                frequencies.get(local_ids.get(identifier, ""), 10**9),
                -content.get(f"id:{identifier}", 0.0),
            ),
        )[:10]

    def _fetch_performer_pool(
        self,
        client: GraphQLClient,
        target: PerformerProfile | None,
        gender: str,
        ethnicity: str,
        *,
        performed_with: str | None = None,
    ) -> list[dict[str, Any]]:
        """Union popularity-ranked StashDB performer pools biased toward the target.

        StashDB's queryPerformers honors age, gender, ethnicity, and performed_with
        filters but silently ignores the schema's body-attribute criteria (height,
        cup size, breast type, ...), so the target profile can only narrow
        retrieval with an age floor. The unfiltered popularity query stays as a
        recall floor; the co-star query pulls performers who have actually worked
        with the target, which reaches the mature ecosystem a popularity sweep
        misses; the re-ranker picks the closest profiles from the union.
        """
        base: dict[str, object] = {
            "page": 1,
            "per_page": 500,
            "sort": "POPULARITY",
            "direction": "DESC",
        }
        if gender:
            base["gender"] = gender
        if ethnicity:
            base["ethnicity"] = ethnicity
        queries = [dict(base)]
        if performed_with:
            queries.append({**base, "performed_with": performed_with})
        age = target.blocks.get("age", {}).get("age_recording") if target else None
        if age is not None:
            lower = int(age.value - 12)
            if lower >= 25:
                queries.append({**base, "age": {"value": lower, "modifier": "GREATER_THAN"}})

        def fetch(query: dict[str, object]) -> Any:
            return client.execute(PERFORMERS, {"input": query})["queryPerformers"]["performers"]

        pooled: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            futures = [executor.submit(copy_context().run, fetch, query) for query in queries]
            for future in futures:
                for performer in future.result():
                    pooled.setdefault(str(performer["id"]), performer)
        return list(pooled.values())

    @staticmethod
    def _annotate_local_match(
        scene: dict[str, Any], links: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        external_id = str(scene["id"])
        local_scene_id = links.get("scene_ids", {}).get(external_id)
        if local_scene_id is None:
            local_scene_id = next(
                (
                    local
                    for local, external in links.get("scenes", {}).items()
                    if external == external_id
                ),
                None,
            )
        match_type = "stashdb_id" if local_scene_id else None
        if local_scene_id is None:
            for fingerprint in scene.get("fingerprints", []):
                if str(fingerprint.get("algorithm") or "").casefold() != "phash":
                    continue
                value = normalize_phash(fingerprint.get("hash"))
                if value is None:
                    continue
                local_scene_id = links.get("scene_phashes", {}).get(value)
                if local_scene_id:
                    match_type = "phash"
                    break
        if local_scene_id is None:
            return {key: value for key, value in scene.items() if key != "curator_local_match"}
        return {
            **scene,
            "curator_local_match": {
                "type": match_type,
                "local_scene_id": local_scene_id,
            },
        }

    def _fetch_probes(
        self,
        client: GraphQLClient,
        probes: list[tuple[str, list[str], int, str, str]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
        if not probes:
            return {}, defaultdict(set)

        def fetch(
            probe: tuple[str, list[str], int, str, str],
        ) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
            rows: dict[str, dict[str, Any]] = {}
            sources: dict[str, set[str]] = defaultdict(set)
            self._fetch(client, rows, sources, *probe)
            return rows, sources

        rows: dict[str, dict[str, Any]] = {}
        sources: dict[str, set[str]] = defaultdict(set)
        with ThreadPoolExecutor(max_workers=len(probes)) as executor:
            futures = [executor.submit(copy_context().run, fetch, probe) for probe in probes]
            for future in futures:
                probe_rows, probe_sources = future.result()
                rows.update(probe_rows)
                for identifier, values in probe_sources.items():
                    sources[identifier].update(values)
        return rows, sources

    def _external_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.stashbox_endpoint.casefold() != STASHDB.casefold():
            payload["curator_endpoint"] = self.stashbox_endpoint
        return payload

    def _merge_external(
        self, entity_type: str, items: Iterable[dict[str, Any]], *, pool: str = "explore"
    ) -> None:
        """Merge discovered entities so they can be shortlisted or chained into.

        Callers that browse on the user's behalf (a performer hunt, a "similar to
        this" probe) merge with the default 'explore' pool: the row becomes
        shortlistable and usable as a similarity anchor, but stays out of the
        general Expand browse (`results()`), which only shows `refresh()`'s own
        'candidate' pool. Otherwise one performer's whole catalog, or one scene's
        probe, would bleed into another's Expand results until the next refresh.
        """
        now_ms = time.time_ns() // 1_000_000
        with transaction(self.connection):
            self.connection.executemany(
                """
                INSERT INTO external_entity(
                  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, external_id) DO UPDATE SET
                  payload_json=excluded.payload_json, score=excluded.score,
                  sources_json=excluded.sources_json, fetched_at_ms=excluded.fetched_at_ms,
                  pool=CASE WHEN pool='candidate' THEN 'candidate' ELSE excluded.pool END
                """,
                (
                    (
                        entity_type,
                        str(item["id"]),
                        json.dumps(self._external_payload(item["payload"]), separators=(",", ":")),
                        float(item["score"]),
                        json.dumps(item["sources"], separators=(",", ":")),
                        now_ms,
                        pool,
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
        local_ids = {name.removeprefix("tag:") for name in vector}
        if not local_ids:
            return {}
        external_ids = self._external_tag_ids(local_ids)
        names = {
            str(row["tag_id"]): str(row["name"])
            for row in self.connection.execute(
                f"SELECT tag_id, name FROM source_tag WHERE tag_id IN "
                f"({','.join('?' for _ in local_ids)})",
                sorted(local_ids),
            )
        }
        return {
            (
                f"id:{external_ids[local_id]}"
                if local_id in external_ids
                else f"name:{names[local_id].casefold()}"
            ): value
            for name, value in vector.items()
            if (local_id := name.removeprefix("tag:")) in names
        }

    def _external_content_space(
        self, feature_version: str
    ) -> tuple[dict[str, set[str]], dict[str, float], dict[str, set[str]], float]:
        config_row = self.connection.execute(
            "SELECT config_json FROM feature_build WHERE feature_version=?", (feature_version,)
        ).fetchone()
        config = json.loads(config_row[0]) if config_row else {}
        total = max(
            1, int(self.connection.execute("SELECT count(*) FROM source_scene").fetchone()[0])
        )
        rows = list(
            self.connection.execute(
                """
                SELECT d.name, d.metadata_json, t.tag_id, t.name AS tag_name
                FROM feature_definition d JOIN source_tag t ON d.name='tag:' || t.tag_id
                WHERE d.feature_version=? AND d.family='content'
                """,
                (feature_version,),
            )
        )
        external_ids = self._external_tag_ids({str(row["tag_id"]) for row in rows})
        mappings: dict[str, set[str]] = defaultdict(set)
        weights: dict[str, float] = {}
        for row in rows:
            name = str(row["name"])
            local_id = str(row["tag_id"])
            frequency = int(json.loads(row["metadata_json"])["document_frequency"])
            rarity = min(
                float(config.get("idf_cap", DEFAULT_CONFIG.feature.idf_cap)),
                1
                + float(config.get("idf_strength", DEFAULT_CONFIG.feature.idf_strength))
                * math.log((total + 1) / (frequency + 1)),
            )
            weights[name] = (
                rarity
                * frequency
                / (
                    frequency
                    + float(config.get("one_off_prior", DEFAULT_CONFIG.feature.one_off_prior))
                )
            )
            mappings[f"name:{str(row['tag_name']).casefold()}"].add(name)
            if local_id in external_ids:
                mappings[f"id:{external_ids[local_id]}"].add(name)
        parents: dict[str, set[str]] = defaultdict(set)
        for row in self.connection.execute("SELECT tag_id, parent_tag_id FROM tag_parent"):
            child = f"tag:{row['tag_id']}"
            parent = f"tag:{row['parent_tag_id']}"
            if child in weights and parent in weights:
                parents[child].add(parent)
        return (
            mappings,
            weights,
            parents,
            float(config.get("parent_weight", DEFAULT_CONFIG.feature.parent_weight)),
        )

    @staticmethod
    def _external_candidate_content(
        tags: Iterable[dict[str, Any]],
        space: tuple[dict[str, set[str]], dict[str, float], dict[str, set[str]], float],
    ) -> dict[str, float]:
        mappings, weights, parents, parent_weight = space
        base: dict[str, float] = {}
        for tag in tags:
            names = mappings.get(f"id:{tag.get('id')}", set()) | mappings.get(
                f"name:{str(tag.get('name') or '').casefold()}", set()
            )
            for name in names:
                base[name] = 1.0
                for parent in parents.get(name, set()):
                    base[parent] = max(base.get(parent, 0.0), parent_weight)
        vector = {name: base_value * weights[name] for name, base_value in base.items()}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {name: value / norm for name, value in vector.items()}

    def _external_tag_ids(self, local_ids: set[str]) -> dict[str, str]:
        if not local_ids:
            return {}
        taxonomy = TaxonomyIndex(self.connection)
        result = {
            str(row["tag_id"]): str(row["stash_id"])
            for row in self.connection.execute(
                f"SELECT tag_id, stash_id FROM source_tag_stash_id WHERE tag_id IN "
                f"({','.join('?' for _ in local_ids)}) "
                "AND lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))",
                (*sorted(local_ids), self.stashbox_endpoint),
            )
        }
        for row in self.connection.execute(
            f"SELECT tag_id, name FROM source_tag WHERE tag_id IN "
            f"({','.join('?' for _ in local_ids)})",
            sorted(local_ids),
        ):
            local_id = str(row["tag_id"])
            if local_id in result:
                continue
            match = taxonomy.resolve(local_id, str(row["name"]))
            if match and match.external_tag_id and match.confidence >= 0.9:
                result[local_id] = match.external_tag_id
        return result

    def _seeds(
        self,
        client: GraphQLClient,
        model_id: str,
        feature_version: str,
        links: dict[str, dict[str, str]],
        *,
        similar_top_k: int = 20,
        similar_per_favorite: int = 5,
        gender: str = "",
        ethnicity: str = "",
        timings: dict[str, int] | None = None,
        lookalike: dict[str, Any] | None = None,
        now_ms: int = 0,
    ) -> dict[str, list[str]]:
        timings = timings if timings is not None else {}
        lookalike = lookalike if lookalike is not None else {}
        top = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT scene_id FROM model_scene_score WHERE model_id=?
                ORDER BY appeal * confidence DESC LIMIT 500
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
        # A performer outside the library but similar to the user's own favorites never
        # reaches the seed set through evidence alone (that only sees local performers).
        # Chase the strongest favorites into StashDB and pull their closest look-alikes so
        # the pool reaches scenes by performers the model has affinity for but has not seen.
        if is_theporndb(self.stashbox_endpoint):
            performers = performers[:16]
            similar_top_k, similar_per_favorite = (
                min(4, similar_top_k),
                min(4, similar_per_favorite),
            )
        if client is not None and similar_top_k > 0 and similar_per_favorite > 0 and performers:
            performers = self._expand_similar_performers(
                client,
                performers,
                evidence,
                model_id,
                feature_version,
                links,
                similar_top_k,
                similar_per_favorite,
                gender,
                ethnicity,
                timings,
                lookalike,
                now_ms,
            )
        played = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT scene_id FROM source_scene
                ORDER BY play_count DESC, updated_at DESC LIMIT 200
                """
            )
        ]
        studio_scope = list(dict.fromkeys((*top, *played)))
        studios: set[str] = set()
        if studio_scope:
            studios = {
                links["studios"][str(row[0])]
                for row in self.connection.execute(
                    f"SELECT DISTINCT studio_id FROM source_scene WHERE scene_id IN "
                    f"({','.join('?' for _ in studio_scope)}) AND studio_id IS NOT NULL",
                    studio_scope,
                )
                if str(row[0]) in links["studios"]
            }
        local_tags = [
            str(row[0]).removeprefix("tag:")
            for row in self.connection.execute(
                """
                SELECT d.name FROM feature_affinity a
                JOIN feature_definition d USING(feature_id)
                WHERE a.model_id=? AND d.feature_version=? AND d.family='content'
                  AND a.affinity > 0
                ORDER BY a.affinity * a.confidence DESC LIMIT 50
                """,
                (model_id, feature_version),
            )
        ]
        direct_tags = [
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT tag_id FROM direct_tag_preference
                WHERE value > 0 ORDER BY value DESC, tag_id
                """
            )
        ]
        local_tags = list(dict.fromkeys((*direct_tags, *local_tags)))
        resolved = self._external_tag_ids(set(local_tags))
        tags = list(dict.fromkeys(resolved[value] for value in local_tags if value in resolved))[
            :50
        ]
        return {
            "performers": performers[:32] if is_theporndb(self.stashbox_endpoint) else performers,
            "studios": sorted(studios)[: 8 if is_theporndb(self.stashbox_endpoint) else 60],
            "tags": tags,
        }

    def _expand_similar_performers(
        self,
        client: GraphQLClient,
        base: list[str],
        evidence: dict[str, dict[str, Any]],
        model_id: str,
        feature_version: str,
        links: dict[str, dict[str, str]],
        top_k: int,
        per_favorite: int,
        gender: str,
        ethnicity: str,
        timings: dict[str, int],
        lookalike: dict[str, Any] | None = None,
        now_ms: int = 0,
    ) -> list[str]:
        # Best-effort enrichment: it must never fail an Expand refresh. A lookup-alike pass
        # is only worth the seed breadth it adds, so any failure (a StashDB instance that
        # predates a query, a missing profile, or a broken response) degrades to base seeds.
        #
        # lookalike holds the cached chase on entry; its additions are reused while the
        # inputs match and it is under a week old. On return it holds the entry to save,
        # or nothing for a cache hit or a chase with a failed lookup (an incomplete result).
        lookalike = lookalike if lookalike is not None else {}
        cached = dict(lookalike)
        lookalike.clear()
        ranked = sorted(
            evidence.items(), key=lambda value: (-float(value[1]["strength"]), value[0])
        )
        key = json.dumps(
            [
                self.stashbox_endpoint.rstrip("/").lower(),
                gender,
                ethnicity,
                top_k,
                per_favorite,
                [external_id for external_id, _info in ranked[:top_k]],
            ],
            separators=(",", ":"),
        )
        cached_at = int(cached.get("fetched_at_ms") or 0)
        if cached.get("key") == key and 0 <= now_ms - cached_at < EXPAND_LOOKALIKE_TTL_MS:
            timings["seeds_chase_cached"] = 1
            return self._merge_lookalikes(base, cached.get("additions") or [], evidence)
        t0 = time.monotonic()
        try:
            profiles = FeatureStore(self.connection).performer_profiles(feature_version)
        except Exception:
            return base
        timings["seeds_profiles"] = round((time.monotonic() - t0) * 1_000)
        if not profiles:
            return base
        weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
        recorded = date.today().isoformat()
        additions: list[str] = []
        network_ms = 0
        match_ms = 0
        calls = 0
        failures = 0
        for external_id, info in ranked[:top_k]:
            target = profiles.get(info["local_id"])
            if target is None:
                continue
            t_net = time.monotonic()
            try:
                pool = self._fetch_performer_pool(
                    client, target, gender, ethnicity, performed_with=external_id
                )
            except (GraphQLError, KeyError, TypeError):
                failures += 1
                continue
            network_ms += round((time.monotonic() - t_net) * 1_000)
            calls += 1
            scored: list[tuple[float, str]] = []
            t_match = time.monotonic()
            for performer in pool:
                profile = self._profile(performer, recorded)
                if self._profile_conflicts(profile, target):
                    continue
                similarity, _match, _coverage = self._profile_match(profile, target, weights)
                scored.append((similarity, str(performer["id"])))
            match_ms += round((time.monotonic() - t_match) * 1_000)
            scored.sort(key=lambda value: value[0], reverse=True)
            for _similarity, external in scored[:per_favorite]:
                if external not in evidence and external not in additions:
                    additions.append(external)
        timings["seeds_chase_network"] = network_ms
        timings["seeds_chase_match"] = match_ms
        timings["seeds_chase_calls"] = calls
        if not failures:
            lookalike.update(key=key, fetched_at_ms=now_ms, additions=additions)
        return self._merge_lookalikes(base, additions, evidence)

    @staticmethod
    def _merge_lookalikes(
        base: list[str], additions: Iterable[str], evidence: dict[str, dict[str, Any]]
    ) -> list[str]:
        """Base seeds plus chase additions the user has no evidence for yet (a cached
        chase can predate the latest evidence)."""
        return list(
            dict.fromkeys((*base, *(value for value in additions if value not in evidence)))
        )

    @staticmethod
    def _fetch(
        client: GraphQLClient,
        rows: dict[str, dict[str, Any]],
        sources: dict[str, set[str]],
        source: str,
        values: list[str],
        limit: int,
        modifier: str = "INCLUDES",
        sort: str = "DATE",
    ) -> tuple[int, bool]:
        fetched = 0
        page = 1
        total = 0
        page_size = min(250, limit)
        while fetched < limit:
            query: dict[str, object] = {
                "page": page,
                "per_page": page_size,
                "sort": "TRENDING" if source == "wildcard" else sort,
                "direction": "DESC",
            }
            if source != "wildcard":
                query[source] = {"value": values, "modifier": modifier}
            data = client.execute(SCENES, {"input": query})["queryScenes"]
            total = int(data["count"])
            batch = data["scenes"]
            accepted = batch[: limit - fetched]
            for scene in accepted:
                identifier = str(scene["id"])
                rows.setdefault(identifier, scene)
                sources[identifier].add(source)
            fetched += len(accepted)
            if not batch or fetched >= total:
                break
            page += 1
        return total, fetched < total

    @staticmethod
    def _fetch_since(
        client: GraphQLClient,
        rows: dict[str, dict[str, Any]],
        sources: dict[str, set[str]],
        source: str,
        values: list[str],
        limit: int,
        since_ms: int,
    ) -> None:
        """StashDB cannot filter scenes by updated_at, so the probe sorts by UPDATED_AT
        and pages until it reaches a scene last updated at or before the watermark. A
        scene without a readable updated time counts as changed."""
        fetched = 0
        page = 1
        page_size = min(250, limit)
        while fetched < limit:
            query: dict[str, object] = {
                "page": page,
                "per_page": page_size,
                "sort": "UPDATED_AT",
                "direction": "DESC",
                source: {"value": values, "modifier": "INCLUDES"},
            }
            data = client.execute(SCENES, {"input": query})["queryScenes"]
            total = int(data["count"])
            batch = data["scenes"]
            for scene in batch:
                if fetched >= limit:
                    return
                try:
                    updated = datetime.fromisoformat(str(scene["updated"]))
                except (KeyError, TypeError, ValueError):
                    updated = None
                if updated is not None:
                    updated = updated if updated.tzinfo else updated.replace(tzinfo=UTC)
                    if (updated - _EPOCH) // timedelta(milliseconds=1) <= since_ms:
                        return
                identifier = str(scene["id"])
                rows.setdefault(identifier, scene)
                sources[identifier].add(source)
                fetched += 1
            if not batch or page * page_size >= total:
                return
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
        *,
        multi_hop_seed: str | None = None,
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
            (self.stashbox_endpoint, model_id, feature_version),
        ):
            value = float(row["value"])
            tag_affinity[f"name:{str(row['name']).casefold()}"] = value
            if row["stash_id"]:
                tag_affinity[f"id:{row['stash_id']}"] = value
        for row in self.connection.execute(
            """
            SELECT ids.stash_id, t.name, p.value
            FROM direct_tag_preference p JOIN source_tag t USING(tag_id)
            LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
              AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
            """,
            (self.stashbox_endpoint,),
        ):
            value = float(row["value"])
            tag_affinity.setdefault(f"name:{str(row['name']).casefold()}", value)
            if row["stash_id"]:
                tag_affinity.setdefault(f"id:{row['stash_id']}", value)
        external_studio_appeal = {
            links["studios"][str(row["studio_id"])]: float(row["appeal"])
            for row in self.connection.execute(
                """
                WITH appeal AS (
                  SELECT scene_id, max(appeal) AS value FROM model_scene_lane
                  WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id
                )
                SELECT s.studio_id, AVG(a.value) AS appeal
                FROM source_scene s JOIN appeal a USING(scene_id)
                WHERE s.studio_id IS NOT NULL GROUP BY s.studio_id
                """,
                (model_id,),
            )
            if str(row["studio_id"]) in links["studios"]
        }
        evidence = self._performer_evidence(model_id, links)
        evidence_by_local = {str(item["local_id"]): item for item in evidence.values()}
        anchor_ids = {key for key, item in evidence_by_local.items() if float(item["strength"]) > 0}
        profiles = FeatureStore(self.connection).performer_profiles(feature_version, anchor_ids)
        local_studios = {external: local for local, external in links["studios"].items()}
        anchors = [
            (profiles[key], item) for key, item in evidence_by_local.items() if key in profiles
        ]
        weights = dict(DEFAULT_CONFIG.feature.performer_block_weights)
        matcher = _AnchorMatcher(anchors, weights)
        performer_rows: dict[str, dict[str, Any]] = {}
        scene_rows = []
        for scene in scenes:
            tag_signals = sorted(
                (self._tag_value(tag, tag_affinity) for tag in scene.get("tags", [])),
                key=abs,
                reverse=True,
            )[:5]
            tag_value = math.tanh(sum(tag_signals))
            cast = [item["performer"] for item in scene.get("performers", [])]
            cast_weight = self._cast_weight(len(cast))
            identity_evidence = max(
                (evidence.get(str(item["id"]), {}) for item in cast),
                default={},
                key=lambda item: float(item.get("strength", 0)),
            )
            identity = float(identity_evidence.get("strength", 0)) * cast_weight
            studio = scene.get("studio") or {}
            studio_value = external_studio_appeal.get(str(studio.get("id") or ""), 0)
            studio_payload = {**studio}
            if local_studio := local_studios.get(str(studio.get("id") or "")):
                studio_payload["curator_local"] = {"id": local_studio}
            similarity_value = 0.0
            for performer in cast:
                external_id = str(performer["id"])
                local = evidence.get(external_id)
                match = (
                    matcher.best(
                        performer,
                        scene.get("production_date") or scene.get("release_date"),
                    )
                    if local is None
                    else None
                )
                strength = float(match[3].get("strength", 0)) if match else 0.0
                similarity_value = max(
                    similarity_value, (match[0] if match else 0.0) * strength * cast_weight
                )
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
                0.40 * tag_value + 0.25 * identity + 0.10 * studio_value + 0.15 * similarity_value
            ) / 0.90
            payload = {
                **scene,
                "studio": studio_payload,
                "performers": [
                    {"performer": performer_rows[str(item["id"])]["payload"]} for item in cast
                ],
                "why": self._why(scene, tag_affinity, identity, similarity_value, len(cast)),
            }
            scene_rows.append(
                {
                    "id": str(scene["id"]),
                    "payload": payload,
                    "score": score,
                    "sources": sorted(sources[str(scene["id"])]),
                }
            )
        if multi_hop_seed is not None:
            REMOTE_MULTI_HOP_WEIGHT = 0.05
            try:
                mh = MultiHopAffinity(self.connection, model_id)
            except Exception:
                mh = None
            if mh is not None:
                for scene_row in scene_rows:
                    performers = scene_row["payload"].get("performers", [])  # type: ignore[attr-defined]
                    if not isinstance(performers, list):
                        continue
                    local_ids: set[str] = set()
                    for p in performers:
                        if not isinstance(p, dict):
                            continue
                        remote = p.get("performer")
                        if not isinstance(remote, dict):
                            continue
                        pid = links["performers"].get(str(remote["id"]))
                        if pid is not None:
                            local_ids.add(pid)
                    if not local_ids:
                        continue
                    reach = mh.performer_reach(multi_hop_seed, local_ids)
                    mh_score = max(reach.values()) if reach else 0.0
                    scene_row["multi_hop_reach"] = mh_score
                    scene_row["score"] = (
                        float(scene_row["score"])  # type: ignore[arg-type]
                        + REMOTE_MULTI_HOP_WEIGHT * mh_score
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
            WITH appeal AS (
              SELECT scene_id, max(appeal) AS value FROM model_scene_lane
              WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id
            )
            SELECT p.performer_id, p.name, p.favorite,
              COALESCE(SUM(s.play_count), 0) AS play_count,
              COALESCE(SUM(CASE WHEN s.play_count > 0 THEN a.value * s.play_count END)
                / NULLIF(SUM(CASE WHEN s.play_count > 0 THEN s.play_count END), 0), 0)
                AS observed_appeal
            FROM source_performer p
            LEFT JOIN scene_performer sp USING(performer_id)
            LEFT JOIN source_scene s USING(scene_id)
            LEFT JOIN appeal a USING(scene_id)
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
    def _cast_weight(count: int) -> float:
        return min(1.0, math.sqrt(4 / max(1, count)))

    @staticmethod
    def _why(
        scene: dict[str, Any],
        tag_affinity: dict[str, float],
        identity: float,
        similarity: float,
        cast_count: int = 1,
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
        if cast_count > 8:
            reasons.append("performer evidence reduced for the large compilation cast")
        return reasons
