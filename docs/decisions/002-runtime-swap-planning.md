# Planning: compiled runtime swap (Go/Rust core)

Status: **Phase 1 decided (Go); Phase 2 delivered (2026-08-09)**. Record of
evidence, the equality-coverage strategy, the RPC correction, and the
release/dev workflow for the compiled-core direction. Complements ADR 001
(backend runtime, accepted) and `docs/handover-rpc-plugin.md` (resident RPC
conversion, blocked/superseded).

The Phase 2 outcome (compiled core wired into the model build as optional
acceleration, differential harness, dev/CI tooling) is recorded in section 8.

Updated: 2026-08-09.

## 1. Goals restated

- Runtime speed for the expensive stages (model build, per-call latency).
- Dependencies pulled in at **build time**, with no separate install task at
  runtime (the current "Install optional dependencies" numpy/networkx pip task).

## 2. Banked findings (evidence)

### 2.1 Constraints that shape every option

- Stash's plugin index (`index.yml`) has **no platform/architecture field**: one
  zip per plugin id. A compiled-only plugin is one architecture unless the zip
  carries several binaries or the plugin downloads one at first run.
- Stash's official Docker image **does not ship Python**; community issues and
  forum threads document Python plugins as effectively locked out of default
  Docker installs unless users install Python themselves (and reinstall it after
  every Stash update). Curator's docs require Python 3.12+ today.
- Stash supports `raw` (spawn per call — Curator today) and `rpc` (resident
  process, JSON-RPC over stdio; Go reference implementation `pkg/plugin/examples/
  gorpc`, `pkg/plugin/common.ServePlugin`). The Python RPC conversion is already
  designed in `docs/handover-rpc-plugin.md`.
- Current runtime profile (measured, ~24k-scene library, numpy): 409s model build;
  132s similarity (76s content neighbors + 56s performer); 243s publication
  (144s classification/order/reason/index; the 88s validation scan was removed).
- Per-call Python spawn + import measured at ~630-860 ms (with numpy) in the RPC
  handover; ~730 ms for the full import stack on this dev host. Every interactive
  operation, task, and entity hook pays it.
- The pure-Python fallback is ~870x slower per element than numpy BLAS on the
  cosine workload — effectively unusable at production library sizes, which is
  why the numpy acceleration task exists.

### 2.2 Language comparison (Rust vs Go vs Python)

| Axis | Go | Rust | Python (current) |
| --- | --- | --- | --- |
| Deps at build time | stdlib covers http/json/zip/testing; sqlite via module | crates | runtime pip task for numpy/networkx |
| Per-call startup | ~3-8 ms | ~2-5 ms | ~630-860 ms |
| Multi-arch distribution | cheap (`CGO_ENABLED=0`+modernc, or native CI runners per arch) | expensive (musl/OpenSSL/cross-toolchain per target) | n/a (source ships everywhere) |
| Port cost (~31k LOC + 10.5k LOC tests) | lower (simpler language, fast compile loop) | higher (borrow checker) | n/a |
| Hot-loop ceiling | below numpy unless fused/sparse (see 2.3) | ndarray+SIMD closer to numpy | numpy = OpenBLAS |
| SQLite | mattn (CGO, C-speed) or modernc (pure Go, slower) | rusqlite bundled | stdlib sqlite3 |
| Ecosystem fit | Stash is Go; RPC example is Go | n/a | no runtime deps today |

**Lean:** Go over Rust for this project (Stash's own stack, cheap distribution,
faster port). But see the decision framework in 3 — the *size* of the change is
the bigger question than the language.

### 2.3 Benchmark evidence (banked POC)

Location: the banked `poc/golang-similarity-benchmark/` (now removed; its numbers
and how-to lived in the POC README). Kernels mirror production
`_content_neighbors_numpy` exactly and were cross-verified against a Python replica
on shared data: **0 mismatched rows**, max weight error 1.4e-17. The shipped
differential gate (`tests/oracle.py` + `tests/core/` vs the `curator-core` binary)
is the live successor to this banked evidence.

| Scenario | numpy (prod algo) | Go dense 4t | Go sparse fused 4t |
| --- | --- | --- | --- |
| N=6 000, d=120, nnz=12 | 24.3s | 13.8s (1.8x) | 6.3s (3.9x) |
| N=3 000, d=600, nnz=30 | 18.0s | 4.5s (4.0x) | 1.45s (12.4x) |
| N=24 000, d=120 (prod size) | ~400s extrapolated | — | 44.8s |
| N=24 000, d=600 (tag-heavy) | ~19 min extrapolated | — | 51.6s |

Machine context: 4-core x86_64, 7 GB RAM, numpy 2.5.1 + scipy-openblas 0.3.33
(~4-6 GFLOPS raw matmul — a slow BLAS environment), Go 1.26.5.

Key structural results:

- numpy densifies: O(N^2 d) arithmetic, paid twice (float64 dot + float32 binary
  matmul), plus a Python per-row `flatnonzero`/`partition` loop. Go sparse-fused
  is O(N * nnz * col-nnz) and **immune to feature-column count `d`** — and real
  Curator vectors include description-token columns, so production `d` is likely
  in the hundreds-to-thousands.
- numpy allocates ~3 * block * N * 8B per block (sim/weights/shared — >1 GB at
  production block sizes; this box swapped at N=24 000). Go streams per-row
  top-k with O(N + k) scratch — no big matrices.
- Both implementations pay an O(N^2) per-row selection scan; at N=24 000 that is
  the remaining ~20-40s floor for Go and ~24k Python-level numpy calls for numpy.
- Go kernels are deterministic (1t vs 4t identical outputs, verified).
- Caveats: synthetic data only; production feature-column count and sparsity are
  **not yet measured**; numpy ratios will narrow on servers with fast BLAS at
  low `d` (the selection scan becomes the common floor).

## 2.4 Phase 0 benchmark results (measured 2026-08-09, automated harness)

Harness: `scripts/benchmark.py` — drives a Docker Stash (v0.31.1, plugin 0.5.1)
with the plugin installed, runs the operation battery and tasks through
`runPluginOperation`/`runPluginTask`, and pulls profiling traces from a copied
sidecar. Sidecar: copy of the live 23,917-scene sidecar (published model, 200
traces, 73 jobs). Run: `uv run python scripts/benchmark.py --db PATH
[--cold-build]`; report written to `.tmp/benchmark-report/` (gitignored).

Interactive operations (client wall time, 4 reps, numpy installed):

- every operation pays ~1.1 s median spawn+import (numpy import dominates);
  actual work is 55-250 ms median for everything except Similar;
- `get_similar` scene: 2.5 s wall (1.6 s work); performer: 8.3 s wall (7.2 s work);
- without numpy in the container the same ops were ~500-700 ms wall — the
  acceleration task adds ~400-700 ms to every spawn;
- one rep of `get_config` crashed the plugin process (`signal: bus error`)
  after numpy import; the next rep succeeded (self-healing, but a real defect
  candidate to investigate).

Tasks (fresh copies of the sidecar, so warm paths):

- `prepare`: 2.0 s wall, 96 ms trace — caches already materialized (no-op);
- `backup`: 2.0 s wall, 718 ms trace — 105 MB sidecar via the backup API;
- `build` (cold, `--cold-build` invalidates the published model first):
  **278 s wall / 276 s trace** with numpy, stage breakdown: similarity 74.5 s
  (content) + 57.3 s (performer) = 132 s, feature build 54 s, indexing 86 s,
  varied ordering 52 s, score-first ordering 10 s, lane classification 15 s,
  scoring 22 s, affinities 20 s, publication 0.1 s (validation scan already
  removed). `install-deps` (numpy/networkx venv) completes in ~1-2 min
  (needs network).

Real workload shape (from the sidecar's feature artifact, counts only):
**N = 23,917 scenes, d = 10,245 content features, ~33 content features per
scene (0.3% sparsity)**. The POC's d=600 scenario was already ~17x below real
d, so the Go sparse advantage (immune to d; numpy pays O(N^2 d) twice) is
larger in production than the 12.4x measured at d=600: numpy ~11.7T MACs vs
Go ~61M + the O(N^2) selection scan both pay.

### Phase 0 conclusions

- **Interactive latency is spawn-dominated, not work-dominated**: the RPC
  conversion (per-call spawn -> resident process) is the fix for interactive
  ops, and it also removes the numpy-import tax the acceleration task adds to
  every call.
- **Build time breaks down as similarity (132 s) + indexing (86 s) + varied
  ordering (52 s)**: the compiled-core hybrid's ceiling on this workload is
  similarity + the Python-loop stages; indexing/varied-ordering are SQLite
  write-bound and would move less.
- **The real d ~ 10k validates the d-immunity argument** for the compiled
  core; numpy's dense work scales with d, Go's sparse work does not.
- **One observed crash** (bus error on numpy import) is worth a defect ticket
  regardless of the language decision.

## 3. Decision framework

The fix depends on which pain dominates; the options are nearly disjoint:

| Observed pain | Cheapest fix | Notes |
| --- | --- | --- |
| Interactive latency (pages/hooks feel slow) | ~~RPC conversion~~ **disproven**: the `rpc` interface spawns per call, same as `raw` (verified v0.31.1 + develop). Real options: compiled core (ms spawn), lazy-import slimming (~0.3-0.4s spawn), or a self-managed resident daemon. See 6. |
| Optional-deps install task friction | Vendor wheels into the zip | Offline, pinned, deterministic; still a task, no network. ~0.5 day. |
| Build wall-time / scaling | Compiled core (Go) in numpy's role | Validated 4-12x on the similarity stage on this box; ~2-3x on the whole build. ~2-4 days for a sidecar-wired slice. |
| Full rewrite of everything | Not justified | 31k LOC + 10.5k LOC tests for a ~2-3x win on a background task with progress bars. |

**Recommended shape if the compiled direction is chosen:** the binary replaces
numpy's *role* — optional acceleration with the pure-Python fallback retained, so
the plugin never depends on it and equality guarantees are the same as today's
"deterministic and correct in either mode" promise. This sidesteps the
single-zip/arch constraint (see 5) and gives a clean rollback path.

## 4. Equality-coverage plan

Goal: any compiled implementation must produce outputs the existing Python
implementation accepts, under a defined tolerance policy, with the 10.5k LOC test
corpus as the oracle (not ported — *driven*).

### 4.1 What "equal" means, by artifact

- **SQLite sidecar**: identical schema; the ordered, checksummed migration chain
  (`curator/storage/sql/`) must be implemented with the same checksums so a
  sidecar built by either implementation is accepted by the other. Migration
  status and `PRAGMA integrity_check` must match.
- **Published artifacts**: same rows, structure, and schema for the same input
  corpus — floats within 1e-9 relative tolerance (revised from hash-equal in
  issue #113: glibc patch levels and FMA-capable CPUs shift last bits of
  stored floats, and the bit-exact math ports that pinned them were removed).
- **JSON API responses**: same structure and non-float values; floats within
  1e-9 relative tolerance (the frontend contract is the JSON payloads; the JS
  does not change).
- **Floats**: exact for integer/hash/count domains (ids, shared counts, checksums,
  hashes); 1e-9 relative tolerance for similarity/weight/affinity floats and all
  other stored floats; selection
  and ordering tie-breaking **identical by construction** — sort keys must match
  production exactly (e.g. `(-weight, id)`).
- The float32 shared-count exactness trick (counts <= feature count, exact in
  float32; BLAS matmul path) must be replicated or proven equivalent; Go uses
  integer counts, which are exact.

### 4.2 Layers of coverage

1. **Kernel differential tests** (already proven in the POC): Python owns the
   data, the binary reads it and must reproduce outputs within tolerance. Promote
   the POC's verify mode into a fixture-based permanent test.
2. **Corpus differential tests**: seeded synthetic corpora varying N, d, nnz, and
   sparsity; run the full pipeline (not just the kernel) through both
   implementations and diff every output artifact (neighbor selections, weights,
   classifications, lane orders, reasons, published artifacts). Synthetic corpora
   only in-repo — never a sidecar snapshot (private data). A local, uncommitted
   sidecar may be used for manual runs.
3. **Schema/migration parity**: build a sidecar with Python migrations, run the
   compiled implementation against it and vice versa; assert status + checksums
   match. This is the integration-surprise surface the POC cannot probe.
4. **Existing tests as acceptance**: the current 39 test files (e.g.
   `tests/model/test_builder.py` reference values) define the behavioral oracle;
   the compiled implementation must pass them via its process boundary.
5. **CI differential gate**: a job that builds both implementations, runs the
   corpus differential tests, and fails on any mismatch beyond tolerance; runs on
   every PR touching the core. Determinism is enforced by the corpus test (both
   implementations must be deterministic; Go: no map-iteration-order dependence,
   fixed chunking — verified in the POC).

### 4.3 Harness shape

Keep pytest as the single harness. The compiled core is exercised through its
process boundary (argv/stdin + JSON), exactly like the POC's `verify` mode, so the
10.5k LOC suite stays the oracle without porting. Integration tests (Playwright +
real Stash) remain for end-to-end behavior; profiling (`curator/profiling.py`)
remains the timing oracle.

## 5. Release and dev workflow (compiled direction)

> **Implemented (2026-08-09, Phase 3):** the binary now ships inside the
> plugin zip as per-arch binaries (linux amd64/arm64, windows amd64, darwin
> amd64/arm64 — mirroring Stash's own release matrix). `scripts/build_plugin.py`
> cross-compiles them with `CGO_ENABLED=0` + modernc (one machine, no native
> runners needed) into `core/bin/`, caches by freshness, and adds them to the
> zip; the runtime selects the matching `curator-core-<goos>-<goarch>` via the
> `curator/core.py` resolver (env pin > shipped binary > plain name > repo dev
> build), with the pure-Python fallback unchanged. The archive test asserts
> binary presence per shipped platform. Go is now required at plugin-build
> time (pages/release/integration workflows install it); it stays a
> build-time-only dependency.

### 5.1 Dev loop

- Python harness + pytest unchanged; the core is built and driven via IPC.
- `scripts/verify` gains: build the core (if changed), run the differential gate.
- Go toolchain is a dev/build dependency only — never a runtime one.

### 5.2 Build and CI

- Per-arch binaries on native GitHub runners (linux amd64/arm64, darwin,
  windows). CGO decision for SQLite: `mattn/go-sqlite3` (C-speed, per-arch builds)
  vs `modernc.org/sqlite` (pure Go, one-machine cross-compile, slower on the
  540 MiB artifact stage — lean mattn + native runners).
- The archive test (`tests/plugin/test_runtime.py`) extends to assert the binary
  is present in the zip for each shipped platform.

### 5.3 Distribution (the single-zip constraint)

Three options, with the recommended one first:

1. **One zip, all supported-arch binaries; runtime selects.** Plugin probes
   `runtime.GOOS/GOARCH`-style detection and runs the matching binary; pure-Python
   fallback if none. Zip grows by ~15 MB per arch. Simple, offline, no download —
   at the cost of zip size. Mirrors the optional-acceleration role (3).
2. **Universal launcher downloads the binary at first run.** Smallest zip, but
   reintroduces a runtime download (more robust than pip, still a network step).
3. **Per-arch plugin ids in the index.** Cleanest per-arch UX in Stash, but three
   release lines and confusing updates.

### 5.4 Versioning and release

- Keep release-please; the version source stays `pyproject.toml` (release-type
  python), injected into the binary at build time (same pattern as
  `curator/__init__.py` today). The pages workflow rebuilds the zip and index
  from main.
- Rollout: the binary ships as optional acceleration; rollback = remove it
  (fallback active). Measure on the installed sidecar with the existing profiling
  page and stage timings before/after.

## 6. RPC plan

> **Corrected (2026-08-09):** the premise is disproven, and RPC is now **off the
> table entirely**. Verified against Stash `v0.31.1` and `develop` source
> (`pkg/plugin/rpc.go`): the `rpc` interface spawns the plugin executable **per
> call** (`pie.StartProviderCodec` in each `rpcPluginTask.Start()`; the client —
> and child process — is closed when the single `Run` completes). There is no
> resident process and no crash-restart. Converting `interface: raw -> rpc`
> therefore cannot remove the ~1.1 s spawn.

**Conclusion:** with residency absent, RPC offers no benefit over `raw` for this
plugin — same lifecycle, more wire machinery (jsonrpc `RPCRunner` framing). The
chosen compiled-core direction (Go) keeps the **`raw` interface**: the exec line
becomes the binary (`exec: [./curator-core, "{pluginDir}"]`) with the same
stdin/stdout JSON contract, and the ~3-8 ms binary spawn makes residency
irrelevant. `docs/handover-rpc-plugin.md` is retained as blocked/superseded
reference (wire-format details only).

The spawn tax is removed by the compiled core; if pure Python were ever
required again, the fallback options are:

1. **Self-managed resident daemon** (Python stays) — the plugin starts a detached
   daemon on first call (sidecar + socket); later calls connect in ~20-50 ms.
   Costs: lifecycle management (daemon lifetime, plugin updates, stale sockets),
   concurrency with Stash's own spawn-per-call processes (WAL handles DB
   contention; the single-running-job guard needs care).
2. **Lazy/slim imports in Python** — numpy import is ~400-700 ms of the ~1.1 s
   spawn (measured); making it lazy or dropping it from the hot path cuts spawn
   to ~0.2-0.4 s. Cheap, low-risk, a partial mitigation that also helps the
   compiled hybrid's fallback path (recommended regardless).
3. **Accept the status quo** — hooks already enqueue (PR 90); interactive ops are
   ~0.6-1.4 s. Judge against the measured Phase 0 numbers.

## 7. Open questions (must resolve before committing)

Phase 0 answered the first two:

1. ~~Which pain dominates?~~ **Measured**: interactive latency is spawn-dominated
   (~1.1 s per call, ~55-250 ms of work); the cold build is 278 s here with
   similarity + indexing + varied ordering as the top stages. Both the RPC
   conversion (interactive) and the compiled core (build) have measured targets.
2. ~~Real `d` and sparsity?~~ **Measured**: d = 10,245 content features, ~33 per
   scene (0.3% sparsity), N = 23,917 — validates the d-immunity argument.
3. Target Stash version's RPC stability for hooks (v0.31 declared today).
4. ~~Required platform matrix (windows? arm64? — decides 5.3).~~ **Answered
   (2026-08-09): linux amd64/arm64, windows amd64, darwin amd64/arm64** —
   Stash's own release matrix; unsupported platforms simply fall back to
   numpy/pure Python (the resolver probe rejects wrong-arch binaries).
5. BLAS quality on the actual server (the Go-vs-numpy ratio at the real d ~ 10k
   is expected to exceed the d=600 measurement of 12.4x).
6. Root cause of the observed `bus error` crash on numpy import in the
   container (defect ticket, independent of the language decision).

## 8. Proposed sequencing

- **Phase 0 (done):** POC banked (the `poc/golang-similarity-benchmark/` module,
  since removed); automated benchmark harness (`scripts/benchmark.py`);
  interactive latency, cold-build stage breakdown, install-deps cost, and real
  d/sparsity measured (2.4).
- **Phase 1:** **decided (2026-08-09): compiled core (Go)**. The RPC conversion
  is off the table (disproven — no residency in the `rpc` interface; RPC offers
  no benefit over `raw` for a binary). The compiled core is the lever for **both**
  goals: ms-level spawn removes the per-call cost AND the d-immunity addresses
  the build (278 s build, similarity 132 s of it). Lazy-import slimming
  (section 6) is a cheap partial mitigation worth doing regardless.
- **Phase 2 (compiled core — next work package):** port the content-neighbor and
  performer-similarity kernels (math already validated in the POC), wire to the
  sidecar via the differential harness (4.2), ship as optional acceleration
  replacing numpy on the **existing `raw` interface** (the exec line becomes the
  binary; same stdin/stdout JSON contract; ~3-8 ms spawn), pure-Python fallback
  retained; measure end-to-end on the installed sidecar.

### Phase 2 delivered (2026-08-09)

**Done.** The kernels are promoted from the POC to a real Go module (`core/`,
`github.com/mrx-31415/stash-curator/core`), wired into the model build, and
covered by a differential gate. The binary does **not ship in the plugin zip
yet** — distribution (5.2/5.3) is the next work package.

- `core/` — `curator-core` CLI (`version`, `content-neighbors`,
  `performer-similarity`): NDJSON progress + result over stdout, JSON payload
  over stdin. Reads feature rows directly from the SQLite feature artifact
  (pure-Go `modernc.org/sqlite`, `CGO_ENABLED=0`; the mattn/modernc decision is
  deferred to distribution). Version injected from `pyproject.toml` at build
  time (`scripts/build_core.sh`).
- Content-neighbor stage mirrors `_content_neighbors_numpy` exactly, including
  the `_preference_content_vectors` derivation (strengths from learned
  affinities, generic-weight multiplier, L2 normalization). Performer-similarity
  stage mirrors `_performer_similarity_scores_numpy`, including the masked-NaN
  semantics: numpy's dense `block_value * block_used` keeps `NaN * False = NaN`
  in the numerator whenever a weight>0 cosine block has a zero norm on either
  side, so pairs where either profile lacks any global cosine block are excluded
  from candidates — the Go kernel reproduces that exactly (documented in
  `core/performer.go`). This is an existing numpy-path behavior the pure-Python
  fallback does not share; fixing it is a separate product decision that would
  change model output vs today's numpy builds.
- Python wiring (`curator/core.py` + `curator/model/builder.py`): resolver
  (`CURATOR_CORE` env > installed `plugin/curator-core` > repo
  `core/bin/curator-core`), protocol probe (version mismatch degrades to
  numpy), subprocess runner with streamed progress; dispatch order is
  compiled core > numpy > pure Python; a resolved-but-broken binary fails the
  stage loudly instead of silently falling back. Post-selection evidence math
  and the identity-affinity derivation are shared helpers between the numpy and
  compiled paths, so the remaining math is identical by construction.
- Differential gate (`tests/core/test_core.py`, `tests/model/test_core.py`):
  seeded synthetic corpora varying N, d, nnz, sparsity (never a real sidecar);
  exact ids/counts, 1e-9 floats, identical selection/ordering; cross-thread
  determinism (1t vs 4t byte-identical); broken-binary and fallback contract.
  `scripts/verify core` builds the binary, runs `go vet`/`go test`, and runs
  the gate; `scripts/verify full` gates first, then runs the unit suite with
  the binary active (329 tests). CI gained setup-go and a `core` job.
- Measured (2026-08-09, this dev host, 4-core):
  - Production-shape synthetic (N=24 000, d=10 245, nnz=33, ~55% labeled —
    the Phase 0-measured feature shape), real builder stages: content
    neighbors numpy 126.4s -> core 8.1s (**15.6x**); performer similarity
    (10 000 profiles, 200 known) 10.8s -> 9.1s (1.2x — the performer stage is
    pair-bound, not a d-immunity win); spawn `curator-core version` vs
    `python3 -c "import curator"` ~7x on this box.
  - Docker cold build on a copy of the live sidecar (23 860 scenes, 895
    labeled) with the core in the plugin zip: similarity stage 119.3s
    (content 75.7 + performer 43.6) vs the Phase 0 numpy baseline 132s
    (74.5 + 57.3) — ~10% at this library's low-label shape; total build
    330s (includes old-schema migrations and numpy-less fallbacks in other
    stages). The container's content-stage span is ~10x the host core time
    at the presumed shape; the container's feature-build shape was not
    captured before teardown — follow-up: confirm the container's feature
    density and that the core subprocess ran (correctness gates are green
    regardless).
- Acceptance deltas: artifact hashes differ from numpy builds in the last
  float bits (documented delta — accumulation order differs at ~1e-15);
  stage-level outputs match within the 1e-9 tolerance.
- **Phase 3 (distribution): delivered (2026-08-09).** One zip with per-arch
  binaries (linux amd64/arm64, windows amd64, darwin amd64/arm64), runtime
  select + pure-Python fallback, archive test asserts binary presence per
  shipped platform; the pages/release/integration workflows install Go.
  `modernc.org/sqlite` (pure Go) means one machine cross-compiles every
  target — native per-arch runners were not needed. The `raw` interface
  stays; switching the exec line to the binary is a later, separate step.
- **Phase 4 (full Go backend on `raw`): decided shape (2026-08-10).** The
  kernel port is done (similarity + pagerank), the venv is gone (numpy/
  networkx are dev-only oracles in `tests/oracle.py`), and the installed
  cold build measures 3.2x on the similarity stage with zero runtime
  installs. The remaining question is whether the *whole backend* becomes Go
  (the exec line becomes `curator-core`). Full handover + first agent prompt:
  `docs/handover-go-backend.md`.

  Decomposition (each slice keeps the previous state shippable — unported ops
  fall back to the Python backend until the binary covers them):

  - **Slice 0 — transport + skeleton.** The binary implements the raw
    protocol (stdin JSON → dispatch → stdout JSON), settings application, and
    the ordered, checksummed migration chain + artifact attach/views (the
    sidecar-parity surface — the riskiest part). Ships with the trivial ops
    (round_trip, health, get_config, get_job_status) and a Python fallback
    dispatch for everything else.

    > Delivered (2026-08-10): transport, settings, migration chain with
    > byte-identical checksums (parity proven both directions), artifact
    > attach/views, byte-identical trivial ops, `profile_trace` parity for
    > `get_config`, and the Python fallback. Differential gate:
    > `tests/core/test_backend.py`. Handover for the next slice:
    > `docs/handover-go-backend-slice1.md`.
  - **Slice 1 — read-path interactive ops (highest ROI).** get_slate,
    get_similar (the math is already Go), get_explanation, get_shortlist,
    feedback/recommendation history, taste profile, diagnostics. Pure sidecar
    reads + byte-exact JSON; this is what kills the ~300-700ms per-call
    interactive spawn (5ms binary spawn).
  - **Slice 2 — network layer (the goroutine slice).** Two GraphQL clients
    with one pattern: Stash sync (incremental reconciliation) and StashDB
    expand/hunt (performer hunt measured ~47s wall — the most fetch-bound
    interactive op; errgroup fan-out over performers is the real concurrency
    win). Local Similar is sidecar-only; the sync side is mostly write-bound
    (51s measured, most of it reconciliation + DB), so the expand/hunt side
    benefits most.
  - **Slice 3 — write-path tasks.** backup/compact/vacuum/prepare
    (mechanical SQLite), then the build's remaining Python stages
    (affinities, scoring, lanes, publication — the largest port chunk, each a
    bounded algorithm with the published model artifact as the oracle).
  - **Slice 4 — frontend parity pass + delete Python.** Every op's JSON
    contract verified byte-for-byte against the current backend's outputs
    (the existing suite is the oracle), then the Python backend ships out.

  Sequential order: Slice 0 must land first (parity foundation); Slice 1 is
  the recommended first vertical slice after it. The exec-line swap happens
  when Slice 0 + 1 are covered; unported ops keep the Python fallback until
  then.
