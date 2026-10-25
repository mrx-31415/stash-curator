package main

import "testing"

// The materialized slate ranks on score summaries; only the returned items
// get their components, neighbors and eligibility decoded.
func TestHydrateItemDetailsLoadsOnlySelectedItems(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{
		`INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms)
VALUES ('model', 'published', 'features', '{}', 0)`,
		`INSERT INTO source_scene(scene_id, source_hash) VALUES ('a', 'fixture'), ('b', 'fixture')`,
		`INSERT INTO model_scene_score(model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
appeal, current_fit, confidence, metadata_confidence, recovery, components_json, eligibility_json)
VALUES ('model', 'a', 0, 0, 0, 0.5, 0.4, 0.9, 1, 1, '{"content":{"value":0.25}}', '{"eligible":true}'),
       ('model', 'b', 0, 0, 0, 0.3, 0.2, 0.8, 1, 1, '{"content":{"value":0.1}}', '{"eligible":true}')`,
		`INSERT INTO model_scene_neighbor(model_id, scene_id, rank, neighbor_scene_id, similarity, weight, outcome)
VALUES ('model', 'a', 0, 'b', 0.7, 0.5, 1)`,
	} {
		if _, err := db.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	summaries, err := modelScoreSummaries(db, "model", map[string]bool{"a": true, "b": true})
	if err != nil {
		t.Fatal(err)
	}
	if summaries["a"].appeal != 0.5 || summaries["b"].confidence != 0.8 || summaries["a"].components.kind != jNull {
		t.Fatalf("summaries should carry only numeric columns: %#v", summaries)
	}

	selected := &recommendationItem{sceneID: "a", needsDetails: true}
	prebuilt := &recommendationItem{sceneID: "b", components: jvObj(jvKey("kept", jvBool(true)))}
	if err := hydrateItemDetails(db, "model", []*recommendationItem{selected, prebuilt}); err != nil {
		t.Fatal(err)
	}
	if selected.needsDetails || numberValue(selected.components.get("content").get("value")) != 0.25 ||
		!selected.eligibility.get("eligible").truthy() || len(selected.neighbors.arr) != 1 {
		t.Fatalf("selected item not hydrated: %#v", selected)
	}
	if !prebuilt.components.get("kept").truthy() || prebuilt.neighbors.kind != jNull {
		t.Fatalf("already-built item was reloaded: %#v", prebuilt)
	}
}

func TestStoredComponentsDropStretchCandidates(t *testing.T) {
	candidate := jvObj(jvKey("name", jvStr("tag")), jvKey("value", jvFloat(0.2)))
	components := jvObj(
		jvKey("content", jvObj(jvKey("value", jvFloat(0.3)), jvKey("stretch_candidates", jvArr(candidate)))),
		jvKey("studio", jvObj(jvKey("value", jvFloat(0.1)), jvKey("stretch_candidates", jvArr()))),
		jvKey("fit", jvObj(jvKey("value", jvFloat(0.4)))),
	)
	stored := storedComponents(components)
	if got, want := stored.marshalSortedKeys(), `{"content":{"value":0.3},"fit":{"value":0.4},"studio":{"value":0.1}}`; got != want {
		t.Fatalf("stored components = %s, want %s", got, want)
	}
	if !components.get("content").has("stretch_candidates") {
		t.Fatal("storedComponents mutated the build-time components")
	}
	contributors := classificationPayload(components).get("stretch_contributors").get("positive")
	if len(contributors.arr) != 1 || contributors.arr[0].get("name").asString() != "tag" {
		t.Fatalf("stretch contributors lost: %s", contributors.marshalCompact())
	}
}
