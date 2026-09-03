"""Versioned configuration for feature, model, ranking, and explanation behavior."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TagRule:
    match: str
    pattern: str
    role: str


@dataclass(frozen=True)
class FeatureConfig:
    tag_id_overrides: tuple[tuple[str, str], ...] = ()
    tag_rules: tuple[TagRule, ...] = (
        TagRule("prefix", "[Workflow:", "workflow_administrative"),
        TagRule("prefix", "[Technical:", "quality_technical"),
        TagRule("exact", "[Curator: Ignore]", "ignored"),
        TagRule(
            "regex",
            r"\b(?:blonde?|brunette|redhead|black hair|brown hair|dyed hair)\b",
            "performer_attribute",
        ),
        TagRule(
            "regex",
            r"\b(?:blue|brown|green|hazel|gr[ae]y) eyes?\b",
            "performer_attribute",
        ),
        TagRule(
            "regex",
            r"\b(?:caucasian|asian|latina?|ebony)\b|"
            r"\b(?:black|white|pale|medium|dark) skin\b",
            "performer_attribute",
        ),
        TagRule(
            "regex",
            r"\b(?:big|small|medium|huge|tiny) (?:ass|tits|boobs|breasts)\b",
            "performer_attribute",
        ),
        TagRule(
            "regex",
            r"\b(?:fake|natural) (?:tits|boobs|breasts)\b|\baugmentation\b",
            "performer_attribute",
        ),
        TagRule("regex", r"\b(?:tattoos?|piercings?)\b", "performer_attribute"),
        TagRule(
            "regex",
            r"^(?:athletic(?: body| woman)?|bubble butt|trimmed)$",
            "performer_attribute",
        ),
    )
    marker_weight: float = 0.45
    parent_weight: float = 0.35
    idf_strength: float = 0.5
    idf_cap: float = 2.5
    one_off_prior: float = 2.0
    # Exact-name list of scene tags excluded from tag analysis. Auto-generated
    # / metadata tags like "[Timestamp: Synced]" describe the file/import, not
    # the scene; they pollute content features, affinity accumulation, the
    # Taste Profile, and lane facets. Exact-name match only (no bracket
    # heuristics — bracketing is unreliable). Empty by default.
    ignored_tags: tuple[str, ...] = ()
    performer_block_weights: tuple[tuple[str, float], ...] = (
        ("content", 1.0),
        ("measurements", 1.0),
        ("augmentation", 0.9),
        ("ethnicity", 0.8),
        ("height", 0.7),
        ("age", 0.6),
        ("hair", 0.45),
        ("tattoos", 0.35),
        ("piercings", 0.25),
        ("eyes", 0.1),
    )


@dataclass(frozen=True)
class ModelConfig:
    algorithm_version: int = 6
    affinity_prior: float = 1.0
    # Weight on the taxonomy prior. A tag with a parent is shrunk toward
    # what its siblings say rather than toward zero, so the prior means
    # "what we know about this category" instead of "no opinion". A tag
    # with no parent, or whose siblings carry no support, borrows nothing
    # and behaves exactly as before. 0.0 disables the borrowing entirely.
    affinity_sibling_prior: float = 1.0
    affinity_confidence_scale: float = 3.0
    direct_confidence_scale: float = 0.8
    cooldown_center_days: float = 90.0
    cooldown_width_days: float = 15.0
    dormancy_center_days: float = 120.0
    dormancy_width_days: float = 45.0
    baseline_bound: float = 0.10
    content_bound: float = 0.35
    neighbor_bound: float = 0.20
    performer_identity_bound: float = 0.30
    performer_similarity_bound: float = 0.16
    studio_bound: float = 0.12
    structure_bound: float = 0.05
    satiation_bound: float = 0.12
    performer_favorite_prior: float = 0.18
    performer_rating_bound: float = 0.10
    studio_favorite_prior: float = 0.04
    scene_rating_confidence: float = 0.90
    curation_rating_confidence: float = 0.80
    curation_pair_confidence: float = 0.15
    curation_pair_surprise_bonus: float = 2.0
    curation_pair_ips_cap: float = 2.0
    # Deliberate "this impact move is wrong" correction: a per-scene signal the
    # user posts from the impact report to pull a wrongly promoted/demoted
    # scene back toward its true appeal. Stronger than an implicit signal but
    # below a fresh rating, since it is a verdict on the model's move, not a
    # first-hand rating.
    impact_correction_confidence: float = 0.60
    # Implicit negatives from impressions (#146 Channel A). When a recommended
    # scene is played or thumbed, the passed-over earlier-position cards in the
    # same impression are treated as weak pairwise losers. The base is half the
    # deliberate-pick base (curation_pair_confidence) so implicit signal never
    # outranks explicit feedback; the issue author flagged it may need to be
    # even weaker after live measurement. Config-backed so it can be tuned.
    implicit_skip_confidence: float = 0.075
    implicit_skip_surprise_bonus: float = 2.0
    implicit_skip_ips_cap: float = 2.0
    not_now_days: float = 30.0
    not_now_penalty: float = 0.50
    neighbor_count: int = 12
    minimum_neighbor_similarity: float = 0.05
    neighbor_confidence_scale: float = 0.35
    neighbor_generic_weight: float = 0.0
    performer_similarity_novelty_floor: float = 0.05


@dataclass(frozen=True)
class RankingConfig:
    adjacent_shared_performers: bool = False
    relax_adjacent_when_exhausted: bool = False
    performer_repeat_penalty: float = 0.06
    studio_penalty: float = 0.08
    content_penalty: float = 0.14
    history_performer_penalty: float = 0.04
    history_studio_penalty: float = 0.03
    history_content_penalty: float = 0.05
    history_size: int = 50
    uncovered_content_bonus: float = 0.03
    best_bet_fit: float = 0.18
    best_bet_confidence: float = 0.30
    best_bet_relevance: float = 0.60
    best_bet_neighbor_percentile: float = 0.60
    best_bet_anchor_percentile: float = 0.60
    best_bet_metadata_confidence: float = 0.35
    revisit_direct_confidence: float = 0.35
    stretch_contributor_count: int = 3
    stretch_anchor_affinity: float = 0.015
    stretch_anchor_confidence: float = 0.5
    stretch_untested_support: float = 0.5
    stretch_fit_floor: float = 0.0
    stretch_per_dimension: int = 1
    dark_prior_strength: float = 20.0
    dark_threshold: float = 0.55
    dark_min_library: int = 60
    dark_max_library: int = 500
    dark_min_features: int = 4
    dark_min_facet_types: int = 2
    dark_corroboration_bonus: float = 0.15
    blind_spot_per_facet: int = 1
    dormant_min_plays: int = 3
    dormant_min_scenes: int = 2
    dormant_min_positive: float = 0.10
    dormant_floor: float = 0.5
    dormant_per_entity: int = 1
    page_size: int = 20
    for_you_pattern: tuple[str, ...] = (
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "stretch",
        "best_bets",
        "best_bets",
        "stretch",
        "best_bets",
        "revisit",
        "best_bets",
        "stretch",
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "stretch",
        "best_bets",
        "blind_spots",
        "dormant",
    )


@dataclass(frozen=True)
class CuratorConfig:
    feature: FeatureConfig = FeatureConfig()
    model: ModelConfig = ModelConfig()
    ranking: RankingConfig = RankingConfig()
    random_seed: int = 31415

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def feature_json(self) -> str:
        return json.dumps(asdict(self.feature), sort_keys=True, separators=(",", ":"))

    def feature_fingerprint(self) -> str:
        return hashlib.sha256(self.feature_json().encode()).hexdigest()


DEFAULT_CONFIG = CuratorConfig()
