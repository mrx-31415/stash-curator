package main

// Issue #186: the model build must fail loudly when feature_affinity came out
// empty while the build produced non-empty inputs (labels/direct_scene_state
// or entity_feature rows), instead of silently publishing a model with no
// content-based recommendations. A legitimately empty corpus (no labels and
// no entity features) must still build.

import (
	"strings"
	"testing"
)

// artifactSanityDB returns an artifact-shaped connection with empty
// feature_affinity and entity_feature tables, so the check's count queries
// resolve exactly as they do on the model artifact.
func artifactSanityDB(t *testing.T) dbx {
	t.Helper()
	db, _ := openTempDB(t)
	if _, err := db.Exec(`CREATE TABLE feature_affinity (
		model_id TEXT NOT NULL, feature_id TEXT NOT NULL
	) STRICT`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE entity_feature (
		feature_version TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
		feature_id TEXT NOT NULL, value REAL NOT NULL, confidence REAL NOT NULL
	) STRICT`); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestModelAffinitySanityCheckFailsWhenAffinitiesEmptyDespiteInputs(t *testing.T) {
	db := artifactSanityDB(t)
	// Non-empty labels (the direct_scene_state source), zero affinity rows:
	// the build must fail with a message naming the artifact table and stage.
	if _, err := db.Exec(`INSERT INTO entity_feature(
		feature_version, entity_type, entity_id, feature_id, value, confidence
	) VALUES ('fv-1', 'scene', 's1', 'f1', 1.0, 1.0)`); err != nil {
		t.Fatal(err)
	}
	err := modelAffinitySanityCheck(db, "model-1", "fv-1", map[string]sceneLabel{
		"s1": {absoluteEvidence: 2},
	})
	if err == nil {
		t.Fatal("expected the sanity check to fail: affinities empty while labels and entity_feature are non-empty")
	}
	for _, want := range []string{"feature_affinity", "model.publish", "0 rows"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error must mention %q, got: %v", want, err)
		}
	}
}

func TestModelAffinitySanityCheckFailsOnLabelsOnly(t *testing.T) {
	db := artifactSanityDB(t)
	// Labels alone (no entity_feature rows) still mean the build expected
	// content signal from a labeled corpus; empty affinities must fail.
	err := modelAffinitySanityCheck(db, "model-1", "fv-1", map[string]sceneLabel{
		"s1": {absoluteEvidence: 2},
	})
	if err == nil {
		t.Fatal("expected the sanity check to fail: affinities empty while labels are non-empty")
	}
	if !strings.Contains(err.Error(), "feature_affinity") {
		t.Errorf("error must name feature_affinity, got: %v", err)
	}
}

func TestModelAffinitySanityCheckFailsOnEntityFeaturesOnly(t *testing.T) {
	db := artifactSanityDB(t)
	if _, err := db.Exec(`INSERT INTO entity_feature(
		feature_version, entity_type, entity_id, feature_id, value, confidence
	) VALUES ('fv-1', 'scene', 's1', 'f1', 1.0, 1.0)`); err != nil {
		t.Fatal(err)
	}
	err := modelAffinitySanityCheck(db, "model-1", "fv-1", map[string]sceneLabel{})
	if err == nil {
		t.Fatal("expected the sanity check to fail: affinities empty while entity_feature is non-empty")
	}
}

func TestModelAffinitySanityCheckAllowsEmptyCorpus(t *testing.T) {
	db := artifactSanityDB(t)
	// A legitimately empty corpus: no labels, no entity_feature rows, zero
	// affinities. The build must NOT fail on emptiness alone.
	if err := modelAffinitySanityCheck(db, "model-1", "fv-1", map[string]sceneLabel{}); err != nil {
		t.Fatalf("empty-but-consistent corpus must not fail, got: %v", err)
	}
}

func TestModelAffinitySanityCheckAllowsWrittenAffinities(t *testing.T) {
	db := artifactSanityDB(t)
	if _, err := db.Exec(`INSERT INTO feature_affinity(model_id, feature_id)
		VALUES ('model-1', 'f1')`); err != nil {
		t.Fatal(err)
	}
	if err := modelAffinitySanityCheck(db, "model-1", "fv-1", map[string]sceneLabel{
		"s1": {absoluteEvidence: 2},
	}); err != nil {
		t.Fatalf("non-empty affinities must pass even with inputs present, got: %v", err)
	}
}

func TestExecMultiRowVerifiesRowsAffected(t *testing.T) {
	db := artifactSanityDB(t)
	if _, err := db.Exec(`ALTER TABLE feature_affinity RENAME TO feature_affinity_old`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE feature_affinity (
		model_id TEXT NOT NULL, feature_id TEXT NOT NULL,
		PRIMARY KEY (model_id, feature_id)
	) STRICT, WITHOUT ROWID`); err != nil {
		t.Fatal(err)
	}
	conn, err := db.Conn(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	// Plain multi-row insert: all rows land, affected == len(batch).
	if err := execMultiRow(conn, `INSERT INTO feature_affinity(model_id, feature_id) VALUES (?, ?)`,
		[][]any{{"m", "f1"}, {"m", "f2"}}); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := conn.QueryRowContext(t.Context(), `SELECT count(*) FROM feature_affinity`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 2 {
		t.Fatalf("expected 2 rows, got %d", count)
	}
	// A statement that affects fewer rows than the batch must error instead
	// of silently succeeding (the #186 write-path guard): the second row
	// collides with an existing key, so OR IGNORE affects only one.
	err = execMultiRow(conn, `INSERT OR IGNORE INTO feature_affinity(model_id, feature_id) VALUES (?, ?)`,
		[][]any{{"m", "f3"}, {"m", "f1"}})
	if err == nil {
		t.Fatal("expected a rows-affected mismatch to error")
	}
	if !strings.Contains(err.Error(), "affected") {
		t.Errorf("error should describe the affected-row mismatch, got: %v", err)
	}
}
