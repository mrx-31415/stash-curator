"""Transport-neutral operations used by the Stash plugin and tests."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from curator.config import DEFAULT_CONFIG
from curator.expand import ExpandService
from curator.explanations import ExplanationService
from curator.features import FeatureStore
from curator.interactions import InteractionStore
from curator.model import ModelUpdateCoordinator, RecommendationModelStore
from curator.ranking import SlateBuilder
from curator.ranking.slate import Slate
from curator.similarity import SimilarityService
from curator.storage import transaction

API_SCHEMA_VERSION = 1
DEFAULT_PLUGIN_CONFIG: dict[str, object] = {
    "page_size": 20,
    "sync_page_size": 250,
    "debounce_ms": 2_000,
    "model_update_event_threshold": 5,
    "model_update_max_wait_minutes": 30,
    "model_update_min_interval_minutes": 60,
    "prune_tag_name": "[Prune]",
    "expand_horizon_days": 90,
    "expand_gender": "FEMALE",
    "expand_wildcard": False,
}


class CuratorAPI:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_slate(
        self,
        lane: str,
        count: int,
        *,
        impression_id: str | None = None,
        context: dict[str, object] | None = None,
        now_ms: int | None = None,
        exclude_scene_ids: set[str] | None = None,
        exploration: float = 0,
    ) -> dict[str, object]:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        config = self.config()["config"]
        assert isinstance(config, dict)
        coordinator = ModelUpdateCoordinator(
            self.connection, debounce_ms=int(config["debounce_ms"])
        )
        # Model builds can take minutes on a large library. The plugin schedules them as
        # native background tasks; slate requests always use the last published model.
        timings["model_update"] = round((time.perf_counter() - started) * 1000)
        stage_started = time.perf_counter()
        excluded = exclude_scene_ids or set()
        built = SlateBuilder(self.connection).recommend(
            lane, count + len(excluded), exploration=exploration
        )
        selected = tuple(item for item in built.items if item.scene_id not in excluded)[:count]
        slate = Slate(
            built.model_id,
            built.lane,
            tuple(replace(item, position=position) for position, item in enumerate(selected)),
            built.diagnostics,
            built.timings_ms,
        )
        timings["ranking"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        impression_id = impression_id or str(uuid4())
        now_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        InteractionStore(self.connection).record_impression(impression_id, slate, now_ms, context)
        timings["impression"] = round((time.perf_counter() - stage_started) * 1000)
        stage_started = time.perf_counter()
        explanations = ExplanationService(self.connection)
        items = []
        for item in slate.items:
            explanation = explanations.explain_recommendation(item)
            payload = asdict(item)
            payload["impression_id"] = impression_id
            payload["explanation"] = explanation.summary
            payload["supporting_reasons"] = [
                {
                    "code": reason.code,
                    "direction": reason.direction,
                    "magnitude": reason.magnitude,
                    "subject_type": reason.subject_type,
                    "subject_id": reason.subject_id,
                    "detail": reason.detail,
                }
                for reason in explanation.selected_reasons
            ]
            items.append(payload)
        timings["explanations"] = round((time.perf_counter() - stage_started) * 1000)
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
            "items": items,
            "diagnostics": list(slate.diagnostics),
            "timings_ms": timings,
            "ranking_timings_ms": slate.timings_ms,
        }

    def inspector(self, entity_type: str, entity_id: str) -> dict[str, object]:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model")
        if entity_type == "scene":
            score = RecommendationModelStore(self.connection).scores(model_id).get(entity_id)
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
        impression_id: str | None = None,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        if not 1 <= count <= 100:
            raise ValueError("count must be between 1 and 100")
        service = SimilarityService(self.connection)
        if entity_type == "scene":
            results = service.scenes(entity_id, count)
            table, id_column, label_column = "source_scene", "scene_id", "title"
        elif entity_type == "performer":
            results = service.performers(entity_id, count)
            table, id_column, label_column = "source_performer", "performer_id", "name"
        else:
            raise ValueError(f"unsupported similar entity type: {entity_type}")
        labels = {
            str(row[id_column]): str(row[label_column] or "")
            for row in self.connection.execute(f"SELECT {id_column}, {label_column} FROM {table}")
        }
        impression_id = impression_id or str(uuid4())
        if entity_type == "scene":
            InteractionStore(self.connection).record_ranked_impression(
                impression_id,
                "similar",
                service.model_id,
                (
                    (item.entity_id, position, item.rank_score, item.relationships)
                    for position, item in enumerate(results)
                ),
                now_ms if now_ms is not None else time.time_ns() // 1_000_000,
                {"provenance": "similar", "source_scene_id": entity_id},
            )
        return {
            "schema_version": API_SCHEMA_VERSION,
            "model_id": service.model_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "impression_id": impression_id if entity_type == "scene" else None,
            "items": [
                {**asdict(item), "label": labels.get(item.entity_id, "")} for item in results
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
        }

    def expand(
        self,
        entity_type: str,
        *,
        sort: str = "match",
        performer_id: str | None = None,
        favorite_only: bool = False,
        count: int = 50,
    ) -> dict[str, object]:
        return ExpandService(self.connection).results(
            entity_type,
            sort=sort,
            performer_id=performer_id,
            favorite_only=favorite_only,
            count=count,
        )

    def expand_shortlist(self) -> dict[str, object]:
        return ExpandService(self.connection).shortlist_results()

    def update_shortlist(self, entity_type: str, external_id: str, selected: bool) -> None:
        ExpandService(self.connection).shortlist(entity_type, external_id, selected)

    def external_similar(self, entity_type: str, entity_id: str) -> dict[str, object]:
        return ExpandService(self.connection).similar(entity_type, entity_id)

    def submit_feedback(self, entries: list[dict[str, Any]]) -> dict[str, object]:
        inserted = InteractionStore(self.connection).submit_feedback(entries)
        return {"schema_version": API_SCHEMA_VERSION, "accepted": inserted}

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
        states = {
            str(row["scene_id"]): str(row["state"])
            for row in self.connection.execute("SELECT scene_id, state FROM pruning_candidate")
        }
        explicit = {
            str(row[0])
            for row in self.connection.execute(
                """
                SELECT f.scene_id FROM feedback f
                WHERE f.reversed_by_id IS NULL AND f.feedback_type IN ('thumb_down', 'never_show')
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
        scores = (
            {
                str(row["scene_id"]): row
                for row in self.connection.execute(
                    """
                    SELECT scene_id, appeal, confidence FROM model_scene_score
                    WHERE model_id=? AND (scene_id IN (
                      SELECT scene_id FROM pruning_candidate WHERE state='review'
                    ) OR appeal<=? AND confidence>=?)
                    """,
                    (model_id, appeal_limit, confidence_limit),
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

    def reconcile_prune_tag(self, tag_name: str) -> None:
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
        with transaction(self.connection):
            self.connection.execute("DELETE FROM pruning_candidate WHERE state='remove'")
            self.connection.executemany(
                """
                INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
                VALUES (?, 'remove', ?, ?, ?)
                ON CONFLICT(scene_id) DO UPDATE SET state='remove',
                    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
                """,
                ((scene_id, now_ms, now_ms, f"Tagged {tag_name}") for scene_id in tagged),
            )

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
            "sync_page_size",
            "debounce_ms",
            "model_update_event_threshold",
            "model_update_max_wait_minutes",
            "model_update_min_interval_minutes",
            "prune_tag_name",
            "expand_horizon_days",
            "expand_gender",
            "expand_wildcard",
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
