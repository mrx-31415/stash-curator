"""Load and validate external microplanner realization data."""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from pathlib import Path

_EVIDENCE_FIELDS = {
    "challenge",
    "known",
    "performer",
    "precedent",
    "precedent_outcome",
    "precedents",
    "profile",
    "studio",
    "tags",
    "target",
}
_PLAN_FIELDS = {
    "boundary",
    "boundary_cap",
    "primary",
    "primary_cap",
    "support",
    "support_cap",
}
_CARD_TEMPLATES = {
    ("direct.positive", "lead"): (
        "you have enjoyed this scene before",
        "this scene has a positive history with you",
        "you have returned to this scene before",
    ),
    ("direct.positive", "support"): (
        "you have seen this scene successfully before",
        "your own history supports it",
        "you already know this scene can be worthwhile",
    ),
    ("appeal.performer_identity", "lead"): (
        "you tend to enjoy {performer}",
        "your history with {performer} is positive",
        "{performer} has been a reliable choice for you",
    ),
    ("appeal.performer_identity", "support"): (
        "{performer} is another performer you enjoy",
        "{performer}'s history adds support",
        "you have a positive history with {performer}",
    ),
    ("appeal.content_neighbor", "lead"): (
        "{tags} also recur in scenes you have enjoyed",
        "your history is positive around {tags}",
        "the {tags} here match a pattern you have enjoyed",
    ),
    ("appeal.content_neighbor", "support"): (
        "{tags} are also present in scenes you have enjoyed",
        "{tags} add a familiar content pattern",
        "your past choices also favour {tags}",
    ),
    ("appeal.tag_positive", "lead"): (
        "scenes with {tags} have tended to suit you",
        "your history is positive around {tags}",
        "{tags} are a recurring positive pattern for you",
    ),
    ("appeal.tag_positive", "support"): (
        "{tags} provide additional support",
        "your past choices also favour {tags}",
        "{tags} are another positive signal",
    ),
    ("appeal.studio", "lead"): (
        "your history with {studio} is positive",
        "scenes from {studio} have often suited you",
        "{studio} has been a reliable source in your library",
    ),
    ("appeal.studio", "support"): (
        "{studio} adds a positive studio signal",
        "your history with {studio} provides additional support",
        "{studio} is another familiar source",
    ),
    ("appeal.performer_similar", "lead"): (
        "{target} resembles {known} in {profile}",
        "{target} is similar to {known}, particularly in {profile}",
        "{known} is a useful reference for {target} because of {profile}",
    ),
    ("appeal.performer_similar", "support"): (
        "{target} also resembles {known} in {profile}",
        "the similarity between {target} and {known} is strongest in {profile}",
        "{profile} is the main connection between {target} and {known}",
    ),
    ("appeal.tag_negative", "boundary"): (
        "your history with {tags} is mixed",
        "the pattern around {tags} has been less consistent for you",
        "there is some friction around {tags}",
    ),
    ("fit.cooldown", "boundary"): (
        "you watched this relatively recently",
        "it may need a little more time to feel fresh",
        "recency is holding this back for now",
    ),
    ("fit.not_now", "boundary"): (
        "your recent Not now feedback still applies",
        "you asked to leave this for later",
        "the temporary Not now signal is still active",
    ),
    ("explore.challenge", "boundary"): (
        "the deliberate stretch is {challenge}",
        "{challenge} is the part being tested here",
        "this asks you to reconsider {challenge}",
    ),
    ("explore.disagreement", "boundary"): (
        "your past choices give mixed signals here",
        "the evidence points in different directions",
        "this sits near a boundary in your history",
    ),
    ("explore.coverage", "boundary"): (
        "there is less history to rely on here",
        "this explores a less-covered part of your library",
        "the evidence is thinner than usual",
    ),
    ("explore.unknown", "boundary"): (
        "the evidence here is limited",
        "this is a less-tested direction",
        "your history does not give a clear answer yet",
    ),
    ("fallback", "lead"): ("the evidence is limited",),
    ("fallback", "support"): ("there is some supporting evidence",),
    ("fallback", "boundary"): ("the evidence is still uncertain",),
}


@dataclass(frozen=True)
class RealizationCatalog:
    version: int
    evidence: dict[str, dict[str, tuple[str, ...]]]
    pairings: dict[str, dict[str, tuple[str, ...]]]
    plans: dict[str, dict[str, tuple[str, ...]]]

    @classmethod
    def load(cls, path: Path | None = None) -> RealizationCatalog:
        source = path or Path(__file__).with_name("realizations.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("realization catalog must have version 1")
        evidence = cls._section(payload.get("evidence"), _EVIDENCE_FIELDS)
        pairings = cls._section(payload.get("pairings"), _EVIDENCE_FIELDS)
        plans = cls._section(payload.get("plans"), _PLAN_FIELDS)
        return cls(1, evidence, pairings, plans)

    @staticmethod
    def _section(value: object, allowed_fields: set[str]) -> dict[str, dict[str, tuple[str, ...]]]:
        if not isinstance(value, dict) or not value:
            raise ValueError("realization catalog section must be a non-empty object")
        result: dict[str, dict[str, tuple[str, ...]]] = {}
        for group_name, raw_group in value.items():
            if not isinstance(group_name, str) or not isinstance(raw_group, dict) or not raw_group:
                raise ValueError("realization groups must be named non-empty objects")
            group: dict[str, tuple[str, ...]] = {}
            for variant_name, raw_variants in raw_group.items():
                if (
                    not isinstance(variant_name, str)
                    or not isinstance(raw_variants, list)
                    or not raw_variants
                    or not all(isinstance(item, str) and item.strip() for item in raw_variants)
                ):
                    raise ValueError("realization variants must be non-empty string lists")
                variants = tuple(raw_variants)
                for template in variants:
                    fields = {
                        field_name
                        for _, field_name, _, _ in string.Formatter().parse(template)
                        if field_name
                    }
                    if not fields <= allowed_fields:
                        unknown = sorted(fields - allowed_fields)
                        raise ValueError(f"unknown realization fields: {unknown}")
                group[variant_name] = variants
            if sum(len(variants) for variants in group.values()) < 20:
                raise ValueError(
                    f"realization category {group_name!r} must contain at least 20 variants"
                )
            result[group_name] = group
        return result

    def evidence_variant(
        self,
        code: str,
        position: str,
        slots: dict[str, str],
        seed: str,
    ) -> str:
        variants = _CARD_TEMPLATES.get((code, position)) or _CARD_TEMPLATES[("fallback", position)]
        return self._choose(variants, f"{seed}\0evidence\0{code}\0{position}").format(**slots)

    def plan_variant(self, lane: str, shape: str, slots: dict[str, str], seed: str) -> str:
        del lane, seed
        templates = {
            "primary": "{primary_cap}.",
            "primary_support": "{primary_cap}. {support_cap}.",
            "primary_boundary": "{primary_cap}. {boundary_cap}.",
            "primary_support_boundary": "{primary_cap}. {support_cap}. {boundary_cap}.",
        }
        try:
            return templates[shape].format(**slots)
        except KeyError as error:
            raise ValueError(f"missing plan shape {shape!r}") from error

    def pairing_variant(
        self,
        first_code: str,
        second_code: str,
        slots: dict[str, str],
        seed: str,
    ) -> str | None:
        key = "+".join(sorted((first_code, second_code)))
        group = self.pairings.get(key)
        if group is None:
            return None
        variants = group["fused"]
        return self._choose(variants, f"{seed}\0pairing\0{key}").format(**slots)

    @staticmethod
    def _choose(variants: tuple[str, ...], seed: str) -> str:
        index = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % len(variants)
        return variants[index]
