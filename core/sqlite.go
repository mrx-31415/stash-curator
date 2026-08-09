package main

// Shared SQLite and scheduling helpers.

import (
	"database/sql"
	"runtime"
)

// openReadonly opens a feature artifact read-only. Artifacts are immutable
// published generations, so a plain mode=ro connection is safe.
func openReadonly(path string) (*sql.DB, error) {
	return sql.Open("sqlite", "file:"+path+"?mode=ro")
}

// nthreads resolves the worker count: the payload knob when set, else all
// available processors (matching the POC's GOMAXPROCS default).
func nthreads(requested int) int {
	if requested > 0 {
		return requested
	}
	return runtime.GOMAXPROCS(0)
}
