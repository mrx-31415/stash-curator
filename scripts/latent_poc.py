"""Disposable latent-scene-model evaluation against Curator's sidecar."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

import numpy as np
from scipy.sparse import coo_matrix
from scipy.stats import spearmanr
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import MaxAbsScaler, normalize


def _matrix(connection: sqlite3.Connection, version: str, scene_ids: list[str]):
    connection.execute("CREATE TEMP TABLE poc_scene(scene_id TEXT PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO poc_scene VALUES (?)", ((scene_id,) for scene_id in scene_ids)
    )
    scene_index = {scene_id: index for index, scene_id in enumerate(scene_ids)}
    feature_index: dict[str, int] = {}
    feature_names: list[str] = []
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    performer_names = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT performer_id, name FROM source_performer")
    }
    studio_names = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT studio_id, name FROM source_studio")
    }
    tag_names = {
        str(row[0]): str(row[1] or row[0])
        for row in connection.execute("SELECT tag_id, name FROM source_tag")
    }

    def add(scene_id: str, key: str, label: str, value: float) -> None:
        if scene_id not in scene_index or value == 0:
            return
        column = feature_index.get(key)
        if column is None:
            column = len(feature_names)
            feature_index[key] = column
            feature_names.append(label)
        rows.append(scene_index[scene_id])
        columns.append(column)
        values.append(value)

    for row in connection.execute(
        """
        SELECT ef.entity_id, ef.feature_id, fd.family, fd.name, fd.metadata_json,
               ef.value * ef.confidence AS weighted_value
        FROM entity_feature ef JOIN feature_definition fd ON fd.feature_id=ef.feature_id
        JOIN poc_scene selected ON selected.scene_id=ef.entity_id
        WHERE ef.feature_version=? AND ef.entity_type='scene'
        """,
        (version,),
    ):
        metadata = json.loads(row[4])
        family, name = str(row[2]), str(row[3])
        if family == "content":
            label = str(metadata.get("tag_name", name))
        elif family == "performer_identity":
            label = f"performer: {performer_names.get(str(metadata.get('performer_id')), name)}"
        elif family == "studio":
            label = f"studio: {studio_names.get(str(metadata.get('studio_id')), name)}"
        else:
            label = name.replace("_", " ")
        add(str(row[0]), f"scene:{row[1]}", label, float(row[5]))

    for row in connection.execute(
        """
        SELECT sp.scene_id, ef.feature_id, fd.family, fd.name, fd.metadata_json,
               avg(ef.value * ef.confidence) AS weighted_value
        FROM scene_performer sp
        JOIN poc_scene selected ON selected.scene_id=sp.scene_id
        JOIN entity_feature ef ON ef.entity_id=sp.performer_id
        JOIN feature_definition fd ON fd.feature_id=ef.feature_id
        WHERE ef.feature_version=? AND ef.entity_type='performer'
          AND fd.family LIKE 'profile:%'
        GROUP BY sp.scene_id, ef.feature_id, fd.family, fd.name, fd.metadata_json
        """,
        (version,),
    ):
        family = str(row[2]).removeprefix("profile:").replace("_", " ")
        name = str(row[3]).replace("_", " ")
        metadata = json.loads(row[4])
        label = tag_names.get(name.removeprefix("tag:"), name) if family == "content" else name
        add(str(row[0]), f"profile:{row[1]}", f"performer {family}: {label}", float(row[5]))

    matrix = coo_matrix(
        (values, (rows, columns)), shape=(len(scene_ids), len(feature_names)), dtype=np.float64
    ).tocsr()
    return scene_ids, feature_names, matrix


def _metadata(connection: sqlite3.Connection) -> dict[str, dict[str, str]]:
    result = {
        str(row[0]): {
            "title": str(row[1] or row[0]),
            "studio": str(row[2] or ""),
            "performers": "",
        }
        for row in connection.execute(
            """
            SELECT s.scene_id, s.title, st.name FROM source_scene s
            JOIN poc_scene selected ON selected.scene_id=s.scene_id
            LEFT JOIN source_studio st ON st.studio_id=s.studio_id
            """
        )
    }
    performers: dict[str, list[str]] = {}
    for row in connection.execute(
        """
        SELECT sp.scene_id, p.name FROM scene_performer sp
        JOIN poc_scene selected ON selected.scene_id=sp.scene_id
        JOIN source_performer p ON p.performer_id=sp.performer_id
        ORDER BY sp.scene_id, sp.position
        """
    ):
        performers.setdefault(str(row[0]), []).append(str(row[1] or "Unknown"))
    for scene_id, names in performers.items():
        result[scene_id]["performers"] = ", ".join(names)
    return result


def _card(
    scene_id: str,
    metadata: dict[str, str],
    predicted: float,
    current: float,
    cluster: int,
    features: list[str],
    neighbor: str,
    similarity: float,
    stash_url: str | None,
) -> str:
    title = html.escape(metadata["title"])
    image = ""
    if stash_url:
        base = stash_url.removesuffix("/graphql").rstrip("/")
        encoded = quote(scene_id, safe="")
        url = f"{base}/scenes/{encoded}"
        title = f'<a href="{html.escape(url, quote=True)}">{title}</a>'
        image = (
            f'<a href="{html.escape(url, quote=True)}"><img loading="lazy" '
            f'src="{html.escape(base + "/scene/" + encoded + "/screenshot", quote=True)}"></a>'
        )
    return f"""
    <article>{image}<h3>{title}</h3>
      <p class="meta">{html.escape(metadata["performers"])} · {html.escape(metadata["studio"])}</p>
      <p>Latent {predicted:+.3f} · Curator {current:+.3f} · Cluster {cluster}</p>
      <p><b>Strongest dimensions:</b> {html.escape(", ".join(features) or "none")}</p>
      <p><b>Nearest enjoyed scene:</b> {html.escape(neighbor)} ({similarity:.2f})</p>
    </article>"""


def _render(
    output: Path,
    *,
    model_id: str,
    metrics: dict[str, float | int],
    latent_cards: str,
    current_cards: str,
    explorer_cards: str,
    cluster_rows: str,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    metric_rows = "".join(
        f"<tr><th>{html.escape(key.replace('_', ' ').title())}</th><td>{value}</td></tr>"
        for key, value in metrics.items()
    )
    output.write_text(
        f"""<!doctype html><meta charset="utf-8"><title>Curator latent PoC</title>
<style>
body{{font:15px system-ui;background:#151518;color:#eee;margin:2rem}}a{{color:#9cc8ff}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1rem}}
article{{background:#24242a;border-radius:10px;padding:1rem}}img{{width:100%;aspect-ratio:16/9;
object-fit:cover;border-radius:7px}}.meta,small{{color:#aaa}}table{{border-collapse:collapse}}
td,th{{padding:.35rem .7rem;border-bottom:1px solid #444;text-align:left}}
</style><h1>Latent scene-model PoC</h1><p class="meta">Model {html.escape(model_id)}</p>
<p>This is a relative-enjoyment experiment: the historical labels are predominantly positive,
so the model ranks stronger versus weaker positive outcomes rather than learning dislike.</p>
<table>{metric_rows}</table>
<h2>Latent top picks</h2><div class="grid">{latent_cards}</div>
<h2>Current Curator top picks</h2><div class="grid">{current_cards}</div>
<h2>Best pick from different clusters</h2><div class="grid">{explorer_cards}</div>
<h2>Cluster vocabulary</h2><table>
<tr><th>Cluster</th><th>Scenes</th><th>Features</th></tr>{cluster_rows}</table>
""",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.dimensions < 2 or args.clusters < 2 or args.count < 1 or args.max_scenes < 0:
        raise ValueError(
            "dimensions and clusters must be at least 2; count positive; max-scenes nonnegative"
        )
    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        model = connection.execute(
            "SELECT model_id, feature_version FROM model_version WHERE status='published'"
        ).fetchone()
        if model is None:
            raise RuntimeError("no published model; run build-model first")
        model_id, version = str(model[0]), str(model[1])
        raw_labels = [
            (str(row[0]), float(row[1]), float(row[2]))
            for row in connection.execute(
                """
                SELECT scene_id, direct_appeal, confidence
                FROM direct_scene_state WHERE model_id=?
                """,
                (model_id,),
            )
        ]
        all_scene_ids = [
            str(row[0]) for row in connection.execute("SELECT scene_id FROM source_scene")
        ]
        if args.max_scenes and args.max_scenes < len(raw_labels):
            raise ValueError("--max-scenes must include all labelled scenes")
        if args.max_scenes and len(all_scene_ids) > args.max_scenes:
            labelled_ids = {scene_id for scene_id, _, _ in raw_labels}
            # ponytail: deterministic sample; use --max-scenes 0 for the full library.
            candidates = sorted(
                (scene_id for scene_id in all_scene_ids if scene_id not in labelled_ids),
                key=lambda scene_id: hashlib.sha256(scene_id.encode()).digest(),
            )
            scene_ids = sorted(labelled_ids) + candidates[: args.max_scenes - len(labelled_ids)]
        else:
            scene_ids = all_scene_ids
        scene_ids, feature_names, raw = _matrix(connection, version, scene_ids)
        scaled = MaxAbsScaler().fit_transform(raw)
        matrix = TfidfTransformer().fit_transform(scaled)
        dimensions = min(args.dimensions, matrix.shape[0] - 1, matrix.shape[1] - 1)
        svd = TruncatedSVD(dimensions, random_state=42)
        embedding = normalize(svd.fit_transform(matrix))
        index = {scene_id: position for position, scene_id in enumerate(scene_ids)}
        labels = [
            (index[scene_id], outcome, confidence) for scene_id, outcome, confidence in raw_labels
        ]
        if len(labels) < 20:
            raise RuntimeError("at least 20 labelled scenes are required")
        rng = np.random.default_rng(42)
        order = rng.permutation(len(labels))
        split = max(1, int(len(labels) * 0.8))
        train, test = order[:split], order[split:]
        label_rows = np.array([item[0] for item in labels])
        outcomes = np.array([item[1] for item in labels])
        sample_weights = np.array([item[2] for item in labels])
        validation = Ridge(alpha=args.alpha).fit(
            embedding[label_rows[train]], outcomes[train], sample_weight=sample_weights[train]
        )
        held_out = validation.predict(embedding[label_rows[test]])
        correlation = float(spearmanr(outcomes[test], held_out).statistic)
        taste = Ridge(alpha=args.alpha).fit(
            embedding[label_rows], outcomes, sample_weight=sample_weights
        )
        predicted = taste.predict(embedding)
        kmeans = MiniBatchKMeans(
            n_clusters=min(args.clusters, len(scene_ids)), random_state=42, n_init="auto"
        ).fit(embedding)
        clusters = kmeans.labels_
        current: dict[str, tuple[float, bool]] = {}
        for row in connection.execute(
            """
            SELECT scene_id, general_appeal, eligibility_json
            FROM model_scene_score JOIN poc_scene USING(scene_id) WHERE model_id=?
            """,
            (model_id,),
        ):
            current[str(row[0])] = (float(row[1]), bool(json.loads(row[2]).get("eligible")))
        played = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT source_play.scene_id
                FROM source_play JOIN poc_scene USING(scene_id)
                """
            )
        }
        candidates = [
            position
            for position, scene_id in enumerate(scene_ids)
            if scene_id not in played and current.get(scene_id, (0.0, False))[1]
        ]
        latent_top = sorted(candidates, key=lambda row: (-predicted[row], scene_ids[row]))[
            : args.count
        ]
        current_top = sorted(
            candidates,
            key=lambda row: (-current.get(scene_ids[row], (0.0, False))[0], scene_ids[row]),
        )[: args.count]
        cluster_best: dict[int, int] = {}
        for row in sorted(candidates, key=lambda item: (-predicted[item], scene_ids[item])):
            cluster_best.setdefault(int(clusters[row]), row)
        explorers = sorted(cluster_best.values(), key=lambda row: -predicted[row])[: args.count]
        positive_rows = label_rows[outcomes >= np.quantile(outcomes, 0.75)]
        metadata = _metadata(connection)
        feature_weights = svd.components_.T @ taste.coef_

        def details(row: int) -> tuple[list[str], str, float]:
            item = matrix.getrow(row)
            contributions = item.data * feature_weights[item.indices]
            best = np.argsort(-contributions)[:5]
            features = [
                feature_names[item.indices[position]]
                for position in best
                if contributions[position] > 0
            ]
            similarities = embedding[positive_rows] @ embedding[row]
            nearest = int(positive_rows[int(np.argmax(similarities))])
            return features, metadata[scene_ids[nearest]]["title"], float(np.max(similarities))

        def cards(rows: list[int]) -> str:
            result = []
            for row in rows:
                features, neighbor, similarity = details(row)
                scene_id = scene_ids[row]
                result.append(
                    _card(
                        scene_id,
                        metadata[scene_id],
                        float(predicted[row]),
                        current.get(scene_id, (0.0, False))[0],
                        int(clusters[row]),
                        features,
                        neighbor,
                        similarity,
                        args.stash_url,
                    )
                )
            return "".join(result)

        vocabulary = kmeans.cluster_centers_ @ svd.components_
        cluster_rows = "".join(
            f"<tr><td>{cluster}</td><td>{int(np.sum(clusters == cluster))}</td><td>"
            + html.escape(", ".join(feature_names[index] for index in np.argsort(-row)[:6]))
            + "</td></tr>"
            for cluster, row in enumerate(vocabulary)
        )
        metrics: dict[str, float | int] = {
            "scenes": len(scene_ids),
            "features": len(feature_names),
            "labelled_scenes": len(labels),
            "dimensions": dimensions,
            "clusters": len(kmeans.cluster_centers_),
            "held_out_mae": round(float(np.mean(np.abs(outcomes[test] - held_out))), 4),
            "held_out_spearman": round(correlation, 4),
        }
        _render(
            args.output,
            model_id=model_id,
            metrics=metrics,
            latent_cards=cards(latent_top),
            current_cards=cards(current_top),
            explorer_cards=cards(explorers),
            cluster_rows=cluster_rows,
        )
        return {"output": str(args.output.resolve()), "model_id": model_id, **metrics}
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/curator.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("reports/latent-poc.html"))
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL"))
    parser.add_argument("--dimensions", type=int, default=48)
    parser.add_argument("--clusters", type=int, default=32)
    parser.add_argument("--alpha", type=float, default=10.0)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--max-scenes", type=int, default=6000)
    print(json.dumps(run(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
