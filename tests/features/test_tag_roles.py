from curator.config import FeatureConfig, TagRule
from curator.features.tag_roles import TagRole, TagRoleResolver


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
