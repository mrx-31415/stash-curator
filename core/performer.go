package main

// Performer-similarity stage. Mirrors
// PreferenceModelBuilder._performer_similarity_scores_numpy
// (curator/model/builder.py): profiles are read from the feature artifact, then
// every profile is compared against the known-affinity set (|affinity| >=
// cutoff) with weighted block similarities, a cup/measurements penalty, and an
// augmentation penalty. The result shape is the production dict:
//
//	{performer_id: {value, confidence, matches: [{performer_id, similarity,
//	  affinity, confidence, blocks: {block: value}}]}}
//
// Blocks iterate in sorted order and shared keys in sorted order, matching the
// numpy column construction; each (profile, known) pair is independent, so the
// output is identical across goroutine counts.

import (
	"database/sql"
	"encoding/json"
	"math"
	"os"
	"sort"
	"strings"
	"sync"
)

type performerPayload struct {
	DB               string               `json:"db"`
	FeatureVersion   string               `json:"feature_version"`
	IdentityAffinity map[string][]float64 `json:"identity_affinity"`
	BlockWeights     map[string]float64   `json:"block_weights"`
	Cutoff           float64              `json:"cutoff"`
	NumericBlocks    []string             `json:"numeric_blocks"`
	NumericScales    map[string]float64   `json:"numeric_scales"`
	Threads          int                  `json:"threads,omitempty"`
	Profile          bool                 `json:"profile,omitempty"`
}

type profileValue struct {
	value      float64
	confidence float64
}

type performerProfile struct {
	id         string
	blocks     map[string]map[string]profileValue
	norms      map[string]float64
	sortedKeys map[string][]string
	// keys holds each block's name set; populated by the query-time
	// similarity path (readProfiles leaves it nil).
	keys map[string]map[string]bool
}

func readProfiles(db *sql.DB, featureVersion string, numeric map[string]bool) (map[string]*performerProfile, error) {
	rows, err := db.Query(`
		SELECT ef.entity_id, fd.family, fd.name, ef.value, ef.confidence
		FROM entity_feature ef
		JOIN feature_definition fd ON fd.feature_id = ef.feature_id
		WHERE ef.feature_version = ? AND ef.entity_type = 'performer' AND fd.family LIKE 'profile:%'
		ORDER BY ef.entity_id, ef.feature_id`, featureVersion)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	profiles := make(map[string]*performerProfile)
	for rows.Next() {
		var entity, family, name string
		var value, confidence float64
		if err := rows.Scan(&entity, &family, &name, &value, &confidence); err != nil {
			return nil, err
		}
		profile := profiles[entity]
		if profile == nil {
			profile = &performerProfile{id: entity, blocks: make(map[string]map[string]profileValue)}
			profiles[entity] = profile
		}
		block := strings.TrimPrefix(family, "profile:")
		if profile.blocks[block] == nil {
			profile.blocks[block] = make(map[string]profileValue)
		}
		profile.blocks[block][name] = profileValue{value: value, confidence: confidence}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, profile := range profiles {
		profile.norms = make(map[string]float64, len(profile.blocks))
		profile.sortedKeys = make(map[string][]string, len(profile.blocks))
		for block, values := range profile.blocks {
			keys := make([]string, 0, len(values))
			for key := range values {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			profile.sortedKeys[block] = keys
			if numeric[block] {
				continue
			}
			var sumSquares float64
			for _, key := range keys {
				sumSquares += values[key].value * values[key].value
			}
			profile.norms[block] = math.Sqrt(sumSquares)
		}
	}
	return profiles, nil
}

func cacheProfileKeys(profile *performerProfile) {
	if profile.sortedKeys != nil {
		return
	}
	profile.sortedKeys = make(map[string][]string, len(profile.blocks))
	for block, values := range profile.blocks {
		keys := make([]string, 0, len(values))
		for key := range values {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		profile.sortedKeys[block] = keys
	}
}

// performerMatch is one entry of the production "matches" list (top-3).
type performerMatch struct {
	id         string
	similarity float64
	affinity   float64
	confidence float64
	blocks     map[string]float64
}

type performerResult struct {
	value      float64
	confidence float64
	matches    []performerMatch
}

// sortedSharedKeys returns the keys present in both blocks, sorted (numpy
// iterates the dense matrix columns in sorted key order).
func sortedSharedKeys(left, right map[string]profileValue) []string {
	keys := make([]string, 0)
	for key := range left {
		if _, ok := right[key]; ok {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys
}

func sharedProfileKeys(left, right *performerProfile, block string,
	leftValues, rightValues map[string]profileValue) []string {
	leftKeys, leftOK := left.sortedKeys[block]
	rightKeys, rightOK := right.sortedKeys[block]
	if !leftOK || !rightOK {
		return sortedSharedKeys(leftValues, rightValues)
	}
	keys := make([]string, 0, min(len(leftKeys), len(rightKeys)))
	for i, j := 0, 0; i < len(leftKeys) && j < len(rightKeys); {
		if leftKeys[i] < rightKeys[j] {
			i++
		} else if leftKeys[i] > rightKeys[j] {
			j++
		} else {
			keys = append(keys, leftKeys[i])
			i++
			j++
		}
	}
	return keys
}

func runPerformerSimilarity() {
	var payload performerPayload
	if err := json.NewDecoder(os.Stdin).Decode(&payload); err != nil {
		fail("performer-similarity: invalid payload: %v", err)
	}
	profile := newProfileRecorder(payload.Profile)
	db, err := openReadonly(payload.DB)
	if err != nil {
		fail("performer-similarity: open %s: %v", payload.DB, err)
	}
	defer db.Close()
	numeric := make(map[string]bool, len(payload.NumericBlocks))
	for _, block := range payload.NumericBlocks {
		numeric[block] = true
	}
	end := profile.begin("core.read_profiles")
	profiles, err := readProfiles(db, payload.FeatureVersion, numeric)
	end()
	if err != nil {
		fail("performer-similarity: read profiles: %v", err)
	}
	end = profile.begin("core.kernel")
	result := performerSimilarityScores(payload, profiles, numeric)
	end()
	end = profile.begin("core.encode_result")
	profile.emit()
	if err := writeJSONLine(map[string]any{"result": result}); err != nil {
		fail("performer-similarity: write result: %v", err)
	}
	end()
}

func performerSimilarityScores(
	payload performerPayload,
	profiles map[string]*performerProfile,
	numeric map[string]bool,
) map[string]any {
	for _, profile := range profiles {
		cacheProfileKeys(profile)
	}
	profileIDs := make([]string, 0, len(profiles))
	for id := range profiles {
		profileIDs = append(profileIDs, id)
	}
	sort.Strings(profileIDs)

	knownIDs := make([]string, 0)
	for id, affinity := range payload.IdentityAffinity {
		if _, ok := profiles[id]; ok && math.Abs(affinity[0]) >= payload.Cutoff {
			knownIDs = append(knownIDs, id)
		}
	}
	sort.Strings(knownIDs)

	results := make([]performerResult, len(profileIDs))
	if len(knownIDs) == 0 {
		for i := range results {
			results[i] = performerResult{value: 0.0, confidence: 0.0, matches: []performerMatch{}}
		}
	} else {
		globalBlockSet := make(map[string]bool)
		for _, profile := range profiles {
			for block := range profile.blocks {
				globalBlockSet[block] = true
			}
		}
		globalBlocks := make([]string, 0, len(globalBlockSet))
		for block := range globalBlockSet {
			globalBlocks = append(globalBlocks, block)
		}
		sort.Strings(globalBlocks)
		threads := nthreads(payload.Threads)
		if threads > len(profileIDs) {
			threads = len(profileIDs)
		}
		chunk := (len(profileIDs) + threads - 1) / threads
		var wg sync.WaitGroup
		for w := 0; w < threads; w++ {
			start := w * chunk
			end := min(start+chunk, len(profileIDs))
			if start >= end {
				continue
			}
			wg.Add(1)
			go func(start, end int) {
				defer wg.Done()
				for i := start; i < end; i++ {
					results[i] = performerForProfile(payload, profiles, profileIDs, knownIDs, globalBlocks, i, numeric)
				}
			}(start, end)
		}
		wg.Wait()
	}

	out := make(map[string]any, len(profileIDs))
	for i, id := range profileIDs {
		r := results[i]
		matches := make([]any, 0, len(r.matches))
		for _, m := range r.matches {
			matches = append(matches, map[string]any{
				"performer_id": m.id,
				"similarity":   m.similarity,
				"affinity":     m.affinity,
				"confidence":   m.confidence,
				"blocks":       m.blocks,
			})
		}
		out[id] = map[string]any{
			"value":      r.value,
			"confidence": r.confidence,
			"matches":    matches,
		}
	}
	return out
}

// performerPair computes the weighted block similarity plus penalties for one
// (profile, known) pair, mirroring the numpy per-block matrix math.
//
// numpy densifies every block over the GLOBAL block set (all blocks any profile
// has) and multiplies block_value * block_used per cell; a cosine block whose
// norm is zero on either side yields 0/0 = NaN, and NaN * False keeps the
// numerator NaN for the pair even though the block is unused. The pair is then
// excluded from candidates. Mirror that exactly: any weight>0 cosine block with
// a zero norm on either profile poisons the pair's similarity.
func performerPair(
	left, right *performerProfile,
	globalBlocks []string,
	weights, scales map[string]float64,
	numeric map[string]bool,
) (similarity float64, blocks map[string]float64) {
	blocks = make(map[string]float64)
	var numerator, denominator float64
	cosineZero := false
	for _, block := range globalBlocks {
		weight := weights[block]
		if weight <= 0 {
			continue
		}
		leftValues, leftOK := left.blocks[block]
		rightValues, rightOK := right.blocks[block]
		var blockValue float64
		used := false
		if numeric[block] {
			if !leftOK || !rightOK {
				continue
			}
			keys := sharedProfileKeys(left, right, block, leftValues, rightValues)
			var total float64
			count := 0
			for _, key := range keys {
				lv := leftValues[key]
				rv := rightValues[key]
				if lv.value == 0 || rv.value == 0 {
					continue
				}
				scale := scales[key]
				if scale == 0 {
					scale = 1.0
				}
				total += math.Exp(-math.Abs(lv.value-rv.value)/scale) * min(lv.confidence, rv.confidence)
				count++
			}
			if count > 0 {
				blockValue = total / float64(count)
				used = true
			}
		} else {
			normLeft := left.norms[block]
			normRight := right.norms[block]
			if normLeft == 0 || normRight == 0 {
				// numpy: dot/(norms*known_norms) over the dense matrix is 0/0,
				// and the masked multiply keeps the NaN in the numerator.
				cosineZero = true
				continue
			}
			keys := sharedProfileKeys(left, right, block, leftValues, rightValues)
			var dot, confidenceSum float64
			count := 0
			for _, key := range keys {
				lv := leftValues[key]
				rv := rightValues[key]
				if lv.value == 0 || rv.value == 0 {
					continue
				}
				dot += lv.value * rv.value
				confidenceSum += min(lv.confidence, rv.confidence)
				count++
			}
			used = true
			confidence := 0.0
			if count > 0 {
				confidence = confidenceSum / float64(count)
			}
			blockValue = dot / (normLeft * normRight) * confidence
			if blockValue > 1 {
				blockValue = 1
			} else if blockValue < 0 {
				blockValue = 0
			}
		}
		if used {
			denominator += weight
			numerator += blockValue * weight
			blocks[block] = blockValue
		}
	}
	if denominator <= 0 {
		return 0.0, blocks
	}
	if cosineZero {
		// numpy: where(denominator > 0, numerator/denominator*penalty, 0)
		// yields NaN, which never passes the similarity > 0 candidate filter.
		return math.NaN(), blocks
	}
	penalty := 1.0
	if measurementsLeft, ok := left.blocks["measurements"]; ok {
		if measurementsRight, ok := right.blocks["measurements"]; ok {
			cupLeft, okLeft := measurementsLeft["cup_index"]
			cupRight, okRight := measurementsRight["cup_index"]
			if okLeft && okRight && cupLeft.value != 0 && cupRight.value != 0 {
				penalty *= math.Exp(-0.18 * math.Max(0.0, math.Abs(cupLeft.value-cupRight.value)-1.0))
			}
		}
	}
	if augmentationLeft, ok := left.blocks["augmentation"]; ok {
		if augmentationRight, ok := right.blocks["augmentation"]; ok {
			anyLeft, anyRight := false, false
			for _, v := range augmentationLeft {
				if v.value != 0 {
					anyLeft = true
					break
				}
			}
			for _, v := range augmentationRight {
				if v.value != 0 {
					anyRight = true
					break
				}
			}
			if anyLeft && anyRight {
				shared := 0
				for key, lv := range augmentationLeft {
					if lv.value == 0 {
						continue
					}
					if rv, ok := augmentationRight[key]; ok && rv.value != 0 {
						shared++
					}
				}
				if shared == 0 {
					penalty *= 0.65
				}
			}
		}
	}
	return numerator / denominator * penalty, blocks
}

// performerForProfile selects the top-5 known matches for one profile and
// aggregates value/confidence, mirroring the numpy per-row loop.
func performerForProfile(
	payload performerPayload,
	profiles map[string]*performerProfile,
	profileIDs []string,
	knownIDs []string,
	globalBlocks []string,
	index int,
	numeric map[string]bool,
) performerResult {
	profile := profiles[profileIDs[index]]
	type candidate struct {
		id         string
		similarity float64
		affinity   float64
		confidence float64
		blocks     map[string]float64
	}
	candidates := make([]candidate, 0, len(knownIDs))
	for _, knownID := range knownIDs {
		if knownID == profile.id {
			continue
		}
		similarity, blocks := performerPair(profile, profiles[knownID], globalBlocks, payload.BlockWeights, payload.NumericScales, numeric)
		if math.IsNaN(similarity) || similarity <= 0 {
			continue
		}
		affinity := payload.IdentityAffinity[knownID]
		candidates = append(candidates, candidate{
			id:         knownID,
			similarity: similarity,
			affinity:   affinity[0],
			confidence: affinity[1],
			blocks:     blocks,
		})
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].similarity != candidates[j].similarity {
			return candidates[i].similarity > candidates[j].similarity
		}
		return candidates[i].id < candidates[j].id
	})
	if len(candidates) > 5 {
		candidates = candidates[:5]
	}
	var denominator float64
	for _, c := range candidates {
		denominator += c.similarity * c.similarity * c.similarity
	}
	value, confidence := 0.0, 0.0
	if denominator > 0 {
		for _, c := range candidates {
			weight := c.similarity * c.similarity * c.similarity
			value += c.affinity * weight
			confidence += c.confidence * weight
		}
		value /= denominator
		confidence /= denominator
	}
	kept := min(3, len(candidates))
	matches := make([]performerMatch, 0, kept)
	for _, c := range candidates[:kept] {
		matches = append(matches, performerMatch{
			id:         c.id,
			similarity: c.similarity,
			affinity:   c.affinity,
			confidence: c.confidence,
			blocks:     c.blocks,
		})
	}
	return performerResult{value: value, confidence: confidence, matches: matches}
}
