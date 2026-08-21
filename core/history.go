// get_recommendation_history / get_feedback_history / get_shortlist /
// get_taste_profile — ports of the corresponding CuratorAPI methods
// (curator/api.py) plus the FeatureConfig fingerprint used by the taste
// profile's tag-role config_version.
package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

func opGetRecommendationHistory(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_recommendation_history",
		func(settings jVal) (jVal, error) { return getRecommendationHistoryBody(pluginDir, payload, settings) })
}

func getRecommendationHistoryBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	page := argsInt(args, "page", 1)
	pageSize := argsInt(args, "page_size", 20)
	var lane jVal = jvNull()
	if args.get("lane").truthy() {
		lane = jvStr(args.get("lane").asString())
	}
	if page < 1 || pageSize < 1 || pageSize > 100 {
		return jvNull(), fmt.Errorf("invalid recommendation history page")
	}
	if lane.kind == jStr && !slateLanes[lane.s] {
		return jvNull(), fmt.Errorf("unknown recommendation lane")
	}
	where := ""
	parameters := []any{}
	if lane.kind == jStr {
		where = "WHERE h.lane=?"
		parameters = append(parameters, lane.s)
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	var total int64
	if err := db.QueryRow(`SELECT count(*) FROM recommendation_history h `+where, parameters...).Scan(&total); err != nil {
		return jvNull(), err
	}
	query := `SELECT h.history_id, h.scene_id, h.impression_id, h.lane, h.shown_at_ms,
           i.reason_snapshot_json,
           EXISTS(
             SELECT 1 FROM model_scene_score score
             WHERE score.model_id=? AND score.scene_id=h.scene_id
           ) AS current_model
    FROM recommendation_history h
    LEFT JOIN impression_item i
      ON i.impression_id=h.impression_id AND i.scene_id=h.scene_id
    ` + where + `
    ORDER BY h.shown_at_ms DESC, h.history_id DESC LIMIT ? OFFSET ?`
	queryArgs := make([]any, 0, len(parameters)+3)
	queryArgs = append(queryArgs, modelID)
	queryArgs = append(queryArgs, parameters...)
	queryArgs = append(queryArgs, pageSize, (page-1)*pageSize)
	rows, err := db.Query(query, queryArgs...)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var historyID, sceneID, impressionID, laneName string
		var shownAtMs, currentModel int64
		var snapshot sql.NullString
		if err := rows.Scan(&historyID, &sceneID, &impressionID, &laneName, &shownAtMs, &snapshot, &currentModel); err != nil {
			return jvNull(), err
		}
		var reasonSnapshot jVal
		if snapshot.Valid && snapshot.String != "" {
			reasonSnapshot, err = parseJSON([]byte(snapshot.String))
			if err != nil {
				reasonSnapshot = jvNull()
			}
		} else {
			reasonSnapshot = jvArr()
		}
		items.arr = append(items.arr, jvObj(
			jvKey("history_id", jvStr(historyID)),
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("impression_id", jvStr(impressionID)),
			jvKey("lane", jvStr(laneName)),
			jvKey("shown_at_ms", jvInt(shownAtMs)),
			jvKey("current_model", jvInt(currentModel)),
			jvKey("reason_snapshot", reasonSnapshot),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(pageSize)),
		jvKey("total", jvInt(total)),
		jvKey("lane", lane),
		jvKey("items", items),
	), nil
}

func opGetFeedbackHistory(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_feedback_history",
		func(settings jVal) (jVal, error) { return getFeedbackHistoryBody(pluginDir, payload, settings) })
}

func getFeedbackHistoryBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	page := argsInt(args, "page", 1)
	pageSize := argsInt(args, "page_size", 20)
	if page < 1 || pageSize < 1 || pageSize > 100 {
		return jvNull(), fmt.Errorf("invalid feedback history page")
	}
	const where = "feedback_type <> 'reversal'"
	var total int64
	if err := db.QueryRow(`SELECT count(*) FROM feedback WHERE ` + where).Scan(&total); err != nil {
		return jvNull(), err
	}
	rows, err := db.Query(`SELECT feedback_id, scene_id, feedback_type, value, occurred_at_ms,
           reversed_by_id
    FROM feedback WHERE `+where+`
    ORDER BY occurred_at_ms DESC, feedback_id DESC LIMIT ? OFFSET ?`,
		pageSize, (page-1)*pageSize)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var feedbackID, sceneID, feedbackType string
		var occurredAtMs int64
		var value any
		var reversedByID sql.NullString
		if err := rows.Scan(&feedbackID, &sceneID, &feedbackType, &value, &occurredAtMs, &reversedByID); err != nil {
			return jvNull(), err
		}
		// feedback.value is a TEXT column; Python's sqlite3 returns the stored
		// text verbatim, so the emitted JSON keeps strings as strings.
		var valueVal jVal = jvNull()
		switch t := value.(type) {
		case string:
			valueVal = jvStr(t)
		case []byte:
			valueVal = jvStr(string(t))
		case float64:
			valueVal = jvFloat(t)
		case int64:
			valueVal = jvInt(t)
		}
		var reversedVal jVal = jvNull()
		if reversedByID.Valid {
			reversedVal = jvStr(reversedByID.String)
		}
		items.arr = append(items.arr, jvObj(
			jvKey("feedback_id", jvStr(feedbackID)),
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("feedback_type", jvStr(feedbackType)),
			jvKey("value", valueVal),
			jvKey("occurred_at_ms", jvInt(occurredAtMs)),
			jvKey("reversed_by_id", reversedVal),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(pageSize)),
		jvKey("total", jvInt(total)),
		jvKey("items", items),
	), nil
}

func opGetShortlist(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_shortlist",
		func(settings jVal) (jVal, error) { return getShortlistBody(pluginDir, payload, settings) })
}

// getShortlistBody mirrors backend.py's get_shortlist dispatch +
// ExpandService.shortlist_results.
func getShortlistBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	page := argsInt(args, "page", 1)
	count := argsInt(args, "page_size", pythonInt(cfg.get("page_size")))
	if page < 1 || count < 1 || count > 500 {
		return jvNull(), fmt.Errorf("invalid shortlist page")
	}
	var total int64
	if err := db.QueryRow(`SELECT count(*) FROM external_shortlist`).Scan(&total); err != nil {
		return jvNull(), err
	}
	rows, err := db.Query(`SELECT * FROM external_shortlist ORDER BY added_at_ms DESC LIMIT ? OFFSET ?`,
		count, (page-1)*count)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return jvNull(), err
	}
	items := jvArr()
	for rows.Next() {
		values := make([]any, len(columns))
		scanned := make([]any, len(columns))
		for i := range columns {
			scanned[i] = &values[i]
		}
		if err := rows.Scan(scanned...); err != nil {
			return jvNull(), err
		}
		row := make(map[string]any, len(columns))
		for i, name := range columns {
			row[name] = values[i]
		}
		sources, err := parseJSON([]byte(asDBString(row["sources_json"])))
		if err != nil {
			sources = jvNull()
		}
		payloadJSON, err := parseJSON([]byte(asDBString(row["payload_json"])))
		if err != nil {
			payloadJSON = jvNull()
		}
		items.arr = append(items.arr, jvObj(
			jvKey("entity_type", jvStr(asDBString(row["entity_type"]))),
			jvKey("id", jvStr(asDBString(row["external_id"]))),
			jvKey("score", jvFloat(asDBFloat(row["score"]))),
			jvKey("sources", sources),
			jvKey("payload", payloadJSON),
			jvKey("shortlisted", jvBool(true)),
			jvKey("added_at_ms", jvInt(asDBInt(row["added_at_ms"]))),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("ready", jvBool(true)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(total)),
		jvKey("has_more", jvBool(page*count < total)),
		jvKey("items", items),
	), nil
}

func asDBFloat(v any) float64 {
	switch t := v.(type) {
	case float64:
		return t
	case int64:
		return float64(t)
	case []byte:
		f, _ := strconv.ParseFloat(string(t), 64)
		return f
	case string:
		f, _ := strconv.ParseFloat(t, 64)
		return f
	}
	return 0
}

func opGetTasteProfile(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_taste_profile",
		func(settings jVal) (jVal, error) { return getTasteProfileBody(pluginDir, payload, settings) })
}

func getTasteProfileBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	direct := make(map[string][2]jVal) // tag_id -> (value, blocked)
	rows, err := db.Query(`SELECT tag_id, value, blocked FROM direct_tag_preference`)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var tagID string
		var value float64
		var blocked int64
		if err := rows.Scan(&tagID, &value, &blocked); err != nil {
			return jvNull(), err
		}
		direct[tagID] = [2]jVal{jvFloat(value), jvBool(blocked != 0)}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	configVersion := "cfg-" + featureFingerprint()[:20]
	type profileItem struct {
		tagID      string
		name       string
		role       string
		sceneCount int64
		affinity   float64
		confidence float64
		support    float64
	}
	var items []profileItem
	itemRows, err := db.Query(`WITH scene_counts AS (
  SELECT tag_id, count(DISTINCT scene_id) AS scene_count
  FROM scene_tag WHERE provenance='scene' GROUP BY tag_id
)
SELECT t.tag_id, t.name, r.role, coalesce(sc.scene_count, 0) AS scene_count,
       a.affinity, a.confidence, a.effective_support
FROM source_tag t
JOIN tag_role r ON r.tag_id=t.tag_id AND r.config_version=?
LEFT JOIN scene_counts sc ON sc.tag_id=t.tag_id
LEFT JOIN feature_definition d
  ON d.feature_version=? AND d.family='content' AND d.name='tag:' || t.tag_id
LEFT JOIN feature_affinity a
  ON a.feature_id=d.feature_id AND a.model_id=?
ORDER BY t.name, t.tag_id`, configVersion, featureVersion, modelID)
	if err != nil {
		return jvNull(), err
	}
	for itemRows.Next() {
		var tagID, name, role string
		var sceneCount int64
		var affinity, confidence, effectiveSupport sql.NullFloat64
		if err := itemRows.Scan(&tagID, &name, &role, &sceneCount, &affinity, &confidence, &effectiveSupport); err != nil {
			return jvNull(), err
		}
		items = append(items, profileItem{
			tagID: tagID, name: name, role: role, sceneCount: sceneCount,
			affinity:   affinity.Float64,
			confidence: confidence.Float64,
			support:    effectiveSupport.Float64,
		})
	}
	itemRows.Close()
	if err := itemRows.Err(); err != nil {
		return jvNull(), err
	}
	type outputItem struct {
		tagID         string
		name          string
		inferredValue float64
		confidence    float64
		support       float64
		sceneCount    int64
		directValue   jVal
		directBlocked bool
		prompt        jVal
	}
	output := make([]outputItem, 0, len(items))
	for _, item := range items {
		directValue := jvNull()
		directBlocked := false
		if v, ok := direct[item.tagID]; ok {
			directValue = v[0]
			directBlocked = v[1].b
		}
		var prompt jVal = jvNull()
		if directValue.kind == jNull && item.role == "content" && item.sceneCount >= 2 {
			if item.confidence >= 0.35 && mathAbs(item.affinity) >= 0.15 {
				prompt = jvStr("belief")
			} else {
				prompt = jvStr("uncertain")
			}
		}
		output = append(output, outputItem{
			tagID:         item.tagID,
			name:          item.name,
			inferredValue: item.affinity,
			confidence:    item.confidence,
			support:       item.support,
			sceneCount:    item.sceneCount,
			directValue:   directValue,
			directBlocked: directBlocked,
			prompt:        prompt,
		})
	}
	// Python sort key: (prompt is None, prompt == "uncertain",
	// not (inferred > 0), -abs(inferred), name.casefold(), tag_id)
	sort.SliceStable(output, func(i, j int) bool {
		a, b := output[i], output[j]
		apNone := a.prompt.kind == jNull
		bpNone := b.prompt.kind == jNull
		if apNone != bpNone {
			return !apNone
		}
		apUncertain := a.prompt.kind == jStr && a.prompt.s == "uncertain"
		bpUncertain := b.prompt.kind == jStr && b.prompt.s == "uncertain"
		if apUncertain != bpUncertain {
			return !apUncertain
		}
		apos := a.inferredValue > 0
		bpos := b.inferredValue > 0
		if apos != bpos {
			return apos
		}
		if mathAbs(a.inferredValue) != mathAbs(b.inferredValue) {
			return mathAbs(a.inferredValue) > mathAbs(b.inferredValue)
		}
		aname, bname := strings.ToLower(a.name), strings.ToLower(b.name)
		if aname != bname {
			return aname < bname
		}
		return a.tagID < b.tagID
	})
	outItems := jvArr()
	for _, item := range output {
		outItems.arr = append(outItems.arr, jvObj(
			jvKey("tag_id", jvStr(item.tagID)),
			jvKey("name", jvStr(item.name)),
			jvKey("inferred_value", jvFloat(item.inferredValue)),
			jvKey("confidence", jvFloat(item.confidence)),
			jvKey("support", jvFloat(item.support)),
			jvKey("scene_count", jvInt(item.sceneCount)),
			jvKey("direct_value", item.directValue),
			jvKey("direct_blocked", jvBool(item.directBlocked)),
			jvKey("prompt", item.prompt),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(modelID)),
		jvKey("items", outItems),
	), nil
}

// featureFingerprint mirrors CuratorConfig.feature_fingerprint: sha256 of
// the sorted-key canonical JSON of FeatureConfig (asdict serialization).
func featureFingerprint() string {
	return sha256Hex(featureConfigCanonicalJSON())
}

// featureConfigCanonicalJSON mirrors FeatureConfig.feature_json() with the
// default (empty) ignored_tags. It is the default-config fingerprint used by
// the read-path tag_role/config-version lookups, which always run against the
// default feature config.
func featureConfigCanonicalJSON() string {
	return featureConfigCanonicalJSONWith(nil)
}

// featureConfigCanonicalJSONWith mirrors FeatureConfig.feature_json() for a
// given ignored_tags list (nil → the empty default). The build passes the
// runtime ignored_tags (from curator_config.ignored_tags) so the feature
// version and model fingerprint change when the ignore list changes.
func featureConfigCanonicalJSONWith(ignoredTags []string) string {
	rules := jvArr()
	rule := func(match, pattern, role string) {
		rules.arr = append(rules.arr, jvObj(
			jvKey("match", jvStr(match)),
			jvKey("pattern", jvStr(pattern)),
			jvKey("role", jvStr(role)),
		))
	}
	rule("prefix", "[Workflow:", "workflow_administrative")
	rule("prefix", "[Technical:", "quality_technical")
	rule("exact", "[Curator: Ignore]", "ignored")
	rule("regex", `\b(?:blonde?|brunette|redhead|black hair|brown hair|dyed hair)\b`, "performer_attribute")
	rule("regex", `\b(?:blue|brown|green|hazel|gr[ae]y) eyes?\b`, "performer_attribute")
	rule("regex", `\b(?:caucasian|asian|latina?|ebony)\b|\b(?:black|white|pale|medium|dark) skin\b`, "performer_attribute")
	rule("regex", `\b(?:big|small|medium|huge|tiny) (?:ass|tits|boobs|breasts)\b`, "performer_attribute")
	rule("regex", `\b(?:fake|natural) (?:tits|boobs|breasts)\b|\baugmentation\b`, "performer_attribute")
	rule("regex", `\b(?:tattoos?|piercings?)\b`, "performer_attribute")
	rule("regex", `^(?:athletic(?: body| woman)?|bubble butt|trimmed)$`, "performer_attribute")
	blockWeights := jvArr()
	for _, item := range performerBlockWeights {
		blockWeights.arr = append(blockWeights.arr, jvArr(
			jvStr(item.block),
			jvFloat(item.weight),
		))
	}
	config := jvObj(
		jvKey("idf_cap", jvFloat(2.5)),
		jvKey("idf_strength", jvFloat(0.5)),
		jvKey("ignored_tags", jvStrList(ignoredTags)),
		jvKey("marker_weight", jvFloat(0.45)),
		jvKey("one_off_prior", jvFloat(2.0)),
		jvKey("parent_weight", jvFloat(0.35)),
		jvKey("performer_block_weights", blockWeights),
		jvKey("tag_id_overrides", jvArr()),
		jvKey("tag_rules", rules),
	)
	return config.marshalSortedKeys()
}

func sha256Hex(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}
