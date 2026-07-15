"""Explainable tag-role resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from curator.config import FeatureConfig


class TagRole(StrEnum):
    CONTENT = "content"
    PERFORMER_ATTRIBUTE = "performer_attribute"
    QUALITY_TECHNICAL = "quality_technical"
    WORKFLOW_ADMINISTRATIVE = "workflow_administrative"
    IGNORED = "ignored"


@dataclass(frozen=True)
class TagRoleResult:
    role: TagRole
    reason: str


class TagRoleResolver:
    """Resolve ID overrides before name rules and conservative defaults."""

    def __init__(self, config: FeatureConfig) -> None:
        self.overrides = {tag_id: TagRole(role) for tag_id, role in config.tag_id_overrides}
        self.rules = tuple(
            (rule.match, rule.pattern, TagRole(rule.role), self._compile(rule.match, rule.pattern))
            for rule in config.tag_rules
        )

    @staticmethod
    def _compile(match: str, pattern: str) -> re.Pattern[str] | None:
        if match not in {"exact", "prefix", "regex"}:
            raise ValueError(f"unsupported tag rule match type: {match}")
        return re.compile(pattern, re.IGNORECASE) if match == "regex" else None

    def resolve(self, tag_id: str, name: str | None) -> TagRoleResult:
        override = self.overrides.get(tag_id)
        if override:
            return TagRoleResult(override, "explicit_tag_id_override")
        normalized = (name or "").strip()
        folded = normalized.casefold()
        for match, pattern, role, compiled in self.rules:
            applies = (
                (match == "exact" and folded == pattern.casefold())
                or (match == "prefix" and folded.startswith(pattern.casefold()))
                or (match == "regex" and compiled is not None and compiled.search(normalized))
            )
            if applies:
                return TagRoleResult(role, f"configured_{match}_rule:{pattern}")
        if normalized.startswith("[") and normalized.endswith("]"):
            return TagRoleResult(TagRole.WORKFLOW_ADMINISTRATIVE, "bracketed_automation_default")
        return TagRoleResult(TagRole.CONTENT, "content_default")
