"""Faithful replica of production curator/model/builder.py::_content_neighbors_numpy.

Same math and order: block 2048 (memory-limited box; production uses 4096 — the
algorithm and results are identical), float64 target @ labeled.T, float32 binary
matmul for shared counts, sim *= 1-exp(-shared/4), weights = sim^3 * conf,
per-row flatnonzero + partition + sort, top-12 by (-weight, column).

Usage: OPENBLAS_NUM_THREADS=N python3 ref_numpy.py N D NNZ [verify_go_file]
"""

import json
import os
import sys
import time

import numpy as np

BLOCK = 1024
MIN_SIM = 0.05
NEIGHBOR_COUNT = 12


def generate(n, d, nnz, seed=7):
    rng = np.random.default_rng(seed)
    values = {}
    for i in range(n):
        cols = rng.choice(d, size=nnz, replace=False)
        vals = np.abs(rng.standard_normal(nnz))
        vals /= np.linalg.norm(vals)
        values[i] = {int(c): float(v) for c, v in zip(cols, vals, strict=True)}
    conf = 0.3 + rng.random(n) * 0.7
    return values, conf


def content_neighbors_numpy(values, conf, min_sim=MIN_SIM, neighbor_count=NEIGHBOR_COUNT):
    """Returns per-scene list of (labeled_j, similarity, weight) selected neighbors."""
    scene_ids = sorted(values)
    column_names = sorted({c for sid in scene_ids for c in values[sid]})
    col_index = {c: i for i, c in enumerate(column_names)}
    n = len(scene_ids)
    d = len(column_names)
    labeled_values = np.zeros((n, d))
    for col, sid in enumerate(scene_ids):
        for c, v in values[sid].items():
            labeled_values[col, col_index[c]] = v
    target_values = labeled_values
    labeled_conf = np.array(conf)
    labeled_binary = (labeled_values != 0).astype(np.float32)
    target_binary = (target_values != 0).astype(np.float32)
    self_column = np.arange(n)

    t_matmul = 0.0
    t_select = 0.0
    results = {}
    for start in range(0, n, BLOCK):
        end = min(start + BLOCK, n)
        t0 = time.perf_counter()
        sim = target_values[start:end] @ labeled_values.T
        shared = (target_binary[start:end] @ labeled_binary.T).astype(np.float64)
        sim *= 1.0 - np.exp(-shared / 4.0)
        weights = sim**3 * labeled_conf[np.newaxis, :]
        valid = sim >= min_sim
        for local_row in range(end - start):
            own = int(self_column[start + local_row])
            if own >= 0:
                valid[local_row, own] = False
        t_matmul += time.perf_counter() - t0

        t1 = time.perf_counter()
        for local_row in range(end - start):
            sid = scene_ids[start + local_row]
            vi = np.flatnonzero(valid[local_row])
            if len(vi) == 0:
                results[sid] = []
                continue
            rw = weights[local_row, vi]
            chosen = min(neighbor_count, len(rw))
            boundary = float(np.partition(rw, len(rw) - chosen)[len(rw) - chosen])
            candidates = vi[rw >= boundary]
            ev = sorted(
                (
                    (int(c), float(sim[local_row, c]), float(weights[local_row, c]))
                    for c in candidates
                ),
                key=lambda item: (-item[2], item[0]),
            )[:neighbor_count]
            results[sid] = ev
        t_select += time.perf_counter() - t1
    return results, t_matmul, t_select


def main():
    if sys.argv[1] == "dump":
        # dump N D NNZ OUT  -> single source of truth for cross-verification.
        n, d, nnz = (int(x) for x in sys.argv[2:5])
        out = sys.argv[5]
        values, conf = generate(n, d, nnz)
        results, _, _ = content_neighbors_numpy(values, conf)
        with open(out, "w") as fh:
            json.dump(
                {
                    "values": {str(k): v for k, v in values.items()},
                    "conf": [float(x) for x in conf],
                    "results": {str(k): [[j, s, w] for j, s, w in v] for k, v in results.items()},
                },
                fh,
            )
        print(f"dumped {out}")
        return
    n, d, nnz = (int(x) for x in sys.argv[1:4])
    verify_path = sys.argv[4] if len(sys.argv) > 4 else None
    reps = int(os.environ.get("NP_REPS", "3"))
    values, conf = generate(n, d, nnz)

    best = None
    for _ in range(reps):
        t0 = time.perf_counter()
        results, t_mm, t_sel = content_neighbors_numpy(values, conf)
        el = time.perf_counter() - t0
        if best is None or el < best[0]:
            best = (el, results, t_mm, t_sel)
    el, results, t_mm, t_sel = best
    macs = n * n * d * 2
    valid_counts = [len(v) for v in results.values()]
    print(
        f"numpy  n={n} d={d} nnz={nnz} "
        f"threads={os.environ.get('OPENBLAS_NUM_THREADS', '?')} reps={reps}: "
        f"{el:.2f}s total  (matmul+overlap {t_mm:.2f}s, per-row select {t_sel:.2f}s, "
        f"dense MACs {macs / 1e9:.1f}G -> {macs / el / 1e9:.1f} GFLOPS effective; "
        f"avg valid/row {sum(valid_counts) / len(valid_counts):.0f})"
    )
    sys.stdout.flush()

    if verify_path:
        # Compare against Go's output (JSON: per row [[j, s, w], ...]).
        with open(verify_path) as fh:
            go_results = json.load(fh)
        mismatched = 0
        max_w_err = 0.0
        for i in range(n):
            rp = [(j, s, w) for j, s, w in results[i]]
            gp = [tuple(x) for x in go_results[i]]
            if len(rp) != len(gp):
                mismatched += 1
                continue
            for (j1, _s1, w1), (j2, _s2, w2) in zip(rp, gp, strict=True):
                if j1 != j2:
                    mismatched += 1
                    break
                max_w_err = max(max_w_err, abs(w1 - w2))
        print(f"verify vs Go: mismatched rows={mismatched} maxWErr={max_w_err:.3e}")


if __name__ == "__main__":
    main()
