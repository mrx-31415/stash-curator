package main

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// Find and the performer inspector load the other profiles trimmed to what
// the target shares; every similarity, block score and weight must match
// the full profiles. Values are dyadic so norms sum exactly in any order.
func TestProfilesComparedToMatchFullProfiles(t *testing.T) {
	const version = "fv-compare"
	row := func(id, block, name string, value, confidence float64) featureRow {
		return featureRow{entityType: "performer", entityID: id, family: "profile:" + block, name: name, value: value, confidence: confidence}
	}
	features := []featureRow{
		row("t", "content", "tag:1", 0.5, 1), row("t", "content", "tag:2", 0.25, 0.5), row("t", "content", "tag:3", -0.5, 1),
		row("t", "augmentation", "augmentation:natural", 1, 1),
		row("t", "measurements", "cup_index", 3, 1), row("t", "measurements", "band_inches", 34, 0.5),
		row("t", "hair", "hair:blonde", 1, 0.75), row("t", "eyes", "eyes:blue", 0, 1),
		// a: partial content overlap, an augmentation set that shares nothing
		// (the penalty must still apply), a cosine block with no shared key.
		row("a", "content", "tag:1", 0.75, 1), row("a", "content", "tag:4", 0.5, 1), row("a", "content", "tag:5", 0.25, 0.5),
		row("a", "augmentation", "augmentation:enhanced", 1, 1),
		row("a", "measurements", "cup_index", 5, 0.75), row("a", "tattoos", "tattoos:yes", 1, 1),
		row("a", "hair", "hair:brown", 1, 1),
		row("b", "content", "tag:4", 1, 1), row("b", "augmentation", "augmentation:natural", 0.5, 1),
		row("c", "height", "height_cm", 170, 1),
		row("d", "content", "tag:2", 0.5, 0.5), row("d", "hair", "hair:blonde", 0.5, 1), row("d", "eyes", "eyes:blue", 0, 1),
	}
	db := packedProfileDB(t, version, features)
	weights := performerBlockWeightsMap()
	for _, packed := range []bool{true, false} {
		if !packed {
			if _, err := db.Exec(`DROP TABLE performer_profile`); err != nil {
				t.Fatal(err)
			}
		}
		full, err := loadPerformerProfiles(db, version, nil)
		if err != nil {
			t.Fatal(err)
		}
		for targetID, target := range full {
			trimmed, err := loadProfilesComparedTo(db, version, target)
			if err != nil {
				t.Fatal(err)
			}
			if len(trimmed) != len(full) {
				t.Fatalf("packed=%v: %d trimmed profiles, want %d", packed, len(trimmed), len(full))
			}
			for otherID, other := range full {
				wantSimilarity, wantBlocks, wantWeights := performerSimilarity(target, other, weights)
				gotSimilarity, gotBlocks, gotWeights := performerSimilarity(target, trimmed[otherID], weights)
				if gotSimilarity != wantSimilarity || !reflect.DeepEqual(gotBlocks, wantBlocks) || !reflect.DeepEqual(gotWeights, wantWeights) {
					t.Errorf("packed=%v %s→%s: got %v %v %v, want %v %v %v", packed, targetID, otherID,
						gotSimilarity, gotBlocks, gotWeights, wantSimilarity, wantBlocks, wantWeights)
				}
			}
		}
	}
}

// The packed-profile scanner must read what encoding/json reads, and reject
// what it would not accept as a {block: {name: [value, confidence]}} row.
func TestVisitPackedProfileMatchesEncodingJSON(t *testing.T) {
	valid := []string{
		`{}`,
		`{"content":{}}`,
		`{"content":{"tag:1":[0.5,1.0],"tag:2":[-1e-05,0.25]},"height":{"height_cm":[170.0,1.0]}}`,
		" {\n \"hair\" : { \"hair:\\u00dcn\\\"q\\\"\" : [ 1 , 0.65 ] } } \n",
		`{"a\\b":{"😀":[2E+3,-0]}}`,
	}
	for _, raw := range valid {
		var want map[string]map[string][2]float64
		if err := json.Unmarshal([]byte(raw), &want); err != nil {
			t.Fatalf("fixture %q: %v", raw, err)
		}
		got := map[string]map[string][2]float64{}
		err := visitPackedProfile([]byte(raw), func(block string, name []byte, value, confidence float64) {
			if got[block] == nil {
				got[block] = map[string][2]float64{}
			}
			got[block][string(name)] = [2]float64{value, confidence}
		})
		if err != nil {
			t.Fatalf("%q: %v", raw, err)
		}
		for block, values := range want {
			if got[block] == nil {
				got[block] = map[string][2]float64{}
			}
			if !reflect.DeepEqual(got[block], values) {
				t.Errorf("%q block %q: got %v, want %v", raw, block, got[block], values)
			}
		}
		if len(got) != len(want) {
			t.Errorf("%q: got blocks %v, want %v", raw, got, want)
		}
	}
	invalid := []string{
		``, `[]`, `{"content":[]}`, `{"content":{"tag":[1]}}`, `{"content":{"tag":[1,2,3]}}`,
		`{"content":{"tag":[NaN,1]}}`, `{"content":{"tag":["1",1]}}`, `{"content":{"tag":[1,1]}`,
		`{"content":{"tag":[1,1]}} x`, `{"content" {"tag":[1,1]}}`, `{"content":{"tag":[1,1],}}`,
		`{"content":{"tag:[1,1]}}`, `{"content":{"tag":[1,1]}"hair":{}}`,
	}
	for _, raw := range invalid {
		if err := visitPackedProfile([]byte(raw), func(string, []byte, float64, float64) {}); err == nil {
			t.Errorf("%q: accepted", strings.TrimSpace(raw))
		}
	}
}
