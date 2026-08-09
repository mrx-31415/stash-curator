# Stash Curator handover

Updated: 2026-08-09. Next work package is the resident RPC plugin conversion
(see below); Phase 0 planning and measurements are banked in
`docs/decisions/002-runtime-swap-planning.md` and the RPC design in
`docs/handover-rpc-plugin.md`.

## Current state

Curator is a working preview for Stash v0.31 with Python 3.12+. Public product,
architecture, privacy, and contributor guidance now lives in the main `docs/` pages.
Historical design and research records are retained in `docs/archive/` but are not
current guidance or part of the published site.

Stage 4 is complete. A native backup validated, restartable legacy compaction removed
1,189,457 rebuildable rows, explicit vacuum reduced the core from 775,700,480 to
95,678,464 bytes, and post-restart installed verification passes. Schema-1 artifacts,
durable state, all pre-existing backups, and the protected pre-repair copy remain.

## Open acceptance work

- Complete installed desktop/mobile keyboard, playback, Prune, StashDB failure, and
  restart checks before calling the project 1.0-ready.
- After publishing, smoke-test every route and fetch the public `index.yml` source.

## Next work package

**Convert the plugin to Stash's resident RPC interface** (decision from the Phase 0
planning round). The design, measured baseline, implementation steps, risks, and
acceptance criteria live in [`handover-rpc-plugin.md`](handover-rpc-plugin.md); the
full planning record and Phase 0 measurements are in
`docs/decisions/002-runtime-swap-planning.md`. Validation tooling:
`scripts/benchmark.py` (automated ops/task battery + trace pull; run before and
after the conversion). Uncommitted at handoff: `scripts/benchmark.py`, `poc/`,
`docs/decisions/002-runtime-swap-planning.md`, `.gitignore`.

Deferred UI follow-ups (retain as a separate coherent package):

- Rename the feedback-facing history label to clearer product language, likely
  **Feedback history** or **Review feedback**.
- Fix black option text in the **Recommendation history** dropdown under the dark
  theme.

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

## Guardrails

Never delete or reset a sidecar to solve migration trouble. Never commit private
library data, IDs, credentials, reports, or evaluation notes. Curator's only Stash
mutation is explicit, reversible Prune tagging; StashDB access stays read-only.
