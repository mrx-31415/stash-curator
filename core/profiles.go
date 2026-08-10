// Performer profile similarity — a port of curator/features/profiles.py.
//
// Block math mirrors the Python exactly: numeric blocks (measurements,
// height, age) accumulate over SORTED shared keys; cosine blocks accumulate
// over set-intersection order, which in CPython is hash order. For the
// shipped feature builder every cosine block carries at most one value, so
// the accumulation order is deterministic in practice; the differential
// harness covers this.
package main

import (
	"math"
	"sort"
)

// numericScales mirrors profiles.NUMERIC_SCALES.
var numericScales = map[string]float64{
	"height_cm":       12.0,
	"weight_kg":       15.0,
	"band_inches":     6.0,
	"cup_index":       2.0,
	"waist_inches":    7.0,
	"hip_inches":      8.0,
	"waist_to_hip":    0.12,
	"waist_to_height": 0.10,
	"hip_to_height":   0.12,
	"age_recording":   8.0,
}

// numericBlocks mirrors profiles.NUMERIC_BLOCKS.
var numericBlocks = map[string]bool{"measurements": true, "height": true, "age": true}

// performerBlockWeights mirrors FeatureConfig.performer_block_weights in
// tuple order (dict(block_weights) preserves it).
var performerBlockWeights = []struct {
	block  string
	weight float64
}{
	{"content", 1.0},
	{"measurements", 1.0},
	{"augmentation", 0.9},
	{"ethnicity", 0.8},
	{"height", 0.7},
	{"age", 0.6},
	{"hair", 0.45},
	{"tattoos", 0.35},
	{"piercings", 0.25},
	{"eyes", 0.1},
}

// blockSimilarity mirrors profiles.block_similarity.
func blockSimilarity(left, right *performerProfile, block string) (float64, bool) {
	leftBlock, leftOK := left.blocks[block]
	rightBlock, rightOK := right.blocks[block]
	if !leftOK || !rightOK {
		return 0, false
	}
	if numericBlocks[block] {
		return numericSimilarity(leftBlock, rightBlock, left.keys[block], right.keys[block])
	}
	return cosineSimilarity(leftBlock, rightBlock, left.norms[block], right.norms[block], left.keys[block], right.keys[block])
}

// numericSimilarity mirrors profiles._numeric: shared keys sorted, mean of
// exp(-|diff|/scale) * min confidence.
func numericSimilarity(left, right map[string]profileValue, leftKeys, rightKeys map[string]bool) (float64, bool) {
	shared := intersectKeys(leftKeys, rightKeys)
	if len(shared) == 0 {
		return 0, false
	}
	sort.Strings(shared)
	sum := 0.0
	for _, key := range shared {
		scale := numericScales[key]
		if scale == 0 {
			scale = 1.0
		}
		leftValue := left[key]
		rightValue := right[key]
		closeness := pyExp(-math.Abs(leftValue.value-rightValue.value) / scale)
		confidence := leftValue.confidence
		if rightValue.confidence < confidence {
			confidence = rightValue.confidence
		}
		sum += closeness * confidence
	}
	return sum / float64(len(shared)), true
}

// cosineSimilarity mirrors profiles._cosine: dot over shared keys, scaled by
// the mean pairwise-min confidence, clamped to [0, 1].
func cosineSimilarity(left, right map[string]profileValue, leftNorm, rightNorm float64, leftKeys, rightKeys map[string]bool) (float64, bool) {
	shared := intersectKeys(leftKeys, rightKeys)
	if len(shared) == 0 {
		return 0.0, true
	}
	dot := 0.0
	confidenceSum := 0.0
	for _, key := range shared {
		leftValue := left[key]
		rightValue := right[key]
		dot += leftValue.value * rightValue.value
		confidence := leftValue.confidence
		if rightValue.confidence < confidence {
			confidence = rightValue.confidence
		}
		confidenceSum += confidence
	}
	if leftNorm == 0 || rightNorm == 0 {
		return 0, false
	}
	confidence := confidenceSum / float64(len(shared))
	value := dot / (leftNorm * rightNorm) * confidence
	if value < 0 {
		value = 0
	}
	if value > 1 {
		value = 1
	}
	return value, true
}

// intersectKeys returns the keys present in both sets. Iteration order only
// matters for the cosine accumulation, and the shipped cosine blocks hold at
// most one shared key, so order is deterministic in practice.
func intersectKeys(left, right map[string]bool) []string {
	if len(left) > len(right) {
		left, right = right, left
	}
	shared := make([]string, 0, len(left))
	for key := range left {
		if right[key] {
			shared = append(shared, key)
		}
	}
	return shared
}

// similarityPenalty mirrors profiles.similarity_penalty.
func similarityPenalty(left, right *performerProfile) float64 {
	penalty := 1.0
	leftCup, leftOK := profileValueAt(left, "measurements", "cup_index")
	rightCup, rightOK := profileValueAt(right, "measurements", "cup_index")
	if leftOK && rightOK {
		penalty *= pyExp(-0.18 * mathMax(0.0, math.Abs(leftCup.value-rightCup.value)-1))
	}
	leftAug, leftOK := left.blocks["augmentation"]
	rightAug, rightOK := right.blocks["augmentation"]
	if leftOK && rightOK && len(leftAug) > 0 && len(rightAug) > 0 && !keysOverlap(leftAug, rightAug) {
		penalty *= 0.65
	}
	return penalty
}

func profileValueAt(p *performerProfile, block, key string) (profileValue, bool) {
	values, ok := p.blocks[block]
	if !ok {
		return profileValue{}, false
	}
	v, ok := values[key]
	return v, ok
}

func keysOverlap(a, b map[string]profileValue) bool {
	for key := range a {
		if _, ok := b[key]; ok {
			return true
		}
	}
	return false
}

// blockSimilaritiesAll mirrors profiles.block_similarities: per-block
// similarities and the weights they were measured with, over the sorted
// shared blocks (the Python dict insertion order), plus the ordered block
// names and weights for deterministic accumulation.
func blockSimilaritiesAll(left, right *performerProfile, blockWeights map[string]float64) (map[string]float64, map[string]float64, []string, []float64) {
	blocks := make([]string, 0)
	for block := range left.blocks {
		if _, ok := right.blocks[block]; ok {
			blocks = append(blocks, block)
		}
	}
	sort.Strings(blocks)
	similarities := make(map[string]float64)
	usedWeights := make(map[string]float64)
	var ordered []string
	var weights []float64
	for _, block := range blocks {
		weight := blockWeights[block]
		if weight <= 0 {
			continue
		}
		similarity, ok := blockSimilarity(left, right, block)
		if !ok {
			continue
		}
		similarities[block] = similarity
		usedWeights[block] = weight
		ordered = append(ordered, block)
		weights = append(weights, weight)
	}
	return similarities, usedWeights, ordered, weights
}

// performerSimilarity mirrors profiles.performer_similarity; returns the
// combined similarity plus the per-block similarities and used weights.
func performerSimilarity(left, right *performerProfile, blockWeights map[string]float64) (float64, map[string]float64, map[string]float64) {
	similarities, usedWeights, ordered, weights := blockSimilaritiesAll(left, right, blockWeights)
	denominator := neumaierSum(weights)
	total := 0.0
	if denominator > 0 {
		products := make([]float64, 0, len(ordered))
		for _, block := range ordered {
			products = append(products, similarities[block]*usedWeights[block])
		}
		total = neumaierSum(products) / denominator
	}
	return total * similarityPenalty(left, right), similarities, usedWeights
}

// performerBlockWeightsMap mirrors DEFAULT_CONFIG.feature.performer_block_weights
// as a lookup map.
func performerBlockWeightsMap() map[string]float64 {
	weights := map[string]float64{}
	for _, entry := range performerBlockWeights {
		weights[entry.block] = entry.weight
	}
	return weights
}
