// Operation profiling — a port of curator/profiling.py for the ported ops.
//
// The raw backend mirrors backend.py's _profiled lifecycle: get_config runs
// inside a trace; when the plugin's profilingEnabled setting is on, a
// profile_trace row is saved with the same columns and a trace_json of the
// same shape (root "plugin" event + recorded spans). The backend process
// handles one operation, so a package-level active trace is safe and matches
// Python's ContextVar default-None semantics.
package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

const (
	maxTraceEvents = 10_000
	maxTraces      = 200
)

type traceEvent struct {
	name       string
	category   string
	startedNs  int64 // perf-counter start, relative to trace.startedNs
	durationNs int64
	details    jVal // optional args object
}

type trace struct {
	name        string
	kind        string
	traceID     string
	startedAtNs int64 // wall clock (time.Now().UnixNano())
	startedNs   int64 // perf counter
	events      []traceEvent
	dropped     int
	status      string // "ok" | "error"
	errorType   string
	durationUs  int64
}

// activeTrace is the current operation's trace, or nil (Python ContextVar).
var activeTrace *trace

func currentTrace() *trace { return activeTrace }

func beginTrace(name, kind string) *trace {
	t := &trace{
		name:        name,
		kind:        kind,
		traceID:     uuid4(),
		startedAtNs: time.Now().UnixNano(),
		startedNs:   time.Now().UnixNano(), // perf_counter_ns equivalent
		status:      "ok",
	}
	activeTrace = t
	return t
}

func endTrace(t *trace) {
	t.durationUs = (time.Now().UnixNano() - t.startedNs) / 1_000
	activeTrace = nil
}

func (t *trace) fail(err error) {
	t.status = "error"
	if err != nil {
		t.errorType = errorTypeName(err)
	}
}

// errorTypeName mirrors Python's type(error).__name__ for the trace status.
// The Go port's failures map onto the Python exception classes the frontend
// recognizes; unclassified errors fall back to RuntimeError.
func errorTypeName(err error) string {
	msg := err.Error()
	switch {
	case strings.HasPrefix(msg, "Stash "):
		return "GraphQLError"
	case strings.Contains(msg, "migration"):
		return "MigrationError"
	}
	return "RuntimeError"
}

func (t *trace) record(category, name string, startedNs, durationNs int64, details jVal) {
	if t == nil {
		return
	}
	if len(t.events) >= maxTraceEvents {
		t.dropped++
		return
	}
	t.events = append(t.events, traceEvent{
		name:       name,
		category:   category,
		startedNs:  startedNs,
		durationNs: durationNs,
		details:    details,
	})
}

// payload mirrors Trace.payload(): the root "plugin" event plus recorded
// spans, as an ordered JSON value serialized with compact separators.
func (t *trace) payload() jVal {
	rootArgs := jvObj(jvKey("status", jvStr(t.status)), jvKey("kind", jvStr(t.kind)))
	if t.errorType != "" {
		rootArgs.set("error_type", jvStr(t.errorType))
	}
	events := jvArr()
	events.arr = append(events.arr, jvObj(
		jvKey("name", jvStr(t.name)),
		jvKey("cat", jvStr("plugin")),
		jvKey("ph", jvStr("X")),
		jvKey("ts", jvInt(t.startedAtNs/1_000)),
		jvKey("dur", jvInt(t.durationUs)),
		jvKey("pid", jvInt(1)),
		jvKey("tid", jvInt(0)),
		jvKey("args", rootArgs),
	))
	for _, event := range t.events {
		item := jvObj(
			jvKey("name", jvStr(event.name)),
			jvKey("cat", jvStr(event.category)),
			jvKey("ph", jvStr("X")),
			jvKey("ts", jvInt((t.startedAtNs+event.startedNs-t.startedNs)/1_000)),
			jvKey("dur", jvInt(maxInt64(0, event.durationNs/1_000))),
			jvKey("pid", jvInt(1)),
			jvKey("tid", jvInt(0)),
		)
		if event.details.kind == jObj && len(event.details.obj) > 0 {
			item.set("args", event.details)
		}
		events.arr = append(events.arr, item)
	}
	if t.dropped > 0 {
		events.arr = append(events.arr, jvObj(
			jvKey("name", jvStr("trace truncated")),
			jvKey("cat", jvStr("plugin")),
			jvKey("ph", jvStr("i")),
			jvKey("s", jvStr("t")),
			jvKey("ts", jvInt(t.startedAtNs/1_000+t.durationUs)),
			jvKey("pid", jvInt(1)),
			jvKey("tid", jvInt(0)),
			jvKey("args", jvObj(jvKey("dropped_events", jvInt(int64(t.dropped))))),
		))
	}
	return jvObj(jvKey("traceEvents", events), jvKey("displayTimeUnit", jvStr("ms")))
}

// saveTrace mirrors curator.profiling.save_trace: insert the row under
// BEGIN IMMEDIATE and trim to the newest MAX_TRACES.
func saveTrace(databasePath string, t *trace) error {
	db, err := openDatabase(databasePath, false, nil)
	if err != nil {
		return err
	}
	defer db.Close()
	if err := execImmediate(db,
		`INSERT INTO profile_trace(
			trace_id, kind, operation, started_at_ms, duration_us, status,
			span_count, truncated, trace_json
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		t.traceID, t.kind, t.name, t.startedAtNs/1_000_000, t.durationUs, t.status,
		len(t.events), boolToInt(t.dropped > 0), t.payload().marshalCompact(),
	); err != nil {
		return err
	}
	_, err = db.Exec(`DELETE FROM profile_trace WHERE trace_id IN (
		SELECT trace_id FROM profile_trace
		ORDER BY started_at_ms DESC, rowid DESC LIMIT -1 OFFSET ?)`, maxTraces)
	return err
}

func boolToInt(v bool) int64 {
	if v {
		return 1
	}
	return 0
}

func maxInt64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

// uuid4 builds a random v4 UUID without external dependencies.
func uuid4() string {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		panic(err) // crypto/rand failure is unrecoverable
	}
	raw[6] = (raw[6] & 0x0f) | 0x40
	raw[8] = (raw[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		raw[0:4], raw[4:6], raw[6:8], raw[8:10], raw[10:16])
}

// warnLog mirrors backend.py's _log("w", message): the stderr progress-marker
// protocol, which the plugin logs as a warning.
func warnLog(message string) {
	fmt.Fprintf(os.Stderr, "\x01w\x02%s\n", message)
}

var fromIntoUpdateTable = regexp.MustCompile(`(?i)\b(?:FROM|INTO|UPDATE|TABLE)\s+([\w.]+)`)

// sqlSpanDetails mirrors curator.storage.database._sql_details: the span name
// is "COMMAND TARGET" when a FROM/INTO/UPDATE/TABLE clause is present, else
// the command; the details carry the whitespace-normalized statement.
func sqlSpanDetails(statement string) (string, jVal) {
	normalized := strings.Join(strings.Fields(statement), " ")
	if len(normalized) > 1_000 {
		normalized = normalized[:1_000]
	}
	command := "SQL"
	if first, _, found := strings.Cut(normalized, " "); found && first != "" {
		command = strings.ToUpper(first)
	} else if normalized != "" {
		command = strings.ToUpper(normalized)
	}
	name := command
	if match := fromIntoUpdateTable.FindStringSubmatch(normalized); match != nil {
		name = command + " " + match[1]
	}
	return name, jvObj(jvKey("statement", jvStr(normalized)))
}

// tracedDB wraps *sql.DB so every statement executed under an active trace
// records a sqlite span, matching Python's ProfiledConnection.
type tracedDB struct {
	db *sql.DB
	t  *trace
}

func (d *tracedDB) Conn(ctx context.Context) (*sql.Conn, error) { return d.db.Conn(ctx) }
func (d *tracedDB) Close() error                                { return d.db.Close() }

func (d *tracedDB) Exec(query string, args ...any) (sql.Result, error) {
	name, details := sqlSpanDetails(query)
	started := time.Now().UnixNano()
	result, err := d.db.Exec(query, args...)
	d.t.record("sqlite", name, started, time.Now().UnixNano()-started, details)
	return result, err
}

func (d *tracedDB) Query(query string, args ...any) (*sql.Rows, error) {
	name, details := sqlSpanDetails(query)
	started := time.Now().UnixNano()
	rows, err := d.db.Query(query, args...)
	d.t.record("sqlite", name, started, time.Now().UnixNano()-started, details)
	return rows, err
}

func (d *tracedDB) QueryRow(query string, args ...any) *sql.Row {
	name, details := sqlSpanDetails(query)
	started := time.Now().UnixNano()
	row := d.db.QueryRow(query, args...)
	// database/sql defers execution to Scan, so record eagerly like Python's
	// execute (which binds immediately).
	d.t.record("sqlite", name, started, time.Now().UnixNano()-started, details)
	return row
}
