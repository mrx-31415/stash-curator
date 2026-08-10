// SQLite connection setup for the backend ops, mirroring
// curator/storage/database.py connect_database: WAL for writable connections,
// foreign keys on, a shared 128 MiB page cache, and the read-only mmap for
// artifacts. Connections opened under an active trace are wrapped so every
// statement records a sqlite span, matching Python's ProfiledConnection.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

// dbx is the SQLite surface the backend ops use. *sql.DB satisfies it;
// tracedDB adds span recording while an operation trace is active.
type dbx interface {
	Exec(query string, args ...any) (sql.Result, error)
	Query(query string, args ...any) (*sql.Rows, error)
	QueryRow(query string, args ...any) *sql.Row
	Conn(ctx context.Context) (*sql.Conn, error)
	Close() error
}

// traceOf returns the span recorder attached to a traced connection, if any.
func traceOf(db dbx) *trace {
	if traced, ok := db.(*tracedDB); ok {
		return traced.t
	}
	return nil
}

// databasePath mirrors backend.py's _database_path: args.database_path, then
// settings.databasePath, then the plugin data directory.
func databasePath(pluginDir string, payload, settings jVal) string {
	configured := ""
	if args := payload.get("args"); args.kind == jObj {
		if v := args.get("database_path"); v.kind == jStr {
			configured = strings.TrimSpace(v.s)
		}
	}
	if configured == "" && settings.kind == jObj {
		if v := settings.get("databasePath"); v.kind == jStr {
			configured = strings.TrimSpace(v.s)
		}
	}
	if configured == "" {
		return filepath.Join(pluginDir, "data", "curator.sqlite3")
	}
	return expandUser(configured)
}

func expandUser(path string) string {
	if strings.HasPrefix(path, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(path, "~/"))
		}
	}
	return path
}

// openDatabase opens the sidecar with Python-equivalent PRAGMAs and URI
// filenames; trace, when non-nil, records every statement as a sqlite span.
// The caller resolves the path (realpath) first, matching connect_database's
// path.expanduser().resolve().
func openDatabase(path string, readonly bool, trace *trace) (dbx, error) {
	uri := fileURI(path, readonly)
	db, err := sql.Open("sqlite", uri)
	if err != nil {
		return nil, err
	}
	var out dbx = db
	if trace != nil {
		out = &tracedDB{db: db, t: trace}
	}
	// sql.Open does not connect; force a real connection so PRAGMA failures
	// surface here rather than on the first op.
	if _, err := out.Exec("SELECT 1"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := out.Exec("PRAGMA foreign_keys = ON"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := out.Exec("PRAGMA busy_timeout = 30000"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := out.Exec("PRAGMA cache_size = -131072"); err != nil {
		db.Close()
		return nil, err
	}
	if readonly {
		if _, err := out.Exec("PRAGMA mmap_size = 536870912"); err != nil {
			db.Close()
			return nil, err
		}
	} else {
		var mode string
		if err := out.QueryRow("PRAGMA journal_mode").Scan(&mode); err != nil {
			db.Close()
			return nil, err
		}
		if !strings.EqualFold(mode, "wal") {
			if _, err := out.Exec("PRAGMA journal_mode = WAL"); err != nil {
				db.Close()
				return nil, err
			}
		}
		if _, err := out.Exec("PRAGMA synchronous = NORMAL"); err != nil {
			db.Close()
			return nil, err
		}
	}
	return out, nil
}

// fileURI builds a Python-connect-style file URI: file:///abs/path with the
// mode=ro query for read-only opens.
func fileURI(path string, readonly bool) string {
	u := url.URL{Scheme: "file", Path: path}
	if readonly {
		u.RawQuery = "mode=ro"
	}
	return u.String()
}

// openSidecar mirrors backend.py's _open: connect, migrate, apply settings.
func openSidecar(pluginDir string, payload, settings jVal, attachArtifacts bool) (dbx, error) {
	path := realpath(databasePath(pluginDir, payload, settings))
	parent := filepath.Dir(path)
	if _, err := os.Stat(parent); os.IsNotExist(err) {
		if err := os.MkdirAll(parent, 0o755); err != nil {
			return nil, fmt.Errorf("could not create database directory: %v", err)
		}
	}
	db, err := openDatabase(path, false, currentTrace())
	if err != nil {
		return nil, err
	}
	if err := migrate(db, nowMs()); err != nil {
		db.Close()
		return nil, err
	}
	if err := applyPluginSettings(db, settings, nowMs()); err != nil {
		db.Close()
		return nil, err
	}
	if attachArtifacts {
		if err := attachActiveArtifacts(db); err != nil {
			db.Close()
			return nil, err
		}
	}
	return db, nil
}

func nowMs() int64 {
	return timeNowUnixMilli()
}

// timeNowUnixMilli is injectable so Go tests can pin timestamps that the
// byte-identical differential comparisons depend on.
var timeNowUnixMilli = func() int64 { return time.Now().UnixMilli() }
