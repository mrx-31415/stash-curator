package main

import (
	"math"
	"testing"
)

func TestPerformerEstimateCertainty(t *testing.T) {
	profiles := map[string]*performerProfile{}
	ids := []string{"target", "a", "b", "c", "d", "e"}
	for _, id := range ids {
		profiles[id] = &performerProfile{id: id,
			blocks:      map[string]map[string]profileValue{"hair": {"brown": {value: 1, confidence: 1}}},
			norms:       map[string]float64{"hair": 1},
			sortedBlock: map[string][]profileBlockEntry{"hair": {{key: "brown", value: profileValue{value: 1, confidence: 1}}}},
		}
	}
	payload := performerPayload{BlockWeights: map[string]float64{"hair": 1}, IdentityAffinity: map[string][]float64{}}
	for _, id := range ids[1:] {
		payload.IdentityAffinity[id] = []float64{0.5, 0.75}
	}
	estimate := func(known []string) performerResult {
		return performerForProfile(payload, profiles, ids, known, []string{"hair"}, 0, map[string]bool{})
	}
	one, many := estimate(ids[1:2]), estimate(ids[1:])
	if !(one.confidence > 0 && many.confidence > one.confidence && many.confidence <= 0.65) {
		t.Fatalf("certainty does not grow conservatively: one=%g many=%g", one.confidence, many.confidence)
	}
	payload.IdentityAffinity["b"] = []float64{-0.5, 0.75}
	conflict := estimate(ids[1:3])
	if math.Abs(conflict.value) > 1e-12 || conflict.confidence > 1e-12 {
		t.Fatalf("conflicting matches must cancel certainty: %+v", conflict)
	}
	profiles["a"].blocks["hair"]["brown"] = profileValue{value: 1, confidence: 0.2}
	profiles["a"].sortedBlock["hair"][0].value.confidence = 0.2
	weak := estimate(ids[1:2])
	if weak.confidence >= one.confidence {
		t.Fatalf("weak metadata must reduce certainty: weak=%g strong=%g", weak.confidence, one.confidence)
	}
	if empty := estimate(nil); empty.value != 0 || empty.confidence != 0 {
		t.Fatalf("missing evidence must stay unknown: %+v", empty)
	}
}

func TestPerformerPreferenceCombinesEvidence(t *testing.T) {
	estimate := modelPrior{value: 0.5, confidence: 0.6}
	inferred := performerPreference(0, 0, false, modelPrior{}, estimate)
	if math.Abs(numberValue(inferred.get("affinity"))-0.3) > 1e-12 || numberValue(inferred.get("confidence")) != 0.6 {
		t.Fatalf("missing direct evidence must use the conservative estimate: %s", inferred.marshalCompact())
	}
	direct := performerPreference(0.8, 0.9, true, modelPrior{}, estimate)
	if math.Abs(numberValue(direct.get("affinity"))-0.75) > 1e-12 || math.Abs(numberValue(direct.get("confidence"))-0.96) > 1e-12 {
		t.Fatalf("agreeing estimates must strengthen direct evidence: %s", direct.marshalCompact())
	}
	conflict := performerPreference(-0.8, 0.9, true, modelPrior{}, estimate)
	if numberValue(conflict.get("confidence")) != 0.9 {
		t.Fatal("conflicting inference must not increase direct certainty")
	}
	if absent := performerPreference(0, 0, false, modelPrior{}, modelPrior{}); absent.get("affinity").kind != jNull {
		t.Fatal("no evidence must remain unknown")
	}
	if uncertain := performerPreference(0, 0, true, modelPrior{}, modelPrior{}); uncertain.get("affinity").kind == jNull || numberValue(uncertain.get("confidence")) != 0 {
		t.Fatal("conflicting evidence must show an uncertain neutral estimate")
	}
}

func TestPerformerSimilarityWithMissingFields(t *testing.T) {
	profile := func(id, piercing string) *performerProfile {
		p := &performerProfile{id: id,
			blocks:      map[string]map[string]profileValue{"hair": {"brown": {value: 1, confidence: 1}}},
			norms:       map[string]float64{"hair": 1},
			sortedBlock: map[string][]profileBlockEntry{"hair": {{key: "brown", value: profileValue{value: 1, confidence: 1}}}},
		}
		if piercing != "" {
			ordinal := 0
			if piercing == "present" {
				ordinal = 1
			}
			p.blocks["piercings"] = map[string]profileValue{piercing: {value: 1, confidence: 1}}
			p.norms["piercings"] = 1
			p.sortedBlock["piercings"] = []profileBlockEntry{{key: piercing, ordinal: ordinal, value: profileValue{value: 1, confidence: 1}}}
		}
		return p
	}
	weights := map[string]float64{"hair": 1, "piercings": 1}
	for _, tc := range []struct {
		name, left, right string
		want              float64
	}{
		{"missing target field", "", "present", 1},
		{"missing seed field", "present", "", 1},
		{"missing on both", "", "", 1},
		{"explicit difference", "absent", "present", 0.5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			left, right := profile("target", tc.left), profile("seed", tc.right)
			value, _ := performerPair(left, right, []string{"hair", "piercings"}, weights, nil, nil, true)
			if math.IsNaN(value) || math.Abs(value-tc.want) > 1e-12 {
				t.Fatalf("similarity=%g, want %g", value, tc.want)
			}
			payload := performerPayload{BlockWeights: weights, IdentityAffinity: map[string][]float64{"seed": {0.5, 0.75}}}
			result := performerForProfile(payload, map[string]*performerProfile{"target": left, "seed": right},
				[]string{"target"}, []string{"seed"}, []string{"hair", "piercings"}, 0, nil)
			if result.confidence <= 0 || len(result.matches) != 1 {
				t.Fatal("available shared evidence must produce an estimate")
			}
		})
	}
	left, right := profile("target", ""), profile("seed", "")
	value, _ := performerPair(left, right, []string{"piercings"}, weights, nil, nil, false)
	if value != 0 {
		t.Fatal("no usable shared fields must produce no match")
	}
}
