// get_slate / replace_item — a port of CuratorAPI.get_slate and
// SlateBuilder.recommend (curator/api.py, curator/ranking/slate.py) for the
// materialized-lane path the published model serves. Byte-identical JSON to
// the Python backend for the same sidecar state, including the read-path
// writes: the eligibility-count cache row and the impression rows.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
)

// slateLanes mirrors SlateBuilder's lane vocabulary.
var slateLanes = map[string]bool{
	"for_you": true, "best_bets": true, "revisit": true, "stretch": true, "blind_spots": true,
	"dormant": true,
}

// queriedScoreFirstLanes mirrors slate.QUERIED_SCORE_FIRST_LANES.
var queriedScoreFirstLanes = map[string]bool{"best_bets": true, "revisit": true, "stretch": true}

// scoreFirstRankingJSON mirrors slate.SCORE_FIRST_RANKING_JSON.
const scoreFirstRankingJSON = `{"penalties":{"performer":0.0,"studio":0.0,"content":0.0,"history":0.0,"live_cooldown":0.0},"bonuses":{"uncovered_content":0.0}}`

func opGetSlate(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_slate",
		func(settings jVal) (jVal, error) { return getSlateBody(pluginDir, payload, settings) })
}

func opReplaceItem(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "replace_item",
		func(settings jVal) (jVal, error) { return replaceItemBody(pluginDir, payload, settings) })
}

// openAPISidecar mirrors _api's connection: migrate, apply settings, attach
// the published artifacts.
func openAPISidecar(pluginDir string, payload, settings jVal) (dbx, error) {
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return nil, err
	}
	// The settings were just applied to the sidecar; if schedules or auto
	// tasks are enabled the worker must exist to act on them. This is the
	// single point covering every op, so any Curator activity (including the
	// Settings panel's own reload after a toggle) spawns or keeps the daemon.
	ensureAutoWorker(pluginDir, payload, settings, db)
	return db, nil
}

// getSlateBody mirrors backend.py's get_slate dispatch + CuratorAPI.get_slate.
func getSlateBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	count := argsInt(args, "count", pythonInt(cfg.get("page_size")))
	lane := argsString(args, "lane", "for_you")
	page := argsInt(args, "page", 1)
	var impressionID jVal = jvNull()
	if args.get("impression_id").truthy() {
		impressionID = jvStr(args.get("impression_id").asString())
	}
	var context jVal = jvNull()
	if c := args.get("context"); c.kind == jObj {
		context = c
	}
	exploration := argsFloat(args, "exploration", 0)
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
	gender := argsString(args, "gender", "")
	return getSlateCore(db, config, lane, count, page, impressionID, context, excludedSet, exploration,
		includeTags, excludeTags, performerIDs, studioIDs, gender)
}

// replaceItemBody mirrors backend.py's replace_item: get_slate(lane, 1,
// context={"replacement": True}). Unlike get_slate, replace_item reads
// exclude_scene_ids without a [] default, so an absent key errors.
func replaceItemBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	config, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	args := payload.get("args")
	excluded := args.get("exclude_scene_ids")
	if !isList(excluded) {
		return jvNull(), fmt.Errorf("exclude_scene_ids must be a list")
	}
	excludedSet, err := excludeSceneIDs(excluded)
	if err != nil {
		return jvNull(), err
	}
	lane := argsString(args, "lane", "for_you")
	exploration := argsFloat(args, "exploration", 0)
	return getSlateCore(db, config, lane, 1, 1, jvNull(),
		jvObj(jvKey("replacement", jvBool(true))), excludedSet, exploration, nil, nil, nil, nil, "")
}

// getSlateCore mirrors CuratorAPI.get_slate after arg coercion. The filter
// args (includeTags/excludeTags/performerIDs/studioIDs/gender) narrow the
// lane's already-classified candidates the same way get_similar narrows its
// candidates; they don't change ranking. A filtered materialized request
// scans candidate IDs for its exact total but hydrates only the requested
// page; exploratory requests still recompute the full slate.
func getSlateCore(db dbx, config jVal, lane string, count, page int64, impressionID, context jVal, excluded map[string]bool, exploration float64, includeTags, excludeTags, performerIDs, studioIDs []string, gender string) (jVal, error) {
	if page < 1 || count < 1 || count > 500 {
		return jvNull(), fmt.Errorf("invalid recommendation page")
	}
	cfg := config.get("config")
	modelUpdate, err := modelUpdateStatus(db)
	if err != nil {
		return jvNull(), err
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	start := (page - 1) * count
	end := page * count
	diversityEnabled := cfg.get("diversity_enabled").truthy()

	sceneFilter, err := buildSceneFilter(db, includeTags, excludeTags, performerIDs, studioIDs, gender)
	if err != nil {
		return jvNull(), err
	}
	var total int64 = -1
	if exploration == 0 {
		total, err = availableCount(db, modelID, lane, diversityEnabled, excluded, sceneFilter)
		if err != nil {
			return jvNull(), err
		}
	}
	var requestCount int64
	if total >= 0 {
		requestCount = end + int64(len(excluded))
	} else {
		var candidateCount int64
		if lane == "for_you" {
			candidateCount = scanInt(db, `SELECT count(DISTINCT scene_id) FROM model_scene_lane WHERE model_id=?`, modelID)
		} else {
			candidateCount = scanInt(db, `SELECT count(DISTINCT scene_id) FROM model_scene_lane WHERE model_id=? AND lane=?`, modelID, lane)
		}
		requestCount = maxInt64(end+int64(len(excluded)), candidateCount+int64(len(excluded)))
	}
	built, err := recommend(db, modelID, lane, requestCount, diversityEnabled, exploration, sceneFilter)
	if err != nil {
		return jvNull(), err
	}
	var available []*recommendationItem
	for _, item := range built.items {
		if !excluded[item.sceneID] {
			available = append(available, item)
		}
	}
	if total < 0 {
		total = int64(len(available))
	}
	var selected []*recommendationItem
	if start < int64(len(available)) {
		selEnd := minInt64(end, int64(len(available)))
		for i := start; i < selEnd; i++ {
			item := *available[i]
			item.position = i
			selected = append(selected, &item)
		}
	}
	if impressionID.kind == jNull {
		impressionID = jvStr(uuid4())
	}
	now := nowMs()
	if err := recordImpression(db, impressionID.asString(), built.lane, built.modelID, selected, now, context); err != nil {
		return jvNull(), err
	}
	rebuilding, err := scanExists(db, `SELECT 1 FROM curator_job
WHERE state='running' AND job_type IN ('build', 'force-build', 'update-model', 'sync-build', 'full-sync-build') LIMIT 1`)
	if err != nil {
		return jvNull(), err
	}
	items := jvArr()
	for _, item := range selected {
		items.arr = append(items.arr, recommendationItemJSON(item, impressionID))
	}
	diagnostics := jvArr()
	for _, d := range built.diagnostics {
		diagnostics.arr = append(diagnostics.arr, jvStr(d))
	}
	// timings_ms and ranking_timings_ms are wall-clock in Python and vary
	// between runs; the harness compares them structurally. The keys must
	// match Python's set exactly.
	timings := jvObj(
		jvKey("model_update", jvInt(0)),
		jvKey("ranking", jvInt(0)),
		jvKey("impression", jvInt(0)),
		jvKey("total", jvInt(0)),
	)
	rankingTimings := jvObj()
	for _, k := range []string{"materialized", "selection", "total"} {
		if v, ok := built.timingsMs[k]; ok {
			rankingTimings.set(k, jvInt(v))
		}
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(built.modelID)),
		jvKey("config_updated_at_ms", jvInt(pythonInt(config.get("updated_at_ms")))),
		jvKey("model_pending", jvBool(modelUpdate.pending())),
		jvKey("rebuilding", jvBool(rebuilding)),
		jvKey("impression_id", impressionID),
		jvKey("lane", jvStr(lane)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(total)),
		jvKey("has_more", jvBool(total > end)),
		jvKey("items", items),
		jvKey("diagnostics", diagnostics),
		jvKey("timings_ms", timings),
		jvKey("ranking_timings_ms", rankingTimings),
	), nil
}

// recommendationItem mirrors SlateBuilder's RecommendationItem dataclass in
// asdict() key order, with the impression_id appended by get_slate.
type recommendationItem struct {
	sceneID       string
	lane          string
	sourceLane    string
	subtype       jVal
	position      int64
	appeal        float64
	currentFit    float64
	confidence    float64
	laneValue     float64
	finalUtility  float64
	penalties     jVal
	bonuses       jVal
	components    jVal
	neighbors     jVal
	eligibility   jVal
	qualification jVal
	reasonIDs     []string
}

func recommendationItemDict(item *recommendationItem) jVal {
	reasons := jvArr()
	for _, id := range item.reasonIDs {
		reasons.arr = append(reasons.arr, jvStr(id))
	}
	return jvObj(
		jvKey("scene_id", jvStr(item.sceneID)),
		jvKey("lane", jvStr(item.lane)),
		jvKey("source_lane", jvStr(item.sourceLane)),
		jvKey("subtype", item.subtype),
		jvKey("position", jvInt(item.position)),
		jvKey("appeal", jvFloat(item.appeal)),
		jvKey("current_fit", jvFloat(item.currentFit)),
		jvKey("confidence", jvFloat(item.confidence)),
		jvKey("lane_value", jvFloat(item.laneValue)),
		jvKey("final_utility", jvFloat(item.finalUtility)),
		jvKey("penalties", item.penalties),
		jvKey("bonuses", item.bonuses),
		jvKey("components", item.components),
		jvKey("neighbors", item.neighbors),
		jvKey("eligibility", item.eligibility),
		jvKey("qualification", item.qualification),
		jvKey("reason_ids", reasons),
	)
}

func recommendationItemJSON(item *recommendationItem, impressionID jVal) jVal {
	result := recommendationItemDict(item)
	result.set("impression_id", impressionID)
	return result
}

// builtSlate mirrors slate.Slate.
type builtSlate struct {
	modelID     string
	lane        string
	items       []*recommendationItem
	diagnostics []string
	timingsMs   map[string]int64
}

// directPlayFilter carries _direct_play_filters' two outputs.
type directPlayFilter struct {
	plays       map[string]int64 // scene_id -> last_played
	unrecovered map[string]bool
}

// observedPlaybackSQL mirrors events.contracts.OBSERVED_PLAYBACK_SQL.
const observedPlaybackSQL = `(
    active_seconds > 0
    OR json_array_length(COALESCE(json_extract(summary_json, '$.played_ranges'), '[]')) > 0
    OR COALESCE(json_extract(summary_json, '$.maximum_position_seconds'), 0)
       > COALESCE(json_extract(summary_json, '$.start_position_seconds'), 0)
)`

// directPlayFilters mirrors SlateBuilder._direct_play_filters.
func directPlayFilters(db dbx, nowMs int64) (directPlayFilter, error) {
	plays := make(map[string]int64)
	rows, err := db.Query(`SELECT scene_id, max(ended_at_ms) AS last_played FROM play_session
WHERE provenance='direct_player' AND ` + observedPlaybackSQL + ` GROUP BY scene_id`)
	if err != nil {
		return directPlayFilter{}, err
	}
	for rows.Next() {
		var sceneID string
		var lastPlayed int64
		if err := rows.Scan(&sceneID, &lastPlayed); err != nil {
			return directPlayFilter{}, err
		}
		plays[sceneID] = lastPlayed
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return directPlayFilter{}, err
	}
	unrecovered := make(map[string]bool)
	for sceneID, playedAt := range plays {
		days := float64(nowMs-playedAt) / 86_400_000
		if days < 0 {
			days = 0
		}
		if sceneRecovery(days) < 0.10 {
			unrecovered[sceneID] = true
		}
	}
	return directPlayFilter{plays: plays, unrecovered: unrecovered}, nil
}

// materializedRowIsEligible mirrors SlateBuilder._materialized_row_is_eligible.
func materializedRowIsEligible(sceneID, sourceLane string, eligibility map[string]eligibilityResult, filter directPlayFilter) bool {
	state, ok := eligibility[sceneID]
	if !ok {
		state = eligibilityResult{}
	}
	_, played := filter.plays[sceneID]
	return state.eligible &&
		!(sourceLane == "best_bets" && played) &&
		!(sourceLane == "revisit" && filter.unrecovered[sceneID])
}

// recommend mirrors SlateBuilder.recommend. The materialized path (published
// model with materialized lanes, exploration == 0) is the read interface the
// build task serves; the greedy recompute path is ported for byte parity when
// lanes are not materialized or exploration is non-zero.
func recommend(db dbx, modelID, lane string, count int64, diversityEnabled bool, exploration float64, sceneFilter func(string) bool) (builtSlate, error) {
	if !slateLanes[lane] {
		return builtSlate{}, fmt.Errorf("unknown lane: %s", lane)
	}
	if count < 1 {
		return builtSlate{}, fmt.Errorf("count must be positive")
	}
	if !isFinite(exploration) || exploration < -1 || exploration > 1 {
		return builtSlate{}, fmt.Errorf("exploration must be between -1 and 1")
	}
	if modelID == "" {
		return builtSlate{}, fmt.Errorf("no published model; run build-model first")
	}
	if exploration == 0 {
		slate, ok, err := loadMaterializedSlate(db, modelID, lane, count, diversityEnabled, sceneFilter)
		if err != nil {
			return builtSlate{}, err
		}
		if ok {
			return slate, nil
		}
	}
	return recommendGreedy(db, modelID, lane, count, diversityEnabled, exploration, sceneFilter)
}

func isFinite(f float64) bool { return !math.IsInf(f, 0) && !math.IsNaN(f) }

// laneValueMaxes returns the per-lane max lane_value from model_scene_lane,
// used to make the displayed "Rank in <lane>" relative to the lane's best
// (issue #212).
func laneValueMaxes(db dbx, modelID string) (map[string]float64, error) {
	rows, err := db.Query(`SELECT lane, MAX(lane_value) FROM model_scene_lane WHERE model_id=? GROUP BY lane`, modelID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := map[string]float64{}
	for rows.Next() {
		var lane string
		var maxValue float64
		if err := rows.Scan(&lane, &maxValue); err != nil {
			return nil, err
		}
		result[lane] = maxValue
	}
	return result, rows.Err()
}

// rankValue normalizes a lane value against the lane's best so the top of the
// lane reads 1.00 (issue #212). Lanes without a positive max (including the
// score_review pseudo-lane) keep their raw value.
func rankValue(laneValue, laneMax float64) float64 {
	if laneMax <= 0 {
		return laneValue
	}
	return laneValue / laneMax
}

// loadMaterializedSlate mirrors SlateBuilder._load_materialized_slate. The
// second return value is false when the model has no materialized lanes.
// sceneFilter, when non-nil, additionally gates each row (get_slate's
// include/exclude tag, performer, studio, and gender filters).
func loadMaterializedSlate(db dbx, modelID, lane string, count int64, diversityEnabled bool, sceneFilter func(string) bool) (builtSlate, bool, error) {
	exists, err := scanExists(db, `SELECT 1 FROM model_lane_order_state WHERE model_id=?`, modelID)
	if err != nil || !exists {
		return builtSlate{}, false, err
	}
	ordering := "varied"
	if !diversityEnabled {
		ordering = "score_first"
	}
	queryScoreFirst := !diversityEnabled && queriedScoreFirstLanes[lane]
	now := nowMs()
	filter, err := directPlayFilters(db, now)
	if err != nil {
		return builtSlate{}, false, err
	}
	type slateRow struct {
		position    int64
		sceneID     string
		sourceLane  string
		utility     float64
		rankingJSON string
	}
	var selectedRows []slateRow
	offset := int64(0)
	chunkSize := maxInt64(100, count)
	for int64(len(selectedRows)) < count {
		var rows *sql.Rows
		if queryScoreFirst {
			rows, err = db.Query(`SELECT 0 AS position, scene_id, lane AS source_lane,
	                           lane_value AS utility, ? AS ranking_json
	                    FROM model_scene_lane
	                    WHERE model_id=? AND lane=?
	                    ORDER BY lane_value DESC, scene_id
	                    LIMIT ? OFFSET ?`, scoreFirstRankingJSON, modelID, lane, chunkSize, offset)
		} else {
			rows, err = db.Query(`SELECT position, scene_id, source_lane, utility, ranking_json
	                    FROM model_lane_order
	                    WHERE model_id=? AND lane=? AND ordering=?
	                    ORDER BY position LIMIT ? OFFSET ?`, modelID, lane, ordering, chunkSize, offset)
		}
		if err != nil {
			return builtSlate{}, false, err
		}
		chunk := make([]slateRow, 0, chunkSize)
		for rows.Next() {
			var row slateRow
			if err := rows.Scan(&row.position, &row.sceneID, &row.sourceLane, &row.utility, &row.rankingJSON); err != nil {
				rows.Close()
				return builtSlate{}, false, err
			}
			chunk = append(chunk, row)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return builtSlate{}, false, err
		}
		if len(chunk) == 0 {
			break
		}
		offset += int64(len(chunk))
		sceneIDs := make(map[string]bool, len(chunk))
		for _, row := range chunk {
			sceneIDs[row.sceneID] = true
		}
		eligibility, err := sceneEligibility(db, now, sceneIDs)
		if err != nil {
			return builtSlate{}, false, err
		}
		for _, row := range chunk {
			if materializedRowIsEligible(row.sceneID, row.sourceLane, eligibility, filter) &&
				(sceneFilter == nil || sceneFilter(row.sceneID)) {
				selectedRows = append(selectedRows, row)
			}
		}
		if int64(len(chunk)) < chunkSize {
			break
		}
	}
	if int64(len(selectedRows)) > count {
		selectedRows = selectedRows[:count]
	}
	sceneIDs := make(map[string]bool, len(selectedRows))
	for _, row := range selectedRows {
		sceneIDs[row.sceneID] = true
	}
	scores, err := modelScores(db, modelID, sceneIDs)
	if err != nil {
		return builtSlate{}, false, err
	}
	classifications, err := laneClassifications(db, modelID, sceneIDs)
	if err != nil {
		return builtSlate{}, false, err
	}
	liveFit, liveCooldown, err := liveCurrentFit(db, modelID, filter, now)
	if err != nil {
		return builtSlate{}, false, err
	}
	// The displayed "Rank in <lane>" is relative to the lane's best (issue
	// #212): normalize each item's lane_value by its source lane's max so the
	// top of every lane reads 1.00.
	laneMaxes, err := laneValueMaxes(db, modelID)
	if err != nil {
		return builtSlate{}, false, err
	}
	items := make([]*recommendationItem, 0, len(selectedRows))
	for position, row := range selectedRows {
		sceneID := row.sceneID
		classification, ok := classifications[sceneID+"\x00"+row.sourceLane]
		if !ok {
			continue
		}
		score, ok := scores[sceneID]
		if !ok {
			continue
		}
		ranking, err := parseJSON([]byte(row.rankingJSON))
		if err != nil {
			return builtSlate{}, false, err
		}
		penalties := ranking.get("penalties")
		if penalties.kind != jObj {
			penalties = jvObj()
		}
		penaltiesCopy := jVal{kind: jObj, obj: append([]jPair(nil), penalties.obj...)}
		penaltiesCopy.set("live_cooldown", jvFloat(liveCooldown[sceneID]))
		bonuses := ranking.get("bonuses")
		if bonuses.kind != jObj {
			bonuses = jvObj()
		}
		reasons := []string{"eligibility.lane"}
		for _, pair := range penaltiesCopy.obj {
			if pair.key == "live_cooldown" {
				continue
			}
			if pair.val.kind == jNum && floatValue(pair.val) > 0 {
				reasons = append(reasons, "diversity."+pair.key)
			}
		}
		currentFit := score.currentFit
		if v, ok := liveFit[sceneID]; ok {
			currentFit = v
		}
		items = append(items, &recommendationItem{
			sceneID:       sceneID,
			lane:          lane,
			sourceLane:    row.sourceLane,
			subtype:       classification.subtype,
			position:      int64(position),
			appeal:        score.appeal,
			currentFit:    currentFit,
			confidence:    score.confidence,
			laneValue:     rankValue(classification.laneValue, laneMaxes[row.sourceLane]),
			finalUtility:  row.utility - liveCooldown[sceneID],
			penalties:     penaltiesCopy,
			bonuses:       bonuses,
			components:    score.components,
			neighbors:     score.neighbors,
			eligibility:   score.eligibility,
			qualification: classification.qualification,
			reasonIDs:     reasons,
		})
	}
	elapsed := int64(0)
	return builtSlate{
		modelID:     modelID,
		lane:        lane,
		items:       items,
		diagnostics: nil,
		timingsMs:   map[string]int64{"materialized": 1, "selection": elapsed, "total": elapsed},
	}, true, nil
}

func floatValue(v jVal) float64 {
	f, err := pythonFloat(v)
	if err != nil {
		return 0
	}
	return f
}

// laneClassification mirrors LaneClassification for the materialized reads.
type laneClassification struct {
	subtype       jVal
	laneValue     float64
	qualification jVal
}

// laneClassifications reads model_scene_lane for the selected scenes, keyed
// by (scene_id, lane) like Python's classifications dict.
func laneClassifications(db dbx, modelID string, sceneIDs map[string]bool) (map[string]laneClassification, error) {
	result := make(map[string]laneClassification, len(sceneIDs))
	if len(sceneIDs) == 0 {
		return result, nil
	}
	ids := sortedKeys(sceneIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, modelID)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT scene_id, lane, subtype, lane_value, qualification_json
FROM model_scene_lane WHERE model_id=? AND scene_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID, lane string
		var subtype sql.NullString
		var laneValue float64
		var qualificationJSON string
		if err := rows.Scan(&sceneID, &lane, &subtype, &laneValue, &qualificationJSON); err != nil {
			return nil, err
		}
		var subtypeVal jVal = jvNull()
		if subtype.Valid {
			subtypeVal = jvStr(subtype.String)
		}
		qualification, err := parseJSON([]byte(qualificationJSON))
		if err != nil {
			qualification = jvNull()
		}
		result[sceneID+"\x00"+lane] = laneClassification{subtype: subtypeVal, laneValue: laneValue, qualification: qualification}
	}
	return result, rows.Err()
}

// modelScore mirrors RecommendationModelStore.ModelSceneScore on the fields
// the slate items need.
type modelScore struct {
	appeal      float64
	currentFit  float64
	confidence  float64
	components  jVal
	neighbors   jVal
	eligibility jVal
}

// modelScores mirrors RecommendationModelStore.scores: the score row plus
// neighbors from model_scene_neighbor ordered by (scene_id, rank).
func modelScores(db dbx, modelID string, sceneIDs map[string]bool) (map[string]modelScore, error) {
	result := make(map[string]modelScore, len(sceneIDs))
	if len(sceneIDs) == 0 {
		return result, nil
	}
	ids := sortedKeys(sceneIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, modelID)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT scene_id, appeal, current_fit, confidence,
    components_json, eligibility_json
FROM model_scene_score WHERE model_id=? AND scene_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, componentsJSON, eligibilityJSON string
		var appeal, currentFit, confidence float64
		if err := rows.Scan(&sceneID, &appeal, &currentFit, &confidence, &componentsJSON, &eligibilityJSON); err != nil {
			rows.Close()
			return nil, err
		}
		components, err := parseJSON([]byte(componentsJSON))
		if err != nil {
			components = jvNull()
		}
		eligibility, err := parseJSON([]byte(eligibilityJSON))
		if err != nil {
			eligibility = jvNull()
		}
		result[sceneID] = modelScore{appeal: appeal, currentFit: currentFit, confidence: confidence, components: components, eligibility: eligibility}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	neighborRows, err := db.Query(`SELECT scene_id, neighbor_scene_id, similarity, weight, outcome
FROM model_scene_neighbor WHERE model_id=? AND scene_id IN (`+placeholders+`) ORDER BY scene_id, rank`, args...)
	if err != nil {
		return nil, err
	}
	defer neighborRows.Close()
	neighborsByScene := make(map[string][]jVal)
	for neighborRows.Next() {
		var sceneID, neighborID string
		var similarity, weight, outcome float64
		if err := neighborRows.Scan(&sceneID, &neighborID, &similarity, &weight, &outcome); err != nil {
			return nil, err
		}
		neighborsByScene[sceneID] = append(neighborsByScene[sceneID], jvObj(
			jvKey("scene_id", jvStr(neighborID)),
			jvKey("similarity", jvFloat(similarity)),
			jvKey("weight", jvFloat(weight)),
			jvKey("outcome", jvFloat(outcome)),
		))
	}
	if err := neighborRows.Err(); err != nil {
		return nil, err
	}
	for sceneID, score := range result {
		score.neighbors = jvArr(neighborsByScene[sceneID]...)
		result[sceneID] = score
	}
	return result, nil
}

// liveCurrentFit mirrors SlateBuilder._live_current_fit.
func liveCurrentFit(db dbx, modelID string, filter directPlayFilter, nowMs int64) (map[string]float64, map[string]float64, error) {
	liveFit := make(map[string]float64)
	cooldown := make(map[string]float64)
	if len(filter.plays) == 0 {
		return liveFit, cooldown, nil
	}
	ids := sortedIntKeys(filter.plays)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, modelID)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT scene_id, appeal, current_fit FROM model_scene_score
WHERE model_id=? AND scene_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID string
		var appeal, storedFit float64
		if err := rows.Scan(&sceneID, &appeal, &storedFit); err != nil {
			return nil, nil, err
		}
		days := float64(nowMs-filter.plays[sceneID]) / 86_400_000
		if days < 0 {
			days = 0
		}
		recovery := sceneRecovery(days)
		live := appeal - mathMax(0, appeal)*(1-recovery)
		liveFit[sceneID] = mathMin(storedFit, live)
		cooldown[sceneID] = mathMax(0, storedFit-live)
	}
	return liveFit, cooldown, rows.Err()
}

func mathMax(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

func mathMin(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func minInt64(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}

// availableCount mirrors SlateBuilder.available_count: -1 signals None (no
// model or no materialized lanes). Unfiltered per-lane counts are cached in
// application_meta under an eligibility fingerprint; filtered counts are
// request-specific and bypass the cache.
func availableCount(db dbx, modelID, lane string, diversityEnabled bool, excluded map[string]bool, sceneFilter func(string) bool) (int64, error) {
	if modelID == "" {
		return -1, nil
	}
	exists, err := scanExists(db, `SELECT 1 FROM model_lane_order_state WHERE model_id=?`, modelID)
	if err != nil || !exists {
		return -1, err
	}
	ordering := "varied"
	if !diversityEnabled {
		ordering = "score_first"
	}
	queryScoreFirst := !diversityEnabled && queriedScoreFirstLanes[lane]
	var fingerprint, cacheKey string
	if sceneFilter == nil {
		fingerprint, err = eligibilityFingerprint(db)
		if err != nil {
			return 0, err
		}
		cacheKey = "eligibility_count:" + modelID + ":" + lane + ":" + ordering
		var value string
		err = db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, cacheKey).Scan(&value)
		if err == nil {
			payload, perr := parseJSON([]byte(value))
			if perr == nil && payload.get("fingerprint").asString() == fingerprint {
				total := pythonInt(payload.get("count")) - excludedEligibleCount(db, excluded)
				if total < 0 {
					total = 0
				}
				return total, nil
			}
		} else if err != sql.ErrNoRows {
			return 0, err
		}
	}
	var rows *sql.Rows
	if queryScoreFirst {
		rows, err = db.Query(`SELECT scene_id, lane AS source_lane FROM model_scene_lane
WHERE model_id=? AND lane=?`, modelID, lane)
	} else {
		rows, err = db.Query(`SELECT scene_id, source_lane FROM model_lane_order
WHERE model_id=? AND lane=? AND ordering=?`, modelID, lane, ordering)
	}
	if err != nil {
		return 0, err
	}
	type laneRow struct{ sceneID, sourceLane string }
	var chunk []laneRow
	for rows.Next() {
		var r laneRow
		if err := rows.Scan(&r.sceneID, &r.sourceLane); err != nil {
			rows.Close()
			return 0, err
		}
		chunk = append(chunk, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	sceneIDs := make(map[string]bool, len(chunk))
	for _, r := range chunk {
		sceneIDs[r.sceneID] = true
	}
	now := nowMs()
	eligibility, err := sceneEligibility(db, now, sceneIDs)
	if err != nil {
		return 0, err
	}
	filter, err := directPlayFilters(db, now)
	if err != nil {
		return 0, err
	}
	total := int64(0)
	for _, r := range chunk {
		if materializedRowIsEligible(r.sceneID, r.sourceLane, eligibility, filter) &&
			(sceneFilter == nil || sceneFilter(r.sceneID) && !excluded[r.sceneID]) {
			total++
		}
	}
	if sceneFilter != nil {
		return total, nil
	}
	payload := jvObj(jvKey("fingerprint", jvStr(fingerprint)), jvKey("count", jvInt(total)))
	if err := execImmediate(db, `INSERT INTO application_meta(key, value) VALUES (?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, cacheKey, payload.marshalCompact()); err != nil {
		return 0, err
	}
	total -= excludedEligibleCount(db, excluded)
	if total < 0 {
		total = 0
	}
	return total, nil
}

// eligibilityFingerprint mirrors SlateBuilder._eligibility_fingerprint: a
// sha256 over per-input (count, max-ms) digests.
func eligibilityFingerprint(db dbx) (string, error) {
	digest := sha256.New()
	queries := []struct {
		label string
		sql   string
	}{
		{"feedback", `SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM feedback WHERE reversed_by_id IS NULL`},
		{"exclusion", `SELECT count(*), coalesce(max(created_at_ms), 0) FROM exclusion WHERE reversed_at_ms IS NULL`},
		{"pruning", `SELECT count(*), coalesce(max(updated_at_ms), 0) FROM pruning_candidate`},
		{"blocked_tags", `SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM direct_tag_preference WHERE blocked=1`},
		{"blocked_terms", `SELECT count(*), coalesce(max(occurred_at_ms), 0) FROM direct_term_preference WHERE blocked=1`},
		{"files", `SELECT count(*), 0 FROM source_file WHERE available=1`},
	}
	for _, q := range queries {
		var count, maxMs int64
		if err := db.QueryRow(q.sql).Scan(&count, &maxMs); err != nil {
			return "", err
		}
		digest.Write([]byte(q.label + ":" + strconv.FormatInt(count, 10) + ":" + strconv.FormatInt(maxMs, 10)))
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

// excludedEligibleCount mirrors SlateBuilder._excluded_eligible_count.
func excludedEligibleCount(db dbx, excluded map[string]bool) int64 {
	if len(excluded) == 0 {
		return 0
	}
	eligibility, err := sceneEligibility(db, nowMs(), excluded)
	if err != nil {
		return 0
	}
	count := int64(0)
	for sceneID := range excluded {
		if state, ok := eligibility[sceneID]; ok && state.eligible {
			count++
		}
	}
	return count
}

// recordImpression mirrors InteractionStore.record_ranked_impression as
// called by get_slate: INSERT OR IGNORE the impression row, then the item
// rows when it was newly inserted, inside BEGIN IMMEDIATE.
func recordImpression(db dbx, impressionID, lane, modelID string, items []*recommendationItem, requestedAtMs int64, requestContext jVal) error {
	contextJSON := "{}"
	if requestContext.kind == jObj {
		contextJSON = requestContext.marshalSortedKeys()
	}
	conn, err := db.Conn(context.Background())
	if err != nil {
		return err
	}
	defer conn.Close()
	ctx := context.Background()
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	rowsAffected := int64(0)
	{
		result, err := conn.ExecContext(ctx, `INSERT OR IGNORE INTO impression(
    impression_id, requested_at_ms, lane, model_id, config_version, request_context_json
) VALUES (?, ?, ?, ?, 'builtin', ?)`, impressionID, requestedAtMs, lane, modelID, contextJSON)
		if err != nil {
			conn.ExecContext(ctx, "ROLLBACK")
			return err
		}
		if result != nil {
			rowsAffected, _ = result.RowsAffected()
		}
	}
	if rowsAffected > 0 {
		for _, item := range items {
			reasons := jvArr()
			for _, id := range item.reasonIDs {
				reasons.arr = append(reasons.arr, jvStr(id))
			}
			if _, err := conn.ExecContext(ctx, `INSERT INTO impression_item(
    impression_id, scene_id, position, policy_score, reason_snapshot_json
) VALUES (?, ?, ?, ?, ?)`, impressionID, item.sceneID, item.position, item.finalUtility, reasons.marshalCompact()); err != nil {
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

// sortedKeys returns a sorted slice of a string-keyed map.
func sortedKeys(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// sortedIntKeys returns the sorted keys of a string -> int64 map.
func sortedIntKeys(values map[string]int64) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// scanExists runs a SELECT 1 ... LIMIT 1 probe.
func scanExists(db dbx, query string, args ...any) (bool, error) {
	var one int
	err := db.QueryRow(query, args...).Scan(&one)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, nil
}

// scanInt runs a count probe.
func scanInt(db dbx, query string, args ...any) int64 {
	var value int64
	if err := db.QueryRow(query, args...).Scan(&value); err != nil {
		return 0
	}
	return value
}

// currentModelID mirrors RecommendationModelStore.current_model_id: the
// attached model generation id, else the published model_version row.
func currentModelID(db dbx) (string, error) {
	if attached := attachedGenerationID(db, "model"); attached != "" {
		return attached, nil
	}
	var modelID string
	err := db.QueryRow(`SELECT model_id FROM model_version WHERE status='published'`).Scan(&modelID)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return modelID, nil
}

// attachedGenerationID mirrors artifacts.attached_generation_id: the
// generation_id of the attached read-only artifact, or "".
func attachedGenerationID(db dbx, kind string) string {
	var generationID string
	if err := db.QueryRow(`SELECT generation_id FROM ` + kind + `_generation.artifact_meta`).Scan(&generationID); err != nil {
		return ""
	}
	return generationID
}

// buildSceneFilter returns a predicate for get_slate's include/exclude tag,
// performer, studio, and gender filters, or nil when none are set. It mirrors
// the corresponding per-candidate checks in similarCore/similarityService.scenes
// (core/similar.go), narrowed to the fields that make sense for a lane that's
// already been classified by the model: no minimum-similarity or
// favorite-only knob, since those are about ranking a candidate against a
// source entity, not about narrowing a pre-picked set.
func buildSceneFilter(db dbx, includeTags, excludeTags, performerIDs, studioIDs []string, gender string) (func(string) bool, error) {
	if len(includeTags) == 0 && len(excludeTags) == 0 && len(performerIDs) == 0 && len(studioIDs) == 0 && gender == "" {
		return nil, nil
	}
	performers, err := scenePerformers(db)
	if err != nil {
		return nil, err
	}
	var genders map[string]string
	if gender != "" {
		genders, err = performerGenders(db)
		if err != nil {
			return nil, err
		}
	}
	var studioByScene map[string]string
	if len(studioIDs) > 0 {
		studioByScene, err = studios(db)
		if err != nil {
			return nil, err
		}
	}
	included, err := equivalentTagNames(db, includeTags)
	if err != nil {
		return nil, err
	}
	excluded, err := equivalentTagNames(db, excludeTags)
	if err != nil {
		return nil, err
	}
	filterNames := make(map[string]bool)
	for _, group := range included {
		for name := range group {
			filterNames[name] = true
		}
	}
	for _, group := range excluded {
		for name := range group {
			filterNames[name] = true
		}
	}
	var sceneTags map[string]map[string]bool
	if len(filterNames) > 0 {
		sceneTags, err = sceneTagNames(db, filterNames)
		if err != nil {
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
	return func(sceneID string) bool {
		candidatePerformers := performers[sceneID]
		if gender != "" {
			matched := false
			for _, p := range candidatePerformers {
				if genders[p] == gender {
					matched = true
					break
				}
			}
			if !matched {
				return false
			}
		}
		candidateTags := sceneTags[sceneID]
		for _, group := range included {
			has := false
			for name := range group {
				if candidateTags[name] {
					has = true
					break
				}
			}
			if !has {
				return false
			}
		}
		for _, group := range excluded {
			for name := range group {
				if candidateTags[name] {
					return false
				}
			}
		}
		if len(performerIDSet) > 0 && !containsAll(candidatePerformers, performerIDSet) {
			return false
		}
		if len(studioIDSet) > 0 && !studioIDSet[studioByScene[sceneID]] {
			return false
		}
		return true
	}, nil
}
