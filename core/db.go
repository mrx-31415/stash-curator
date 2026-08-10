// SQLite connection setup for the backend ops, mirroring
// curator/storage/database.py connect_database: WAL for writable connections,
// foreign keys on, a shared 128 MiB page cache, and the read-only mmap for
// artifacts. Returns a *sql.DB whose single logical connection mirrors the
// Python side's explicit-transaction discipline (the raw plugin never opens
// concurrent writers).
package main

import (
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

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
// filenames. The caller resolves the path (realpath) first, matching
// connect_database's path.expanduser().resolve().
func openDatabase(path string, readonly bool) (*sql.DB, error) {
	uri := fileURI(path, readonly)
	db, err := sql.Open("sqlite", uri)
	if err != nil {
		return nil, err
	}
	// sql.Open does not connect; force a real connection so PRAGMA failures
	// surface here rather than on the first op.
	if _, err := db.Exec("SELECT 1"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("PRAGMA foreign_keys = ON"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("PRAGMA busy_timeout = 30000"); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("PRAGMA cache_size = -131072"); err != nil {
		db.Close()
		return nil, err
	}
	if readonly {
		if _, err := db.Exec("PRAGMA mmap_size = 536870912"); err != nil {
			db.Close()
			return nil, err
		}
	} else {
		var mode string
		if err := db.QueryRow("PRAGMA journal_mode").Scan(&mode); err != nil {
			db.Close()
			return nil, err
		}
		if !strings.EqualFold(mode, "wal") {
			if _, err := db.Exec("PRAGMA journal_mode = WAL"); err != nil {
				db.Close()
				return nil, err
			}
		}
		if _, err := db.Exec("PRAGMA synchronous = NORMAL"); err != nil {
			db.Close()
			return nil, err
		}
	}
	return db, nil
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
func openSidecar(pluginDir string, payload, settings jVal, attachArtifacts bool) (*sql.DB, error) {
	path := realpath(databasePath(pluginDir, payload, settings))
	parent := filepath.Dir(path)
	if _, err := os.Stat(parent); os.IsNotExist(err) {
		if err := os.MkdirAll(parent, 0o755); err != nil {
			return nil, fmt.Errorf("could not create database directory: %v", err)
		}
	}
	db, err := openDatabase(path, false)
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
