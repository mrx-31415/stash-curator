# Compiled core (curator-core)

Optional acceleration for Stash Curator's model build. The binary replaces
numpy's role in the similarity stage: the content-neighbor and
performer-similarity kernels are implemented with identical semantics to the
production Python paths in `curator/model/builder.py`, reading feature rows
directly from the SQLite feature artifact. The plugin never depends on it — the
pure-Python fallback (and numpy, when installed) stays fully intact.

Go is a **dev/build dependency only**; the shipped plugin runs the binary as a
subprocess when present (see `docs/decisions/002-runtime-swap-planning.md`,
Phase 2, and `curator/core.py` for resolution and fallback).

## Build

```bash
scripts/build_core.sh          # -> core/bin/curator-core (version from pyproject.toml)
go test ./...                  # kernel self-tests (module lives in core/)
go vet ./...
```

The binary is built with `CGO_ENABLED=0`; SQLite reads use the pure-Go
`modernc.org/sqlite` driver. `scripts/build_plugin.py` cross-compiles the
shipped per-arch binaries (linux amd64/arm64, windows amd64, darwin
amd64/arm64) into the plugin zip; the runtime selects the matching
`curator-core-<goos>-<goarch>` and falls back to numpy / pure Python when none
exists.

## Protocol

Each stage reads one JSON payload from stdin and writes newline-delimited JSON
to stdout: optional `{"progress": fraction}` lines followed by a final
`{"result": ...}` line. Errors go to stderr with a non-zero exit status.

When the payload requests `"profile": true` (the Python side sets it when the
plugin's profiling is active), the binary additionally emits
`{"span": {"name", "cat": "core", "offset_us", "dur_us"}}` lines before the
result — offsets relative to the binary's process start. `curator/core.py`
folds them into the plugin's profile_trace with category `core`, so builds
show an inside-the-binary breakdown (read_features, preference_vectors,
build_columns, kernel, encode_result).

```
curator-core version
curator-core content-neighbors
curator-core performer-similarity
```

`version` prints `{"protocol": 1, "version": "<pyproject version>"}`. The Python
side (`curator/core.py`, `CORE_PROTOCOL`) probes this before enabling the
compiled path.

### content-neighbors

Input: `db` (feature artifact path), `feature_version`, `labels`
(`{scene_id: [outcome, confidence]}`), `label_mean`, `affinities`
(`{feature_id: {affinity, confidence, learned_affinity?, learned_confidence?}}`),
`config` (`min_similarity`, `neighbor_count`, `confidence_scale`,
`generic_weight`), `progress_total`, optional `threads`.

Semantics mirror `_content_neighbors_numpy` exactly: preference vectors are
derived like `_preference_content_vectors`, then per row
`sim = dot(A_i, B_j)`, `shared = count of co-occurring non-zero features`,
`s = sim * (1 - exp(-shared/4))`, `w = s^3 * labeled_conf[j]`, keeping the top
`neighbor_count` by `(-w, scene_id)` among `s >= min_similarity`, excluding
self. numpy's 4096-row blocking is a memory/vectorization chunk and never
changes the math, so this kernel processes rows directly. Output:
`{"result": {scene_id: {"neighbors": [[id, similarity, weight, outcome], ...]}}}`.

### performer-similarity

Input: `db`, `feature_version`, `identity_affinity`
(`{performer_id: [affinity*confidence, confidence]}`), `block_weights`, `cutoff`
(`PERFORMER_SIMILARITY_AFFINITY_CUTOFF`), `numeric_blocks`, `numeric_scales`,
optional `threads`.

Semantics mirror `_performer_similarity_scores_numpy`: profiles are compared
against the known-affinity set (|affinity| >= cutoff) with weighted block
similarities (cosine for shared-key blocks, exp-closeness means for numeric
blocks), a cup-index penalty, and an augmentation penalty. Output is the
production result dict:
`{"result": {performer_id: {value, confidence, matches: [{performer_id,
similarity, affinity, confidence, blocks: {block: value}}]}}}`.

## Determinism

Both kernels are deterministic: fixed chunking across goroutines, no
map-iteration-order dependence in any output, and the selection sort keys match
production (`(-weight, id)` / `(-similarity, performer_id)`). `threads` is a
testing knob; the POC verified 1t vs 4t produce identical output and
`tests/core/` re-verifies it here.

## Differential harness

The pytest files `tests/core/test_core.py` and `tests/model/test_core.py` are
the oracle: Python owns the data (seeded synthetic corpora — never a real
sidecar), the binary must reproduce the numpy outputs within tolerance (exact
ids/counts, 1e-9 floats). The CI core job builds the binary and runs the gate
with `CURATOR_CORE` set; the pure-Python fallback is exercised by the main
suite without a binary.
