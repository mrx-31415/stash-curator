package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestExpandInitializesLocalMatchesInWorker(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"data":{"findScenes":{"count":1,"scenes":[{"id":"1","stash_ids":[{"endpoint":"https://stashdb.org/graphql","stash_id":"owned"}]}]}}}`)
	}))
	defer server.Close()
	u, _ := url.Parse(server.URL)
	port, _ := strconv.Atoi(u.Port())
	payload := taskPayload(path, "get_expand")
	payload.set("server_connection", jvObj(jvKey("Host", jvStr(u.Hostname())), jvKey("Port", jvInt(int64(port)))))
	pluginDir := t.TempDir()
	previousSpawn := spawnWorkerFn
	spawnWorkerFn = func(string) error { return nil }
	defer func() { spawnWorkerFn = previousSpawn }()
	for range 2 {
		result, err := getExpandBody(pluginDir, payload, jvObj())
		if err != nil || !result.get("initializing").truthy() || result.get("ready").truthy() || len(result.get("items").arr) != 0 {
			t.Fatalf("initializing response: %s, %v", result.marshalCompact(), err)
		}
	}
	var jobs int
	db.QueryRow(`SELECT COUNT(*) FROM curator_job WHERE job_type='local-matches'`).Scan(&jobs)
	if calls != 0 || jobs != 1 {
		t.Fatalf("browse scanned Stash or duplicated the job: calls=%d jobs=%d", calls, jobs)
	}
	writer, err := openDatabase(path, false, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Exec(`BEGIN IMMEDIATE`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`PRAGMA busy_timeout=1`); err != nil {
		t.Fatal(err)
	}
	ready, pollErr := ensureLocalSceneMatches(pluginDir, payload, jvObj(), db)
	writer.Exec(`ROLLBACK`)
	writer.Close()
	if pollErr != nil || ready {
		t.Fatalf("poll blocked on worker write lock: %v", pollErr)
	}
	if _, err := db.Exec(`UPDATE curator_job SET state='failed', error='test failure'`); err != nil {
		t.Fatal(err)
	}
	if _, err := getExpandBody(pluginDir, payload, jvObj()); err == nil || !strings.Contains(err.Error(), "test failure") {
		t.Fatalf("worker failure not surfaced: %v", err)
	}
	trace := beginTrace("worker-local-matches", "task")
	_, err = runTaskMode(db, pluginDir, payload, localMatchTask, jvObj(), 1)
	endTrace(trace)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"local_matches.fetch", "local_matches.index"} {
		found := false
		for _, event := range trace.events {
			found = found || event.name == name
		}
		if !found {
			t.Fatalf("missing profile span %s", name)
		}
	}
	result, err := getExpandBody(pluginDir, payload, jvObj())
	if err != nil || result.get("initializing").truthy() || calls != 1 {
		t.Fatalf("completed worker was not reused: calls=%d result=%s error=%v", calls, result.marshalCompact(), err)
	}
}

func TestExpandRefreshPreparesLocalMatches(t *testing.T) {
	for _, mode := range []string{"expand-refresh", "expand-rebuild"} {
		t.Run(mode, func(t *testing.T) {
			db, path := openTempDB(t)
			if err := migrate(db, 1); err != nil {
				t.Fatal(err)
			}
			pages, targeted := 0, 0
			remoteID := "owned"
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body struct{ Query string }
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
					return
				}
				w.Header().Set("Content-Type", "application/json")
				if !strings.Contains(body.Query, "CuratorLocalSceneMatches") {
					fmt.Fprint(w, `{"errors":[{"message":"stop after local preparation"}]}`)
					return
				}
				if strings.Contains(body.Query, "ByIds") {
					targeted++
				} else {
					pages++
				}
				fmt.Fprintf(w, `{"data":{"findScenes":{"count":1,"scenes":[{"id":"1","stash_ids":[{"endpoint":"https://stashdb.org/graphql","stash_id":%q}]}]}}}`, remoteID)
			}))
			defer server.Close()
			u, _ := url.Parse(server.URL)
			port, _ := strconv.Atoi(u.Port())
			payload := taskPayload(path, mode)
			payload.set("server_connection", jvObj(jvKey("Host", jvStr(u.Hostname())), jvKey("Port", jvInt(int64(port)))))
			run := func() {
				t.Helper()
				_, err := runTaskMode(db, t.TempDir(), payload, mode, jvObj(), 1)
				if err == nil || !strings.Contains(err.Error(), "stop after local preparation") {
					t.Fatalf("unexpected refresh result: %v", err)
				}
			}
			run()
			var ready, value string
			if err := db.QueryRow(`SELECT value FROM application_meta WHERE key='local_scene_matches_ready'`).Scan(&ready); err != nil || ready != "1" {
				t.Fatalf("refresh did not initialize matches: %s %v", ready, err)
			}
			remoteID = "updated-owned"
			if err := withTxn(db, func(conn *sql.Conn) error { return queueLocalSceneMatch(conn, "1") }); err != nil {
				t.Fatal(err)
			}
			run()
			if err := db.QueryRow(`SELECT value FROM local_scene_match WHERE scene_id='1' AND kind='stashdb_id'`).Scan(&value); err != nil || value != remoteID {
				t.Fatalf("refresh did not apply pending match: %s %v", value, err)
			}
			run()
			if pages != 1 || targeted != 1 {
				t.Fatalf("refresh rescanned unchanged library: pages=%d targeted=%d", pages, targeted)
			}
			result, err := getExpandBody(t.TempDir(), payload, jvObj())
			if err != nil || result.get("initializing").truthy() {
				t.Fatalf("browse still initialized after refresh: %s %v", result.marshalCompact(), err)
			}
		})
	}
}

func BenchmarkLocalSceneMatchesBackfill(b *testing.B) {
	const count = 24000
	pages := make([][]byte, count/1000)
	for page := range pages {
		scenes := jvArr()
		for offset := range 1000 {
			id := page*1000 + offset + 1
			scenes.arr = append(scenes.arr, jvObj(jvKey("id", jvStr(strconv.Itoa(id))),
				jvKey("stash_ids", jvArr(jvObj(jvKey("endpoint", jvStr(stashdbEndpoint)), jvKey("stash_id", jvStr(fmt.Sprintf("remote-%d", id)))))),
				jvKey("files", jvArr(jvObj(jvKey("fingerprints", jvArr(jvObj(jvKey("type", jvStr("phash")), jvKey("value", jvStr(fmt.Sprintf("%016x", id)))))))))))
		}
		pages[page] = []byte(jvObj(jvKey("data", jvObj(jvKey("findScenes", jvObj(jvKey("count", jvInt(count)), jvKey("scenes", scenes)))))).marshalCompact())
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Variables struct {
				Page int `json:"page"`
			} `json:"variables"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			b.Error(err)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(pages[body.Variables.Page-1])
	}))
	defer server.Close()
	b.ResetTimer()
	b.StopTimer()
	for range b.N {
		db, err := openDatabase(filepath.Join(b.TempDir(), "matches.sqlite3"), false, nil)
		if err != nil {
			b.Fatal(err)
		}
		if err := migrate(db, 1); err != nil {
			b.Fatal(err)
		}
		trace := beginTrace("worker-local-matches", "task")
		b.StartTimer()
		err = backfillLocalSceneMatches(db, server.URL, nil, nil)
		b.StopTimer()
		endTrace(trace)
		db.Close()
		if err != nil {
			b.Fatal(err)
		}
		for _, event := range trace.events {
			if event.name == "local_matches.fetch" || event.name == "local_matches.index" {
				b.ReportMetric(float64(event.durationNs)/1e6, event.name+"-ms")
			}
		}
	}
}

func TestLocalSceneMatchesBackfillAndTargetedUpdates(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	scene, err := parseJSON([]byte(`{"id":"1","stash_ids":[{"endpoint":"https://stashdb.org/graphql","stash_id":"owned"}],"files":[{"fingerprints":[{"type":"PHASH","value":"0123456789ABCDEF"},{"type":"phash","value":"invalid"}]}]}`))
	if err != nil {
		t.Fatal(err)
	}
	unlinked, _ := parseJSON([]byte(`{"id":"2","files":[{"fingerprints":[{"type":"phash","value":"1111111111111111"}]}]}`))
	calls := 0
	deleted := false
	var duringFetch func()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Query     string
			Variables map[string]json.RawMessage
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
			return
		}
		calls++
		items := jvArr(scene, unlinked)
		if strings.Contains(body.Query, "ByIds") {
			if string(body.Variables["ids"]) != `["1"]` {
				t.Errorf("targeted ids: %s", body.Variables["ids"])
			}
			items = jvArr(scene)
			if deleted {
				items = jvArr()
			}
		} else if !strings.Contains(body.Query, "CuratorLocalSceneMatches") {
			t.Errorf("unexpected whole-library query: %s", body.Query)
		}
		// Queue a newer mutation after the fetch has captured its old response.
		if duringFetch != nil {
			duringFetch()
			duringFetch = nil
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(jvObj(jvKey("data", jvObj(jvKey("findScenes", jvObj(jvKey("count", jvInt(int64(len(items.arr)))), jvKey("scenes", items)))))).marshalCompact()))
	}))
	defer server.Close()
	u, _ := url.Parse(server.URL)
	port, _ := strconv.Atoi(u.Port())
	payload := jvObj(jvKey("server_connection", jvObj(jvKey("Host", jvStr(u.Hostname())), jvKey("Port", jvInt(int64(port))))))
	serve := func() jVal {
		t.Helper()
		links, err := localSceneLinks(payload, db)
		if err != nil {
			t.Fatal(err)
		}
		return links
	}
	queue := func() {
		t.Helper()
		if err := withTxn(db, func(conn *sql.Conn) error { return queueLocalSceneMatch(conn, "1") }); err != nil {
			t.Fatal(err)
		}
	}
	links := serve()
	if links.get("scene_ids").get("owned").asString() != "1" || links.get("scene_phashes").get("0123456789abcdef").asString() != "1" || links.get("scene_phashes").get("1111111111111111").asString() != "2" {
		t.Fatalf("backfill: %s", links.marshalCompact())
	}
	if links.get("scene_phashes").has("invalid") {
		t.Fatal("invalid phash indexed")
	}
	if serve().marshalCompact() != links.marshalCompact() || calls != 1 {
		t.Fatalf("unchanged browse fetched Stash: %d", calls)
	}
	scene.set("title", jvStr("metadata edit"))
	queue()
	if serve().marshalCompact() != links.marshalCompact() || calls != 2 {
		t.Fatal("metadata edit changed matching facts or rescanned library")
	}
	scene.set("stash_ids", jvArr())
	scene.set("files", jvArr())
	queue()
	links = serve()
	if links.get("scene_ids").has("owned") || links.get("scene_phashes").has("0123456789abcdef") {
		t.Fatal("removed links or fingerprints retained")
	}
	queue()
	duringFetch = queue
	serve()
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM local_scene_match_pending`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("newer hook lost: count=%d err=%v", count, err)
	}
	serve()
	if err := db.QueryRow(`SELECT count(*) FROM local_scene_match_pending`).Scan(&count); err != nil || count != 0 {
		t.Fatalf("pending not drained: %d %v", count, err)
	}
	deleted = true
	queue()
	serve()
	if err := db.QueryRow(`SELECT count(*) FROM local_scene_match WHERE scene_id='1'`).Scan(&count); err != nil || count != 0 {
		t.Fatal("deleted scene retained")
	}
	stale := jvObj(jvKey("id", jvStr("owned")), jvKey("curator_local_match", jvObj(jvKey("type", jvStr("stashdb_id")))))
	if annotateLocalMatch(stale, nil, nil).has("curator_local_match") {
		t.Fatal("removed match annotation retained")
	}
}

func TestLocalSceneMatchesSyncAndDeletion(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	scene, _ := parseJSON([]byte(`{"id":"1","stash_ids":[{"endpoint":"https://stashdb.org/graphql","stash_id":"owned"}],"files":[]}`))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(jvObj(jvKey("data", jvObj(jvKey("findScene", scene)))).marshalCompact()))
	}))
	defer server.Close()
	service, err := newSyncService(server.URL, nil, newSyncRepository(db), 250)
	if err != nil {
		t.Fatal(err)
	}
	if changed, err := service.upsertEntity("scene", "1"); err != nil || !changed {
		t.Fatalf("initial sync: %v %v", changed, err)
	}
	scene.set("stash_ids", jvArr())
	if changed, err := service.upsertEntity("scene", "1"); err != nil || changed {
		t.Fatalf("matching-only edit changed model hash: %v %v", changed, err)
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM local_scene_match`).Scan(&count); err != nil || count != 0 {
		t.Fatal("unchanged source hash prevented index update")
	}
	scene.set("stash_ids", jvArr(jvObj(jvKey("endpoint", jvStr("https://stashdb.org/graphql")), jvKey("stash_id", jvStr("owned")))))
	if _, err := service.upsertEntity("scene", "1"); err != nil {
		t.Fatal(err)
	}
	if err := withTxn(db, func(conn *sql.Conn) error { return syncDeleteEntitiesConn(conn, "scene", []string{"1"}) }); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT count(*) FROM local_scene_match`).Scan(&count); err != nil || count != 0 {
		t.Fatal("sync deletion left matching facts")
	}
}
