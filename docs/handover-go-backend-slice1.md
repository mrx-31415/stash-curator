# Handover: full Go backend (Phase 4, Slice 1)

Self-contained handover + first agent prompt for the next work package:
porting the read-path interactive operations into `curator-core` with
byte-exact JSON, so the plugin can switch its exec line to the binary with
the Python fallback covering everything not yet ported.

## Goal

Every interactive read op the frontend pages call — slate, similar,
explanation, shortlist, recommendation/feedback history, taste profile,
diagnostics — runs natively in `curator-core` (ms spawn instead of the
~300-700 ms Python spawn), producing byte-identical JSON to `backend.py` for
the same payloads and sidecar state. With Slice 0 + 1 covered, the plugin
switches its exec line to the binary; unported ops keep the Python fallback
until Slice 4 deletes Python.

## What already shipped (do not redo)

Slice 0 + the profiling follow-up are delivered and committed (`4e2bb61`,
`2a02f93`; not pushed):

- **Transport** (`core/backend.go`): stdin JSON → dispatch → stdout JSON,
  `{"output":…}`/`{"error":…}` + exit 1, argv `[pluginDir]` / `[pluginDir, mode]`,
  stderr progress markers.
- **Python-compatible JSON writer** (`core/jsonv.go`): insertion-ordered keys,
  `ensure_ascii` escaping, CPython float repr — verified against `repr()`
  ground truth. Byte-identity of JSON is *solved*; do not re-touch the writer.
- **Settings** (`core/settings.go`): `_settings` (GraphQL, swallows errors),
  `_apply_plugin_settings` merge/validation with Python's exact error
  strings, sorted-key `config_json` writes, `DEFAULT_PLUGIN_CONFIG`.
- **Migrations** (`core/migrations.go` + `core/migrations/`): embedded
  byte-identical copies of `curator/storage/sql/` (0001-0027), sha256
  checksums match by construction, status/migrate semantics parity — proven
  both directions by `tests/core/test_backend.py`.
- **Artifacts** (`core/artifacts.go`): `attach_active_artifacts` /
  `attach_build_sources` — read-only immutable ATTACH + shadowing TEMP VIEWs.
  The Slice-1 ops read the model through these views; they work.
- **Profiling** (`core/tracing.go`): full `_profiled` equivalent — trace
  lifecycle, stash/sqlite span recording through the `dbx` surface
  (`core/db.go`), `saveTrace` with 200-row retention, warn-only save failures.
  `get_config` is wrapped; every Slice-1 op must be wrapped the same way
  (they all run under `_profiled` in Python).
- **Fallback** (`core/fallback.go`): unported ops spawn `pluginDir/backend.py`
  with the same argv/stdin and relay stdout/stderr; exit code mirrored.
- **Differential harness pattern** (`tests/core/test_backend.py`, 18 tests):
  stub GraphQL server (settings + runtime queries by operation name),
  `assert_byte_identical` (fresh sidecar copies at the same database path),
  migration/artifact/settings/fallback/profiling parity. Extend it, don't
  fork it.

The multi-hop PageRank kernel is already ported (`core/multi_hop.go`, stage
protocol `multi-hop`); `get_similar`'s performer-graph blend uses it in
Python (`curator/similarity.py` → `MultiHopAffinity`).

## The slice plan (from the planning doc §8)

> **Slice 1 — read-path interactive ops (highest ROI).** get_slate,
> get_similar (the math is already Go), get_explanation, get_shortlist,
> feedback/recommendation history, taste profile, diagnostics. Pure sidecar
> reads + byte-exact JSON; this is what kills the ~300-700ms per-call
> interactive spawn (5ms binary spawn).

Sequential order: Slice 0 must land first (parity foundation — done);
Slice 1 is the first vertical slice after it. **The exec-line swap happens
when Slice 0 + 1 are covered**; unported ops keep the Python fallback until
then.

## Slice 1 — this agent's scope

### Ops to port (all dispatched through `_api` + `_profiled` in backend.py)

| op | Python reference | output shape notes |
| --- | --- | --- |
| `get_slate`, `replace_item` | `CuratorAPI.get_slate` (`curator/api.py`) + `SlateBuilder.recommend` (`curator/ranking/slate.py`) | `replace_item` is `get_slate(…, context={"replacement": True})`, count 1 |
| `get_similar` | `CuratorAPI.similar` + `SimilarityService` (`curator/similarity.py`) | scene + performer; scene records a ranked impression |
| `get_explanation` | `CuratorAPI.explanation` + `curator/explanations/` (planner) | the largest pure-logic chunk |
| `get_recommendation_history` | `CuratorAPI.recommendation_history` | reads through the attached model views |
| `get_shortlist` | `ExpandService.shortlist_results` (`curator/expand.py`) | local sidecar read |
| `get_feedback_history` | `CuratorAPI.feedback_history` | |
| `get_taste_profile` | `CuratorAPI.taste_profile` | float output — the jsonv repr already handles it |
| `get_diagnostics` | `backend.py _diagnostics` | `MigrationRunner.status` (exists), `generation_diagnostics`, `compaction_status`, job aggregates |

Non-goals (stay on the fallback): network ops (`get_expand`,
`get_performer_hunt`, `get_external_similar`, `send_whisparr` → Slice 2),
write-path ops (`update_shortlist`, `submit_feedback`, `correct_feedback`,
`submit_tag_preferences`, `submit_events`, `set_prune_tag`, `update_pruning`,
`get_pruning_queue`, `get_prune_candidates`, `dismiss_prune_candidate`,
`reverse_exclusion`, `update_config`, backup ops, `reset`), all task modes
and `entity-sync`.

### The differential contract — read this before writing any test

All Slice-1 outputs are deterministic given (payload, sidecar state, stub
Stash) **except** a small set of fields Python itself regenerates per call;
stored floats may also differ by last bits across libm/CPU environments, so
the differential gates compare structure exactly (keys, ids, counts,
orderings, strings, integers) and floats within rel 1e-9 tolerance:

| op | run-varying fields |
| --- | --- |
| `get_slate` | `timings_ms`, `ranking_timings_ms` (wall-clock ints); `impression_id` (uuid4 unless `args.impression_id` is passed); `config_updated_at_ms` (only moves when settings are applied) |
| `get_similar` | `timings_ms`; `impression_id` (scene only, uuid4 unless passed) |
| `get_diagnostics` | `generated_at_ms` |
| others | none |

Harness rule: pass a fixed `impression_id` in `args` where the op accepts it;
compare every other byte exactly; for the timing fields assert key sets and
types (non-negative ints) and allow value differences — two Python runs
differ there too. Do **not** chase byte-equality of `timings_ms`; the
frontend treats them as informational.

### Writes in the "read" path — replicate exactly

- `get_slate` records the impression: `InteractionStore.record_impression`
  (`curator/interactions.py`) — bounded write of `impression` +
  `impression_item` rows with `now_ms`.
- `get_similar` (scene) records a ranked impression with
  `PRAGMA busy_timeout = 100`, and on a lock error whose message contains
  "locked" (casefold) **swallows it and returns `impression_id: None`**,
  restoring `busy_timeout = 30000` afterwards. The Go side must replicate the
  busy-timeout juggling and the swallow (modernc's busy error text must be
  matched the same way).
- Both join the op's connection, not a separate one.

### Shared plumbing to port once (mirror `_api`'s shell)

- `_open(payload, settings)` — exists (`core/db.go openSidecar`).
- Args coercion with Python semantics (`str`/`int`/`float`/`bool` on JSON
  values) and `_string_list` (list of ≤ 50 strings ≤ 100 chars; exact
  `ValueError` messages: "filter values must be a list of at most 50 strings"
  etc.).
- `exclude_scene_ids` set coercion; `page`/`count` bounds with Python's exact
  messages ("invalid recommendation page", "invalid Similar page",
  "minimum_similarity must be between 0 and 1", …).
- `config()` reads (exists), `coordinator.status().pending` (the
  `model_update_state` read exists in `opHealth` — factor it out),
  `RecommendationModelStore.current_model_id` (exists), the
  `"unknown Curator API operation: …"` error.
- `_profiled` wrapping for every op (trace saved when `profilingEnabled`),
  exactly like `opGetConfig` in `core/ops.go`.

### The substantive ports

- `SlateBuilder.recommend` — the slate math: reads `model_scene_lane`,
  `model_lane_order`, `model_lane_candidate_cache`, `model_scene_score`
  through the attached views, applies exclusions (`exclusion` table),
  exploration, and deterministic ordering/tie-breaks. `tests/ranking/`
  (`test_slate.py`, `test_policy.py`) and `tests/test_api.py` are the oracle.
  Lane caches are materialized by the build task (Slice 3) — Slice 1 only
  reads them.
- `SimilarityService.scenes/performers` — `model_scene_neighbor` /
  `model_scene_score` reads plus the multi-hop performer-graph blend:
  decide between calling the pagerank in-process (the Go func in
  `core/multi_hop.go`) or via the stage protocol. `performers()` also reads
  `feature_affinity` and `FeatureStore.similar_performers` (reads
  `entity_feature` through the attached `feature_generation` view).
- `ExplanationService` — reason selection from `model_scene_reason` +
  scores, plus the microplanner (`curator/explanations/planner.py`). Port the
  JSON contract; `tests/explanations/` is the oracle.
- `_diagnostics` — `generation_diagnostics` + `compaction_status`
  (`curator/storage/database.py`) + migration status + the job aggregate.

### Differential harness plan

Seed sidecars by building a **real model with the Python builder on
synthetic corpora** — the pattern already exists in `tests/model/test_core.py`
(synthetic corpus → feature artifact → `PreferenceModelBuilder` → published
model + lane caches), then seed shortlist/feedback/history/impression rows
deterministically. The ops read through the attached model views, so a
plain-schema sidecar is not enough. Never a live sidecar. The stub GraphQL
server already answers the settings query every op's `_profiled` wrapper
needs.

### The exec-line swap (Slice-1 milestone, one open design decision)

The zip ships per-arch binaries (`curator-core-<goos>-<goarch>`,
`scripts/build_plugin.py`), and `stash-curator.yml`'s `exec` list is static —
so the swap needs a tiny launcher in the zip that resolves the arch binary
and execs it with `{pluginDir}` as argv[1] (shell/bat shim, or a Python
shim — the shim's own spawn cost is a few ms, fine). Recommended: shim in
the zip, exec line → shim, `backend.py` stays in the zip until Slice 4 so
the fallback keeps working. If the launcher feels like a separate product
call, the ops can land without the swap — but the planning doc's milestone
is "swap when Slice 0 + 1 are covered".

## Acceptance criteria

- Every Slice-1 op's JSON is byte-identical to the Python backend's on
  identical sidecar copies (synthetic, builder-seeded) + stub Stash, per the
  run-varying-fields contract above; a differential test covers each op.
- The read-path writes (impression rows, incl. the busy_timeout=100 swallow)
  leave identical sidecar state to Python's.
- Profile traces are recorded for every Slice-1 op when `profilingEnabled`
  (extend `test_profiling_trace_parity` to the new ops).
- Unported ops still work via the fallback; `scripts/verify core` and
  `scripts/verify full` green; static binary; no new runtime dependencies;
  `core/go.mod` unchanged.
- With the launcher swap (if taken): ported ops native through the installed
  zip, unported ops via fallback through the same zip.

## Constraints

- Follow AGENTS.md: read `docs/handover.md` + this doc + the planning doc §8
  first; `scripts/verify changed <file>` while iterating, `scripts/verify
  full` near completion. Go toolchain is a dev dependency
  (`/home/johan/go-toolchain/go/bin` on this host, or `go` in PATH).
- Keep private library data out of tracked files and diffs; synthetic
  corpora and copies only, never the live sidecar.
- Conventional Commits; push only when asked.

## First agent prompt

> Port the read-path interactive operations of Stash Curator's backend into
> the Go module at `core/` (module
> `github.com/mrx-31415/stash-curator/core`, binary `curator-core`), so the
> plugin can switch its exec line to the binary with Python fallback for
> everything else.
>
> READ FIRST: `docs/handover-go-backend-slice1.md`, `docs/handover.md`,
> `docs/decisions/002-runtime-swap-planning.md` §8, `plugin/backend.py`
> (dispatch + `_api` + `_profiled`), `curator/api.py` (get_slate, similar,
> explanation, recommendation_history, expand_shortlist, feedback_history,
> taste_profile), `curator/ranking/slate.py`, `curator/similarity.py`,
> `curator/explanations/`, `curator/interactions.py` (impression writes),
> `core/ops.go` + `core/tracing.go` (the existing `_profiled`-equivalent and
> trace plumbing), and AGENTS.md.
>
> SCOPE (Slice 1): port `get_slate`/`replace_item`, `get_similar`,
> `get_explanation`, `get_recommendation_history`, `get_shortlist`,
> `get_feedback_history`, `get_taste_profile`, `get_diagnostics` —
> byte-identical JSON vs backend.py for the same payloads and sidecar state,
> per the run-varying-fields contract in the handover (fixed
> `impression_id` in the harness; timing fields compared structurally). The
> read-path writes (impression recording, incl. get_similar's
> busy_timeout=100 lock swallow) must replicate Python exactly. Every op
> runs under the `_profiled` lifecycle (profile_trace when profilingEnabled).
> Non-goals: the network ops (expand/hunt/external similar/whisparr), the
> write-path ops (feedback/tag/preferences/prune/exclusions/update_config),
> tasks, entity-sync — they stay on the Python fallback.
>
> ACCEPTANCE: differential tests in `tests/core/` prove byte-identical
> outputs vs the Python backend on builder-seeded synthetic sidecars for
> every ported op; profile-trace parity extends to the new ops; unported ops
> still work via the fallback through the installed zip; `scripts/verify
> core` + `scripts/verify full` green; static binary, no new runtime deps.
>
> Do not push; commit with Conventional Commits when the slice is green and
> report exactly what was verified.
