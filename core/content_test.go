package main

// Kernel self-verification: the optimized kernels against straightforward
// reference implementations, determinism across goroutine counts, and selection
// ordering. The Python differential harness (tests/core/, tests/model/) is the
// oracle against the production numpy paths.

import (
	"math"
	"math/rand"
	"reflect"
	"sort"
	"testing"
	"time"
)

func genSparseRows(t *testing.T, n, nnz, d int, seed int64) ([]sparseRow, []string) {
	t.Helper()
	rng := rand.New(rand.NewSource(seed))
	rows := make([]sparseRow, n)
	ids := make([]string, n)
	for i := range rows {
		perm := rng.Perm(d)[:nnz]
		sort.Ints(perm)
		keys := make([]int, nnz)
		values := make([]float64, nnz)
		var sumSquares float64
		for k := range perm {
			keys[k] = perm[k]
			values[k] = math.Abs(rng.NormFloat64())
			sumSquares += values[k] * values[k]
		}
		norm := math.Sqrt(sumSquares)
		for k := range values {
			values[k] /= norm
		}
		rows[i] = sparseRow{keys: keys, values: values}
		ids[i] = string(rune('a' + i))
	}
	return rows, ids
}

// contentRef is the sort-based reference (no heap), same math.
func contentRef(
	targetRows []sparseRow,
	ownPos []int,
	colLists [][]colEntry,
	labeledConf []float64,
	labeledIDs []string,
	cfg contentConfig,
) [][]contentNeighbor {
	n := len(targetRows)
	results := make([][]contentNeighbor, n)
	sims := make([]float64, len(labeledConf))
	shared := make([]int32, len(labeledConf))
	stamps := make([]int32, len(labeledConf))
	stamp := int32(0)
	for i := range targetRows {
		stamp++
		row := targetRows[i]
		for k, key := range row.keys {
			value := row.values[k]
			for _, ce := range colLists[key] {
				pos := ce.pos
				if stamps[pos] != stamp {
					stamps[pos] = stamp
					sims[pos] = value * ce.v
					shared[pos] = 1
				} else {
					sims[pos] += value * ce.v
					shared[pos]++
				}
			}
		}
		var candidates []contentNeighbor
		for pos := range labeledConf {
			if stamps[pos] != stamp || pos == ownPos[i] {
				continue
			}
			s := sims[pos] * (1 - math.Exp(-float64(shared[pos])/4.0))
			if s < cfg.MinSimilarity {
				continue
			}
			candidates = append(candidates, contentNeighbor{id: labeledIDs[pos], s: s, w: s * s * s * labeledConf[pos]})
		}
		sort.Slice(candidates, func(a, b int) bool {
			if candidates[a].w != candidates[b].w {
				return candidates[a].w > candidates[b].w
			}
			return candidates[a].id < candidates[b].id
		})
		if len(candidates) > cfg.NeighborCount {
			candidates = candidates[:cfg.NeighborCount]
		}
		results[i] = candidates
	}
	return results
}

func buildColLists(rows []sparseRow, d int) [][]colEntry {
	lists := make([][]colEntry, d)
	for pos, row := range rows {
		for k, key := range row.keys {
			lists[key] = append(lists[key], colEntry{pos: pos, v: row.values[k]})
		}
	}
	return lists
}

func TestContentKernelMatchesReference(t *testing.T) {
	cfg := contentConfig{MinSimilarity: 0.05, NeighborCount: 12}
	for _, params := range []struct{ n, nnz, d int }{
		{300, 12, 120},
		{600, 30, 600},
		{100, 3, 50},
		{50, 40, 200},
	} {
		rows, _ := genSparseRows(t, params.n, params.nnz, params.d, 7)
		conf := make([]float64, params.n)
		for i := range conf {
			conf[i] = 0.3 + rand.Float64()*0.7
		}
		labeledIDs := make([]string, params.n)
		ownPos := make([]int, params.n)
		for i := 0; i < params.n; i++ {
			labeledIDs[i] = string(rune('a' + i))
			ownPos[i] = i
		}
		colLists := buildColLists(rows, params.d)
		got := contentKernel(rows, ownPos, colLists, conf, labeledIDs, cfg, params.n, 4)
		want := contentRef(rows, ownPos, colLists, conf, labeledIDs, cfg)
		if len(got) != len(want) {
			t.Fatalf("row count mismatch: got %d want %d", len(got), len(want))
		}
		mismatched, maxWErr := 0, 0.0
		for i := range want {
			if len(got[i]) != len(want[i]) {
				mismatched++
				continue
			}
			for m := range want[i] {
				if got[i][m].id != want[i][m].id {
					mismatched++
					break
				}
				if err := math.Abs(got[i][m].w - want[i][m].w); err > maxWErr {
					maxWErr = err
				}
			}
		}
		if mismatched != 0 || maxWErr != 0 {
			t.Fatalf("n=%d: mismatched rows=%d maxWErr=%e", params.n, mismatched, maxWErr)
		}
	}
}

func TestContentKernelDeterministicAcrossThreads(t *testing.T) {
	cfg := contentConfig{MinSimilarity: 0.05, NeighborCount: 12}
	rows, _ := genSparseRows(t, 500, 15, 300, 11)
	conf := make([]float64, len(rows))
	labeledIDs := make([]string, len(rows))
	ownPos := make([]int, len(rows))
	for i := range rows {
		conf[i] = 0.3 + rand.Float64()*0.7
		labeledIDs[i] = string(rune('a' + i))
		ownPos[i] = i
	}
	colLists := buildColLists(rows, 300)
	one := contentKernel(rows, ownPos, colLists, conf, labeledIDs, cfg, len(rows), 1)
	four := contentKernel(rows, ownPos, colLists, conf, labeledIDs, cfg, len(rows), 4)
	if !reflect.DeepEqual(one, four) {
		t.Fatal("thread counts produced different neighbor sets")
	}
}

func TestContentKernelSelectionOrder(t *testing.T) {
	// A row against two candidates with equal weight must order by id ascending,
	// and the output must be sorted by (-weight, id).
	cfg := contentConfig{MinSimilarity: 0.05, NeighborCount: 12}
	rows := []sparseRow{
		{keys: []int{0}, values: []float64{1.0}},
	}
	ownPos := []int{-1}
	conf := []float64{1.0, 1.0}
	labeledIDs := []string{"b", "a"}
	// Both candidates share key 0; sim and weight are identical, so id order wins.
	colLists := [][]colEntry{{{pos: 0, v: 1.0}, {pos: 1, v: 1.0}}}
	got := contentKernel(rows, ownPos, colLists, conf, labeledIDs, cfg, 1, 1)
	if len(got[0]) != 2 {
		t.Fatalf("expected 2 neighbors, got %d", len(got[0]))
	}
	if got[0][0].id != "a" || got[0][1].id != "b" {
		t.Fatalf("tie-break must sort by id ascending: %+v", got[0])
	}
}

func TestContentKernelExcludesSelf(t *testing.T) {
	cfg := contentConfig{MinSimilarity: 0.05, NeighborCount: 12}
	rows := []sparseRow{
		{keys: []int{0}, values: []float64{1.0}},
		{keys: []int{0}, values: []float64{1.0}},
	}
	ownPos := []int{0, 1}
	conf := []float64{1.0, 1.0}
	labeledIDs := []string{"self", "other"}
	colLists := buildColLists(rows, 1)
	got := contentKernel(rows, ownPos, colLists, conf, labeledIDs, cfg, 2, 1)
	if len(got[0]) != 1 || got[0][0].id != "other" {
		t.Fatalf("row 0 must exclude itself and keep the other: %+v", got[0])
	}
	if len(got[1]) != 1 || got[1][0].id != "self" {
		t.Fatalf("row 1 must exclude itself and keep the other: %+v", got[1])
	}
}

func TestPerformerKernelDeterministicAcrossThreads(t *testing.T) {
	payload := performerPayload{
		BlockWeights: map[string]float64{
			"content": 1.0, "measurements": 1.0, "augmentation": 0.9,
			"ethnicity": 0.8, "height": 0.7, "hair": 0.45,
		},
		Cutoff:        0.005,
		NumericBlocks: []string{"measurements"},
		NumericScales: map[string]float64{"height_cm": 12.0, "cup_index": 2.0},
	}
	profiles := make(map[string]*performerProfile)
	for i := 0; i < 200; i++ {
		id := string(rune('p'+i%26)) + string(rune('a'+i/26))
		blocks := map[string]map[string]profileValue{
			"content":      {"tag:a": {value: 0.8, confidence: 0.9}, "tag:b": {value: 0.4, confidence: 0.7}},
			"hair":         {"brown": {value: 1.0, confidence: 0.8}},
			"measurements": {"cup_index": {value: float64(30 + i%10), confidence: 1.0}},
		}
		if i%3 == 0 {
			blocks["augmentation"] = map[string]profileValue{"fake": {value: 1.0, confidence: 1.0}}
		}
		profiles[id] = &performerProfile{id: id, blocks: blocks}
	}
	numeric := map[string]bool{"measurements": true}
	known := map[string][]float64{}
	for i := 0; i < 5; i++ {
		id := string(rune('p' + i))
		known[id] = []float64{0.4, 0.9}
	}
	payload.IdentityAffinity = known

	one := performerSimilarityScores(payload, profiles, numeric)
	payload.Threads = 1
	four := performerSimilarityScores(payload, profiles, numeric)
	if !reflect.DeepEqual(one, four) {
		t.Fatal("thread counts produced different performer results")
	}
	// Every profile must be present in the result.
	for id := range profiles {
		if _, ok := one[id]; !ok {
			t.Fatalf("missing result for profile %s", id)
		}
	}
}

func TestPerformerPairHandComputed(t *testing.T) {
	weights := map[string]float64{"content": 1.0}
	scales := map[string]float64{}
	numeric := map[string]bool{}
	left := &performerProfile{
		id:     "l",
		blocks: map[string]map[string]profileValue{"content": {"a": {value: 1.0, confidence: 0.5}}},
		norms:  map[string]float64{"content": 1.0},
	}
	right := &performerProfile{
		id:     "r",
		blocks: map[string]map[string]profileValue{"content": {"a": {value: 0.5, confidence: 0.5}}},
		norms:  map[string]float64{"content": 0.5},
	}
	similarity, blocks := performerPair(left, right, []string{"content"}, weights, scales, numeric)
	// dot = 0.5, norm product = 0.5, confidence = 0.5 -> cosine = 0.5.
	if math.Abs(similarity-0.5) > 1e-12 {
		t.Fatalf("expected similarity 0.5, got %v", similarity)
	}
	if !reflect.DeepEqual(blocks, map[string]float64{"content": 0.5}) {
		t.Fatalf("unexpected blocks: %v", blocks)
	}
}

func TestProfileRecorderSpans(t *testing.T) {
	disabled := newProfileRecorder(false)
	end := disabled.begin("core.nothing")
	end()
	disabled.emit()
	if len(disabled.spans) != 0 {
		t.Fatalf("disabled recorder must not collect spans")
	}
	enabled := newProfileRecorder(true)
	end = enabled.begin("core.work")
	time.Sleep(2 * time.Millisecond)
	end()
	if len(enabled.spans) != 1 {
		t.Fatalf("expected one span, got %d", len(enabled.spans))
	}
	span := enabled.spans[0]
	if span.name != "core.work" || span.durUs < 1000 || span.offsetUs < 0 {
		t.Fatalf("unexpected span: %+v", span)
	}
}

func TestPagerankConvergesAndIsDeterministic(t *testing.T) {
	adjacency := map[string]map[string]float64{
		"a": {"b": 0.6, "c": 0.4},
		"b": {"a": 1.0},
		"c": {}, // dangling
	}
	first := pagerank(adjacency, "a", 0.85, 100, 1e-6)
	second := pagerank(adjacency, "a", 0.85, 100, 1e-6)
	if !reflect.DeepEqual(first, second) {
		t.Fatal("pagerank must be deterministic")
	}
	total := 0.0
	for _, score := range first {
		total += score
	}
	if math.Abs(total-1.0) > 1e-3 {
		t.Fatalf("scores must conserve mass, got %v", total)
	}
	if first["a"] <= 0 || first["b"] <= 0 || first["c"] <= 0 {
		t.Fatalf("all nodes must have positive mass: %v", first)
	}
}
