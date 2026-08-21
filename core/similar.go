// get_similar — a port of backend.py's get_similar dispatch and
// SimilarityService (curator/similarity.py): preference-aware local scene and
// performer similarity with the multi-hop performer-graph blend, plus the
// ranked-impression write for scene similarity (with the busy_timeout=100
// lock swallow).
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
)

// multiHopBlendWeight mirrors similarity.MULTI_HOP_BLEND_WEIGHT.
const multiHopBlendWeight = 0.05

// setTimingKeys resets the service timings object to the given key set with
// zero values, preserving insertion order (Python's dict assignment order).
func (s *similarityService) setTimingKeys(keys ...string) {
	s.timingsMs = jvObj()
	for _, key := range keys {
		s.timingsMs.set(key, jvInt(0))
	}
}

// similarityResult mirrors SimilarityService.SimilarityResult.
type similarityResult struct {
	entityID      string
	similarity    float64
	appeal        float64
	rankScore     float64
	relationships []string
	details       jVal
	appealRaw     float64
	explanation   jVal
}

func similarityResultJSON(r *similarityResult) jVal {
	relationships := jvArr()
	for _, rel := range r.relationships {
		relationships.arr = append(relationships.arr, jvStr(rel))
	}
	return jvObj(
		jvKey("entity_id", jvStr(r.entityID)), jvKey("similarity", jvFloat(r.similarity)),
		jvKey("appeal", jvFloat(r.appeal)), jvKey("appeal_raw", jvFloat(r.appealRaw)),
		jvKey("rank_score", jvFloat(r.rankScore)), jvKey("relationships", relationships),
		jvKey("details", r.details), jvKey("explanation", r.explanation),
	)
}

func similarExplanation(similarity, appealRaw float64, relationships []string) jVal {
	labels := map[string]string{"same_performer": "Same performer", "similar_performer": "Similar performer profile", "shared_content": "Shared content", "similar_structure": "Similar cast structure", "same_studio": "Same studio", "multi_hop": "Multi-hop performer connection"}
	names := make([]string, 0, len(relationships))
	reasons := jvArr()
	for _, value := range relationships {
		label := labels[value]
		if label == "" {
			label = value
		}
		names = append(names, label)
		reasons.arr = append(reasons.arr, jvObj(jvKey("code", jvStr(value)), jvKey("label", jvStr(label)), jvKey("direction", jvStr("positive")), jvKey("magnitude", jvFloat(1)), jvKey("confidence", jvFloat(1))))
	}
	summary := "Closest available content match."
	if len(names) > 0 {
		summary = "Related through " + strings.Join(names, ", ")
	}
	components := jvArr()
	components.arr = append(components.arr,
		jvObj(jvKey("name", jvStr("content_similarity")), jvKey("label", jvStr("Similarity")), jvKey("value", jvFloat(similarity)), jvKey("scale", jvStr("0..1")), jvKey("direction", jvStr("positive")), jvKey("available", jvBool(true))),
		jvObj(jvKey("name", jvStr("appeal")), jvKey("label", jvStr("Appeal")), jvKey("value", jvFloat(appealRaw)), jvKey("scale", jvStr("-1..1")), jvKey("direction", jvStr(direction(appealRaw))), jvKey("available", jvBool(true))),
	)
	return jvObj(jvKey("summary", jvStr(summary)), jvKey("components", components), jvKey("reasons", reasons))
}

// similarityService mirrors SimilarityService.
type similarityService struct {
	db             dbx
	read           dbx // read-only pooled connection for parallel bulk reads
	modelID        string
	featureVersion string
	appeals        map[string]float64
	totalCount     int
	timingsMs      jVal
}

func newSimilarityService(db, read dbx) (*similarityService, error) {
	modelID, err := currentModelID(db)
	if err != nil {
		return nil, err
	}
	if modelID == "" {
		return nil, fmt.Errorf("no published model")
	}
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return nil, err
	}
	appeals := make(map[string]float64)
	rows, err := db.Query(`SELECT scene_id, max(appeal) AS appeal FROM model_scene_lane
WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id`, modelID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var appeal float64
		if err := rows.Scan(&sceneID, &appeal); err != nil {
			return nil, err
		}
		appeals[sceneID] = appeal
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	{
		// The lane index is a fast path, not a complete one: Stretch and Blind
		// Spots both gate (unlike the Adventure lane they replaced, which
		// admitted every eligible scene and so made the index complete by
		// construction). An eligible scene that misses every lane still needs
		// an appeal for Similar to surface it, so anything the index is
		// missing is filled in here rather than only falling back when the
		// index is empty outright.
		rows, err := db.Query(`SELECT scene_id, appeal FROM model_scene_score
WHERE model_id=? AND json_extract(eligibility_json, '$.eligible')=1`, modelID)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			var appeal float64
			if err := rows.Scan(&sceneID, &appeal); err != nil {
				return nil, err
			}
			if _, ok := appeals[sceneID]; !ok {
				appeals[sceneID] = appeal
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	return &similarityService{
		db:             db,
		read:           read,
		modelID:        modelID,
		featureVersion: featureVersion,
		appeals:        appeals,
		timingsMs:      jvObj(jvKey("initialization", jvInt(0))),
	}, nil
}

func opGetSimilar(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_similar",
		func(settings jVal) (jVal, error) { return getSimilarBody(pluginDir, payload, settings) })
}

// getSimilarBody mirrors backend.py's get_similar dispatch + CuratorAPI.similar.
func getSimilarBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	excluded := args.get("exclude_scene_ids")
	if args.has("exclude_scene_ids") && !isList(excluded) {
		return jvNull(), fmt.Errorf("exclude_scene_ids must be a list")
	}
	excludedSet, err := excludeSceneIDs(excluded)
	if err != nil {
		return jvNull(), err
	}
	entityType := argsString(args, "entity_type", "")
	entityID := argsString(args, "entity_id", "")
	count := argsInt(args, "count", pythonInt(cfg.get("page_size")))
	page := argsInt(args, "page", 1)
	var impressionID jVal = jvNull()
	if args.get("impression_id").truthy() {
		impressionID = jvStr(args.get("impression_id").asString())
	}
	gender := argsString(args, "gender", "")
	includeTags, err := stringList(args.get("include_tags"))
	if err != nil {
		return jvNull(), err
	}
	excludeTags, err := stringList(args.get("exclude_tags"))
	if err != nil {
		return jvNull(), err
	}
	performerIDs, err := stringList(args.get("performer_ids"))
	if err != nil {
		return jvNull(), err
	}
	studioIDs, err := stringList(args.get("studio_ids"))
	if err != nil {
		return jvNull(), err
	}
	favoriteOnly := argsBool(args, "favorite_only", false)
	minimumSimilarity := 0.18
	if v := args.get("minimum_similarity"); v.kind != jNull {
		minimumSimilarity, _ = pythonFloat(v)
	}
	readDB, err := openSidecarReadPool(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer readDB.Close()
	return similarCore(db, readDB, entityType, entityID, count, page, impressionID, gender, includeTags, excludeTags, performerIDs, studioIDs, favoriteOnly, minimumSimilarity, excludedSet)
}

// similarCore mirrors CuratorAPI.similar after arg coercion.
func similarCore(db, read dbx, entityType, entityID string, count, page int64, impressionID jVal,
	gender string, includeTags, excludeTags, performerIDs, studioIDs []string,
	favoriteOnly bool, minimumSimilarity float64, excluded map[string]bool) (jVal, error) {
	if page < 1 || count < 1 || count > 500 {
		return jvNull(), fmt.Errorf("invalid Similar page")
	}
	if minimumSimilarity < 0 || minimumSimilarity > 1 {
		return jvNull(), fmt.Errorf("minimum_similarity must be between 0 and 1")
	}
	start := (page - 1) * count
	end := page * count
	requested := end + 1 + int64(len(excluded))
	service, err := newSimilarityService(db, read)
	if err != nil {
		return jvNull(), err
	}
	var results []*similarityResult
	table := "source_scene"
	idColumn := "scene_id"
	labelColumn := "title"
	if entityType == "scene" {
		results, err = service.scenes(entityID, requested, gender, includeTags, excludeTags, performerIDs, studioIDs, favoriteOnly, minimumSimilarity)
		if err != nil {
			return jvNull(), err
		}
	} else if entityType == "performer" {
		results, err = service.performers(entityID, requested, gender)
		if err != nil {
			return jvNull(), err
		}
		table, idColumn, labelColumn = "source_performer", "performer_id", "name"
	} else {
		return jvNull(), fmt.Errorf("unsupported similar entity type: %s", entityType)
	}
	rawResults := results
	available := make([]*similarityResult, 0, len(rawResults))
	for _, item := range rawResults {
		if !excluded[item.entityID] {
			available = append(available, item)
		}
	}
	var paged []*similarityResult
	if start < int64(len(available)) {
		selEnd := minInt64(end, int64(len(available)))
		paged = available[start:selEnd]
	}
	rawSet := make(map[string]bool, len(rawResults))
	for _, item := range rawResults {
		rawSet[item.entityID] = true
	}
	overlap := 0
	for sceneID := range excluded {
		if rawSet[sceneID] {
			overlap++
		}
	}
	total := service.totalCount - overlap
	if total < 0 {
		total = 0
	}
	labels := make(map[string]string)
	rows, err := db.Query(`SELECT ` + idColumn + `, ` + labelColumn + ` FROM ` + table)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var id string
		var label sql.NullString
		if err := rows.Scan(&id, &label); err != nil {
			return jvNull(), err
		}
		labels[id] = ""
		if label.Valid {
			labels[id] = label.String
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	if impressionID.kind == jNull {
		impressionID = jvStr(uuid4())
	}
	var sceneImpression jVal = jvNull()
	if entityType == "scene" {
		swallowed, err := recordRankedImpressionSwallowed(db, impressionID.asString(), "similar", service.modelID, paged, start, entityID)
		if err != nil {
			return jvNull(), err
		}
		if swallowed {
			sceneImpression = jvNull()
		} else {
			sceneImpression = impressionID
		}
	}
	items := jvArr()
	for position, item := range paged {
		label := labels[item.entityID]
		obj := similarityResultJSON(item)
		obj.set("label", jvStr(label))
		obj.set("position", jvInt(start+int64(position)))
		items.arr = append(items.arr, obj)
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(service.modelID)),
		jvKey("entity_type", jvStr(entityType)),
		jvKey("entity_id", jvStr(entityID)),
		jvKey("impression_id", sceneImpression),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(int64(total))),
		jvKey("has_more", jvBool(int64(total) > end)),
		jvKey("timings_ms", service.timingsMs),
		jvKey("items", items),
	), nil
}

// recordRankedImpressionSwallowed mirrors api.similar's scene impression
// write: PRAGMA busy_timeout=100 around the write; a lock error whose message
// contains "locked" (casefolded) is swallowed (returning swallowed=true, so
// the caller emits impression_id None); busy_timeout is restored to 30000
// afterwards.
func recordRankedImpressionSwallowed(db dbx, impressionID, lane, modelID string, items []*similarityResult, start int64, sourceSceneID string) (bool, error) {
	conn, err := db.Conn(context.Background())
	if err != nil {
		return false, err
	}
	defer conn.Close()
	ctx := context.Background()
	if _, err := conn.ExecContext(ctx, "PRAGMA busy_timeout = 100"); err != nil {
		return false, err
	}
	swallowed := false
	impressionErr := recordRankedImpressionConn(conn, impressionID, lane, modelID, items, start, sourceSceneID)
	if impressionErr != nil {
		if strings.Contains(strings.ToLower(impressionErr.Error()), "locked") {
			swallowed = true
		} else {
			conn.ExecContext(ctx, "PRAGMA busy_timeout = 30000")
			return false, impressionErr
		}
	}
	if _, err := conn.ExecContext(ctx, "PRAGMA busy_timeout = 30000"); err != nil {
		return false, err
	}
	return swallowed, nil
}

// recordRankedImpressionConn mirrors InteractionStore.record_ranked_impression
// with the similar-path item shape: (entity_id, position, rank_score,
// relationships) and context {"provenance": "similar", "source_scene_id": ...}.
func recordRankedImpressionConn(conn *sql.Conn, impressionID, lane, modelID string, items []*similarityResult, start int64, sourceSceneID string) error {
	ctx := context.Background()
	contextJSON := jvObj(
		jvKey("provenance", jvStr("similar")),
		jvKey("source_scene_id", jvStr(sourceSceneID)),
	).marshalSortedKeys()
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	result, err := conn.ExecContext(ctx, `INSERT OR IGNORE INTO impression(
    impression_id, requested_at_ms, lane, model_id, config_version, request_context_json
) VALUES (?, ?, ?, ?, 'builtin', ?)`, impressionID, nowMs(), lane, modelID, contextJSON)
	if err != nil {
		conn.ExecContext(ctx, "ROLLBACK")
		return err
	}
	rowsAffected := int64(0)
	if result != nil {
		rowsAffected, _ = result.RowsAffected()
	}
	if rowsAffected > 0 {
		for position, item := range items {
			relationships := jvArr()
			for _, rel := range item.relationships {
				relationships.arr = append(relationships.arr, jvStr(rel))
			}
			if _, err := conn.ExecContext(ctx, `INSERT INTO impression_item(
    impression_id, scene_id, position, policy_score, reason_snapshot_json
) VALUES (?, ?, ?, ?, ?)`, impressionID, item.entityID, start+int64(position), item.rankScore, relationships.marshalCompact()); err != nil {
				conn.ExecContext(ctx, "ROLLBACK")
				return err
			}
		}
	}
	if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
		return err
	}
	return nil
}

// scenes mirrors SimilarityService.scenes.
func (s *similarityService) scenes(sceneID string, count int64, gender string,
	includeTags, excludeTags, performerIDs, studioIDs []string, favoriteOnly bool, minimumSimilarity float64) ([]*similarityResult, error) {
	var probe int
	err := s.db.QueryRow(`SELECT 1 FROM model_scene_score WHERE model_id=? AND scene_id=?`, s.modelID, sceneID).Scan(&probe)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("unknown scene: %s", sceneID)
	}
	if err != nil {
		return nil, err
	}
	candidateIDs := make(map[string]bool, len(s.appeals))
	for sceneID := range s.appeals {
		candidateIDs[sceneID] = true
	}
	// The similar reads split into artifact reads (the feature/model
	// generations are ATTACHed only on the main connection) and sidecar-table
	// reads. The sidecar reads run concurrently on the read-only pool (the
	// main connection stays pinned for writes + attaches; WAL permits
	// concurrent readers). All merges are deterministic, so the op output is
	// identical regardless of completion order.
	type similarReads struct {
		targetContent   map[string]map[string]float64
		contentOverlaps map[string]float64
		performers      map[string][]string
		genders         map[string]string
		studios         map[string]string
		names           map[string]string
		included        []map[string]bool
		excluded        []map[string]bool
		favorites       map[string]bool
		blockedScenes   map[string]bool
		blockedTerms    []string
	}
	var loads similarReads
	var readWG sync.WaitGroup
	var readMu sync.Mutex
	var readErr error
	runLoad := func(fn func() error) {
		readWG.Add(1)
		go func() {
			defer readWG.Done()
			if err := fn(); err != nil {
				readMu.Lock()
				if readErr == nil {
					readErr = err
				}
				readMu.Unlock()
			}
		}()
	}
	runLoad(func() error {
		var err error
		loads.targetContent, _, err = sceneContentVectors(s.db, s.featureVersion, map[string]bool{sceneID: true})
		return err
	})
	runLoad(func() error {
		var err error
		loads.contentOverlaps, err = sceneContentOverlaps(s.db, s.featureVersion, sceneID)
		return err
	})
	runLoad(func() error {
		var err error
		loads.performers, err = scenePerformers(s.read)
		return err
	})
	runLoad(func() error {
		var err error
		loads.genders, err = performerGenders(s.read)
		return err
	})
	runLoad(func() error {
		var err error
		loads.studios, err = studios(s.read)
		return err
	})
	runLoad(func() error {
		var err error
		loads.names, err = loadTagNames(s.read)
		return err
	})
	runLoad(func() error {
		var err error
		loads.included, err = equivalentTagNames(s.read, includeTags)
		return err
	})
	runLoad(func() error {
		var err error
		loads.excluded, err = equivalentTagNames(s.read, excludeTags)
		return err
	})
	runLoad(func() error {
		if favoriteOnly {
			var err error
			loads.favorites, err = loadFavoritePerformers(s.read)
			return err
		}
		return nil
	})
	runLoad(func() error {
		var err error
		loads.blockedScenes, err = loadBlockedScenes(s.read)
		return err
	})
	runLoad(func() error {
		var err error
		loads.blockedTerms, err = loadBlockedTerms(s.read)
		return err
	})
	readWG.Wait()
	if readErr != nil {
		return nil, readErr
	}
	targetVector := loads.targetContent[sceneID]
	if targetVector == nil {
		targetVector = map[string]float64{}
	}
	targetPerformers := loads.performers[sceneID]
	performerScores := make(map[string]float64)
	for _, targetID := range targetPerformers {
		edgeRows, err := s.db.Query(`SELECT similar_performer_id, similarity FROM model_performer_edge
WHERE model_id=? AND performer_id=? ORDER BY rank`, s.modelID, targetID)
		if err != nil {
			return nil, err
		}
		for edgeRows.Next() {
			var similarID string
			var similarity float64
			if err := edgeRows.Scan(&similarID, &similarity); err != nil {
				return nil, err
			}
			if similarity > performerScores[similarID] {
				performerScores[similarID] = similarity
			}
		}
		edgeRows.Close()
		if err := edgeRows.Err(); err != nil {
			return nil, err
		}
	}
	targetStudio := loads.studios[sceneID]
	targetStructure := minFloat64(1.0, mathMax(0.0, float64(len(targetPerformers)-1))/3.0)
	filterNames := make(map[string]bool)
	for _, group := range loads.included {
		for name := range group {
			filterNames[name] = true
		}
	}
	for _, group := range loads.excluded {
		for name := range group {
			filterNames[name] = true
		}
	}
	var sceneTags map[string]map[string]bool
	if len(filterNames) > 0 {
		var err error
		sceneTags, err = sceneTagNames(s.read, filterNames)
		if err != nil {
			return nil, err
		}
	}
	if len(loads.blockedTerms) > 0 {
		placeholders := inClause(len(loads.blockedTerms))
		args := make([]any, 0, len(loads.blockedTerms)+1)
		args = append(args, s.featureVersion)
		for _, term := range loads.blockedTerms {
			args = append(args, "desc:"+term)
		}
		rows, err := s.db.Query(`SELECT DISTINCT ef.entity_id FROM entity_feature ef
JOIN feature_definition fd ON fd.feature_id=ef.feature_id
WHERE ef.feature_version=? AND ef.entity_type='scene'
  AND fd.family='content'
  AND fd.name IN (`+placeholders+`)`, args...)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var blockedSceneID string
			if err := rows.Scan(&blockedSceneID); err != nil {
				rows.Close()
				return nil, err
			}
			loads.blockedScenes[blockedSceneID] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	performerIDSet := make(map[string]bool, len(performerIDs))
	for _, id := range performerIDs {
		performerIDSet[id] = true
	}
	studioIDSet := make(map[string]bool, len(studioIDs))
	for _, id := range studioIDs {
		studioIDSet[id] = true
	}
	var results []*similarityResult
	for candidateID := range candidateIDs {
		candidateAppeal := s.appeals[candidateID]
		if candidateID == sceneID {
			continue
		}
		if loads.blockedScenes[candidateID] {
			continue
		}
		candidatePerformers := loads.performers[candidateID]
		if gender != "" {
			matched := false
			for _, value := range candidatePerformers {
				if loads.genders[value] == gender {
					matched = true
					break
				}
			}
			if !matched {
				continue
			}
		}
		same := intersectStringSets(targetPerformers, candidatePerformers)
		profileValue := 0.0
		profileFound := false
		for _, value := range candidatePerformers {
			if score, ok := performerScores[value]; ok && (!profileFound || score > profileValue) {
				profileValue = score
				profileFound = true
			}
		}
		performerValue := 1.0
		if len(same) == 0 {
			// Python's max((performer_scores.get(v, 0) ...), default=0)
			// yields the int 0 when no candidate performer has a score.
			if !profileFound {
				performerValue = 0
			} else {
				performerValue = profileValue
			}
		}
		candidateTags := sceneTags[candidateID]
		skip := false
		for _, group := range loads.included {
			has := false
			for name := range group {
				if candidateTags[name] {
					has = true
					break
				}
			}
			if !has {
				skip = true
				break
			}
		}
		if skip {
			continue
		}
		for _, group := range loads.excluded {
			has := false
			for name := range group {
				if candidateTags[name] {
					has = true
					break
				}
			}
			if has {
				skip = true
				break
			}
		}
		if skip {
			continue
		}
		if favoriteOnly && !anyIntersects(loads.favorites, candidatePerformers) {
			continue
		}
		if len(performerIDSet) > 0 && !containsAll(candidatePerformers, performerIDSet) {
			continue
		}
		if len(studioIDSet) > 0 {
			candidateStudio, ok := loads.studios[candidateID]
			if !ok || !studioIDSet[candidateStudio] {
				continue
			}
		}
		contentValue := loads.contentOverlaps[candidateID]
		structure := 1 - mathAbs(targetStructure-minFloat64(1.0, mathMax(0.0, float64(len(candidatePerformers)-1))/3.0))
		sameStudio := targetStudio != "" && loads.studios[candidateID] == targetStudio
		similarity := 0.5*contentValue + 0.3*performerValue + 0.1*structure
		if sameStudio {
			similarity += 0.1
		}
		if similarity < minimumSimilarity {
			continue
		}
		var relationships []string
		if len(same) > 0 {
			relationships = append(relationships, "same_performer")
		} else if profileValue >= 0.65 {
			relationships = append(relationships, "similar_performer")
		}
		if contentValue > 0 {
			relationships = append(relationships, "shared_content")
		}
		if structure >= 0.8 {
			relationships = append(relationships, "similar_structure")
		}
		if sameStudio {
			relationships = append(relationships, "same_studio")
		}
		appeal := (candidateAppeal + 1) / 2
		rankScore := 0.7*similarity + 0.3*appeal
		sharedIDs := make([]string, 0, len(same))
		for id := range same {
			sharedIDs = append(sharedIDs, id)
		}
		sort.Strings(sharedIDs)
		sharedIDsJSON := jvArr()
		for _, id := range sharedIDs {
			sharedIDsJSON.arr = append(sharedIDsJSON.arr, jvStr(id))
		}
		var performerVal jVal = jvFloat(performerValue)
		if len(same) == 0 && !profileFound {
			performerVal = jvInt(0)
		}
		details := jvObj(
			jvKey("content", jvFloat(contentValue)), jvKey("performer", performerVal),
			jvKey("structure", jvFloat(structure)), jvKey("studio", jvFloat(boolFloat(sameStudio))),
			jvKey("shared_tags", jvArr()), jvKey("shared_performer_ids", sharedIDsJSON),
			jvKey("score_breakdown", jvObj(
				jvKey("similarity", jvFloat(math.Round(0.7*similarity*1e4)/1e4)),
				jvKey("appeal", jvFloat(math.Round(0.3*appeal*1e4)/1e4)),
			)),
		)
		results = append(results, &similarityResult{
			entityID: candidateID, similarity: similarity, appeal: appeal,
			rankScore: rankScore, relationships: relationships, details: details,
			appealRaw: candidateAppeal, explanation: similarExplanation(similarity, candidateAppeal, relationships),
		})
	}
	sort.Slice(results, func(i, j int) bool {
		if results[i].rankScore != results[j].rankScore {
			return results[i].rankScore > results[j].rankScore
		}
		return results[i].entityID < results[j].entityID
	})
	s.totalCount = len(results)
	mh := newMultiHop(s.db, s.modelID)
	reach, err := mh.reach(sceneID)
	if err != nil {
		return nil, err
	}
	if len(reach) > 0 {
		blended := make([]*similarityResult, 0, len(results))
		for _, item := range results {
			reached := false
			reachScore := 0.0
			if value, ok := reach[item.entityID]; ok {
				reached = true
				reachScore = value
			}
			cp := *item
			if reached {
				cp.relationships = append(append([]string{}, item.relationships...), "multi_hop")
			}
			cp.rankScore = item.rankScore + multiHopBlendWeight*reachScore
			details := jVal{kind: jObj, obj: append([]jPair(nil), item.details.obj...)}
			details.set("score_breakdown", jvObj(
				jvKey("similarity", jvFloat(math.Round(0.7*item.similarity*1e4)/1e4)),
				jvKey("appeal", jvFloat(math.Round(0.3*item.appeal*1e4)/1e4)),
				jvKey("multi_hop", jvFloat(math.Round(multiHopBlendWeight*reachScore*1e4)/1e4)),
			))
			if reached {
				via, err := mh.multiHopVia(sceneID, item.entityID)
				if err != nil {
					return nil, err
				}
				details.set("multi_hop_reach", jvFloat(reachScore))
				details.set("multi_hop_via", jvStr(via))
			}
			cp.details = details
			blended = append(blended, &cp)
		}
		results = blended
	}
	selected := diverseScenes(results, loads.performers, count)
	s.setTimingKeys("initialization", "content", "profiles", "performer_similarity", "multi_hop", "ranking", "details", "total")
	selectedIDs := make(map[string]bool, len(selected))
	for _, item := range selected {
		selectedIDs[item.entityID] = true
	}
	selectedContent, _, err := sceneContentVectors(s.db, s.featureVersion, selectedIDs)
	if err != nil {
		return nil, err
	}
	for _, item := range selected {
		vector := selectedContent[item.entityID]
		shared := make([]string, 0)
		for name := range targetVector {
			if _, ok := vector[name]; ok {
				shared = append(shared, name)
			}
		}
		sort.Slice(shared, func(i, j int) bool {
			return -targetVector[shared[i]]*vector[shared[i]] < -targetVector[shared[j]]*vector[shared[j]]
		})
		if len(shared) > 5 {
			shared = shared[:5]
		}
		tags := jvArr()
		for _, key := range shared {
			tagName, ok := loads.names[key]
			if !ok {
				tagName = strings.TrimPrefix(key, "tag:")
			}
			tags.arr = append(tags.arr, jvStr(tagName))
		}
		item.details.set("shared_tags", tags)
	}
	return selected, nil
}

// sceneContentOverlaps mirrors FeatureStore.scene_content_overlaps.
// sceneContentOverlaps mirrors SimilarityService._content_overlaps: the
// per-candidate dot products over the target's own features only.
func sceneContentOverlaps(db dbx, featureVersion, sceneID string) (map[string]float64, error) {
	result := make(map[string]float64)
	rows, err := db.Query(`WITH target AS (
  SELECT feature_id, value FROM scene_content_search
  WHERE feature_version=? AND scene_id=?
)
SELECT other.scene_id AS entity_id, sum(target.value * other.value) AS similarity
FROM target JOIN scene_content_search other USING(feature_id)
WHERE other.scene_id<>?
GROUP BY other.scene_id`, featureVersion, sceneID, sceneID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var entityID string
		var similarity float64
		if err := rows.Scan(&entityID, &similarity); err != nil {
			return nil, err
		}
		result[entityID] = similarity
	}
	return result, rows.Err()
}

// loadTagNames mirrors the source_tag read of SimilarityService.scenes.
func loadTagNames(db dbx) (map[string]string, error) {
	names := map[string]string{}
	rows, err := db.Query(`SELECT tag_id, name FROM source_tag`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var tagID, name string
		if err := rows.Scan(&tagID, &name); err != nil {
			return nil, err
		}
		names["tag:"+tagID] = name
	}
	return names, rows.Err()
}

// loadFavoritePerformers mirrors the favorite-performer read of
// SimilarityService.scenes.
func loadFavoritePerformers(db dbx) (map[string]bool, error) {
	favorites := map[string]bool{}
	rows, err := db.Query(`SELECT performer_id FROM source_performer WHERE favorite=1`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var performerID string
		if err := rows.Scan(&performerID); err != nil {
			return nil, err
		}
		favorites[performerID] = true
	}
	return favorites, rows.Err()
}

// loadBlockedScenes mirrors the blocked-tag preference read of
// SimilarityService.scenes: the blocked tags, then the scenes carrying them.
func loadBlockedScenes(db dbx) (map[string]bool, error) {
	blockedScenes := map[string]bool{}
	rows, err := db.Query(`SELECT tag_id FROM direct_tag_preference WHERE blocked=1`)
	if err != nil {
		return nil, err
	}
	var blockedTagIDs []string
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			rows.Close()
			return nil, err
		}
		blockedTagIDs = append(blockedTagIDs, tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(blockedTagIDs) == 0 {
		return blockedScenes, nil
	}
	sort.Strings(blockedTagIDs)
	placeholders := inClause(len(blockedTagIDs))
	args := make([]any, len(blockedTagIDs))
	for i, tagID := range blockedTagIDs {
		args[i] = tagID
	}
	rows, err = db.Query(`SELECT scene_id FROM scene_tag WHERE tag_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			return nil, err
		}
		blockedScenes[sceneID] = true
	}
	return blockedScenes, rows.Err()
}

// loadBlockedTerms mirrors the blocked-term preference read of
// SimilarityService.scenes.
func loadBlockedTerms(db dbx) ([]string, error) {
	rows, err := db.Query(`SELECT term FROM direct_term_preference WHERE blocked=1`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var blockedTerms []string
	for rows.Next() {
		var term string
		if err := rows.Scan(&term); err != nil {
			return nil, err
		}
		blockedTerms = append(blockedTerms, term)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.Strings(blockedTerms)
	return blockedTerms, nil
}

// scenePerformers mirrors SimilarityService._scene_performers.
func scenePerformers(db dbx) (map[string][]string, error) {
	rows, err := db.Query(`SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string][]string)
	for rows.Next() {
		var sceneID, performerID string
		if err := rows.Scan(&sceneID, &performerID); err != nil {
			return nil, err
		}
		found := false
		for _, existing := range result[sceneID] {
			if existing == performerID {
				found = true
				break
			}
		}
		if !found {
			result[sceneID] = append(result[sceneID], performerID)
		}
	}
	return result, rows.Err()
}

// performerGenders mirrors SimilarityService._performer_genders.
func performerGenders(db dbx) (map[string]string, error) {
	rows, err := db.Query(`SELECT performer_id, gender FROM source_performer`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]string)
	for rows.Next() {
		var performerID string
		var gender sql.NullString
		if err := rows.Scan(&performerID, &gender); err != nil {
			return nil, err
		}
		if gender.Valid {
			result[performerID] = gender.String
		} else {
			result[performerID] = ""
		}
	}
	return result, rows.Err()
}

// studios mirrors SimilarityService._studios.
func studios(db dbx) (map[string]string, error) {
	rows, err := db.Query(`SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]string)
	for rows.Next() {
		var sceneID, studioID string
		if err := rows.Scan(&sceneID, &studioID); err != nil {
			return nil, err
		}
		result[sceneID] = studioID
	}
	return result, rows.Err()
}

// sceneTagNames mirrors SimilarityService._scene_tags: tag names casefolded.
func sceneTagNames(db dbx, names map[string]bool) (map[string]map[string]bool, error) {
	sortedNames := make([]string, 0, len(names))
	for name := range names {
		sortedNames = append(sortedNames, name)
	}
	sort.Strings(sortedNames)
	placeholders := inClause(len(sortedNames))
	args := make([]any, len(sortedNames))
	for i, name := range sortedNames {
		args[i] = name
	}
	rows, err := db.Query(`SELECT st.scene_id, t.name FROM scene_tag st
JOIN source_tag t USING(tag_id) WHERE lower(t.name) IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]map[string]bool)
	for rows.Next() {
		var sceneID, name string
		if err := rows.Scan(&sceneID, &name); err != nil {
			return nil, err
		}
		set := result[sceneID]
		if set == nil {
			set = map[string]bool{}
			result[sceneID] = set
		}
		set[strings.ToLower(name)] = true
	}
	return result, rows.Err()
}

// diverseScenes mirrors SimilarityService._diverse_scenes.
func diverseScenes(ranked []*similarityResult, performers map[string][]string, count int64) []*similarityResult {
	selected := make([]*similarityResult, 0, count)
	remaining := append([]*similarityResult{}, ranked...)
	for len(remaining) > 0 && int64(len(selected)) < count {
		var previous map[string]bool
		if len(selected) > 0 {
			previous = make(map[string]bool)
			for _, p := range performers[selected[len(selected)-1].entityID] {
				previous[p] = true
			}
		}
		index := 0
		for i, item := range remaining {
			if len(previous) == 0 {
				index = i
				break
			}
			overlap := false
			for _, p := range performers[item.entityID] {
				if previous[p] {
					overlap = true
					break
				}
			}
			if !overlap {
				index = i
				break
			}
			index = 0 // default when every remaining candidate overlaps
		}
		selected = append(selected, remaining[index])
		remaining = append(remaining[:index], remaining[index+1:]...)
	}
	return selected
}

// performers mirrors SimilarityService.performers.
func (s *similarityService) performers(performerID string, count int64, gender string) ([]*similarityResult, error) {
	profiles, err := s.performerProfiles()
	if err != nil {
		return nil, err
	}
	blockWeights := make(map[string]float64, len(performerBlockWeights))
	for _, item := range performerBlockWeights {
		blockWeights[item.block] = item.weight
	}
	var matches []similarPerformerMatch
	if target, ok := profiles[performerID]; ok {
		for otherID, other := range profiles {
			if otherID == performerID {
				continue
			}
			similarity, blocks, weights := performerSimilarity(target, other, blockWeights)
			matches = append(matches, similarPerformerMatch{id: otherID, similarity: similarity, blocks: blocks, weights: weights})
		}
		sort.Slice(matches, func(i, j int) bool {
			if matches[i].similarity != matches[j].similarity {
				return matches[i].similarity > matches[j].similarity
			}
			return matches[i].id < matches[j].id
		})
		if len(matches) > 10_000 {
			matches = matches[:10_000]
		}
	}
	if len(matches) == 0 {
		var probe int
		err := s.db.QueryRow(`SELECT 1 FROM source_performer WHERE performer_id=?`, performerID).Scan(&probe)
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("unknown performer: %s", performerID)
		}
		if err != nil {
			return nil, err
		}
	}
	scenePerformers, err := scenePerformers(s.read)
	if err != nil {
		return nil, err
	}
	scenesByPerformer := make(map[string][]float64)
	for sceneID, performerIDs := range scenePerformers {
		appeal, ok := s.appeals[sceneID]
		if !ok {
			continue
		}
		value := (appeal + 1) / 2
		for _, candidateID := range performerIDs {
			scenesByPerformer[candidateID] = append(scenesByPerformer[candidateID], value)
		}
	}
	genders, err := performerGenders(s.read)
	if err != nil {
		return nil, err
	}
	var results []*similarityResult
	for _, match := range matches {
		if gender != "" && genders[match.id] != gender {
			continue
		}
		values := append([]float64{}, scenesByPerformer[match.id]...)
		sort.Slice(values, func(i, j int) bool { return values[i] > values[j] })
		if len(values) > 5 {
			values = values[:5]
		}
		appeal := 0.5
		if len(values) > 0 {
			appeal = sumFloats(values) / float64(len(values))
		}
		blocks := jvObj()
		for _, block := range sortedFloatKeysM(match.blocks) {
			blocks.set(block, jvFloat(match.blocks[block]))
		}
		weights := jvObj()
		for _, block := range sortedFloatKeysM(match.weights) {
			weights.set(block, jvFloat(match.weights[block]))
		}
		results = append(results, &similarityResult{
			entityID:      match.id,
			similarity:    match.similarity,
			appeal:        appeal,
			rankScore:     0.7*match.similarity + 0.3*appeal,
			relationships: []string{"similar_performer"},
			details: jvObj(
				jvKey("blocks", blocks),
				jvKey("block_weights", weights),
			),
		})
	}
	sort.Slice(results, func(i, j int) bool {
		if results[i].rankScore != results[j].rankScore {
			return results[i].rankScore > results[j].rankScore
		}
		return results[i].entityID < results[j].entityID
	})
	s.totalCount = len(results)
	if int64(len(results)) > count {
		results = results[:count]
	}
	return results, nil
}

type similarPerformerMatch struct {
	id         string
	similarity float64
	blocks     map[string]float64
	weights    map[string]float64
}

// performerProfiles mirrors FeatureStore.performer_profiles: profile blocks
// from entity_feature with family LIKE 'profile:%'.
func (s *similarityService) performerProfiles() (map[string]*performerProfile, error) {
	rows, err := s.db.Query(`SELECT ef.entity_id, fd.family, fd.name, ef.value, ef.confidence
FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
WHERE ef.feature_version=? AND ef.entity_type='performer' AND fd.family LIKE 'profile:%'
ORDER BY ef.entity_id, ef.feature_id`, s.featureVersion)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	profiles := make(map[string]*performerProfile)
	for rows.Next() {
		var entityID, family, name string
		var value, confidence float64
		if err := rows.Scan(&entityID, &family, &name, &value, &confidence); err != nil {
			return nil, err
		}
		profile := profiles[entityID]
		if profile == nil {
			profile = &performerProfile{
				id:     entityID,
				blocks: map[string]map[string]profileValue{},
				norms:  map[string]float64{},
				keys:   map[string]map[string]bool{},
			}
			profiles[entityID] = profile
		}
		block := strings.TrimPrefix(family, "profile:")
		values := profile.blocks[block]
		if values == nil {
			values = map[string]profileValue{}
			profile.blocks[block] = values
			profile.keys[block] = map[string]bool{}
		}
		values[name] = profileValue{value: value, confidence: confidence}
		profile.keys[block][name] = true
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, profile := range profiles {
		for block, values := range profile.blocks {
			if numericBlocks[block] {
				continue
			}
			// profiles.py: norm = sqrt(sum(value**2 ...)).
			squares := make([]float64, 0, len(values))
			for _, item := range values {
				squares = append(squares, item.value*item.value)
			}
			profile.norms[block] = math.Sqrt(sumFloats(squares))
		}
	}
	return profiles, nil
}

func intersectStringSets(a, b []string) map[string]bool {
	set := make(map[string]bool, len(a))
	result := make(map[string]bool)
	for _, value := range a {
		set[value] = true
	}
	for _, value := range b {
		if set[value] {
			result[value] = true
		}
	}
	return result
}

func anyIntersects(set map[string]bool, values []string) bool {
	for _, value := range values {
		if set[value] {
			return true
		}
	}
	return false
}

func containsAll(values []string, required map[string]bool) bool {
	present := make(map[string]bool, len(values))
	for _, value := range values {
		present[value] = true
	}
	for key := range required {
		if !present[key] {
			return false
		}
	}
	return true
}

func minFloat64(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func mathAbs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

func boolFloat(v bool) float64 {
	if v {
		return 1
	}
	return 0
}

func sqrtFloat(v float64) float64 { return math.Sqrt(v) }
