package main

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

// A sidecar that ran the old one-per-build pruning: a backlog of superseded
// generations, a retired row that used to block it, a missing artifact, and
// files left by killed builds. One pass must leave only the published and
// previous model and the features they use.
func TestPruneSnapshotsClearsBacklog(t *testing.T) {
	db, corePath := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	directory := cacheDirectory(realpath(corePath))
	if err := os.MkdirAll(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	id := func(digit int) string { return strings.Repeat(string(rune('0'+digit)), 20) }
	touch := func(name string, age time.Duration) {
		t.Helper()
		path := filepath.Join(directory, name)
		if err := os.WriteFile(path, nil, 0o600); err != nil {
			t.Fatal(err)
		}
		stamp := time.Now().Add(-age)
		if err := os.Chtimes(path, stamp, stamp); err != nil {
			t.Fatal(err)
		}
	}
	exec := func(query string, args ...any) {
		t.Helper()
		if _, err := db.Exec(query, args...); err != nil {
			t.Fatal(err)
		}
	}
	for generation := 1; generation <= 4; generation++ {
		status := "superseded"
		if generation == 4 {
			status = "published"
		}
		feature := "fv-" + id(generation)
		model := "model-" + id(generation)
		exec(`INSERT INTO feature_build(feature_version, status, config_json, source_fingerprint,
			created_at_ms, published_at_ms, artifact_basename, validation_status)
			VALUES (?, ?, '{}', ?, ?, ?, ?, 'valid')`,
			feature, status, feature, generation, generation, "feature-"+feature+".sqlite3")
		exec(`INSERT INTO model_version(model_id, status, feature_version, config_json,
			created_at_ms, published_at_ms, artifact_basename, validation_status)
			VALUES (?, ?, ?, '{}', ?, ?, ?, 'valid')`,
			model, status, feature, generation, generation, model+".sqlite3")
		touch("feature-"+feature+".sqlite3", 0)
		if generation != 1 {
			touch(model+".sqlite3", 0)
		}
	}
	// Retired by the old pruning (basename dropped, row kept), and a
	// pre-artifact model whose core rows legacy compaction has yet to delete.
	exec(`INSERT INTO model_version(model_id, status, feature_version, config_json,
		created_at_ms, published_at_ms, validation_status)
		VALUES (?, 'superseded', ?, '{}', 0, 0, 'retired')`, "model-"+id(0), "fv-"+id(1))
	exec(`INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms)
		VALUES ('legacy', 'superseded', ?, '{}', 0)`, "fv-"+id(1))
	exec(`INSERT INTO model_lane_order_state(model_id, created_at_ms) VALUES ('legacy', 0)`)
	exec(`INSERT INTO feature_definition(feature_id, feature_version, family, name, provenance)
		VALUES ('legacy-feature', ?, 'tag', 'Tag', 'test')`, "fv-"+id(1))
	touch("model-"+id(9)+".sqlite3", 7*time.Hour)
	touch(".model-"+id(8)+"."+strings.Repeat("a", 32)+".tmp", 7*time.Hour)
	fresh := ".feature-fv-" + id(7) + "." + strings.Repeat("b", 32) + ".tmp"
	touch(fresh, time.Minute)

	if err := pruneSnapshots(db); err != nil {
		t.Fatal(err)
	}

	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatal(err)
	}
	var files []string
	for _, entry := range entries {
		files = append(files, entry.Name())
	}
	want := []string{
		fresh,
		"feature-fv-" + id(3) + ".sqlite3", "feature-fv-" + id(4) + ".sqlite3",
		"model-" + id(3) + ".sqlite3", "model-" + id(4) + ".sqlite3",
	}
	sort.Strings(want)
	if strings.Join(files, " ") != strings.Join(want, " ") {
		t.Fatalf("derived files = %v, want %v", files, want)
	}
	models, err := queryStrings(db, `SELECT model_id || ':' || coalesce(artifact_basename, '-')
		|| ':' || coalesce(cleanup_error, '-') FROM model_version ORDER BY model_id`)
	if err != nil {
		t.Fatal(err)
	}
	wantModels := []string{
		"legacy:-:-",
		"model-" + id(3) + ":model-" + id(3) + ".sqlite3:-",
		"model-" + id(4) + ":model-" + id(4) + ".sqlite3:-",
	}
	if strings.Join(models, " ") != strings.Join(wantModels, " ") {
		t.Fatalf("model rows = %v, want %v", models, wantModels)
	}
	features, err := queryStrings(db, `SELECT feature_version FROM feature_build ORDER BY feature_version`)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(features, " ") != "fv-"+id(3)+" fv-"+id(4) {
		t.Fatalf("feature rows = %v", features)
	}
	var legacyFeatures int
	if err := db.QueryRow(`SELECT count(*) FROM feature_definition`).Scan(&legacyFeatures); err != nil {
		t.Fatal(err)
	}
	if legacyFeatures != 0 {
		t.Fatalf("legacy feature rows of a pruned version survived: %d", legacyFeatures)
	}
}
