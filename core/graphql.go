// Minimal GraphQL client for the ported backend operations, mirroring
// curator/graphql/client.py: POST {"query", "variables"} to {base}/graphql,
// JSON response parsed into an ordered value; errors and missing data raise
// like the Python GraphQLError paths.
package main

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
)

// Query documents, byte-identical to plugin/backend.py.
const settingsQuery = `
query CuratorPluginSettings {
  configuration { plugins(include: ["stash-curator"]) }
}
`
const runtimeQuery = `
query CuratorPluginRuntime {
  version { version }
  jobQueue { id status description progress startTime }
  configuration { general { stashBoxes { endpoint api_key } } }
}
`
const stashBoxesQuery = `
query CuratorStashBoxes {
  configuration { general { stashBoxes { endpoint api_key name } } }
}
`
const externalLinksStateQuery = `
query CuratorExternalLinksState {
  scenes: findScenes(
    scene_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count scenes { updated_at } }
  performers: findPerformers(
    performer_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count performers { updated_at } }
  studios: findStudios(
    studio_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: 1, per_page: 1, sort: "updated_at", direction: DESC}
  ) { count studios { updated_at } }
}
`
const externalLinksQuery = `
query CuratorExternalLinks($page: Int!, $perPage: Int!) {
  scenes: findScenes(
    scene_filter: {stash_id_endpoint: {endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL}}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) {
    count
    scenes {
      id stash_ids { endpoint stash_id }
      files { fingerprints { type value } }
    }
  }
  performers: findPerformers(
    performer_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count performers { id stash_ids { endpoint stash_id } } }
  studios: findStudios(
    studio_filter: {stash_id_endpoint: {
      endpoint: "https://stashdb.org/graphql", modifier: NOT_NULL
    }}
    filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}
  ) { count studios { id stash_ids { endpoint stash_id } } }
}
`

// StashDB query documents, byte-identical to curator/expand.py.
const stashdbScenesQuery = `
query CuratorExpandScenes($input: SceneQueryInput!) {
  queryScenes(input: $input) {
    count
    scenes {
      id title release_date production_date duration details
      studio { id name }
      tags { id name }
      images { url width height }
      fingerprints { hash algorithm duration }
      performers { performer {
        id name gender birth_date ethnicity eye_color hair_color height cup_size band_size
        waist_size hip_size breast_type tattoos { location } piercings { location }
        images { url width height }
      } }
    }
  }
}
`
const stashdbPerformersQuery = `
query CuratorSimilarPerformers($input: PerformerQueryInput!) {
  queryPerformers(input: $input) {
    performers {
      id name gender birth_date ethnicity eye_color hair_color height cup_size band_size
      waist_size hip_size breast_type scene_count tattoos { location } piercings { location }
      images { url width height }
    }
  }
}
`

// graphqlOperationName mirrors curator.graphql.client._operation_name.
func graphqlOperationName(document string) string {
	re := regexp.MustCompile(`\b(?:query|mutation)\s+([A-Za-z_][A-Za-z0-9_]*)`)
	if match := re.FindStringSubmatch(document); match != nil {
		return match[1]
	}
	return "anonymous"
}

// stashConnection mirrors backend.py's _stash_connection: scheme://host:port
// plus the Cookie header from the session.
func stashConnection(payload jVal) (string, map[string]string) {
	server := payload.get("server_connection")
	host := "127.0.0.1"
	if h := server.get("Host"); h.kind == jStr && h.s != "" {
		host = h.s
	}
	if host == "0.0.0.0" {
		host = "127.0.0.1"
	}
	scheme := "http"
	if s := server.get("Scheme"); s.kind == jStr && s.s != "" {
		scheme = s.s
	}
	port := "9999"
	if p := server.get("Port"); p.kind != jNull {
		port = fmt.Sprintf("%d", pythonInt(p))
	}
	headers := map[string]string{}
	cookie := server.get("SessionCookie")
	if cookie.kind == jObj {
		name := cookie.get("Name")
		value := cookie.get("Value")
		if name.kind == jStr && name.s != "" && value.kind == jStr && value.s != "" {
			headers["Cookie"] = name.s + "=" + value.s
		}
	}
	return fmt.Sprintf("%s://%s:%s", scheme, host, port), headers
}

// pluginSettings mirrors backend.py's _settings: the stash-curator plugin
// settings from the SETTINGS_QUERY, or {} when anything fails.
func pluginSettings(payload jVal) jVal {
	base, headers := stashConnection(payload)
	data, err := graphqlQuery(base, headers, settingsQuery, jvNull())
	if err != nil {
		return jvObj()
	}
	settings := data.get("configuration").get("plugins").get("stash-curator")
	if settings.kind == jObj {
		return settings
	}
	return jvObj()
}

// graphqlQuery POSTs one query and returns the response data object,
// mirroring GraphQLClient._send: errors raise, data must be an object. When
// an operation trace is active, the call records a "stash" span named after
// the query operation, like the Python client's span() wrapper.
func graphqlQuery(base string, headers map[string]string, query string, variables jVal) (jVal, error) {
	return graphqlQueryCat(base, headers, query, variables, "stash")
}

// graphqlQueryCat is graphqlQuery with an explicit span category; StashDB
// queries record "stashdb" spans (GraphQLClient's profile_category).
func graphqlQueryCat(base string, headers map[string]string, query string, variables jVal, category string) (jVal, error) {
	started := int64(0)
	if t := currentTrace(); t != nil {
		started = time.Now().UnixNano()
	}
	base = strings.TrimRight(base, "/")
	url := base
	if !strings.HasSuffix(base, "/graphql") {
		url = base + "/graphql"
	}
	body := `{"query":` + marshalJSONString(query) + `,"variables":` + variables.marshalCompact() + `}`
	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader(body))
	if err != nil {
		return jvNull(), fmt.Errorf("Stash request failed: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return jvNull(), fmt.Errorf("Stash request failed: %v", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return jvNull(), fmt.Errorf("Stash request failed: %v", err)
	}
	if t := currentTrace(); t != nil {
		t.record(category, graphqlOperationName(query), started, time.Now().UnixNano()-started, jvNull())
	}
	payload, err := parseJSON(raw)
	if err != nil {
		return jvNull(), errors.New("Stash returned invalid JSON")
	}
	if payload.kind != jObj {
		return jvNull(), errors.New("Stash returned a non-object GraphQL response")
	}
	if errs := payload.get("errors"); errs.kind != jNull {
		return jvNull(), fmt.Errorf("Stash GraphQL error: %s", errs.marshalCompact())
	}
	data := payload.get("data")
	if data.kind != jObj {
		return jvNull(), errors.New("Stash GraphQL response has no data object")
	}
	return data, nil
}

// stashdbClient mirrors backend.py's _stashdb: query the configured Stash
// boxes, pick the one matching the stashdb.org endpoint, and require an API
// key. The returned base URL and key drive the StashDB queries; the span
// category for those queries is "stashdb".
//
// CURATOR_STASHDB_ENDPOINT (test-only, mirroring the CURATOR_CORE resolver
// seam) redirects the base URL to a local stub so the differential harness
// can pin every StashDB response without real network access.
func stashdbClient(payload jVal) (string, string, error) {
	base, headers := stashConnection(payload)
	data, err := graphqlQuery(base, headers, stashBoxesQuery, jvNull())
	if err != nil {
		return "", "", err
	}
	boxes := data.get("configuration").get("general").get("stashBoxes")
	if boxes.kind == jArr {
		for _, box := range boxes.arr {
			endpoint := strings.TrimRight(box.get("endpoint").asString(), "/")
			if !strings.EqualFold(endpoint, strings.TrimRight(stashdbEndpoint, "/")) {
				continue
			}
			if !box.get("api_key").truthy() {
				continue
			}
			url := box.get("endpoint").asString()
			if override := os.Getenv("CURATOR_STASHDB_ENDPOINT"); override != "" {
				url = override
			}
			return url, box.get("api_key").asString(), nil
		}
	}
	return "", "", errors.New("configure StashDB with an API key in Stash settings")
}

// stashdbQuery executes one StashDB query with the ApiKey header, recording
// a "stashdb" span, mirroring GraphQLClient(endpoint, api_key=...,
// profile_category="stashdb").execute.
func stashdbQuery(baseURL, apiKey, query string, variables jVal) (jVal, error) {
	headers := map[string]string{"ApiKey": apiKey}
	return graphqlQueryCat(baseURL, headers, query, variables, "stashdb")
}
