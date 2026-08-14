// get_score_review — review the bottom of the appeal distribution (the
// sentiment check). A port of CuratorAPI.get_score_review +
// SlateBuilder.score_review (curator/api.py, curator/ranking/slate.py) for
// the model-scored read path. Candidates are model_scene_score rows ordered
// by appeal ASC (tie-break scene_id), filtered appeal <= max_appeal, with
// the same live eligibility applied as the slate path (stale/deleted scenes
// excluded), paged by (page-1)*count. Impressions are recorded like
// get_slate under the "score_review" lane so the existing
// Feedback/qualified-impression plumbing works unchanged. Byte-identical
// JSON to the Python backend for the same sidecar state.
package main

import "fmt"

// scoreReviewLane is the item lane and impression lane for this op.
const scoreReviewLane = "score_review"

// scoreReviewEligibility is sceneEligibility for the review surface: the
// current_thumb_down reason does NOT exclude. Recommendation lanes hide
// thumb-downed scenes so they are never re-recommended; the score-review
// surface exists to inspect the bottom of the appeal distribution, and the
// scenes the user explicitly disliked are exactly the ones it must show.
// Every other reason (file_unavailable, hard_exclusion, pruning_*,
// not_now, blocked_tag) still excludes.
func scoreReviewEligibility(db dbx, referenceAtMs int64, sceneIDs map[string]bool) (map[string]eligibilityResult, error) {
	eligibility, err := sceneEligibility(db, referenceAtMs, sceneIDs)
	if err != nil {
		return nil, err
	}
	for sceneID, state := range eligibility {
		if state.eligible {
			continue
		}
		reasons := state.reasons[:0]
		for _, reason := range state.reasons {
			if reason != "current_thumb_down" {
				reasons = append(reasons, reason)
			}
		}
		state.reasons = reasons
		state.eligible = len(reasons) == 0
		eligibility[sceneID] = state
	}
	return eligibility, nil
}

func opGetScoreReview(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_score_review",
		func(settings jVal) (jVal, error) { return getScoreReviewBody(pluginDir, payload, settings) })
}

// getScoreReviewBody mirrors backend.py's get_score_review dispatch +
// CuratorAPI.get_score_review.
func getScoreReviewBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	count := argsInt(args, "count", pythonInt(cfg.get("page_size")))
	maxAppeal := argsFloat(args, "max_appeal", 0)
	order := pythonStrOrEmpty(args.get("order"))
	if order == "" {
		order = "asc"
	}
	if order != "asc" && order != "desc" {
		return jvNull(), fmt.Errorf("invalid score review order")
	}
	return getScoreReviewCore(db, config, page, count, maxAppeal, order)
}

// getScoreReviewCore mirrors CuratorAPI.get_score_review after arg coercion.
func getScoreReviewCore(db dbx, config jVal, page, count int64, maxAppeal float64, order string) (jVal, error) {
	if page < 1 || count < 1 || count > 500 {
		return jvNull(), fmt.Errorf("invalid score review page")
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model; run build-model first")
	}
	start := (page - 1) * count
	end := page * count

	total, err := scoreReviewTotal(db, modelID, maxAppeal)
	if err != nil {
		return jvNull(), err
	}
	built, err := scoreReviewLoad(db, modelID, end, maxAppeal, order)
	if err != nil {
		return jvNull(), err
	}
	var selected []*recommendationItem
	if start < int64(len(built.items)) {
		selEnd := minInt64(end, int64(len(built.items)))
		for i := start; i < selEnd; i++ {
			item := *built.items[i]
			item.position = i
			selected = append(selected, &item)
		}
	}
	impressionID := jvStr(uuid4())
	if err := recordImpression(db, impressionID.asString(), scoreReviewLane, modelID, selected, nowMs(), jvNull()); err != nil {
		return jvNull(), err
	}
	items := jvArr()
	for _, item := range selected {
		items.arr = append(items.arr, recommendationItemJSON(item, impressionID))
	}
	return jvObj(
		jvKey("items", items),
		jvKey("total", jvInt(total)),
		jvKey("page_size", jvInt(count)),
		jvKey("has_more", jvBool(total > end)),
		jvKey("page", jvInt(page)),
		jvKey("model_version", jvStr(modelID)),
	), nil
}

// scoreReviewTotal mirrors SlateBuilder.score_review_available_count: the
// count of eligible model_scene_score rows with appeal <= max_appeal,
// applying the same live eligibility as the slate path.
func scoreReviewTotal(db dbx, modelID string, maxAppeal float64) (int64, error) {
	rows, err := db.Query(`SELECT scene_id FROM model_scene_score
WHERE model_id=? AND appeal <= ?`, modelID, maxAppeal)
	if err != nil {
		return 0, err
	}
	sceneIDs := make(map[string]bool)
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return 0, err
		}
		sceneIDs[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	eligibility, err := scoreReviewEligibility(db, nowMs(), sceneIDs)
	if err != nil {
		return 0, err
	}
	total := int64(0)
	for sceneID := range sceneIDs {
		if state, ok := eligibility[sceneID]; ok && state.eligible {
			total++
		}
	}
	return total, nil
}

// scoreReviewRow carries one candidate row from the appeal-ordered scan.
type scoreReviewRow struct {
	sceneID string
}

// scoreReviewLoad mirrors SlateBuilder.score_review: candidates from
// model_scene_score ordered by appeal ASC (tie-break scene_id), filtered
// appeal <= max_appeal, the same live eligibility applied as the slate path,
// hydrated into recommendation items with score-first semantics
// (final_utility = appeal, the score-first zero penalties/bonuses, lane
// "score_review").
func scoreReviewLoad(db dbx, modelID string, count int64, maxAppeal float64, order string) (builtSlate, error) {
	now := nowMs()
	var selectedRows []scoreReviewRow
	offset := int64(0)
	chunkSize := maxInt64(100, count)
	direction := "ASC"
	if order == "desc" {
		direction = "DESC"
	}
	for int64(len(selectedRows)) < count {
		rows, err := db.Query(`SELECT scene_id FROM model_scene_score
WHERE model_id=? AND appeal <= ?
ORDER BY appeal `+direction+`, scene_id
LIMIT ? OFFSET ?`, modelID, maxAppeal, chunkSize, offset)
		if err != nil {
			return builtSlate{}, err
		}
		chunk := make([]scoreReviewRow, 0, chunkSize)
		for rows.Next() {
			var row scoreReviewRow
			if err := rows.Scan(&row.sceneID); err != nil {
				rows.Close()
				return builtSlate{}, err
			}
			chunk = append(chunk, row)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return builtSlate{}, err
		}
		if len(chunk) == 0 {
			break
		}
		offset += int64(len(chunk))
		sceneIDs := make(map[string]bool, len(chunk))
		for _, row := range chunk {
			sceneIDs[row.sceneID] = true
		}
		eligibility, err := scoreReviewEligibility(db, now, sceneIDs)
		if err != nil {
			return builtSlate{}, err
		}
		for _, row := range chunk {
			if state, ok := eligibility[row.sceneID]; ok && state.eligible {
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
		return builtSlate{}, err
	}
	penalties := scoreFirstPenalties()
	bonuses := scoreFirstBonuses()
	items := make([]*recommendationItem, 0, len(selectedRows))
	for position, row := range selectedRows {
		score, ok := scores[row.sceneID]
		if !ok {
			continue
		}
		items = append(items, &recommendationItem{
			sceneID:       row.sceneID,
			lane:          scoreReviewLane,
			sourceLane:    scoreReviewLane,
			subtype:       jvNull(),
			position:      int64(position),
			appeal:        score.appeal,
			currentFit:    score.currentFit,
			confidence:    score.confidence,
			laneValue:     score.appeal,
			finalUtility:  score.appeal,
			penalties:     penalties,
			bonuses:       bonuses,
			components:    score.components,
			neighbors:     score.neighbors,
			eligibility:   score.eligibility,
			qualification: jvObj(),
			reasonIDs:     []string{"eligibility.lane"},
		})
	}
	return builtSlate{
		modelID:     modelID,
		lane:        scoreReviewLane,
		items:       items,
		diagnostics: nil,
		timingsMs:   map[string]int64{"materialized": 1, "selection": 0, "total": 0},
	}, nil
}

// scoreFirstPenalties mirrors the penalties dict the materialized
// score-first read path produces: the score-first ranking JSON with the
// live_cooldown slot filled (0.0 — the score-review lane applies no
// cooldown).
func scoreFirstPenalties() jVal {
	ranking, err := parseJSON([]byte(scoreFirstRankingJSON))
	if err != nil {
		return jvObj()
	}
	penalties := ranking.get("penalties")
	if penalties.kind != jObj {
		return jvObj()
	}
	copy := jVal{kind: jObj, obj: append([]jPair(nil), penalties.obj...)}
	copy.set("live_cooldown", jvFloat(0))
	return copy
}

// scoreFirstBonuses mirrors the bonuses dict of the score-first ranking
// JSON.
func scoreFirstBonuses() jVal {
	ranking, err := parseJSON([]byte(scoreFirstRankingJSON))
	if err != nil {
		return jvObj()
	}
	bonuses := ranking.get("bonuses")
	if bonuses.kind != jObj {
		return jvObj()
	}
	return jVal{kind: jObj, obj: append([]jPair(nil), bonuses.obj...)}
}
