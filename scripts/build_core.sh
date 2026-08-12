#!/usr/bin/env bash
# Build the compiled core (curator-core) for the current GOOS/GOARCH.
#
# The version is read from pyproject.toml (the single version source) and
# injected into the binary at build time. CGO is enabled: SQLite reads use
# the native mattn/go-sqlite3 driver (the amalgamation is compiled in, no
# system SQLite needed), so the build host needs a C compiler for the local
# GOOS/GOARCH. Output:
#   core/bin/curator-core   (curator-core.exe on Windows)
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(uv run --frozen python - <<'PY'
import tomllib
from pathlib import Path
print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])
PY
)"

mkdir -p core/bin
binary="core/bin/curator-core"
if [[ "$(go env GOOS)" == "windows" ]]; then
  binary="core/bin/curator-core.exe"
fi

(
  cd core
  CGO_ENABLED=1 go build \
    -tags sqlite_dbstat \
    -trimpath \
    -ldflags "-s -w -X main.coreVersion=${version}" \
    -o "../${binary}" \
    .
)

echo "built ${binary} (${version})"
