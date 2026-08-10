# Handover: full Go backend (Phase 4, Slice 2)

Self-contained handover + first agent prompt for the next work package:
porting the network-layer interactive operations into `curator-core` with
byte-exact JSON, so every interactive frontend op runs natively in the binary
and only write-path ops and tasks stay on the Python fallback.

## Goal

The four fetch-bound interactive ops — `get_expand`, `get_performer_hunt`,
`get_external_similar`, `send_whisparr` — run natively in `curator-core`,
producing byte-identical JSON to `backend.py` for the same payloads, sidecar
state, and stub Stash/StashDB/Whisparr responses. Performer hunt is the
single most fetch-bound interactive op (~47 s wall measured; errgroup
fan-out over performers is the real concurrency win), so this slice is also
where the Go side first exercises real concurrency against live services.
The Stash sync client (incremental reconciliation) is the second GraphQL
client pattern in this slice; its task wiring lands in Slice 3.

With Slice 0 + 1 + 2 covered, every interactive page op the frontend calls
runs natively through the installed zip (the exec swap is already live);
unported write-path ops, tasks, and entity-sync keep the Python fallback
until Slices 3-4.

## What already shipped (do not redo)

Slices 0-1 plus the launcher and follow-up fixes are merged on `main`
(origin/main `0ff1e04`; local `feat/read-path-backend-port` is stale and can
be deleted):

- **Transport** (`core/backend.go`): stdin JSON → dispatch → stdout JSON,
  `{"output":…}`/`{"error":…}` + exit 1, argv `[pluginDir]` / `[pluginDir, mode]`,
  stderr progress markers. Dispatch is now native for: `health`, `round_trip`,
  `get_config`, `get_job_status`, `get_slate`, `replace_item`, `get_similar`,
  `get_explanation`, `get_recommendation_history`, `get_shortlist`,
  `get_feedback_history`, `get_taste_profile`, `get_diagnostics`. Everything
  else (the four network ops, write-path ops, tasks, `entity-sync`) falls back
  to `pluginDir/backend.py` (`core/fallback.go`).
- **Python-compatible JSON writer** (`core/jsonv.go`): byte-identity solved;
  do not re-touch. Float helpers for CPython parity live in
  `core/floatround.go` (`round(x, n)` exact-decimal), `core/neumaier.go`
  (Python 3.12+ `sum()`), `core/pyexp.go` and `core/pycube.go`
  (glibc-compatible `exp`/cube) — each pinned by generated corpus tests.
- **Settings/migrations/artifacts/profiling**: `core/settings.go`,
  `core/migrations.go` (+ `core/migrations/`, checksummed, parity-proven),
  `core/artifacts.go` (ATTACH + shadowing TEMP VIEWs; `attachBuildSources`
  collects table names before creating views), `core/tracing.go`
  (`_profiled` lifecycle via `profiledOperation` in `core/profiled.go`).
- **Sidecar plumbing**: `core/db.go` (openSidecar, one sqlite connection per
  op — Python parity), `core/apiargs.go` (`_string_list`, exclude sets,
  page/count bounds with Python's exact messages), `core/eligibility.go`
  (scene_eligibility, scene_recovery), `core/taxonomy.go`
  (`equivalent_tag_names` — already ported; expand/similar filters reuse it),
  `core/graphql.go` (minimal Stash client — settings/runtime queries only;
  this is the file to grow for Slice 2).
- **Ops**: `core/slate.go` + `core/slate_greedy.go`, `core/similar.go` +
  `core/profiles.go` + `core/multihop.go` (multi-hop pagerank in-process),
  `core/explanations.go` + `core/explanations_render.go`,
  `core/history.go`, `core/diagnostics.go`.
- **Exec swap**: `plugin/launcher.py` resolves `curator-core-<goos>-<goarch>`
  and execs it (Stash has no per-platform manifests); `backend.py` stays in
  the zip as the fallback.
- **Harness**: `tests/core/test_backend.py` (Slice-0) +
  `tests/core/test_backend_slice1.py` (builder-seeded model sidecars,
  byte-parity/state/trace parity), `tests/integration/test_backend_swap.py`
  (ops through the installed zip in docker Stash), `tests/plugin/test_runtime.py`
  (archive + launcher).

## Slice 2 — this agent's scope

### Ops to port (all dispatched through `_api` + `_profiled` in backend.py)

| op | Python reference | notes |
| --- | --- | --- |
| `get_expand` | `CuratorAPI.expand` → `ExpandService.results` (`curator/expand.py`) | StashDB scene queries + local scoring + shortlist merge; `_string_list` filters already ported |
| `get_performer_hunt` | `ExpandService.performer_hunt` | the ~47 s fetch-bound op — the errgroup fan-out target |
| `get_external_similar` | `ExpandService.targeted_similar` | StashDB similar with the local preference blend (reads feature content + affinities) |
| `send_whisparr` | `backend.py` dispatch → `WhisparrClient.send_scene` (`curator/whisparr.py`) | needs a Whisparr stub for the harness |

The four ops share plumbing that must be ported once:

- **The Stash GraphQL client grows to the full query surface**: the
  external-links scan (`EXTERNAL_LINKS_QUERY` in `backend.py`, paginated 500,
  walking scenes/performers/studios + fingerprints), the StashDB queries in
  `curator/expand.py`, and the sync query surface in `curator/sync/` +
  `curator/graphql/operations.py`. `core/graphql.go` already POSTs
  `{"query", "variables"}` with trace spans — extend it, don't fork it.
- **The external-links cache**: `_external_links` scans Stash and caches
  `{"state", "links"}` into `application_meta` under
  `EXTERNAL_LINKS_CACHE_KEY`, reused while Stash's library fingerprint is
  unchanged. That cache write is part of the read path (like the
  eligibility-count cache) and must be replicated exactly.
- **`normalize_phash`** (`curator/expand.py`), the StashDB endpoint constant,
  `PERFORMER_HUNT_LIMIT = 1_000`, and the taxonomy StashDB client
  (`curator/taxonomy/stashdb.py`) for tag resolution.
- **Concurrency**: `get_performer_hunt` fans out over performers. Decide
  stdlib `sync.WaitGroup` + error channel vs adding `golang.org/x/sync` to
  `core/go.mod` (a build-time-only dependency; Slice 1's "go.mod unchanged"
  constraint was slice-scoped — justify any addition). Results must stay
  deterministic regardless of goroutine completion order (sort before
  emitting, like the kernel stages).
- **The Stash sync client pattern** (`SyncService`/`SyncRepository`,
  `curator/sync/`): port the incremental-reconciliation client and the
  source-table read/write surface (source_scene, source_performer,
  source_studio, source_tag, scene_tag, scene_performer, source_play, …).
  The `sync-build`/`update-model` task wiring that consumes it is Slice 3 —
  this slice delivers the client + repository so Slice 3 only wires modes.
  If the repository port feels too large for one slice, land the four ops
  first (they are the acceptance) and deliver the sync client as the second
  pattern after.

Non-goals (stay on the fallback): write-path ops (`update_shortlist`,
`submit_feedback`, `correct_feedback`, `submit_tag_preferences`,
`submit_events`, `set_prune_tag`, `update_pruning`, `get_pruning_queue`,
`get_prune_candidates`, `dismiss_prune_candidate`, `reverse_exclusion`,
`update_config`, backups, `reset`), all task modes, and `entity-sync`.

## The byte-exactness contract

Outputs are deterministic given (payload, sidecar state, stub Stash, stub
StashDB, stub Whisparr). Run-varying fields are only wall-clock timings:

| op | run-varying fields |
| --- | --- |
| `get_expand` | `timings_ms` if present in the shape |
| `get_performer_hunt` | `timings_ms` if present |
| `get_external_similar` | `timings_ms` if present |
| `send_whisparr` | anything the Whisparr API returns that a stub cannot pin (stub it; assert the request the Go client sends, and compare the response fields Python would emit) |

Harness rule: stub StashDB and Whisparr with canned, deterministic responses;
compare every other byte exactly; compare timing fields structurally (key
sets + non-negative ints). Check the Python shapes first — some of these ops
carry `timings_ms`, some do not — the structural comparison only applies
where the shape has them.

## Differential harness plan

Extend `tests/core/test_backend.py`'s stub pattern (do not fork it):

- Add a StashDB endpoint stub (the existing `_StubStash` answers
  `CuratorPluginRuntime`/`CuratorPluginSettings` by operation name; add a
  second server or route for `https://stashdb.org/graphql` — note the real
  client hardcodes the StashDB URL, so the stub must be injectable the same
  way the Stash URL is: via the payload's server_connection, or a
  test-only override) and a Whisparr stub.
- Seed the sidecar with the builder-seeded model pattern from
  `tests/model/test_builder.py` (targeted_similar reads content features +
  affinities + the local preference blend) plus deterministic
  `external_shortlist` / `external_entity` rows.
- Per-op differential tests assert byte-identical stdout vs
  `plugin/backend.py` on identical sidecar copies, per the contract above;
  the external-links cache write and any read-path writes must leave
  identical sidecar state (extend the state-parity pattern).
- Profile-trace parity extends to the new ops (extend the Slice-1 trace
  test's parametrization).

## Acceptance criteria

- Every Slice-2 op's JSON is byte-identical to the Python backend's on
  identical (payload, sidecar copy, stub Stash, stub StashDB, stub Whisparr),
  per the run-varying-fields contract; a differential test covers each op.
- The external-links cache write and any other read-path writes leave
  identical sidecar state to Python's.
- Profile traces are recorded for every Slice-2 op when `profilingEnabled`.
- Unported ops still work via the fallback; `scripts/verify core` and
  `scripts/verify full` green; static binary; no new runtime dependencies
  (a build-time-only `golang.org/x/sync` addition must be justified in the
  PR description).
- With the already-live launcher swap: the four ops run natively through the
  installed zip; unported ops via fallback through the same zip.

## Constraints

- Follow AGENTS.md: read `docs/handover.md`, this doc, and
  `docs/decisions/002-runtime-swap-planning.md` §8 first; `scripts/verify
  changed <file>` while iterating, `scripts/verify full` near completion. Go
  toolchain: `/home/johan/go-toolchain/go/bin` on this host, or `go` in PATH
  (the pre-push hook needs Go on PATH).
- Keep private library data out of tracked files and diffs; synthetic
  corpora and copies only, never the live sidecar. The live Stash runs on
  `192.168.1.100` (see the global agent file); it is reachable for read-only
  probes but never a test oracle.
- Known edges to carry forward: the NFS-backed sidecar/WAL hazard (issue
  #103 — storage layout workaround: `databasePath` local + `backupPath` on
  NFS), `get_slate` exploration != 0 parity limitation on artifact sidecars,
  and the documented glibc-deviation cases in the float corpus tests.
- Conventional Commits; push only when asked. The `ci/slice0-baseline`
  diagnostic branch is closed and can be deleted.

## First agent prompt

> Port the network-layer interactive operations of Stash Curator's backend
> into the Go module at `core/` (module
> `github.com/mrx-31415/stash-curator/core`, binary `curator-core`), so all
> interactive frontend ops run natively with Python fallback for everything
> else.
>
> READ FIRST: `docs/handover-go-backend-slice2.md`, `docs/handover.md`,
> `docs/decisions/002-runtime-swap-planning.md` §8, `plugin/backend.py`
> (dispatch + `_api` + `_profiled` + `_external_links`), `curator/expand.py`
> (results, performer_hunt, targeted_similar, normalize_phash),
> `curator/whisparr.py`, `curator/graphql/` (client + operations),
> `curator/sync/` (SyncService/SyncRepository), `core/graphql.go` (extend,
> don't fork), `core/ops.go` + `core/tracing.go` + `core/profiled.go` (the
> `_profiled` lifecycle), and AGENTS.md.
>
> SCOPE (Slice 2): port `get_expand`, `get_performer_hunt`,
> `get_external_similar`, `send_whisparr` — byte-identical JSON vs
> backend.py for the same payloads, sidecar state, and stub
> Stash/StashDB/Whisparr responses, per the run-varying-fields contract in
> the handover (stub the network endpoints; timing fields compared
> structurally). The external-links cache write is part of the read path and
> must be replicated exactly. `get_performer_hunt` is the errgroup fan-out
> target (stdlib `sync.WaitGroup` or a justified `golang.org/x/sync`
> addition); results must be deterministic regardless of goroutine order.
> Port the Stash sync client pattern (`SyncService`/`SyncRepository`) as the
> second GraphQL client — the task wiring that consumes it is Slice 3.
> Non-goals: the write-path ops, tasks, and entity-sync stay on the Python
> fallback.
>
> ACCEPTANCE: differential tests in `tests/core/` prove byte-identical
> outputs vs the Python backend on builder-seeded synthetic sidecars with
> stub Stash/StashDB/Whisparr for every ported op; profile-trace parity
> extends to the new ops; unported ops still work via the fallback through
> the installed zip; `scripts/verify core` + `scripts/verify full` green;
> static binary, no new runtime deps.
>
> Do not push; commit with Conventional Commits when the slice is green and
> report exactly what was verified.
