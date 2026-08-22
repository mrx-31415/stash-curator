// Slice-4 frontend-parity ops: get_external_tag_choices, get_inspector_entity,
// get_tag_sentiment_follow_up, and reset — the last ops the Python fallback
// served. Each mirrors plugin/backend.py's _api branch and the CuratorAPI
// method it calls, including the exact error messages and output key order.
package main

import (
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// ── get_external_tag_choices ───────────────────────────────────────────────

// opGetExternalTagChoices mirrors backend.py's get_external_tag_choices
// branch: match requested StashDB tag ids/names against local source tags by
// stable stash_id, a unique name match, or the active taxonomy alias, for the
// expand-filter tag dropdown.
func opGetExternalTagChoices(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_external_tag_choices",
		func(settings jVal) (jVal, error) { return externalTagChoicesBody(pluginDir, payload, settings) })
}

func externalTagChoicesBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	tags := args.get("tags")
	if tags.kind != jArr {
		return jvNull(), fmt.Errorf("tags must be a list")
	}
	if len(tags.arr) > 100 {
		return jvNull(), fmt.Errorf("at most 100 external tags are supported")
	}
	type requestedTag struct {
		id   string
		name string
	}
	requested := make([]requestedTag, 0, len(tags.arr))
	for _, item := range tags.arr {
		if item.kind != jObj {
			continue
		}
		id := item.get("id")
		name := item.get("name")
		if id.truthy() || name.truthy() {
			requested = append(requested, requestedTag{
				id:   pythonStrOrEmpty(id),
				name: strings.TrimSpace(pythonStrOrEmpty(name)),
			})
		}
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	configVersion, err := effectiveTagRoleConfigVersion(db)
	if err != nil {
		return jvNull(), err
	}
	type choiceRow struct {
		tagID         string
		name          string
		directValue   sql.NullFloat64
		directBlocked sql.NullInt64
		stashID       sql.NullString
	}
	rows, err := db.Query(`SELECT t.tag_id, t.name, p.value AS direct_value,
       p.blocked AS direct_blocked, ids.stash_id
FROM source_tag t
JOIN tag_role r
  ON r.tag_id=t.tag_id AND r.config_version=?
LEFT JOIN direct_tag_preference p ON p.tag_id=t.tag_id
LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
  AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
ORDER BY t.tag_id`, configVersion, stashdbEndpoint)
	if err != nil {
		return jvNull(), err
	}
	var rowsList []choiceRow
	for rows.Next() {
		var row choiceRow
		if err := rows.Scan(&row.tagID, &row.name, &row.directValue, &row.directBlocked, &row.stashID); err != nil {
			rows.Close()
			return jvNull(), err
		}
		rowsList = append(rowsList, row)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	byExternal := make(map[string]choiceRow)
	byName := make(map[string][]choiceRow)
	for _, row := range rowsList {
		if row.stashID.Valid && row.stashID.String != "" {
			byExternal[row.stashID.String] = row
		}
		key := strings.ToLower(row.name) // Python str(row["name"] or "")
		byName[key] = append(byName[key], row)
	}
	var snapshotID string
	var hasSnapshot bool
	err = db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`).Scan(&snapshotID)
	if err == nil {
		hasSnapshot = true
	} else if !errors.Is(err, sql.ErrNoRows) {
		return jvNull(), err
	}
	out := jvArr()
	seen := make(map[string]bool)
	for _, req := range requested {
		matched, ok := byExternal[req.id]
		if !ok {
			matches := byName[strings.ToLower(req.name)]
			if len(matches) == 1 {
				matched = matches[0]
				ok = true
			}
		}
		if !ok && hasSnapshot && req.name != "" {
			// Try taxonomy alias → local tag mapping.
			var localID string
			err := db.QueryRow(`
SELECT ttm.local_tag_id
FROM taxonomy_tag tt
JOIN tag_taxonomy_match ttm
  ON ttm.snapshot_id=tt.snapshot_id AND ttm.external_tag_id=tt.tag_id
WHERE tt.snapshot_id=? AND lower(tt.name)=?
UNION
SELECT ttm.local_tag_id
FROM taxonomy_tag_alias tta
JOIN taxonomy_tag tt USING(snapshot_id, tag_id)
JOIN tag_taxonomy_match ttm
  ON ttm.snapshot_id=tt.snapshot_id AND ttm.external_tag_id=tt.tag_id
WHERE tta.snapshot_id=? AND lower(tta.alias)=?`,
				snapshotID, strings.ToLower(req.name), snapshotID, strings.ToLower(req.name)).Scan(&localID)
			if err == nil {
				for _, candidate := range rowsList {
					if candidate.tagID == localID {
						matched, ok = candidate, true
						break
					}
				}
			} else if !errors.Is(err, sql.ErrNoRows) {
				return jvNull(), err
			}
		}
		if !ok || seen[matched.tagID] {
			continue
		}
		seen[matched.tagID] = true
		directValue := jvNull()
		if matched.directValue.Valid {
			directValue = jvFloat(matched.directValue.Float64)
		}
		name := matched.name
		if name == "" {
			name = matched.tagID
		}
		out.arr = append(out.arr, jvObj(
			jvKey("tag_id", jvStr(matched.tagID)),
			jvKey("name", jvStr(name)),
			jvKey("direct_value", directValue),
			jvKey("direct_blocked", jvBool(matched.directBlocked.Valid && matched.directBlocked.Int64 != 0)),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("items", out),
	), nil
}

// ── get_scene_tag_choices ──────────────────────────────────────────────────

// opGetSceneTagChoices mirrors backend.py's get_scene_tag_choices branch:
// the scene's own classified tags (tag_role for the current config version)
// with their direct preferences, sorted by name — the local-card counterpart
// of get_external_tag_choices. A tag can appear once per provenance, so rows
// are grouped by tag_id.
func opGetSceneTagChoices(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_scene_tag_choices",
		func(settings jVal) (jVal, error) { return sceneTagChoicesBody(pluginDir, payload, settings) })
}

func sceneTagChoicesBody(pluginDir string, payload, settings jVal) (jVal, error) {
	sceneID := pythonStrOrEmpty(payload.get("args").get("scene_id"))
	if sceneID == "" {
		return jvNull(), fmt.Errorf("scene_id is required")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	configVersion, err := effectiveTagRoleConfigVersion(db)
	if err != nil {
		return jvNull(), err
	}
	rows, err := db.Query(`SELECT t.tag_id, t.name, p.value AS direct_value,
       p.blocked AS direct_blocked
FROM scene_tag st
JOIN source_tag t ON t.tag_id=st.tag_id
JOIN tag_role r ON r.tag_id=t.tag_id AND r.config_version=?
LEFT JOIN direct_tag_preference p ON p.tag_id=t.tag_id
WHERE st.scene_id=?
GROUP BY t.tag_id
ORDER BY t.name COLLATE NOCASE, t.tag_id`, configVersion, sceneID)
	if err != nil {
		return jvNull(), err
	}
	out := jvArr()
	for rows.Next() {
		var tagID string
		var name string
		var directValue sql.NullFloat64
		var directBlocked sql.NullInt64
		if err := rows.Scan(&tagID, &name, &directValue, &directBlocked); err != nil {
			rows.Close()
			return jvNull(), err
		}
		if name == "" {
			name = tagID
		}
		value := jvNull()
		if directValue.Valid {
			value = jvFloat(directValue.Float64)
		}
		out.arr = append(out.arr, jvObj(
			jvKey("tag_id", jvStr(tagID)),
			jvKey("name", jvStr(name)),
			jvKey("direct_value", value),
			jvKey("direct_blocked", jvBool(directBlocked.Valid && directBlocked.Int64 != 0)),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("items", out),
	), nil
}

// ── get_scene_description_tokens ───────────────────────────────────────────

// opGetSceneDescriptionTokens mirrors backend.py's get_scene_description_tokens
// branch: the scene's desc:<term> content features from the current feature
// build, with direct term preferences — the data source for the term-rating
// view. Terms are truthful to the built model (library-relative TF-IDF), never
// re-tokenized from the scene text.
func opGetSceneDescriptionTokens(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_scene_description_tokens",
		func(settings jVal) (jVal, error) { return sceneDescriptionTokensBody(pluginDir, payload, settings) })
}

func sceneDescriptionTokensBody(pluginDir string, payload, settings jVal) (jVal, error) {
	sceneID := pythonStrOrEmpty(payload.get("args").get("scene_id"))
	if sceneID == "" {
		return jvNull(), fmt.Errorf("scene_id is required")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	direct := make(map[string]termPref)
	rows, err := db.Query(`SELECT term, value, blocked FROM direct_term_preference`)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var term string
		var value float64
		var blocked int64
		if err := rows.Scan(&term, &value, &blocked); err != nil {
			rows.Close()
			return jvNull(), err
		}
		direct[term] = termPref{value: value, blocked: blocked != 0}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	featureVersion, err := currentFeatureVersion(db)
	if err != nil {
		return jvNull(), err
	}
	out := jvArr()
	if featureVersion != "" {
		rows, err := db.Query(`SELECT fd.name, fd.metadata_json
FROM entity_feature ef
JOIN feature_definition fd ON fd.feature_id=ef.feature_id
WHERE ef.feature_version=? AND ef.entity_type='scene' AND ef.entity_id=?
  AND fd.family='content' AND fd.name LIKE 'desc:%'
ORDER BY fd.name`, featureVersion, sceneID)
		if err != nil {
			return jvNull(), err
		}
		for rows.Next() {
			var name string
			var metadataJSON string
			if err := rows.Scan(&name, &metadataJSON); err != nil {
				rows.Close()
				return jvNull(), err
			}
			term := strings.TrimPrefix(name, "desc:")
			metadata := parseJSONOr(metadataJSON)
			documentFrequency := int64(pythonFloatOr(metadata.get("document_frequency"), 0))
			value := jvNull()
			blocked := false
			if pref, ok := direct[term]; ok {
				value = jvFloat(pref.value)
				blocked = pref.blocked
			}
			out.arr = append(out.arr, jvObj(
				jvKey("term", jvStr(term)),
				jvKey("document_frequency", jvInt(documentFrequency)),
				jvKey("direct_value", value),
				jvKey("direct_blocked", jvBool(blocked)),
			))
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("items", out),
	), nil
}

// termPref is a direct_term_preference row (value + blocked flag).
type termPref struct {
	value   float64
	blocked bool
}

// ── get_inspector_entity ───────────────────────────────────────────────────

// inspectorSceneScore carries every ModelSceneScore field asdict() exposes,
// in dataclass field order.
type inspectorSceneScore struct {
	modelID          string
	sceneID          string
	generalAppeal    float64
	directAppeal     float64
	directConfidence float64
	appeal           float64
	currentFit       float64
	confidence       float64
	metadataConf     float64
	recovery         float64
	components       jVal
	neighbors        jVal
	eligibility      jVal
}

func (s *inspectorSceneScore) json() jVal {
	return jvObj(
		jvKey("model_id", jvStr(s.modelID)),
		jvKey("scene_id", jvStr(s.sceneID)),
		jvKey("general_appeal", jvFloat(s.generalAppeal)),
		jvKey("direct_appeal", jvFloat(s.directAppeal)),
		jvKey("direct_confidence", jvFloat(s.directConfidence)),
		jvKey("appeal", jvFloat(s.appeal)),
		jvKey("current_fit", jvFloat(s.currentFit)),
		jvKey("confidence", jvFloat(s.confidence)),
		jvKey("metadata_confidence", jvFloat(s.metadataConf)),
		jvKey("recovery", jvFloat(s.recovery)),
		jvKey("components", s.components),
		jvKey("neighbors", s.neighbors),
		jvKey("eligibility", s.eligibility),
	)
}

// inspectorSceneScoreFor mirrors RecommendationModelStore.scores({scene_id})
// for one scene: the score row plus neighbors ordered by (scene_id, rank).
func inspectorSceneScoreFor(db dbx, modelID, sceneID string) (*inspectorSceneScore, error) {
	score := &inspectorSceneScore{}
	var componentsJSON, eligibilityJSON string
	err := db.QueryRow(`SELECT model_id, scene_id, general_appeal, direct_appeal,
    direct_confidence, appeal, current_fit, confidence, metadata_confidence,
    recovery, components_json, eligibility_json
FROM model_scene_score WHERE model_id=? AND scene_id=?`,
		modelID, sceneID).Scan(&score.modelID, &score.sceneID, &score.generalAppeal,
		&score.directAppeal, &score.directConfidence, &score.appeal, &score.currentFit,
		&score.confidence, &score.metadataConf, &score.recovery, &componentsJSON, &eligibilityJSON)
	if err != nil {
		return nil, err
	}
	if components, err := parseJSON([]byte(componentsJSON)); err == nil {
		score.components = components
	} else {
		score.components = jvNull()
	}
	if eligibility, err := parseJSON([]byte(eligibilityJSON)); err == nil {
		score.eligibility = eligibility
	} else {
		score.eligibility = jvNull()
	}
	neighborRows, err := db.Query(`SELECT neighbor_scene_id, similarity, weight, outcome
FROM model_scene_neighbor WHERE model_id=? AND scene_id=? ORDER BY scene_id, rank`, modelID, sceneID)
	if err != nil {
		return nil, err
	}
	defer neighborRows.Close()
	neighbors := jvArr()
	for neighborRows.Next() {
		var neighborID string
		var similarity, weight, outcome float64
		if err := neighborRows.Scan(&neighborID, &similarity, &weight, &outcome); err != nil {
			return nil, err
		}
		neighbors.arr = append(neighbors.arr, jvObj(
			jvKey("scene_id", jvStr(neighborID)),
			jvKey("similarity", jvFloat(similarity)),
			jvKey("weight", jvFloat(weight)),
			jvKey("outcome", jvFloat(outcome)),
		))
	}
	if err := neighborRows.Err(); err != nil {
		return nil, err
	}
	score.neighbors = neighbors
	return score, nil
}

// opGetInspectorEntity mirrors backend.py's get_inspector_entity branch: the
// entity inspector panel (scene score + explanation, or performer profile +
// nearest performers).
func opGetInspectorEntity(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_inspector_entity",
		func(settings jVal) (jVal, error) { return inspectorEntityBody(pluginDir, payload, settings) })
}

func inspectorEntityBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	entityType := pythonStrOrEmpty(args.get("entity_type"))
	entityID := pythonStrOrEmpty(args.get("entity_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model")
	}
	switch entityType {
	case "scene":
		score, err := inspectorSceneScoreFor(db, modelID, entityID)
		if err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return jvNull(), fmt.Errorf("unknown scene: %s", entityID)
			}
			return jvNull(), err
		}
		explanation, err := renderExplanationForScene(db, pluginDir, modelID, entityID)
		if err != nil {
			return jvNull(), err
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("entity_type", jvStr(entityType)),
			jvKey("entity_id", jvStr(entityID)),
			jvKey("model_id", jvStr(modelID)),
			jvKey("score", score.json()),
			jvKey("explanation", explanation),
		), nil
	case "performer":
		profile, err := performerRow(db, entityID)
		if err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return jvNull(), fmt.Errorf("unknown performer: %s", entityID)
			}
			return jvNull(), err
		}
		var featureVersion string
		if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
			return jvNull(), err
		}
		similar, err := similarPerformers(db, featureVersion, entityID, 10)
		if err != nil {
			return jvNull(), err
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("entity_type", jvStr(entityType)),
			jvKey("entity_id", jvStr(entityID)),
			jvKey("model_id", jvStr(modelID)),
			jvKey("profile", profile),
			jvKey("similar", similar),
		), nil
	}
	return jvNull(), fmt.Errorf("unsupported inspector entity type: %s", entityType)
}

// performerRow mirrors Python's `SELECT * FROM source_performer` dict(row):
// every column in table order with sqlite type conversion.
func performerRow(db dbx, performerID string) (jVal, error) {
	rows, err := db.Query(`SELECT * FROM source_performer WHERE performer_id=?`, performerID)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return jvNull(), err
	}
	if !rows.Next() {
		return jvNull(), sql.ErrNoRows
	}
	values := make([]any, len(columns))
	scanned := make([]any, len(columns))
	for i := range columns {
		scanned[i] = &values[i]
	}
	if err := rows.Scan(scanned...); err != nil {
		return jvNull(), err
	}
	out := jvObj()
	for i, name := range columns {
		out.set(name, dbValueToJSON(values[i]))
	}
	return out, rows.Err()
}

// dbValueToJSON converts a driver value to the Python sqlite type mapping:
// NULL -> null, INTEGER/REAL -> number, TEXT/BLOB -> string.
func dbValueToJSON(v any) jVal {
	switch t := v.(type) {
	case nil:
		return jvNull()
	case int64:
		return jvInt(t)
	case float64:
		return jvFloat(t)
	case string:
		return jvStr(t)
	case []byte:
		return jvStr(string(t))
	}
	return jvNull()
}

// similarPerformers mirrors FeatureStore.similar_performers: rank every other
// profile by performer_similarity, ties by performer id, and take `count`.
func similarPerformers(db dbx, featureVersion, performerID string, count int) (jVal, error) {
	profiles, err := performerProfilesAll(db, featureVersion)
	if err != nil {
		return jvNull(), err
	}
	type match struct {
		performerID string
		similarity  float64
		blocks      jVal
	}
	weights := performerBlockWeightsMap()
	var matches []match
	if target := profiles[performerID]; target != nil {
		for otherID, profile := range profiles {
			if otherID == performerID {
				continue
			}
			similarity, similarities, _ := performerSimilarity(target, profile, weights)
			_, _, ordered, _ := blockSimilaritiesAll(target, profile, weights)
			blocks := jvObj()
			for _, block := range ordered {
				blocks.set(block, jvFloat(similarities[block]))
			}
			matches = append(matches, match{performerID: otherID, similarity: similarity, blocks: blocks})
		}
	}
	sort.Slice(matches, func(i, j int) bool {
		if matches[i].similarity != matches[j].similarity {
			return matches[i].similarity > matches[j].similarity
		}
		return matches[i].performerID < matches[j].performerID
	})
	if len(matches) > count {
		matches = matches[:count]
	}
	out := jvArr()
	for _, m := range matches {
		out.arr = append(out.arr, jvObj(
			jvKey("performer_id", jvStr(m.performerID)),
			jvKey("similarity", jvFloat(m.similarity)),
			jvKey("blocks", m.blocks),
		))
	}
	return out, nil
}

// ── get_tag_sentiment_follow_up ────────────────────────────────────────────

// opGetTagSentimentFollowUp mirrors backend.py's get_tag_sentiment_follow_up
// branch: the scene's tags that the taste profile has no direct preference
// for, ranked by inference strength, limited to 3.
func opGetTagSentimentFollowUp(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_tag_sentiment_follow_up",
		func(settings jVal) (jVal, error) { return tagSentimentFollowUpBody(pluginDir, payload, settings) })
}

func tagSentimentFollowUpBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	sceneID := pythonStrOrEmpty(args.get("scene_id"))
	limit := minInt64(3, argsInt(args, "limit", 3))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	if sceneID == "" || limit < 1 || limit > 3 {
		return jvNull(), fmt.Errorf("scene_id and a limit from 1 to 3 are required")
	}
	sceneTags := make(map[string]bool)
	tagRows, err := db.Query(`
SELECT tag_id FROM scene_tag
WHERE scene_id=? AND provenance='scene'`, sceneID)
	if err != nil {
		return jvNull(), err
	}
	for tagRows.Next() {
		var tagID string
		if err := tagRows.Scan(&tagID); err != nil {
			tagRows.Close()
			return jvNull(), err
		}
		sceneTags[tagID] = true
	}
	tagRows.Close()
	if err := tagRows.Err(); err != nil {
		return jvNull(), err
	}
	if len(sceneTags) == 0 {
		var probe int
		err := db.QueryRow(`SELECT 1 FROM source_scene WHERE scene_id=?`, sceneID).Scan(&probe)
		if errors.Is(err, sql.ErrNoRows) {
			return jvNull(), fmt.Errorf("unknown scene: %s", sceneID)
		}
		if err != nil {
			return jvNull(), err
		}
	}
	var totalScenes int64
	if err := db.QueryRow(`SELECT count(*) FROM source_scene`).Scan(&totalScenes); err != nil {
		return jvNull(), err
	}
	taste, err := getTasteProfileBody(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	candidates := jvArr()
	for _, item := range taste.get("items").arr {
		tagID := item.get("tag_id")
		if tagID.kind != jStr || !sceneTags[tagID.s] {
			continue
		}
		if item.get("direct_value").kind != jNull {
			continue
		}
		sceneCount := pythonInt(item.get("scene_count"))
		// ponytail: library-wide prevalence is the existing cheap generic-tag signal.
		if sceneCount >= 5 && float64(sceneCount) >= 0.8*float64(totalScenes) {
			continue
		}
		candidates.arr = append(candidates.arr, item)
	}
	sort.SliceStable(candidates.arr, func(i, j int) bool {
		a, b := candidates.arr[i], candidates.arr[j]
		aInferred := pythonFloatValue(a.get("inferred_value"))
		bInferred := pythonFloatValue(b.get("inferred_value"))
		aKey := sentimentKey(aInferred, pythonFloatValue(a.get("confidence")))
		bKey := sentimentKey(bInferred, pythonFloatValue(b.get("confidence")))
		if aKey != bKey {
			return aKey < bKey
		}
		if mathAbs(aInferred) != mathAbs(bInferred) {
			return mathAbs(aInferred) > mathAbs(bInferred)
		}
		aname, bname := strings.ToLower(a.get("name").asString()), strings.ToLower(b.get("name").asString())
		if aname != bname {
			return aname < bname
		}
		return a.get("tag_id").asString() < b.get("tag_id").asString()
	})
	out := jvArr()
	for i := int64(0); i < limit && i < int64(len(candidates.arr)); i++ {
		out.arr = append(out.arr, candidates.arr[i])
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("items", out),
	), nil
}

// sentimentKey mirrors the tag_sentiment_follow_up sort's first component:
// 0 for a positive inference above 0.05, 1 for weak evidence, else 2.
func sentimentKey(inferred, confidence float64) int64 {
	if inferred > 0.05 {
		return 0
	}
	if confidence < 0.35 || mathAbs(inferred) < 0.15 {
		return 1
	}
	return 2
}

func pythonFloatValue(v jVal) float64 {
	f, err := pythonFloat(v)
	if err != nil {
		return 0
	}
	return f
}

// ── reset ──────────────────────────────────────────────────────────────────

// opReset mirrors backend.py's reset branch: destructive sidecar reset that
// removes the database, its WAL/SHM sidecars, and every recognized artifact,
// then recreates a fresh migrated sidecar. Requires confirmation == "RESET"
// and no running curator job.
func opReset(pluginDir string, payload jVal) (jVal, error) {
	args := payload.get("args")
	if pythonStrOrEmpty(args.get("confirmation")) != "RESET" {
		return jvNull(), fmt.Errorf("reset requires confirmation")
	}
	settings := pluginSettings(payload)
	database := databasePath(pluginDir, payload, settings)
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	var probe int
	err = db.QueryRow(`SELECT 1 FROM curator_job WHERE state='running' LIMIT 1`).Scan(&probe)
	db.Close()
	if err == nil {
		return jvNull(), fmt.Errorf("cannot reset Curator while a job is running")
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return jvNull(), err
	}
	for _, path := range append([]string{database, database + "-wal", database + "-shm"}, recognizedArtifacts(database)...) {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return jvNull(), err
		}
	}
	reopened, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	reopened.Close()
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("reset", jvBool(true)),
	), nil
}

// recognizedArtifacts mirrors artifacts.recognized_artifacts: the final and
// temporary feature/model artifact files in the <stem>-derived directory
// beside the core database, excluding symlinks.
func recognizedArtifacts(corePath string) []string {
	directory := cacheDirectory(corePath)
	info, err := os.Lstat(directory)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return nil
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil
	}
	var result []string
	for _, entry := range entries {
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			continue
		}
		if finalArtifactName.MatchString(entry.Name()) || tempArtifactName.MatchString(entry.Name()) {
			result = append(result, filepath.Join(directory, entry.Name()))
		}
	}
	return result
}
