package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestExpandRejectsTextFiltersBeforeFetchingCandidates(t *testing.T) {
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	stashdbEndpoint = "https://example.test/graphql"
	for _, kind := range []string{"String", "MultiIDCriterionInput", "disabled"} {
		t.Run(kind, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				if kind == "disabled" {
					fmt.Fprint(w, `{"errors":[{"message":"Introspection disabled"}]}`)
					return
				}
				fmt.Fprintf(w, `{"data":{"__type":{"inputFields":[{"name":"performers","type":{"name":%q}}]}}}`, kind)
			}))
			defer server.Close()
			err := validateExpandSceneFilters(server.URL, "fixture-key")
			if calls != 1 {
				t.Fatalf("unexpected request count: %d", calls)
			}
			if kind == "String" {
				if err == nil || !strings.Contains(err.Error(), "expects text instead of StashDB's filter object") {
					t.Fatalf("incompatible schema not explained: %v", err)
				}
			} else if err != nil {
				t.Fatalf("compatible/unknown schema rejected: %v", err)
			}
		})
	}
}

func TestTaxonomyUsesOnlySelectedSource(t *testing.T) {
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	stashdbEndpoint = "https://example.test/graphql"
	if !isStashdbEndpoint("https://EXAMPLE.TEST/graphql/") || isStashdbEndpoint("https://stashdb.org/graphql") {
		t.Fatal("taxonomy accepted the wrong source")
	}
	stashdbEndpoint = "https://stashdb.org/graphql"
	if !isStashdbEndpoint("http://stashdb.org/graphql/") {
		t.Fatal("legacy StashDB endpoint alias rejected")
	}
}

func TestConfigureStashbox(t *testing.T) {
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	for _, tc := range []struct{ name, settings, want string }{
		{"missing", `{}`, "https://stashdb.org/graphql"},
		{"null", `{"stashBoxEndpoint":null}`, "https://stashdb.org/graphql"},
		{"empty", `{"stashBoxEndpoint":" "}`, "https://stashdb.org/graphql"},
		{"configured", `{"stashBoxEndpoint":" https://example.test/graphql/ "}`, "https://example.test/graphql"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			settings, err := parseJSON([]byte(tc.settings))
			if err != nil {
				t.Fatal(err)
			}
			configureStashbox(settings)
			if stashdbEndpoint != tc.want {
				t.Fatalf("endpoint = %q, want %q", stashdbEndpoint, tc.want)
			}
		})
	}
}

func TestWhisparrRequiresStashdbEndpoint(t *testing.T) {
	for _, tc := range []struct {
		endpoint string
		allowed  bool
	}{
		{"", true},
		{" https://STASHDB.ORG/graphql/ ", true},
		{"https://example.test/graphql", false},
		{"https://stashdb.org.example.test/graphql", false},
	} {
		settings := jvObj(jvKey("stashBoxEndpoint", jvStr(tc.endpoint)),
			jvKey("whisparrUrl", jvStr("http://whisparr.invalid")),
			jvKey("whisparrApiKey", jvStr("existing-key")))
		if got := whisparrEnabled(settings); got != tc.allowed {
			t.Fatalf("endpoint %q: enabled=%v want=%v", tc.endpoint, got, tc.allowed)
		}
		if !tc.allowed {
			_, err := sendWhisparrBody(t.TempDir(), jvObj(), settings)
			if err == nil || err.Error() != "Whisparr is only available when the StashDB endpoint is selected" {
				t.Fatalf("endpoint %q was not rejected before lookup/send: %v", tc.endpoint, err)
			}
		}
	}
}

func TestExpandEndpointSwitchQueuesOnceAndReportsFailure(t *testing.T) {
	db, path := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	previousEndpoint, previousSpawn := stashdbEndpoint, spawnWorkerFn
	t.Cleanup(func() { stashdbEndpoint, spawnWorkerFn = previousEndpoint, previousSpawn })
	spawnWorkerFn = func(string) error { return nil }
	settings := jvObj(jvKey("stashBoxEndpoint", jvStr("https://example.test/graphql")))
	configureStashbox(settings)
	payload := taskPayload(path, "get_expand")
	pluginDir := t.TempDir()
	for i := range 2 {
		ready, err := ensureExpandEndpoint(pluginDir, payload, settings, db)
		if err != nil || ready {
			t.Fatalf("preparation: ready=%v error=%v", ready, err)
		}
		if i == 0 {
			if _, err := db.Exec(`UPDATE curator_job SET payload_json=json_set(payload_json,'$.args.automatic',json('true'))`); err != nil {
				t.Fatal(err)
			}
		}
	}
	var automatic bool
	if err := db.QueryRow(`SELECT json_extract(payload_json,'$.args.automatic') FROM curator_job LIMIT 1`).Scan(&automatic); err != nil || automatic {
		t.Fatalf("browsing did not release deferred refresh: automatic=%v error=%v", automatic, err)
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM curator_job WHERE job_type='expand-refresh'`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("queued jobs=%d error=%v", count, err)
	}
	if _, err := db.Exec(`UPDATE curator_job SET state='failed',error='offline'`); err != nil {
		t.Fatal(err)
	}
	if _, err := ensureExpandEndpoint(pluginDir, payload, settings, db); err == nil || !strings.Contains(err.Error(), "offline") {
		t.Fatalf("failure not surfaced: %v", err)
	}
	configureStashbox(jvObj())
	if ready, err := ensureExpandEndpoint(pluginDir, payload, jvObj(), db); err != nil || !ready {
		t.Fatalf("return to original endpoint: ready=%v error=%v", ready, err)
	}
}

func TestExpandDoesNotServeAnotherEndpointCache(t *testing.T) {
	db := expandResultsFixture(t, 3)
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	stashdbEndpoint = "https://example.test/graphql"
	result, err := expandResults(db, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, -1, 20, jvNull())
	if err != nil || result.get("ready").truthy() || len(result.get("items").arr) != 0 {
		t.Fatalf("served old endpoint: %s error=%v", result.marshalCompact(), err)
	}
}

func TestExpandSkipsCandidatesStampedWithAnotherSource(t *testing.T) {
	db := expandResultsFixture(t, 3)
	if _, err := db.Exec(`UPDATE external_entity SET payload_json=json_set(payload_json,'$.curator_endpoint','https://example.test/graphql') WHERE external_id='ext-0000'`); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		result, err := expandResults(db, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, -1, 20, jvNull())
		if err != nil || result.get("total").asString() != "2" {
			t.Fatalf("served mixed sources: %s error=%v", result.marshalCompact(), err)
		}
	}
}

func TestExpandEndpointChangesDuringPageRead(t *testing.T) {
	db := expandResultsFixture(t, 3)
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	stashdbEndpoint = "https://stashdb.org/graphql"
	serve := func(connection dbx) jVal {
		t.Helper()
		result, err := expandResults(connection, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, -1, 20, jvNull())
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	if len(serve(db).get("items").arr) != 3 {
		t.Fatal("fixture did not populate the ordering cache")
	}
	connection := &expandChangeBeforePage{dbx: db, change: func() error {
		_, err := db.Exec(`INSERT INTO application_meta VALUES ('expand_cache_endpoint','https://example.test/graphql')`)
		return err
	}}
	if len(serve(connection).get("items").arr) != 0 {
		t.Fatal("served candidates after cache source changed")
	}
}
