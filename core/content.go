package main

// Content-neighbor stage. Mirrors PreferenceModelBuilder._content_neighbors_numpy
// (curator/model/builder.py) exactly:
//
//   - preference vectors are derived from raw content features the same way
//     _preference_content_vectors does (per-name strength from learned
//     affinities, generic-weight multiplier, per-scene L2 normalization);
//   - per row, sim = dot(A_i, B_j) and shared = count of co-occurring non-zero
//     features (float32-exact counts in numpy, exact integers here);
//   - s = sim * (1 - exp(-shared / 4)); w = s^3 * labeled_conf[j];
//   - keep the top neighbor_count by (-w, id) among s >= min_similarity,
//     excluding self; labeled candidates only (labels restricted to scenes with
//     vectors), mirroring the numpy labeled-column construction.
//
// numpy blocks rows by 4096 for memory reasons; that chunking never changes the
// math, so this kernel processes rows directly (row independence also makes the
// output identical across goroutine counts, verified in the POC and here).

import (
	"container/heap"
	"database/sql"
	"encoding/json"
	"math"
	"os"
	"sort"
	"sync"

	_ "modernc.org/sqlite"
)

type affinityEntry struct {
	Affinity          float64  `json:"affinity"`
	Confidence        float64  `json:"confidence"`
	LearnedAffinity   *float64 `json:"learned_affinity,omitempty"`
	LearnedConfidence *float64 `json:"learned_confidence,omitempty"`
}

type contentConfig struct {
	MinSimilarity   float64 `json:"min_similarity"`
	NeighborCount   int     `json:"neighbor_count"`
	ConfidenceScale float64 `json:"confidence_scale"`
	GenericWeight   float64 `json:"generic_weight"`
}

type contentPayload struct {
	DB             string                   `json:"db"`
	FeatureVersion string                   `json:"feature_version"`
	Labels         map[string][]float64     `json:"labels"`
	LabelMean      float64                  `json:"label_mean"`
	Affinities     map[string]affinityEntry `json:"affinities"`
	Config         contentConfig            `json:"config"`
	ProgressTotal  int                      `json:"progress_total"`
	Threads        int                      `json:"threads,omitempty"`
}

// contentNeighbor mirrors the production evidence tuple (scene id, similarity,
// weight); the outcome is looked up from the labels when emitting.
type contentNeighbor struct {
	id string
	s  float64
	w  float64
}

// neighborHeap keeps the *worst* kept neighbor (smallest w, largest id) at the
// top so the streaming top-k selection matches production's (-weight, id) sort.
type neighborHeap []contentNeighbor

func (h neighborHeap) Len() int { return len(h) }
func (h neighborHeap) Less(i, j int) bool {
	if h[i].w != h[j].w {
		return h[i].w < h[j].w
	}
	return h[i].id > h[j].id
}
func (h neighborHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *neighborHeap) Push(x any)   { *h = append(*h, x.(contentNeighbor)) }
func (h *neighborHeap) Pop() any {
	old := *h
	x := old[len(old)-1]
	*h = old[:len(old)-1]
	return x
}
func (h neighborHeap) Peek() contentNeighbor { return h[0] }

type contentRow struct {
	entityID  string
	featureID string
	name      string
	value     float64
}

func readContentRows(db *sql.DB, featureVersion string) ([]contentRow, error) {
	rows, err := db.Query(`
		SELECT ef.entity_id, fd.feature_id, fd.name, ef.value
		FROM entity_feature ef
		JOIN feature_definition fd ON fd.feature_id = ef.feature_id
		WHERE ef.feature_version = ? AND ef.entity_type = 'scene' AND fd.family = 'content'
		ORDER BY ef.entity_id, fd.name`, featureVersion)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []contentRow{}
	for rows.Next() {
		var r contentRow
		if err := rows.Scan(&r.entityID, &r.featureID, &r.name, &r.value); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// preferenceVectors replicates _preference_content_vectors: the first content
// feature with a given name (in (entity_id, name) order, matching the
// entity_features ordering) fixes that name's strength; each raw vector value is
// scaled by generic + (1-generic) * strength/maximum when any strength exists,
// then the vector is L2-normalized (norm 0 -> 1.0).
func preferenceVectors(
	rows []contentRow,
	affinities map[string]affinityEntry,
	generic float64,
) (map[string]map[string]float64, []string, error) {
	strengths := make(map[string]float64)
	seen := make(map[string]bool)
	for _, r := range rows {
		if seen[r.name] {
			continue
		}
		seen[r.name] = true
		a, ok := affinities[r.featureID]
		if !ok {
			strengths[r.name] = 0.0
			continue
		}
		learned := a.Affinity
		learnedConfidence := a.Confidence
		if a.LearnedAffinity != nil {
			learned = *a.LearnedAffinity
		}
		if a.LearnedConfidence != nil {
			learnedConfidence = *a.LearnedConfidence
		}
		strengths[r.name] = math.Max(0.0, learned) * learnedConfidence
	}
	maximum := 0.0
	for _, strength := range strengths {
		if strength > maximum {
			maximum = strength
		}
	}
	byScene := make(map[string]map[string]float64)
	for _, r := range rows {
		if byScene[r.entityID] == nil {
			byScene[r.entityID] = make(map[string]float64)
		}
		byScene[r.entityID][r.name] = r.value
	}
	sceneOrder := make([]string, 0, len(byScene))
	for sceneID := range byScene {
		sceneOrder = append(sceneOrder, sceneID)
	}
	sort.Strings(sceneOrder)
	weighted := make(map[string]map[string]float64, len(sceneOrder))
	for _, sceneID := range sceneOrder {
		raw := byScene[sceneID]
		names := make([]string, 0, len(raw))
		for name := range raw {
			names = append(names, name)
		}
		sort.Strings(names)
		values := make(map[string]float64, len(names))
		for _, name := range names {
			value := raw[name]
			multiplier := 1.0
			if maximum > 0 {
				multiplier = generic + (1-generic)*strengths[name]/maximum
			}
			if multiplier > 1e-9 {
				values[name] = value * multiplier
			}
		}
		var sumSquares float64
		for _, name := range names {
			value := values[name]
			sumSquares += value * value
		}
		norm := math.Sqrt(sumSquares)
		if norm == 0 {
			norm = 1.0
		}
		scaled := make(map[string]float64, len(values))
		for name, value := range values {
			scaled[name] = value / norm
		}
		weighted[sceneID] = scaled
	}
	return weighted, sceneOrder, nil
}

func runContentNeighbors() {
	var payload contentPayload
	if err := json.NewDecoder(os.Stdin).Decode(&payload); err != nil {
		fail("content-neighbors: invalid payload: %v", err)
	}
	db, err := openReadonly(payload.DB)
	if err != nil {
		fail("content-neighbors: open %s: %v", payload.DB, err)
	}
	defer db.Close()
	rows, err := readContentRows(db, payload.FeatureVersion)
	if err != nil {
		fail("content-neighbors: read features: %v", err)
	}
	preference, sceneOrder, err := preferenceVectors(rows, payload.Affinities, payload.Config.GenericWeight)
	if err != nil {
		fail("content-neighbors: derive preference vectors: %v", err)
	}
	result, err := contentNeighborEvidence(payload, preference, sceneOrder)
	if err != nil {
		fail("content-neighbors: %v", err)
	}
	if err := writeJSONLine(map[string]any{"result": result}); err != nil {
		fail("content-neighbors: write result: %v", err)
	}
}

func contentNeighborEvidence(
	payload contentPayload,
	preference map[string]map[string]float64,
	sceneOrder []string,
) (map[string]any, error) {
	// Column mapping: every feature name across all preference vectors, sorted.
	seenNames := make(map[string]bool)
	for _, vector := range preference {
		for name := range vector {
			seenNames[name] = true
		}
	}
	allNames := make([]string, 0, len(seenNames))
	for name := range seenNames {
		allNames = append(allNames, name)
	}
	sort.Strings(allNames)
	nameIndex := make(map[string]int, len(allNames))
	for index, name := range allNames {
		nameIndex[name] = index
	}

	// Labeled candidates: labels restricted to scenes with vectors, sorted,
	// mirroring numpy's sorted labeled_ids construction.
	labeledIDs := make([]string, 0)
	for sceneID := range payload.Labels {
		if _, ok := preference[sceneID]; ok {
			labeledIDs = append(labeledIDs, sceneID)
		}
	}
	sort.Strings(labeledIDs)
	labeledConf := make([]float64, len(labeledIDs))
	labeledOutcome := make([]float64, len(labeledIDs))
	labeledPos := make(map[string]int, len(labeledIDs))
	for pos, sceneID := range labeledIDs {
		label := payload.Labels[sceneID]
		labeledConf[pos] = label[1]
		labeledOutcome[pos] = label[0]
		labeledPos[sceneID] = pos
	}

	// Column lists over labeled rows only: a target's key with no labeled
	// co-occurrence contributes nothing (numpy drops it via the column filter).
	colLists := make([][]colEntry, len(allNames))
	for pos, sceneID := range labeledIDs {
		row := sparseFromMap(preference[sceneID], nameIndex)
		for k, key := range row.keys {
			colLists[key] = append(colLists[key], colEntry{pos: pos, v: row.values[k]})
		}
	}

	n := len(sceneOrder)
	targetRows := make([]sparseRow, n)
	ownPos := make([]int, n)
	for i, sceneID := range sceneOrder {
		targetRows[i] = sparseFromMap(preference[sceneID], nameIndex)
		own, ok := labeledPos[sceneID]
		if !ok {
			own = -1
		}
		ownPos[i] = own
	}
	neighbors := contentKernel(targetRows, ownPos, colLists, labeledConf, labeledIDs,
		payload.Config, payload.ProgressTotal, nthreads(payload.Threads))

	result := make(map[string]any, n)
	for i, sceneID := range sceneOrder {
		entries := make([][]any, 0, len(neighbors[i]))
		for _, nb := range neighbors[i] {
			entries = append(entries, []any{
				nb.id,
				nb.s,
				nb.w,
				labeledOutcome[labeledPos[nb.id]],
			})
		}
		result[sceneID] = map[string]any{"neighbors": entries}
	}
	return result, nil
}

type colEntry struct {
	pos int
	v   float64
}

type sparseRow struct {
	keys   []int
	values []float64
}

func sparseFromMap(vector map[string]float64, nameIndex map[string]int) sparseRow {
	names := make([]string, 0, len(vector))
	for name := range vector {
		names = append(names, name)
	}
	sort.Strings(names)
	keys := make([]int, len(names))
	values := make([]float64, len(names))
	for i, name := range names {
		keys[i] = nameIndex[name]
		values[i] = vector[name]
	}
	return sparseRow{keys: keys, values: values}
}

// reportPoints lists the progress indices numpy reports: every 250th row and the
// final row (deduplicated when n is a multiple of 250).
func reportPoints(n int) []int {
	points := make([]int, 0, n/250+1)
	for p := 250; p < n; p += 250 {
		points = append(points, p)
	}
	return append(points, n)
}

// contentKernel is the fused sparse kernel: sim and shared accumulate in one
// pass over (row non-zeros x column non-zeros), streaming top-k per row with
// deterministic fixed chunking across goroutines. Progress lines are emitted in
// strict row order regardless of worker interleaving.
func contentKernel(
	targetRows []sparseRow,
	ownPos []int,
	colLists [][]colEntry,
	labeledConf []float64,
	labeledIDs []string,
	cfg contentConfig,
	progressTotal int,
	threads int,
) [][]contentNeighbor {
	n := len(targetRows)
	if n == 0 {
		return nil
	}
	results := make([][]contentNeighbor, n)
	if threads > n {
		threads = n
	}
	chunk := (n + threads - 1) / threads

	var mu sync.Mutex
	completed := 0
	cond := sync.NewCond(&mu)
	reporterDone := make(chan struct{})
	go func() {
		defer close(reporterDone)
		for _, point := range reportPoints(n) {
			mu.Lock()
			for completed < point {
				cond.Wait()
			}
			mu.Unlock()
			fraction := float64(point) / float64(max(1, progressTotal))
			_ = writeJSONLine(map[string]any{"progress": fraction})
		}
	}()

	var wg sync.WaitGroup
	for w := 0; w < threads; w++ {
		start := w * chunk
		end := min(start+chunk, n)
		if start >= end {
			continue
		}
		wg.Add(1)
		go func(start, end int) {
			defer wg.Done()
			sims := make([]float64, len(labeledConf))
			shared := make([]int32, len(labeledConf))
			stamps := make([]int32, len(labeledConf))
			stamp := int32(0)
			for i := start; i < end; i++ {
				stamp++
				row := targetRows[i]
				own := ownPos[i]
				// Accumulate sim and shared for all labeled j reachable from the
				// row's keys.
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
				sel := &neighborHeap{}
				for pos := range labeledConf {
					if stamps[pos] != stamp || pos == own {
						continue
					}
					s := sims[pos] * (1 - math.Exp(-float64(shared[pos])/4.0))
					if s < cfg.MinSimilarity {
						continue
					}
					w := s * s * s * labeledConf[pos]
					if sel.Len() < cfg.NeighborCount {
						heap.Push(sel, contentNeighbor{id: labeledIDs[pos], s: s, w: w})
					} else if w > sel.Peek().w || (w == sel.Peek().w && labeledIDs[pos] < sel.Peek().id) {
						heap.Pop(sel)
						heap.Push(sel, contentNeighbor{id: labeledIDs[pos], s: s, w: w})
					}
				}
				out := make([]contentNeighbor, 0, sel.Len())
				for sel.Len() > 0 {
					out = append(out, heap.Pop(sel).(contentNeighbor))
				}
				// heap.Pop yields worst-first; reverse to (-w, id) order.
				for l, r := 0, len(out)-1; l < r; l, r = l+1, r-1 {
					out[l], out[r] = out[r], out[l]
				}
				results[i] = out
				mu.Lock()
				completed++
				cond.Signal()
				mu.Unlock()
			}
		}(start, end)
	}
	wg.Wait()
	<-reporterDone
	return results
}
