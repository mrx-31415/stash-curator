package main

import (
	"database/sql"
	"path/filepath"
	"testing"
)

func TestMultiRowInsert(t *testing.T) {
	stmt := `INSERT INTO t(a, b) VALUES (?, ?)`
	got, err := multiRowInsert(stmt, 3)
	if err != nil {
		t.Fatal(err)
	}
	want := `INSERT INTO t(a, b) VALUES (?, ?),(?, ?),(?, ?)`
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
	// Single row: unchanged.
	single, err := multiRowInsert(stmt, 1)
	if err != nil || single != stmt {
		t.Errorf("n=1: %q, %v", single, err)
	}
	// Statements without a repeatable tuple error (caller falls back).
	if _, err := multiRowInsert("SELECT 1", 3); err == nil {
		t.Error("expected error for a non-INSERT statement")
	}
	if _, err := multiRowInsert(`INSERT INTO t(a) VALUES (?, ?`, 2); err == nil {
		t.Error("expected error for an unbalanced tuple")
	}
}

func TestExecMultiRowInsertsAllRows(t *testing.T) {
	db, err := sql.Open("sqlite3", filepath.Join(t.TempDir(), "multi.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE t(id INTEGER PRIMARY KEY, a TEXT, b REAL)`); err != nil {
		t.Fatal(err)
	}
	conn, err := db.Conn(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	const rows = 2500
	data := make([][]any, 0, rows)
	for i := 0; i < rows; i++ {
		data = append(data, []any{int64(i), "name-" + string(rune('a'+i%26)), float64(i) / 2})
	}
	if err := execMultiRow(conn, `INSERT INTO t(id, a, b) VALUES (?, ?, ?)`, data); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM t`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != rows {
		t.Fatalf("inserted %d rows, want %d", count, rows)
	}
	var sum float64
	if err := db.QueryRow(`SELECT sum(b) FROM t`).Scan(&sum); err != nil {
		t.Fatal(err)
	}
	want := float64(rows*(rows-1)) / 4 // sum of i/2 for i in 0..rows-1
	if sum != want {
		t.Errorf("sum(b) = %v, want %v", sum, want)
	}
}

func TestInsertArtifactRowsBatchSizes(t *testing.T) {
	db, err := sql.Open("sqlite3", filepath.Join(t.TempDir(), "batch.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE t(a TEXT, b INTEGER)`); err != nil {
		t.Fatal(err)
	}
	rows := make([][]any, 0, 2500)
	for i := 0; i < 2500; i++ {
		rows = append(rows, []any{"x", int64(i)})
	}
	if err := insertArtifactRows(db, `INSERT INTO t(a, b) VALUES (?, ?)`, rows); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM t`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 2500 {
		t.Fatalf("inserted %d rows", count)
	}
}
