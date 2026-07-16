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
            result[group_name] = group
        return result

    def evidence_variant(
        self,
        code: str,
        position: str,
        slots: dict[str, str],
        seed: str,
    ) -> str:
        group = self.evidence.get(code) or self.evidence["fallback"]
        variants = group.get(position) or group.get("lead")
        if variants is None:
            raise ValueError(f"missing evidence position {position!r} for {code!r}")
        return self._choose(variants, f"{seed}\0evidence\0{code}\0{position}").format(**slots)

    def plan_variant(self, lane: str, shape: str, slots: dict[str, str], seed: str) -> str:
        group = self.plans.get(lane) or self.plans["generic"]
        variants = group.get(shape) or self.plans["generic"].get(shape)
        if variants is None:
            raise ValueError(f"missing plan shape {shape!r} for {lane!r}")
        return self._choose(variants, f"{seed}\0plan\0{lane}\0{shape}").format(**slots)

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
