"""Deterministic microplanning and realization from reason objects only."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from curator.explanations.catalog import RealizationCatalog
from curator.explanations.planner import EvidenceUnit, Microplanner
from curator.explanations.reasons import Reason, ReasonGraphStore
from curator.ranking import RecommendationItem


@dataclass(frozen=True)
class Explanation:
    summary: str
    selected_reasons: tuple[Reason, ...]
    all_reasons: tuple[Reason, ...]


class ExplanationService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.store = ReasonGraphStore(connection)
        self.planner = Microplanner()
        self.catalog = RealizationCatalog.load()

    def explain_scene(self, model_id: str, scene_id: str) -> Explanation:
        reasons = self.store.reasons(model_id, scene_id)
        if not reasons:
            self.store.build(model_id)
            reasons = self.store.reasons(model_id, scene_id)
        return self._render(reasons, f"{model_id}\0{scene_id}")

    def explain_recommendation(self, item: RecommendationItem) -> Explanation:
        model_id = self._current_model_id()
        base = self.store.reasons(model_id, item.scene_id)
        if not base:
            self.store.build(model_id)
            base = self.store.reasons(model_id, item.scene_id)
        reasons = (*base, *self._ranking_reasons(model_id, item))
        return self._render(
            reasons,
            f"{model_id}\0{item.scene_id}\0{item.lane}\0{item.source_lane}\0{item.position}",
        )

    def _current_model_id(self) -> str:
        row = self.connection.execute(
            "SELECT model_id FROM model_version WHERE status='published'"
        ).fetchone()
        if row is None:
            raise RuntimeError("no published model")
        return str(row[0])

    def _ranking_reasons(self, model_id: str, item: RecommendationItem) -> tuple[Reason, ...]:
        row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        feature_version = str(row[0])
        reasons = [
            Reason(
                "eligibility.lane",
                "neutral",
                0.0,
                1.0,
                "scene",
                item.scene_id,
                "standard",
                "lane_policy",
                {
                    "lane": item.source_lane,
                    "subtype": item.subtype,
                    "qualification": item.qualification,
                },
                model_id,
                feature_version,
            )
        ]
        if item.source_lane in {"discover", "adventure"}:
            exploration_code = self._exploration_code(item)
            if exploration_code is not None:
                reasons.append(
                    Reason(
                        exploration_code,
                        "unknown",
                        min(1.0, _number(item.qualification.get("uncertainty"))),
                        item.confidence,
                        "scene",
                        item.scene_id,
                        "standard",
                        "lane_policy",
                        {
                            "subtype": item.subtype,
                            "challenged_assumption": item.qualification.get(
                                "challenged_assumption"
                            ),
                            "positive_anchors": item.qualification.get("positive_anchors", {}),
                        },
                        model_id,
                        feature_version,
                    )
                )
        for name, penalty in item.penalties.items():
            if penalty <= 0:
                continue
            code = {
                "performer": "diversity.performer",
                "studio": "diversity.studio",
                "content": "diversity.content",
                "history": "diversity.content",
            }.get(name, "diversity.content")
            reasons.append(
                Reason(
                    code,
                    "negative",
                    min(1.0, penalty),
                    1.0,
                    "scene",
                    item.scene_id,
                    "standard",
                    "slate_selection",
                    {"penalty": name, "value": penalty},
                    model_id,
                    feature_version,
                )
            )
        return tuple(reasons)

    @staticmethod
    def _exploration_code(item: RecommendationItem) -> str | None:
        if item.subtype == "model_disagreement":
            return "explore.disagreement"
        if item.subtype == "stretch":
            return "explore.challenge"
        if item.subtype in {"under_covered_island", "anchored_model_gap"}:
            return "explore.coverage"
        return None

    def _render(self, reasons: tuple[Reason, ...], seed: str) -> Explanation:
        plan = self.planner.plan(reasons)
        slots: dict[str, str] = {}
        primary = self._realize(plan.primary, "lead", seed)
        slots.update(primary=primary, primary_cap=_capitalize(primary))
        if plan.support is not None:
            support = self._realize(plan.support, "support", seed)
            slots.update(support=support, support_cap=_capitalize(support))
        if plan.boundary is not None:
            boundary = self._realize(plan.boundary, "boundary", seed)
            slots.update(boundary=boundary, boundary_cap=_capitalize(boundary))
        summary = self.catalog.plan_variant(plan.lane, plan.shape, slots, seed)
        return Explanation(summary, plan.selected_reasons, reasons)

    def _realize(self, unit: EvidenceUnit, position: str, seed: str) -> str:
        reason = unit.reason
        return self.catalog.evidence_variant(reason.code, position, self._slots(reason), seed)

    def _slots(self, reason: Reason) -> dict[str, str]:
        slots = {
            "challenge": "one less-certain part of your taste",
            "known": "a familiar performer",
            "performer": "a familiar performer",
            "precedent": "a scene that worked for you",
            "precedent_outcome": "which worked for you",
            "precedents": "nearby scenes you enjoyed",
            "profile": "their overall profiles",
            "studio": "a familiar studio",
            "tags": "familiar elements",
            "target": "a new performer",
        }
        slots.update(self._specific_slots(reason))
        return slots

    def _specific_slots(self, reason: Reason) -> dict[str, str]:
        if reason.code == "appeal.content_neighbor":
            return self._neighbor_slots(reason)
        if reason.code == "appeal.performer_similar":
            return self._similarity_slots(reason)
        if reason.code == "appeal.performer_identity":
            return {"performer": self._name("performer", reason.subject_id)}
        if reason.code == "appeal.studio":
            return {"studio": self._name("studio", reason.subject_id)}
        if reason.code.startswith("appeal.tag_"):
            return {"tags": self._tag_names(reason)}
        if reason.code == "explore.challenge":
            return {"challenge": self._challenge_phrase(reason.detail.get("challenged_assumption"))}
        return {}

    def _neighbor_slots(self, reason: Reason) -> dict[str, str]:
        raw = reason.detail.get("neighbors", [])
        neighbors = (
            [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        )
        useful = [item for item in neighbors if _number(item.get("outcome")) > 0][:2]
        titles = [self._prose_precedent(item.get("title")) for item in useful]
        tags = list(
            dict.fromkeys(
                tag for item in useful for tag in self._detail_list(item.get("shared_tags"))
            )
        )[:3]
        return {
            "precedent": titles[0] if titles else "an earlier scene",
            "precedent_outcome": self._outcome_phrase(useful[0]) if useful else "from your history",
            "precedents": self._natural_list(titles or ["nearby scenes you enjoyed"]),
            "tags": self._natural_list(tags or ["their content profile"]),
        }

    @staticmethod
    def _prose_precedent(value: object) -> str:
        del value
        return "an earlier scene"

    @staticmethod
    def _outcome_phrase(neighbor: dict[str, object]) -> str:
        outcome = _number(neighbor.get("outcome"))
        if outcome >= 0.75:
            return "which you enjoyed"
        if outcome >= 0.45:
            return "which you liked"
        return "which you watched before"

    @staticmethod
    def _challenge_phrase(value: object) -> str:
        return {
            "studio": "a less familiar studio",
            "performer": "a less familiar performer",
            "content": "a less familiar content pattern",
            "history": "something outside your usual rotation",
        }.get(str(value), "one less-certain part of your taste")

    def _similarity_slots(self, reason: Reason) -> dict[str, str]:
        matches = reason.detail.get("matches", [])
        known_id = None
        if isinstance(matches, list) and matches and isinstance(matches[0], dict):
            known_id = str(matches[0].get("performer_id", "")) or None
        aspects = self._detail_list(reason.detail.get("shared_aspects"))
        description = str(reason.detail.get("profile_description", "")).strip()
        profile = self._natural_list(aspects or ["their overall performer profiles"])
        if description and description != "a similar overall performer profile":
            profile = f"{profile}, reflected in {description}"
        return {
            "known": self._name("performer", known_id),
            "profile": profile,
            "target": self._name("performer", reason.subject_id),
        }

    def _tag_names(self, reason: Reason) -> str:
        names = self._detail_list(reason.detail.get("related_names"))
        if not names:
            name = str(reason.detail.get("name", "a relevant content pattern")).strip()
            names = [name]
        return self._natural_list(names[:3])

    @staticmethod
    def _detail_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    @staticmethod
    def _natural_list(values: list[str]) -> str:
        unique = list(dict.fromkeys(values))
        if not unique:
            return "the available evidence"
        if len(unique) == 1:
            return unique[0]
        if len(unique) == 2:
            return f"{unique[0]} and {unique[1]}"
        return f"{', '.join(unique[:-1])}, and {unique[-1]}"

    def _name(self, entity_type: str, entity_id: str | None) -> str:
        if not entity_id:
            return "this performer" if entity_type == "performer" else "this studio"
        table, id_column = (
            ("source_performer", "performer_id")
            if entity_type == "performer"
            else ("source_studio", "studio_id")
        )
        row = self.connection.execute(
            f"SELECT name FROM {table} WHERE {id_column}=?", (entity_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] else entity_id


def _capitalize(value: str) -> str:
    return value[:1].upper() + value[1:]


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
