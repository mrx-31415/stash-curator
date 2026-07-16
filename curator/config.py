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
    algorithm_version: int = 3
    affinity_prior: float = 1.0
    affinity_confidence_scale: float = 3.0
    direct_confidence_scale: float = 0.8
    cooldown_center_days: float = 90.0
    cooldown_width_days: float = 15.0
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
    discover_anchor: float = 0.08
    page_size: int = 20
    for_you_pattern: tuple[str, ...] = (
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "discover",
        "best_bets",
        "best_bets",
        "discover",
        "best_bets",
        "revisit",
        "best_bets",
        "discover",
        "best_bets",
        "best_bets",
        "revisit",
        "best_bets",
        "discover",
        "best_bets",
        "adventure",
        "best_bets",
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
