package main

// Issue #186: the model build must fail loudly when the write path lands a
// different number of feature_affinity rows than the build computed in memory,
// instead of silently publishing a model whose content affinities were
// partially or wholly dropped. A legitimately empty in-memory computation
// (no affinity signal) must still build — the check only guards the write.

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

func TestModelAffinitySanityCheckFailsWhenComputedButNotWritten(t *testing.T) {
	db := artifactSanityDB(t)
	// The build computed 3 affinities in memory but the write path landed 0.
	err := modelAffinitySanityCheck(db, "model-1", 3)
	if err == nil {
		t.Fatal("expected the sanity check to fail: computed 3 affinities, wrote 0")
	}
	for _, want := range []string{"feature_affinity", "model.publish", "computed 3"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error must mention %q, got: %v", want, err)
		}
	}
}

func TestModelAffinitySanityCheckFailsOnPartialWrite(t *testing.T) {
	db := artifactSanityDB(t)
	if _, err := db.Exec(`INSERT INTO feature_affinity(model_id, feature_id)
		VALUES ('model-1', 'f1')`); err != nil {
		t.Fatal(err)
	}
	// Computed 3, wrote 1: a partial write must fail.
	err := modelAffinitySanityCheck(db, "model-1", 3)
	if err == nil {
		t.Fatal("expected the sanity check to fail on a partial write")
	}
	if !strings.Contains(err.Error(), "feature_affinity") {
		t.Errorf("error must name feature_affinity, got: %v", err)
	}
}

func TestModelAffinitySanityCheckAllowsEmptyComputation(t *testing.T) {
	db := artifactSanityDB(t)
	// A legitimately empty in-memory computation: the build had no affinity
	// signal, so nothing to write. Must NOT fail.
	if err := modelAffinitySanityCheck(db, "model-1", 0); err != nil {
		t.Fatalf("empty-but-consistent build must not fail, got: %v", err)
	}
}

func TestModelAffinitySanityCheckAllowsFullyWritten(t *testing.T) {
	db := artifactSanityDB(t)
	if _, err := db.Exec(`INSERT INTO feature_affinity(model_id, feature_id)
		VALUES ('model-1', 'f1'), ('model-1', 'f2'), ('model-1', 'f3')`); err != nil {
		t.Fatal(err)
	}
	// Computed 3, wrote 3: consistent, must pass.
	if err := modelAffinitySanityCheck(db, "model-1", 3); err != nil {
		t.Fatalf("consistent build must pass, got: %v", err)
	}
}

func TestModelAffinitySanityCheckAllowsNoComputationNoWrite(t *testing.T) {
	db := artifactSanityDB(t)
	// Computed 0, wrote 0: the empty-corpus path. Must pass.
	if err := modelAffinitySanityCheck(db, "model-1", 0); err != nil {
		t.Fatalf("zero-computed zero-written must pass, got: %v", err)
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
