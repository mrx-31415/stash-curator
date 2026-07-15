"""Build and persist truthful reasons directly from model decomposition."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from curator.model import ModelSceneScore, RecommendationModelStore
from curator.storage import transaction


@dataclass(frozen=True)
class Reason:
    code: str
    direction: str
    magnitude: float
    confidence: float
    subject_type: str | None
    subject_id: str | None
    visibility: str
    provenance: str
    detail: dict[str, object]
    model_id: str
    feature_version: str


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _direction(value: float) -> str:
    return "positive" if value > 1e-9 else "negative" if value < -1e-9 else "neutral"


class ReasonGraphStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def build(self, model_id: str) -> None:
        scores = RecommendationModelStore(self.connection).scores(model_id)
        row = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"unknown model: {model_id}")
        feature_version = str(row[0])
        graphs = {
            scene_id: self._scene_reasons(score, feature_version)
            for scene_id, score in scores.items()
        }
        with transaction(self.connection):
            self.connection.execute("DELETE FROM model_scene_reason WHERE model_id=?", (model_id,))
            self.connection.executemany(
                """
                INSERT INTO model_scene_reason(
                    model_id, scene_id, reason_index, reason_code, direction,
                    magnitude, confidence, subject_type, subject_id, visibility,
                    provenance, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        model_id,
                        scene_id,
                        index,
                        reason.code,
                        reason.direction,
                        reason.magnitude,
                        reason.confidence,
                        reason.subject_type,
                        reason.subject_id,
                        reason.visibility,
                        reason.provenance,
                        json.dumps(reason.detail, sort_keys=True, separators=(",", ":")),
                    )
                    for scene_id, reasons in sorted(graphs.items())
                    for index, reason in enumerate(reasons)
                ),
            )

    def reasons(self, model_id: str, scene_id: str) -> tuple[Reason, ...]:
        model = self.connection.execute(
            "SELECT feature_version FROM model_version WHERE model_id=?", (model_id,)
        ).fetchone()
        if model is None:
            raise RuntimeError(f"unknown model: {model_id}")
        rows = self.connection.execute(
            """
            SELECT * FROM model_scene_reason
            WHERE model_id=? AND scene_id=? ORDER BY reason_index
            """,
            (model_id, scene_id),
        )
        return tuple(
            Reason(
                str(row["reason_code"]),
                str(row["direction"]),
                float(row["magnitude"]),
                float(row["confidence"]),
                str(row["subject_type"]) if row["subject_type"] else None,
                str(row["subject_id"]) if row["subject_id"] else None,
                str(row["visibility"]),
                str(row["provenance"]),
                json.loads(row["detail_json"]),
                model_id,
                str(model[0]),
            )
            for row in rows
        )

    def _scene_reasons(self, score: ModelSceneScore, feature_version: str) -> tuple[Reason, ...]:
        reasons: list[Reason] = []
        self._content_reasons(score, feature_version, reasons)
        self._performer_reasons(score, feature_version, reasons)
        self._studio_reasons(score, feature_version, reasons)
        self._neighbor_reason(score, feature_version, reasons)
        self._direct_reasons(score, feature_version, reasons)
        self._fit_reasons(score, feature_version, reasons)
        return tuple(
            sorted(
                reasons,
                key=lambda item: (
                    0 if item.direction == "positive" else 1,
                    -item.magnitude,
                    item.code,
                    item.subject_id or "",
                ),
            )
        )

    def _content_reasons(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        content = score.components.get("content")
        if not isinstance(content, dict) or not isinstance(content.get("top"), list):
            return
        related_names: dict[str, list[str]] = {"positive": [], "negative": []}
        for item in content["top"]:
            if not isinstance(item, dict):
                continue
            value = _number(item.get("value"))
            metadata = item.get("metadata", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            name = str(metadata.get("tag_name", "")).strip()
            direction = "positive" if value > 0 else "negative"
            if abs(value) >= 1e-6 and name and name not in related_names[direction]:
                related_names[direction].append(name)
        for item in content["top"]:
            if not isinstance(item, dict):
                continue
            value = _number(item.get("value"))
            if abs(value) < 1e-6:
                continue
            metadata = item.get("metadata", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            reasons.append(
                self._reason(
                    score,
                    feature_version,
                    "appeal.tag_positive" if value > 0 else "appeal.tag_negative",
                    value,
                    _number(item.get("confidence")),
                    "tag",
                    str(metadata.get("tag_id")) if metadata.get("tag_id") else None,
                    "learned_feature_affinity",
                    {
                        "name": str(metadata.get("tag_name", "this content pattern")),
                        "related_names": related_names[_direction(value)][:3],
                        "contribution": value,
                        "support": metadata.get("document_frequency"),
                    },
                )
            )

    def _performer_reasons(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        identity = score.components.get("performer_identity")
        if isinstance(identity, dict) and isinstance(identity.get("performers"), list):
            for item in identity["performers"]:
                if not isinstance(item, dict):
                    continue
                value = _number(item.get("value"))
                if abs(value) < 1e-6:
                    continue
                performer_id = str(item.get("performer_id", "")) or None
                reasons.append(
                    self._reason(
                        score,
                        feature_version,
                        "appeal.performer_identity",
                        value,
                        score.confidence,
                        "performer",
                        performer_id,
                        "performer_identity_model",
                        dict(item),
                    )
                )
        similar = score.components.get("performer_similarity")
        if not isinstance(similar, dict) or not isinstance(similar.get("performers"), list):
            return
        for item in similar["performers"]:
            if not isinstance(item, dict):
                continue
            value = _number(item.get("value"))
            matches = item.get("matches", [])
            if abs(value) < 1e-6 or not isinstance(matches, list) or not matches:
                continue
            performer_id = str(item.get("performer_id", "")) or None
            ordered_matches = self._supporting_matches(matches, value)
            representative = ordered_matches[0]
            reasons.append(
                self._reason(
                    score,
                    feature_version,
                    "appeal.performer_similar",
                    value,
                    score.confidence,
                    "performer",
                    performer_id,
                    "performer_profile_similarity",
                    {
                        "matches": ordered_matches,
                        "value": value,
                        "similarity": representative.get("similarity"),
                        "shared_aspects": self._shared_aspects(representative),
                        "block_similarities": representative.get("blocks", {}),
                        "profile_description": self._profile_description(
                            performer_id, feature_version
                        ),
                    },
                )
            )

    @staticmethod
    def _supporting_matches(matches: list[object], value: float) -> list[dict[str, object]]:
        valid = [dict(item) for item in matches if isinstance(item, dict)]

        def key(item: dict[str, object]) -> tuple[bool, float, str]:
            affinity = _number(item.get("affinity"))
            agrees = affinity * value > 0
            impact = abs(affinity) * _number(item.get("similarity")) ** 3
            return (not agrees, -impact, str(item.get("performer_id", "")))

        return sorted(valid, key=key)

    @staticmethod
    def _shared_aspects(match: dict[str, object]) -> list[str]:
        blocks = match.get("blocks")
        if not isinstance(blocks, dict):
            return []
        labels = {
            "content": "the kinds of scenes they appear in",
            "proportions": "body proportions",
            "age": "age at recording",
            "augmentation": "augmentation profile",
            "appearance": "broad appearance profile",
            "tattoos": "tattoo profile",
            "piercings": "piercing profile",
            "eyes": "eye color",
        }
        ranked = sorted(
            (
                (_number(similarity), labels.get(str(block), str(block).replace("_", " ")))
                for block, similarity in blocks.items()
                if _number(similarity) > 0.05
            ),
            key=lambda item: (-item[0], item[1]),
        )
        return [label for _, label in ranked[:3]]

    def _profile_description(self, performer_id: str | None, feature_version: str) -> str:
        if performer_id is None:
            return "a similar overall performer profile"
        rows = self.connection.execute(
            """
            SELECT fd.family, fd.name, ef.value FROM entity_feature ef
            JOIN feature_definition fd ON fd.feature_id=ef.feature_id
            WHERE ef.feature_version=? AND ef.entity_type='performer'
              AND ef.entity_id=? AND fd.family LIKE 'profile:%'
            """,
            (feature_version, performer_id),
        )
        values = {(str(row["family"]), str(row["name"])): float(row["value"]) for row in rows}
        phrases: list[str] = []
        height = values.get(("profile:proportions", "height_cm"))
        if height is not None:
            phrases.append(
                "shorter stature"
                if height < 160
                else "taller stature"
                if height > 175
                else "similar height"
            )
        cup = values.get(("profile:proportions", "cup_index"))
        if cup is not None:
            phrases.append(
                "fuller bust" if cup >= 5 else "smaller bust" if cup <= 2 else "mid-range bust"
            )
        ratio = values.get(("profile:proportions", "waist_to_hip"))
        if ratio is not None:
            phrases.append(
                "pronounced waist-to-hip proportions"
                if ratio <= 0.72
                else "straighter waist-to-hip proportions"
                if ratio >= 0.84
                else "balanced waist-to-hip proportions"
            )
        if ("profile:tattoos", "present") in values:
            phrases.append("visible tattoos")
        if not phrases:
            return "a similar overall performer profile"
        return ", ".join(phrases[:3])

    def _studio_reasons(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        studio = score.components.get("studio")
        if not isinstance(studio, dict) or not isinstance(studio.get("studios"), list):
            return
        for item in studio["studios"]:
            if not isinstance(item, dict):
                continue
            value = _number(item.get("value"))
            if abs(value) < 1e-6:
                continue
            studio_id = str(item.get("studio_id", "")) or None
            reasons.append(
                self._reason(
                    score,
                    feature_version,
                    "appeal.studio",
                    value,
                    score.confidence,
                    "studio",
                    studio_id,
                    "studio_affinity",
                    {"studio_id": studio_id},
                )
            )

    def _neighbor_reason(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        neighbor = score.components.get("content_neighbor")
        value = _number(neighbor.get("value")) if isinstance(neighbor, dict) else 0.0
        if abs(value) < 1e-6 or not score.neighbors:
            return
        reasons.append(
            self._reason(
                score,
                feature_version,
                "appeal.content_neighbor",
                value,
                score.confidence,
                "scene",
                str(score.neighbors[0].get("scene_id", "")) or None,
                "content_neighbor_model",
                {"neighbors": list(score.neighbors)},
            )
        )

    def _direct_reasons(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        direct = score.components.get("direct")
        if not isinstance(direct, dict) or score.direct_confidence <= 0:
            return
        reasons.append(
            self._reason(
                score,
                feature_version,
                "direct.positive" if score.direct_appeal > 0 else "direct.negative",
                score.direct_appeal,
                score.direct_confidence,
                "scene",
                score.scene_id,
                "exact_scene_outcomes",
                {
                    "signals": direct.get("signals", []),
                    "effective_evidence": direct.get("effective_evidence", 0),
                },
            )
        )
        residual = _number(direct.get("residual"))
        if abs(residual) >= 0.10:
            reasons.append(
                self._reason(
                    score,
                    feature_version,
                    "direct.residual",
                    residual,
                    score.direct_confidence,
                    "scene",
                    score.scene_id,
                    "direct_model_residual",
                    {"residual": residual},
                )
            )

    def _fit_reasons(
        self, score: ModelSceneScore, feature_version: str, reasons: list[Reason]
    ) -> None:
        fit = score.components.get("fit")
        if not isinstance(fit, dict):
            return
        for key, code in (
            ("cooldown", "fit.cooldown"),
            ("satiation", "fit.satiation"),
            ("not_now", "fit.not_now"),
        ):
            value = _number(fit.get(key))
            if abs(value) > 1e-6:
                reasons.append(
                    self._reason(
                        score,
                        feature_version,
                        code,
                        value,
                        1.0,
                        "scene",
                        score.scene_id,
                        "current_fit_adjustment",
                        {key: value, "recovery": fit.get("recovery")},
                    )
                )

    @staticmethod
    def _reason(
        score: ModelSceneScore,
        feature_version: str,
        code: str,
        value: float,
        confidence: float,
        subject_type: str | None,
        subject_id: str | None,
        provenance: str,
        detail: dict[str, object],
    ) -> Reason:
        return Reason(
            code,
            _direction(value),
            min(1.0, abs(value)),
            max(0.0, min(1.0, confidence)),
            subject_type,
            subject_id,
            ReasonGraphStore._visibility(code),
            provenance,
            detail,
            score.model_id,
            feature_version,
        )

    @staticmethod
    def _visibility(code: str) -> str:
        if code == "appeal.performer_similar":
            return "sensitive"
        if code.startswith("direct.") or code.startswith("fit."):
            return "private"
        return "standard"
