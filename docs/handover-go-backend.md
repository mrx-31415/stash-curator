# Handover: full Go backend (Phase 4, Slice 0)

Self-contained handover + first agent prompt for the next work package: making
`curator-core` the plugin's exec line by porting the backend to Go, slice by
slice, with Python fallback until the binary covers every op.

## Goal

`plugin/stash-curator.yml` exec line becomes `./curator-core` (the raw
interface, unchanged): the binary reads the same stdin JSON payload and writes
the same stdout JSON as `backend.py` today. The measured prize is the
interactive spawn (~300-700ms Python per call → ~5ms binary). The build and
kernels are already accelerated; this package targets the remaining Python
runtime.

## What already shipped (do not redo)

- `core/` Go module: `curator-core` with `version`, `content-neighbors`,
  `performer-similarity`, `multi-hop` stages; NDJSON progress+result protocol;
  profiling spans; per-arch binaries in the zip; differential gate
  (`tests/oracle.py` = numpy oracle) — all green.
- The numpy/networkx venv is removed; the compiled core is the single runtime
  implementation of the kernels; a missing binary fails build stages loudly.
- Installed verification: cold build 23.1s similarity vs 72.9s numpy baseline
  (3.2x) with zero runtime installs.
- `docs/decisions/002-runtime-swap-planning.md` §8 has the full slice plan.

## The slice plan (from the planning doc)

- Slice 0 — transport + skeleton: raw protocol, settings, the ordered
  checksummed migration chain + artifact attach/views (sidecar parity —
  riskiest), trivial ops (round_trip, health, get_config, get_job_status),
  Python fallback dispatch for everything else.
- Slice 1 — read-path interactive ops (slate, similar, explanation,
  shortlist, history, taste profile, diagnostics) — differential JSON
  (structure exact, floats within rel 1e-9 tolerance), pure
  sidecar reads.
- Slice 2 — network layer: GraphQL clients for Stash sync and StashDB
  expand/hunt (errgroup fan-out for the hunt; local Similar is sidecar-only).
- Slice 3 — write-path tasks: backup/compact/vacuum/prepare, then the build's
  remaining Python stages.
- Slice 4 — frontend parity pass + delete Python.

## Slice 0 — this agent's scope

Port the raw protocol transport and the sidecar parity foundation into
`curator-core`, with a Python fallback dispatch for every op the binary does
not yet implement.

Concretely:

1. **Protocol**: read one JSON payload from stdin (the same shape
   `backend.py` receives: `server_connection` + `args`), dispatch on
   `args.operation` / task mode, write the same stdout JSON the Python backend
   writes, and stderr progress markers (`\x01p\x02…`) exactly as
   `plugin/backend.py` emits them. The plugin config (`stash-curator.yml`)
   currently invokes `backend.py` with an optional task mode arg; the binary
   must accept the same argv shapes.
2. **Settings**: the `_apply_plugin_settings` semantics from `backend.py` —
   config merge + `curator_config` row update on open.
3. **Migrations**: port `curator/storage/migrations.py` + the ordered SQL
   chain in `curator/storage/sql/` (0001-0027) to Go with **identical
   checksums and migration-status semantics**, so a sidecar migrated by either
   implementation is accepted by the other. The modernc sqlite driver is
   already a dependency.
4. **Artifact attach/views**: the `attach_active_artifacts` /
   `attach_build_sources` behavior from `curator/storage/artifacts.py`
   (ATTACH the published feature/model generations read-only + temp views
   shadowing the core tables).
5. **Trivial ops first**: `round_trip`, `health`, `get_config`,
   `get_job_status` — differential outputs vs the Python backend on the same
   payloads.
6. **Python fallback dispatch**: any op/task the binary does not implement yet
   is delegated to the bundled `backend.py` (the binary spawns it with the
   same argv/stdin contract it received) — the plugin never breaks during the
   transition.

### Acceptance criteria

- The binary's `round_trip`/`health`/`get_config`/`get_job_status` outputs are
  structurally identical (floats within tolerance) to the Python backend's for the same payloads and sidecar
  state (a differential test compares both on identical copies).
- A sidecar migrated by the Go migration chain has the same
  `schema_migration` rows + checksums as one migrated by Python, and
  `PRAGMA integrity_check` passes; vice versa (Python accepts a Go-migrated
  sidecar and Go accepts a Python-migrated one).
- Attached artifact views resolve the same tables (feature_build /
  model_version registry) as the Python attach path.
- Unported ops still work via the fallback (round-trip through the installed
  zip).
- `scripts/verify core` and `scripts/verify full` pass; the unit suite stays
  green; Go is a build-time dep only.
- No new runtime dependencies; the per-arch binary stays static
  (`CGO_ENABLED=0`, modernc).

### Constraints

- Follow AGENTS.md: read `docs/handover.md` + the planning doc first; use
  `scripts/verify changed <file>` while iterating, `scripts/verify full` near
  completion. Go toolchain is a dev dependency.
- Keep private library data out of tracked files and diffs; test against
  synthetic corpora and copies, never the live sidecar.
- Conventional Commits; push only when asked.

## First agent prompt

> Port the raw transport + sidecar-parity foundation of Stash Curator's
> backend to the existing Go module at `core/` (module
> `github.com/mrx-31415/stash-curator/core`, binary `curator-core`), so the
> plugin can eventually run with `curator-core` as its exec line on the raw
> interface.
>
> READ FIRST: `docs/handover-go-backend.md`, `docs/handover.md`,
> `docs/decisions/002-runtime-swap-planning.md` §8,
> `plugin/backend.py` (the raw protocol + `_apply_plugin_settings`),
> `curator/storage/migrations.py` + `curator/storage/sql/`,
> `curator/storage/artifacts.py` (attach/views), and AGENTS.md.
>
> SCOPE (Slice 0): (1) stdin-JSON → dispatch → stdout-JSON transport matching
> backend.py's contract, including stderr progress markers; (2) settings
> application; (3) the ordered migration chain with identical checksums and a
> differential test proving Python↔Go sidecar interchange; (4) artifact
> attach/views; (5) differential `round_trip`, `health`, `get_config`,
> `get_job_status`; (6) a Python fallback dispatch (binary spawns backend.py
> for unported ops). Non-goals: the read-path ops, the network layer, write
> tasks, the exec-line switch in stash-curator.yml.
>
> ACCEPTANCE: differential trivial-op outputs vs the Python backend on the
> same payloads; sidecar migration parity both directions (same checksums,
> integrity_check ok); attached artifact views resolve identically; unported
> ops work via fallback through the installed zip; `scripts/verify core` +
> `scripts/verify full` green; static binary, no new runtime deps.
>
> Do not push; commit with Conventional Commits when the slice is green and
> report exactly what was verified.
