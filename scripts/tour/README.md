# Docs tour recording

Rebuilds the tour video, GIF, and posters in `docs/assets/` from the current plugin,
using a throwaway Stash with fictional metadata and Blender Foundation film excerpts.
Nothing touches a real library.

Requirements: Docker, ffmpeg, Go (for the plugin build), and the integration
dependency group (`uv sync --locked --group integration`).

```bash
scripts/tour/up.sh          # download and cut clips, build, start Stash on :9998, seed, build the model
uv run --group integration --frozen python scripts/tour/record.py
scripts/tour/up.sh down     # remove the container and its volume
```

Record once per `up.sh`. The tour itself opens **Why this?** and plays a Roulette
pick, and Curator learns from both, so a second recording on the same stack shows
different recommendations.

- `media.py` downloads the films into `.tmp/tour/` and cuts 12-second scenes,
  skipping black frames, titles, and credits.
- `seed.py` gives the scenes fictional studios, performers, and tags, and writes a
  viewing history: an old favourite studio (Dormant, Revisit), a current one
  (For You), one tried and abandoned, and one never watched.
- `record.py` drives the storyboard in headless Chromium and records CDP screencast
  frames. Page loads happen off camera, and a drawn cursor shows each click.

The film credits on the docs homepage (`docs/index.md`, `#tour`) must list every
film `media.py` uses.
