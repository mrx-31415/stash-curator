package main

import (
	"database/sql"
	"net/url"
	"path/filepath"
	"testing"
)

func TestFileURIWindowsDrive(t *testing.T) {
	path := "C:/Users/Besitzer/.stash/plugins/stash-curator/data/curator.sqlite3"
	for _, readonly := range []bool{false, true} {
		uri := fileURI(path, readonly)
		u, err := url.Parse(uri)
		if err != nil {
			t.Fatal(err)
		}
		if u.Scheme != "file" || u.Host != "" || u.Path != "/"+path {
			t.Fatalf("Windows drive path became a URI authority: %s", uri)
		}
		if (u.Query().Get("mode") == "ro") != readonly {
			t.Fatalf("incorrect read-only mode: %s", uri)
		}
	}
	for _, immutable := range []bool{false, true} {
		u, err := url.Parse(readonlyArtifactURI(path, immutable))
		if err != nil {
			t.Fatal(err)
		}
		if u.Host != "" || u.Path != "/"+path || u.Query().Get("mode") != "ro" ||
			(u.Query().Get("immutable") == "1") != immutable {
			t.Fatalf("incorrect Windows artifact URI: %s", u)
		}
	}
}

func TestSQLiteURIFilenameRoundTrip(t *testing.T) {
	// filepath.Join supplies native backslashes when this test runs on Windows.
	path := filepath.Join(t.TempDir(), "curator #100% & café.sqlite3")
	db, err := openDatabase(path, false, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec("CREATE TABLE marker (value TEXT); INSERT INTO marker VALUES ('same file')"); err != nil {
		db.Close()
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	readonly, err := openReadonly(path)
	if err != nil {
		t.Fatal(err)
	}
	defer readonly.Close()
	var value string
	if err := readonly.QueryRow("SELECT value FROM marker").Scan(&value); err != nil || value != "same file" {
		t.Fatalf("read-only filename round trip: value=%q, error=%v", value, err)
	}
	if _, err := readonly.Exec("INSERT INTO marker VALUES ('write')"); err == nil {
		t.Fatal("read-only connection allowed a write")
	}
	for _, immutable := range []bool{false, true} {
		artifact, err := sql.Open("sqlite3", readonlyArtifactURI(path, immutable))
		if err != nil {
			t.Fatal(err)
		}
		err = artifact.QueryRow("SELECT value FROM marker").Scan(&value)
		artifact.Close()
		if err != nil || value != "same file" {
			t.Fatalf("artifact filename round trip: value=%q, error=%v", value, err)
		}
	}
}
