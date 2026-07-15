import json
from pathlib import Path

import pytest

from curator.cli import run


def test_database_cli_migrate_status_and_backup(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "curator.sqlite3"
    backup = tmp_path / "backup.sqlite3"

    assert run(["--db", str(database), "db", "migrate", "--json"]) == 0
    migrated = json.loads(capsys.readouterr().out)
    assert migrated["current_version"] == migrated["latest_version"] == 1

    assert run(["--db", str(database), "db", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["pending_versions"] == []

    assert run(["--db", str(database), "db", "backup", str(backup), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"backup": str(backup.resolve())}
    assert backup.is_file()
