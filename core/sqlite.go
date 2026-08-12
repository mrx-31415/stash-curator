package main

// Shared SQLite and scheduling helpers.

import (
	"database/sql"
	"runtime"
)

// openReadonly opens a feature artifact read-only. Artifacts are immutable
// published generations, so a plain mode=ro connection is safe; the pragmas
// mirror connect_database's read tuning (30 s busy timeout, 128 MiB page
// cache, 512 MiB mmap) so kernel scans of the hundreds-of-MiB artifacts
// stay in cache instead of SQLite's 2 MiB default. The pool is pinned to one
// connection so the pragmas cover every statement (mattn applies DSN params
// per connection, but has no mmap_size key, so they are Exec'd here like
// openDatabase does).
func openReadonly(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3", "file:"+path+"?mode=ro")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	for _, pragma := range []string{
		"PRAGMA busy_timeout = 30000",
		"PRAGMA cache_size = -131072",
		"PRAGMA mmap_size = 536870912",
	} {
		if _, err := db.Exec(pragma); err != nil {
			db.Close()
			return nil, err
		}
	}
	return db, nil
}

// nthreads resolves the worker count: the payload knob when set, else all
// available processors (matching the POC's GOMAXPROCS default).
func nthreads(requested int) int {
	if requested > 0 {
		return requested
	}
	return runtime.GOMAXPROCS(0)
}
