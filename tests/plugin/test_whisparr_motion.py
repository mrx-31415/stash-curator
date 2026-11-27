import subprocess
from pathlib import Path


def test_whisparr_motion():
    subprocess.run(
        ["node", str(Path(__file__).with_suffix(".cjs"))],
        check=True,
        capture_output=True,
        text=True,
    )
