"""Transport-neutral operations used by the Stash plugin and tests."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from curator.config import DEFAULT_CONFIG
from curator.explanations import ExplanationService
from curator.features import FeatureStore
from curator.interactions import InteractionStore
from curator.model import ModelUpdateCoordinator, RecommendationModelStore
from curator.ranking import LanePolicy, SlateBuilder
from curator.ranking.slate import Slate
from curator.storage import transaction

API_SCHEMA_VERSION = 1
DEFAULT_PLUGIN_CONFIG: dict[str, object] = {
    "page_size": 20,
    "sync_page_size": 250,
    "debounce_ms": 2_000,
    "auto_sync_hours": 24,
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
        exploration: int = 0,
    ) -> dict[str, object]:
        started = time.perf_counter()
        timings: dict[str, int] = {}
        config = self.config()["config"]
        assert isinstance(config, dict)
        coordinator = ModelUpdateCoordinator(
            self.connection, debounce_ms=int(config["debounce_ms"])
        )
        built_models = coordinator.drain()
        for model in built_models:
            LanePolicy(self.connection).classify(model.model_id)
            SlateBuilder(self.connection).prepare(model.model_id)
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
                "SELECT 1 FROM curator_job WHERE state='running' LIMIT 1"
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
        allowed = {"page_size", "sync_page_size", "debounce_ms", "auto_sync_hours"}
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
        auto_sync = values.get("auto_sync_hours")
        if auto_sync is not None and (
            not isinstance(auto_sync, (int, float)) or not 0 <= float(auto_sync) <= 24 * 30
        ):
            raise ValueError("auto_sync_hours must be between 0 and 720")
