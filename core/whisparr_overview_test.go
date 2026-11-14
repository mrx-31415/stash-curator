package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A Whisparr stub with one scene per status, plus a recorder for actions.
type whisparrStub struct {
	calls []string
}

func (stub *whisparrStub) serve(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	if r.Header.Get("X-Api-Key") != "key" {
		w.WriteHeader(http.StatusUnauthorized)
		io.WriteString(w, `{"message":"Unauthorized"}`)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	switch {
	case r.Method == "GET" && r.URL.Path == "/api/v3/movie":
		io.WriteString(w, `[
 {"id":1,"title":"Missing","stashId":"s-missing","hasFile":false,"monitored":false,"added":"2026-11-01T10:00:00Z","images":[{"coverType":"poster","remoteUrl":"http://img/p"},{"coverType":"screenshot","remoteUrl":"http://img/s"}]},
 {"id":2,"title":"Downloading","stashId":"s-down","hasFile":false,"monitored":true},
 {"id":3,"title":"Grabbed","foreignId":"s-grabbed","hasFile":true,"sizeOnDisk":1234},
 {"id":4,"title":"Owned","stashId":"s-owned","hasFile":true}
]`)
	case r.Method == "GET" && r.URL.Path == "/api/v3/queue":
		io.WriteString(w, `{"totalRecords":1,"records":[{"movieId":2,"status":"Downloading","size":200,"sizeleft":50,"timeleft":"00:05:00","statusMessages":[{"messages":["slow peer"]}]}]}`)
	default:
		stub.calls = append(stub.calls, r.Method+" "+r.URL.Path+" "+string(body))
		if r.Method == "DELETE" {
			return // the editor delete answers 200 with no body
		}
		io.WriteString(w, `{}`)
	}
}

func whisparrOverviewFixture(t *testing.T) (*whisparrStub, string, jVal, dbx) {
	t.Helper()
	db, path := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	for _, statement := range []string{
		`INSERT INTO application_meta(key, value) VALUES ('local_scene_matches_ready', 'https://stashdb.org/graphql')`,
		`INSERT INTO local_scene_match(scene_id, kind, value) VALUES ('42', 'stashdb_id', 's-owned')`,
		`INSERT INTO external_whisparr_sent(endpoint, external_id, sent_at_ms) VALUES ('https://stashdb.org/graphql', 's-missing', 7)`,
		`INSERT INTO external_entity(entity_type, external_id, payload_json, score, fetched_at_ms) VALUES ('scene', 's-missing', '{}', 0.75, 1)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	stub := &whisparrStub{}
	server := httptest.NewServer(http.HandlerFunc(stub.serve))
	t.Cleanup(server.Close)
	settings := jvObj(jvKey("whisparrUrl", jvStr(server.URL+"/")), jvKey("whisparrApiKey", jvStr("key")))
	return stub, path, settings, db
}

func TestWhisparrOverviewClassifiesScenesAgainstTheLibrary(t *testing.T) {
	_, path, settings, _ := whisparrOverviewFixture(t)
	result, err := getWhisparrOverviewBody(t.TempDir(), taskPayload(path, "get_whisparr_overview"), settings)
	if err != nil {
		t.Fatal(err)
	}
	if got := result.get("counts").marshalCompact(); got != `{"missing":1,"downloading":1,"not_in_stash":1,"in_library":1}` {
		t.Fatalf("counts = %s", got)
	}
	if !result.get("library_ready").truthy() {
		t.Fatal("library matches should be ready")
	}
	byTitle := map[string]jVal{}
	for _, item := range result.get("items").arr {
		byTitle[item.get("title").asString()] = item
	}
	missing := byTitle["Missing"]
	if missing.get("status").asString() != "missing" || missing.get("image").asString() != "http://img/s" ||
		pythonInt(missing.get("sent_at_ms")) != 7 || missing.get("score").marshalCompact() != "0.75" {
		t.Fatalf("missing = %s", missing.marshalCompact())
	}
	queue := byTitle["Downloading"].get("queue")
	if queue.get("progress").marshalCompact() != "0.75" || queue.get("problem").asString() != "slow peer" || queue.get("state").asString() != "downloading" {
		t.Fatalf("queue = %s", queue.marshalCompact())
	}
	if grabbed := byTitle["Grabbed"]; grabbed.get("status").asString() != "not_in_stash" || grabbed.get("stashdb_id").asString() != "s-grabbed" {
		t.Fatalf("grabbed = %s", grabbed.marshalCompact())
	}
	if owned := byTitle["Owned"]; owned.get("local_scene_id").asString() != "42" || owned.get("sent_at_ms").kind != jNull {
		t.Fatalf("owned = %s", owned.marshalCompact())
	}
}

func TestWhisparrActionsNeverDeleteFiles(t *testing.T) {
	stub, path, settings, db := whisparrOverviewFixture(t)
	run := func(args jVal) (jVal, error) {
		args.set("database_path", jvStr(path))
		payload := jvObj(jvKey("args", args), jvKey("server_connection", jvObj()))
		return whisparrActionBody(t.TempDir(), payload, settings)
	}
	ids := jvArr(jvInt(1), jvInt(1), jvInt(3))
	if _, err := run(jvObj(jvKey("action", jvStr("search")), jvKey("whisparr_ids", ids))); err != nil {
		t.Fatal(err)
	}
	if _, err := run(jvObj(jvKey("action", jvStr("monitor")), jvKey("whisparr_ids", ids))); err != nil {
		t.Fatal(err)
	}
	result, err := run(jvObj(jvKey("action", jvStr("remove")), jvKey("whisparr_ids", ids), jvKey("stashdb_ids", jvArr(jvStr("s-missing")))))
	if err != nil || pythonInt(result.get("count")) != 2 {
		t.Fatalf("remove = %s, %v", result.marshalCompact(), err)
	}
	want := []string{
		`POST /api/v3/command {"name":"MoviesSearch","movieIds":[1,3]}`,
		`PUT /api/v3/movie/editor {"movieIds":[1,3],"monitored":true}`,
		`DELETE /api/v3/movie/editor {"movieIds":[1,3],"deleteFiles":false,"addImportExclusion":false}`,
	}
	if strings.Join(stub.calls, "\n") != strings.Join(want, "\n") {
		t.Fatalf("calls:\n%s", strings.Join(stub.calls, "\n"))
	}
	var sent int
	if err := db.QueryRow(`SELECT COUNT(*) FROM external_whisparr_sent`).Scan(&sent); err != nil || sent != 0 {
		t.Fatalf("removed scene still recorded as sent: %d, %v", sent, err)
	}
	for _, bad := range []jVal{
		jvObj(jvKey("action", jvStr("delete_files")), jvKey("whisparr_ids", ids)),
		jvObj(jvKey("action", jvStr("search")), jvKey("whisparr_ids", jvArr())),
		jvObj(jvKey("action", jvStr("search")), jvKey("whisparr_ids", jvArr(jvInt(0)))),
	} {
		if _, err := run(bad); err == nil {
			t.Fatalf("accepted %s", bad.marshalCompact())
		}
	}
	if len(stub.calls) != 3 {
		t.Fatalf("rejected actions reached Whisparr: %v", stub.calls)
	}
}
