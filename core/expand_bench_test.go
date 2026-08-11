package main

import (
	"fmt"
	"math"
	"testing"
)

// Benchmark helper: build a realistic anchor profile (standard blocks + a
// ~1230-key content block, as on the live library).
func benchAnchorProfile(id string, contentKeys int) *performerProfile {
	blocks := map[string]map[string]profileValue{}
	keys := map[string]map[string]bool{}
	blocks["content"] = map[string]profileValue{}
	keys["content"] = map[string]bool{}
	for i := 0; i < contentKeys; i++ {
		name := fmt.Sprintf("c%d", i)
		blocks["content"][name] = profileValue{value: float64(i%100) / 50, confidence: 1.0}
		keys["content"][name] = true
	}
	blocks["ethnicity"] = map[string]profileValue{"Caucasian": {value: 1, confidence: 0.8}}
	keys["ethnicity"] = map[string]bool{"Caucasian": true}
	blocks["hair"] = map[string]profileValue{"Black": {value: 1, confidence: 0.45}}
	keys["hair"] = map[string]bool{"Black": true}
	blocks["eyes"] = map[string]profileValue{"Blue": {value: 1, confidence: 0.1}}
	keys["eyes"] = map[string]bool{"Blue": true}
	blocks["measurements"] = map[string]profileValue{
		"band_inches": {value: 34, confidence: 1}, "waist_inches": {value: 24, confidence: 1},
		"hip_inches": {value: 36, confidence: 1}, "cup_index": {value: 4, confidence: 1},
	}
	keys["measurements"] = map[string]bool{"band_inches": true, "waist_inches": true, "hip_inches": true, "cup_index": true}
	blocks["height"] = map[string]profileValue{"height_cm": {value: 170, confidence: 1}}
	keys["height"] = map[string]bool{"height_cm": true}
	blocks["age"] = map[string]profileValue{"age_recording": {value: 33.5, confidence: 0.9}}
	keys["age"] = map[string]bool{"age_recording": true}
	blocks["augmentation"] = map[string]profileValue{"natural": {value: 1, confidence: 1}}
	keys["augmentation"] = map[string]bool{"natural": true}
	blocks["tattoos"] = map[string]profileValue{"present": {value: 1, confidence: 0.8}}
	keys["tattoos"] = map[string]bool{"present": true}
	blocks["piercings"] = map[string]profileValue{"present": {value: 1, confidence: 0.8}}
	keys["piercings"] = map[string]bool{"present": true}
	p := &performerProfile{id: id, blocks: blocks, norms: map[string]float64{}, keys: keys}
	finalizeProfileNorms(p)
	return p
}

func benchExternalPerformer(id string) jVal {
	items := []jPair{
		{"id", jvStr(id)},
		{"gender", jvStr("FEMALE")},
		{"ethnicity", jvStr("Caucasian")},
		{"hair_color", jvStr("Brown")},
		{"eye_color", jvStr("Hazel")},
		{"height", jvStr("168")},
		{"band_size", jvStr("34")},
		{"waist_size", jvStr("25")},
		{"hip_size", jvStr("36")},
		{"cup_size", jvStr("D")},
		{"breast_type", jvStr("natural")},
		{"birth_date", jvStr("1992-03-15")},
	}
	return jVal{kind: jObj, obj: items}
}

func BenchmarkComputeTerms(b *testing.B) {
	anchors := make([]anchorPair, 0, 454)
	for i := 0; i < 454; i++ {
		anchors = append(anchors, anchorPair{
			profile:  benchAnchorProfile(fmt.Sprintf("a%d", i), 1230),
			evidence: &performerEvidence{name: fmt.Sprintf("Anchor %d", i), strength: 0.8},
		})
	}
	m := newAnchorMatcher(anchors, performerBlockWeightsMap())
	b.ResetTimer()
	perf := benchExternalPerformer("ext")
	for i := 0; i < b.N; i++ {
		m.computeTerms(perf)
	}
}

func BenchmarkBest(b *testing.B) {
	anchors := make([]anchorPair, 0, 454)
	for i := 0; i < 454; i++ {
		anchors = append(anchors, anchorPair{
			profile:  benchAnchorProfile(fmt.Sprintf("a%d", i), 1230),
			evidence: &performerEvidence{name: fmt.Sprintf("Anchor %d", i), strength: 0.8},
		})
	}
	m := newAnchorMatcher(anchors, performerBlockWeightsMap())
	perf := benchExternalPerformer("ext")
	m.computeTerms(perf)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		m.best(perf, jvStr("2024-03-15"))
	}
}

func BenchmarkPyExpLocked(b *testing.B) {
	for i := 0; i < b.N; i++ {
		math.Exp(-0.5 - float64(i%97)*0.001)
	}
}

func TestBenchHelpersCompile(t *testing.T) {
	_ = math.Min
	p := benchAnchorProfile("x", 10)
	if len(p.blocks["content"]) != 10 {
		t.Fatalf("content block size %d", len(p.blocks["content"]))
	}
}
