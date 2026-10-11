package main

import "testing"

func TestModelStoredFeaturesShareDefinitions(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO feature_definition VALUES ('f', 'v', 'content', 'shared', 'tag', '{"tag_id":"tag"}')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO entity_feature VALUES ('v','scene','a','f',1.0,0.8), ('v','scene','b','f',0.5,0.2)`); err != nil {
		t.Fatal(err)
	}
	features, err := modelStoredFeatures(db, "v", "scene")
	if err != nil {
		t.Fatal(err)
	}
	a, b := features["a"][0], features["b"][0]
	if a.value != 1 || b.value != 0.5 || a.confidence != 0.8 || b.confidence != 0.2 {
		t.Fatalf("scene-specific values changed: %#v, %#v", a, b)
	}
	if a.metadata.get("tag_id").asString() != "tag" || &a.metadata.obj[0] != &b.metadata.obj[0] {
		t.Fatal("shared feature metadata was copied or changed")
	}
}

func TestPreferenceContentDimensions(t *testing.T) {
	features := map[string][]storedFeature{
		"a": {{featureID: "positive", family: "content", name: "shared"}, {featureID: "negative", family: "content", name: "negative"}},
		"b": {{featureID: "positive", family: "content", name: "shared"}, {featureID: "override", family: "content", name: "override"}, {featureID: "performer", family: "performer_identity", name: "performer"}},
	}
	affinities := map[string]modelAffinity{
		"positive":  {affinity: 0.5, confidence: 1},
		"negative":  {affinity: -0.5, confidence: 1},
		"override":  {affinity: -1, confidence: 0, contexts: jvObj(jvKey("learned_affinity", jvFloat(0.3)), jvKey("learned_confidence", jvFloat(0.5)))},
		"performer": {affinity: 1, confidence: 1},
	}
	if got := preferenceContentDimensions(features, affinities); got != 2 {
		t.Fatalf("got %d learned content dimensions, want 2", got)
	}
}
