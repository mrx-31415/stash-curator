import subprocess
from pathlib import Path


def test_stashbox_settings() -> None:
    subprocess.run(["node", str(Path(__file__).with_suffix(".cjs"))], check=True)
