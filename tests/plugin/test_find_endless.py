import subprocess
from pathlib import Path


def test_find_endless():
    subprocess.run(
        ["node", str(Path(__file__).with_suffix(".cjs"))],
        check=True,
        capture_output=True,
        text=True,
    )


def test_find_batches_share_grid_rows():
    css = (Path(__file__).parents[2] / "plugin" / "stash-curator.css").read_text()
    batches = css.split(".curator-find-endless > [data-endless-page],", 1)[1].split("}", 1)[0]
    assert "> .curator-grid," in batches
    assert "> .curator-preview-wall" in batches
    assert "display: contents;" in batches
    controls = css.split(".curator-find-endless > :not([data-endless-page]),", 1)[1].split("}", 1)[
        0
    ]
    assert "> .curator-loading," in controls
    assert "> .alert" in controls
    assert "grid-column: 1 / -1;" in controls
