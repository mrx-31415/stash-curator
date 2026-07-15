"""Deterministic planning and natural-language rendering from reason objects only."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

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

    def explain_scene(self, model_id: str, scene_id: str) -> Explanation:
        reasons = self.store.reasons(model_id, scene_id)
        if not reasons:
            self.store.build(model_id)
            reasons = self.store.reasons(model_id, scene_id)
        return self._render(reasons)

    def explain_recommendation(self, item: RecommendationItem) -> Explanation:
        model_id = self._current_model_id()
        base = self.store.reasons(model_id, item.scene_id)
        if not base:
            self.store.build(model_id)
            base = self.store.reasons(model_id, item.scene_id)
        reasons = (*base, *self._ranking_reasons(model_id, item))
        return self._render(reasons)

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
            code = self._exploration_code(item)
            reasons.append(
                Reason(
                    code,
                    "unknown",
                    min(1.0, _number(item.qualification.get("uncertainty"))),
                    item.confidence,
                    "scene",
                    item.scene_id,
                    "standard",
                    "lane_policy",
                    {
                        "subtype": item.subtype,
                        "challenged_assumption": item.qualification.get("challenged_assumption"),
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
    def _exploration_code(item: RecommendationItem) -> str:
        if item.subtype == "model_disagreement":
            return "explore.disagreement"
        if item.subtype == "stretch":
            return "explore.challenge"
        if item.subtype in {"under_covered_island", "anchored_model_gap"}:
            return "explore.coverage"
        return "explore.unknown"

    def _render(self, reasons: tuple[Reason, ...]) -> Explanation:
        selected = self._plan(reasons)
        positive = [reason for reason in selected if reason.direction == "positive"]
        exploration = [reason for reason in selected if reason.code.startswith("explore.")]
        reservations = [
            reason
            for reason in selected
            if reason.direction == "negative" and not reason.code.startswith("diversity.")
        ]
        phrases = [self._phrase(reason) for reason in positive]
        phrases.extend(self._phrase(reason) for reason in exploration)
        phrases.extend(self._phrase(reason) for reason in reservations)
        summary = " ".join(phrase for phrase in phrases if phrase)
        if not summary:
            summary = "This is a cautious catalog suggestion where Curator has limited evidence."
        return Explanation(summary, selected, reasons)

    @staticmethod
    def _plan(reasons: tuple[Reason, ...]) -> tuple[Reason, ...]:
        positive = sorted(
            (reason for reason in reasons if reason.direction == "positive"),
            key=lambda reason: (-reason.magnitude * reason.confidence, reason.code),
        )
        exploration = sorted(
            (reason for reason in reasons if reason.code.startswith("explore.")),
            key=lambda reason: (-reason.magnitude, reason.code),
        )
        adjustments = sorted(
            (
                reason
                for reason in reasons
                if reason.direction == "negative"
                and (
                    reason.code in {"fit.cooldown", "fit.not_now"}
                    or reason.code.startswith("appeal.")
                )
            ),
            key=lambda reason: (-reason.magnitude * reason.confidence, reason.code),
        )
        selected: list[Reason] = []
        seen_families: set[str] = set()
        for reason in positive:
            family = ExplanationService._reason_family(reason.code)
            if family in seen_families:
                continue
            selected.append(reason)
            seen_families.add(family)
            if len(selected) == 2:
                break
        if exploration:
            selected.append(exploration[0])
        if adjustments and len(selected) < 3:
            selected.append(adjustments[0])
        return tuple(selected[:3])

    @staticmethod
    def _reason_family(code: str) -> str:
        if code.startswith("appeal.tag_"):
            return "appeal.tag"
        if code.startswith("appeal.performer_"):
            return "appeal.performer"
        return code.rsplit(".", 1)[0]

    def _phrase(self, reason: Reason) -> str:
        code = reason.code
        if code == "appeal.tag_positive":
            names = self._detail_list(reason.detail.get("related_names"))
            tags = self._natural_list(names or [str(reason.detail.get("name", "content"))])
            return self._choose(
                reason,
                (
                    f"The content makes a good case for this one, especially {tags}.",
                    f"The combination of {tags} lines up particularly well with your past choices.",
                    f"A lot of the fit comes from {tags}, which recur in scenes you enjoy.",
                ),
            )
        if code == "appeal.tag_negative":
            names = self._detail_list(reason.detail.get("related_names"))
            tags = self._natural_list(
                names or [str(reason.detail.get("name", "one content pattern"))]
            )
            return self._choose(
                reason,
                (
                    f"The main reservation is {tags}, which are less convincing in your history.",
                    f"There is some friction around {tags}; those patterns have worked less often.",
                    f"The presence of {tags} makes this a little less certain "
                    "than the stronger picks.",
                ),
            )
        if code == "appeal.performer_identity":
            name = self._name("performer", reason.subject_id)
            return self._choose(
                reason,
                (
                    f"Your history with {name} is one of the clearest reasons to recommend it.",
                    f"{name} has been a reliable draw for you, which gives this a strong start.",
                    f"A large part of the appeal is {name}, based on how their scenes "
                    "have worked for you.",
                ),
            )
        if code == "appeal.performer_similar":
            matches = reason.detail.get("matches", [])
            known_id = None
            if isinstance(matches, list) and matches and isinstance(matches[0], dict):
                known_id = str(matches[0].get("performer_id", "")) or None
            target = self._name("performer", reason.subject_id)
            known = self._name("performer", known_id)
            profile = str(reason.detail.get("profile_description", "a similar overall profile"))
            aspects = self._natural_list(
                self._detail_list(reason.detail.get("shared_aspects"))
                or ["their overall performer profiles"]
            )
            effect = (
                f"Since {known} has worked for you, that resemblance gives this scene a lift."
                if reason.direction == "positive"
                else f"Your history with {known} makes that resemblance a mild reservation."
            )
            return self._choose(
                reason,
                (
                    f"{target} looks close to {known}, mainly in {aspects}. "
                    f"In plain terms, {target} has {profile}. {effect}",
                    f"I would place {target} near {known} because of {aspects}; "
                    f"the visible profile is {profile}. {effect}",
                ),
            )
        if code == "appeal.studio":
            name = self._name("studio", reason.subject_id)
            return self._choose(
                reason,
                (
                    f"{name} has a good enough track record with you to add some confidence.",
                    f"Your history with {name} works in this scene's favor.",
                    f"Scenes from {name} have tended to suit you, which helps here.",
                ),
            )
        if code == "appeal.content_neighbor":
            return self._neighbor_phrase(reason)
        if code == "direct.positive":
            return self._choose(
                reason,
                (
                    "You have come back to this scene successfully before, so it has "
                    "earned another look.",
                    "This has worked well for you directly, making it a particularly safe revisit.",
                    "Your own history is the strongest argument here: this scene has "
                    "delivered before.",
                ),
            )
        if code == "direct.negative":
            return "Your direct history with this scene is negative."
        if code == "fit.cooldown":
            return "I ranked it lower for now because you watched it relatively recently."
        if code == "fit.satiation":
            return (
                "I held it back slightly to avoid repeating a recent performer, "
                "studio, or content pattern."
            )
        if code == "fit.not_now":
            return "Your recent Not now feedback temporarily lowers its fit."
        if code == "explore.challenge":
            challenge = reason.detail.get("challenged_assumption") or "one weaker preference"
            return (
                f"This is a deliberate stretch: it challenges {challenge} "
                "while retaining a positive anchor."
            )
        if code == "explore.disagreement":
            return "This is testing a scene where Curator's positive and negative signals disagree."
        if code == "explore.coverage":
            return (
                "This explores a coherent part of your library that your history "
                "has covered less often."
            )
        if code == "explore.unknown":
            return "This is a deliberate probe beyond the better-known parts of your taste."
        return ""

    def _neighbor_phrase(self, reason: Reason) -> str:
        raw = reason.detail.get("neighbors", [])
        neighbors = (
            [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        )
        useful = [item for item in neighbors if _number(item.get("outcome")) > 0][:2]
        if not useful:
            return "Its closest content precedents provide some supporting evidence."
        titles = [
            str(item.get("title") or item.get("scene_id") or "a nearby scene") for item in useful
        ]
        tags = self._natural_list(
            list(
                dict.fromkeys(
                    tag for item in useful for tag in self._detail_list(item.get("shared_tags"))
                )
            )[:4]
        )
        title_list = self._natural_list(titles)
        if len(useful) == 1:
            return self._choose(
                reason,
                (
                    f"A useful precedent is {title_list}: it shares {tags} with this "
                    "scene and sits in your positive viewing history.",
                    f"{title_list} is the clearest nearby example, overlapping on "
                    f"{tags} and having worked well for you.",
                ),
            )
        return self._choose(
            reason,
            (
                f"Two useful precedents are {title_list}. They overlap on {tags}, and "
                "both sit in your positive viewing history.",
                f"This sits near {title_list}, chiefly through {tags}; both of those "
                "scenes worked well for you.",
                f"The closest encouraging comparisons are {title_list}, which share "
                f"{tags} and have both worked for you before.",
            ),
        )

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

    @staticmethod
    def _choose(reason: Reason, variants: tuple[str, ...]) -> str:
        key = f"{reason.model_id}\0{reason.subject_id or ''}\0{reason.code}".encode()
        index = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % len(variants)
        return variants[index]

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


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
