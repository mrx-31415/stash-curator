"""The model digest must identify the code that produced the artifact.

`model_digest` hashes source data and config but never code, so before the
scoring fingerprint an algorithm change with unchanged inputs produced an
identical `model_id`: the build found the published row, incremented
`reuse_count`, and served the previous algorithm's artifact.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from curator.model.fingerprint import SCORING_FINGERPRINT
from scripts import scoring_fingerprint


def test_generated_constants_match_the_manifest() -> None:
    """The tripwire: any manifest edit is stale until --write regenerates."""
    expected = scoring_fingerprint.compute()
    for relative, content in scoring_fingerprint.render(expected).items():
        actual = (scoring_fingerprint.REPO_ROOT / relative).read_text()
        assert actual == content, (
            f"{relative} is stale; run `python scripts/scoring_fingerprint.py --write`"
        )


def test_python_and_go_constants_agree() -> None:
    """The digest is a mirrored pair, so both sides must hash the same value."""
    go_source = (scoring_fingerprint.REPO_ROOT / scoring_fingerprint.GO_TARGET).read_text()
    assert f'const scoringFingerprint = "{SCORING_FINGERPRINT}"' in go_source


def test_generated_targets_are_not_in_the_manifest() -> None:
    """Hashing the files that carry the hash would make it self-referential."""
    assert scoring_fingerprint.PYTHON_TARGET not in scoring_fingerprint.MANIFEST
    assert scoring_fingerprint.GO_TARGET not in scoring_fingerprint.MANIFEST


def test_manifest_is_sorted_and_present() -> None:
    assert list(scoring_fingerprint.MANIFEST) == sorted(scoring_fingerprint.MANIFEST)
    for relative in scoring_fingerprint.MANIFEST:
        assert (scoring_fingerprint.REPO_ROOT / relative).is_file(), relative


def test_missing_manifest_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="manifest file is missing"):
        scoring_fingerprint.compute(tmp_path)


@pytest.mark.parametrize("relative", scoring_fingerprint.MANIFEST)
def test_changing_any_manifest_file_changes_the_fingerprint(tmp_path: Path, relative: str) -> None:
    """The acceptance criterion, one file at a time.

    Runs against a copy so a real scoring source is never touched.
    """
    for entry in scoring_fingerprint.MANIFEST:
        target = tmp_path / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(scoring_fingerprint.REPO_ROOT / entry, target)

    before = scoring_fingerprint.compute(tmp_path)
    assert before == SCORING_FINGERPRINT

    changed = tmp_path / relative
    changed.write_bytes(changed.read_bytes() + b"\n// scoring behaviour changed\n")

    assert scoring_fingerprint.compute(tmp_path) != before


def test_line_ending_normalization_keeps_the_fingerprint_stable(tmp_path: Path) -> None:
    """A CRLF checkout must not invalidate every cached model."""
    for entry in scoring_fingerprint.MANIFEST:
        target = tmp_path / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (scoring_fingerprint.REPO_ROOT / entry).read_bytes()
        target.write_bytes(source.replace(b"\n", b"\r\n"))

    assert scoring_fingerprint.compute(tmp_path) == SCORING_FINGERPRINT
