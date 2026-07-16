"""Load and render the external recommendation copy catalog."""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from pathlib import Path

_FIELDS = {
    "challenge",
    "known",
    "performer",
    "profile",
    "studio",
    "tags",
    "target",
}


@dataclass(frozen=True)
class RealizationCatalog:
    version: int
    evidence: dict[str, dict[str, tuple[str, ...]]]

    @classmethod
    def load(cls, path: Path | None = None) -> RealizationCatalog:
        source = path or Path(__file__).with_name("realizations.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("realization catalog must have version 1")
        evidence = cls._section(payload.get("evidence"))
        return cls(1, evidence)

    @staticmethod
    def _section(value: object) -> dict[str, dict[str, tuple[str, ...]]]:
        if not isinstance(value, dict) or not value:
            raise ValueError("realization catalog must have a non-empty evidence object")
        result: dict[str, dict[str, tuple[str, ...]]] = {}
        for group_name, raw_group in value.items():
            if not isinstance(group_name, str) or not isinstance(raw_group, dict) or not raw_group:
                raise ValueError("realization groups must be named non-empty objects")
            group: dict[str, tuple[str, ...]] = {}
            for position, raw_variants in raw_group.items():
                if (
                    not isinstance(position, str)
                    or not isinstance(raw_variants, list)
                    or len(raw_variants) < 3
                    or not all(isinstance(item, str) and item.strip() for item in raw_variants)
                ):
                    raise ValueError("each realization position needs at least three strings")
                variants = tuple(raw_variants)
                for template in variants:
                    fields = {
                        field_name
                        for _, field_name, _, _ in string.Formatter().parse(template)
                        if field_name
                    }
                    if not fields <= _FIELDS:
                        raise ValueError(f"unknown realization fields: {sorted(fields - _FIELDS)}")
                group[position] = variants
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

    @staticmethod
    def plan_variant(lane: str, shape: str, slots: dict[str, str], seed: str) -> str:
        del lane, seed
        parts = {
            "primary": ("primary_cap",),
            "primary_support": ("primary_cap", "support_cap"),
            "primary_boundary": ("primary_cap", "boundary_cap"),
            "primary_support_boundary": ("primary_cap", "support_cap", "boundary_cap"),
        }.get(shape)
        if parts is None:
            raise ValueError(f"missing plan shape {shape!r}")
        return ". ".join(slots[part] for part in parts) + "."

    @staticmethod
    def _choose(variants: tuple[str, ...], seed: str) -> str:
        index = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % len(variants)
        return variants[index]
