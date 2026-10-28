// Slice-4 frontend-parity ops: get_external_tag_choices, get_inspector_entity,
// and reset — the last ops the Python fallback
// served. Each mirrors plugin/backend.py's _api branch and the CuratorAPI
// method it calls, including the exact error messages and output key order.
package main

import (
	"database/sql"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func opGetExternalTagSearch(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_external_tag_search", func(settings jVal) (jVal, error) {
		args := payload.get("args")
		query := args.get("query")
		if !args.has("query") {
			query = jvStr("")
		}
		if query.kind != jStr || len(query.s) > 100 {
			return jvNull(), fmt.Errorf("query must be a string up to 100 bytes")
		}
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		var ready bool
		if err := db.QueryRow(`SELECT EXISTS(SELECT 1 FROM taxonomy_snapshot WHERE snapshot_id=
            (SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'))`).Scan(&ready); err != nil {
			return jvNull(), err
		}
		text := strings.TrimSpace(query.s)
		rows, err := db.Query(`SELECT t.tag_id, t.name FROM taxonomy_tag t
            WHERE t.snapshot_id=(SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id')
              AND ?<>'' AND (instr(lower(t.name), lower(?))>0 OR EXISTS(
                SELECT 1 FROM taxonomy_tag_alias a WHERE a.snapshot_id=t.snapshot_id AND a.tag_id=t.tag_id
                  AND instr(lower(a.alias), lower(?))>0))
            ORDER BY lower(t.name)=lower(?) DESC, t.name COLLATE NOCASE, t.tag_id LIMIT 8`, text, text, text, text)
		if err != nil {
			return jvNull(), err
		}
		defer rows.Close()
		items := jvArr()
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return jvNull(), err
			}
			items.arr = append(items.arr, jvObj(jvKey("id", jvStr(id)), jvKey("name", jvStr(name))))
		}
		return jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)), jvKey("ready", jvBool(ready)), jvKey("items", items)), rows.Err()
	})
}

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
	rows, err := db.Query(`SELECT t.tag_id, COALESCE(t.name, '') AS name, p.value AS direct_value,
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
		if row.name != "" {
			key := strings.ToLower(row.name)
			byName[key] = append(byName[key], row)
		}
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
	rows, err := db.Query(`SELECT t.tag_id, COALESCE(t.name, '') AS name, p.value AS direct_value,
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
		similar := jvArr()
		if !args.has("include_similar") || args.get("include_similar").truthy() {
			started := time.Now()
			similar, err = similarPerformers(db, featureVersion, entityID, 10)
			currentTrace().record("core", "inspector.similar_performers", started.UnixNano(), time.Since(started).Nanoseconds(), jvNull())
			if err != nil {
				return jvNull(), err
			}
		}
		affinity, confidence, hasAffinity, err := performerAffinity(db, modelID, featureVersion, entityID)
		if err != nil {
			return jvNull(), err
		}
		prior := performerPrior(profile.get("favorite").truthy(), number(profile.get("rating100")), profile.get("rating100").kind != jNull)
		var estimate modelPrior
		err = db.QueryRow(`SELECT value, confidence FROM model_performer_estimate
WHERE model_id=? AND performer_id=?`, modelID, entityID).Scan(&estimate.value, &estimate.confidence)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return jvNull(), err
		}
		preference := performerPreference(affinity, confidence, hasAffinity || err == nil, prior, estimate)
		result := jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("entity_type", jvStr(entityType)),
			jvKey("entity_id", jvStr(entityID)),
			jvKey("model_id", jvStr(modelID)),
			jvKey("profile", profile),
			jvKey("affinity", preference.get("affinity")),
			jvKey("confidence", preference.get("confidence")),
			jvKey("affinity_details", preference.get("affinity_details")),
			jvKey("similar", similar),
		)
		if args.get("include_evidence").truthy() {
			evidence, err := performerInspectorEvidence(db, modelID, featureVersion, entityID)
			if err != nil {
				return jvNull(), err
			}
			result.set("evidence", evidence)
		}
		return result, nil
	}
	return jvNull(), fmt.Errorf("unsupported inspector entity type: %s", entityType)
}

func performerInspectorEvidence(db dbx, modelID, featureVersion, performerID string) (jVal, error) {
	scenes := jvArr()
	rows, err := db.Query(`SELECT ef.entity_id, COALESCE(s.title, ''), json_extract(ms.components_json, '$.direct')
FROM entity_feature ef JOIN model_scene_score ms ON ms.scene_id=ef.entity_id AND ms.model_id=?
LEFT JOIN source_scene s ON s.scene_id=ef.entity_id
WHERE ef.feature_version=? AND ef.entity_type='scene' AND ef.feature_id=? AND ef.value>0
AND json_extract(ms.components_json, '$.direct.learning_evidence')>0
ORDER BY json_extract(ms.components_json, '$.direct.learning_evidence') DESC, ef.entity_id LIMIT 8`,
		modelID, featureVersion, featureID(featureVersion, "scene", "performer_identity", "performer:"+performerID))
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var id, title, directJSON string
		if err := rows.Scan(&id, &title, &directJSON); err != nil {
			rows.Close()
			return jvNull(), err
		}
		direct, err := parseJSON([]byte(directJSON))
		if err != nil {
			rows.Close()
			return jvNull(), err
		}
		scenes.arr = append(scenes.arr, jvObj(jvKey("scene_id", jvStr(id)), jvKey("title", jvStr(title)), jvKey("direct", direct)))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	matches := jvArr()
	rows, err = db.Query(`SELECT e.similar_performer_id, COALESCE(p.name, ''), e.similarity, e.affinity, e.confidence
FROM model_performer_edge e LEFT JOIN source_performer p ON p.performer_id=e.similar_performer_id
WHERE e.model_id=? AND e.performer_id=? ORDER BY e.rank`, modelID, performerID)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		var similarity, affinity, confidence float64
		if err := rows.Scan(&id, &name, &similarity, &affinity, &confidence); err != nil {
			return jvNull(), err
		}
		matches.arr = append(matches.arr, jvObj(jvKey("performer_id", jvStr(id)), jvKey("name", jvStr(name)),
			jvKey("similarity", jvFloat(similarity)), jvKey("affinity", jvFloat(affinity)), jvKey("confidence", jvFloat(confidence))))
	}
	return jvObj(jvKey("scenes", scenes), jvKey("performers", matches)), rows.Err()
}

func opGetPerformerAffinities(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_performer_affinities", func(settings jVal) (jVal, error) {
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
		var featureVersion string
		if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
			return jvNull(), err
		}
		priors, err := performerPriors(db)
		if err != nil {
			return jvNull(), err
		}
		// Start with performer definitions instead of probing every content affinity.
		estimates := map[string]modelPrior{}
		estimateRows, err := db.Query(`SELECT performer_id, value, confidence
FROM model_performer_estimate WHERE model_id=? ORDER BY performer_id`, modelID)
		if err != nil {
			return jvNull(), err
		}
		for estimateRows.Next() {
			var performerID string
			var estimate modelPrior
			if err := estimateRows.Scan(&performerID, &estimate.value, &estimate.confidence); err != nil {
				estimateRows.Close()
				return jvNull(), err
			}
			estimates[performerID] = estimate
		}
		err = estimateRows.Err()
		estimateRows.Close()
		if err != nil {
			return jvNull(), err
		}
		rows, err := db.Query(`SELECT fd.name, fa.affinity, fa.confidence
FROM feature_definition fd CROSS JOIN feature_affinity fa USING(feature_id)
WHERE fa.model_id=? AND fd.feature_version=? AND fd.family='performer_identity'
ORDER BY fd.name`, modelID, featureVersion)
		if err != nil {
			return jvNull(), err
		}
		defer rows.Close()
		affinities := jvObj()
		for _, performerID := range sortedStringKeys(priors) {
			estimate, hasEstimate := estimates[performerID]
			if prior := priors[performerID]; prior.confidence > 0 || hasEstimate {
				affinities.set(performerID, performerPreference(0, 0, hasEstimate, prior, estimate))
			}
		}
		for rows.Next() {
			var name string
			var affinity, confidence float64
			if err := rows.Scan(&name, &affinity, &confidence); err != nil {
				return jvNull(), err
			}
			performerID := strings.TrimPrefix(name, "performer:")
			if prior, exists := priors[performerID]; exists {
				affinities.set(performerID, performerPreference(affinity, confidence, true, prior, estimates[performerID]))
			}
		}
		return jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("model_id", jvStr(modelID)), jvKey("affinities", affinities)), rows.Err()
	})
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
	targets, err := loadPerformerProfiles(db, featureVersion, []string{performerID})
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
	if target := targets[performerID]; target != nil {
		profiles, err := loadProfilesComparedTo(db, featureVersion, target)
		if err != nil {
			return jvNull(), err
		}
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

func performerPreference(affinity, confidence float64, hasEvidence bool, prior, estimate modelPrior) jVal {
	value, certainty := jvNull(), jvNull()
	learned := affinity * confidence
	directConfidence := math.Max(confidence, prior.confidence)
	similarityConfidence := estimate.confidence * math.Max(0.05, 1-directConfidence)
	similarity := estimate.value * similarityConfidence
	if hasEvidence || prior.confidence > 0 || estimate.confidence > 0 {
		value = jvFloat(learned + prior.value + similarity)
		combinedConfidence := directConfidence + (1-directConfidence)*estimate.confidence
		if (learned+prior.value)*estimate.value < 0 {
			combinedConfidence = math.Max(directConfidence, similarityConfidence)
		}
		certainty = jvFloat(combinedConfidence)
	}
	return jvObj(jvKey("affinity", value), jvKey("confidence", certainty),
		jvKey("affinity_details", jvObj(jvKey("learned", jvFloat(learned)), jvKey("prior", jvFloat(prior.value)),
			jvKey("similarity", jvFloat(similarity)), jvKey("similarity_confidence", jvFloat(similarityConfidence)),
			// The learned part's own confidence, so a client can recover its
			// evidence (confidence = 1 - exp(-support / 3)) for estimates.
			jvKey("learned_confidence", jvFloat(confidence)))))
}

// The deterministic identity key avoids scanning feature definitions for a name.
func performerAffinity(db dbx, modelID, featureVersion, performerID string) (float64, float64, bool, error) {
	var affinity, confidence float64
	err := db.QueryRow(`SELECT fa.affinity, fa.confidence
FROM feature_affinity fa WHERE fa.model_id = ? AND fa.feature_id = ?`,
		modelID, featureID(featureVersion, "scene", "performer_identity", "performer:"+performerID)).Scan(&affinity, &confidence)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, 0, false, nil
	}
	if err != nil {
		return 0, 0, false, err
	}
	return affinity, confidence, true, nil
}

// Tag questions constants mirror curator/api.py's TAG_QUESTION_* values;
// directTagSupport mirrors the model build's blend weight for a direct answer.
const (
	tagQuestionPoolSize = 300
	tagQuestionMinReach = 2
	tagQuestionExamples = 6
	directTagSupport    = 8.0
	// tagQuestionGuess and tagQuestionMinStrength mirror TAG_QUESTION_GUESS
	// and TAG_QUESTION_MIN_STRENGTH.
	tagQuestionGuess       = 0.15
	tagQuestionMinStrength = 0.05
)

func opGetTagQuestions(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_tag_questions",
		func(settings jVal) (jVal, error) { return tagQuestionsBody(pluginDir, payload, settings) })
}

// tagQuestionsBody mirrors CuratorAPI.tag_questions: unanswered content tags
// ranked by leverage (the share of the blended affinity a direct answer would
// control) times reach (the rank-discounted share of the For You pool
// carrying the tag).
func tagQuestionsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	limit := argsInt(payload.get("args"), "limit", 5)
	excluded, err := excludeTagIDs(payload.get("args").get("exclude_tag_ids"))
	if err != nil {
		return jvNull(), err
	}
	if limit < 1 || limit > 10 {
		return jvNull(), fmt.Errorf("limit must be between 1 and 10")
	}
	taste, err := getTasteProfileBody(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	built, err := recommend(db, modelID, "for_you", tagQuestionPoolSize,
		config.get("config").get("diversity_enabled").truthy(), 0, nil)
	if err != nil {
		return jvNull(), err
	}
	pool := make([]string, 0, len(built.items))
	for _, item := range built.items {
		pool = append(pool, item.sceneID)
	}
	weights := make(map[string]float64, len(pool))
	totalWeight := 0.0
	for index, sceneID := range pool {
		weights[sceneID] = 1 / math.Log2(float64(index+2))
		totalWeight += weights[sceneID]
	}
	sceneTags := make(map[string][]string, len(pool))
	rows, err := db.Query(`
SELECT scene_id, tag_id FROM scene_tag
WHERE provenance='scene' AND scene_id IN (SELECT value FROM json_each(?))`, jsonIDs(pool))
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var sceneID, tagID string
		if err := rows.Scan(&sceneID, &tagID); err != nil {
			rows.Close()
			return jvNull(), err
		}
		sceneTags[sceneID] = append(sceneTags[sceneID], tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	reachWeight := make(map[string]float64)
	members := make(map[string][]string)
	for _, sceneID := range pool {
		tags := sceneTags[sceneID]
		sort.Strings(tags)
		for _, tagID := range tags {
			reachWeight[tagID] += weights[sceneID]
			members[tagID] = append(members[tagID], sceneID)
		}
	}
	var totalScenes int64
	if err := db.QueryRow(`SELECT count(*) FROM source_scene`).Scan(&totalScenes); err != nil {
		return jvNull(), err
	}
	type question struct {
		item     jVal
		tagID    string
		name     string
		inferred float64
		reach    float64
		leverage float64
		value    float64
	}
	var candidates []question
	for _, item := range taste.get("items").arr {
		tagID := item.get("tag_id").asString()
		sceneCount := pythonInt(item.get("scene_count"))
		if item.get("prompt").kind == jNull ||
			excluded[tagID] ||
			len(members[tagID]) < tagQuestionMinReach ||
			// ponytail: library-wide prevalence is the existing cheap generic-tag signal.
			(sceneCount >= 5 && float64(sceneCount) >= 0.8*float64(totalScenes)) {
			continue
		}
		reach := reachWeight[tagID] / totalWeight
		leverage := directTagSupport / (pythonFloatValue(item.get("support")) + directTagSupport)
		inferred := pythonFloatValue(item.get("inferred_value"))
		strength := math.Max(mathAbs(inferred), tagQuestionMinStrength)
		candidates = append(candidates, question{
			item: item, tagID: tagID, name: item.get("name").asString(),
			inferred: inferred,
			reach:    reach, leverage: leverage, value: leverage * reach * strength,
		})
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if a.value != b.value {
			return a.value > b.value
		}
		if mathAbs(a.inferred) != mathAbs(b.inferred) {
			return mathAbs(a.inferred) < mathAbs(b.inferred)
		}
		aname, bname := strings.ToLower(a.name), strings.ToLower(b.name)
		if aname != bname {
			return aname < bname
		}
		return a.tagID < b.tagID
	})
	out := jvArr()
	for i := 0; i < int(limit) && i < len(candidates); i++ {
		c := candidates[i]
		examples := jvArr()
		for k, sceneID := range members[c.tagID] {
			if k >= tagQuestionExamples {
				break
			}
			examples.arr = append(examples.arr, jvStr(sceneID))
		}
		out.arr = append(out.arr, jvObj(
			jvKey("tag_id", jvStr(c.tagID)),
			jvKey("name", c.item.get("name")),
			jvKey("inferred_value", c.item.get("inferred_value")),
			jvKey("confidence", c.item.get("confidence")),
			jvKey("support", c.item.get("support")),
			jvKey("inherited_value", c.item.get("inherited_value")),
			jvKey("scene_count", c.item.get("scene_count")),
			jvKey("reach", jvFloat(c.reach)),
			jvKey("leverage", jvFloat(c.leverage)),
			jvKey("value", jvFloat(c.value)),
			jvKey("guess", tagQuestionGuessOf(c.inferred)),
			jvKey("examples", examples),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("pool_size", jvInt(int64(len(pool)))),
		jvKey("items", out),
	), nil
}

// answerReviewMinConfidence mirrors ANSWER_REVIEW_MIN_CONFIDENCE.
const answerReviewMinConfidence = 0.35

func opGetAnswerReview(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_answer_review",
		func(settings jVal) (jVal, error) { return answerReviewBody(pluginDir, payload, settings) })
}

// answerReviewBody mirrors CuratorAPI.answer_review: direct tag answers ranked
// by |answer - learned| x learned confidence, where learned is the
// viewing-only affinity the model keeps beside each answer.
func answerReviewBody(pluginDir string, payload, settings jVal) (jVal, error) {
	limit := argsInt(payload.get("args"), "limit", 5)
	if limit < 1 || limit > 10 {
		return jvNull(), fmt.Errorf("limit must be between 1 and 10")
	}
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
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return jvNull(), err
	}
	configVersion, err := effectiveTagRoleConfigVersion(db)
	if err != nil {
		return jvNull(), err
	}
	type review struct {
		tagID, name                 string
		answer, learned, confidence float64
		answeredAtMs, sceneCount    int64
		disagreement                float64
	}
	rows, err := db.Query(`
SELECT p.tag_id, coalesce(nullif(t.name, ''), p.tag_id), p.value, p.occurred_at_ms, a.metadata_json,
       (SELECT count(DISTINCT st.scene_id) FROM scene_tag st
        WHERE st.tag_id=p.tag_id AND st.provenance='scene') AS scene_count
FROM direct_tag_preference p
JOIN source_tag t ON t.tag_id=p.tag_id
JOIN tag_role r ON r.tag_id=p.tag_id AND r.config_version=? AND r.role='content'
JOIN feature_definition d
  ON d.feature_version=? AND d.family='content' AND d.name='tag:' || p.tag_id
JOIN feature_affinity a ON a.feature_id=d.feature_id AND a.model_id=?
WHERE p.blocked=0`, configVersion, featureVersion, modelID)
	if err != nil {
		return jvNull(), err
	}
	var candidates []review
	for rows.Next() {
		var item review
		var metadataJSON string
		if err := rows.Scan(&item.tagID, &item.name, &item.answer, &item.answeredAtMs, &metadataJSON, &item.sceneCount); err != nil {
			rows.Close()
			return jvNull(), err
		}
		metadata := parseJSONOr(metadataJSON)
		learned, learnedConfidence := metadata.get("learned_affinity"), metadata.get("learned_confidence")
		if learned.kind != jNum || learnedConfidence.kind != jNum {
			continue
		}
		item.learned, item.confidence = numberValue(learned), numberValue(learnedConfidence)
		if item.confidence < answerReviewMinConfidence {
			continue
		}
		item.disagreement = mathAbs(item.answer-item.learned) * item.confidence
		candidates = append(candidates, item)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if a.disagreement != b.disagreement {
			return a.disagreement > b.disagreement
		}
		if a.sceneCount != b.sceneCount {
			return a.sceneCount > b.sceneCount
		}
		aname, bname := strings.ToLower(a.name), strings.ToLower(b.name)
		if aname != bname {
			return aname < bname
		}
		return a.tagID < b.tagID
	})
	out := jvArr()
	for i := 0; i < int(limit) && i < len(candidates); i++ {
		c := candidates[i]
		examples := jvArr()
		exampleRows, err := db.Query(`
SELECT st.scene_id FROM scene_tag st
JOIN model_scene_score s ON s.scene_id=st.scene_id AND s.model_id=?
WHERE st.tag_id=? AND st.provenance='scene'
ORDER BY s.current_fit DESC, st.scene_id LIMIT ?`, modelID, c.tagID, tagQuestionExamples)
		if err != nil {
			return jvNull(), err
		}
		for exampleRows.Next() {
			var sceneID string
			if err := exampleRows.Scan(&sceneID); err != nil {
				exampleRows.Close()
				return jvNull(), err
			}
			examples.arr = append(examples.arr, jvStr(sceneID))
		}
		exampleRows.Close()
		if err := exampleRows.Err(); err != nil {
			return jvNull(), err
		}
		out.arr = append(out.arr, jvObj(
			jvKey("tag_id", jvStr(c.tagID)),
			jvKey("name", jvStr(c.name)),
			jvKey("answer", jvFloat(c.answer)),
			jvKey("answered_at_ms", jvInt(c.answeredAtMs)),
			jvKey("learned_value", jvFloat(c.learned)),
			jvKey("learned_confidence", jvFloat(c.confidence)),
			jvKey("scene_count", jvInt(c.sceneCount)),
			jvKey("disagreement", jvFloat(c.disagreement)),
			jvKey("examples", examples),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("candidate_count", jvInt(int64(len(candidates)))),
		jvKey("items", out),
	), nil
}

// tagQuestionGuessOf names a confident current guess, or null.
func tagQuestionGuessOf(inferred float64) jVal {
	if mathAbs(inferred) < tagQuestionGuess {
		return jvNull()
	}
	if inferred > 0 {
		return jvStr("like")
	}
	return jvStr("dislike")
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

func opGetSceneReasonCandidates(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_scene_reason_candidates",
		func(settings jVal) (jVal, error) { return sceneReasonCandidatesBody(pluginDir, payload, settings) })
}

// sceneReasonCandidatesBody mirrors CuratorAPI.scene_reason_candidates: the
// highest-rated played scenes ("hits") or the lowest-rated scenes ("misses"),
// without answered or excluded scenes.
func sceneReasonCandidatesBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	excluded := args.get("exclude_scene_ids")
	if excluded.truthy() && excluded.kind != jArr {
		return jvNull(), fmt.Errorf("exclude_scene_ids must be a list")
	}
	mode := argsString(args, "mode", "")
	limit := argsInt(args, "limit", 20)
	if mode != "hits" && mode != "misses" {
		return jvNull(), fmt.Errorf("mode must be hits or misses")
	}
	if limit < 1 || limit > 50 {
		return jvNull(), fmt.Errorf("limit must be between 1 and 50")
	}
	exclude := map[string]bool{}
	if excluded.kind == jArr {
		for _, item := range excluded.arr {
			exclude[item.asString()] = true
		}
	}
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
	played, order := "", "ASC"
	if mode == "hits" {
		played, order = "AND s.scene_id IN (SELECT scene_id FROM source_play)", "DESC"
	}
	rows, err := db.Query(`
SELECT s.scene_id, s.appeal, s.confidence FROM model_scene_score s
WHERE s.model_id=? `+played+`
  AND s.scene_id NOT IN (SELECT scene_id FROM scene_reason_answer)
  AND s.scene_id NOT IN (SELECT value FROM json_each(?))
ORDER BY s.appeal `+order+`, s.scene_id
LIMIT ?`, modelID, jsonIDs(sortedStringKeys(exclude)), limit)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var sceneID string
		var appeal, confidence float64
		if err := rows.Scan(&sceneID, &appeal, &confidence); err != nil {
			return jvNull(), err
		}
		items.arr = append(items.arr, jvObj(
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("appeal", jvFloat(appeal)),
			jvKey("confidence", jvFloat(confidence)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("mode", jvStr(mode)),
		jvKey("items", items),
	), nil
}

func opGetStudioAffinities(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_studio_affinities", func(settings jVal) (jVal, error) {
		return studioAffinitiesBody(pluginDir, payload, settings)
	})
}

// studioAffinitiesBody mirrors CuratorAPI.studio_affinities: learned affinity
// times its confidence plus the Stash-favourite prior, with the learned
// confidence for client-side estimates.
func studioAffinitiesBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return jvNull(), err
	}
	type learnedStudio struct{ affinity, confidence float64 }
	learned := map[string]learnedStudio{}
	rows, err := db.Query(`SELECT fd.name, fa.affinity, fa.confidence
FROM feature_definition fd CROSS JOIN feature_affinity fa USING(feature_id)
WHERE fa.model_id=? AND fd.feature_version=? AND fd.family='studio'
ORDER BY fd.name`, modelID, featureVersion)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var name string
		var item learnedStudio
		if err := rows.Scan(&name, &item.affinity, &item.confidence); err != nil {
			rows.Close()
			return jvNull(), err
		}
		learned[strings.TrimPrefix(name, "studio:")] = item
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	studios, err := db.Query(`SELECT studio_id, favorite FROM source_studio ORDER BY studio_id`)
	if err != nil {
		return jvNull(), err
	}
	defer studios.Close()
	affinities := jvObj()
	for studios.Next() {
		var studioID string
		var favorite bool
		if err := studios.Scan(&studioID, &favorite); err != nil {
			return jvNull(), err
		}
		item, ok := learned[studioID]
		if !ok && !favorite {
			continue
		}
		prior, priorConfidence := 0.0, 0.0
		if favorite {
			prior, priorConfidence = 0.04, 0.70
		}
		affinities.set(studioID, jvObj(
			jvKey("affinity", jvFloat(item.affinity*item.confidence+prior)),
			jvKey("confidence", jvFloat(math.Max(item.confidence, priorConfidence))),
			jvKey("affinity_details", jvObj(
				jvKey("learned", jvFloat(item.affinity*item.confidence)),
				jvKey("prior", jvFloat(prior)),
				jvKey("learned_confidence", jvFloat(item.confidence)),
			)),
		))
	}
	if err := studios.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(modelID)),
		jvKey("affinities", affinities),
	), nil
}
