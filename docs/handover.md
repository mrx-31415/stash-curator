# Stash Curator handover

Updated: 2026-07-30 after Stage 4 live storage cutover.

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

Retain these installed UI follow-ups as a separate coherent package:

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
schema, cardinality, reason-coverage, and lane-state validation remain.

Keep these two independent follow-ups for later measurement:

1. Bound performer-similarity propagation to meaningful learned affinities. The live
   model had 334 performer-identity affinities, but only 206 had effective absolute
   affinity of at least 0.005 and 149 reached 0.01. Start with a fixed 0.005 cutoff,
   retain the existing exact identity contribution, and compare recommendation quality
   before changing the threshold. The current profile suggests roughly 20 seconds of
   build-time savings.
2. Generate explanations for requested scenes instead of materializing every reason,
   and serve exact score-first ordering from indexed queries. The current artifact
   stores 218,770 reason rows using 268 MiB and 135,304 order rows using about 39 MiB
   including its unique index. Reuse the existing targeted reason-building flow, keep
   globally varied ordering precomputed for stable pagination, and measure page latency
   before removing persisted rows.

Before either change, split the current broad indexing timer into lane classification,
score-first ordering, varied ordering, reason generation, and SQLite index creation.
Run the installed operation cold and warm; retain ranking, explanation, and stable-page
tests plus a private before/after quality review.

## Guardrails

Never delete or reset a sidecar to solve migration trouble. Never commit private
library data, IDs, credentials, reports, or evaluation notes. Curator's only Stash
mutation is explicit, reversible Prune tagging; StashDB access stays read-only.
