// Batch artifact inserts — rewrite per-row INSERT loops into one multi-row
// `INSERT ... VALUES (...),(...)` statement per chunk, cutting the per-row
// cgo Exec/bind overhead across the build's ~1.7M artifact rows (the
// measured feature_database_writing / database_writing hot spots). The
// differential gate compares artifact rows, not SQL, so the row content is
// unchanged; only the statement shape differs.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
)

// maxVariableCount is SQLite's default bound-parameter limit; the chunk size
// is capped so columns x rows stays under it.
const maxVariableCount = 30_000

// multiRowInsert expands an `INSERT INTO t(...) VALUES (?, ?)` statement into
// one with the VALUES tuple repeated n times. Returns an error for
// statements without a single repeatable tuple.
func multiRowInsert(statement string, n int) (string, error) {
	if n <= 1 {
		return statement, nil
	}
	valuesIdx := strings.Index(statement, "VALUES")
	if valuesIdx < 0 {
		return "", fmt.Errorf("no VALUES clause")
	}
	prefix := statement[:valuesIdx]
	rest := strings.TrimSpace(statement[valuesIdx+len("VALUES"):])
	if !strings.HasPrefix(rest, "(") {
		return "", fmt.Errorf("unexpected VALUES form")
	}
	depth := 0
	closeIdx := -1
	for i, r := range rest {
		switch r {
		case '(':
			depth++
		case ')':
			depth--
			if depth == 0 {
				closeIdx = i
				break
			}
		}
		if closeIdx >= 0 {
			break
		}
	}
	if closeIdx < 0 {
		return "", fmt.Errorf("unbalanced VALUES tuple")
	}
	tuple := rest[:closeIdx+1]
	tail := strings.TrimSpace(rest[closeIdx+1:])
	values := strings.Repeat(tuple+",", n-1) + tuple
	out := prefix + "VALUES " + values
	if tail != "" {
		out += " " + tail
	}
	return out, nil
}

// execMultiRow inserts rows on conn with one multi-row statement per chunk
// (falling back to per-row execution for statements without a repeatable
// VALUES tuple). The chunk cap keeps the bound variables under SQLite's
// limit. The caller owns the transaction.
func execMultiRow(conn *sql.Conn, statement string, rows [][]any) error {
	if len(rows) == 0 {
		return nil
	}
	columns := len(rows[0])
	chunk := len(rows)
	if chunk > maxVariableCount/columns {
		chunk = maxVariableCount / columns
	}
	if chunk < 1 {
		chunk = 1
	}
	for start := 0; start < len(rows); start += chunk {
		end := start + chunk
		if end > len(rows) {
			end = len(rows)
		}
		batch := rows[start:end]
		args := make([]any, 0, len(batch)*columns)
		for _, row := range batch {
			args = append(args, row...)
		}
		stmt := statement
		if len(batch) > 1 {
			if expanded, err := multiRowInsert(statement, len(batch)); err == nil {
				stmt = expanded
			}
		}
		// Issue #186 audit: a statement that reports success without affecting
		// the expected rows (a silent no-op or a partially applied write) must
		// not look like a completed insert — the model build would publish an
		// artifact with missing rows.
		res, err := conn.ExecContext(context.Background(), stmt, args...)
		if err != nil {
			return err
		}
		affected, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if affected != int64(len(batch)) {
			return fmt.Errorf("execMultiRow: statement affected %d rows, want %d", affected, len(batch))
		}
	}
	return nil
}

// insertArtifactRows batches rows into the artifact with one transaction per
// batch of 1000 (mirroring _publish's insert_rows), each batch as a single
// multi-row statement.
func insertArtifactRows(artifact dbx, statement string, rows [][]any) error {
	if len(rows) == 0 {
		return nil
	}
	columns := len(rows[0])
	chunk := 1000
	if chunk > maxVariableCount/columns {
		chunk = maxVariableCount / columns
	}
	if chunk < 1 {
		chunk = 1
	}
	for start := 0; start < len(rows); start += chunk {
		end := start + chunk
		if end > len(rows) {
			end = len(rows)
		}
		batch := rows[start:end]
		if err := withTxn(artifact, func(conn *sql.Conn) error {
			return execMultiRow(conn, statement, batch)
		}); err != nil {
			return err
		}
	}
	return nil
}
