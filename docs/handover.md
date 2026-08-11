# Stash Curator handover

Updated: 2026-08-11. Slices 0–4 of the Go backend are merged: the
`curator-core` binary serves the raw-plugin interface natively — trivial
ops, the read-path interactive ops (slate, similar, explanation, shortlist,
histories, taste profile, diagnostics), the network-layer ops
(get_expand, get_performer_hunt, get_external_similar, send_whisparr), the
write-path ops and task modes (backup/compact/vacuum/prepare, sync-build,
model build), the StashDB + Stash sync client surfaces, the last
frontend-parity ops (get_external_tag_choices, get_inspector_entity,
get_tag_sentiment_follow_up, reset), and the entity-sync hook mode. The
differential gates compare structure exactly (ids, counts, orderings,
strings, integers) and floats within a relative tolerance (rel 1e-9); the
bit-exact CPython math ports that previously anchored byte-identity were
removed (see `docs/decisions/002-runtime-swap-planning.md` §4 and issue
#113). The installed plugin's exec line runs through a launcher that
resolves the per-arch binary; the in-binary Python fallback is retired
(unknown ops and task modes error with Python's exact messages), and the
packaged Python backend is removed from the zip — the launcher fails with a
clear reinstall message when no binary exists for the platform (see
`handover-go-backend-slice1.md` through `handover-go-backend-slice4.md`
for the delivered ports). The
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

**Open-issues follow-up (issues #92, #93, #94, #95, #103, #109, #110) —
delivered (2026-08-11) on `fix/slice4-open-issues` (stacked on
`feat/slice4-frontend-parity`).** A single package closing the seven open
issues:

- **#92** — the compact tag-rating rows reserve the Clear slot (`visibility:
  hidden` placeholder) so rated and unrated rows align, and the card action
  row renders above the expanded list.
- **#93** — `get_scene_tag_choices` op (scene's classified tags, alphabetical,
  with direct preferences) plus the "Rate tags & terms" panel on
  recommendation lanes and library Similar cards (outside `card-section`, so
  the SFW Switch contract holds).
- **#94** — migration 0028 (`direct_term_preference` + history, mirroring
  0016/0026), `get_scene_description_tokens` + `submit_term_preferences` ops
  (Go + Python oracle), the direct-term affinity blend in the model build,
  blocked-term enforcement (lanes via `entity_feature` mapping, Similar,
  remote Expand via description tokenization; the slate eligibility
  fingerprint gained a `blocked_terms` digest), and the merged
  tags-and-terms expander on external, recommendation, and Similar cards.
  Terms are truthful to the built model (never re-tokenized for display).
- **#95** — remote scenes are ranked by description term affinity: a new
  `0.10 * term_value` component (weights renormalized to
  `0.40/0.10/0.25/0.10/0.15`), blocked terms exclude remote candidates whose
  description tokens carry them, and `_why`/`expandWhy` name positive term
  contributions. Local Similar's content dot-product is intentionally
  unchanged (affinities are not blended into vectors).
- **#109** — root-caused: concurrent first opens of a WAL sidecar race on the
  `-shm` recovery lock and fail *instantly* with `database is locked (5)`
  (the busy handler does not cover it; reproduced by a new contention test).
  The whole `openSidecar` phase plus `withTxn`/`execImmediate` now retry busy
  failures (bounded, 150/300 ms backoff; COMMIT failures are never retried),
  and the frontend maps surviving lock errors to an actionable
  `databasePath`-on-local-storage message. `busy_timeout` itself is honored
  for ordinary contention (verified 30 s waits).
- **#110** — the expand-refresh marker stream gained dense ticks for the
  previously markerless pre-work (external-links walk 0.05→0.08, taxonomy
  and seed phases bracketed at 50/150 ticks inside 0.08→0.98), matched
  Go/Python, and the task indicator shows a completed job at 100% ("Done")
  for 15 s instead of reverting to idle at the last sub-100% value.
- **#103** — the two-path layout is documented in `getting-started.md` and
  `privacy.md`: the working sidecar on local storage, backups (SQLite backup
  API, WAL-consistent) on the network share via `backupPath`. No sync task
  (deferred); #109's retry + message is the mitigation until the layout is
  applied.

Delivery details: migration 0028 is byte-identical in
`core/migrations/` and `curator/storage/sql/` (checksum-guarded); all new
ops have Go/Python byte-identical differential tests
(`tests/core/test_backend_slice4.py`, `test_backend_slice3_modelbuild.py`,
`test_backend_slice3_writes.py`); blocked-term and ranking behavior has
synthetic tests (`tests/ranking/test_slate.py`,
`tests/model/test_multi_hop.py`, `tests/test_expand.py`,
`tests/test_interactions.py`); `scripts/verify full` passes (490 tests).

**Full Go backend (Phase 4), Slice 4 — frontend parity + cleanup — delivered
(2026-08-11).** Slices 0–4 are complete: the binary serves every operation,
task mode, and the `entity-sync` hook mode the frontend or Stash can invoke
natively — the read-path interactive ops, the network-layer ops (`get_expand`,
`get_performer_hunt`, `get_external_similar`, `send_whisparr`), the write-path
ops and task modes, the model build, and the last frontend-parity ops
(`get_external_tag_choices`, `get_inspector_entity`,
`get_tag_sentiment_follow_up`, `reset`) plus the entity hook. The differential
gates compare structure exactly and floats within rel 1e-9 tolerance; the
glibc-math ports (`pyExp`/`pyLog`/`pyTanh`, correctly-rounded square/cube,
Python `round()`, Neumaier sum) and their corpus fixtures were removed (issue
#113) so the core uses plain Go stdlib math and stored floats may differ from
Python by last bits. The in-binary Python fallback is retired: unknown
operations and task modes error with Python's exact messages, and
`core/fallback.go` is deleted. The packaged Python backend is also removed
from the shipped zip (`scripts/build_plugin.py` ships only the binaries plus
the explanation catalog resource; `plugin/launcher.py` fails with a clear
reinstall message when no binary exists for the platform). The installed
plugin's exec line runs through the arch-resolving launcher
(`plugin/launcher.py`). Delivery details and verification:
[`handover-go-backend-slice4.md`](handover-go-backend-slice4.md).

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
