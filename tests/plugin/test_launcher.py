import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LAUNCHER = Path(__file__).parents[2] / "plugin" / "launcher.py"


@pytest.mark.parametrize(
    ("platform", "machine", "environ", "expected"),
    [
        ("linux", "x86_64", {}, "curator-core-linux-amd64"),
        ("linux", "aarch64", {}, "curator-core-linux-arm64"),
        ("darwin", "arm64", {}, "curator-core-darwin-arm64"),
        ("darwin", "x86_64", {}, "curator-core-darwin-amd64"),
        ("win32", None, {"PROCESSOR_ARCHITECTURE": "AMD64"}, "curator-core-windows-amd64.exe"),
        (
            "win32",
            None,
            {"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"},
            "curator-core-windows-amd64.exe",
        ),
    ],
)
def test_launcher_names_every_shipped_binary(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    machine: str | None,
    environ: dict[str, str],
    expected: str,
) -> None:
    # The launcher avoids the platform module to keep Python startup cheap,
    # so its os/sys detection must still match build_plugin.py's names.
    spec = importlib.util.spec_from_file_location("curator_launcher", LAUNCHER)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(sys, "platform", platform)
    for name in ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    if machine is not None:
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine))
    assert launcher._binary_name() == expected
