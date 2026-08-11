// External similarity — ports of ExpandService.similar and
// ExpandService.targeted_similar (the get_external_similar body): retrieve a
// candidate pool from StashDB, score it against the local model, merge it
// into the sidecar, then rank it with the local similarity contract.
package main

import (
	"database/sql"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
)

// performerProfilesAll mirrors FeatureStore.performer_profiles without an id
// restriction (the targeted performer path loads every profile).
func performerProfilesAll(db dbx, featureVersion string) (map[string]*performerProfile, error) {
	rows, err := db.Query(`SELECT ef.entity_id, fd.family, fd.name, ef.value, ef.confidence
FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
WHERE ef.feature_version=? AND ef.entity_type='performer' AND fd.family LIKE 'profile:%'
ORDER BY ef.entity_id, ef.feature_id`, featureVersion)
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
		finalizeProfileNorms(profile)
	}
	return profiles, nil
}

// expandSimilar mirrors ExpandService.similar: rank the external_entity pool
// (optionally restricted to candidate_ids) against a local scene or
// performer, with the same similarity/appeal blend and why strings.
func (s *expandService) similar(entityType, entityID string, count int64, candidateIDs map[string]bool,
	includeTags, excludeTags, performerNames, studioNames []string, favoriteOnly bool,
	minimumSimilarity float64) (jVal, error) {
	if minimumSimilarity < 0 || minimumSimilarity > 1 {
		return jvNull(), errors.New("minimum_similarity must be between 0 and 1")
	}
	shortlisted := map[string]bool{}
	shortRows, err := s.db.Query(`SELECT external_id FROM external_shortlist WHERE entity_type=?`, entityType)
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
	weights := map[string]float64{}
	for _, item := range performerBlockWeights {
		weights[item.block] = item.weight
	}
	items := make([]jVal, 0)
	if entityType == "scene" {
		includeGroups, err := equivalentTagNames(s.db, includeTags)
		if err != nil {
			return jvNull(), err
		}
		excludeGroups, err := equivalentTagNames(s.db, excludeTags)
		if err != nil {
			return jvNull(), err
		}
		targetTags, err := s.externalContent(entityID)
		if err != nil {
			return jvNull(), err
		}
		featureVersion, err := currentFeatureVersion(s.db)
		if err != nil {
			return jvNull(), err
		}
		targetContent := map[string]float64{}
		var targetContentOrder []string
		if featureVersion != "" {
			vectors, order, err := sceneContentVectors(s.db, featureVersion, map[string]bool{entityID: true})
			if err != nil {
				return jvNull(), err
			}
			targetContent = vectors[entityID]
			targetContentOrder = order[entityID]
		}
		var contentSpace *contentSpace
		if featureVersion != "" {
			contentSpace, err = s.externalContentSpace(featureVersion)
			if err != nil {
				return jvNull(), err
			}
		}
		targetPerformers := make([]string, 0)
		perfRows, err := s.db.Query(`SELECT performer_id FROM scene_performer WHERE scene_id=?`, entityID)
		if err != nil {
			return jvNull(), err
		}
		for perfRows.Next() {
			var performerID string
			if err := perfRows.Scan(&performerID); err != nil {
				return jvNull(), err
			}
			targetPerformers = append(targetPerformers, performerID)
		}
		perfRows.Close()
		if err := perfRows.Err(); err != nil {
			return jvNull(), err
		}
		targetStudioID := ""
		var studioID sql.NullString
		err = s.db.QueryRow(`SELECT studio_id FROM source_scene WHERE scene_id=?`, entityID).Scan(&studioID)
		if err == nil && studioID.Valid && studioID.String != "" {
			targetStudioID = studioID.String
		} else if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return jvNull(), err
		}
		targetStructure := math.Min(1.0, float64(maxInt(0, len(targetPerformers)-1))/3.0)
		targetIsCompilation := false
		var probe int
		err = s.db.QueryRow(`
SELECT 1 FROM scene_tag st JOIN source_tag t USING(tag_id)
WHERE st.scene_id=? AND lower(t.name)='compilation' LIMIT 1`, entityID).Scan(&probe)
		if err == nil {
			targetIsCompilation = true
		} else if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return jvNull(), err
		}
		var profiles map[string]*performerProfile
		if featureVersion != "" {
			profiles, err = performerProfilesAll(s.db, featureVersion)
			if err != nil {
				return jvNull(), err
			}
		}
		targets := make([]*performerProfile, 0, len(targetPerformers))
		for _, performerID := range targetPerformers {
			if profile, ok := profiles[performerID]; ok {
				targets = append(targets, profile)
			}
		}
		entityRows, err := s.db.Query(`SELECT * FROM external_entity WHERE entity_type='scene'`)
		if err != nil {
			return jvNull(), err
		}
		columns, err := entityRows.Columns()
		if err != nil {
			return jvNull(), err
		}
		for entityRows.Next() {
			values := make([]any, len(columns))
			scanned := make([]any, len(columns))
			for i := range columns {
				scanned[i] = &values[i]
			}
			if err := entityRows.Scan(scanned...); err != nil {
				return jvNull(), err
			}
			row := make(map[string]any, len(columns))
			for i, name := range columns {
				row[name] = values[i]
			}
			externalID := asDBString(row["external_id"])
			if candidateIDs != nil && !candidateIDs[externalID] {
				continue
			}
			payload, err := parseJSON([]byte(asDBString(row["payload_json"])))
			if err != nil {
				return jvNull(), err
			}
			if !targetIsCompilation {
				isCompilation := false
				for _, tag := range payload.get("tags").arr {
					if strings.ToLower(pythonStrOrEmpty(tag.get("name"))) == "compilation" {
						isCompilation = true
						break
					}
				}
				if isCompilation {
					continue
				}
			}
			if !expandSceneMatches(payload, includeTags, excludeTags, performerNames, studioNames,
				"", "", includeGroups, excludeGroups, nil) {
				continue
			}
			if favoriteOnly {
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
			// tags: {id:X: name, name:X: name} for the shared-why text.
			tags := jvObj()
			for _, tag := range payload.get("tags").arr {
				name := tag.get("name").asString()
				tags.set("id:"+tag.get("id").asString(), jvStr(name))
				tags.set("name:"+strings.ToLower(pythonStrOrEmpty(tag.get("name"))), jvStr(name))
			}
			shared := map[string]bool{}
			for _, pair := range targetTags.obj {
				if tags.has(pair.key) {
					shared[pair.key] = true
				}
			}
			var candidateContent jVal = jvObj()
			if contentSpace != nil {
				candidateContent = externalCandidateContent(payload.get("tags"), contentSpace)
			}
			content := 0.0
			contentValues := make([]float64, 0, len(targetContentOrder))
			for _, name := range targetContentOrder {
				value := targetContent[name]
				contentValues = append(contentValues, value*pythonFloatOr(candidateContent.get(name), 0))
			}
			content = sumFloats(contentValues)
			targetPerformerSet := map[string]bool{}
			for _, id := range targetPerformers {
				targetPerformerSet[id] = true
			}
			exactPerformer := false
			for _, item := range payload.get("performers").arr {
				if targetPerformerSet[item.get("performer").get("curator_local").get("id").asString()] {
					exactPerformer = true
					break
				}
			}
			performer := 0.0
			if exactPerformer {
				performer = 1.0
			} else {
				best := 0.0
				for _, item := range payload.get("performers").arr {
					recorded := payload.get("production_date")
					if !recorded.truthy() {
						recorded = payload.get("release_date")
					}
					candidate := expandProfile(item.get("performer"), recorded)
					for _, target := range targets {
						value, _ := profileMatch(candidate, target, weights)
						if value > best {
							best = value
						}
					}
				}
				performer = best
			}
			performer *= 0.35 + 0.65*content
			structure := 1 - math.Abs(targetStructure-
				math.Min(1.0, float64(maxInt(0, len(payload.get("performers").arr)-1))/3.0))
			candidateStudio := payload.get("studio")
			if candidateStudio.kind != jObj {
				candidateStudio = jvObj()
			}
			sameStudio := targetStudioID != "" &&
				candidateStudio.get("curator_local").get("id").asString() == targetStudioID
			similarity := 0.5*content + 0.3*performer + 0.1*structure + 0.1*boolFloat(sameStudio)
			if similarity < minimumSimilarity {
				continue
			}
			rowScore := asDBFloat(row["score"])
			appeal := math.Max(0.0, math.Min(1.0, (rowScore+1)/2))
			itemScore := 0.7*similarity + 0.3*appeal
			why := whyForShared(tags, shared, exactPerformer, performer, sameStudio)
			itemPayload := cloneObj(payload)
			itemPayload.set("why", why)
			sources, err := parseJSON([]byte(asDBString(row["sources_json"])))
			if err != nil {
				sources = jvArr()
			}
			items = append(items, jvObj(
				jvKey("id", jvStr(externalID)),
				jvKey("entity_type", jvStr("scene")),
				jvKey("similarity", jvFloat(similarity)),
				jvKey("appeal", jvFloat(appeal)),
				jvKey("score", jvFloat(itemScore)),
				jvKey("sources", sources),
				jvKey("shortlisted", jvBool(shortlisted[externalID])),
				jvKey("payload", itemPayload),
			))
		}
		entityRows.Close()
		if err := entityRows.Err(); err != nil {
			return jvNull(), err
		}
	} else if entityType == "performer" {
		featureVersion, err := currentFeatureVersion(s.db)
		if err != nil {
			return jvNull(), err
		}
		var target *performerProfile
		if featureVersion != "" {
			profiles, err := performerProfilesAll(s.db, featureVersion)
			if err != nil {
				return jvNull(), err
			}
			target = profiles[entityID]
		}
		if target == nil {
			return jvNull(), fmt.Errorf("unknown performer: %s", entityID)
		}
		var birthdate sql.NullString
		err = s.db.QueryRow(`SELECT birthdate FROM source_performer WHERE performer_id=?`, entityID).Scan(&birthdate)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return jvNull(), err
		}
		var birthdateVal jVal = jvNull()
		if birthdate.Valid {
			birthdateVal = jvStr(birthdate.String)
		}
		target = expandWithAge(target, birthdateVal)
		entityRows, err := s.db.Query(`SELECT * FROM external_entity WHERE entity_type='performer'`)
		if err != nil {
			return jvNull(), err
		}
		columns, err := entityRows.Columns()
		if err != nil {
			return jvNull(), err
		}
		for entityRows.Next() {
			values := make([]any, len(columns))
			scanned := make([]any, len(columns))
			for i := range columns {
				scanned[i] = &values[i]
			}
			if err := entityRows.Scan(scanned...); err != nil {
				return jvNull(), err
			}
			row := make(map[string]any, len(columns))
			for i, name := range columns {
				row[name] = values[i]
			}
			externalID := asDBString(row["external_id"])
			if candidateIDs != nil && !candidateIDs[externalID] {
				continue
			}
			payload, err := parseJSON([]byte(asDBString(row["payload_json"])))
			if err != nil {
				return jvNull(), err
			}
			candidate := expandProfile(payload, jvNull())
			similarity, coverage, sims, used := profileMatchFull(candidate, target, weights)
			if similarity < 0.25 || coverage < 0.25 {
				continue
			}
			appeal := 0.0
			sceneCount := payload.get("scene_count")
			if sceneCount.kind != jNull {
				appeal = math.Min(1.0, math.Log1p(float64(pythonInt(sceneCount)))/math.Log1p(500))
			} else {
				rowScore := asDBFloat(row["score"])
				appeal = math.Max(0.0, math.Min(1.0, (rowScore+1)/2))
			}
			blocks := make([]string, 0, len(sims))
			for block := range sims {
				blocks = append(blocks, block)
			}
			sort.SliceStable(blocks, func(i, j int) bool {
				return sims[blocks[i]]*used[blocks[i]] > sims[blocks[j]]*used[blocks[j]]
			})
			if len(blocks) > 3 {
				blocks = blocks[:3]
			}
			attributes := make([]string, 0, len(blocks))
			for _, block := range blocks {
				attributes = append(attributes, strings.ReplaceAll(block, "augmentation", "breast type"))
			}
			why := jvArr(jvStr("Closest on " + strings.Join(attributes, ", ")))
			if conflicts := profileConflicts(candidate, target); len(conflicts) > 0 {
				why.arr = append(why.arr, jvStr("Differs in "+strings.Join(conflicts, ", ")))
			}
			itemPayload := cloneObj(payload)
			itemPayload.set("why", why)
			sources, err := parseJSON([]byte(asDBString(row["sources_json"])))
			if err != nil {
				sources = jvArr()
			}
			itemScore := 0.7*similarity + 0.3*appeal
			items = append(items, jvObj(
				jvKey("id", jvStr(externalID)),
				jvKey("entity_type", jvStr("performer")),
				jvKey("similarity", jvFloat(similarity)),
				jvKey("appeal", jvFloat(appeal)),
				jvKey("score", jvFloat(itemScore)),
				jvKey("sources", sources),
				jvKey("shortlisted", jvBool(shortlisted[externalID])),
				jvKey("payload", itemPayload),
			))
		}
		entityRows.Close()
		if err := entityRows.Err(); err != nil {
			return jvNull(), err
		}
	} else {
		return jvNull(), errors.New("invalid external similarity entity type")
	}
	sort.SliceStable(items, func(i, j int) bool {
		leftScore := pythonFloatOr(items[i].get("score"), 0)
		rightScore := pythonFloatOr(items[j].get("score"), 0)
		if leftScore != rightScore {
			return leftScore > rightScore
		}
		return items[i].get("id").asString() < items[j].get("id").asString()
	})
	if int64(len(items)) > count {
		items = items[:count]
	}
	return jvObj(
		jvKey("ready", jvBool(len(items) > 0)),
		jvKey("items", jvArr(items...)),
	), nil
}

// whyForShared mirrors the shared-tag why string in ExpandService.similar.
func whyForShared(tags jVal, shared map[string]bool, exactPerformer bool, performer float64, sameStudio bool) jVal {
	if len(shared) > 0 {
		names := make([]string, 0, len(shared))
		for key := range shared {
			names = append(names, key)
		}
		sort.Strings(names)
		joined := make([]string, 0, len(names))
		for _, key := range names {
			joined = append(joined, tags.get(key).asString())
		}
		return jvArr(jvStr("Shares " + strings.Join(joined, ", ")))
	}
	if exactPerformer {
		return jvArr(jvStr("Same performer"))
	}
	if performer > 0 {
		return jvArr(jvStr("Similar performer profile"))
	}
	if sameStudio {
		return jvArr(jvStr("Same studio"))
	}
	return jvArr(jvStr("Similar cast structure"))
}

// profileMatchFull mirrors ExpandService._profile_match, also returning the
// per-block similarities and weights for the why attributes.
//go:noinline
func profileMatchFull(left, right *performerProfile, weights map[string]float64) (float64, float64, map[string]float64, map[string]float64) {
	total, sims, used := performerSimilarity(left, right, weights)
	relevant := 0.0
	for key, value := range weights {
		if key != "content" {
			relevant += value
		}
	}
	coverage := 0.0
	if relevant != 0 {
		weightValues := make([]float64, 0, len(used))
		for _, value := range used {
			weightValues = append(weightValues, value)
		}
		coverage = math.Min(1.0, sumFloats(weightValues)/relevant)
	}
	return total * math.Sqrt(coverage), coverage, sims, used
}

// expandTargetedSimilar mirrors ExpandService.targeted_similar: retrieve a
// StashDB pool biased toward the target, score/merge it, and rank it.
func expandTargetedSimilar(db dbx, clientURL, apiKey string, links jVal, entityType, entityID,
	gender string, count int64, includeTags, excludeTags, performerNames, studioNames []string,
	favoriteOnly, includeOwned, hidePhash bool, minimumSimilarity float64) (jVal, error) {
	service := newExpandService(db)
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
	trace := currentTrace()
	started := time.Now()
	// timings keys are inserted in Python's assignment order; the performer
	// path never sets "scoring".
	timings := jvObj()
	candidateIDs := map[string]bool{}
	if entityType == "scene" {
		content, err := service.externalContent(entityID)
		if err != nil {
			return jvNull(), err
		}
		performers := make([]string, 0)
		perfRows, err := db.Query(`SELECT performer_id FROM scene_performer WHERE scene_id=?`, entityID)
		if err != nil {
			return jvNull(), err
		}
		for perfRows.Next() {
			var performerID string
			if err := perfRows.Scan(&performerID); err != nil {
				return jvNull(), err
			}
			if v := links.get("performers").get(performerID); v.truthy() {
				performers = append(performers, v.asString())
			}
		}
		perfRows.Close()
		if err := perfRows.Err(); err != nil {
			return jvNull(), err
		}
		studios := make([]string, 0)
		studioRows, err := db.Query(`SELECT studio_id FROM source_scene WHERE scene_id=?`, entityID)
		if err != nil {
			return jvNull(), err
		}
		for studioRows.Next() {
			var studioID sql.NullString
			if err := studioRows.Scan(&studioID); err != nil {
				return jvNull(), err
			}
			if studioID.Valid && studioID.String != "" {
				if v := links.get("studios").get(studioID.String); v.truthy() {
					studios = append(studios, v.asString())
				}
			}
		}
		studioRows.Close()
		if err := studioRows.Err(); err != nil {
			return jvNull(), err
		}
		tagIDs, err := service.probeTagIDs(content)
		if err != nil {
			return jvNull(), err
		}
		tightTagIDs := tagIDs
		if len(tightTagIDs) > 3 {
			tightTagIDs = tightTagIDs[:3]
		}
		probes := []fetchPageSpec{
			{source: "tags", values: tagIDs, limit: 250, modifier: "INCLUDES", sort: "DATE"},
			{source: "tags", values: tagIDs, limit: 250, modifier: "INCLUDES", sort: "POPULARITY"},
			{source: "performers", values: performers, limit: 150, modifier: "INCLUDES", sort: "DATE"},
			{source: "performers", values: performers, limit: 150, modifier: "INCLUDES", sort: "POPULARITY"},
			{source: "studios", values: studios, limit: 150, modifier: "INCLUDES", sort: "DATE"},
			{source: "studios", values: studios, limit: 150, modifier: "INCLUDES", sort: "POPULARITY"},
		}
		if len(tightTagIDs) >= 2 {
			probes = append(probes,
				fetchPageSpec{source: "tags", values: tightTagIDs, limit: 100, modifier: "INCLUDES_ALL", sort: "DATE"},
				fetchPageSpec{source: "tags", values: tightTagIDs, limit: 100, modifier: "INCLUDES_ALL", sort: "POPULARITY"},
			)
		}
		filtered := make([]fetchPageSpec, 0, len(probes))
		for _, probe := range probes {
			if len(probe.values) > 0 {
				filtered = append(filtered, probe)
			}
		}
		rows, sources, err := fetchProbes(clientURL, apiKey, filtered)
		if err != nil {
			return jvNull(), err
		}
		retrievalMs := elapsedMs(started)
		timings.set("retrieval", jvInt(retrievalMs))
		recordDurationMs(trace, "python", "external_similar.retrieval", retrievalMs)
		stageStart := time.Now()
		candidates := make([]jVal, 0)
		for _, value := range rows.list() {
			candidate := annotateLocalMatch(value, links)
			matchType := candidate.get("curator_local_match").get("type").asString()
			if !(includeOwned || matchType != "stashdb_id") {
				continue
			}
			if hidePhash && matchType == "phash" {
				continue
			}
			if !matchesGender(candidate, gender) {
				continue
			}
			if includeOwned && candidate.get("curator_local_match").get("local_scene_id").asString() == entityID {
				continue
			}
			candidates = append(candidates, candidate)
		}
		for _, candidate := range candidates {
			candidateIDs[candidate.get("id").asString()] = true
		}
		scenes, _, err := service.score(candidates, sources, modelID, featureVersion, links, jvStr(entityID))
		if err != nil {
			return jvNull(), err
		}
		if err := service.mergeExternal("scene", scenes); err != nil {
			return jvNull(), err
		}
		scoringMs := elapsedMs(stageStart)
		timings.set("scoring", jvInt(scoringMs))
		recordDurationMs(trace, "python", "external_similar.scoring", scoringMs)
	} else if entityType == "performer" {
		var targetRow struct {
			gender    sql.NullString
			ethnicity sql.NullString
			birthdate sql.NullString
		}
		err := db.QueryRow(`SELECT gender, ethnicity, birthdate FROM source_performer WHERE performer_id=?`,
			entityID).Scan(&targetRow.gender, &targetRow.ethnicity, &targetRow.birthdate)
		if err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return jvNull(), fmt.Errorf("unknown performer: %s", entityID)
			}
			return jvNull(), err
		}
		selectedGender := gender
		if selectedGender == "" {
			selectedGender = targetRow.gender.String
		}
		ethnicity := strings.ToUpper(strings.ReplaceAll(targetRow.ethnicity.String, " ", "_"))
		switch ethnicity {
		case "CAUCASIAN", "BLACK", "ASIAN", "INDIAN", "LATIN", "MIDDLE_EASTERN", "MIXED", "OTHER":
		default:
			ethnicity = ""
		}
		var target *performerProfile
		if featureVersion != "" {
			profiles, err := performerProfilesAll(db, featureVersion)
			if err != nil {
				return jvNull(), err
			}
			target = profiles[entityID]
		}
		if target != nil {
			var birthdateVal jVal = jvNull()
			if targetRow.birthdate.Valid {
				birthdateVal = jvStr(targetRow.birthdate.String)
			}
			target = expandWithAge(target, birthdateVal)
		}
		performedWith := ""
		if v := links.get("performers").get(entityID); v.truthy() {
			performedWith = v.asString()
		}
		candidates, err := fetchPerformerPool(clientURL, apiKey, target, selectedGender, ethnicity, performedWith)
		if err != nil {
			return jvNull(), err
		}
		excluded := map[string]bool{}
		if includeOwned {
			if v := links.get("performers").get(entityID); v.truthy() {
				excluded[v.asString()] = true
			}
		} else {
			for _, pair := range links.get("performers").obj {
				excluded[pair.val.asString()] = true
			}
		}
		candidateIDs = map[string]bool{}
		merged := make([]scoredScene, 0, len(candidates))
		for _, payload := range candidates {
			id := payload.get("id").asString()
			if excluded[id] {
				continue
			}
			candidateIDs[id] = true
			merged = append(merged, scoredScene{
				id:      id,
				payload: payload,
				score:   0.0,
				sources: []string{"similar"},
			})
		}
		if err := service.mergeExternal("performer", merged); err != nil {
			return jvNull(), err
		}
		retrievalMs := elapsedMs(started)
		timings.set("retrieval", jvInt(retrievalMs))
		recordDurationMs(trace, "python", "external_similar.retrieval", retrievalMs)
	} else {
		return jvNull(), errors.New("invalid external similarity entity type")
	}
	stageStart := time.Now()
	result, err := service.similar(entityType, entityID, count*2, candidateIDs,
		includeTags, excludeTags, performerNames, studioNames, favoriteOnly, minimumSimilarity)
	if err != nil {
		return jvNull(), err
	}
	rawItems := result.get("items").arr
	blockedGroups, err := service.blockedTagNameGroups()
	if err != nil {
		return jvNull(), err
	}
	filtered := make([]jVal, 0, len(rawItems))
	for _, item := range rawItems {
		if gender != "" && !payloadMatchesGender(item.get("payload"), entityType, gender) {
			continue
		}
		filtered = append(filtered, item)
	}
	if entityType == "scene" {
		sceneFiltered := make([]jVal, 0, len(filtered))
		for _, item := range filtered {
			if expandSceneMatches(item.get("payload"), nil, nil, nil, nil, "", "",
				nil, nil, blockedGroups) {
				sceneFiltered = append(sceneFiltered, item)
			}
		}
		filtered = sceneFiltered
	}
	if int64(len(filtered)) > count {
		filtered = filtered[:count]
	}
	if entityType == "performer" {
		localByExternal := map[string]string{}
		for _, pair := range links.get("performers").obj {
			localByExternal[pair.val.asString()] = pair.key
		}
		for i := range filtered {
			localID, ok := localByExternal[filtered[i].get("id").asString()]
			if !ok {
				continue
			}
			var favorite int64
			err := db.QueryRow(`SELECT favorite FROM source_performer WHERE performer_id=?`, localID).Scan(&favorite)
			if err != nil {
				return jvNull(), err
			}
			payload := filtered[i].get("payload")
			payload.set("curator_local", jvObj(
				jvKey("id", jvStr(localID)),
				jvKey("favorite", jvBool(favorite != 0)),
			))
			filtered[i].set("payload", payload)
		}
	} else if entityType == "scene" {
		localByExternal := map[string]string{}
		sceneIDs := links.get("scene_ids")
		if len(sceneIDs.obj) == 0 {
			for _, pair := range links.get("scenes").obj {
				localByExternal[pair.val.asString()] = pair.key
			}
		} else {
			for _, pair := range sceneIDs.obj {
				localByExternal[pair.key] = pair.val.asString()
			}
		}
		for i := range filtered {
			localID, ok := localByExternal[filtered[i].get("id").asString()]
			if !ok {
				continue
			}
			payload := filtered[i].get("payload")
			payload.set("curator_local", jvObj(jvKey("id", jvStr(localID))))
			filtered[i].set("payload", payload)
		}
	}
	result.set("items", jvArr(filtered...))
	result.set("total", jvInt(int64(len(filtered))))
	result.set("ready", jvBool(len(filtered) > 0))
	rankingMs := elapsedMs(stageStart)
	timings.set("ranking", jvInt(rankingMs))
	recordDurationMs(trace, "python", "external_similar.filter_and_rank", rankingMs)
	timings.set("total", jvInt(elapsedMs(started)))
	result.set("timings_ms", timings)
	return result, nil
}

func elapsedMs(started time.Time) int64 {
	return pyRound(time.Since(started).Seconds() * 1000)
}
