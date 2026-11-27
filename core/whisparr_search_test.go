package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const sweepNow int64 = 1_800_000_000_000 // 2027-01-15

// sweepStub is a Whisparr with one scene per sweep outcome.
type sweepStub struct {
	indexerStatus string // GET /indexerstatus body
	commands      string // GET /command body
	searches      []string
	fail          bool
	missing       map[string]bool // "METHOD path" answering 404
}

func (stub *sweepStub) serve(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	if stub.fail {
		w.WriteHeader(http.StatusInternalServerError)
		io.WriteString(w, `{"message":"Boom"}`)
		return
	}
	if stub.missing[r.Method+" "+r.URL.Path] {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	switch {
	case r.URL.Path == "/api/v3/indexerstatus":
		io.WriteString(w, stub.indexerStatus)
	case r.Method == "GET" && r.URL.Path == "/api/v3/command":
		io.WriteString(w, stub.commands)
	case r.URL.Path == "/api/v3/movie":
		io.WriteString(w, `[
 {"id":1,"stashId":"best","hasFile":false},
 {"id":5,"stashId":"older","hasFile":false},
 {"id":6,"stashId":"newer","hasFile":false,"releaseDate":"2026-01-01"},
 {"id":2,"stashId":"downloading","hasFile":false},
 {"id":3,"stashId":"in-library","hasFile":false},
 {"id":4,"stashId":"grabbed","hasFile":true},
 {"id":7,"stashId":"unreleased","hasFile":false,"releaseDate":"2030-01-01T00:00:00Z"},
 {"id":8,"stashId":"stale","hasFile":false},
 {"id":9,"stashId":"not-due","hasFile":false}
]`)
	case r.URL.Path == "/api/v3/queue":
		io.WriteString(w, `{"totalRecords":1,"records":[{"movieId":2}]}`)
	case r.Method == "POST" && r.URL.Path == "/api/v3/command":
		stub.searches = append(stub.searches, string(body))
		io.WriteString(w, `{"id":1}`)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func sweepFixture(t *testing.T) (*sweepStub, jVal, dbx) {
	t.Helper()
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	day := int64(24 * 3_600_000)
	rows := []struct {
		id      string
		movie   int64
		added   int64
		nextDue int64
	}{
		{"best", 1, sweepNow - day, sweepNow - 1},
		{"older", 5, sweepNow - day, sweepNow - 3_000},
		{"newer", 6, sweepNow - day, sweepNow - 2_000},
		{"downloading", 2, sweepNow - day, sweepNow - 1},
		{"in-library", 3, sweepNow - day, sweepNow - 1},
		{"grabbed", 4, sweepNow - day, sweepNow - 1},
		{"unreleased", 7, sweepNow - day, sweepNow - 1},
		{"stale", 8, sweepNow - 61*day, sweepNow - 1},
		{"not-due", 9, sweepNow - day, sweepNow + 1_000},
		{"gone", 99, sweepNow - day, sweepNow - 1},
	}
	for _, row := range rows {
		if err := queueWhisparrSearch(db, row.id, row.movie, row.added); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec(`UPDATE whisparr_search SET next_due_at_ms=? WHERE external_id=?`, row.nextDue, row.id); err != nil {
			t.Fatal(err)
		}
	}
	for _, statement := range []string{
		`INSERT INTO local_scene_match(scene_id, kind, value) VALUES ('42', 'stashdb_id', 'in-library')`,
		`INSERT INTO external_entity(entity_type, external_id, payload_json, score, fetched_at_ms) VALUES ('scene', 'best', '{}', 0.9, 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	stub := &sweepStub{indexerStatus: `[]`, commands: `[]`}
	server := httptest.NewServer(http.HandlerFunc(stub.serve))
	t.Cleanup(server.Close)
	settings := jvObj(jvKey("whisparrUrl", jvStr(server.URL)), jvKey("whisparrApiKey", jvStr("key")))
	return stub, settings, db
}

func sweepConfig(batch int) whisparrSweepConfig {
	return whisparrSweepConfig{enabled: true, intervalMs: 15 * 60_000, batchSize: batch, giveUpMs: 60 * 24 * 3_600_000}
}

func searchStates(t *testing.T, db dbx) map[string]string {
	t.Helper()
	rows, err := db.Query(`SELECT external_id, state, attempts, next_due_at_ms FROM whisparr_search`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id, state string
		var attempts, due int64
		if err := rows.Scan(&id, &state, &attempts, &due); err != nil {
			t.Fatal(err)
		}
		out[id] = state
		if state == "active" {
			switch {
			case attempts > 0:
				out[id] += "/searched+" + formatHours(due-sweepNow)
			case due > sweepNow:
				out[id] += "/waiting"
			}
		}
	}
	return out
}

func formatHours(ms int64) string {
	return strings.TrimSuffix(jvFloat(float64(ms)/3_600_000).marshalCompact(), ".0") + "h"
}

func TestWhisparrSweepSearchesOneBatchAndSettlesTheRest(t *testing.T) {
	stub, settings, db := sweepFixture(t)
	summary, err := runWhisparrSweep(db, settings, sweepConfig(2), sweepNow)
	if err != nil {
		t.Fatal(err)
	}
	// The scored scene goes first, then the longest-waiting unscored one.
	if strings.Join(stub.searches, "|") != `{"name":"MoviesSearch","movieIds":[1,5]}` {
		t.Fatalf("searches = %v", stub.searches)
	}
	if got := summary.marshalSortedKeys(); got != `{"active":6,"done":2,"gave_up":1,"removed":1,"searched":2,"status":"searched"}` {
		t.Fatalf("summary = %s", got)
	}
	want := map[string]string{
		"best":        "active/searched+2h",
		"older":       "active/searched+2h",
		"newer":       "active", // released and due, but the batch is full
		"downloading": "active/waiting",
		"in-library":  "done",
		"grabbed":     "done",
		"unreleased":  "active/waiting",
		"stale":       "gave_up",
		"not-due":     "active/waiting",
	}
	got := searchStates(t, db)
	for id, state := range want {
		if got[id] != state {
			t.Errorf("%s = %q, want %q", id, got[id], state)
		}
	}
	if _, ok := got["gone"]; ok || len(got) != len(want) {
		t.Fatalf("states = %v", got)
	}
	var release int64
	if err := db.QueryRow(`SELECT next_due_at_ms FROM whisparr_search WHERE external_id='unreleased'`).Scan(&release); err != nil || release != 1_893_456_000_000 {
		t.Fatalf("unreleased waits until %d, %v", release, err)
	}
	lastRun, paused, err := whisparrSweepState(db)
	if err != nil || lastRun != sweepNow || paused != 0 {
		t.Fatalf("sweep state = %d %d %v", lastRun, paused, err)
	}
}

func TestWhisparrSweepRetriesOnAWideningSchedule(t *testing.T) {
	want := []int64{2, 6, 24, 24, 24, 168, 168}
	for i, hours := range want {
		if got := whisparrSearchRetryAfter(int64(i + 1)); got != hours*3_600_000 {
			t.Fatalf("after search %d: %dms, want %dh", i+1, got, hours)
		}
	}
}

func TestWhisparrSweepWaitsOutIndexerBackoffAndRunningSearches(t *testing.T) {
	stub, settings, db := sweepFixture(t)
	stub.indexerStatus = `[{"indexerId":1,"disabledTill":"2027-01-15T09:00:00Z"},{"indexerId":2,"disabledTill":"2020-01-01T00:00:00Z"}]`
	summary, err := runWhisparrSweep(db, settings, sweepConfig(3), sweepNow)
	if err != nil || summary.get("status").asString() != "indexer_backoff" {
		t.Fatalf("summary = %s, %v", summary.marshalCompact(), err)
	}
	_, paused, _ := whisparrSweepState(db)
	if paused != 1_800_003_600_000 {
		t.Fatalf("paused until %d", paused)
	}
	config := jvObj(jvKey("whisparr_sweep_enabled", jvBool(true)), jvKey("whisparr_sweep_interval_minutes", jvInt(15)))
	if due, _ := whisparrSweepDue(db, config, paused-1); due {
		t.Fatal("sweep due during indexer backoff")
	}
	if due, _ := whisparrSweepDue(db, config, paused); !due {
		t.Fatal("sweep not due after the backoff")
	}

	stub.indexerStatus = `[]`
	stub.commands = `[{"name":"MoviesSearch","status":"started"}]`
	summary, err = runWhisparrSweep(db, settings, sweepConfig(3), sweepNow)
	if err != nil || summary.get("status").asString() != "search_running" {
		t.Fatalf("summary = %s, %v", summary.marshalCompact(), err)
	}
	if len(stub.searches) != 0 {
		t.Fatalf("searched while Whisparr was busy: %v", stub.searches)
	}
}

func TestWhisparrSweepBacksOffWithoutFailingWhenWhisparrIsDown(t *testing.T) {
	stub, settings, db := sweepFixture(t)
	stub.fail = true
	summary, err := taskWhisparrSearch(db, settings)
	if err != nil || summary.get("status").asString() != "error" || !strings.Contains(summary.get("error").asString(), "HTTP 500") {
		t.Fatalf("summary = %s, %v", summary.marshalCompact(), err)
	}
	var lastErr string
	if err := db.QueryRow(`SELECT last_error FROM whisparr_sweep`).Scan(&lastErr); err != nil || !strings.Contains(lastErr, "Boom") {
		t.Fatalf("last_error = %q, %v", lastErr, err)
	}
}

func TestWhisparrSweepKeepsTheDaemonAliveOnlyWhileScenesWait(t *testing.T) {
	_, _, db := sweepFixture(t)
	alive, err := schedulerStayAlive(db, sweepNow)
	if err != nil || !alive {
		t.Fatalf("stay alive = %v, %v", alive, err)
	}
	if _, err := db.Exec(`UPDATE whisparr_search SET state='done'`); err != nil {
		t.Fatal(err)
	}
	if alive, err := schedulerStayAlive(db, sweepNow); err != nil || alive {
		t.Fatalf("stay alive with nothing waiting = %v, %v", alive, err)
	}
	if active, _ := whisparrSearchActive(db, jvObj(jvKey("whisparr_sweep_enabled", jvBool(false)))); active {
		t.Fatal("disabled rotation reported active")
	}
}

func TestWhisparrSweepTickQueuesAJobThatRunsWhileBrowsing(t *testing.T) {
	_, _, db := sweepFixture(t)
	queued, err := whisparrSweepTick(db, jvObj(jvKey("args", jvObj())), sweepNow)
	if err != nil || !queued {
		t.Fatalf("queued = %v, %v", queued, err)
	}
	if again, _ := whisparrSweepTick(db, jvObj(jvKey("args", jvObj())), sweepNow); again {
		t.Fatal("a second sweep was queued behind the first")
	}
	jobID, _, _, mode, err := claimQueuedJob(db, true) // a Curator page is open
	if err != nil || jobID == "" || mode != whisparrSearchTask {
		t.Fatalf("claimed %q %q, %v", jobID, mode, err)
	}
}

func TestWhisparrOverviewShowsAndManagesTheRotation(t *testing.T) {
	stub, path, settings, db := whisparrOverviewFixture(t)
	// rotate and resume wake the daemon; a real one would hold the temp
	// dir's log open and break its cleanup on Windows.
	prevSpawn := spawnWorkerFn
	spawnWorkerFn = func(string) error { return nil }
	defer func() { spawnWorkerFn = prevSpawn }()
	run := func(args jVal) (jVal, error) {
		args.set("database_path", jvStr(path))
		payload := jvObj(jvKey("args", args), jvKey("server_connection", jvObj()))
		return whisparrActionBody(t.TempDir(), payload, settings)
	}
	// "Add to rolling search" pairs each Whisparr id with its StashDB id;
	// an id without a StashDB id is skipped.
	result, err := run(jvObj(jvKey("action", jvStr("rotate")),
		jvKey("whisparr_ids", jvArr(jvInt(1), jvInt(2), jvInt(1))),
		jvKey("stashdb_ids", jvArr(jvStr("s-missing"), jvStr(""), jvStr("s-missing")))))
	if err != nil || pythonInt(result.get("count")) != 1 {
		t.Fatalf("rotate = %s, %v", result.marshalCompact(), err)
	}
	if _, err := run(jvObj(jvKey("action", jvStr("rotate")), jvKey("whisparr_ids", jvArr(jvInt(1))), jvKey("stashdb_ids", jvArr()))); err == nil {
		t.Fatal("unpaired ids accepted")
	}
	if err := recordWhisparrSweep(db, 5_000, 0, "Whisparr rejected the request (HTTP 500)"); err != nil {
		t.Fatal(err)
	}

	overview, err := getWhisparrOverviewBody(t.TempDir(), taskPayload(path, "get_whisparr_overview"), settings)
	if err != nil {
		t.Fatal(err)
	}
	summary := overview.get("rotation")
	if !summary.get("enabled").truthy() || pythonInt(summary.get("active")) != 1 || pythonInt(summary.get("batch_size")) != 3 ||
		pythonInt(summary.get("next_sweep_at_ms")) != 5_000+15*60_000 || !strings.Contains(summary.get("last_error").asString(), "HTTP 500") {
		t.Fatalf("rotation = %s", summary.marshalCompact())
	}
	for _, item := range overview.get("items").arr {
		rotation := item.get("rotation")
		if item.get("stashdb_id").asString() == "s-missing" {
			if rotation.get("state").asString() != "active" || pythonInt(rotation.get("attempts")) != 0 || rotation.get("last_searched_at_ms").kind != jNull {
				t.Fatalf("missing scene rotation = %s", rotation.marshalCompact())
			}
		} else if rotation.kind != jNull {
			t.Fatalf("%s has rotation %s", item.get("title").asString(), rotation.marshalCompact())
		}
	}

	if _, err := run(jvObj(jvKey("action", jvStr("stop")), jvKey("whisparr_ids", jvArr(jvInt(1))), jvKey("stashdb_ids", jvArr(jvStr("s-missing"))))); err != nil {
		t.Fatal(err)
	}
	var state string
	if err := db.QueryRow(`SELECT state FROM whisparr_search WHERE external_id='s-missing'`).Scan(&state); err != nil || state != "stopped" {
		t.Fatalf("state = %q, %v", state, err)
	}
	if len(stub.calls) != 0 {
		t.Fatalf("rotation actions reached Whisparr: %v", stub.calls)
	}
}

func TestWhisparrSweepSkipsChecksAWhisparrVersionLacks(t *testing.T) {
	stub, settings, db := sweepFixture(t)
	stub.missing = map[string]bool{"GET /api/v3/indexerstatus": true, "GET /api/v3/command": true}
	summary, err := runWhisparrSweep(db, settings, sweepConfig(2), sweepNow)
	if err != nil || summary.get("status").asString() != "searched" || len(stub.searches) != 1 {
		t.Fatalf("summary = %s, %v, searches %v", summary.marshalCompact(), err, stub.searches)
	}
	// A required endpoint missing is still an error, and names the endpoint.
	stub.missing["GET /api/v3/movie"] = true
	summary, err = taskWhisparrSearch(db, settings)
	if err != nil || !strings.HasPrefix(summary.get("error").asString(), "GET /movie: Whisparr rejected the request (HTTP 404)") {
		t.Fatalf("summary = %s, %v", summary.marshalCompact(), err)
	}
	// "Try now" lifts the pause so the next tick runs a round.
	if _, paused, _ := whisparrSweepState(db); paused <= nowMs() {
		t.Fatalf("no pause after an error: %d", paused)
	}
	if err := resumeWhisparrSweep(db); err != nil {
		t.Fatal(err)
	}
	if lastRun, paused, err := whisparrSweepState(db); err != nil || lastRun != 0 || paused != 0 {
		t.Fatalf("after resume: last run %d, paused %d, %v", lastRun, paused, err)
	}
}
