# Handover: full Go backend (Phase 4, Slice 2)

Updated: 2026-08-10. Slices 0 and 1 are merged to main (rebase-merge, `0ff1e04`
is the tip). The plugin's exec line already runs the arch-resolving launcher
(`plugin/launcher.py` → per-arch `curator-core`), so ops ported in this slice
become native with **no packaging change** — the Python fallback covers
everything not yet ported.

## Goal

Port the network-layer interactive ops into `core/` (module
`github.com/mrx-31415/stash-curator/core`, binary `curator-core`) so that the
StashDB/Whisparr-facing operations run natively with byte-identical JSON to
`plugin/backend.py`, same payloads + same sidecar state + same network
responses. This is the "goroutine slice" from the planning doc: the fetch-bound
StashDB ops are where Go's concurrency actually pays off.

## What already shipped (do not redo)

- **Slice 0** (transport + sidecar parity): `health`, `round_trip`,
  `get_config`, `get_job_status` native; `core/jsonv.go` (Python-compatible
  JSON writer — do not re-touch), `core/tracing.go` (trace plumbing +
  `saveTrace`), `core/settings.go` (sidecarConfig, defaultPluginConfig,
  `_apply_plugin_settings`), `core/artifacts.go` (attachActiveArtifacts —
  **the attach fallback chain immutable→ro→plain-path is the current shipped
  behavior; keep it**), `core/graphql.go` (minimal Stash client — settings
  fetch only), `core/migrations.go`, `core/db.go` (openDatabase with
  **`SetMaxOpenConns(1)`** — Python-parity single-connection semantics; keep).
- **Slice 1** (read-path ops, merged): `get_slate`/`replace_item`,
  `get_similar` (local scene + performer, in-process multi-hop pagerank),
  `get_explanation` (runtime reason derivation + microplanner + catalog),
  `get_recommendation_history`, `get_shortlist`, `get_feedback_history`,
  `get_taste_profile`, `get_diagnostics` — all under `_profiled`.
  Infrastructure to reuse as-is:
  - `core/profiled.go` — `profiledOperation` (the `_profiled` lifecycle: begin
    trace → settings → body → saveTrace when profilingEnabled). Wire the new
    ops through it.
  - `core/apiargs.go` — `_string_list`, page/count bounds, error-message
    mirroring (Python's exact strings).
  - Byte-exact helpers (`core/floatround.go`, `core/neumaier.go`,
    `core/pyexp.go`, `core/pycube.go`) — determinism anchors with corpus
    tests; **do not remove or swap for naive math** (see Constraints).
  - `tests/core/test_backend_slice1.py` — the differential harness pattern
    (builder-seeded sidecar, fresh copies per run, byte-compare with timing
    fields stripped, recursive `_strip_key` for uuid fields).
  - `tests/integration/test_backend_swap.py` — through-the-installed-zip
    parity in docker Stash (oracle = direct backend.py run inside the
    container against the same sidecar).
- **Exec launcher** (merged): `plugin/launcher.py` + yml exec line. Ops
  ported here automatically serve native through the launcher.

## The slice plan (from the planning doc §8)

> **Slice 2 — network layer (the goroutine slice).** Two GraphQL clients with
> one pattern: Stash sync (incremental reconciliation) and StashDB expand/hunt
> (performer hunt measured ~47s wall — the most fetch-bound interactive op;
> errgroup fan-out over performers is the real concurrency win). Local Similar
> is sidecar-only; the sync side is mostly write-bound (51s measured, most of
> it reconciliation + DB), so the expand/hunt side benefits most.

## Slice 2 — this agent's scope

### Ops to port (all dispatched through `_api` + `_profiled` in backend.py)

- `get_expand` — `api.expand(...)` → `ExpandService.results` (the largest:
  scene anchors, performer/studio queries, phash matching, scoring, pagination
  `sort=match`). Args: entity_type, page, sort, performer_id, favorite_only,
  gender (default `config["expand_gender"]`), include_tags/exclude_tags
  (`_string_list`), performer_query/studio_query, performer_names/studio_names,
  hide_phash_matches (default True), minimum_score (default -1), count
  (default `config["page_size"]`).
- `get_performer_hunt` — `ExpandService.performer_hunt(stashdb,
  external_links, performer_id, limit=PERFORMER_HUNT_LIMIT, include_tags,
  exclude_tags)` — **the ~47s wall op: the concurrency win lives here**.
- `get_external_similar` — `ExpandService.targeted_similar(stashdb,
  external_links, entity_type, entity_id, count=100, gender, include_tags,
  exclude_tags, performer_names, studio_names, favorite_only, include_owned,
  hide_phash_matches, minimum_similarity=0.15)`.
- `send_whisparr` — `WhisparrClient` POST (payload + API-key header) —
  replicate the exact request body/headers from `curator/whisparr.py`.

Non-goals (stay on the Python fallback): `update_shortlist` and all write-path
ops (Slice 3), tasks and entity-sync, the sync-build task itself.

### The two GraphQL-client patterns (port once each)

1. **StashDB client** — `_stashdb(payload)` from the plugin settings (stashbox
   endpoints + API key from the plugin config), including the auth token
   refresh flow. The expand/hunt/external-similar ops query StashDB for
   performer fuzzy/exact search, scene-by-phash, and scene/studio metadata.
   See `curator/graphql/client.py` + `curator/graphql/adapters.py`,
   `curator/expand.py`.
2. **Stash incremental sync client** — the paginated
   tags/studios/performers/scenes/plays reconciliation used by the sync side
   (it feeds Slice 3's task modes). Port the client surface now; the task
   wiring is Slice 3. This one is write-bound; do not over-optimize.

### Read-path plumbing to port exactly

- **External links cache** — `plugin/backend.py` `_external_links(payload,
  connection)`: state-hashed cache under `application_meta`
  (`EXTERNAL_LINKS_CACHE_KEY = "external_links"`); fetch on cache miss, upsert
  the row. The write and the state hash must match Python byte-for-byte.
- **Expand scene cache** — `ExpandService` maintains scene-cache rows in the
  sidecar during refresh; replicate whatever writes `expand.py` makes (verify
  against backend.py behaviorally; the differential state-parity test pins
  them).
- **phash normalization** — replicate the exact bit/rounding operations in
  `curator/expand.py` (`hide_phash_matches` uses them).
- **Taxonomy** — StashDB alias handling for include/exclude tags
  (`curator/taxonomy/`); the local `equivalent_tag_names` port
  (`core/taxonomy.go`) exists — extend with the StashDB-alias variant.

### Byte-exactness contract (network ops)

The JSON contract is the same as Slice 1: byte-identical vs backend.py for the
same payloads + same sidecar copies + **same stubbed network responses**.
Run-varying fields (compare structurally: key set + non-negative ints):
`timings_ms` on all four ops. Everything else must be byte-identical — which
means the differential harness must pin every StashDB response.

## Differential harness plan

Extend the Slice-1 pattern (`tests/core/test_backend_slice1.py`) with a
**StashDB stub**: the existing `_StubStash` HTTP server in
`tests/core/test_backend.py` answers settings/runtime on the Stash port; add a
second handler on the configured StashDB endpoint serving fixed fixtures for
the queries the ops issue (performer search, scene phash, aliases). The stub
must return deterministic responses (no timestamps inside the payloads the ops
echo back). Byte-compare each op vs the direct backend.py run on fresh sidecar
copies, strip `timings_ms`, and add a state-parity test for the
external-links cache + scene-cache writes. Profile-trace parity extends to the
new ops (all run under `_profiled`).

## Concurrency

The performer hunt fans out over performers. Port with a bounded worker pool
(stdlib `sync.WaitGroup` + channel; see Constraints — no new deps). The
fan-out must not change the output: results are merged deterministically
(sort keys, tie-breaks) exactly as `ExpandService` does in Python.

## Acceptance criteria

- Differential tests in `tests/core/` prove byte-identical outputs vs the
  Python backend (same sidecar copies, stubbed StashDB) for every ported op,
  timings structural, cache-write state parity asserted.
- Profile-trace parity for the new ops; unported write-path ops still work via
  the fallback through the installed zip.
- `scripts/verify core` + `scripts/verify full` green; `scripts/verify
  integration` green (extend `test_backend_swap.py` with one network op
  through the installed zip against the stub, if feasible — the docker env has
  no real StashDB).
- Static binary, no new runtime dependencies, `core/go.mod` unchanged.

## Constraints

- **No new runtime dependencies; `core/go.mod` unchanged.** The planning doc's
  "errgroup" is guidance for the fan-out shape — stdlib `sync.WaitGroup` +
  channel suffices. If you believe `golang.org/x/sync/errgroup` is justified,
  follow AGENTS.md: "do not introduce a dependency without a measured need".
- Byte-exact helpers stay; never replace `pyRoundTo`/`neumaierSum`/`pyExp`/
  `pyCube` with naive math — they are the differential corpus-tested anchors
  (documented glibc-deviation edges live in their corpus tests).
- Do not touch `core/jsonv.go`. Do not "fix" the masked-NaN performer kernel
  divergence (reviewed product decision).
- Keep `SetMaxOpenConns(1)` and the attach fallback chain as shipped.
- SQLite schema changes need a new ordered migration; never edit applied
  migrations.
- Live Stash and StashDB access is read-only. `send_whisparr` writes to a
  separate Whisparr app — only exercised via the user's UI.
- Keep private Stash URLs, entity IDs, reports, and credentials out of tracked
  files and command output. The harness uses synthetic corpora and stubs.
- Sidecar-on-NFS caveat (observed `SQLITE_BUSY_RECOVERY`): the durable fix is
  the `databasePath` setting pointing at local storage; tracked as
  `docs/../github issue #103` — do not attempt a storage redesign here.
- Do not push. Commit with Conventional Commits when the slice is green and
  report exactly what was verified.

## First agent prompt

> Port the network-layer interactive operations of Stash Curator's backend
> into the Go module at `core/` (module
> `github.com/mrx-31415/stash-curator/core`, binary `curator-core`), so the
> plugin's launcher serves them natively with Python fallback for everything
> not yet ported.
>
> READ FIRST: `docs/handover-go-backend-slice2.md`, `docs/handover.md`,
> `docs/decisions/002-runtime-swap-planning.md` §8 (Slice 2),
> `docs/handover-go-backend-slice1.md` (the delivered Slice-1 port — reuse its
> plumbing: `core/profiled.go`, `core/apiargs.go`, the byte-exact helpers,
> the differential and integration harness patterns),
> `plugin/backend.py` (dispatch + `_api` + `_profiled` + `_stashdb` +
> `_external_links`), `curator/expand.py` (`ExpandService`: results,
> performer_hunt, targeted_similar, phash normalization, scene cache),
> `curator/graphql/` (client + adapters), `curator/whisparr.py`,
> `curator/taxonomy/` (StashDB aliases), `core/graphql.go` + `core/ops.go` +
> `core/db.go` (existing client/connection surface), and AGENTS.md.
>
> SCOPE (Slice 2): port `get_expand`, `get_performer_hunt`,
> `get_external_similar`, `send_whisparr` — byte-identical JSON vs backend.py
> for the same payloads, sidecar copies, and stubbed StashDB responses, per
> the run-varying-fields contract in the handover (`timings_ms` structural;
> everything else exact). Port the two GraphQL-client patterns (StashDB
> expand/hunt + the Stash incremental-sync client surface) and the read-path
> writes exactly: the external-links cache (state-hashed upsert) and the
> expand scene-cache writes. Performer hunt must fan out over performers with
> a bounded stdlib worker pool without changing the deterministic output.
> Non-goals: `update_shortlist` and all write-path ops (Slice 3), task modes,
> entity-sync.
>
> ACCEPTANCE: differential tests in `tests/core/` prove byte-identical
> outputs vs the Python backend on stubbed network fixtures for every ported
> op; state parity for the cache writes; profile-trace parity; unported ops
> still work via the fallback through the installed zip; `scripts/verify
> core` + `scripts/verify full` + `scripts/verify integration` green; static
> binary, no new runtime deps (`core/go.mod` unchanged).
>
> Do not push; commit with Conventional Commits when the slice is green and
> report exactly what was verified.

## Delivery (2026-08-10)

Slice 2 is delivered on `feat/read-path-backend-port`:

- `e859cb9` feat: port network-layer interactive ops to the Go core
- `cf11cdf` perf: make the network ops interactive on large libraries
- `924a9fc` perf: parallelize the expand probe page fetches

All four ops (`get_expand`, `get_performer_hunt`, `get_external_similar`,
`send_whisparr`) run natively, byte-identical to `backend.py` on the stubbed
differential harness (21 slice-2 tests + the slice-1 suite). `scripts/verify
core` / `full` / `integration` green. The Stash sync client surface
(`core/syncclient.go`) compiles but is exercised only by Slice 3's task
wiring.

### Performance findings (matter for Slice 3)

- `pyExp` was a correctly-rounded `math/big` exp (~19 µs per unique input);
  the anchor matcher hit ~860 K unique age-diffs per hunt (~26 s of
  scoring). It is now a table-based port of glibc's dbl-64 exp
  (`core/pyexp.go` + `core/exp_data.go`), bit-exact vs CPython everywhere
  (validated on 50 K samples), memoized. The glibc-deviation points are
  pinned in the corpus test against Python values, not Go's `math.Exp`.
- The anchor matcher precomputes terms in a bounded worker pool and scores
  scenes in parallel with deterministic ordered merging; terms are compact
  (the chosen anchor's block maps are re-derived on demand, age appended
  last so the why-block tie order matches Python).
- `pyLog`/`pyTanh` are glibc-faithful ports (needed: Go's `math.Log`/`Tanh`
  differ from glibc by 1 ulp on 7–16% of inputs).
- The multi-hop walk depends only on the seed: compute once per op, reuse
  per scene.
- Taxonomy `resolve` must build its index once per call (a per-tag
  re-scan is O(N²) over ~23 K tags).
- Nested DB queries while a rowset holds the single pooled connection
  deadlock (`SetMaxOpenConns(1)`); collect-then-query where Python nests
  cursors on one connection.
- Live (23.9 K-scene library): hunt 43.8 s → 11.7 s; external similar
  timed out → 40.2 s, of which **28 s is StashDB server latency** on one
  probe (the tight-tags INCLUDES_ALL query) — external, identical for
  Python; 8 s scoring, 4 s ranking remain. Per-page fetch concurrency is in.

### Test seam

`CURATOR_STASHDB_ENDPOINT` (backend.py `_stashdb` + the Go client, mirroring
the `CURATOR_CORE` resolver pattern) redirects the hardcoded stashdb.org
endpoint to a local stub for the differential harness.

### Slice 3 (next phase)

Write-path ops (backup/compact/vacuum/prepare/refresh/update_shortlist) +
task modes + the sync task wiring (consumes `core/syncclient.go`). See
`docs/handover-go-backend.md` and `docs/decisions/002-runtime-swap-planning.md`
§8. The write-path ops are mostly mechanical SQLite; `refresh` is the
largest port. Entity-sync needs the `source_hash` parity already in
`core/syncclient.go`. Profile-trace parity extends to task modes.
