package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"testing"
)

func tpdbFixture(t *testing.T) jVal {
	t.Helper()
	raw, err := os.ReadFile("../tests/fixtures/theporndb.json")
	if err != nil {
		t.Fatal(err)
	}
	fixture, err := parseJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	return fixture
}

func TestThePornDBNormalization(t *testing.T) {
	fixture := tpdbFixture(t)
	person := cloneObj(fixture.get("site_performer"))
	person.set("parent", fixture.get("performer"))
	scene := fixture.get("scene")
	scene.set("performers", jvArr(person, person))
	scene.set("site", fixture.get("site"))
	scene.set("tags", fixture.get("tags"))
	value := tpdbScene(scene)
	profile := value.get("performers").arr[0].get("performer")
	if len(value.get("performers").arr) != 1 || profile.get("id").asString() != "parent-performer" ||
		profile.get("height").asString() != "160.0" || profile.get("band_size").asString() != "34.0" ||
		profile.get("cup_size").asString() != "DD" || profile.get("hair_color").asString() != "BRUNETTE" ||
		profile.get("breast_type").asString() != "NATURAL" || len(profile.get("piercings").arr) != 0 {
		t.Fatalf("bad performer normalization: %s", profile.marshalCompact())
	}
	if value.get("studio").get("id").asString() != "studio-uuid" || value.get("tags").arr[0].get("id").asString() != "tag-uuid" || value.get("fingerprints").arr[0].get("algorithm").asString() != "PHASH" {
		t.Fatalf("bad scene normalization: %s", value.marshalCompact())
	}
	missing := tpdbPerformer(fixture.get("site_performer"))
	if missing.get("height").kind != jNull || missing.get("breast_type").kind != jNull {
		t.Fatalf("invented unavailable attributes: %s", missing.marshalCompact())
	}
}

func TestThePornDBFiltersAndPagination(t *testing.T) {
	fixture := tpdbFixture(t)
	sceneRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.Header.Get("Authorization") != "Bearer test-key" || r.Header.Get("ApiKey") != "" {
			t.Errorf("wrong REST method/authentication")
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/performers/parent-performer":
			fmt.Fprintf(w, `{"data":%s}`, fixture.get("performer").marshalCompact())
		case "/performer-sites/site-performer":
			person := cloneObj(fixture.get("site_performer"))
			person.set("parent", fixture.get("performer"))
			fmt.Fprintf(w, `{"data":%s}`, person.marshalCompact())
		case "/sites/studio-uuid":
			fmt.Fprintf(w, `{"data":%s}`, fixture.get("site").marshalCompact())
		case "/tags":
			fmt.Fprintf(w, `{"data":%s,"meta":{"total":1,"current_page":1}}`, fixture.get("tags").marshalCompact())
		case "/scenes":
			sceneRequests++
			params := r.URL.Query()
			if params.Get("performers[42]") != "Example Performer" || params.Get("sites[9]") != "Example Studio" || params.Get("tags[7]") != "Example Tag" || params.Get("tag_and") != "true" {
				t.Errorf("incorrect ID translation: %s", r.URL.RawQuery)
			}
			page, _ := strconv.Atoi(params.Get("page"))
			size, _ := strconv.Atoi(params.Get("per_page"))
			if size > 100 {
				t.Errorf("REST page cap exceeded: %d", size)
			}
			rows := jvArr()
			for i := (page - 1) * size; i < page*size && i < 205; i++ {
				row := cloneObj(fixture.get("scene"))
				row.set("id", jvStr(fmt.Sprintf("scene-%03d", i)))
				rows.arr = append(rows.arr, row)
			}
			fmt.Fprintf(w, `{"data":%s,"meta":{"total":205,"current_page":%d}}`, rows.marshalCompact(), page)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()
	client := newTPDBClient(server.URL, "test-key")
	input := jvObj(jvKey("page", jvInt(2)), jvKey("per_page", jvInt(150)))
	for source, id := range map[string]string{"performers": "site-performer", "studios": "studio-uuid", "tags": "tag-uuid"} {
		input.set(source, jvObj(jvKey("value", jvArr(jvStr(id))), jvKey("modifier", jvStr("INCLUDES_ALL"))))
	}
	result, err := client.query("CuratorExpandScenes", jvObj(jvKey("input", input)))
	if err != nil {
		t.Fatal(err)
	}
	rows := result.get("queryScenes").get("scenes").arr
	if len(rows) != 55 || rows[0].get("id").asString() != "scene-150" || rows[54].get("id").asString() != "scene-204" || sceneRequests != 2 {
		t.Fatalf("virtual pagination lost rows: %s", result.marshalCompact())
	}
	input.set("performers", jvObj(jvKey("value", jvArr(jvStr("missing"))), jvKey("modifier", jvStr("INCLUDES"))))
	result, err = client.query("CuratorExpandScenes", jvObj(jvKey("input", input)))
	if err != nil || result.get("queryScenes").get("count").asString() != "0" || sceneRequests != 2 {
		t.Fatalf("unresolved filter was dropped: %s %v", result.marshalCompact(), err)
	}
	input.set("updated_at", jvObj())
	if _, err := client.query("CuratorExpandScenes", jvObj(jvKey("input", input))); err == nil {
		t.Fatal("unsupported incremental filter silently accepted")
	}
}
