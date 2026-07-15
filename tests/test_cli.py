import json
from pathlib import Path

import pytest

from curator.cli import run


def test_doctor_human_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--db", str(tmp_path / "doctor.sqlite3"), "doctor"]) == 0
    captured = capsys.readouterr()
    assert "runtime is ready" in captured.out


def test_doctor_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "doctor.sqlite3"
    assert run(["--db", str(database), "doctor", "--json"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    assert result["stash"] == "not_configured"
    assert result["schema_current"] == 0
    assert result["schema_latest"] == 3


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    captured = capsys.readouterr()
    assert "usage: curator" in captured.out
