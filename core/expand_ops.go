// Network-layer op wiring — ports of backend.py's get_expand,
// get_performer_hunt, get_external_similar dispatch (through _api), each
// running under the _profiled lifecycle.
package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"sync"
	"time"
)

// opGetExpand mirrors backend.py's _profiled-wrapped get_expand dispatch.
func opGetExpand(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_expand",
		func(settings jVal) (jVal, error) { return getExpandBody(pluginDir, payload, settings) })
}

func getExpandBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	args := payload.get("args")
	entityType := argsString(args, "entity_type", "scene")
	page := argsInt(args, "page", 1)
	sortBy := argsString(args, "sort", "match")
	performerID := argsOptionalString(args, "performer_id")
	favoriteOnly := argsBool(args, "favorite_only", false)
	// Python: str(args.get("gender", config["expand_gender"])) — a present
	// null still produces "None".
	gender := cfg.get("expand_gender").asString()
	if args.has("gender") {
		gender = args.get("gender").asString()
	}
	includeTags, err := stringList(args.get("include_tags"))
	if err != nil {
		return jvNull(), err
	}
	excludeTags, err := stringList(args.get("exclude_tags"))
	if err != nil {
		return jvNull(), err
	}
	performerQuery := argsString(args, "performer_query", "")
	studioQuery := argsString(args, "studio_query", "")
	performerNames, err := stringList(args.get("performer_names"))
	if err != nil {
		return jvNull(), err
	}
	studioNames, err := stringList(args.get("studio_names"))
	if err != nil {
		return jvNull(), err
	}
	hidePhash := argsBool(args, "hide_phash_matches", true)
	minimumScore := -1.0
	if v := args.get("minimum_score"); v.kind != jNull {
		minimumScore, err = pythonFloat(v)
		if err != nil {
			return jvNull(), err
		}
	}
	count := argsInt(args, "count", pythonInt(cfg.get("page_size")))
	// The local-match exclusion is re-derived at serve time against the
	// current links map: a candidate fetched while the local scene had no
	// StashDB id keeps its missing annotation in payload_json forever, so
	// the stored annotation is never authoritative for hiding (issue #118).
	links := jvNull()
	if entityType == "scene" {
		ready, err := ensureLocalSceneMatches(pluginDir, payload, settings, db)
		if err != nil {
			return jvNull(), err
		}
		if !ready {
			return jvObj(jvKey("ready", jvBool(false)), jvKey("initializing", jvBool(true)),
				jvKey("page", jvInt(page)), jvKey("page_size", jvInt(count)),
				jvKey("total", jvInt(0)), jvKey("has_more", jvBool(false)), jvKey("items", jvArr())), nil
		}
		links, err = localSceneLinks(payload, db)
		if err != nil {
			return jvNull(), err
		}
	}
	return expandResults(db, entityType, page, sortBy, performerID, favoriteOnly, gender,
		includeTags, excludeTags, performerNames, studioNames, performerQuery, studioQuery,
		hidePhash, minimumScore, count, links)
}

// expandResults mirrors ExpandService.results.
func expandResults(db dbx, entityType string, page int64, sortBy string, performerID jVal,
	favoriteOnly bool, gender string, includeTags, excludeTags, performerNames, studioNames []string,
	performerQuery, studioQuery string, hidePhash bool, minimumScore float64, count int64,
	links jVal) (jVal, error) {
	if (entityType != "scene" && entityType != "performer") || (sortBy != "match" && sortBy != "newest") {
		return jvNull(), errors.New("invalid Expand query")
	}
	if page < 1 || count < 1 || count > 500 || page > math.MaxInt64/count {
		return jvNull(), errors.New("invalid Expand page")
	}
	if minimumScore < -1 || minimumScore > 1 {
		return jvNull(), errors.New("minimum_score must be between -1 and 1")
	}
	var fetchedAtMs, expiresAtMs int64
	cacheFound := false
	err := db.QueryRow(`SELECT fetched_at_ms, expires_at_ms FROM expand_cache WHERE singleton=1`).
		Scan(&fetchedAtMs, &expiresAtMs)
	if err == nil {
		cacheFound = true
	} else if err != sql.ErrNoRows {
		return jvNull(), err
	}
	if !cacheFound {
		return jvObj(
			jvKey("ready", jvBool(false)),
			jvKey("page", jvInt(page)),
			jvKey("page_size", jvInt(count)),
			jvKey("total", jvInt(0)),
			jvKey("has_more", jvBool(false)),
			jvKey("items", jvArr()),
		), nil
	}
	shortlisted := map[string]bool{}
	shortRows, err := db.Query(`SELECT external_id FROM external_shortlist WHERE entity_type=?`, entityType)
	if err != nil {
		return jvNull(), err
	}
	for shortRows.Next() {
		var externalID string
		if err := shortRows.Scan(&externalID); err != nil {
			return jvNull(), err
		}
		shortlisted[externalID] = true
	}
	shortRows.Close()
	if err := shortRows.Err(); err != nil {
		return jvNull(), err
	}
	includeGroups, err := equivalentTagNames(db, includeTags)
	if err != nil {
		return jvNull(), err
	}
	excludeGroups, err := equivalentTagNames(db, excludeTags)
	if err != nil {
		return jvNull(), err
	}
	service := newExpandService(db)
	blockedGroups, err := service.blockedTagNameGroups()
	if err != nil {
		return jvNull(), err
	}
	var byExternalID, byPhash map[string]string
	if links.kind == jObj {
		byExternalID, byPhash = sceneLinkMaps(links)
	}
	var revision int64
	if err := db.QueryRow(`SELECT revision FROM expand_candidate_revision WHERE entity_type=?`, entityType).Scan(&revision); err != nil {
		return jvNull(), err
	}
	digest := sha256.New()
	encoder := json.NewEncoder(digest)
	if err := encoder.Encode([]any{entityType, sortBy, performerID.marshalCompact(), favoriteOnly, gender,
		includeTags, excludeTags, performerNames, studioNames, performerQuery, studioQuery, hidePhash,
		minimumScore, includeGroups, excludeGroups, blockedGroups, byExternalID, byPhash, revision}); err != nil {
		return jvNull(), err
	}
	type expandRow struct {
		externalID  string
		score       float64
		payloadJSON string
		sourcesJSON string
	}
	render := func(row expandRow, payload jVal) jVal {
		sources, err := parseJSON([]byte(row.sourcesJSON))
		if err != nil {
			sources = jvArr()
		}
		return jvObj(
			jvKey("id", jvStr(row.externalID)),
			jvKey("score", jvFloat(row.score)),
			jvKey("sources", sources),
			jvKey("payload", payload),
			jvKey("shortlisted", jvBool(shortlisted[row.externalID])),
		)
	}
	fingerprint := hex.EncodeToString(digest.Sum(nil))
	// Candidate triggers advance the revision; unchanged pages only load their
	// own payloads. Filter, taxonomy, block and library inputs stay fingerprinted.
	cacheKey := "expand_order:v2:" + entityType
	var cached string
	err = db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, cacheKey).Scan(&cached)
	if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	if parsed, parseErr := parseJSON([]byte(cached)); parseErr == nil && parsed.get("fingerprint").asString() == fingerprint && parsed.get("ids").kind == jArr {
		ids := parsed.get("ids").arr
		start, end := (page-1)*count, minInt64(page*count, int64(len(ids)))
		requested := jvArr()
		for i := start; i < end; i++ {
			requested.arr = append(requested.arr, ids[i])
		}
		// Check the revision in the page query's snapshot too, so a concurrent
		// candidate update cannot combine an old ordering with new payloads.
		pageRows, err := db.Query(`SELECT e.external_id, e.score, e.payload_json, e.sources_json
FROM json_each(?) requested CROSS JOIN external_entity e ON e.external_id=requested.value
WHERE e.entity_type=? AND e.pool='candidate'
AND (SELECT revision FROM expand_candidate_revision WHERE entity_type=?)=?
ORDER BY CAST(requested.key AS INTEGER)`, requested.marshalCompact(), entityType, entityType, revision)
		if err != nil {
			return jvNull(), err
		}
		items := jvArr()
		for pageRows.Next() {
			var row expandRow
			if err := pageRows.Scan(&row.externalID, &row.score, &row.payloadJSON, &row.sourcesJSON); err != nil {
				pageRows.Close()
				return jvNull(), err
			}
			payload, err := parseJSON([]byte(row.payloadJSON))
			if err != nil {
				pageRows.Close()
				return jvNull(), err
			}
			if links.kind == jObj && entityType == "scene" {
				payload = annotateLocalMatch(payload, byExternalID, byPhash)
			}
			items.arr = append(items.arr, render(row, payload))
		}
		pageRows.Close()
		if err := pageRows.Err(); err != nil {
			return jvNull(), err
		}
		if len(items.arr) == len(requested.arr) {
			return expandPageResult(page, count, fetchedAtMs, expiresAtMs, int64(len(ids)), items), nil
		}
	}
	// Cache misses still parse and rank the full candidate pool in parallel.
	entityRows, err := db.Query(`SELECT external_id, score, payload_json, sources_json
FROM external_entity WHERE entity_type=? AND pool='candidate' ORDER BY external_id`, entityType)
	if err != nil {
		return jvNull(), err
	}
	materialized := make([]expandRow, 0)
	for entityRows.Next() {
		var row expandRow
		if err := entityRows.Scan(&row.externalID, &row.score, &row.payloadJSON, &row.sourcesJSON); err != nil {
			entityRows.Close()
			return jvNull(), err
		}
		materialized = append(materialized, row)
	}
	entityRows.Close()
	if err := entityRows.Err(); err != nil {
		return jvNull(), err
	}
	results := make([]jVal, len(materialized))
	errs := make([]error, len(materialized))
	workers := nthreads(0)
	if workers > len(materialized) {
		workers = len(materialized)
	}
	if workers < 1 {
		workers = 1
	}
	var wg sync.WaitGroup
	jobCh := make(chan int)
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobCh {
				row := materialized[i]
				if row.score < minimumScore {
					continue
				}
				payload, err := parseJSON([]byte(row.payloadJSON))
				if err != nil {
					errs[i] = err
					continue
				}
				// Issue #118: the stored annotation can be stale (the
				// candidate was fetched before the local scene gained its
				// StashDB id). Re-derive it against the current links map;
				// the serve-time match is authoritative for the exclusion and
				// for the served payload.
				if links.kind == jObj && entityType == "scene" {
					payload = annotateLocalMatch(payload, byExternalID, byPhash)
				}
				matchType := payload.get("curator_local_match").get("type").asString()
				if entityType == "scene" && (matchType == "stashdb_id" || (hidePhash && matchType == "phash")) {
					continue
				}
				if performerID.kind != jNull && entityType == "scene" {
					found := false
					for _, item := range payload.get("performers").arr {
						if item.get("performer").get("id").asString() == performerID.asString() {
							found = true
							break
						}
					}
					if !found {
						continue
					}
				}
				if favoriteOnly && entityType == "scene" {
					hasFavorite := false
					for _, item := range payload.get("performers").arr {
						if item.get("performer").get("curator_local").get("favorite").truthy() {
							hasFavorite = true
							break
						}
					}
					if !hasFavorite {
						continue
					}
				}
				if gender != "" && !payloadMatchesGender(payload, entityType, gender) {
					continue
				}
				if entityType == "scene" && !expandSceneMatches(payload, includeTags, excludeTags,
					performerNames, studioNames, performerQuery, studioQuery,
					includeGroups, excludeGroups, blockedGroups) {
					continue
				}
				results[i] = render(row, payload)
			}
		}()
	}
	for i := range materialized {
		jobCh <- i
	}
	close(jobCh)
	wg.Wait()
	for _, err := range errs {
		if err != nil {
			return jvNull(), err
		}
	}
	rows := make([]jVal, 0, len(results))
	for _, result := range results {
		if result.kind != jNull {
			rows = append(rows, result)
		}
	}
	if sortBy == "newest" && entityType == "scene" {
		sort.SliceStable(rows, func(i, j int) bool {
			left := sortNewestKey(rows[i])
			right := sortNewestKey(rows[j])
			if left.date != right.date {
				return left.date > right.date
			}
			return left.score > right.score
		})
	} else {
		sort.SliceStable(rows, func(i, j int) bool {
			leftScore := pythonFloatOr(rows[i].get("score"), 0)
			rightScore := pythonFloatOr(rows[j].get("score"), 0)
			if leftScore != rightScore {
				return leftScore > rightScore
			}
			return rows[i].get("id").asString() < rows[j].get("id").asString()
		})
		if entityType == "scene" {
			rows = expandDiverseScenes(rows)
		}
	}
	start := (page - 1) * count
	end := page * count
	var pageItems jVal
	if start < int64(len(rows)) {
		pageItems = jvArr(rows[start:minInt64(end, int64(len(rows)))]...)
	} else {
		pageItems = jvArr()
	}
	ids := jvArr()
	for _, row := range rows {
		ids.arr = append(ids.arr, row.get("id"))
	}
	if err := execImmediate(db, `INSERT INTO application_meta(key,value) VALUES (?,?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, cacheKey,
		jvObj(jvKey("fingerprint", jvStr(fingerprint)), jvKey("ids", ids)).marshalCompact()); err != nil {
		warnLog("Could not cache Expand ordering: " + err.Error())
	}
	return expandPageResult(page, count, fetchedAtMs, expiresAtMs, int64(len(rows)), pageItems), nil
}

func expandPageResult(page, count, fetchedAtMs, expiresAtMs, total int64, items jVal) jVal {
	return jvObj(
		jvKey("ready", jvBool(true)),
		jvKey("fetched_at_ms", jvInt(fetchedAtMs)),
		jvKey("expires_at_ms", jvInt(expiresAtMs)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(total)),
		jvKey("has_more", jvBool(total > page*count)),
		jvKey("items", items),
	)
}

type newestKey struct {
	date  string
	score float64
}

func sortNewestKey(item jVal) newestKey {
	date := pythonStrOrEmpty(item.get("payload").get("release_date"))
	if date == "" {
		date = pythonStrOrEmpty(item.get("payload").get("production_date"))
	}
	return newestKey{date: date, score: pythonFloatOr(item.get("score"), 0)}
}

// opGetStashdbPerformerSearch — name search over StashDB performers for the
// Performer Hunt picker (issue #218): lets the user hunt scenes for a
// performer that is not in the local library.
func opGetStashdbPerformerSearch(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_stashdb_performer_search",
		func(settings jVal) (jVal, error) { return getStashdbPerformerSearchBody(pluginDir, payload, settings) })
}

func getStashdbPerformerSearchBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	query := argsString(args, "query", "")
	limit := argsInt(args, "limit", 8)
	if limit < 1 || limit > 50 {
		limit = 8
	}
	clientURL, apiKey, err := stashdbClient(payload)
	if err != nil {
		return jvNull(), err
	}
	search := jvObj(
		jvKey("page", jvInt(1)),
		jvKey("per_page", jvInt(limit)),
		jvKey("names", jvStr(query)),
	)
	data, err := stashdbQuery(clientURL, apiKey, stashdbPerformerSearchQuery, jvObj(jvKey("input", search)))
	if err != nil {
		return jvNull(), err
	}
	items := jvArr()
	for _, performer := range data.get("queryPerformers").get("performers").arr {
		items.arr = append(items.arr, jvObj(
			jvKey("id", performer.get("id")),
			jvKey("name", performer.get("name")),
			jvKey("aliases", performer.get("aliases")),
			jvKey("disambiguation", performer.get("disambiguation")),
			jvKey("scene_count", performer.get("scene_count")),
			jvKey("images", performer.get("images")),
		))
	}
	return jvObj(jvKey("items", items)), nil
}

// opGetPerformerHunt mirrors backend.py's _profiled-wrapped get_performer_hunt.
func opGetPerformerHunt(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_performer_hunt",
		func(settings jVal) (jVal, error) { return getPerformerHuntBody(pluginDir, payload, settings) })
}

func getPerformerHuntBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	performerID := argsString(args, "performer_id", "")
	includeTags, err := stringList(args.get("include_tags"))
	if err != nil {
		return jvNull(), err
	}
	excludeTags, err := stringList(args.get("exclude_tags"))
	if err != nil {
		return jvNull(), err
	}
	clientURL, apiKey, err := stashdbClient(payload)
	if err != nil {
		return jvNull(), err
	}
	links, err := externalLinks(payload, db)
	if err != nil {
		return jvNull(), err
	}
	result, err := expandPerformerHunt(db, clientURL, apiKey, links, performerID,
		performerHuntLimit, includeTags, excludeTags)
	return result, err
}

// expandPerformerHunt mirrors ExpandService.performer_hunt.
func expandPerformerHunt(db dbx, clientURL, apiKey string, links jVal, performerID string,
	limit int64, includeTags, excludeTags []string) (jVal, error) {
	var name sql.NullString
	err := db.QueryRow(`SELECT name FROM source_performer WHERE performer_id=?`, performerID).Scan(&name)
	isLocal := err == nil
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return jvNull(), err
	}
	externalPerformerID := performerID
	performerName := performerID
	if isLocal {
		external := links.get("performers").get(performerID)
		if !external.truthy() {
			return jvNull(), errors.New("selected performer is not linked to StashDB")
		}
		externalPerformerID = external.asString()
		if name.Valid && name.String != "" {
			performerName = name.String
		}
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	featureVersion, err := currentFeatureVersion(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" || featureVersion == "" {
		return jvNull(), errors.New("no published model")
	}
	rows := &sceneRows{m: map[string]jVal{}}
	sources := map[string]map[string]bool{}
	totalCount, truncated, err := fetchParallel(clientURL, apiKey,
		fetchPageSpec{source: "performers", values: []string{externalPerformerID}, limit: limit, modifier: "INCLUDES", sort: "DATE"},
		rows, sources, 8)
	if err != nil {
		return jvNull(), err
	}
	if !isLocal {
		for _, scene := range rows.order {
			performerName = ""
			for _, item := range rows.m[scene].get("performers").arr {
				if item.get("performer").get("id").asString() == externalPerformerID {
					performerName = pythonStrOrEmpty(item.get("performer").get("name"))
					break
				}
			}
			if performerName != "" {
				break
			}
		}
		if performerName == "" {
			performerName = performerID
		}
	}
	annotated := make([]jVal, 0, len(rows.order))
	byExternalID, byPhash := sceneLinkMaps(links)
	for _, id := range rows.order {
		annotated = append(annotated, annotateLocalMatch(rows.m[id], byExternalID, byPhash))
	}
	service := newExpandService(db)
	scenes, _, err := service.score(annotated, sources, modelID, featureVersion, links, jvStr(performerID))
	if err != nil {
		return jvNull(), err
	}
	if err := service.mergeExternal("scene", scenes); err != nil {
		return jvNull(), err
	}
	includeGroups, err := equivalentTagNames(db, includeTags)
	if err != nil {
		return jvNull(), err
	}
	excludeGroups, err := equivalentTagNames(db, excludeTags)
	if err != nil {
		return jvNull(), err
	}
	blockedGroups, err := service.blockedTagNameGroups()
	if err != nil {
		return jvNull(), err
	}
	shortlisted := map[string]bool{}
	shortRows, err := db.Query(`SELECT external_id FROM external_shortlist WHERE entity_type='scene'`)
	if err != nil {
		return jvNull(), err
	}
	for shortRows.Next() {
		var externalID string
		if err := shortRows.Scan(&externalID); err != nil {
			return jvNull(), err
		}
		shortlisted[externalID] = true
	}
	shortRows.Close()
	if err := shortRows.Err(); err != nil {
		return jvNull(), err
	}
	items := make([]jVal, 0, len(scenes))
	for _, scene := range scenes {
		if !expandSceneMatches(scene.payload, includeTags, excludeTags, nil, nil, "", "",
			includeGroups, excludeGroups, blockedGroups) {
			continue
		}
		item := jvObj(
			jvKey("id", jvStr(scene.id)),
			jvKey("payload", scene.payload),
			jvKey("score", jvFloat(scene.score)),
			jvKey("sources", jvStrList(scene.sources)),
		)
		if scene.hasMultiHop {
			item.set("multi_hop_reach", jvFloat(scene.multiHopReach))
		}
		match := scene.payload.get("curator_local_match")
		item.set("linked_locally", jvBool(match.kind == jObj))
		item.set("local_scene_id", match.get("local_scene_id"))
		item.set("match_type", match.get("type"))
		item.set("shortlisted", jvBool(shortlisted[scene.id]))
		items = append(items, item)
	}
	sort.SliceStable(items, func(i, j int) bool {
		leftReach := boolFloat(items[i].get("multi_hop_reach").truthy())
		rightReach := boolFloat(items[j].get("multi_hop_reach").truthy())
		leftDate := pythonStrOrEmpty(items[i].get("payload").get("release_date"))
		if leftDate == "" {
			leftDate = pythonStrOrEmpty(items[i].get("payload").get("production_date"))
		}
		rightDate := pythonStrOrEmpty(items[j].get("payload").get("release_date"))
		if rightDate == "" {
			rightDate = pythonStrOrEmpty(items[j].get("payload").get("production_date"))
		}
		if leftReach != rightReach {
			return leftReach > rightReach
		}
		if leftDate != rightDate {
			return leftDate > rightDate
		}
		return items[i].get("id").asString() > items[j].get("id").asString()
	})
	linkedCount := int64(0)
	for _, item := range items {
		if item.get("linked_locally").truthy() {
			linkedCount++
		}
	}
	return jvObj(
		jvKey("ready", jvBool(true)),
		jvKey("performer_id", jvStr(performerID)),
		jvKey("performer_name", jvStr(performerName)),
		jvKey("stashdb_total", jvInt(totalCount)),
		jvKey("fetched_count", jvInt(int64(len(items)))),
		jvKey("total", jvInt(int64(len(items)))),
		jvKey("linked_count", jvInt(linkedCount)),
		jvKey("not_linked_count", jvInt(int64(len(items))-linkedCount)),
		jvKey("truncated", jvBool(truncated)),
		jvKey("limit", jvInt(limit)),
		jvKey("items", jvArr(items...)),
	), nil
}

// opGetExternalSimilar mirrors backend.py's _profiled-wrapped
// get_external_similar dispatch.
func opGetExternalSimilar(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_external_similar",
		func(settings jVal) (jVal, error) { return getExternalSimilarBody(pluginDir, payload, settings) })
}

func getExternalSimilarBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := config.get("config")
	args := payload.get("args")
	entityType := argsString(args, "entity_type", "")
	entityID := argsString(args, "entity_id", "")
	gender := cfg.get("expand_gender").asString()
	if args.has("gender") {
		gender = args.get("gender").asString()
	}
	includeTags, err := stringList(args.get("include_tags"))
	if err != nil {
		return jvNull(), err
	}
	excludeTags, err := stringList(args.get("exclude_tags"))
	if err != nil {
		return jvNull(), err
	}
	performerNames, err := stringList(args.get("performer_names"))
	if err != nil {
		return jvNull(), err
	}
	studioNames, err := stringList(args.get("studio_names"))
	if err != nil {
		return jvNull(), err
	}
	favoriteOnly := argsBool(args, "favorite_only", false)
	includeOwned := argsBool(args, "include_owned", false)
	hidePhash := argsBool(args, "hide_phash_matches", true)
	minimumSimilarity := 0.15
	if v := args.get("minimum_similarity"); v.kind != jNull {
		minimumSimilarity, err = pythonFloat(v)
		if err != nil {
			return jvNull(), err
		}
	}
	clientURL, apiKey, err := stashdbClient(payload)
	if err != nil {
		return jvNull(), err
	}
	links, err := externalLinks(payload, db)
	if err != nil {
		return jvNull(), err
	}
	return expandTargetedSimilar(db, clientURL, apiKey, links, entityType, entityID,
		gender, 100, includeTags, excludeTags, performerNames, studioNames,
		favoriteOnly, includeOwned, hidePhash, minimumSimilarity)
}

// recordDurationMs mirrors curator.profiling.record_duration: a back-dated
// span for a measured stage when a trace is active.
func recordDurationMs(t *trace, category, name string, durationMs int64) {
	if t == nil {
		return
	}
	endedNs := time.Now().UnixNano()
	startedNs := t.startedNs
	if backdated := endedNs - maxInt64(0, durationMs)*1_000_000; backdated > startedNs {
		startedNs = backdated
	}
	t.record(category, name, startedNs, endedNs-startedNs, jvNull())
}
