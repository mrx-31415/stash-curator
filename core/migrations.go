// Ordered, checksummed SQLite migrations — a port of
// curator/storage/migrations.py with identical checksums and status
// semantics, so a sidecar migrated by either implementation is accepted by
// the other. The SQL files under migrations/ are byte-identical copies of
// curator/storage/sql/ (guarded by tests/core/test_backend.py), which makes
// the sha256 checksums match by construction.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"embed"
	"encoding/hex"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

//go:embed migrations/*.sql
var migrationFS embed.FS

type migration struct {
	version  int
	name     string
	sql      string
	checksum string
}

type migrationStatus struct {
	currentVersion int
	latestVersion  int
	applied        []int
	pending        []int
}

var loadedMigrations []migration

func loadMigrations() ([]migration, error) {
	if loadedMigrations != nil {
		return loadedMigrations, nil
	}
	entries, err := migrationFS.ReadDir("migrations")
	if err != nil {
		return nil, err
	}
	var migrations []migration
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasPrefix(name, "_") || !strings.HasSuffix(name, ".sql") {
			continue
		}
		prefix, rest, found := strings.Cut(name, "_")
		if !found || prefix == "" || !allDigits(prefix) {
			return nil, fmt.Errorf("invalid migration filename: %s", name)
		}
		version, err := strconv.Atoi(prefix)
		if err != nil {
			return nil, fmt.Errorf("invalid migration filename: %s", name)
		}
		content, err := migrationFS.ReadFile("migrations/" + name)
		if err != nil {
			return nil, err
		}
		sqlText := string(content)
		sum := sha256.Sum256(content)
		migrations = append(migrations, migration{
			version:  version,
			name:     strings.TrimSuffix(rest, ".sql"),
			sql:      sqlText,
			checksum: hex.EncodeToString(sum[:]),
		})
	}
	sort.Slice(migrations, func(i, j int) bool { return migrations[i].version < migrations[j].version })
	versions := make([]int, len(migrations))
	for i := range migrations {
		versions[i] = migrations[i].version
	}
	if len(migrations) == 0 || versions[0] != 1 {
		return nil, fmt.Errorf("migration versions must be contiguous from 1: %v", versions)
	}
	for i := 1; i < len(migrations); i++ {
		if versions[i] != versions[i-1]+1 {
			return nil, fmt.Errorf("migration versions must be contiguous from 1: %v", versions)
		}
	}
	loadedMigrations = migrations
	return migrations, nil
}

func allDigits(s string) bool {
	for i := range len(s) {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return s != ""
}

// completeStatement mirrors Python's sqlite3.complete_statement: true only
// when a statement is terminated by a top-level semicolon. Input that ends
// without one is incomplete (verified against sqlite3.complete_statement).
func completeStatement(buffer string) bool {
	state := 0 // 0 normal, 1 line comment, 2 block comment, 3 string, 4 quoted ident, 5 bracket ident, 6 backtick ident
	for i := 0; i < len(buffer); i++ {
		c := buffer[i]
		next := byte(0)
		if i+1 < len(buffer) {
			next = buffer[i+1]
		}
		switch state {
		case 1: // line comment
			if c == '\n' {
				state = 0
			}
		case 2: // block comment
			if c == '*' && next == '/' {
				state = 0
				i++
			}
		case 3: // 'string'
			if c == '\'' {
				if next == '\'' {
					i++
				} else {
					state = 0
				}
			}
		case 4: // "quoted ident"
			if c == '"' {
				if next == '"' {
					i++
				} else {
					state = 0
				}
			}
		case 5: // [bracket ident]
			if c == ']' {
				state = 0
			}
		case 6: // `backtick ident`
			if c == '`' {
				state = 0
			}
		default:
			switch {
			case c == '-' && next == '-':
				state = 1
				i++
			case c == '/' && next == '*':
				state = 2
				i++
			case c == '\'':
				state = 3
			case c == '"':
				state = 4
			case c == '[':
				state = 5
			case c == '`':
				state = 6
			case c == ';':
				return true
			}
		}
	}
	return false
}

// splitStatements mirrors migrations._statements: accumulate lines until
// complete, then strip and emit; trailing non-empty buffer is an error.
func splitStatements(sql string) ([]string, error) {
	var statements []string
	buffer := ""
	start := 0
	for i := 0; i <= len(sql); i++ {
		if i == len(sql) || sql[i] == '\n' {
			end := i
			if i < len(sql) {
				end = i + 1 // keep the newline, like splitlines(keepends=True)
			}
			line := sql[start:end]
			start = i + 1
			buffer += line
			if completeStatement(buffer) {
				statement := strings.TrimSpace(buffer)
				if statement != "" {
					statements = append(statements, statement)
				}
				buffer = ""
			}
		}
	}
	if strings.TrimSpace(buffer) != "" {
		return nil, fmt.Errorf("migration ends with an incomplete SQL statement")
	}
	return statements, nil
}

func queryMigrationStatus(db *sql.DB) (migrationStatus, error) {
	migrations, err := loadMigrations()
	if err != nil {
		return migrationStatus{}, err
	}
	if _, err := db.Exec(`
CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at_ms INTEGER NOT NULL
) STRICT`); err != nil {
		return migrationStatus{}, err
	}
	rows, err := db.Query(`SELECT version, name, checksum, applied_at_ms FROM schema_migration ORDER BY version`)
	if err != nil {
		return migrationStatus{}, err
	}
	defer rows.Close()
	known := make(map[int]migration, len(migrations))
	for i := range migrations {
		known[migrations[i].version] = migrations[i]
	}
	var applied []int
	var unknown []int
	for rows.Next() {
		var version int
		var name, checksum string
		var appliedAtMs int64
		if err := rows.Scan(&version, &name, &checksum, &appliedAtMs); err != nil {
			return migrationStatus{}, err
		}
		if _, ok := known[version]; !ok {
			unknown = append(unknown, version)
			continue
		}
		expected := known[version]
		if name != expected.name || checksum != expected.checksum {
			return migrationStatus{}, fmt.Errorf("migration %d does not match the packaged checksum", version)
		}
		applied = append(applied, version)
	}
	if err := rows.Err(); err != nil {
		return migrationStatus{}, err
	}
	if len(unknown) > 0 {
		return migrationStatus{}, fmt.Errorf("database contains unknown migration versions: %v", unknown)
	}
	sort.Ints(applied)
	appliedSet := make(map[int]bool, len(applied))
	for _, version := range applied {
		appliedSet[version] = true
	}
	var pending []int
	for _, m := range migrations {
		if !appliedSet[m.version] {
			pending = append(pending, m.version)
		}
	}
	current := 0
	if len(applied) > 0 {
		current = applied[len(applied)-1]
	}
	return migrationStatus{
		currentVersion: current,
		latestVersion:  migrations[len(migrations)-1].version,
		applied:        applied,
		pending:        pending,
	}, nil
}

// migrate applies every pending migration transactionally, mirroring
// MigrationRunner.migrate: re-check inside the transaction because another
// plugin operation may have applied a version while this one waited for the
// writer lock.
func migrate(db *sql.DB, appliedAtMs int64) error {
	migrations, err := loadMigrations()
	if err != nil {
		return err
	}
	status, err := queryMigrationStatus(db)
	if err != nil {
		return err
	}
	pending := make(map[int]bool, len(status.pending))
	for _, version := range status.pending {
		pending[version] = true
	}
	for i := range migrations {
		m := migrations[i]
		if !pending[m.version] {
			continue
		}
		if err := migrateOne(db, m, appliedAtMs); err != nil {
			return err
		}
	}
	return nil
}

func migrateOne(db *sql.DB, m migration, appliedAtMs int64) error {
	ctx := context.Background()
	conn, err := db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	defer conn.ExecContext(ctx, "ROLLBACK")
	var present int
	err = conn.QueryRowContext(ctx, `SELECT 1 FROM schema_migration WHERE version=?`, m.version).Scan(&present)
	if err == nil {
		// Another operation applied it while this one waited for the lock.
		return nil
	}
	if err != sql.ErrNoRows {
		return err
	}
	statements, err := splitStatements(m.sql)
	if err != nil {
		return err
	}
	for _, statement := range statements {
		if _, err := conn.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("migration %d: %v", m.version, err)
		}
	}
	if _, err := conn.ExecContext(ctx,
		`INSERT INTO schema_migration(version, name, checksum, applied_at_ms) VALUES (?, ?, ?, ?)`,
		m.version, m.name, m.checksum, appliedAtMs); err != nil {
		return err
	}
	_, err = conn.ExecContext(ctx, "COMMIT")
	return err
}
