package main

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// seedArtifactSidecar builds a fully migrated sidecar whose registry rows
// point at synthetic published artifacts, and writes those artifacts.
func seedArtifactSidecar(t *testing.T, kind string) (*sql.DB, string) {
	t.Helper()
	db, corePath := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	// Synthetic artifact file with the artifact schema.
	generation := "fv-" + strings.Repeat("a", 20)
	if kind == "model" {
		generation = "model-" + strings.Repeat("b", 20)
	}
	basename := "feature-" + generation + ".sqlite3"
	if kind == "model" {
		basename = generation + ".sqlite3"
	}
	artifactPath, err := artifactPath(corePath, basename)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(artifactPath), 0o700); err != nil {
		t.Fatal(err)
	}
	artifact, err := openDatabase(artifactPath, false)
	if err != nil {
		t.Fatal(err)
	}
	defer artifact.Close()
	if _, err := artifact.Exec(fmt.Sprintf("PRAGMA user_version = %d", artifactSchemaVersion)); err != nil {
		t.Fatal(err)
	}
	if _, err := artifact.Exec(`CREATE TABLE artifact_meta (
		kind TEXT NOT NULL, generation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
	) STRICT`); err != nil {
		t.Fatal(err)
	}
	artifactTablesSQL := map[string]string{
		"feature": `CREATE TABLE feature_definition (
			feature_id TEXT PRIMARY KEY, feature_version TEXT NOT NULL, family TEXT NOT NULL,
			name TEXT NOT NULL, provenance TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
		) STRICT; CREATE TABLE entity_feature (
			feature_version TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
			feature_id TEXT NOT NULL, value REAL NOT NULL, confidence REAL NOT NULL,
			PRIMARY KEY (feature_version, entity_type, entity_id, feature_id)
		) STRICT, WITHOUT ROWID; CREATE TABLE scene_content_search (
			feature_version TEXT NOT NULL, feature_id TEXT NOT NULL, scene_id TEXT NOT NULL,
			value REAL NOT NULL, PRIMARY KEY (feature_id, scene_id)
		) STRICT, WITHOUT ROWID;`,
		"model": `CREATE TABLE model_scene_score (
			model_id TEXT NOT NULL, scene_id TEXT NOT NULL, appeal REAL NOT NULL,
			confidence REAL NOT NULL, components_json TEXT NOT NULL,
			PRIMARY KEY (model_id, scene_id)
		) STRICT, WITHOUT ROWID; CREATE TABLE model_scene_lane (
			model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
			lane TEXT NOT NULL CHECK (lane IN ('for_you','best_bets','revisit','discover','adventure')),
			subtype TEXT, lane_value REAL NOT NULL, qualification_json TEXT NOT NULL DEFAULT '{}',
			appeal REAL, PRIMARY KEY (model_id, scene_id, lane)
		) STRICT, WITHOUT ROWID;`,
	}
	if _, err := artifact.Exec(artifactTablesSQL[kind]); err != nil {
		t.Fatal(err)
	}
	// Register the published artifact in the sidecar registry.
	insert := ""
	if kind == "feature" {
		insert = `INSERT INTO feature_build(feature_version, status, config_json, source_fingerprint, created_at_ms, artifact_basename, artifact_schema_version, artifact_bytes, validation_status, validation_summary_json, reuse_count)
			VALUES (?, 'published', '{}', 'fp', 1, ?, ?, 1, 'valid', '{}', 0)`
	} else {
		insert = `INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms, artifact_basename, artifact_schema_version, artifact_bytes, validation_status, validation_summary_json, reuse_count)
			VALUES (?, 'published', 'fv-aaaaaaaaaaaaaaaaaaaa', '{}', 1, ?, ?, 1, 'valid', '{}', 0)`
	}
	if _, err := db.Exec(insert, generation, basename, artifactSchemaVersion); err != nil {
		t.Fatal(err)
	}
	return db, corePath
}

// Attaching creates the temp views over the published generation, and queries
// through them read the artifact rows (shadowing the core schema).
func TestAttachActiveArtifacts(t *testing.T) {
	db, _ := seedArtifactSidecar(t, "feature")
	if err := attachActiveArtifacts(db); err != nil {
		t.Fatal(err)
	}
	// The artifact tables resolve to the attached generation: writing through
	// the shadowing view fails (the artifact is read-only and the view hides
	// the core table).
	if _, err := db.Exec(`INSERT INTO feature_definition(feature_id, feature_version, family, name, provenance)
		VALUES ('f1', 'v1', 'tag', 'n', 'p')`); err == nil {
		t.Fatal("write through the artifact view should fail")
	}
	// A core-only table still resolves to the core schema.
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM source_scene`).Scan(&count); err != nil {
		t.Fatal(err)
	}
}

// A registry pointing at a missing artifact fails with the Python-equivalent
// message.
func TestAttachActiveArtifactsMissingFile(t *testing.T) {
	db, _ := seedArtifactSidecar(t, "feature")
	if err := os.RemoveAll(cacheDirectory(mustDatabasePath(t, db))); err != nil {
		t.Fatal(err)
	}
	err := attachActiveArtifacts(db)
	if err == nil {
		t.Fatal("expected missing-artifact error")
	}
	want := "active artifact is missing: feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3"
	if err.Error() != want {
		t.Errorf("error = %q, want %q", err.Error(), want)
	}
}

// Same missing-artifact failure for the model generation.
func TestAttachActiveArtifactsMissingModelFile(t *testing.T) {
	db, _ := seedArtifactSidecar(t, "model")
	if err := os.RemoveAll(cacheDirectory(mustDatabasePath(t, db))); err != nil {
		t.Fatal(err)
	}
	err := attachActiveArtifacts(db)
	if err == nil {
		t.Fatal("expected missing-artifact error")
	}
	want := "active artifact is missing: model-bbbbbbbbbbbbbbbbbbbb.sqlite3"
	if err.Error() != want {
		t.Errorf("error = %q, want %q", err.Error(), want)
	}
}

// attachBuildSources shadows every non-owned core table plus the feature
// tables, mirroring the build-time attach in artifacts.py.
func TestAttachBuildSources(t *testing.T) {
	db, corePath := seedArtifactSidecar(t, "feature")
	featurePath := filepath.Join(cacheDirectory(corePath), "feature-fv-aaaaaaaaaaaaaaaaaaaa.sqlite3")
	if err := attachBuildSources(db, corePath, featurePath); err != nil {
		t.Fatal(err)
	}
	// core-schema tables (not owned) come from the attached core database.
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM application_meta`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	// feature tables come from the attached feature generation.
	if _, err := db.Query(`SELECT count(*) FROM feature_definition`); err != nil {
		t.Fatal(err)
	}
}

func mustDatabasePath(t *testing.T, db *sql.DB) string {
	t.Helper()
	path, err := coreDatabasePath(db)
	if err != nil {
		t.Fatal(err)
	}
	return path
}
