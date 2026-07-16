"""Select and arrange reason-graph evidence for a short explanation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from curator.explanations.reasons import Reason


@dataclass(frozen=True)
class EvidenceUnit:
    reason: Reason
    family: str
    strength: float


@dataclass(frozen=True)
class DiscoursePlan:
    lane: str
    subtype: str | None
    primary: EvidenceUnit
    support: EvidenceUnit | None
    boundary: EvidenceUnit | None

    @property
    def selected_reasons(self) -> tuple[Reason, ...]:
        return tuple(
            unit.reason for unit in (self.primary, self.support, self.boundary) if unit is not None
        )

    @property
    def shape(self) -> str:
        suffix = ""
        if self.support is not None:
            suffix += "_support"
        if self.boundary is not None:
            suffix += "_boundary"
        return f"primary{suffix}"


class Microplanner:
    """A deterministic editorial policy over truthful reason objects."""

    _PRIORITY: ClassVar[dict[str, int]] = {
        "direct.positive": 7,
        "appeal.performer_identity": 6,
        "appeal.content_neighbor": 5,
        "appeal.tag_positive": 4,
        "appeal.studio": 3,
        "appeal.performer_similar": 2,
    }

    def plan(self, reasons: tuple[Reason, ...]) -> DiscoursePlan:
        lane_reason = next(
            (reason for reason in reasons if reason.code == "eligibility.lane"), None
        )
        lane = str(lane_reason.detail.get("lane", "generic")) if lane_reason else "generic"
        subtype_value = lane_reason.detail.get("subtype") if lane_reason else None
        subtype = str(subtype_value) if subtype_value else None

        positives = self._positive_units(reasons)
        primary = self._primary(positives, lane)
        support = next(
            (
                candidate
                for candidate in positives
                if candidate.reason != primary.reason and self._distinct(primary, candidate)
            ),
            None,
        )
        boundary = self._boundary(reasons, lane)
        return DiscoursePlan(lane, subtype, primary, support, boundary)

    def _positive_units(self, reasons: tuple[Reason, ...]) -> list[EvidenceUnit]:
        units = [
            self._unit(reason)
            for reason in reasons
            if reason.direction == "positive"
            and reason.code in self._PRIORITY
            and self._narratable(reason)
        ]
        return sorted(
            units,
            key=lambda unit: (
                -unit.strength,
                -self._PRIORITY.get(unit.reason.code, 0),
                unit.reason.code,
                unit.reason.subject_id or "",
            ),
        )

    def _primary(self, positives: list[EvidenceUnit], lane: str) -> EvidenceUnit:
        if lane == "revisit":
            direct = next(
                (unit for unit in positives if unit.reason.code == "direct.positive"), None
            )
            if direct is not None:
                return direct
        if positives:
            return positives[0]
        return self._fallback_unit(lane)

    def _boundary(self, reasons: tuple[Reason, ...], lane: str) -> EvidenceUnit | None:
        exploration = sorted(
            (self._unit(reason) for reason in reasons if reason.code.startswith("explore.")),
            key=lambda unit: (-unit.strength, unit.reason.code),
        )
        if lane in {"discover", "adventure"} and exploration:
            return exploration[0]
        reservations = sorted(
            (
                self._unit(reason)
                for reason in reasons
                if reason.direction == "negative"
                and reason.code in {"appeal.tag_negative", "fit.cooldown", "fit.not_now"}
            ),
            key=lambda unit: (-unit.strength, unit.reason.code),
        )
        return reservations[0] if reservations else None

    @staticmethod
    def _distinct(primary: EvidenceUnit, candidate: EvidenceUnit) -> bool:
        if primary.family == candidate.family:
            return False
        # A neighbor clause already names the content features creating the
        # relationship, so a separate tag clause normally repeats the same evidence.
        return {primary.reason.code, candidate.reason.code} != {
            "appeal.content_neighbor",
            "appeal.tag_positive",
        }

    @staticmethod
    def _narratable(reason: Reason) -> bool:
        if reason.code != "appeal.performer_similar":
            return True
        return _number(reason.detail.get("novelty_weight")) >= 0.5

    @staticmethod
    def _unit(reason: Reason) -> EvidenceUnit:
        return EvidenceUnit(reason, _family(reason.code), reason.magnitude * reason.confidence)

    @staticmethod
    def _fallback_unit(lane: str) -> EvidenceUnit:
        reason = Reason(
            "fallback",
            "unknown",
            0.0,
            0.0,
            None,
            None,
            "standard",
            "microplanner_fallback",
            {"lane": lane},
            "",
            "",
        )
        return EvidenceUnit(reason, "fallback", 0.0)


def _family(code: str) -> str:
    if code.startswith("appeal.performer_"):
        return "performer"
    if code.startswith("appeal.tag_") or code == "appeal.content_neighbor":
        return "content"
    return code.rsplit(".", 1)[0]


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
