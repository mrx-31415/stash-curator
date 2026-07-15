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

    @staticmethod
    def _card(
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
        supporting_scenes = ReportGenerator._supporting_scenes(
            explanation_data, redacted, stash_base_url
        )
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
          {supporting_scenes}
          <div class="scores">
            <span>Appeal {float(item_data["appeal"]):+.3f}</span>
            <span>Current Fit {float(item_data["current_fit"]):+.3f}</span>
            <span>Confidence {float(item_data["confidence"]):.2f}</span>
            <span>Lane {float(item_data["lane_value"]):+.3f}</span>
            <span>Utility {float(item_data["final_utility"]):+.3f}</span>
          </div>
          <p class="subtype">{html.escape(str(item_data["source_lane"]))}
            {("· " + html.escape(str(item_data["subtype"]))) if item_data["subtype"] else ""}</p>
          <details><summary>Reason graph</summary><ul>{reason_rows}</ul></details>
          <details><summary>Full inspector data</summary><pre>{debug}</pre></details>
          <label class="review"><input type="checkbox"> Useful</label>
          <label class="review">Notes <input type="text"></label>
        </article>
        """

    @staticmethod
    def _supporting_scenes(
        explanation: dict[str, Any], redacted: bool, stash_base_url: str | None
    ) -> str:
        reasons = cast(list[dict[str, Any]], explanation.get("all_reasons", []))
        neighbor_reason = next(
            (reason for reason in reasons if reason.get("code") == "appeal.content_neighbor"),
            None,
        )
        if not neighbor_reason:
            return ""
        detail = neighbor_reason.get("detail", {})
        raw_neighbors = detail.get("neighbors", []) if isinstance(detail, dict) else []
        if not isinstance(raw_neighbors, list):
            return ""
        rows: list[str] = []
        for neighbor in raw_neighbors[:3]:
            if not isinstance(neighbor, dict):
                continue
            scene_id = str(neighbor.get("scene_id", ""))
            title = html.escape(str(neighbor.get("title") or scene_id or "Supporting scene"))
            if stash_base_url and not redacted and scene_id:
                scene_url = f"{stash_base_url}/scenes/{quote(scene_id, safe='')}"
                title = f'<a href="{html.escape(scene_url, quote=True)}">{title}</a>'
            tags = neighbor.get("shared_tags", [])
            tag_text = (
                ", ".join(html.escape(str(tag)) for tag in tags) if isinstance(tags, list) else ""
            )
            similarity = neighbor.get("similarity")
            similarity_text = (
                f" · similarity {float(similarity):.2f}"
                if isinstance(similarity, (int, float))
                else ""
            )
            shared_text = f" · shared: {tag_text}" if tag_text else ""
            rows.append(f"<li>{title}{shared_text}{similarity_text}</li>")
        if not rows:
            return ""
        return (
            '<details class="supporting-scenes"><summary>Supporting scenes and shared content'
            "</summary><ul>" + "".join(rows) + "</ul></details>"
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
.card header {{ display:flex; gap:.7rem; align-items:baseline; }} .position {{ color:#aaa; }}
.meta,.subtype {{ color:#aaa; }} .why {{ font-size:1.04rem; min-height:4.5em; }}
.scores {{ display:flex; flex-wrap:wrap; gap:.4rem; }} .scores span {{ background:#292932;
padding:.25rem .45rem; border-radius:5px; }} details {{ margin-top:.8rem; }}
pre {{ overflow:auto; font-size:.75rem; }} .review {{ display:block; margin-top:.7rem; }}
input[type=text] {{ width:70%; }} .diagnostics {{ color:#f0c674; }}
</style></head><body>
<h1>Stash Curator evaluation</h1>
<p>Navigate your library, guided by your taste.</p>
<p>Model <code>{html.escape(model_id)}</code> ·
  {"redacted" if redacted else "private local detail"}</p>
<nav><a href="#for_you">For You</a><a href="#best_bets">Best Bets</a>
<a href="#revisit">Revisit</a><a href="#discover">Discover</a>
<a href="#adventure">Adventure</a><a href="#build">Build</a></nav>
{sections}
<section id="build"><h2>Build and configuration</h2><pre>{summary}</pre></section>
</body></html>"""
