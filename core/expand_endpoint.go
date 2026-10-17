package main

import (
	"database/sql"
	"fmt"
	"strings"
)

// Unmarked caches predate endpoint selection and contain StashDB data.
func cachedStashboxEndpoint(db dbx, key string) (string, error) {
	var endpoint string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, key).Scan(&endpoint)
	if err == sql.ErrNoRows {
		return "https://stashdb.org/graphql", nil
	}
	return strings.TrimRight(endpoint, "/"), err
}

func validateExpandSceneFilters(clientURL, apiKey string) error {
	if strings.EqualFold(stashdbEndpoint, "https://stashdb.org/graphql") {
		return nil
	}
	data, err := stashdbQuery(clientURL, apiKey, `query CuratorSceneFilterSchema {
__type(name:"SceneQueryInput") { inputFields { name type { kind name } } }
}`, jvObj())
	if err != nil {
		return nil // Servers may disable introspection; let the normal query report errors.
	}
	for _, field := range data.get("__type").get("inputFields").arr {
		name := field.get("name").asString()
		if (name == "performers" || name == "studios" || name == "tags") && field.get("type").get("name").asString() == "String" {
			return fmt.Errorf("Curator does not yet support Expand with this endpoint: its %s filter expects text instead of StashDB's filter object. Choose a compatible Stash-box endpoint", name)
		}
	}
	return nil
}

func externalPayload(payload jVal) jVal {
	if !strings.EqualFold(stashdbEndpoint, "https://stashdb.org/graphql") {
		payload.set("curator_endpoint", jvStr(stashdbEndpoint))
	}
	return payload
}

func ensureExpandEndpoint(pluginDir string, payload, settings jVal, db dbx) (bool, error) {
	endpoint, err := cachedStashboxEndpoint(db, "expand_cache_endpoint")
	if err != nil || strings.EqualFold(endpoint, stashdbEndpoint) {
		return err == nil, err
	}
	var state, failure, requested string
	var started int64
	err = db.QueryRow(`SELECT state, COALESCE(error,''),
COALESCE(json_extract(payload_json, '$.args.expand_endpoint'),''), started_at_ms
FROM curator_job WHERE job_type IN ('expand-refresh','expand-rebuild')
ORDER BY started_at_ms DESC, rowid DESC LIMIT 1`).Scan(&state, &failure, &requested, &started)
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	if state == "running" && started > nowMs()-6*3_600_000 {
		return false, nil
	}
	if (state == "failed" || state == "cancelled") && strings.EqualFold(requested, stashdbEndpoint) {
		return false, fmt.Errorf("Preparing the selected endpoint failed: %s. Retry Refresh Expand cache in Manage > Tasks", failure)
	}
	args := payload.get("args")
	args.set("expand_endpoint", jvStr(stashdbEndpoint))
	payload.set("args", args)
	_, err = runTaskBody(pluginDir, payload, "expand-refresh", settings)
	return false, err
}
