import json

import pytest

from curator.cli import run


def test_doctor_human_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["doctor"]) == 0
    captured = capsys.readouterr()
    assert "foundation runtime is ready" in captured.out


def test_doctor_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["doctor", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "ok", "version": "0.0.0"}


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    captured = capsys.readouterr()
    assert "usage: curator" in captured.out
