package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func openTempDB(t *testing.T) (dbx, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "sidecar.sqlite3")
	db, err := openDatabase(path, false, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	return db, path
}

// The full chain applies on a fresh database, producing the same status a
// Python-migrated sidecar has (current/latest 30, nothing pending), and a
// second migrate is a no-op.
func TestMigrateFullChain(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	status, err := queryMigrationStatus(db)
	if err != nil {
		t.Fatal(err)
	}
	migrations, err := loadMigrations()
	if err != nil {
		t.Fatal(err)
	}
	if status.currentVersion != 37 || status.latestVersion != 37 || len(status.pending) != 0 {
		t.Fatalf("unexpected status: %+v", status)
	}
	if len(migrations) != 37 {
		t.Fatalf("expected 37 migrations, got %d", len(migrations))
	}
	var rows int
	if err := db.QueryRow(`SELECT count(*) FROM schema_migration`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 37 {
		t.Fatalf("schema_migration has %d rows, want 37", rows)
	}
	// Idempotent second migrate.
	if err := migrate(db, 1_700_000_000_001); err != nil {
		t.Fatalf("second migrate: %v", err)
	}
	if err := db.QueryRow(`SELECT count(*) FROM schema_migration`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 37 {
		t.Fatalf("second migrate added rows: %d", rows)
	}
	var integrity string
	if err := db.QueryRow(`PRAGMA integrity_check`).Scan(&integrity); err != nil {
		t.Fatal(err)
	}
	if integrity != "ok" {
		t.Fatalf("integrity: %s", integrity)
	}
}

// Embedded SQL files must stay byte-identical to the Python migration
// package; the sha256 checksums (and thus schema_migration rows) match by
// construction.
func TestEmbeddedMigrationsMatchPythonPackage(t *testing.T) {
	pythonDir := filepath.Clean(filepath.Join("..", "curator", "storage", "sql"))
	if _, err := os.Stat(pythonDir); err != nil {
		t.Skipf("python migration package not present at %s: %v", pythonDir, err)
	}
	entries, err := migrationFS.ReadDir("migrations")
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		embedded, err := migrationFS.ReadFile("migrations/" + entry.Name())
		if err != nil {
			t.Fatal(err)
		}
		python, err := os.ReadFile(filepath.Join(pythonDir, entry.Name()))
		if err != nil {
			t.Fatalf("missing python counterpart for %s: %v", entry.Name(), err)
		}
		if string(embedded) != string(python) {
			t.Errorf("migrations/%s differs from curator/storage/sql/%s", entry.Name(), entry.Name())
		}
	}
}

// completeStatement must agree with sqlite3.complete_statement on the shapes
// found in the migration corpus (verified against Python).
func TestCompleteStatement(t *testing.T) {
	complete := []string{
		") STRICT;",
		"SELECT 1;",
		"INSERT INTO t VALUES ('a;b');",
		";",
		"CREATE TABLE x (a TEXT);\n",
	}
	for _, c := range complete {
		if !completeStatement(c) {
			t.Errorf("completeStatement(%q) = false, want true", c)
		}
	}
	incomplete := []string{
		"CREATE TABLE application_meta (",
		"key TEXT PRIMARY KEY,",
		"value TEXT NOT NULL",
		"SELECT 1",
		"SELECT 1\n",
		"-- comment only",
		"",
		"INSERT INTO t VALUES ('a;b')",
		"CREATE TABLE x (a TEXT) STRICT",
	}
	for _, c := range incomplete {
		if completeStatement(c) {
			t.Errorf("completeStatement(%q) = true, want false", c)
		}
	}
}

// Every migration splits into non-empty statements; the full ordered chain
// executes cleanly in TestMigrateFullChain (later files reference tables and
// indexes created by earlier ones, so isolated execution is meaningless).
func TestSplitAndExecuteStatements(t *testing.T) {
	migrations, err := loadMigrations()
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range migrations {
		statements, err := splitStatements(m.sql)
		if err != nil {
			t.Fatalf("%d: %v", m.version, err)
		}
		if len(statements) == 0 {
			t.Fatalf("migration %d produced no statements", m.version)
		}
		for _, statement := range statements {
			if strings.TrimSpace(statement) == "" {
				t.Fatalf("migration %d produced an empty statement", m.version)
			}
		}
	}
}
