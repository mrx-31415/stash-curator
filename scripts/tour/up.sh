#!/usr/bin/env bash
# Start a throwaway Stash with the current plugin build and the seeded tour library.
# Leaves it running on $TOUR_PORT so record.py can capture it; `down` removes it.
set -euo pipefail
cd "$(dirname "$0")/../.."

work="${TOUR_WORK:-$(pwd)/.tmp/tour}"
port="${TOUR_PORT:-9998}"
compose=(docker compose -p curator-tour -f tests/integration/docker-compose.yml)
export STASH_CONFIG="$work/stash" STASH_PORT="$port"

if [[ "${1:-}" == down ]]; then
  "${compose[@]}" down --volumes
  exit
fi

case "$(uname -m)" in
  aarch64 | arm64) platform=linux/arm64 ;;
  *) platform=linux/amd64 ;;
esac
uv run --frozen python scripts/tour/media.py --work "$work"
uv run --frozen python scripts/build_plugin.py --platform "$platform"

# A fresh Stash and Curator sidecar every run, so the tour never shows leftovers.
"${compose[@]}" down --volumes 2>/dev/null || true
if [[ -d "$STASH_CONFIG" ]]; then
  docker run --rm -v "$work":/work stashapp/stash:latest rm -rf /work/stash
fi
# Stash only warns when these are missing, then fails every cover and preview.
mkdir -p "$STASH_CONFIG"/{generated,cache,blobs} "$STASH_CONFIG/plugins/stash-curator"
unzip -oq dist/stash-curator.zip -d "$STASH_CONFIG/plugins/stash-curator"
cp tests/integration/stash-config.yml "$STASH_CONFIG/config.yml"

"${compose[@]}" up -d --wait
container="$("${compose[@]}" ps -q stash)"
docker exec "$container" mkdir -p /media
for clip in "$work"/media/*.mp4; do
  docker cp -q "$clip" "$container:/media/"
done
uv run --frozen python scripts/tour/seed.py --stash-url "http://localhost:$port" --media "$work/media"
echo "Tour Stash ready at http://localhost:$port"
