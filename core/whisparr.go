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
	"strconv"
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
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return jvNull(), whisparrHTTPError{status: resp.StatusCode, message: whisparrRejection(resp.StatusCode, raw)}
	}
	// Bulk editor deletes answer 200 with no body.
	if len(strings.TrimSpace(string(raw))) == 0 {
		return jvNull(), nil
	}
	parsed, err := parseJSON(raw)
	if err != nil {
		return jvNull(), errors.New("Whisparr returned invalid JSON")
	}
	return parsed, nil
}

// whisparrHTTPError is a non-2xx Whisparr reply; its text is whisparrRejection's.
type whisparrHTTPError struct {
	status  int
	message string
}

func (e whisparrHTTPError) Error() string { return e.message }

// whisparrNotFound reports a 404: the endpoint does not exist in this
// Whisparr version.
func whisparrNotFound(err error) bool {
	var httpErr whisparrHTTPError
	return errors.As(err, &httpErr) && httpErr.status == http.StatusNotFound
}

// whisparrRejection mirrors whisparr._rejection: describe a non-2xx reply with
// Whisparr's own message when it gives one — {"message": ...} for errors,
// [{"errorMessage": ...}] for validation failures.
func whisparrRejection(status int, raw []byte) string {
	var messages []string
	if body, err := parseJSON(raw); err == nil {
		switch body.kind {
		case jObj:
			messages = append(messages, strings.TrimSpace(pythonStrOrEmpty(body.get("message"))))
		case jArr:
			for _, item := range body.arr {
				if item.kind == jObj {
					messages = append(messages, strings.TrimSpace(pythonStrOrEmpty(item.get("errorMessage"))))
				}
			}
		}
	}
	var detail []string
	for _, message := range messages {
		if message != "" {
			detail = append(detail, message)
		}
	}
	text := fmt.Sprintf("Whisparr rejected the request (HTTP %d)", status)
	if len(detail) > 0 {
		text += ": " + strings.Join(detail, "; ")
	}
	return text
}

// whisparrCuratorTag labels every scene Curator adds, so they can be told
// apart from scenes added in Whisparr itself.
const whisparrCuratorTag = "curator"

// whisparrCuratorTagID mirrors WhisparrClient._curator_tag_id: find the
// curator tag (Whisparr compares labels case-insensitively), else create it.
func whisparrCuratorTagID(baseURL string, headers map[string]string) (jVal, error) {
	tags, err := whisparrRequest("GET", baseURL, headers, "/tag", jvNull())
	if err != nil {
		return jvNull(), err
	}
	var tag jVal = jvNull()
	if tags.kind == jArr {
		for _, item := range tags.arr {
			if item.kind == jObj && strings.EqualFold(strings.TrimSpace(pythonStrOrEmpty(item.get("label"))), whisparrCuratorTag) {
				tag = item
				break
			}
		}
	}
	if tag.kind == jNull {
		if tag, err = whisparrRequest("POST", baseURL, headers, "/tag",
			jvObj(jvKey("label", jvStr(whisparrCuratorTag)))); err != nil {
			return jvNull(), err
		}
	}
	tagID := jvNull()
	if tag.kind == jObj {
		tagID = tag.get("id")
	}
	if id, err := strconv.ParseInt(tagID.num, 10, 64); tagID.kind != jNum || err != nil || id < 1 {
		return jvNull(), errors.New("Whisparr did not return the curator tag")
	}
	return tagID, nil
}

// sendWhisparrScene mirrors WhisparrClient.send_scene for the send_whisparr
// operation: find the movie by stashId, else pick a root folder and quality
// profile, add the movie with the curator tag (monitored when asked, so
// Whisparr's RSS sync grabs a later release), and optionally trigger the
// search command.
func sendWhisparrScene(baseURL, apiKey, stashdbID, title, rootFolder string, qualityProfileID int64, monitor, search bool) (jVal, error) {
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
	tagID, err := whisparrCuratorTagID(baseURL, headers)
	if err != nil {
		return jvNull(), err
	}
	monitorOption := "none"
	if monitor {
		monitorOption = "movieOnly"
	}
	created, err := whisparrRequest("POST", baseURL, headers, "/movie", jvObj(
		jvKey("foreignId", jvStr(stashdbID)),
		jvKey("stashId", jvStr(stashdbID)),
		jvKey("title", jvStr(title)),
		jvKey("rootFolderPath", jvStr(rootFolder)),
		jvKey("qualityProfileId", jvInt(qualityProfileID)),
		jvKey("monitored", jvBool(monitor)),
		jvKey("tags", jvArr(tagID)),
		jvKey("addOptions", jvObj(
			jvKey("monitor", jvStr(monitorOption)),
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
	if id, err := strconv.ParseInt(movieID.num, 10, 64); movieID.kind != jNum || err != nil || id < 1 {
		return jvNull(), errors.New("Whisparr did not return the added scene")
	}
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
	if !whisparrSupportsEndpoint(settings) {
		return jvNull(), errors.New("Whisparr is only available when the StashDB endpoint is selected")
	}
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
WHERE entity_type='scene' AND external_id=? AND endpoint='https://stashdb.org/graphql'
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
	if source := scenePayload.get("curator_endpoint"); source.truthy() && !strings.EqualFold(strings.TrimRight(source.asString(), "/"), "https://stashdb.org/graphql") {
		return jvNull(), errors.New("Whisparr only accepts scenes from StashDB")
	}
	url := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrUrl")))
	key := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrApiKey")))
	root := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrRootFolder")))
	profile := pythonInt(settings.get("whisparrQualityProfileId"))
	monitor := argsBool(settings, "whisparrMonitor", true)
	// With the rolling search on, the daemon searches sent scenes a few at a
	// time instead of one search per send.
	cfg, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	rotation := readWhisparrSweepConfig(cfg.get("config")).enabled
	search := !rotation && argsBool(settings, "whisparrSearchImmediately", true)
	title := pythonStrOrEmpty(scenePayload.get("title"))
	if title == "" {
		title = "Added by Stash Curator"
	}
	result, err := sendWhisparrScene(url, key, externalID, title, root, profile, monitor, search)
	if err != nil {
		return jvNull(), err
	}
	// Remember the send so Find can mark the scene and batch dismissals skip it.
	sentAt := nowMs()
	if err := execImmediate(db, `INSERT OR IGNORE INTO external_whisparr_sent(endpoint, external_id, sent_at_ms)
VALUES (lower(?), ?, ?)`, stashdbEndpoint, externalID, sentAt); err != nil {
		return jvNull(), err
	}
	if whisparrID := pythonInt(result.get("id")); rotation && whisparrID > 0 {
		if err := queueWhisparrSearch(db, externalID, whisparrID, sentAt); err != nil {
			return jvNull(), err
		}
		ensureAutoWorker(pluginDir, payload, settings, db)
	}
	return result, nil
}
