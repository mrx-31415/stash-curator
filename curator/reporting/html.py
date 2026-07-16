"""Generate a self-contained, privacy-aware recommendation evaluation report."""

from __future__ import annotations

import html
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

from curator.explanations import Explanation, ExplanationService, ReasonGraphStore
from curator.model import RecommendationModelStore
from curator.ranking import RecommendationItem, SlateBuilder


@dataclass(frozen=True)
class ReportResult:
    output: Path
    model_id: str
    lane_counts: dict[str, int]
    redacted: bool


class ReportGenerator:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def generate(
        self,
        output: Path,
        *,
        count: int = 20,
        redacted: bool = False,
        stash_url: str | None = None,
    ) -> ReportResult:
        model_id = RecommendationModelStore(self.connection).current_model_id()
        if model_id is None:
            raise RuntimeError("no published model; run build-model first")
        ReasonGraphStore(self.connection).build(model_id)
        explanation_service = ExplanationService(self.connection)
        scores = RecommendationModelStore(self.connection).scores(model_id)
        lanes = ("for_you", "best_bets", "revisit", "discover", "adventure")
        sections = []
        lane_counts: dict[str, int] = {}
        aliases = self._aliases(redacted)
        stash_base_url = None if redacted else self._stash_base_url(stash_url)
        slate_builder = SlateBuilder(self.connection)
        for lane in lanes:
            slate = slate_builder.recommend(lane, count)
            lane_counts[lane] = len(slate.items)
            cards = []
            for item in slate.items:
                explanation = explanation_service.explain_recommendation(item)
                metadata = self._metadata(item.scene_id, aliases, redacted)
                score = scores[item.scene_id]
                cards.append(
                    self._card(
                        metadata,
                        item,
                        score.components,
                        score.neighbors,
                        explanation,
                        aliases,
                        redacted,
                        stash_base_url,
                    )
                )
            diagnostic = "".join(
                f"<li>{html.escape(message)}</li>" for message in slate.diagnostics
            )
            sections.append(
                f"""
                <section id="{lane}">
                  <h2>{html.escape(self._lane_title(lane))} <span>{len(cards)}</span></h2>
                  {'<ul class="diagnostics">' + diagnostic + "</ul>" if diagnostic else ""}
                  <div class="grid">{"".join(cards)}</div>
                </section>
                """
            )
        model_row = self.connection.execute(
            """
            SELECT feature_version, config_json, sync_watermark
            FROM model_version WHERE model_id=?
            """,
            (model_id,),
        ).fetchone()
        summary = html.escape(
            json.dumps(
                {
                    "model_id": model_id,
                    "feature_version": model_row["feature_version"],
                    "sync_watermark": model_row["sync_watermark"],
                    "redacted": redacted,
                    "config": json.loads(model_row["config_json"]),
                },
                sort_keys=True,
                indent=2,
            )
        )
        document = self._document(model_id, summary, "".join(sections), redacted)
        destination = output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8")
        return ReportResult(destination, model_id, lane_counts, redacted)

    def _aliases(self, redacted: bool) -> dict[tuple[str, str], str]:
        if not redacted:
            return {}
        aliases: dict[tuple[str, str], str] = {}
        for entity_type, table, id_column, name_column, prefix in (
            ("scene", "source_scene", "scene_id", "title", "Scene"),
            ("performer", "source_performer", "performer_id", "name", "Performer"),
            ("studio", "source_studio", "studio_id", "name", "Studio"),
            ("tag", "source_tag", "tag_id", "name", "Tag"),
        ):
            for index, row in enumerate(
                self.connection.execute(
                    f"SELECT {id_column}, {name_column} FROM {table} ORDER BY {id_column}"
                ),
                start=1,
            ):
                alias = f"{prefix} {index:03d}"
                aliases[(entity_type, str(row[0]))] = alias
                if row[1]:
                    aliases[(f"{entity_type}_name", str(row[1]))] = alias
        return aliases

    def _metadata(
        self,
        scene_id: str,
        aliases: dict[tuple[str, str], str],
        redacted: bool,
    ) -> dict[str, object]:
        row = self.connection.execute(
            """
            SELECT s.title, s.scene_date, s.studio_id, st.name AS studio_name
            FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
            WHERE s.scene_id=?
            """,
            (scene_id,),
        ).fetchone()
        performers = [
            (str(item["performer_id"]), str(item["name"] or item["performer_id"]))
            for item in self.connection.execute(
                """
                SELECT p.performer_id, p.name FROM scene_performer sp
                JOIN source_performer p ON p.performer_id=sp.performer_id
                WHERE sp.scene_id=? ORDER BY sp.position, p.performer_id
                """,
                (scene_id,),
            )
        ]
        studio_id = str(row["studio_id"]) if row["studio_id"] else None
        return {
            "id": aliases.get(("scene", scene_id), scene_id) if redacted else scene_id,
            "title": aliases.get(("scene", scene_id), scene_id)
            if redacted
            else str(row["title"] or scene_id),
            "date": row["scene_date"],
            "studio": (
                aliases.get(("studio", studio_id), "Studio")
                if redacted and studio_id
                else str(row["studio_name"] or "")
            ),
            "performers": [
                aliases.get(("performer", performer_id), "Performer") if redacted else name
                for performer_id, name in performers
            ],
        }

    def _card(
        self,
        metadata: dict[str, object],
        item: RecommendationItem,
        components: dict[str, object],
        neighbors: tuple[dict[str, object], ...],
        explanation: Explanation,
        aliases: dict[tuple[str, str], str],
        redacted: bool,
        stash_base_url: str | None,
    ) -> str:
        item_data = asdict(item)
        explanation_data = asdict(explanation)
        components_data: object = components
        neighbors_data: object = neighbors
        if redacted:
            item_data = cast(dict[str, Any], ReportGenerator._redact_value(item_data, aliases))
            explanation_data = cast(
                dict[str, Any],
                ReportGenerator._redact_value(explanation_data, aliases),
            )
            explanation_data["summary"] = ReportGenerator._redact_text(
                str(explanation_data["summary"]), aliases
            )
            components_data = ReportGenerator._redact_value(components, aliases)
            neighbors_data = ReportGenerator._redact_value(neighbors, aliases)
        reasons = cast(list[dict[str, Any]], explanation_data["all_reasons"])
        reason_rows = "".join(
            f"<li><code>{html.escape(str(reason['code']))}</code> "
            f"{html.escape(str(reason['direction']))} · {float(reason['magnitude']):.3f} · "
            f"{html.escape(str(reason['visibility']))}</li>"
            for reason in reasons
        )
        debug = html.escape(
            json.dumps(
                {
                    "item": item_data,
                    "components": components_data,
                    "neighbors": neighbors_data,
                },
                sort_keys=True,
                indent=2,
            )
        )
        performer_values = cast(list[object], metadata["performers"])
        performers = ", ".join(map(str, performer_values))
        supporting_evidence = self._supporting_evidence(
            explanation_data, cast(dict[str, object], components_data), redacted, stash_base_url
        )
        score_tree = self._score_tree(item_data, cast(dict[str, object], components_data), redacted)
        scene_link = ""
        title = html.escape(str(metadata["title"]))
        if stash_base_url:
            encoded_scene_id = quote(item.scene_id, safe="")
            scene_url = f"{stash_base_url}/scenes/{encoded_scene_id}"
            screenshot_url = f"{stash_base_url}/scene/{encoded_scene_id}/screenshot"
            scene_link = (
                f'<a class="scene-image" href="{html.escape(scene_url, quote=True)}">'
                f'<img loading="lazy" src="{html.escape(screenshot_url, quote=True)}" '
                f'alt="Cover for {title}"></a>'
            )
            title = f'<a href="{html.escape(scene_url, quote=True)}">{title}</a>'
        return f"""
        <article class="card">
          {scene_link}
          <header><span class="position">#{int(item_data["position"]) + 1}</span>
            <h3>{title}</h3></header>
          <p class="meta">{html.escape(performers)} · {html.escape(str(metadata["studio"]))}
            · {html.escape(str(metadata["date"] or "Unknown date"))}</p>
          <p class="why">{html.escape(str(explanation_data["summary"]))}</p>
          {supporting_evidence}
          <div class="scores">
            <span>Confidence {float(item_data["confidence"]):.2f}</span>
            <span>Lane {float(item_data["lane_value"]):+.3f}</span>
            <span>Utility {float(item_data["final_utility"]):+.3f}</span>
          </div>
          <p class="subtype">{html.escape(str(item_data["source_lane"]))}
            {("· " + html.escape(str(item_data["subtype"]))) if item_data["subtype"] else ""}</p>
          {score_tree}
          <details class="developer"><summary>Reason records (developer view)</summary>
            <ul>{reason_rows}</ul></details>
          <details class="developer"><summary>Raw inspector data (developer view)</summary>
            <pre>{debug}</pre></details>
          <label class="review"><input type="checkbox"> Useful</label>
          <label class="review">Notes <input type="text"></label>
        </article>
        """

    def _supporting_evidence(
        self,
        explanation: dict[str, Any],
        components: dict[str, object],
        redacted: bool,
        stash_base_url: str | None,
    ) -> str:
        reasons = cast(list[dict[str, Any]], explanation.get("all_reasons", []))
        neighbor_reason = next(
            (reason for reason in reasons if reason.get("code") == "appeal.content_neighbor"),
            None,
        )
        sections: list[str] = []
        if neighbor_reason:
            detail = neighbor_reason.get("detail", {})
            raw_neighbors = detail.get("neighbors", []) if isinstance(detail, dict) else []
            rows: list[str] = []
            if isinstance(raw_neighbors, list):
                for neighbor in raw_neighbors[:3]:
                    if not isinstance(neighbor, dict):
                        continue
                    scene_id = str(neighbor.get("scene_id", ""))
                    title = html.escape(
                        str(neighbor.get("title") or scene_id or "Supporting scene")
                    )
                    if stash_base_url and not redacted and scene_id:
                        scene_url = f"{stash_base_url}/scenes/{quote(scene_id, safe='')}"
                        title = f'<a href="{html.escape(scene_url, quote=True)}">{title}</a>'
                    tags = neighbor.get("shared_tags", [])
                    tag_text = (
                        ", ".join(html.escape(str(tag)) for tag in tags)
                        if isinstance(tags, list)
                        else ""
                    )
                    similarity = neighbor.get("similarity")
                    similarity_text = (
                        f" · similarity {float(similarity):.2f}"
                        if isinstance(similarity, (int, float))
                        else ""
                    )
                    shared_text = f" · shared: {tag_text}" if tag_text else ""
                    rows.append(f"<li>{title}{shared_text}{similarity_text}</li>")
            if rows:
                sections.append("<h4>Nearby scenes that worked</h4><ul>" + "".join(rows) + "</ul>")

        content = components.get("content")
        tag_rows: list[str] = []
        if isinstance(content, dict) and isinstance(content.get("top"), list):
            for item in content["top"]:
                if not isinstance(item, dict):
                    continue
                value = self._number(item.get("value"))
                metadata = item.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                name = html.escape(str(metadata.get("tag_name") or item.get("name") or "Tag"))
                confidence = self._number(item.get("confidence"))
                support = metadata.get("document_frequency")
                support_text = (
                    f" · seen on {int(support):,} scenes"
                    if isinstance(support, int) and not isinstance(support, bool)
                    else ""
                )
                effect = "helps" if value > 0 else "holds it back" if value < 0 else "is neutral"
                tag_rows.append(
                    f"<li><strong>{name}</strong> {effect} "
                    f'<span class="number">{value:+.3f}</span> · confidence {confidence:.2f}'
                    f"{support_text}</li>"
                )
        if tag_rows:
            sections.append("<h4>Tag signals</h4><ul>" + "".join(tag_rows) + "</ul>")

        reason_rows: list[str] = []
        reasons = cast(list[dict[str, Any]], explanation.get("all_reasons", []))
        for reason in reasons:
            code = str(reason.get("code", ""))
            if (
                code
                not in {
                    "appeal.performer_identity",
                    "appeal.performer_similar",
                    "appeal.studio",
                }
                or reason.get("direction") != "positive"
            ):
                continue
            subject_id = str(reason.get("subject_id") or "")
            entity_type = "studio" if code == "appeal.studio" else "performer"
            subject = html.escape(self._entity_name(entity_type, subject_id, redacted))
            magnitude = self._number(reason.get("magnitude"))
            if code == "appeal.performer_similar":
                detail = reason.get("detail")
                detail = detail if isinstance(detail, dict) else {}
                matches = detail.get("matches")
                first = matches[0] if isinstance(matches, list) and matches else None
                known_id = str(first.get("performer_id") or "") if isinstance(first, dict) else ""
                known = html.escape(self._entity_name("performer", known_id, redacted))
                aspects = detail.get("shared_aspects")
                aspect_text = (
                    ", ".join(html.escape(str(value)) for value in aspects)
                    if isinstance(aspects, list)
                    else "their profiles"
                )
                text = f"{subject} resembles {known}, especially in {aspect_text}"
            elif code == "appeal.studio":
                text = f"Your history with {subject} contributes"
            else:
                text = f"Your history with {subject} contributes"
            reason_rows.append(f'<li>{text} <span class="number">{magnitude:+.3f}</span></li>')
        if reason_rows:
            sections.append(
                "<h4>Performer and studio signals</h4><ul>" + "".join(reason_rows) + "</ul>"
            )
        if not sections:
            return ""
        return (
            '<details class="supporting-evidence"><summary>Supporting evidence</summary>'
            + "".join(sections)
            + "</details>"
        )

    def _score_tree(
        self, item: dict[str, Any], components: dict[str, object], redacted: bool
    ) -> str:
        appeal_children: list[str] = []
        component_labels = {
            "baseline": "Library baseline",
            "content": "Tag preferences",
            "content_neighbor": "Nearby successful scenes",
            "performer_identity": "Performer history",
            "performer_similarity": "Similar performers",
            "studio": "Studio history",
            "structure": "Scene structure",
        }
        for key, label in component_labels.items():
            component = components.get(key)
            if not isinstance(component, dict):
                continue
            value = self._number(component.get("value"))
            detail_rows = self._component_details(key, component, redacted)
            appeal_children.append(self._tree_node(label, value, detail_rows))
        direct = components.get("direct")
        if isinstance(direct, dict):
            confidence = self._number(direct.get("confidence"))
            signals = direct.get("signals")
            signal_text = ", ".join(map(str, signals)) if isinstance(signals, list) else "none"
            appeal_children.append(
                self._tree_node(
                    "Direct scene history",
                    self._number(direct.get("value")),
                    [f"Confidence {confidence:.2f}", f"Signals: {html.escape(signal_text)}"],
                )
            )
        appeal_node = self._tree_node(
            "Appeal",
            self._number(item.get("appeal")),
            [
                '<span class="hint">General preference evidence is blended with direct scene '
                "history; these children are not always a simple sum.</span>",
                *appeal_children,
            ],
        )

        fit_children = [
            self._tree_leaf("Appeal carried into Current Fit", self._number(item.get("appeal")))
        ]
        fit = components.get("fit")
        if isinstance(fit, dict):
            for key, label in (
                ("cooldown", "Cooldown"),
                ("satiation", "Recent satiation"),
                ("not_now", "Not-now adjustment"),
            ):
                fit_children.append(self._tree_leaf(label, self._number(fit.get(key))))
            fit_children.append(
                f'<li><span>Recovery</span><span class="number">'
                f"{self._number(fit.get('recovery')):.2f}</span></li>"
            )
        fit_node = self._tree_node(
            "Current Fit", self._number(item.get("current_fit")), fit_children
        )
        qualification = item.get("qualification")
        qualification_rows: list[str] = []
        if isinstance(qualification, dict):
            for key, value in qualification.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    qualification_rows.append(
                        self._tree_leaf(key.replace("_", " ").title(), float(value))
                    )
        policy_inputs = [
            '<span class="hint">The lane policy combines and ranks these inputs; they are not '
            "an additive subtotal.</span>",
            appeal_node,
            fit_node,
            self._tree_leaf("Confidence", self._number(item.get("confidence"))),
            *qualification_rows,
        ]
        lane_node = self._tree_node(
            f"{str(item.get('source_lane', 'lane')).replace('_', ' ').title()} lane score",
            self._number(item.get("lane_value")),
            policy_inputs,
        )
        adjustment_rows: list[str] = []
        for direction, values in (
            ("Bonus", item.get("bonuses")),
            ("Penalty", item.get("penalties")),
        ):
            if not isinstance(values, dict):
                continue
            sign = 1.0 if direction == "Bonus" else -1.0
            for name, value in values.items():
                number = self._number(value) * sign
                if abs(number) > 1e-12:
                    adjustment_rows.append(
                        self._tree_leaf(f"{direction}: {str(name).replace('_', ' ')}", number)
                    )
        children = [lane_node, *(adjustment_rows or ['<li class="hint">No page adjustments</li>'])]
        return (
            '<details class="score-tree"><summary>How the score was built '
            f'<span class="number">{self._number(item.get("final_utility")):+.3f}</span>'
            "</summary><ul>" + "".join(children) + "</ul></details>"
        )

    def _component_details(
        self, key: str, component: dict[str, object], redacted: bool
    ) -> list[str]:
        rows: list[str] = []
        top = component.get("top")
        if isinstance(top, list):
            for item in top[:5]:
                if not isinstance(item, dict):
                    continue
                metadata = item.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                name = str(metadata.get("tag_name") or item.get("name") or "Feature")
                rows.append(self._tree_leaf(name, self._number(item.get("value"))))
        entity_key = "studios" if key == "studio" else "performers"
        entities = component.get(entity_key)
        if isinstance(entities, list):
            entity_type = "studio" if key == "studio" else "performer"
            id_key = f"{entity_type}_id"
            for item in entities[:5]:
                if not isinstance(item, dict):
                    continue
                name = self._entity_name(entity_type, str(item.get(id_key) or ""), redacted)
                rows.append(self._tree_leaf(name, self._number(item.get("value"))))
        confidence = component.get("evidence_confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            rows.append(f"Evidence confidence {float(confidence):.2f}")
        return rows

    def _entity_name(self, entity_type: str, entity_id: str, redacted: bool) -> str:
        if not entity_id:
            return "Unknown"
        if redacted and entity_id.startswith(("Performer ", "Studio ")):
            return entity_id
        table, id_column = (
            ("source_performer", "performer_id")
            if entity_type == "performer"
            else ("source_studio", "studio_id")
        )
        if redacted:
            rows = self.connection.execute(f"SELECT {id_column} FROM {table} ORDER BY {id_column}")
            for index, row in enumerate(rows, start=1):
                if str(row[0]) == entity_id:
                    return f"{'Performer' if entity_type == 'performer' else 'Studio'} {index:03d}"
            return "Unknown"
        row = self.connection.execute(
            f"SELECT name FROM {table} WHERE {id_column}=?", (entity_id,)
        ).fetchone()
        return str(row[0] or entity_id) if row else entity_id

    @staticmethod
    def _number(value: object) -> float:
        return (
            float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
        )

    @staticmethod
    def _tree_leaf(label: str, value: float) -> str:
        return f'<li><span>{html.escape(label)}</span><span class="number">{value:+.3f}</span></li>'

    @staticmethod
    def _tree_node(label: str, value: float, children: list[str]) -> str:
        return (
            "<li><details><summary>"
            f'<span>{html.escape(label)}</span><span class="number">{value:+.3f}</span>'
            "</summary><ul>"
            + "".join(
                child if child.lstrip().startswith("<li") else f"<li>{child}</li>"
                for child in children
            )
            + "</ul></details></li>"
        )

    @staticmethod
    def _stash_base_url(stash_url: str | None) -> str | None:
        if not stash_url:
            return None
        parsed = urlsplit(stash_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Stash URL must be an absolute HTTP(S) URL")
        path = parsed.path.rstrip("/")
        if path.endswith("/graphql"):
            path = path[: -len("/graphql")]
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    @staticmethod
    def _redact_value(value: object, aliases: dict[tuple[str, str], str]) -> object:
        identifier_aliases = {identifier: alias for (_, identifier), alias in aliases.items()}
        if isinstance(value, str):
            return identifier_aliases.get(value, value)
        if isinstance(value, dict):
            return {
                str(ReportGenerator._redact_value(key, aliases)): ReportGenerator._redact_value(
                    item, aliases
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [ReportGenerator._redact_value(item, aliases) for item in value]
        return value

    @staticmethod
    def _redact_text(text: str, aliases: dict[tuple[str, str], str]) -> str:
        # Names are replaced only in prose; numeric IDs are handled as exact structured values.
        for (kind, name), alias in sorted(aliases.items(), key=lambda item: -len(item[0][1])):
            if kind.endswith("_name") and name:
                text = text.replace(name, alias)
        return text

    @staticmethod
    def _lane_title(lane: str) -> str:
        return {
            "for_you": "For You",
            "best_bets": "Best Bets",
            "revisit": "Revisit",
            "discover": "Discover",
            "adventure": "Adventure",
        }[lane]

    @staticmethod
    def _document(model_id: str, summary: str, sections: str, redacted: bool) -> str:
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stash Curator evaluation</title>
<style>
:root {{ color-scheme: dark; font: 15px/1.45 system-ui,sans-serif; background:#111; color:#eee; }}
body {{ margin:0 auto; max-width:1500px; padding:2rem; }}
h1,h2,h3 {{ line-height:1.1; }} nav {{ display:flex; gap:1rem; flex-wrap:wrap; position:sticky;
top:0; background:#111e; padding:1rem 0; z-index:2; }} a {{ color:#9cc8ff; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:1rem; }}
.card {{ background:#1d1d21; border:1px solid #383840; border-radius:12px; padding:1rem; }}
.scene-image {{ display:block; margin:-1rem -1rem 1rem; overflow:hidden;
border-radius:11px 11px 0 0; aspect-ratio:16/9; background:#09090b; }}
.scene-image img {{ display:block; width:100%; height:100%; object-fit:cover; }}
body:has(#toggle-images:not(:checked)) .scene-image {{ display:none; }}
.card header {{ display:flex; gap:.7rem; align-items:baseline; }} .position {{ color:#aaa; }}
.meta,.subtype {{ color:#aaa; }} .why {{ font-size:1.04rem; min-height:4.5em; }}
.scores {{ display:flex; flex-wrap:wrap; gap:.4rem; }} .scores span {{ background:#292932;
padding:.25rem .45rem; border-radius:5px; }} details {{ margin-top:.8rem; }}
.report-controls {{ display:flex; gap:1rem; align-items:center; margin:.8rem 0; }}
.report-controls label {{ cursor:pointer; user-select:none; }}
.supporting-evidence h4 {{ margin:.8rem 0 .2rem; }}
.supporting-evidence ul {{ margin-top:.25rem; }}
.number {{ font-variant-numeric:tabular-nums; color:#b9d6ff; margin-left:auto; }}
.score-tree > ul,.score-tree ul {{ list-style:none; padding-left:1rem; }}
.score-tree li {{ margin:.3rem 0; }}
.score-tree summary {{ display:flex; gap:.7rem; cursor:pointer; }}
.score-tree summary::marker,.score-tree summary::-webkit-details-marker {{ display:none; }}
.score-tree summary::before {{ content:"▸"; color:#9cc8ff; }}
.score-tree details[open] > summary::before {{ content:"▾"; }}
.score-tree li:not(:has(details)) {{ display:flex; gap:.7rem; }}
.score-tree .hint,.hint {{ color:#aaa; font-size:.88rem; }}
.developer {{ color:#bbb; }}
pre {{ overflow:auto; font-size:.75rem; }} .review {{ display:block; margin-top:.7rem; }}
input[type=text] {{ width:70%; }} .diagnostics {{ color:#f0c674; }}
</style></head><body>
<h1>Stash Curator evaluation</h1>
<p>Navigate your library, guided by your taste.</p>
<p>Model <code>{html.escape(model_id)}</code> ·
  {"redacted" if redacted else "private local detail"}</p>
<div class="report-controls"><label><input id="toggle-images" type="checkbox" checked>
Show scene images</label></div>
<nav><a href="#for_you">For You</a><a href="#best_bets">Best Bets</a>
<a href="#revisit">Revisit</a><a href="#discover">Discover</a>
<a href="#adventure">Adventure</a><a href="#build">Build</a></nav>
{sections}
<section id="build"><h2>Build and configuration</h2><pre>{summary}</pre></section>
</body></html>"""
