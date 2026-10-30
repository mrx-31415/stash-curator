"""Download the tour's Blender films and cut them into short demo scenes.

Every source is a Blender Foundation film under Creative Commons Attribution; the
credits live in docs/index.md (#tour). Check a new film's license before adding
it. The cut list is fixed so a re-recording shows the same library.

Usage:
  python scripts/tour/media.py --work .tmp/tour
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
import zipfile
from pathlib import Path

PEERTUBE = "https://video.blender.org/download/web-videos/{}-480.mp4"

# (key, url, member inside the zip or None, usable seconds, scenes to cut).
# The usable range leaves out opening titles and end credits.
SOURCES = [
    (
        "bbb",
        "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_640x360.m4v.zip",
        "BigBuckBunny_640x360.m4v",
        (30, 490),
        14,
    ),
    ("llamigos", PEERTUBE.format("23f3ef79-15dc-44c5-aa45-cf92e78a4509"), None, (8, 128), 9),
    ("glasshalf", PEERTUBE.format("64222c8a-c4c7-4b3b-9850-7fb2078edcf6"), None, (8, 170), 9),
    ("dweebs", PEERTUBE.format("7b2eff2a-35f2-4403-9d88-d0dd6e4b5ba1"), None, (2, 52), 3),
]
CLIP_SECONDS = 12


def fetch(work: Path, key: str, url: str, member: str | None) -> Path:
    downloads = work / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / url.rsplit("/", 1)[1]
    if not archive.exists():
        print(f"downloading {url}")
        partial = archive.with_suffix(archive.suffix + ".part")
        urllib.request.urlretrieve(url, partial)
        partial.rename(archive)
    if member is None:
        return archive
    source = work / "src" / member
    if not source.exists():
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(member, work / "src")
    return source


def black_spans(source: Path) -> list[tuple[float, float]]:
    probe = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(source), "-an",
         "-vf", "scale=320:-2,blackdetect=d=0.2:pix_th=0.12", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    found = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", probe.stderr)
    return [(float(a), float(b)) for a, b in found]


def pick_starts(
    usable: tuple[float, float], count: int, black: list[tuple[float, float]]
) -> list[float]:
    """Spread `count` clip starts over the usable range, avoiding black frames."""
    low, high = usable
    candidates = [
        start
        for start in (low + step * 0.5 for step in range(int((high - low - CLIP_SECONDS) * 2) + 1))
        if not any(a < start + CLIP_SECONDS and b > start for a, b in black)
    ]
    if len(candidates) < count:
        raise SystemExit(f"only {len(candidates)} clean starts in {usable}")
    starts: list[float] = []
    for slot in range(count):
        target = low + (high - low - CLIP_SECONDS) * slot / max(count - 1, 1)
        free = [c for c in candidates if all(abs(c - s) >= CLIP_SECONDS for s in starts)]
        if not free:
            break
        starts.append(min(free, key=lambda c: abs(c - target)))
    return sorted(starts)


def cut(source: Path, start: float, target: Path) -> None:
    if target.exists():
        return
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(CLIP_SECONDS),
            "-i", str(source), "-an",
            "-vf", "scale=854:480:force_original_aspect_ratio=increase,crop=854:480,fps=24",
            "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(target),
        ],
        check=True,
    )  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, default=Path(".tmp/tour"))
    args = parser.parse_args()
    media = args.work / "media"
    media.mkdir(parents=True, exist_ok=True)
    clips = []
    for key, url, member, usable, count in SOURCES:
        source = fetch(args.work, key, url, member)
        starts = pick_starts(usable, count, black_spans(source))
        print(f"{key}: {len(starts)} scenes at {starts}")
        for index, start in enumerate(starts, 1):
            name = f"{key}-{index:02d}.mp4"
            cut(source, start, media / name)
            clips.append({"file": name, "film": key, "index": index, "start": start})
    (media / "clips.json").write_text(json.dumps(clips, indent=2))
    print(f"{len(clips)} clips in {media}")


if __name__ == "__main__":
    main()
