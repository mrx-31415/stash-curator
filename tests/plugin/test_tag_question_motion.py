import subprocess
from pathlib import Path


def test_tag_question_motion():
    subprocess.run(
        ["node", str(Path(__file__).with_suffix(".cjs"))],
        check=True,
        capture_output=True,
        text=True,
    )
