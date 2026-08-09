# Go similarity-kernel benchmark (POC)

Validates the "fused sparse Go kernel beats numpy on the Curator similarity stage"
hypothesis. The kernels mirror the production algorithm in
`curator/model/builder.py::_content_neighbors_numpy` exactly: per row,
`sim = dot(A_i, B_j)` and `shared = count of co-occurring non-zero features`, then

```
s = sim * (1 - exp(-shared / 4))
w = s^3 * labeled_conf[j]
keep top-12 by (-w, j) among s >= 0.05 (excluding self)
```

## What is here

- `main.go` — three Go kernels:
  - `denseStraight`: row-major A x column-major B, all `d` keys per row (a naive
    dense port; exploits A-side sparsity only).
  - `sparseFused`: exploits A's non-zeros *and* B's column non-zeros, fuses the
    sim+shared accumulation into one pass, streams top-k per row (no big matrices),
    goroutine-parallel over row chunks.
  - `sparseFusedRef` (in-process): sort-based reference used for self-verification.
- `ref_numpy.py` — faithful replica of the production numpy path (block 1024 for
  memory-limited boxes; production uses 4096 — same algorithm, identical results),
  including the float32 binary matmul for shared counts and the per-row
  `flatnonzero` + `partition` + sort selection loop.

## How to run

Requires Go >= 1.26 and numpy (the repo's venv has it):

```bash
# Cross-verify: Python owns the data, Go must reproduce it.
python3 ref_numpy.py dump 300 120 12 /tmp/cross.json
go run . verify /tmp/cross.json

# Benchmarks (best-of-3 Go, best-of-2 numpy; OPENBLAS_NUM_THREADS=4).
go run . 6000 120 12
OPENBLAS_NUM_THREADS=4 python3 ref_numpy.py 6000 120 12
```

## Results (4-core x86_64, numpy 2.5.1 + scipy-openblas 0.3.33, Go 1.26.5)

Correctness first: on shared Python-owned data (N=300) all Go kernels select
identical neighbors to numpy — **0 mismatched rows**, max weight error 1.4e-17
(float associativity noise only).

| Scenario | numpy (prod algo) | Go dense 4t | Go sparse fused 4t | Go sparse 1t |
| --- | --- | --- | --- | --- |
| N=6 000, d=120, nnz=12 | 24.3s | 13.8s (1.8x) | 6.3s (3.9x) | 8.8s |
| N=3 000, d=600, nnz=30 | 18.0s | 4.5s (4.0x) | 1.45s (12.4x) | 1.8s |
| N=24 000, d=120 (production size) | ~400s extrapolated | — | 44.8s | 57.0s |
| N=24 000, d=600 (tag-heavy) | ~19 min extrapolated | — | 51.6s | 51.0s |

Notes:

- This box's OpenBLAS is slow (~4-6 GFLOPS raw matmul; ~0.4-0.6 GFLOPS effective on
  the full pipeline). On a server with a fast multithreaded BLAS the ratios at
  d=120 narrow (the O(N^2) per-row selection scan becomes the common floor); at
  d=600 numpy still performs 20-100x the arithmetic, so the Go win should survive.
- numpy scales with `d` (it densifies: O(N^2 d), twice - float64 dot + float32
  binary). Go sparse scales with non-zero counts: O(N * nnz * col-nnz), immune to
  `d`. Real Curator vectors include description-token columns, so production `d`
  is likely in the hundreds-to-thousands.
- numpy allocates ~3 * block * N * 8B per block (sim/weights/shared); Go streams
  per-row top-k with O(N + k) scratch per worker - no big matrices at all.
- Both implementations pay an O(N^2) selection scan per row; at N=24 000 that is
  the remaining ~20-40s floor for Go (next optimization: stamped iteration over
  only the reachable columns). Production numpy pays the same cost as 24k
  Python-level numpy calls.
- Go kernels are deterministic: 1t and 4t produce identical neighbor sets
  (verified).

## Caveats

- Synthetic data only (seeded; nnz per row fixed, values |N(0,1)|, row-normalized,
  conf ~ U[0.3, 1]). No real sidecar data was used; the real feature-column count
  and sparsity are not yet measured.
- Extrapolations assume numpy's per-MAC cost is constant with N (conservative:
  selection cost grows too).
- See `docs/decisions/002-runtime-swap-planning.md` for how this evidence feeds the
  runtime-swap decision and the equality-coverage plan.
