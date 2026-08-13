package main

import (
	"testing"
)

// Issue #118: Expand's "already in library" exclusion is decided once at
// fetch time and persisted in external_entity.payload_json. A candidate
// fetched while the local scene had no StashDB id keeps its missing
// curator_local_match annotation forever (incremental since-fetch never
// re-fetches the unchanged StashDB scene), so the browse path must re-derive
// the match against the CURRENT links map at serve time.
func TestExpandResultsReannotatesAgainstCurrentLinks(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	// Candidates stored with NO curator_local_match — the stale-annotation
	// state the bug leaves behind.
	candidates := []struct {
		externalID string
		phash      string // "" = no fingerprint
	}{
		{"ext-owned-now", ""},
		{"ext-phash-owned", "0123456789abcdef"},
		{"ext-unrelated", "ffffffffffffffff"},
	}
	for _, candidate := range candidates {
		payload := jvObj(
			jvKey("id", jvStr(candidate.externalID)),
			jvKey("title", jvStr("Candidate "+candidate.externalID)),
			jvKey("release_date", jvStr("2026-01-01")),
			jvKey("details", jvStr("")),
			jvKey("studio", jvObj()),
			jvKey("tags", jvArr()),
			jvKey("performers", jvArr()),
		)
		if candidate.phash != "" {
			payload.set("fingerprints", jvArr(jvObj(
				jvKey("algorithm", jvStr("phash")),
				jvKey("hash", jvStr(candidate.phash)),
			)))
		} else {
			payload.set("fingerprints", jvArr())
		}
		if _, err := db.Exec(`INSERT INTO external_entity(
			entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool
		) VALUES ('scene', ?, ?, 0.5, '[]', 1000, 'candidate')`,
			candidate.externalID, payload.marshalCompact()); err != nil {
			t.Fatalf("seed candidate %s: %v", candidate.externalID, err)
		}
	}
	if _, err := db.Exec(`INSERT INTO expand_cache(
		singleton, model_id, fetched_at_ms, expires_at_ms, scene_count, performer_count
	) VALUES (1, 'model', 1000, 10000, 3, 0)`); err != nil {
		t.Fatalf("seed expand_cache: %v", err)
	}

	serve := func(links jVal, hidePhash bool) []string {
		t.Helper()
		result, err := expandResults(db, "scene", 1, "match", jvNull(), false, "",
			nil, nil, nil, nil, "", "", hidePhash, -1, 50, links)
		if err != nil {
			t.Fatalf("expandResults: %v", err)
		}
		var ids []string
		for _, item := range result.get("items").arr {
			ids = append(ids, item.get("id").asString())
		}
		return ids
	}
	assertIDs := func(got []string, want ...string) {
		t.Helper()
		gotSet := map[string]bool{}
		for _, id := range got {
			gotSet[id] = true
		}
		wantSet := map[string]bool{}
		for _, id := range want {
			wantSet[id] = true
		}
		if len(gotSet) != len(wantSet) {
			t.Fatalf("serve ids = %v, want %v", got, want)
		}
		for id := range wantSet {
			if !gotSet[id] {
				t.Fatalf("serve ids = %v, want %v (missing %s)", got, want, id)
			}
		}
	}

	// Timeline step 1: fetch time — the local scenes have no StashDB ids,
	// so every candidate is a valid recommendation.
	unlinked := linksFixture(map[string]string{}, map[string]string{})
	assertIDs(serve(unlinked, true), "ext-owned-now", "ext-phash-owned", "ext-unrelated")

	// Timeline step 2: the user adds the stash_id to the local scene (and
	// another local scene gains the exact phash); the links map rebuilds.
	// Browse must now hide the stash_id match and the phash match.
	linked := linksFixture(
		map[string]string{"ext-owned-now": "local-1"},
		map[string]string{"0123456789abcdef": "local-2"},
	)
	assertIDs(serve(linked, true), "ext-unrelated")

	// hide_phash_matches=false keeps the phash-matched candidate but the
	// stash_id exclusion still applies.
	assertIDs(serve(linked, false), "ext-phash-owned", "ext-unrelated")

	// The re-derived payload is what is served: the phash candidate carries
	// its fresh annotation when it is not hidden.
	result, err := expandResults(db, "scene", 1, "match", jvNull(), false, "",
		nil, nil, nil, nil, "", "", false, -1, 50, linked)
	if err != nil {
		t.Fatalf("expandResults: %v", err)
	}
	for _, item := range result.get("items").arr {
		if item.get("id").asString() == "ext-phash-owned" {
			match := item.get("payload").get("curator_local_match")
			if match.get("type").asString() != "phash" ||
				match.get("local_scene_id").asString() != "local-2" {
				t.Fatalf("served phash match = %s", match.marshalCompact())
			}
		}
	}
}

// linksFixture builds a links map in the shape externalLinks produces:
// scenes/scene_ids/performers/studios plus scene_phashes.
func linksFixture(byStashID, byPhash map[string]string) jVal {
	scenes := jvObj()
	sceneIDs := jvObj()
	for external, local := range byStashID {
		scenes.set(local, jvStr(external))
		sceneIDs.set(external, jvStr(local))
	}
	scenePhashes := jvObj()
	for phash, local := range byPhash {
		scenePhashes.set(phash, jvStr(local))
	}
	return jvObj(
		jvKey("scenes", scenes),
		jvKey("scene_ids", sceneIDs),
		jvKey("scene_phashes", scenePhashes),
		jvKey("performers", jvObj()),
		jvKey("studios", jvObj()),
	)
}
