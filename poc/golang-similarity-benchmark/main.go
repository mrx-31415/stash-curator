// POC benchmark: Curator content-neighbor similarity stage.
//
// Mirrors the production algorithm in curator/model/builder.py
// (_content_neighbors_numpy): per row, sim = dot(A_i, B_j) and
// shared = count of co-occurring non-zero features, then
//
//	s = sim * (1 - exp(-shared/4))
//	w = s^3 * labeled_conf[j]
//	keep top-k by (-w, j) among s >= min_sim (excluding self).
//
// Three kernels:
//
//	denseStraight : row-major A, column-major B, all d keys per row (naive port)
//	sparseFused   : exploits A's non-zeros AND B's column non-zeros; fused
//	                sim+shared in one pass; goroutine-parallel over row chunks
//	sparseFused1  : same, single thread (core-scaling attribution)
package main

import (
	"container/heap"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"os"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	minSim        = 0.05
	neighborCount = 12
)

type Row struct {
	Keys   []int
	Values []float64
}

// Neighbor mirrors production's evidence tuple (labeled id, similarity, weight).
type Neighbor struct {
	J int
	S float64
	W float64
}

// ---------- data generation (matches the Python replica's generator) ----------

func genData(n, d, nnz int, seed int64) ([]Row, [][]float64, [][]float64) {
	rng := rand.New(rand.NewSource(seed))
	rows := make([]Row, n)
	for i := range rows {
		perm := rng.Perm(d)[:nnz]
		sort.Ints(perm)
		keys := make([]int, nnz)
		vals := make([]float64, nnz)
		var sumsq float64
		for k := range perm {
			keys[k] = perm[k]
			vals[k] = math.Abs(rng.NormFloat64())
			sumsq += vals[k] * vals[k]
		}
		norm := math.Sqrt(sumsq)
		for k := range vals {
			vals[k] /= norm
		}
		rows[i] = Row{keys, vals}
	}
	// Dense A (row-major) and column-major BT for the straight kernel.
	a := make([][]float64, n)
	bt := make([][]float64, d)
	for k := range bt {
		bt[k] = make([]float64, n)
	}
	for i := range rows {
		a[i] = make([]float64, d)
		for k, key := range rows[i].Keys {
			a[i][key] = rows[i].Values[k]
			bt[key][i] = rows[i].Values[k]
		}
	}
	conf := make([]float64, n)
	for i := range conf {
		conf[i] = 0.3 + rng.Float64()*0.7
	}
	return rows, a, bt
}

// ---------- kernel: sparse, fused ----------

type ColEntry struct {
	J int
	V float64
}

func buildColLists(rows []Row, d int) [][]ColEntry {
	lists := make([][]ColEntry, d)
	for i, row := range rows {
		for k, key := range row.Keys {
			lists[key] = append(lists[key], ColEntry{i, row.Values[k]})
		}
	}
	return lists
}

// sparseFused: sim and shared accumulated in one pass over (row nonzeros x column
// nonzeros); streaming top-k per row. Returns per-row selected neighbors.
func sparseFused(rows []Row, colLists [][]ColEntry, conf []float64, nthreads int) [][]Neighbor {
	n := len(rows)
	results := make([][]Neighbor, n)
	if nthreads > n {
		nthreads = n
	}
	chunk := (n + nthreads - 1) / nthreads
	var wg sync.WaitGroup
	for w := 0; w < nthreads; w++ {
		start := w * chunk
		end := start + chunk
		if end > n {
			end = n
		}
		if start >= end {
			continue
		}
		wg.Add(1)
		go func(start, end int) {
			defer wg.Done()
			sims := make([]float64, n)
			shared := make([]int32, n)
			stamps := make([]int32, n)
			stamp := int32(0)
			for i := start; i < end; i++ {
				stamp++
				row := rows[i]
				// Accumulate sim and shared for all j reachable from row's keys.
				for k, key := range row.Keys {
					val := row.Values[k]
					for _, ce := range colLists[key] {
						j := ce.J
						if stamps[j] != stamp {
							stamps[j] = stamp
							sims[j] = val * ce.V
							shared[j] = 1
						} else {
							sims[j] += val * ce.V
							shared[j]++
						}
					}
				}
				// Collect valid candidates, stream-select top-k by (-w, j).
				sel := &neighborHeap{}
				heap.Init(sel)
				for j := 0; j < n; j++ {
					if stamps[j] != stamp || j == i {
						continue
					}
					s := sims[j] * (1 - math.Exp(-float64(shared[j])/4.0))
					if s < minSim {
						continue
					}
					w := s * s * s * conf[j]
					if sel.Len() < neighborCount {
						heap.Push(sel, Neighbor{j, s, w})
					} else if w > sel.Peek().W || (w == sel.Peek().W && j < sel.Peek().J) {
						heap.Pop(sel)
						heap.Push(sel, Neighbor{j, s, w})
					}
				}
				out := make([]Neighbor, 0, sel.Len())
				for sel.Len() > 0 {
					out = append(out, heap.Pop(sel).(Neighbor))
				}
				// heap.Pop yields worst-first; reverse to (-w, j) order.
				for l, r := 0, len(out)-1; l < r; l, r = l+1, r-1 {
					out[l], out[r] = out[r], out[l]
				}
				results[i] = out
			}
		}(start, end)
	}
	wg.Wait()
	return results
}

// ---------- kernel: dense straight port (all d keys per row, fused sim+shared) ----------

func denseStraight(a [][]float64, bt [][]float64, conf []float64, nthreads int) [][]Neighbor {
	n := len(a)
	d := len(bt)
	results := make([][]Neighbor, n)
	if nthreads > n {
		nthreads = n
	}
	chunk := (n + nthreads - 1) / nthreads
	var wg sync.WaitGroup
	for w := 0; w < nthreads; w++ {
		start := w * chunk
		end := start + chunk
		if end > n {
			end = n
		}
		if start >= end {
			continue
		}
		wg.Add(1)
		go func(start, end int) {
			defer wg.Done()
			sims := make([]float64, n)
			shared := make([]int32, n)
			for i := start; i < end; i++ {
				row := a[i]
				for j := range sims {
					sims[j] = 0
					shared[j] = 0
				}
				for k := 0; k < d; k++ {
					av := row[k]
					if av == 0 {
						continue
					}
					col := bt[k]
					for j := 0; j < n; j++ {
						bv := col[j]
						if bv == 0 {
							continue
						}
						sims[j] += av * bv
						shared[j]++
					}
				}
				sel := &neighborHeap{}
				heap.Init(sel)
				for j := 0; j < n; j++ {
					if j == i || shared[j] == 0 {
						continue
					}
					s := sims[j] * (1 - math.Exp(-float64(shared[j])/4.0))
					if s < minSim {
						continue
					}
					w := s * s * s * conf[j]
					if sel.Len() < neighborCount {
						heap.Push(sel, Neighbor{j, s, w})
					} else if w > sel.Peek().W || (w == sel.Peek().W && j < sel.Peek().J) {
						heap.Pop(sel)
						heap.Push(sel, Neighbor{j, s, w})
					}
				}
				out := make([]Neighbor, 0, sel.Len())
				for sel.Len() > 0 {
					out = append(out, heap.Pop(sel).(Neighbor))
				}
				for l, r := 0, len(out)-1; l < r; l, r = l+1, r-1 {
					out[l], out[r] = out[r], out[l]
				}
				results[i] = out
			}
		}(start, end)
	}
	wg.Wait()
	return results
}

// ---------- min-heap of the *worst* kept neighbor: worst (smallest w, largest j) at top ----------

type neighborHeap []Neighbor

func (h neighborHeap) Len() int { return len(h) }
func (h neighborHeap) Less(i, j int) bool {
	if h[i].W != h[j].W {
		return h[i].W < h[j].W
	}
	return h[i].J > h[j].J
}
func (h neighborHeap) Swap(i, j int)  { h[i], h[j] = h[j], h[i] }
func (h *neighborHeap) Push(x any)    { *h = append(*h, x.(Neighbor)) }
func (h *neighborHeap) Pop() any      { old := *h; x := old[len(old)-1]; *h = old[:len(old)-1]; return x }
func (h neighborHeap) Peek() Neighbor { return h[0] }

// candidateStats counts candidates passing the min-sim filter (excluding self).
func candidateStats(rows []Row, colLists [][]ColEntry, conf []float64) float64 {
	n := len(rows)
	sims := make([]float64, n)
	shared := make([]int32, n)
	stamps := make([]int32, n)
	stamp := int32(0)
	total := 0
	for i := range rows {
		stamp++
		row := rows[i]
		for k, key := range row.Keys {
			val := row.Values[k]
			for _, ce := range colLists[key] {
				j := ce.J
				if stamps[j] != stamp {
					stamps[j] = stamp
					sims[j] = val * ce.V
					shared[j] = 1
				} else {
					sims[j] += val * ce.V
					shared[j]++
				}
			}
		}
		for j := 0; j < n; j++ {
			if stamps[j] == stamp && j != i {
				s := sims[j] * (1 - math.Exp(-float64(shared[j])/4.0))
				if s >= minSim {
					total++
				}
			}
		}
	}
	return float64(total) / float64(n)
}

// ---------- harness ----------

func timeKernel(name string, fn func()) time.Duration {
	best := time.Duration(1 << 62)
	reps := 3
	if v := os.Getenv("GO_REPS"); v != "" {
		fmt.Sscanf(v, "%d", &reps)
	}
	for r := 0; r < reps; r++ {
		runtime.GC()
		t0 := time.Now()
		fn()
		el := time.Since(t0)
		if el < best {
			best = el
		}
	}
	fmt.Printf("%-22s %10s\n", name, best.Round(time.Millisecond))
	return best
}

func main() {
	if len(os.Args) >= 2 && os.Args[1] == "verify" {
		// verify PYTHON_DUMP.json  -> compare Go kernels against the Python replica
		// on data owned by the Python side.
		raw, err := os.ReadFile(os.Args[2])
		if err != nil {
			panic(err)
		}
		var dump struct {
			Values  map[string]map[string]float64 `json:"values"`
			Conf    []float64                     `json:"conf"`
			Results map[string][][3]float64       `json:"results"`
		}
		if err := json.Unmarshal(raw, &dump); err != nil {
			panic(err)
		}
		n := len(dump.Results)
		rows := make([]Row, n)
		for i := 0; i < n; i++ {
			vec := dump.Values[fmt.Sprint(i)]
			keys := make([]int, 0, len(vec))
			for k := range vec {
				var key int
				fmt.Sscanf(k, "%d", &key)
				keys = append(keys, key)
			}
			sort.Ints(keys)
			vals := make([]float64, len(keys))
			for m, k := range keys {
				vals[m] = vec[fmt.Sprint(k)]
			}
			rows[i] = Row{keys, vals}
		}
		d := 0
		for _, row := range rows {
			if len(row.Keys) > 0 && row.Keys[len(row.Keys)-1] >= d {
				d = row.Keys[len(row.Keys)-1] + 1
			}
		}
		colLists := buildColLists(rows, d)
		for _, kernel := range []struct {
			name string
			fn   func() [][]Neighbor
		}{{"sparseFusedRef", func() [][]Neighbor { return sparseFusedRef(rows, colLists, dump.Conf) }},
			{"sparseFused(1t)", func() [][]Neighbor { return sparseFused(rows, colLists, dump.Conf, 1) }},
			{"sparseFused(4t)", func() [][]Neighbor { return sparseFused(rows, colLists, dump.Conf, runtime.GOMAXPROCS(0)) }}} {
			got := kernel.fn()
			mismatched, maxWErr := 0, 0.0
			for i := 0; i < n; i++ {
				want := dump.Results[fmt.Sprint(i)]
				if len(want) != len(got[i]) {
					mismatched++
					continue
				}
				for m := range want {
					if int(want[m][0]) != got[i][m].J {
						mismatched++
						break
					}
					if wErr := math.Abs(want[m][2] - got[i][m].W); wErr > maxWErr {
						maxWErr = wErr
					}
				}
			}
			fmt.Printf("verify %-16s vs numpy: mismatched rows=%d maxWErr=%.3e\n", kernel.name, mismatched, maxWErr)
		}
		return
	}
	if len(os.Args) >= 2 && os.Args[1] == "dump" {
		// dump N D NNZ PATH  -> write reference results as JSON for cross-verification.
		var n, d, nnz int
		fmt.Sscanf(os.Args[2], "%d", &n)
		fmt.Sscanf(os.Args[3], "%d", &d)
		fmt.Sscanf(os.Args[4], "%d", &nnz)
		rows, _, _ := genData(n, d, nnz, 7)
		conf := make([]float64, n)
		rng := rand.New(rand.NewSource(99))
		for i := range conf {
			conf[i] = 0.3 + rng.Float64()*0.7
		}
		colLists := buildColLists(rows, d)
		ref := sparseFusedRef(rows, colLists, conf)
		buf, _ := json.Marshal(ref)
		os.WriteFile(os.Args[5], buf, 0o644)
		fmt.Println("dumped", os.Args[5])
		return
	}
	var n, d, nnz int
	if len(os.Args) == 4 {
		fmt.Sscanf(os.Args[1], "%d", &n)
		fmt.Sscanf(os.Args[2], "%d", &d)
		fmt.Sscanf(os.Args[3], "%d", &nnz)
	} else {
		n, d, nnz = 24000, 120, 12
	}
	threads := runtime.GOMAXPROCS(0)
	reps := 3
	if v := os.Getenv("GO_REPS"); v != "" {
		fmt.Sscanf(v, "%d", &reps)
	}
	fmt.Printf("n=%d d=%d nnz=%d threads=%d reps=%d\n", n, d, nnz, threads, reps)

	rows, a, bt := genData(n, d, nnz, 7)
	conf := make([]float64, n)
	rng := rand.New(rand.NewSource(99))
	for i := range conf {
		conf[i] = 0.3 + rng.Float64()*0.7
	}
	colLists := buildColLists(rows, d)

	only := os.Getenv("GO_ONLY")
	if only == "gen" {
		fmt.Println("generation only")
		return
	}
	if only == "dense" {
		timeKernel("denseStraight 4t", func() { denseStraight(a, bt, conf, threads) })
		return
	}
	if only == "sparse" {
		timeKernel("sparseFused 4t", func() { sparseFused(rows, colLists, conf, threads) })
		return
	}
	if only == "sel" {
		// self-check + selection kernels only (no denseStraight)
		avgCand := candidateStats(rows, colLists, conf)
		fmt.Printf("avg valid/row (Go data) ~ %.0f\n", avgCand)
		ref := sparseFusedRef(rows, colLists, conf)
		got := sparseFused(rows, colLists, conf, 1)
		mismatches, maxWErr := 0, 0.0
		for i := range ref {
			if len(ref[i]) != len(got[i]) {
				mismatches++
				continue
			}
			for m := range ref[i] {
				if ref[i][m].J != got[i][m].J {
					mismatches++
					break
				}
				if wErr := math.Abs(ref[i][m].W - got[i][m].W); wErr > maxWErr {
					maxWErr = wErr
				}
			}
		}
		fmt.Printf("self-check: mismatched rows=%d maxWErr=%.3e\n", mismatches, maxWErr)
		timeKernel("sparseFused 4t", func() { sparseFused(rows, colLists, conf, threads) })
		return
	}

	// Workload fairness: average valid-candidate count per row (>= minSim).
	avgCand := candidateStats(rows, colLists, conf)
	fmt.Printf("avg valid/row (Go data) ~ %.0f\n", avgCand)

	// Correctness vs a reference implementation (sort-based top-k, same math).
	ref := sparseFusedRef(rows, colLists, conf)
	got := sparseFused(rows, colLists, conf, 1)
	mismatches := 0
	maxWErr := 0.0
	for i := range ref {
		if len(ref[i]) != len(got[i]) {
			mismatches++
			continue
		}
		for m := range ref[i] {
			if ref[i][m].J != got[i][m].J {
				mismatches++
				break
			}
			if wErr := math.Abs(ref[i][m].W - got[i][m].W); wErr > maxWErr {
				maxWErr = wErr
			}
		}
	}
	fmt.Printf("self-check: mismatched rows=%d maxWErr=%.3e\n", mismatches, maxWErr)

	kernels := os.Getenv("GO_KERNELS")
	run := func(name string) bool {
		return kernels == "" || strings.Contains(kernels, name)
	}
	if run("dense") {
		timeKernel("denseStraight 4t", func() { denseStraight(a, bt, conf, threads) })
	}
	if run("sparse") {
		timeKernel("sparseFused 4t", func() { sparseFused(rows, colLists, conf, threads) })
		timeKernel("sparseFused 1t", func() { sparseFused(rows, colLists, conf, 1) })
	}
}

// sparseFusedRef: straightforward correct implementation (sort, no heap tricks)
// used only to validate the optimized kernel.
func sparseFusedRef(rows []Row, colLists [][]ColEntry, conf []float64) [][]Neighbor {
	n := len(rows)
	results := make([][]Neighbor, n)
	sims := make([]float64, n)
	shared := make([]int32, n)
	stamps := make([]int32, n)
	stamp := int32(0)
	for i := range rows {
		stamp++
		row := rows[i]
		for k, key := range row.Keys {
			val := row.Values[k]
			for _, ce := range colLists[key] {
				j := ce.J
				if stamps[j] != stamp {
					stamps[j] = stamp
					sims[j] = val * ce.V
					shared[j] = 1
				} else {
					sims[j] += val * ce.V
					shared[j]++
				}
			}
		}
		var cand []Neighbor
		for j := 0; j < n; j++ {
			if stamps[j] != stamp || j == i {
				continue
			}
			s := sims[j] * (1 - math.Exp(-float64(shared[j])/4.0))
			if s < minSim {
				continue
			}
			cand = append(cand, Neighbor{j, s, s * s * s * conf[j]})
		}
		sort.Slice(cand, func(x, y int) bool {
			if cand[x].W != cand[y].W {
				return cand[x].W > cand[y].W
			}
			return cand[x].J < cand[y].J
		})
		if len(cand) > neighborCount {
			cand = cand[:neighborCount]
		}
		kept := make([]Neighbor, len(cand))
		copy(kept, cand)
		results[i] = kept
	}
	return results
}
