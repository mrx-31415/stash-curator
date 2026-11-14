// Whisparr overview: what Whisparr tracks, checked against the library, and
// the few actions that manage it (search, monitor, remove without files).
package main

import (
	"database/sql"
	"errors"
	"fmt"
	"sort"
	"strings"
)

// whisparrActionLimit bounds one action call; the frontend chunks larger sets.
const whisparrActionLimit = 500

// whisparrQueuePageSize and whisparrQueuePages bound the download-queue read.
const (
	whisparrQueuePageSize = 500
	whisparrQueuePages    = 10
)

// whisparrAPI is a configured Whisparr v3 endpoint.
type whisparrAPI struct {
	base    string
	headers map[string]string
}

func newWhisparrAPI(settings jVal) (whisparrAPI, error) {
	if !whisparrSupportsEndpoint(settings) {
		return whisparrAPI{}, errors.New("Whisparr is only available when the StashDB endpoint is selected")
	}
	url := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrUrl")))
	key := strings.TrimSpace(pythonStrOrEmpty(settings.get("whisparrApiKey")))
	if url == "" || key == "" {
		return whisparrAPI{}, errors.New("Whisparr URL and API key are required")
	}
	return whisparrAPI{
		base:    strings.TrimRight(url, "/") + "/api/v3",
		headers: map[string]string{"Content-Type": "application/json", "X-Api-Key": key},
	}, nil
}

func (api whisparrAPI) call(method, path string, body jVal) (jVal, error) {
	return whisparrRequest(method, api.base, api.headers, path, body)
}

// whisparrQueue maps Whisparr movie ids to their download-queue record.
func (api whisparrAPI) queue() (map[int64]jVal, error) {
	byMovie := map[int64]jVal{}
	for page := 1; page <= whisparrQueuePages; page++ {
		data, err := api.call("GET", fmt.Sprintf("/queue?page=%d&pageSize=%d&includeUnknownMovieItems=false", page, whisparrQueuePageSize), jvNull())
		if err != nil {
			return nil, err
		}
		records := data.get("records")
		if data.kind != jObj || records.kind != jArr {
			return nil, errors.New("Whisparr returned an invalid download queue")
		}
		for _, record := range records.arr {
			if id := pythonInt(record.get("movieId")); id > 0 {
				if _, seen := byMovie[id]; !seen {
					byMovie[id] = record
				}
			}
		}
		if len(records.arr) < whisparrQueuePageSize || int64(page*whisparrQueuePageSize) >= pythonInt(data.get("totalRecords")) {
			break
		}
	}
	return byMovie, nil
}

func whisparrStashID(movie jVal) string {
	if id := strings.TrimSpace(pythonStrOrEmpty(movie.get("stashId"))); id != "" {
		return id
	}
	return strings.TrimSpace(pythonStrOrEmpty(movie.get("foreignId")))
}

// whisparrImage prefers a screenshot (what StashDB shows for scenes), then any cover.
func whisparrImage(movie jVal) string {
	fallback := ""
	for _, image := range movie.get("images").arr {
		url := strings.TrimSpace(pythonStrOrEmpty(image.get("remoteUrl")))
		if url == "" {
			continue
		}
		if strings.EqualFold(pythonStrOrEmpty(image.get("coverType")), "screenshot") {
			return url
		}
		if fallback == "" {
			fallback = url
		}
	}
	return fallback
}

func whisparrQueueItem(record jVal) jVal {
	size := pythonFloatOr(record.get("size"), 0)
	left := pythonFloatOr(record.get("sizeleft"), 0)
	progress := 0.0
	if size > 0 {
		progress = (size - left) / size
	}
	messages := []string{}
	if message := strings.TrimSpace(pythonStrOrEmpty(record.get("errorMessage"))); message != "" {
		messages = append(messages, message)
	}
	for _, status := range record.get("statusMessages").arr {
		for _, message := range status.get("messages").arr {
			if text := strings.TrimSpace(pythonStrOrEmpty(message)); text != "" {
				messages = append(messages, text)
			}
		}
	}
	problem := jvNull()
	if len(messages) > 0 {
		problem = jvStr(strings.Join(messages, "; "))
	}
	return jvObj(
		jvKey("state", jvStr(strings.ToLower(pythonStrOrEmpty(record.get("status"))))),
		jvKey("download_state", jvStr(pythonStrOrEmpty(record.get("trackedDownloadState")))),
		jvKey("download_status", jvStr(strings.ToLower(pythonStrOrEmpty(record.get("trackedDownloadStatus"))))),
		jvKey("progress", jvFloat(min(1, max(0, progress)))),
		jvKey("time_left", jvStr(pythonStrOrEmpty(record.get("timeleft")))),
		jvKey("problem", problem),
	)
}

// localStashdbScenes maps StashDB scene ids to a local scene id. Recently
// changed scenes are refreshed first so a just-imported scene counts.
func localStashdbScenes(pluginDir string, payload, settings jVal, db dbx) (map[string]string, bool, error) {
	ready, err := ensureLocalSceneMatches(pluginDir, payload, settings, db)
	if err != nil || !ready {
		return map[string]string{}, false, err
	}
	base, headers := stashConnection(payload)
	if err := refreshPendingLocalSceneMatches(db, base, headers); err != nil {
		return nil, false, err
	}
	rows, err := db.Query(`SELECT value, MIN(CAST(scene_id AS INTEGER)) FROM local_scene_match
WHERE kind='stashdb_id' GROUP BY value`)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	scenes := map[string]string{}
	for rows.Next() {
		var value string
		var sceneID int64
		if err := rows.Scan(&value, &sceneID); err != nil {
			return nil, false, err
		}
		scenes[value] = fmt.Sprint(sceneID)
	}
	return scenes, true, rows.Err()
}

// whisparrSentAt is when Curator sent each StashDB scene to Whisparr.
func whisparrSentAt(db dbx) (map[string]int64, error) {
	rows, err := db.Query(`SELECT external_id, sent_at_ms FROM external_whisparr_sent WHERE endpoint=lower(?)`, stashdbEndpoint)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	sent := map[string]int64{}
	for rows.Next() {
		var id string
		var at int64
		if err := rows.Scan(&id, &at); err != nil {
			return nil, err
		}
		sent[id] = at
	}
	return sent, rows.Err()
}

// cachedSceneScores is Find's match score for scenes still in its cache.
func cachedSceneScores(db dbx, ids []string) (map[string]float64, error) {
	encoded := jvArr()
	for _, id := range ids {
		encoded.arr = append(encoded.arr, jvStr(id))
	}
	rows, err := db.Query(`SELECT external_id, MAX(score) FROM external_entity
WHERE entity_type='scene' AND external_id IN (SELECT value FROM json_each(?)) GROUP BY external_id`, encoded.marshalCompact())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	scores := map[string]float64{}
	for rows.Next() {
		var id string
		var score sql.NullFloat64
		if err := rows.Scan(&id, &score); err != nil {
			return nil, err
		}
		if score.Valid {
			scores[id] = score.Float64
		}
	}
	return scores, rows.Err()
}

func opGetWhisparrOverview(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_whisparr_overview",
		func(settings jVal) (jVal, error) { return getWhisparrOverviewBody(pluginDir, payload, settings) })
}

// whisparrStatuses orders the overview's status filter.
var whisparrStatuses = []string{"missing", "downloading", "not_in_stash", "in_library"}

func getWhisparrOverviewBody(pluginDir string, payload, settings jVal) (jVal, error) {
	api, err := newWhisparrAPI(settings)
	if err != nil {
		return jvNull(), err
	}
	movies, err := api.call("GET", "/movie", jvNull())
	if err != nil {
		return jvNull(), err
	}
	if movies.kind != jArr {
		return jvNull(), errors.New("Whisparr returned an invalid movie list")
	}
	queue, err := api.queue()
	if err != nil {
		return jvNull(), err
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	local, libraryReady, err := localStashdbScenes(pluginDir, payload, settings, db)
	if err != nil {
		return jvNull(), err
	}
	sent, err := whisparrSentAt(db)
	if err != nil {
		return jvNull(), err
	}
	ids := make([]string, 0, len(movies.arr))
	for _, movie := range movies.arr {
		if id := whisparrStashID(movie); id != "" {
			ids = append(ids, id)
		}
	}
	scores, err := cachedSceneScores(db, ids)
	if err != nil {
		return jvNull(), err
	}
	counts := map[string]int64{}
	items := jvArr()
	for _, movie := range movies.arr {
		whisparrID := pythonInt(movie.get("id"))
		if movie.kind != jObj || whisparrID < 1 {
			continue
		}
		stashID := whisparrStashID(movie)
		record, queued := queue[whisparrID]
		localID, inLibrary := local[stashID]
		status := "missing"
		switch {
		case stashID != "" && inLibrary:
			status = "in_library"
		case queued:
			status = "downloading"
		case movie.get("hasFile").truthy():
			status = "not_in_stash"
		}
		counts[status]++
		item := jvObj(
			jvKey("id", jvInt(whisparrID)),
			jvKey("stashdb_id", jvStr(stashID)),
			jvKey("title", jvStr(pythonStrOrEmpty(movie.get("title")))),
			jvKey("studio", jvStr(pythonStrOrEmpty(movie.get("studioTitle")))),
			jvKey("release_date", jvStr(firstNonEmpty(pythonStrOrEmpty(movie.get("releaseDate")), pythonStrOrEmpty(movie.get("digitalRelease"))))),
			jvKey("added", jvStr(pythonStrOrEmpty(movie.get("added")))),
			jvKey("monitored", jvBool(movie.get("monitored").truthy())),
			jvKey("has_file", jvBool(movie.get("hasFile").truthy())),
			jvKey("size_on_disk", jvInt(pythonInt(movie.get("sizeOnDisk")))),
			jvKey("title_slug", jvStr(pythonStrOrEmpty(movie.get("titleSlug")))),
			jvKey("image", jvStr(whisparrImage(movie))),
			jvKey("status", jvStr(status)),
			jvKey("local_scene_id", jvNull()),
			jvKey("queue", jvNull()),
			jvKey("sent_at_ms", jvNull()),
			jvKey("score", jvNull()),
		)
		if inLibrary && stashID != "" {
			item.set("local_scene_id", jvStr(localID))
		}
		if queued {
			item.set("queue", whisparrQueueItem(record))
		}
		if at, ok := sent[stashID]; ok && stashID != "" {
			item.set("sent_at_ms", jvInt(at))
		}
		if score, ok := scores[stashID]; ok && stashID != "" {
			item.set("score", jvFloat(score))
		}
		items.arr = append(items.arr, item)
	}
	countObj := jvObj()
	for _, status := range whisparrStatuses {
		countObj.set(status, jvInt(counts[status]))
	}
	return jvObj(
		jvKey("items", items),
		jvKey("counts", countObj),
		jvKey("library_ready", jvBool(libraryReady)),
		jvKey("whisparr_url", jvStr(strings.TrimSuffix(api.base, "/api/v3"))),
	), nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func opWhisparrAction(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "whisparr_action",
		func(settings jVal) (jVal, error) { return whisparrActionBody(pluginDir, payload, settings) })
}

// whisparrActionBody runs one action on a set of Whisparr scenes. Remove never
// deletes files: Curator does not delete media.
func whisparrActionBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	action := argsString(args, "action", "")
	rawIDs := args.get("whisparr_ids")
	if !isList(rawIDs) || len(rawIDs.arr) == 0 || len(rawIDs.arr) > whisparrActionLimit {
		return jvNull(), fmt.Errorf("whisparr_ids must be a list of 1 to %d ids", whisparrActionLimit)
	}
	ids := jvArr()
	seen := map[int64]bool{}
	for _, value := range rawIDs.arr {
		id := pythonInt(value)
		if id < 1 {
			return jvNull(), errors.New("whisparr_ids must be positive integers")
		}
		if !seen[id] {
			seen[id] = true
			ids.arr = append(ids.arr, jvInt(id))
		}
	}
	api, err := newWhisparrAPI(settings)
	if err != nil {
		return jvNull(), err
	}
	switch action {
	case "search":
		if _, err := api.call("POST", "/command", jvObj(jvKey("name", jvStr("MoviesSearch")), jvKey("movieIds", ids))); err != nil {
			return jvNull(), err
		}
	case "monitor", "unmonitor":
		if _, err := api.call("PUT", "/movie/editor", jvObj(jvKey("movieIds", ids), jvKey("monitored", jvBool(action == "monitor")))); err != nil {
			return jvNull(), err
		}
	case "remove":
		if _, err := api.call("DELETE", "/movie/editor", jvObj(
			jvKey("movieIds", ids),
			jvKey("deleteFiles", jvBool(false)),
			jvKey("addImportExclusion", jvBool(argsBool(args, "exclude", false))),
		)); err != nil {
			return jvNull(), err
		}
		// A scene removed here is no longer "sent": Find shows it as new again.
		var stashIDs []string
		for _, value := range args.get("stashdb_ids").arr {
			if id := strings.TrimSpace(pythonStrOrEmpty(value)); id != "" {
				stashIDs = append(stashIDs, id)
			}
		}
		if len(stashIDs) > 0 {
			sort.Strings(stashIDs)
			encoded := jvArr()
			for _, id := range stashIDs {
				encoded.arr = append(encoded.arr, jvStr(id))
			}
			db, err := openAPISidecar(pluginDir, payload, settings)
			if err != nil {
				return jvNull(), err
			}
			defer db.Close()
			if err := execImmediate(db, `DELETE FROM external_whisparr_sent WHERE endpoint=lower(?)
AND external_id IN (SELECT value FROM json_each(?))`, stashdbEndpoint, encoded.marshalCompact()); err != nil {
				return jvNull(), err
			}
		}
	default:
		return jvNull(), errors.New("action must be search, monitor, unmonitor, or remove")
	}
	return jvObj(jvKey("action", jvStr(action)), jvKey("count", jvInt(int64(len(ids.arr))))), nil
}
