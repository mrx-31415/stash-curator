package main

import (
	"errors"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestTracePayloadStructure(t *testing.T) {
	trace := beginTrace("get_config", "operation")
	defer endTrace(trace)
	started := time.Now().UnixNano()
	trace.record("stash", "CuratorPluginSettings", started, 1_500_000, jvNull())
	name, details := sqlSpanDetails("SELECT config_json, updated_at_ms FROM curator_config WHERE singleton = 1")
	trace.record("sqlite", name, started, 700_000, details)
	endTrace(trace)

	payload := trace.payload()
	root := payload.get("traceEvents").arr[0]
	if got := root.get("name").s; got != "get_config" {
		t.Errorf("root name = %q", got)
	}
	if got := root.get("cat").s; got != "plugin" {
		t.Errorf("root cat = %q", got)
	}
	args := root.get("args")
	if args.get("status").s != "ok" || args.get("kind").s != "operation" {
		t.Errorf("root args = %s", args.marshalCompact())
	}
	if len(payload.get("traceEvents").arr) != 3 {
		t.Fatalf("expected 3 events, got %d", len(payload.get("traceEvents").arr))
	}
	span := payload.get("traceEvents").arr[1]
	if span.get("name").s != "CuratorPluginSettings" || span.get("cat").s != "stash" {
		t.Errorf("stash span = %s", span.marshalCompact())
	}
	sqlite := payload.get("traceEvents").arr[2]
	if sqlite.get("name").s != "SELECT curator_config" {
		t.Errorf("sqlite span name = %q", sqlite.get("name").s)
	}
	if got := sqlite.get("args").get("statement").s; !strings.Contains(got, "FROM curator_config") {
		t.Errorf("sqlite span details = %q", got)
	}
	if payload.get("displayTimeUnit").s != "ms" {
		t.Errorf("displayTimeUnit = %q", payload.get("displayTimeUnit").s)
	}
	// Compact serialization must be valid JSON (profile_trace has
	// json_valid(trace_json)).
	serialized := payload.marshalCompact()
	if _, err := parseJSON([]byte(serialized)); err != nil {
		t.Errorf("trace_json is not valid JSON: %v", err)
	}
}

func TestTraceFailureStatus(t *testing.T) {
	trace := beginTrace("get_config", "operation")
	trace.fail(errors.New("Stash request failed: boom"))
	endTrace(trace)
	root := trace.payload().get("traceEvents").arr[0]
	args := root.get("args")
	if args.get("status").s != "error" {
		t.Errorf("status = %q", args.get("status").s)
	}
	if args.get("error_type").s != "GraphQLError" {
		t.Errorf("error_type = %q", args.get("error_type").s)
	}
}

func TestSaveTraceAndRetention(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	path := mustDatabasePath(t, db)
	for i := 0; i < maxTraces+1; i++ {
		trace := beginTrace("get_config", "operation")
		trace.record("sqlite", "SELECT 1", time.Now().UnixNano(), 1000, jvNull())
		endTrace(trace)
		if err := saveTrace(path, trace); err != nil {
			t.Fatalf("saveTrace %d: %v", i, err)
		}
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM profile_trace`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != maxTraces {
		t.Fatalf("retention: %d rows, want %d", count, maxTraces)
	}
	var traceJSON string
	if err := db.QueryRow(`SELECT trace_json FROM profile_trace LIMIT 1`).Scan(&traceJSON); err != nil {
		t.Fatal(err)
	}
	parsed, err := parseJSON([]byte(traceJSON))
	if err != nil {
		t.Fatalf("stored trace_json invalid: %v", err)
	}
	if len(parsed.get("traceEvents").arr) != 2 {
		t.Errorf("stored trace has %d events", len(parsed.get("traceEvents").arr))
	}
}

func TestSQLSpanDetails(t *testing.T) {
	cases := []struct {
		statement string
		name      string
	}{
		{"SELECT config_json, updated_at_ms FROM curator_config WHERE singleton=1", "SELECT curator_config"},
		{"PRAGMA foreign_keys = ON", "PRAGMA"},
		{"INSERT INTO schema_migration(version) VALUES (1)", "INSERT schema_migration"},
		{"UPDATE curator_config SET config_json=? WHERE singleton=1", "UPDATE curator_config"},
		{"CREATE TABLE schema_migration (version INTEGER)", "CREATE schema_migration"},
		{"BEGIN IMMEDIATE", "BEGIN"},
	}
	for _, c := range cases {
		name, _ := sqlSpanDetails(c.statement)
		if name != c.name {
			t.Errorf("sqlSpanDetails(%q) = %q, want %q", c.statement, name, c.name)
		}
	}
}

func TestUUID4(t *testing.T) {
	re := regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	for range 10 {
		if id := uuid4(); !re.MatchString(id) {
			t.Errorf("uuid4() = %q", id)
		}
	}
}
