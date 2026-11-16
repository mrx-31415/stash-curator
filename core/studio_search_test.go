package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
)

// The remote Studios picker lists direct name hits before sites that only
// matched through an alias or their parent network, and caps the list.
func TestStashdbStudioSearchRanksDirectNameHitsFirst(t *testing.T) {
	previous := stashdbEndpoint
	t.Cleanup(func() { stashdbEndpoint = previous })
	stashdbEndpoint = "https://stashdb.org/graphql"
	var terms []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(string(body), "CuratorStashBoxes"):
			io.WriteString(w, `{"data":{"configuration":{"general":{"stashBoxes":[{"endpoint":"https://stashdb.org/graphql","api_key":"key","name":"StashDB"}]}}}}`)
		case strings.Contains(string(body), "CuratorStudioExact"):
			var request struct {
				Variables struct {
					Name string `json:"name"`
				} `json:"variables"`
			}
			if err := json.Unmarshal(body, &request); err != nil {
				t.Errorf("bad request: %v", err)
			}
			terms = append(terms, "exact:"+request.Variables.Name)
			// The exact lookup finds the studio the like-match page missed.
			io.WriteString(w, `{"data":{"findStudio":{"id":"b","name":"Example Network","parent":null}}}`)
		case strings.Contains(string(body), "CuratorStudioSearch"):
			var request struct {
				Variables struct {
					Input map[string]any `json:"input"`
				} `json:"variables"`
			}
			if err := json.Unmarshal(body, &request); err != nil {
				t.Errorf("bad request: %v", err)
			}
			terms = append(terms, fmt.Sprint("like:", request.Variables.Input["names"]))
			io.WriteString(w, `{"data":{"queryStudios":{"studios":[
 {"id":"a","name":"Alpha Example Network","parent":{"id":"n","name":"Example Network"}},
 {"id":"c","name":"Bravo Example","parent":{"id":"n","name":"Example Network"}},
 {"id":"b","name":"Example Network","parent":null},
 {"id":"d","name":"Example Teens","parent":{"id":"n","name":"Example Network"}}
]}}}`)
		default:
			io.WriteString(w, `{"errors":[{"message":"unexpected query"}]}`)
		}
	}))
	defer server.Close()
	t.Setenv("CURATOR_STASHDB_ENDPOINT", server.URL)
	address, _ := url.Parse(server.URL)
	port, _ := strconv.Atoi(address.Port())
	payload := jvObj(
		jvKey("server_connection", jvObj(jvKey("Host", jvStr(address.Hostname())), jvKey("Port", jvInt(int64(port))))),
		jvKey("args", jvObj(jvKey("query", jvStr(" example network ")), jvKey("limit", jvInt(3)))),
	)
	result, err := getStashdbStudioSearchBody(payload)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(terms, ",") != "exact:example network,like:example network" {
		t.Fatalf("unexpected searches: %v", terms)
	}
	var got []string
	for _, item := range result.get("items").arr {
		got = append(got, item.get("id").asString()+":"+pythonStrOrEmpty(item.get("parent_name")))
	}
	if strings.Join(got, ",") != "b:,a:Example Network,c:Example Network" {
		t.Fatalf("unexpected ranking: %v", got)
	}

	// An empty query never reaches the network.
	terms = nil
	empty, err := getStashdbStudioSearchBody(jvObj(jvKey("args", jvObj(jvKey("query", jvStr("  "))))))
	if err != nil || len(empty.get("items").arr) != 0 || terms != nil {
		t.Fatalf("empty query searched: %v %v", empty, err)
	}
}
