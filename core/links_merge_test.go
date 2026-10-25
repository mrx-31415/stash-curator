package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestPutLink(t *testing.T) {
	for _, keepFirst := range []bool{false, true} {
		target := jvObj()
		index := map[string]int{}
		for _, pair := range [][2]string{{"a", "1"}, {"b", "2"}, {"a", "3"}, {"c", "4"}} {
			putLink(&target, index, pair[0], jvStr(pair[1]), keepFirst)
		}
		want := `{"a":"3","b":"2","c":"4"}`
		if keepFirst {
			want = `{"a":"1","b":"2","c":"4"}`
		}
		if got := target.marshalCompact(); got != want {
			t.Fatalf("keepFirst=%v: %s, want %s", keepFirst, got, want)
		}
	}
}

// fakeLinkedEntity is one Stash entity with a StashDB stash_id; endpoint
// lets a test add one whose stash_id is for another (case-variant) endpoint.
type fakeLinkedEntity struct {
	external, endpoint string
	phashes            []string
	updated            time.Time
}

// fakeLinksStash serves the three external-links queries from an in-memory
// library and counts calls per operation.
type fakeLinksStash struct {
	mu      sync.Mutex
	library map[string]map[int]*fakeLinkedEntity
	calls   map[string]int
}

func (f *fakeLinksStash) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var request struct {
		Query     string         `json:"query"`
		Variables map[string]any `json:"variables"`
	}
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	operation := graphqlOperationName(request.Query)
	f.calls[operation]++
	data := map[string]any{}
	for _, kind := range linkKinds {
		ids := make([]int, 0, len(f.library[kind]))
		for id, entity := range f.library[kind] {
			if operation == "CuratorExternalLinksChanged" {
				since, err := time.Parse(time.RFC3339, request.Variables[strings.TrimSuffix(kind, "s")+"Since"].(string))
				if err != nil {
					http.Error(w, err.Error(), http.StatusBadRequest)
					return
				}
				if !entity.updated.After(since) {
					continue
				}
			}
			ids = append(ids, id)
		}
		if operation == "CuratorExternalLinksState" {
			sort.Slice(ids, func(i, j int) bool {
				return f.library[kind][ids[i]].updated.After(f.library[kind][ids[j]].updated)
			})
			rows := []any{}
			if len(ids) > 0 {
				rows = append(rows, map[string]any{"updated_at": f.library[kind][ids[0]].updated.Format(time.RFC3339)})
			}
			data[kind] = map[string]any{"count": len(ids), kind: rows}
			continue
		}
		sort.Ints(ids)
		page, perPage := int(request.Variables["page"].(float64)), int(request.Variables["perPage"].(float64))
		rows := []any{}
		for _, id := range ids[min((page-1)*perPage, len(ids)):min(page*perPage, len(ids))] {
			entity := f.library[kind][id]
			endpoint := entity.endpoint
			if endpoint == "" {
				endpoint = stashdbEndpoint
			}
			row := map[string]any{
				"id":        strconv.Itoa(id),
				"stash_ids": []any{map[string]any{"endpoint": endpoint, "stash_id": entity.external}},
			}
			if kind == "scenes" {
				fingerprints := []any{}
				for _, phash := range entity.phashes {
					fingerprints = append(fingerprints, map[string]any{"type": "phash", "value": phash})
				}
				row["files"] = []any{map[string]any{"fingerprints": fingerprints}}
			}
			rows = append(rows, row)
		}
		data[kind] = map[string]any{"count": len(ids), kind: rows}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"data": data})
}

func TestIncrementalExternalLinksMatchFullWalk(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	clock := time.Date(2026, 10, 25, 4, 0, 0, 0, time.UTC)
	tick := func() time.Time { clock = clock.Add(time.Minute); return clock }
	stash := &fakeLinksStash{library: map[string]map[int]*fakeLinkedEntity{
		"scenes": {}, "performers": {}, "studios": {},
	}, calls: map[string]int{}}
	for id := 1; id <= 1200; id++ {
		if id == 600 {
			continue // linked later, inside the existing id range
		}
		stash.library["scenes"][id] = &fakeLinkedEntity{
			external: fmt.Sprintf("scene-%d", id%1100), // duplicate externals
			phashes:  []string{fmt.Sprintf("%016x", id%1150)},
			updated:  clock.Add(-time.Duration(id) * time.Second),
		}
	}
	stash.library["scenes"][1201] = &fakeLinkedEntity{external: "other", endpoint: "https://STASHDB.org/graphql/", updated: clock}
	for id := 1; id <= 30; id++ {
		stash.library["performers"][id] = &fakeLinkedEntity{external: fmt.Sprintf("performer-%d", id), updated: clock}
	}
	for id := 1; id <= 10; id++ {
		stash.library["studios"][id] = &fakeLinkedEntity{external: fmt.Sprintf("studio-%d", id), updated: clock}
	}
	server := httptest.NewServer(stash)
	defer server.Close()
	u, _ := url.Parse(server.URL)
	port, _ := strconv.Atoi(u.Port())
	payload := jvObj(jvKey("server_connection", jvObj(jvKey("Host", jvStr(u.Hostname())), jvKey("Port", jvInt(int64(port))))))

	check := func(step string, wantWalk bool) {
		t.Helper()
		stash.calls = map[string]int{}
		got, err := externalLinks(payload, db)
		if err != nil {
			t.Fatalf("%s: %v", step, err)
		}
		walked := stash.calls["CuratorExternalLinks"] > 0
		if walked != wantWalk {
			t.Fatalf("%s: full walk=%v, want %v (calls %v)", step, walked, wantWalk, stash.calls)
		}
		want, err := externalLinksImpl(payload, nil, false, nil)
		if err != nil {
			t.Fatal(err)
		}
		if got.marshalCompact() != want.marshalCompact() {
			t.Fatalf("%s: links differ from a full walk", step)
		}
		cached, ok, err := cachedExternalLinks(db, mustLinksState(t, payload))
		if err != nil || !ok || cached.marshalCompact() != want.marshalCompact() {
			t.Fatalf("%s: cache row does not hold the full-walk links (ok=%v, err=%v)", step, ok, err)
		}
	}

	check("first scan", true)
	check("unchanged library", false)

	// Edits and new links patch the saved records without a walk, including
	// a lower id taking over a phash and an external id moving.
	scenes := stash.library["scenes"]
	scenes[5].external, scenes[5].phashes, scenes[5].updated = "moved", []string{"00000000000004b0"}, tick()
	scenes[2].phashes, scenes[2].updated = []string{"0000000000000384", "000000000000002a"}, tick()
	scenes[1300] = &fakeLinkedEntity{external: "scene-new", phashes: []string{"0000000000000001"}, updated: tick()}
	scenes[600] = &fakeLinkedEntity{external: "scene-3", phashes: []string{"0000000000000002"}, updated: tick()}
	stash.library["performers"][3].external, stash.library["performers"][3].updated = "performer-renamed", tick()
	stash.library["studios"][11] = &fakeLinkedEntity{external: "studio-new", updated: tick()}
	check("edited and added entities", false)
	if stash.calls["CuratorExternalLinksChanged"] != 1 {
		t.Fatalf("incremental patch made %d changed-entity calls, want 1", stash.calls["CuratorExternalLinksChanged"])
	}

	// An unlinked entity only shows up as a count mismatch: walk again.
	delete(scenes, 7)
	scenes[8].updated = tick()
	check("unlinked scene", true)
	check("unchanged after walk", false)

	// More edits than the incremental bound also walk.
	for id := 2000; id <= 2000+maxIncrementalLinkPages*500; id++ {
		scenes[id] = &fakeLinkedEntity{external: fmt.Sprintf("bulk-%d", id), updated: tick()}
	}
	check("bulk edit", true)
}

func mustLinksState(t *testing.T, payload jVal) string {
	t.Helper()
	state, err := externalLinksState(payload)
	if err != nil {
		t.Fatal(err)
	}
	return state
}
