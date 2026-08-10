# Stash Curator handover

Updated: 2026-08-10. Slices 0 and 1 of the full Go backend are delivered:
the `curator-core` binary now serves the raw-plugin interface for the trivial
ops *and* the read-path interactive ops (slate, similar, explanation,
shortlist, histories, taste profile, diagnostics) with byte-identical outputs,
and the installed plugin's exec line runs through a launcher that resolves the
per-arch binary — the Python backend stays as the fallback for everything not
yet ported (see `handover-go-backend-slice1.md` for the port state). The
resident RPC conversion is off the table (disproven — no residency in Stash's
`rpc` interface; see the correction banner in the planning doc);
`docs/handover-rpc-plugin.md` is retained as blocked/superseded reference.

## Current state

Curator is a working preview for Stash v0.31 with Python 3.12+. Public product,
architecture, privacy, and contributor guidance now lives in the main `docs/` pages.
Historical design and research records are retained in `docs/archive/` but are not
current guidance or part of the published site.

Stage 4 is complete. A native backup validated, restartable legacy compaction removed
1,189,457 rebuildable rows, explicit vacuum reduced the core from 775,700,480 to
95,678,464 bytes, and post-restart installed verification passes. Schema-1 artifacts,
durable state, all pre-existing backups, and the protected pre-repair copy remain.

The compiled core (Phase 2) is delivered: the content-neighbor and
performer-similarity kernels are ported to Go with identical semantics, wired
into the model build as a subprocess (compiled core > numpy > pure Python),
with a pytest differential gate against numpy (seeded synthetic corpora, 1e-9
floats, exact ids), cross-thread determinism, and the full unit suite green
with the binary active. Distribution (Phase 3) ships per-arch binaries in the
plugin zip with runtime select and a pure-Python fallback.

## Open acceptance work

- Complete installed desktop/mobile keyboard, playback, Prune, StashDB failure, and
  restart checks before calling the project 1.0-ready.
- After publishing, smoke-test every route and fetch the public `index.yml` source.

## Next work package

**Full Go backend (Phase 4), Slice 1 — read-path interactive ops.** The
kernel port (similarity + pagerank), per-arch distribution, and the
optional-deps venv removal were delivered earlier; Slice 0 of the backend
port (transport, settings, the checksummed migration chain, artifact
attach/views, trivial ops, profiling parity, Python fallback dispatch) is
delivered and verified (2026-08-10): byte-identical `round_trip`, `health`,
`get_config`, `get_job_status` vs the Python backend, sidecar migration
parity both directions, `profile_trace` parity for `get_config`, and the
fallback round-tripping unported ops through the installed zip. The next
slice ports the read-path interactive ops (`get_slate`, `get_similar`,
`get_explanation`, `get_shortlist`, histories, taste profile, diagnostics)
to byte-exact JSON, then the exec line can switch to the binary with the
fallback covering the rest. Full handover + first agent prompt:
[`handover-go-backend-slice1.md`](handover-go-backend-slice1.md).

Deferred UI follow-ups (retain as a separate coherent package):

- Rename the feedback-facing history label to clearer product language, likely
  **Feedback history** or **Review feedback**.
- Fix black option text in the **Recommendation history** dropdown under the
  dark theme.

## Model-build performance follow-ups

Installed profiling on a 23,891-scene library measured a 409-second model build.
Similarity took 132 seconds: 76 seconds for content neighbors and 56 seconds for
performer similarity. Publication took 243 seconds, including a broad 144-second
classification/order/reason/index stage and 88 seconds validating the generated
540 MiB artifact. The model-integrity scan is removed in the current work package;
schema, cardinality, and lane-state validation remain.

The two independent follow-ups now have self-contained handovers:

1. [Bound performer-similarity propagation](handover-performer-similarity.md).
2. [Derive requested explanations and query exact score-first ordering](handover-runtime-model-data.md).

Measured 2026-08-09 on this dev host: production-shape synthetic (N=24 000,
d=10 245, nnz=33, ~55% labeled — the Phase 0 feature shape) content neighbors
126.4s numpy -> 8.1s core (**15.6x**); performer 10.8s -> 9.1s (1.2x at 10k
profiles/200 known); binary spawn ~7x faster than the Python import. A Docker
cold build on a copy of the live sidecar (23 860 scenes, 895 labeled) with the
core in the plugin zip showed the similarity stage at 119.3s vs the 132s numpy
baseline (~10%) — the real library's low label count makes the content kernel's
O(N²) selection scan the shared floor; the 15.6x holds where L·d is large. The
container's content-stage span (75.7s) needs a follow-up (the container's
feature-build shape was not captured before teardown; see the planning doc
section 8).

## Compiled core (Phase 2) — what shipped

- `core/` — Go module: `curator-core` CLI with `version`,
  `content-neighbors`, `performer-similarity` stages; reads feature rows from
  the SQLite feature artifact; NDJSON progress + result; deterministic across
  goroutine counts. Build: `scripts/build_core.sh` (version from
  pyproject.toml). Dev dependency only.
- `curator/core.py` — resolver + protocol probe + subprocess runner; the
  builder dispatches compiled core > numpy > pure Python
  (`curator/model/builder.py`).
- Differential gate: `tests/core/test_core.py` + `tests/model/test_core.py`
  (seeded synthetic corpora; skip without a built binary). `scripts/verify`
  gained `core` mode and gates `full`; CI has a `core` job and setup-go on the
  quality job.
- One documented exact-mirror decision: the performer stage reproduces numpy's
  masked-NaN behavior (pairs where either profile lacks a global cosine block
  are excluded) — the pure-Python fallback differs; see the planning doc
  section 8.

## Guardrails

Never delete or reset a sidecar to solve migration trouble. Never commit private
library data, IDs, credentials, reports, or evaluation notes. Curator's only Stash
mutation is explicit, reversible Prune tagging; StashDB access stays read-only.
