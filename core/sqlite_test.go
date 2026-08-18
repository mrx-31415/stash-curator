package main

// Pragma-parity self-verification: the read-only artifact opens must carry
// the same tuning connect_database applies (30 s busy timeout, 128 MiB page
// cache, 512 MiB mmap), so kernel scans of the hundreds-of-MiB feature
// artifacts do not fall back to SQLite's 2 MiB default cache.

import (
	"testing"
)

func TestOpenReadonlyPragmasApplied(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	db.Close()

	readonly, err := openReadonly(path)
	if err != nil {
		t.Fatal(err)
	}
	defer readonly.Close()
	var cache, mmap, busy int64
	if err := readonly.QueryRow("PRAGMA cache_size").Scan(&cache); err != nil {
		t.Fatal(err)
	}
	if err := readonly.QueryRow("PRAGMA mmap_size").Scan(&mmap); err != nil {
		t.Fatal(err)
	}
	if err := readonly.QueryRow("PRAGMA busy_timeout").Scan(&busy); err != nil {
		t.Fatal(err)
	}
	if cache != -131072 || mmap != 536870912 || busy != 30000 {
		t.Fatalf("readonly pragma parity failed: cache_size=%d mmap_size=%d busy_timeout=%d", cache, mmap, busy)
	}
	// The tuned connection must still be usable (a sidecar migrated by the
	// same chain has its schema_migration rows).
	var latest int64
	if err := readonly.QueryRow(
		`SELECT max(version) FROM schema_migration`).Scan(&latest); err != nil {
		t.Fatal(err)
	}
	if latest != 33 {
		t.Fatalf("latest migration=%d, want 33", latest)
	}
}
