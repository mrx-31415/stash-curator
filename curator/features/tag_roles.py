"""Explainable tag-role resolution."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from curator.config import DEFAULT_CONFIG, FeatureConfig
from curator.taxonomy import TaxonomyMatch


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
    taxonomy: TaxonomyMatch | None = None


def effective_tag_role_config_version(connection: sqlite3.Connection) -> str | None:
    """Return the tag_role config_version to read tag roles under.

    Mirrors core's effectiveTagRoleConfigVersion: the running FeatureConfig
    fingerprint when the build wrote rows for it, otherwise the most complete
    legacy config_version still present. A plugin update can leave the
    published model's tag_role rows under an older fingerprint (the model
    predates the last FeatureConfig change); falling back keeps the taste
    profile, scene tag choices, and tag preferences working until the next
    model build writes rows for the current fingerprint. Returns None when
    tag_role has no rows at all (no build yet).
    """
    current = f"cfg-{DEFAULT_CONFIG.feature_fingerprint()[:20]}"
    row = connection.execute(
        "SELECT 1 FROM tag_role WHERE config_version=? LIMIT 1", (current,)
    ).fetchone()
    if row is not None:
        return current
    row = connection.execute(
        """
        SELECT config_version FROM (
          SELECT config_version, count(*) AS n FROM tag_role
          GROUP BY config_version ORDER BY n DESC, config_version DESC LIMIT 1
        )
        """
    ).fetchone()
    return str(row[0]) if row is not None else None


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

    def resolve(
        self,
        tag_id: str,
        name: str | None,
        taxonomy: TaxonomyMatch | None = None,
    ) -> TagRoleResult:
        override = self.overrides.get(tag_id)
        if override:
            return TagRoleResult(override, "explicit_tag_id_override")
        normalized = (name or "").strip()
        folded = normalized.casefold()
        for match, pattern, role, compiled in self.rules:
            if match == "regex":
                continue
            applies = (
                (match == "exact" and folded == pattern.casefold())
                or (match == "prefix" and folded.startswith(pattern.casefold()))
                or (match == "regex" and compiled is not None and compiled.search(normalized))
            )
            if applies:
                return TagRoleResult(role, f"configured_{match}_rule:{pattern}", taxonomy)
        if taxonomy is not None and taxonomy.role is not None:
            return TagRoleResult(
                TagRole(taxonomy.role),
                f"stashdb_{taxonomy.method}:{taxonomy.external_category_id}",
                taxonomy,
            )
        for match, pattern, role, compiled in self.rules:
            if match != "regex":
                continue
            if compiled is not None and compiled.search(normalized):
                return TagRoleResult(role, f"configured_regex_rule:{pattern}", taxonomy)
        if normalized.startswith("[") and normalized.endswith("]"):
            return TagRoleResult(
                TagRole.WORKFLOW_ADMINISTRATIVE, "bracketed_automation_default", taxonomy
            )
        return TagRoleResult(TagRole.CONTENT, "content_default", taxonomy)
