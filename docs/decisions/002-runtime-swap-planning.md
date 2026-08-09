# Planning: compiled runtime swap (Go/Rust core)

Status: **planning** — no decision made. Record of evidence, the equality-coverage
strategy, the RPC plan pointer, and the release/dev workflow for the compiled-core
direction. Complements ADR 001 (backend runtime, accepted) and
`docs/handover-rpc-plugin.md` (resident RPC conversion, planned).

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

Location: `poc/golang-similarity-benchmark/` (tracked; README has full numbers and
how to run). Kernels mirror production `_content_neighbors_numpy` exactly and were
cross-verified against a Python replica on shared data: **0 mismatched rows**,
max weight error 1.4e-17.

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
| Interactive latency (pages/hooks feel slow) | RPC conversion (Python stays) | Kills ~0.7s spawn + per-call migrate/settings overhead. Designed in `docs/handover-rpc-plugin.md`. |
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
- **Published artifacts**: byte-identical (hash-equal) for the same input corpus —
  the artifact model already checksums and validates generations.
- **JSON API responses**: byte-identical (the frontend contract is the JSON
  payloads; the JS does not change).
- **Floats**: exact for integer/hash/count domains (ids, shared counts, checksums,
  hashes); 1e-9 relative tolerance for similarity/weight/affinity floats; selection
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

Already designed in detail in `docs/handover-rpc-plugin.md` (transport, resident
server, concurrency, lifecycle, steps, risks, acceptance criteria). Additions from
this planning round:

- The RPC conversion is **language-independent and independent of the core swap**:
  the handover's Python resident server works unchanged as the shell for a
  compiled core (each call stays a short JSON-RPC dispatch; the core is invoked
  per call or per task).
- If the backend itself ever becomes Go, Stash's `gorpc` example and
  `pkg/plugin/common` are the reference implementation for the same wire contract.
- Sequencing: do the RPC conversion first if interactive latency is the pain; it
  also removes the per-call `_open()` cost (migrations + settings application run
  on every call today).
- Open items: verify hook behavior under RPC on the target Stash version;
  concurrent `Run` calls (bulk-edit hooks); crash-reconnect semantics via `pie`
  (queue in the sidecar is the safety net).

## 7. Open questions (must resolve before committing)

Phase 0 answered the first two:

1. ~~Which pain dominates?~~ **Measured**: interactive latency is spawn-dominated
   (~1.1 s per call, ~55-250 ms of work); the cold build is 278 s here with
   similarity + indexing + varied ordering as the top stages. Both the RPC
   conversion (interactive) and the compiled core (build) have measured targets.
2. ~~Real `d` and sparsity?~~ **Measured**: d = 10,245 content features, ~33 per
   scene (0.3% sparsity), N = 23,917 — validates the d-immunity argument.
3. Target Stash version's RPC stability for hooks (v0.31 declared today).
4. Required platform matrix (windows? arm64? — decides 5.3).
5. BLAS quality on the actual server (the Go-vs-numpy ratio at the real d ~ 10k
   is expected to exceed the d=600 measurement of 12.4x).
6. Root cause of the observed `bus error` crash on numpy import in the
   container (defect ticket, independent of the language decision).

## 8. Proposed sequencing

- **Phase 0 (done):** POC banked (`poc/golang-similarity-benchmark/`); automated
  benchmark harness (`scripts/benchmark.py`); interactive latency, cold-build
  stage breakdown, install-deps cost, and real d/sparsity measured (2.4).
- **Phase 1:** pick the fix from the table in 3 based on the Phase 0 evidence:
  the strongest measured case is the RPC conversion for interactive latency
  (~1.1 s per call), with the compiled core as the build-time lever (278 s
  build, similarity 132 s of it).
- **Phase 2 (compiled core, if chosen):** port the content-neighbor and
  performer-similarity kernels (math already validated), wire to the sidecar via
  the differential harness (4.2), ship as optional acceleration replacing numpy,
  pure-Python fallback retained; measure end-to-end on the installed sidecar.
- **Phase 3 (optional):** full backend in Go behind the RPC shell, if the hybrid
  proves out and the port budget is available.
