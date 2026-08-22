import sqlite3
from pathlib import Path

from curator.config import DEFAULT_CONFIG, FeatureConfig, TagRule
from curator.features.tag_roles import (
    TagRole,
    TagRoleResolver,
    effective_tag_role_config_version,
)
from curator.storage import MigrationRunner, connect_database
from curator.taxonomy import TaxonomyMatch


def _role_db(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    MigrationRunner(connection).migrate(applied_at_ms=1)
    connection.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) VALUES ('t1', 'Scenario', 'h')"
    )
    return connection


def test_effective_tag_role_config_version_falls_back_to_legacy_build(tmp_path: Path) -> None:
    """Oracle mirror of core's TestEffectiveTagRoleConfigVersion (#238)."""
    connection = _role_db(tmp_path / "curator.sqlite3")
    try:
        # No tag_role rows at all → no effective version (never built).
        assert effective_tag_role_config_version(connection) is None
        # Only a legacy config_version → fall back to it.
        connection.execute(
            "INSERT INTO tag_role(tag_id, config_version, role, resolution_reason) "
            "VALUES ('t1', 'cfg-legacy-old', 'content', 'test')"
        )
        assert effective_tag_role_config_version(connection) == "cfg-legacy-old"
        # Current fingerprint present → the running config wins.
        current = f"cfg-{DEFAULT_CONFIG.feature_fingerprint()[:20]}"
        connection.execute(
            "INSERT INTO tag_role(tag_id, config_version, role, resolution_reason) "
            "VALUES ('t1', ?, 'content', 'test')",
            (current,),
        )
        assert effective_tag_role_config_version(connection) == current
    finally:
        connection.close()


def test_role_precedence_and_explanations() -> None:
    resolver = TagRoleResolver(
        FeatureConfig(
            tag_id_overrides=(("override", "content"),),
            tag_rules=(
                TagRule("prefix", "[Workflow:", "workflow_administrative"),
                TagRule("regex", "technical", "quality_technical"),
            ),
        )
    )

    overridden = resolver.resolve("override", "[Workflow: Hidden]")
    configured = resolver.resolve("rule", "[Workflow: Queue]")
    bracketed = resolver.resolve("bracket", "[Hide]")
    content = resolver.resolve("normal", "Scenario")

    assert overridden.role is TagRole.CONTENT
    assert overridden.reason == "explicit_tag_id_override"
    assert configured.role is TagRole.WORKFLOW_ADMINISTRATIVE
    assert configured.reason.startswith("configured_prefix_rule")
    assert bracketed.role is TagRole.WORKFLOW_ADMINISTRATIVE
    assert bracketed.reason == "bracketed_automation_default"
    assert content.role is TagRole.CONTENT


def test_default_physical_vocabulary_is_not_scene_content() -> None:
    resolver = TagRoleResolver(FeatureConfig())

    for name in (
        "Blonde",
        "Blue Eyes",
        "Big Tits",
        "Fake Tits",
        "Visible Tattoos",
        "Athletic Body",
        "Athletic Woman",
        "Bubble Butt",
        "Trimmed",
    ):
        result = resolver.resolve(name, name)
        assert result.role is TagRole.PERFORMER_ATTRIBUTE
        assert result.reason.startswith("configured_regex_rule")

    assert resolver.resolve("scenario", "Office").role is TagRole.CONTENT


def test_taxonomy_precedes_regex_fallback_but_not_explicit_rules() -> None:
    resolver = TagRoleResolver(
        FeatureConfig(tag_rules=(TagRule("exact", "Athletic Body", "quality_technical"),))
    )
    taxonomy = TaxonomyMatch(
        "snapshot",
        "performer_attribute",
        "external-tag",
        "body-category",
        "unique_name_or_alias",
        0.9,
    )

    configured = resolver.resolve("tag", "Athletic Body", taxonomy)
    classified = TagRoleResolver(FeatureConfig()).resolve("tag", "Athletic Body", taxonomy)

    assert configured.role is TagRole.QUALITY_TECHNICAL
    assert configured.reason.startswith("configured_exact_rule")
    assert classified.role is TagRole.PERFORMER_ATTRIBUTE
    assert classified.reason.startswith("stashdb_unique_name_or_alias")
