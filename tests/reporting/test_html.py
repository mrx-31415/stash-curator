import json
from pathlib import Path

import pytest

from curator.cli import run
from curator.reporting import ReportGenerator
from tests.ranking.test_slate import _database


def test_report_is_self_contained_and_renders_every_lane(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        "UPDATE feature_definition SET metadata_json=? WHERE feature_id='feature-x'",
        (json.dumps({"tag_name": "Shared scenario"}),),
    )
    connection.execute(
        "UPDATE model_scene_score SET neighbors_json=? WHERE scene_id='a-best'",
        (
            json.dumps(
                [
                    {
                        "scene_id": "b-best",
                        "similarity": 0.72,
                        "weight": 0.31,
                        "outcome": 0.8,
                    }
                ]
            ),
        ),
    )
    output = tmp_path / "report.html"

    result = ReportGenerator(connection).generate(
        output, count=3, stash_url="http://stash.test:9999/graphql"
    )
    document = output.read_text(encoding="utf-8")

    assert result.output == output.resolve()
    assert result.lane_counts.keys() == {
        "for_you",
        "best_bets",
        "revisit",
        "discover",
        "adventure",
    }
    assert all(f'<section id="{lane}">' in document for lane in result.lane_counts)
    assert "<style>" in document
    assert "<script" not in document
    assert 'href="http://stash.test:9999/scenes/a-best"' in document
    assert 'src="http://stash.test:9999/scene/a-best/screenshot"' in document
    assert 'loading="lazy"' in document
    assert "Reason graph" in document
    assert "Supporting scenes and shared content" in document
    assert 'href="http://stash.test:9999/scenes/b-best"' in document
    assert "Shared scenario" in document
    assert "direct.positive" in document and "private" in document
    assert "Full inspector data" in document
    assert "Appeal" in document and "Current Fit" in document and "Confidence" in document


def test_redacted_report_removes_synthetic_private_identifiers(tmp_path: Path) -> None:
    connection = _database(tmp_path / "curator.sqlite3")
    connection.execute(
        "INSERT INTO source_tag(tag_id, name, source_hash) "
        "VALUES ('tag-private', 'Secret Tag', 'x')"
    )
    row = connection.execute(
        "SELECT components_json FROM model_scene_score WHERE scene_id='a-best'"
    ).fetchone()
    components = json.loads(row[0])
    components["content"]["top"] = [
        {
            "value": 0.2,
            "confidence": 0.8,
            "metadata": {"tag_id": "tag-private", "tag_name": "Secret Tag"},
        }
    ]
    connection.execute(
        "UPDATE model_scene_score SET components_json=? WHERE scene_id='a-best'",
        (json.dumps(components),),
    )
    output = tmp_path / "redacted.html"

    ReportGenerator(connection).generate(
        output,
        count=20,
        redacted=True,
        stash_url="http://private-stash.test:9999/graphql?apikey=secret",
    )
    document = output.read_text(encoding="utf-8")

    private_values = [
        *(str(row[0]) for row in connection.execute("SELECT scene_id FROM source_scene")),
        *(str(row[0]) for row in connection.execute("SELECT title FROM source_scene")),
        *(str(row[0]) for row in connection.execute("SELECT performer_id FROM source_performer")),
        *(str(row[0]) for row in connection.execute("SELECT name FROM source_performer")),
        *(str(row[0]) for row in connection.execute("SELECT studio_id FROM source_studio")),
        *(str(row[0]) for row in connection.execute("SELECT name FROM source_studio")),
        "tag-private",
        "Secret Tag",
    ]
    assert all(value not in document for value in private_values)
    assert "Scene 001" in document
    assert "Performer 001" in document
    assert "Studio 001" in document
    assert "Tag 001" in document
    assert "private-stash" not in document
    assert "apikey" not in document


def test_explain_and_report_cli_emit_machine_readable_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "curator.sqlite3"
    connection = _database(database)
    connection.close()

    assert run(["--db", str(database), "explain", "--scene-id", "d-revisit", "--json"]) == 0
    explanation = json.loads(capsys.readouterr().out)
    assert explanation["scene_id"] == "d-revisit"
    assert any(reason["code"] == "direct.positive" for reason in explanation["reasons"])

    output = tmp_path / "cli-report.html"
    assert (
        run(
            [
                "--db",
                str(database),
                "report",
                "--output",
                str(output),
                "--count",
                "2",
                "--redacted",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["output"] == str(output.resolve())
    assert report["redacted"] is True
    assert output.exists()
