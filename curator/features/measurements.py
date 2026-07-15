"""Conservative parsing and normalization of performer measurements."""

from __future__ import annotations

import re
from dataclasses import dataclass

CUP_ALIASES = {
    "AA": (0.0, "AA"),
    "A": (1.0, "A"),
    "B": (2.0, "B"),
    "C": (3.0, "C"),
    "D": (4.0, "D"),
    "DD": (5.0, "E"),
    "E": (5.0, "E"),
    "DDD": (6.0, "F"),
    "F": (6.0, "F"),
    "G": (7.0, "G"),
    "H": (8.0, "H"),
    "I": (9.0, "I"),
    "J": (10.0, "J"),
    "K": (11.0, "K"),
}

MEASUREMENT_PATTERN = re.compile(
    r"^\s*(?P<band>\d{2,3})\s*(?P<cup>[A-Za-z]{1,3})?\s*[-/]\s*"
    r"(?P<waist>\d{2,3}(?:\.\d+)?)\s*[-/]\s*(?P<hips>\d{2,3}(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True)
class BodyMeasurements:
    band_inches: float
    cup_index: float | None
    normalized_cup: str | None
    waist_inches: float
    hip_inches: float
    waist_to_hip: float
    confidence: float


def parse_measurements(value: str | None) -> BodyMeasurements | None:
    if not value:
        return None
    match = MEASUREMENT_PATTERN.match(value)
    if not match:
        return None
    band = float(match.group("band"))
    waist = float(match.group("waist"))
    hips = float(match.group("hips"))
    if not 20 <= band <= 70 or not 15 <= waist <= 70 or not 20 <= hips <= 80:
        return None
    cup_raw = (match.group("cup") or "").upper()
    cup = CUP_ALIASES.get(cup_raw)
    confidence = 0.85 if cup_raw in {"DD", "DDD"} else 0.95
    return BodyMeasurements(
        band_inches=band,
        cup_index=cup[0] if cup else None,
        normalized_cup=cup[1] if cup else None,
        waist_inches=waist,
        hip_inches=hips,
        waist_to_hip=waist / hips,
        confidence=confidence if cup else 0.75,
    )


def augmentation_category(value: str | None) -> str | None:
    if not value:
        return None
    folded = value.strip().casefold()
    if folded in {"yes", "y", "true", "fake", "enhanced", "augmented"}:
        return "augmented"
    if folded in {"no", "n", "false", "natural", "none"}:
        return "natural"
    return None


def presence_category(value: str | None) -> str | None:
    if not value:
        return None
    folded = value.strip().casefold()
    return "absent" if folded in {"none", "no", "n", "false"} else "present"
