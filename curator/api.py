"""Transport-neutral operations used by the Stash plugin and tests."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from curator import curation
from curator.config import DEFAULT_CONFIG
from curator.expand import STASHDB, ExpandService
from curator.explanations import ExplanationService
from curator.features import FeatureStore
from curator.interactions import InteractionStore
from curator.model import ModelUpdateCoordinator, RecommendationModelStore
from curator.profiling import record_duration, span
from curator.ranking import SlateBuilder
from curator.ranking.slate import Slate
from curator.similarity import SimilarityService
from curator.storage import transaction

API_SCHEMA_VERSION = 1
DEFAULT_PLUGIN_CONFIG: dict[str, object] = {
    "page_size": 20,
    "diversity_enabled": True,
    "sync_page_size": 250,
    "debounce_ms": 2_000,
    "model_update_event_threshold": 5,
    "model_update_max_wait_minutes": 30,
    "model_update_min_interval_minutes": 60,
    "prune_tag_name": "[Prune]",
    "expand_horizon_days": 90,
    "expand_gender": "FEMALE",
    "expand_wildcard": False,
    "auto_tasks_enabled": False,
    "schedule_expand_refresh_enabled": False,
    "schedule_expand_refresh_interval_hours": 24,
    "schedule_expand_refresh_at_hour": None,
    "schedule_sync_build_enabled": False,
    "schedule_sync_build_interval_hours": 24,
    "schedule_sync_build_at_hour": None,
    "schedule_backup_enabled": False,
    "schedule_backup_interval_hours": 24,
    "schedule_backup_at_hour": None,
}


class CuratorAPI:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_slate(
        self,
        lane: str,
        count: int,
        *,
        page: int = 1,
        impression_id: str | None = None,
        context: dict[str, object] | None = None,
        now_ms: int | None = None,
        exclude_scene_ids: set[str] | None = None,
        exploration: float = 0,
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_ids: tuple[str, ...] = (),
        studio_ids: tuple[str, ...] = (),
        gender: str = "",
    ) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 500:
            raise ValueError("invalid recommendation page")
        started = time.perf_counter()
        timings: dict[str, int] = {}
        config = self.config()["config"]
        assert isinstance(config, dict)
        coordinator = ModelUpdateCoordinator(
            self.connection, debounce_ms=int(config["debounce_ms"])
        )
        model_id = RecommendationModelStore(self.connection).current_model_id()
        # Model builds can take minutes on a large library. The plugin schedules them as
        # native background tasks; slate requests always use the last published model.
        timings["model_update"] = round((time.perf_counter() - started) * 1000)
        record_duration("python", "slate.model_update", timings["model_update"])
        stage_started = time.perf_counter()
        excluded = exclude_scene_ids or set()
        start = (page - 1) * count
        end = page * count
        builder = SlateBuilder(self.connection, diversity_enabled=bool(config["diversity_enabled"]))
        has_filters = bool(include_tags or exclude_tags or performer_ids or studio_ids or gender)
        # A filtered request always recomputes total from a full candidate
        # fetch, the same way an exploration request does, since the cached
        # eligibility count doesn't know about filters.
        total = (
            builder.available_count(model_id, lane, exclude_scene_ids=excluded)
            if exploration == 0 and not has_filters
            else None
        )
        if total is None:
            if lane == "for_you":
                candidate_count = int(
                    self.connection.execute(
                        "SELECT count(DISTINCT scene_id) FROM model_scene_lane WHERE model_id=?",
                        (model_id,),
                    ).fetchone()[0]
                )
            else:
                candidate_count = int(
                    self.connection.execute(
                        """
                        SELECT count(DISTINCT scene_id) FROM model_scene_lane
                        WHERE model_id=? AND lane=?
                        """,
                        (model_id, lane),
                    ).fetchone()[0]
                )
            request_count = max(end + len(excluded), candidate_count + len(excluded))
        else:
            request_count = end + len(excluded)
        built = builder.recommend(
            lane,
            request_count,
            exploration=exploration,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            performer_ids=performer_ids,
            studio_ids=studio_ids,
            gender=gender,
        )
        available = tuple(item for item in built.items if item.scene_id not in excluded)
        if total is None:
            total = len(available)
        selected = available[start:end]
        slate = Slate(
            built.model_id,
            built.lane,
            tuple(
                replace(item, position=position)
                for position, item in enumerate(selected, start=start)
            ),
            built.diagnostics,
            built.timings_ms,
        )
        timings["ranking"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "slate.ranking", timings["ranking"])
        stage_started = time.perf_counter()
        impression_id = impression_id or str(uuid4())
        now_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        InteractionStore(self.connection).record_impression(impression_id, slate, now_ms, context)
        timings["impression"] = round((time.perf_counter() - stage_started) * 1000)
        record_duration("python", "slate.impression", timings["impression"])
        items = [{**asdict(item), "impression_id": impression_id} for item in slate.items]
        timings["total"] = round((time.perf_counter() - started) * 1000)
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": slate.model_id,
            "config_updated_at_ms": self.config()["updated_at_ms"],
            "model_pending": coordinator.status().pending,
            "rebuilding": self.connection.execute(
                """
                SELECT 1 FROM curator_job
                WHERE state='running' AND job_type IN (
                    'build', 'update-model', 'sync-build', 'full-sync-build'
                ) LIMIT 1
                """
            ).fetchone()
            is not None,
            "impression_id": impression_id,
            "lane": lane,
            "page": page,
            "page_size": count,
            "total": total,
            "has_more": total > end,
            "items": items,
            "diagnostics": list(slate.diagnostics),
            "timings_ms": timings,
            "ranking_timings_ms": slate.timings_ms,
        }

    def get_score_review(
        self,
        page: int = 1,
        count: int = 20,
        *,
        max_appeal: float = 0.0,
        order: str = "asc",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 500:
            raise ValueError("invalid score review page")
        if order not in ("asc", "desc"):
            raise ValueError("invalid score review order")
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model; run build-model first")
        start = (page - 1) * count
        end = page * count
        builder = SlateBuilder(self.connection)
        total = builder.score_review_available_count(model_id, max_appeal)
        built = builder.score_review(model_id, end, max_appeal=max_appeal, order=order)
        selected = built.items[start:end]
        slate = Slate(
            built.model_id,
            built.lane,
            tuple(
                replace(item, position=position)
                for position, item in enumerate(selected, start=start)
            ),
            built.diagnostics,
            built.timings_ms,
        )
        impression_id = str(uuid4())
        now_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        InteractionStore(self.connection).record_impression(impression_id, slate, now_ms, None)
        items = [{**asdict(item), "impression_id": impression_id} for item in slate.items]
        return {
            "items": items,
            "total": total,
            "page_size": count,
            "has_more": total > end,
            "page": page,
            "model_version": model_id,
        }

    def inspector(self, entity_type: str, entity_id: str) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        if entity_type == "scene":
            score = (
                RecommendationModelStore(self.connection)
                .scores(model_id, {entity_id})
                .get(entity_id)
            )
            if score is None:
                raise ValueError(f"unknown scene: {entity_id}")
            return {
                "schema_version": API_SCHEMA_VERSION,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "model_id": model_id,
                "score": asdict(score),
                "explanation": self.explanation(entity_id),
            }
        if entity_type == "performer":
            row = self.connection.execute(
                "SELECT * FROM source_performer WHERE performer_id=?", (entity_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown performer: {entity_id}")
            feature_version = self.connection.execute(
                "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
            ).fetchone()[0]
            matches = FeatureStore(self.connection).similar_performers(
                str(feature_version),
                entity_id,
                count=10,
                block_weights=dict(DEFAULT_CONFIG.feature.performer_block_weights),
            )
            return {
                "schema_version": API_SCHEMA_VERSION,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "model_id": model_id,
                "profile": dict(row),
                "similar": [
                    {
                        "performer_id": performer_id,
                        "similarity": result.similarity,
                        "blocks": result.block_similarities,
                    }
                    for performer_id, result in matches
                ],
            }
        raise ValueError(f"unsupported inspector entity type: {entity_type}")

    def similar(
        self,
        entity_type: str,
        entity_id: str,
        count: int = 20,
        *,
        page: int = 1,
        impression_id: str | None = None,
        now_ms: int | None = None,
        gender: str = "",
        include_tags: tuple[str, ...] = (),
        exclude_tags: tuple[str, ...] = (),
        performer_ids: tuple[str, ...] = (),
        studio_ids: tuple[str, ...] = (),
        favorite_only: bool = False,
        minimum_similarity: float = 0.18,
        exclude_scene_ids: set[str] | None = None,
    ) -> dict[str, object]:
        if page < 1 or not 1 <= count <= 500:
            raise ValueError("invalid Similar page")
        if not 0 <= minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be between 0 and 1")
        start = (page - 1) * count
        end = page * count
        excluded = exclude_scene_ids or set()
        requested = end + 1 + len(excluded)
        service = SimilarityService(self.connection)
        if entity_type == "scene":
            results = service.scenes(
                entity_id,
                requested,
                gender,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                performer_ids=performer_ids,
                studio_ids=studio_ids,
                favorite_only=favorite_only,
                minimum_similarity=minimum_similarity,
            )
            table, id_column, label_column = "source_scene", "scene_id", "title"
        elif entity_type == "performer":
            results = service.performers(entity_id, requested, gender)
            table, id_column, label_column = "source_performer", "performer_id", "name"
        else:
            raise ValueError(f"unsupported similar entity type: {entity_type}")
        raw_results = results
        available = tuple(item for item in raw_results if item.entity_id not in excluded)
        results = available[start:end]
        total = max(
            0, service.total_count - len(excluded & {item.entity_id for item in raw_results})
        )
        labels = {
            str(row[id_column]): str(row[label_column] or "")
            for row in self.connection.execute(f"SELECT {id_column}, {label_column} FROM {table}")
        }
        impression_id = impression_id or str(uuid4())
        if entity_type == "scene":
            self.connection.execute("PRAGMA busy_timeout = 100")
            try:
                InteractionStore(self.connection).record_ranked_impression(
                    impression_id,
                    "similar",
                    service.model_id,
                    (
                        (item.entity_id, position, item.rank_score, item.relationships)
                        for position, item in enumerate(results, start=start)
                    ),
                    now_ms if now_ms is not None else time.time_ns() // 1_000_000,
                    {"provenance": "similar", "source_scene_id": entity_id},
                )
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).casefold():
                    raise
                impression_id = None
            finally:
                self.connection.execute("PRAGMA busy_timeout = 30000")
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": service.model_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "impression_id": impression_id if entity_type == "scene" else None,
            "page": page,
            "page_size": count,
            "total": total,
            "has_more": total > end,
            "timings_ms": service.timings_ms,
            "items": [
                {
                    **asdict(item),
                    "label": labels.get(item.entity_id, ""),
                    "position": position,
                }
                for position, item in enumerate(results, start=start)
            ],
        }

    def explanation(self, scene_id: str) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        explanation = ExplanationService(self.connection).explain_scene(model_id, scene_id)
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": model_id,
            "scene_id": scene_id,
            "summary": explanation.summary,
            "reasons": [asdict(reason) for reason in explanation.all_reasons],
            "supporting_reasons": [asdict(reason) for reason in explanation.selected_reasons],
        }

    def recommendation_history(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        lane: str | None = None,
    ) -> dict[str, object]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("invalid recommendation history page")
        if lane and lane not in {"for_you", "best_bets", "revisit", "stretch", "adventure"}:
            raise ValueError("unknown recommendation lane")
        where = "WHERE h.lane=?" if lane else ""
        parameters: tuple[object, ...] = (lane,) if lane else ()
        model_id = RecommendationModelStore(self.connection).current_model_id()
        total = int(
            self.connection.execute(
                f"SELECT count(*) FROM recommendation_history h {where}",
                parameters,
            ).fetchone()[0]
        )
        rows = self.connection.execute(
            f"""
            SELECT h.history_id, h.scene_id, h.impression_id, h.lane, h.shown_at_ms,
                   i.reason_snapshot_json,
                   EXISTS(
                     SELECT 1 FROM model_scene_score score
                     WHERE score.model_id=? AND score.scene_id=h.scene_id
                   ) AS current_model
            FROM recommendation_history h
            LEFT JOIN impression_item i
              ON i.impression_id=h.impression_id AND i.scene_id=h.scene_id
            {where}
            ORDER BY h.shown_at_ms DESC, h.history_id DESC LIMIT ? OFFSET ?
            """,
            (model_id, *parameters, page_size, (page - 1) * page_size),
        )
        items = []
        for row in rows:
            item = dict(row)
            snapshot = item.pop("reason_snapshot_json")
            item["reason_snapshot"] = json.loads(str(snapshot)) if snapshot else []
            items.append(item)
        return {
            "schema_version": API_SCHEMA_VERSION,
            "page": page,
            "page_size": page_size,
            "total": total,
            "lane": lane,
            "items": items,
        }

    def expand(
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
        minimum_score: float = -1.0,
        count: int = 50,
        links: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, object]:
        return ExpandService(self.connection).results(
            entity_type,
            page=page,
            sort=sort,
            performer_id=performer_id,
            favorite_only=favorite_only,
            gender=gender,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            performer_query=performer_query,
            studio_query=studio_query,
            performer_names=performer_names,
            studio_names=studio_names,
            hide_phash_matches=hide_phash_matches,
            minimum_score=minimum_score,
            count=count,
            links=links,
        )

    def expand_shortlist(self, page: int = 1, page_size: int = 20) -> dict[str, object]:
        return ExpandService(self.connection).shortlist_results(page=page, count=page_size)

    def update_shortlist(self, entity_type: str, external_id: str, selected: bool) -> None:
        ExpandService(self.connection).shortlist(entity_type, external_id, selected)

    def external_similar(self, entity_type: str, entity_id: str) -> dict[str, object]:
        return ExpandService(self.connection).similar(entity_type, entity_id)

    def submit_feedback(self, entries: list[dict[str, Any]]) -> dict[str, object]:
        inserted = InteractionStore(self.connection).submit_feedback(entries)
        return {"schema_version": API_SCHEMA_VERSION, "accepted": inserted}

    def feedback_history(self, page: int = 1, page_size: int = 20) -> dict[str, object]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("invalid feedback history page")
        where = "feedback_type <> 'reversal'"
        total = int(
            self.connection.execute(f"SELECT count(*) FROM feedback WHERE {where}").fetchone()[0]
        )
        rows = self.connection.execute(
            f"""
            SELECT feedback_id, scene_id, feedback_type, value, occurred_at_ms,
                   reversed_by_id
            FROM feedback WHERE {where}
            ORDER BY occurred_at_ms DESC, feedback_id DESC LIMIT ? OFFSET ?
            """,
            (page_size, (page - 1) * page_size),
        )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [dict(row) for row in rows],
        }

    def correct_feedback(
        self,
        feedback_id: str,
        correction_id: str,
        feedback_type: str | None,
        *,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        InteractionStore(self.connection).correct_feedback(
            feedback_id,
            correction_id,
            feedback_type,
            now_ms if now_ms is not None else time.time_ns() // 1_000_000,
        )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "feedback_id": feedback_id,
            "correction_id": correction_id,
            "feedback_type": feedback_type,
        }

    def submit_tag_preferences(self, entries: list[dict[str, Any]]) -> dict[str, object]:
        inserted = InteractionStore(self.connection).submit_tag_preferences(entries)
        return {"schema_version": API_SCHEMA_VERSION, "accepted": inserted}

    def submit_term_preferences(self, entries: list[dict[str, Any]]) -> dict[str, object]:
        inserted = InteractionStore(self.connection).submit_term_preferences(entries)
        return {"schema_version": API_SCHEMA_VERSION, "accepted": inserted}

    def get_scene_tag_choices(self, scene_id: str) -> dict[str, object]:
        if not scene_id:
            raise ValueError("scene_id is required")
        config_version = f"cfg-{DEFAULT_CONFIG.feature_fingerprint()[:20]}"
        items: list[dict[str, object]] = []
        for row in self.connection.execute(
            """
            SELECT t.tag_id, t.name, p.value AS direct_value, p.blocked AS direct_blocked
            FROM scene_tag st
            JOIN source_tag t ON t.tag_id=st.tag_id
            JOIN tag_role r ON r.tag_id=t.tag_id AND r.config_version=?
            LEFT JOIN direct_tag_preference p ON p.tag_id=t.tag_id
            WHERE st.scene_id=?
            GROUP BY t.tag_id
            ORDER BY t.name COLLATE NOCASE, t.tag_id
            """,
            (config_version, scene_id),
        ):
            items.append(
                {
                    "tag_id": str(row["tag_id"]),
                    "name": str(row["name"] or row["tag_id"]),
                    "direct_value": (
                        float(row["direct_value"]) if row["direct_value"] is not None else None
                    ),
                    "direct_blocked": bool(row["direct_blocked"]),
                }
            )
        return {"schema_version": API_SCHEMA_VERSION, "items": items}

    def get_scene_description_tokens(self, scene_id: str) -> dict[str, object]:
        if not scene_id:
            raise ValueError("scene_id is required")
        feature_version = FeatureStore(self.connection).current_version()
        direct: dict[str, tuple[float | None, bool]] = {}
        for row in self.connection.execute(
            "SELECT term, value, blocked FROM direct_term_preference"
        ):
            direct[str(row["term"])] = (float(row["value"]), bool(row["blocked"]))
        items: list[dict[str, object]] = []
        if feature_version is not None:
            for row in self.connection.execute(
                """
                SELECT fd.name, fd.metadata_json
                FROM entity_feature ef
                JOIN feature_definition fd ON fd.feature_id=ef.feature_id
                WHERE ef.feature_version=? AND ef.entity_type='scene' AND ef.entity_id=?
                  AND fd.family='content' AND fd.name LIKE 'desc:%'
                ORDER BY fd.name
                """,
                (feature_version, scene_id),
            ):
                term = str(row["name"])[len("desc:") :]
                metadata = json.loads(str(row["metadata_json"] or "{}"))
                direct_value, direct_blocked = direct.get(term, (None, False))
                items.append(
                    {
                        "term": term,
                        "document_frequency": int(metadata.get("document_frequency", 0)),
                        "direct_value": direct_value,
                        "direct_blocked": direct_blocked,
                    }
                )
        return {"schema_version": API_SCHEMA_VERSION, "items": items}

    def taste_profile(self) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        feature_version = str(
            self.connection.execute(
                "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
            ).fetchone()[0]
        )
        direct: dict[str, tuple[float | None, bool]] = {}
        for row in self.connection.execute(
            "SELECT tag_id, value, blocked FROM direct_tag_preference"
        ):
            direct[str(row["tag_id"])] = (float(row["value"]), bool(row["blocked"]))
        items: list[dict[str, object]] = []
        config_version = f"cfg-{DEFAULT_CONFIG.feature_fingerprint()[:20]}"
        for row in self.connection.execute(
            """
            WITH scene_counts AS (
              SELECT tag_id, count(DISTINCT scene_id) AS scene_count
              FROM scene_tag WHERE provenance='scene' GROUP BY tag_id
            )
            SELECT t.tag_id, t.name, r.role, coalesce(sc.scene_count, 0) AS scene_count,
                   a.affinity, a.confidence, a.effective_support
            FROM source_tag t
            JOIN tag_role r ON r.tag_id=t.tag_id AND r.config_version=?
            LEFT JOIN scene_counts sc ON sc.tag_id=t.tag_id
            LEFT JOIN feature_definition d
              ON d.feature_version=? AND d.family='content' AND d.name='tag:' || t.tag_id
            LEFT JOIN feature_affinity a
              ON a.feature_id=d.feature_id AND a.model_id=?
            ORDER BY t.name, t.tag_id
            """,
            (config_version, feature_version, model_id),
        ):
            tag_id = str(row["tag_id"])
            scene_count = int(row["scene_count"])
            affinity = float(row["affinity"] or 0)
            confidence = float(row["confidence"] or 0)
            direct_value, direct_blocked = direct.get(tag_id, (None, False))
            prompt = None
            if direct_value is None and row["role"] == "content" and scene_count >= 2:
                prompt = "belief" if confidence >= 0.35 and abs(affinity) >= 0.15 else "uncertain"
            items.append(
                {
                    "tag_id": tag_id,
                    "name": str(row["name"] or tag_id),
                    "inferred_value": affinity,
                    "confidence": confidence,
                    "support": float(row["effective_support"] or 0),
                    "scene_count": scene_count,
                    "direct_value": direct_value,
                    "direct_blocked": direct_blocked,
                    "prompt": prompt,
                }
            )
        items.sort(
            key=lambda item: (
                item["prompt"] is None,
                item["prompt"] == "uncertain",
                not (float(str(item["inferred_value"])) > 0),
                -abs(float(str(item["inferred_value"]))),
                str(item["name"]).casefold(),
                str(item["tag_id"]),
            )
        )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": model_id,
            "items": items,
        }

    def external_tag_choices(self, tags: list[dict[str, Any]]) -> dict[str, object]:
        if len(tags) > 100:
            raise ValueError("at most 100 external tags are supported")
        requested = [
            (str(item.get("id") or ""), str(item.get("name") or "").strip())
            for item in tags
            if isinstance(item, dict) and (item.get("id") or item.get("name"))
        ]
        config_version = f"cfg-{DEFAULT_CONFIG.feature_fingerprint()[:20]}"
        rows = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT t.tag_id, t.name, p.value AS direct_value,
                       p.blocked AS direct_blocked, ids.stash_id
                FROM source_tag t
                JOIN tag_role r
                  ON r.tag_id=t.tag_id AND r.config_version=?
                LEFT JOIN direct_tag_preference p ON p.tag_id=t.tag_id
                LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
                  AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
                ORDER BY t.tag_id
                """,
                (config_version, STASHDB),
            )
        ]
        by_external = {str(row["stash_id"]): row for row in rows if row["stash_id"]}
        by_name: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_name.setdefault(str(row["name"] or "").casefold(), []).append(row)
        choices: list[dict[str, object]] = []
        seen: set[str] = set()
        for external_id, name in requested:
            matched = by_external.get(external_id)
            if matched is None:
                matches = by_name.get(name.casefold(), [])
                matched = matches[0] if len(matches) == 1 else None
            if matched is None:
                # Try taxonomy alias → local tag mapping
                snapshot = self.connection.execute(
                    "SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'"
                ).fetchone()
                if snapshot:
                    tax_row = self.connection.execute(
                        """
                        SELECT ttm.local_tag_id
                        FROM taxonomy_tag tt
                        JOIN tag_taxonomy_match ttm
                          ON ttm.snapshot_id=tt.snapshot_id AND ttm.external_tag_id=tt.tag_id
                        WHERE tt.snapshot_id=? AND lower(tt.name)=?
                        UNION
                        SELECT ttm.local_tag_id
                        FROM taxonomy_tag_alias tta
                        JOIN taxonomy_tag tt USING(snapshot_id, tag_id)
                        JOIN tag_taxonomy_match ttm
                          ON ttm.snapshot_id=tt.snapshot_id AND ttm.external_tag_id=tt.tag_id
                        WHERE tta.snapshot_id=? AND lower(tta.alias)=?
                        """,
                        (snapshot[0], name.casefold(), snapshot[0], name.casefold()),
                    ).fetchone()
                    if tax_row:
                        local_id = str(tax_row["local_tag_id"])
                        matched = next((r for r in rows if str(r["tag_id"]) == local_id), None)
            if matched is None or str(matched["tag_id"]) in seen:
                continue
            seen.add(str(matched["tag_id"]))
            choices.append(
                {
                    "tag_id": str(matched["tag_id"]),
                    "name": str(matched["name"] or matched["tag_id"]),
                    "direct_value": (
                        float(str(matched["direct_value"]))
                        if matched["direct_value"] is not None
                        else None
                    ),
                    "direct_blocked": bool(matched["direct_blocked"]),
                }
            )
        return {"schema_version": API_SCHEMA_VERSION, "items": choices}

    def tag_sentiment_follow_up(self, scene_id: str, limit: int = 3) -> dict[str, object]:
        if not scene_id or not 1 <= limit <= 3:
            raise ValueError("scene_id and a limit from 1 to 3 are required")
        scene_tags = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT tag_id FROM scene_tag
                WHERE scene_id=? AND provenance='scene'
                """,
                (scene_id,),
            )
        }
        if (
            not scene_tags
            and self.connection.execute(
                "SELECT 1 FROM source_scene WHERE scene_id=?", (scene_id,)
            ).fetchone()
            is None
        ):
            raise ValueError(f"unknown scene: {scene_id}")
        total_scenes = int(
            self.connection.execute("SELECT count(*) FROM source_scene").fetchone()[0]
        )
        profile_items = self.taste_profile()["items"]
        assert isinstance(profile_items, list)
        candidates = [
            item
            for item in profile_items
            if isinstance(item, dict)
            and str(item["tag_id"]) in scene_tags
            and item["direct_value"] is None
            # ponytail: library-wide prevalence is the existing cheap generic-tag signal.
            and not (
                int(item["scene_count"]) >= 5 and int(item["scene_count"]) >= 0.8 * total_scenes
            )
        ]
        candidates.sort(
            key=lambda item: (
                0
                if float(str(item["inferred_value"])) > 0.05
                else (
                    1
                    if float(str(item["confidence"])) < 0.35
                    or abs(float(str(item["inferred_value"]))) < 0.15
                    else 2
                ),
                -abs(float(str(item["inferred_value"]))),
                str(item["name"]).casefold(),
                str(item["tag_id"]),
            )
        )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "scene_id": scene_id,
            "items": candidates[:limit],
        }

    def curation_batch(
        self,
        mode: str,
        base_tag_id: str | None,
        context_tag_id: str | None,
        budget: int = 20,
    ) -> dict[str, object]:
        return curation.create_batch(self.connection, mode, base_tag_id, context_tag_id, budget)

    def submit_curation_ratings(
        self, batch_id: str, ratings: list[dict[str, Any]]
    ) -> dict[str, object]:
        return curation.submit_ratings(self.connection, batch_id, ratings)

    def curation_verdict(self, batch_id: str) -> dict[str, object]:
        return curation.verdict(self.connection, batch_id)

    def tag_context_candidates(self, tag_id: str, min_support: int = 20) -> dict[str, object]:
        return curation.tag_context_candidates(self.connection, tag_id, min_support)

    def curation_picks(
        self,
        dimension: str,
        budget: int = 10,
        base_tag_id: str | None = None,
        context_tag_id: str | None = None,
        performer_id: str | None = None,
    ) -> dict[str, object]:
        return curation.create_pair_round(
            self.connection,
            dimension,
            budget,
            base_tag_id,
            context_tag_id,
            performer_id,
        )

    def submit_curation_picks(
        self, round_id: str, picks: list[dict[str, Any]]
    ) -> dict[str, object]:
        return curation.submit_picks(self.connection, round_id, picks)

    def curation_pair_verdict(self, round_id: str) -> dict[str, object]:
        return curation.pair_verdict(self.connection, round_id)

    def curation_impact(self) -> dict[str, object]:
        return curation.curation_impact(self.connection)

    def submit_events(self, entries: list[dict[str, Any]]) -> dict[str, object]:
        store = InteractionStore(self.connection)
        impressions = [
            entry for entry in entries if entry.get("event_type") == "qualified_impression"
        ]
        sessions = [entry for entry in entries if entry.get("event_type") != "qualified_impression"]
        inserted = store.qualify_impressions(impressions) + store.submit_sessions(sessions)
        return {"schema_version": API_SCHEMA_VERSION, "accepted": inserted}

    def pruning_queue(self) -> dict[str, object]:
        rows = self.connection.execute(
            """
            SELECT p.scene_id, p.state, p.created_at_ms, p.updated_at_ms, p.reason,
                   s.title
            FROM pruning_candidate p LEFT JOIN source_scene s USING(scene_id)
            WHERE p.state IN ('review', 'remove') ORDER BY p.updated_at_ms DESC
            """
        )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "items": [dict(row) for row in rows],
        }

    def prune_candidates(
        self,
        view: str = "candidates",
        *,
        aggressiveness: float = 0.0,
        page: int = 1,
        page_size: int = 20,
        tag_name: str = "[Prune]",
    ) -> dict[str, object]:
        if view not in {"candidates", "tagged", "explicit", "suspects"}:
            raise ValueError("unknown prune view")
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("invalid prune page")
        if not 0 <= aggressiveness <= 1:
            raise ValueError("aggressiveness must be between 0 and 1")
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        with span("python", "prune.tagged"):
            tagged = {
                str(row[0])
                for row in self.connection.execute(
                    """
                    SELECT scene_id FROM scene_tag WHERE tag_id IN (
                      SELECT tag_id FROM source_tag WHERE lower(name)=lower(?)
                    )
                    """,
                    (tag_name,),
                )
            }
        states = {
            str(row["scene_id"]): str(row["state"])
            for row in self.connection.execute("SELECT scene_id, state FROM pruning_candidate")
        }
        with span("python", "prune.explicit"):
            explicit = {
                str(row[0])
                for row in self.connection.execute(
                    """
                    SELECT f.scene_id FROM feedback f
                    WHERE f.reversed_by_id IS NULL
                    AND f.feedback_type IN ('thumb_down', 'never_show')
                    AND f.occurred_at_ms=(
                      SELECT max(f2.occurred_at_ms) FROM feedback f2
                      WHERE f2.scene_id=f.scene_id AND f2.reversed_by_id IS NULL
                      AND f2.feedback_type IN ('thumb_up', 'thumb_down', 'never_show')
                    )
                    """
                )
            } | {scene_id for scene_id, state in states.items() if state == "review"}
        appeal_limit = -0.18 + 0.13 * aggressiveness
        confidence_limit = 0.55 - 0.20 * aggressiveness
        with span("python", "prune.scores"):
            scores = (
                {
                    str(row["scene_id"]): row
                    for row in self.connection.execute(
                        """
                        SELECT scene_id, appeal, confidence FROM model_scene_score
                        WHERE model_id=? AND appeal<=? AND confidence>=?
                        UNION
                        SELECT scene_id, appeal, confidence FROM model_scene_score
                        WHERE model_id=? AND scene_id IN (
                          SELECT scene_id FROM pruning_candidate WHERE state='review'
                        )
                        """,
                        (model_id, appeal_limit, confidence_limit, model_id),
                    )
                }
                if view != "tagged"
                else {}
            )
        suspects = {
            scene_id
            for scene_id, score in scores.items()
            if float(score["appeal"]) <= appeal_limit
            and float(score["confidence"]) >= confidence_limit
            and states.get(scene_id) != "keep"
        }
        selected = {
            "candidates": explicit | suspects,
            "tagged": tagged,
            "explicit": explicit,
            "suspects": suspects,
        }[view] - (tagged if view != "tagged" else set())
        ordered = sorted(
            selected,
            key=lambda scene_id: (
                scene_id not in explicit,
                float(scores[scene_id]["appeal"]) if scene_id in scores else 0,
                scene_id,
            ),
        )
        start = (page - 1) * page_size
        page_ids = ordered[start : start + page_size]
        rows = {
            str(row["scene_id"]): dict(row)
            for row in self.connection.execute(
                f"SELECT scene_id, title, play_count FROM source_scene WHERE scene_id IN "
                f"({','.join('?' for _ in page_ids)})",
                page_ids,
            )
        }
        items = []
        for scene_id in page_ids:
            score = scores.get(scene_id)
            evidence = []
            if scene_id in explicit:
                evidence.append("Explicit negative feedback")
            if scene_id in suspects:
                evidence.append("Low predicted Appeal with supporting evidence")
            items.append(
                {
                    **rows.get(scene_id, {"scene_id": scene_id, "title": "", "play_count": 0}),
                    "appeal": float(score["appeal"]) if score else None,
                    "confidence": float(score["confidence"]) if score else None,
                    "tagged": scene_id in tagged,
                    "explicit": scene_id in explicit,
                    "suspect": scene_id in suspects,
                    "evidence": evidence,
                }
            )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": model_id,
            "view": view,
            "aggressiveness": aggressiveness,
            "tag_name": tag_name,
            "page": page,
            "page_size": page_size,
            "total": len(ordered),
            "items": items,
        }

    def dismiss_prune_candidate(self, scene_id: str, now_ms: int | None = None) -> None:
        now_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
                VALUES (?, 'keep', ?, ?, 'Dismissed model suspect')
                ON CONFLICT(scene_id) DO UPDATE SET state='keep',
                    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
                """,
                (scene_id, now_ms, now_ms),
            )

    def record_prune_tags(
        self, scene_ids: list[str], tagged: bool, tag_id: str, tag_name: str
    ) -> None:
        now_ms = time.time_ns() // 1_000_000
        with transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, 'curator-prune')
                ON CONFLICT(tag_id) DO UPDATE SET name=excluded.name
                """,
                (tag_id, tag_name),
            )
            if tagged:
                self.connection.executemany(
                    """
                    INSERT OR IGNORE INTO scene_tag(scene_id, tag_id, provenance)
                    VALUES (?, ?, 'scene')
                    """,
                    ((scene_id, tag_id) for scene_id in scene_ids),
                )
                self.connection.executemany(
                    """
                    INSERT INTO pruning_candidate(
                        scene_id, state, created_at_ms, updated_at_ms, reason
                    )
                    VALUES (?, 'remove', ?, ?, ?)
                    ON CONFLICT(scene_id) DO UPDATE SET state='remove',
                        updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
                    """,
                    ((scene_id, now_ms, now_ms, f"Tagged {tag_name}") for scene_id in scene_ids),
                )
            else:
                self.connection.executemany(
                    "DELETE FROM scene_tag WHERE scene_id=? AND tag_id=?",
                    ((scene_id, tag_id) for scene_id in scene_ids),
                )
                self.connection.executemany(
                    "DELETE FROM pruning_candidate WHERE scene_id=? AND state='remove'",
                    ((scene_id,) for scene_id in scene_ids),
                )

    def reconcile_prune_tag(self, tag_name: str) -> bool:
        tagged = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT st.scene_id FROM scene_tag st JOIN source_tag t USING(tag_id)
                WHERE lower(t.name)=lower(?)
                """,
                (tag_name,),
            )
        }
        now_ms = time.time_ns() // 1_000_000
        reason = f"Tagged {tag_name}"
        with transaction(self.connection):
            deleted = self.connection.execute(
                """
                DELETE FROM pruning_candidate
                WHERE state='remove' AND scene_id NOT IN (
                    SELECT st.scene_id FROM scene_tag st JOIN source_tag t USING(tag_id)
                    WHERE lower(t.name)=lower(?)
                )
                """,
                (tag_name,),
            ).rowcount
            changed = deleted > 0
            for scene_id in tagged:
                cursor = self.connection.execute(
                    """
                INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
                VALUES (?, 'remove', ?, ?, ?)
                ON CONFLICT(scene_id) DO UPDATE SET state='remove',
                    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
                WHERE pruning_candidate.state!='remove'
                    OR pruning_candidate.reason IS NOT excluded.reason
                """,
                    (scene_id, now_ms, now_ms, reason),
                )
                changed = changed or cursor.rowcount > 0
        return changed

    def update_pruning(
        self, scene_id: str, state: str, now_ms: int | None = None
    ) -> dict[str, object]:
        if state not in {"keep", "remove"}:
            raise ValueError("pruning state must be keep or remove")
        with transaction(self.connection):
            cursor = self.connection.execute(
                """
                UPDATE pruning_candidate SET state=?, updated_at_ms=? WHERE scene_id=?
                """,
                (
                    state,
                    now_ms if now_ms is not None else time.time_ns() // 1_000_000,
                    scene_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"scene is not in the pruning queue: {scene_id}")
            ModelUpdateCoordinator(self.connection).request("pruning_decision")
        return {"schema_version": API_SCHEMA_VERSION, "scene_id": scene_id, "state": state}

    def exclusions(self) -> dict[str, object]:
        rows = self.connection.execute(
            """
            SELECT e.entity_id AS scene_id, e.created_at_ms, s.title
            FROM exclusion e LEFT JOIN source_scene s ON s.scene_id=e.entity_id
            WHERE e.entity_type='scene' AND e.exclusion_type='never_show'
              AND e.reversed_at_ms IS NULL
            ORDER BY e.created_at_ms DESC
            """
        )
        return {"schema_version": API_SCHEMA_VERSION, "items": [dict(row) for row in rows]}

    def reverse_exclusion(self, scene_id: str, now_ms: int | None = None) -> dict[str, object]:
        with transaction(self.connection):
            cursor = self.connection.execute(
                """
                UPDATE exclusion SET reversed_at_ms=?
                WHERE entity_type='scene' AND entity_id=? AND exclusion_type='never_show'
                  AND reversed_at_ms IS NULL
                """,
                (now_ms if now_ms is not None else time.time_ns() // 1_000_000, scene_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"scene is not actively excluded: {scene_id}")
            ModelUpdateCoordinator(self.connection).request("exclusion_reversed")
        return {"schema_version": API_SCHEMA_VERSION, "scene_id": scene_id, "reversed": True}

    def config(self) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT config_json, updated_at_ms FROM curator_config WHERE singleton=1"
        ).fetchone()
        stored = json.loads(row["config_json"])
        return {
            "schema_version": API_SCHEMA_VERSION,
            "config": {**DEFAULT_PLUGIN_CONFIG, **stored},
            "updated_at_ms": int(row["updated_at_ms"]),
        }

    def update_config(
        self, values: dict[str, object], now_ms: int | None = None
    ) -> dict[str, object]:
        allowed = {
            "page_size",
            "diversity_enabled",
            "sync_page_size",
            "debounce_ms",
            "model_update_event_threshold",
            "model_update_max_wait_minutes",
            "model_update_min_interval_minutes",
            "prune_tag_name",
            "expand_horizon_days",
            "expand_gender",
            "expand_wildcard",
            "auto_tasks_enabled",
            "schedule_expand_refresh_enabled",
            "schedule_expand_refresh_interval_hours",
            "schedule_expand_refresh_at_hour",
            "schedule_sync_build_enabled",
            "schedule_sync_build_interval_hours",
            "schedule_sync_build_at_hour",
            "schedule_backup_enabled",
            "schedule_backup_interval_hours",
            "schedule_backup_at_hour",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
        current = self.config()["config"]
        assert isinstance(current, dict)
        merged = {**current, **values}
        self._validate_config(merged)
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1",
                (
                    json.dumps(merged, sort_keys=True, separators=(",", ":")),
                    now_ms if now_ms is not None else time.time_ns() // 1_000_000,
                ),
            )
        return self.config()

    @staticmethod
    def _validate_config(values: dict[str, object]) -> None:
        diversity = values.get("diversity_enabled")
        if diversity is not None and not isinstance(diversity, bool):
            raise ValueError("diversity_enabled must be true or false")
        for key in (
            "schedule_expand_refresh_at_hour",
            "schedule_sync_build_at_hour",
            "schedule_backup_at_hour",
        ):
            value = values.get(key)
            if value is not None and (not isinstance(value, int) or not 0 <= value <= 23):
                raise ValueError(f"{key} must be an integer from 0 to 23")
        for key in ("page_size", "sync_page_size"):
            value = values.get(key)
            if value is not None and (not isinstance(value, int) or not 1 <= value <= 500):
                raise ValueError(f"{key} must be an integer from 1 to 500")
        debounce = values.get("debounce_ms")
        if debounce is not None and (not isinstance(debounce, int) or not 0 <= debounce <= 60_000):
            raise ValueError("debounce_ms must be an integer from 0 to 60000")
        threshold = values.get("model_update_event_threshold")
        if threshold is not None and (not isinstance(threshold, int) or not 1 <= threshold <= 100):
            raise ValueError("model_update_event_threshold must be an integer from 1 to 100")
        for key in ("model_update_max_wait_minutes", "model_update_min_interval_minutes"):
            value = values.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or not 1 <= float(value) <= 24 * 60
            ):
                raise ValueError(f"{key} must be between 1 and 1440")
        prune_tag = values.get("prune_tag_name")
        if prune_tag is not None and (
            not isinstance(prune_tag, str) or not prune_tag.strip() or len(prune_tag) > 100
        ):
            raise ValueError("prune_tag_name must be a non-empty string up to 100 characters")
        horizon = values.get("expand_horizon_days")
        if horizon is not None and (not isinstance(horizon, int) or not 1 <= horizon <= 3650):
            raise ValueError("expand_horizon_days must be an integer from 1 to 3650")
        gender = values.get("expand_gender")
        if gender is not None and not isinstance(gender, str):
            raise ValueError("expand_gender must be a string")
        wildcard = values.get("expand_wildcard")
        if wildcard is not None and not isinstance(wildcard, bool):
            raise ValueError("expand_wildcard must be true or false")
