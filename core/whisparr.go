// Whisparr v3 scene boundary — a port of curator/whisparr.py's
// WhisparrClient.send_scene: the exact request paths, headers, and payloads
// (X-Api-Key, the movie add body with addOptions) and the same error
// messages and result shapes.
package main

import (
	"database/sql"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// whisparrRequest performs one Whisparr API call, mirroring WhisparrClient._request.
func whisparrRequest(method, baseURL string, headers map[string]string, path string, payload jVal) (jVal, error) {
	var body io.Reader
	if payload.kind != jNull {
		body = strings.NewReader(payload.marshalCompact())
	}
	req, err := http.NewRequest(method, baseURL+path, body)
	if err != nil {
		return jvNull(), fmt.Errorf("Whisparr request failed: %v", err)
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return jvNull(), fmt.Errorf("Whisparr request failed: %v", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return jvNull(), fmt.Errorf("Whisparr request failed: %v", err)
	}
	parsed, err := parseJSON(raw)
	if err != nil {
		return jvNull(), errors.New("Whisparr returned invalid JSON")
	}
	return parsed, nil
}

// sendWhisparrScene mirrors WhisparrClient.send_scene for the send_whisparr
// operation: find the movie by stashId, else pick a root folder and quality
// profile, add the movie, and optionally trigger the search command.
func sendWhisparrScene(baseURL, apiKey, stashdbID, title, rootFolder string, qualityProfileID int64, search bool) (jVal, error) {
	if strings.TrimSpace(baseURL) == "" || strings.TrimSpace(apiKey) == "" {
		return jvNull(), errors.New("Whisparr URL and API key are required")
	}
	baseURL = strings.TrimRight(baseURL, "/") + "/api/v3"
	headers := map[string]string{"Content-Type": "application/json", "X-Api-Key": apiKey}
	query := url.Values{"stashId": {stashdbID}}.Encode()
	movies, err := whisparrRequest("GET", baseURL, headers, "/movie?"+query, jvNull())
	if err != nil {
		return jvNull(), err
	}
	if movies.kind != jArr {
		return jvNull(), errors.New("Whisparr returned an invalid movie list")
	}
	for _, item := range movies.arr {
		existingID := pythonStrOrEmpty(item.get("stashId"))
		if existingID == "" {
			existingID = pythonStrOrEmpty(item.get("foreignId"))
		}
		if existingID == stashdbID {
			return jvObj(
				jvKey("status", jvStr("already_exists")),
				jvKey("id", item.get("id")),
			), nil
		}
	}
	if strings.TrimSpace(rootFolder) == "" {
		folders, err := whisparrRequest("GET", baseURL, headers, "/rootfolder", jvNull())
		if err != nil {
			return jvNull(), err
		}
		rootFolder = ""
		if folders.kind == jArr {
			for _, item := range folders.arr {
				if item.kind == jObj && item.get("path").truthy() {
					rootFolder = strings.TrimSpace(item.get("path").asString())
					break
				}
			}
		}
		if rootFolder == "" {
			return jvNull(), errors.New("Whisparr has no configured root folder")
		}
	}
	if qualityProfileID < 1 {
		profiles, err := whisparrRequest("GET", baseURL, headers, "/qualityprofile", jvNull())
		if err != nil {
			return jvNull(), err
		}
		var profile jVal = jvNull()
		if profiles.kind == jArr {
			for _, item := range profiles.arr {
				if item.kind == jObj && item.get("fallback").truthy() {
					profile = item
					break
				}
			}
			if profile.kind == jNull && len(profiles.arr) > 0 {
				profile = profiles.arr[0]
			}
		}
		if profile.kind == jObj {
			qualityProfileID = pythonInt(profile.get("id"))
		}
		if qualityProfileID < 1 {
			return jvNull(), errors.New("Whisparr has no configured quality profile")
		}
	}
	if title == "" {
		title = "Added by Stash Curator"
	}
	created, err := whisparrRequest("POST", baseURL, headers, "/movie", jvObj(
		jvKey("foreignId", jvStr(stashdbID)),
		jvKey("stashId", jvStr(stashdbID)),
		jvKey("title", jvStr(title)),
		jvKey("rootFolderPath", jvStr(rootFolder)),
		jvKey("qualityProfileId", jvInt(qualityProfileID)),
		jvKey("monitored", jvBool(false)),
		jvKey("addOptions", jvObj(
			jvKey("monitor", jvStr("none")),
			jvKey("searchForMovie", jvBool(false)),
		)),
	))
	if err != nil {
		return jvNull(), err
	}
	if created.kind != jObj {
		return jvNull(), errors.New("Whisparr returned an invalid add response")
	}
	movieID := created.get("id")
	if search {
		if _, err := whisparrRequest("POST", baseURL, headers, "/command",
			jvObj(jvKey("name", jvStr("MoviesSearch")), jvKey("movieIds", jvArr(movieID)))); err != nil {
			return jvNull(), err
		}
	}
	return jvObj(
		jvKey("status", jvStr("sent")),
		jvKey("id", movieID),
	), nil
}

// opSendWhisparr mirrors backend.py's _profiled-wrapped send_whisparr:
// load the scene payload row, then push it to Whisparr with the settings.
func opSendWhisparr(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "send_whisparr",
		func(settings jVal) (jVal, error) { return sendWhisparrBody(pluginDir, payload, settings) })
}

func sendWhisparrBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openSidecar(pluginDir, payload, settings, false)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	externalID := argsString(args, "external_id", "")
	var payloadJSON string
	err = db.QueryRow(`
SELECT payload_json FROM external_shortlist
WHERE entity_type='scene' AND external_id=?
UNION ALL
SELECT payload_json FROM external_entity
WHERE entity_type='scene' AND external_id=? LIMIT 1`,
		externalID, externalID).Scan(&payloadJSON)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return jvNull(), errors.New("scene is not in Expand")
		}
		return jvNull(), err
	}
	scenePayload, err := parseJSON([]byte(payloadJSON))
	if err != nil {
		return jvNull(), err
	}
	url := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrUrl")))
	key := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrApiKey")))
	root := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrRootFolder")))
	profile := pythonInt(settings.get("whisparrQualityProfileId"))
	search := argsBool(settings, "whisparrSearchImmediately", true)
	title := pythonStrOrEmpty(scenePayload.get("title"))
	if title == "" {
		title = "Added by Stash Curator"
	}
	return sendWhisparrScene(url, key, externalID, title, root, profile, search)
}
