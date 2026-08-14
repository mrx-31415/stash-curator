// Lane classification — a port of curator/ranking/policy.py's LanePolicy:
// percentile ranks over the family components, the adventure context
// (coverage gaps, unknown performers/studios), and the per-scene best_bets /
// revisit / discover / adventure classification persisted to
// model_scene_lane. Runs on the model artifact connection (reads through the
// attached core + feature views).
package main

import (
	"context"
	"database/sql"
	"math"
	"sort"
)

// lanePercentiles mirrors policy._percentiles: tied values share the midpoint
// percentile; denominator max(1, n-1).
func lanePercentiles(values map[string]float64) map[string]float64 {
	if len(values) == 0 {
		return map[string]float64{}
	}
	ordered := make([]struct {
		sceneID string
		value   float64
	}, 0, len(values))
	for sceneID, value := range values {
		ordered = append(ordered, struct {
			sceneID string
			value   float64
		}{sceneID, value})
	}
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].value != ordered[j].value {
			return ordered[i].value < ordered[j].value
		}
		return ordered[i].sceneID < ordered[j].sceneID
	})
	denominator := float64(maxInt(1, len(ordered)-1))
	result := map[string]float64{}
	start := 0
	for start < len(ordered) {
		end := start + 1
		for end < len(ordered) && ordered[end].value == ordered[start].value {
			end++
		}
		percentile := (float64(start+end-1) / 2) / denominator
		for _, entry := range ordered[start:end] {
			result[entry.sceneID] = percentile
		}
		start = end
	}
	return result
}

// componentValue mirrors policy._component_value over classification_json.
func componentValue(components jVal, name string) float64 {
	component := components.get(name)
	if component.kind != jObj {
		return 0.0
	}
	value := component.get("value")
	if value.kind != jNum {
		return 0.0
	}
	return numberValue(value)
}

// classificationScore is the classification_data read of one scene.
type classificationScore struct {
	sceneID            string
	directAppeal       float64
	directConfidence   float64
	appeal             float64
	currentFit         float64
	confidence         float64
	metadataConfidence float64
	recovery           float64
	components         jVal
	eligibility        jVal
	neighbors          []jVal
}

// classificationData mirrors RecommendationModelStore.classification_data
// (the artifact schema has classification_json).
func classificationData(db dbx, modelID string) (map[string]classificationScore, error) {
	rows, err := db.Query(`
SELECT model_id, scene_id, direct_appeal, direct_confidence, appeal,
       current_fit, confidence, metadata_confidence, recovery,
       classification_json, eligibility_json
FROM model_scene_score WHERE model_id=? ORDER BY scene_id`, modelID)
	if err != nil {
		return nil, err
	}
	var raw []classificationScore
	for rows.Next() {
		var modelID, sceneID, classificationJSON, eligibilityJSON string
		var directAppeal, directConfidence, appeal, currentFit, confidence, metadataConfidence, recovery float64
		if err := rows.Scan(&modelID, &sceneID, &directAppeal, &directConfidence, &appeal,
			&currentFit, &confidence, &metadataConfidence, &recovery,
			&classificationJSON, &eligibilityJSON); err != nil {
			rows.Close()
			return nil, err
		}
		raw = append(raw, classificationScore{
			sceneID:            sceneID,
			directAppeal:       directAppeal,
			directConfidence:   directConfidence,
			appeal:             appeal,
			currentFit:         currentFit,
			confidence:         confidence,
			metadataConfidence: metadataConfidence,
			recovery:           recovery,
			components:         parseJSONOr(classificationJSON),
			eligibility:        parseJSONOr(eligibilityJSON),
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// Collect rows first, then resolve: the pool has a single connection, so a
	// nested query while this cursor is open would deadlock.
	neighbors, err := modelNeighborsByScene(db, modelID)
	if err != nil {
		return nil, err
	}
	result := map[string]classificationScore{}
	for _, row := range raw {
		row.neighbors = neighbors[row.sceneID]
		result[row.sceneID] = row
	}
	return result, nil
}

// modelNeighborsByScene reads the top-5 neighbors for the classify
// similarity_ranks (store._neighbors_by_scene).
func modelNeighborsByScene(db dbx, modelID string) (map[string][]jVal, error) {
	rows, err := db.Query(`
SELECT scene_id, neighbor_scene_id, similarity, weight, outcome
FROM model_scene_neighbor WHERE model_id=? ORDER BY scene_id, rank`, modelID)
	if err != nil {
		return nil, err
	}
	result := map[string][]jVal{}
	for rows.Next() {
		var sceneID, neighborID string
		var similarity, weight, outcome float64
		if err := rows.Scan(&sceneID, &neighborID, &similarity, &weight, &outcome); err != nil {
			rows.Close()
			return nil, err
		}
		result[sceneID] = append(result[sceneID], jvObj(
			jvKey("scene_id", jvStr(neighborID)),
			jvKey("similarity", jvFloat(similarity)),
			jvKey("weight", jvFloat(weight)),
			jvKey("outcome", jvFloat(outcome)),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// playedSceneIDs mirrors LanePolicy._played_scene_ids.
func playedSceneIDs(db dbx) (map[string]bool, error) {
	rows, err := db.Query(`SELECT DISTINCT scene_id FROM source_play
UNION
SELECT DISTINCT scene_id FROM play_session
WHERE provenance<>'direct_player' OR ` + observedPlaybackSQL)
	if err != nil {
		return nil, err
	}
	result := map[string]bool{}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		result[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// adventureSubtype mirrors LanePolicy._adventure_subtype.
func adventureSubtype(score classificationScore, positives, negatives map[string]float64,
	structure, coverageRank float64) string {
	if structure > 0.015 {
		return "structured_combination_challenge"
	}
	if len(positives) > 0 && len(negatives) > 0 {
		return "model_disagreement"
	}
	if len(positives) > 0 && score.confidence < 0.45 {
		return "anchored_model_gap"
	}
	if coverageRank >= 0.65 || (score.metadataConfidence >= 0.30 && score.confidence < 0.25) {
		return "under_covered_island"
	}
	return "pure_probe"
}

// adventureContext mirrors LanePolicy._adventure_context.
func adventureContext(db dbx, modelID string, sceneIDs map[string]bool,
	vectors map[string]map[string]float64) (map[string]float64, map[string]float64, map[string]float64, error) {
	played, err := playedSceneIDs(db)
	if err != nil {
		return nil, nil, nil, err
	}
	libraryCount := map[string]int64{}
	playedCount := map[string]int64{}
	for sceneID, vector := range vectors {
		for feature := range vector {
			libraryCount[feature]++
			if played[sceneID] {
				playedCount[feature]++
			}
		}
	}
	totalScenes := maxInt(1, len(vectors))
	playedScenes := int64(len(played))
	gaps := map[string]float64{}
	for sceneID := range sceneIDs {
		vector := vectors[sceneID]
		var weightedGap, weight float64
		for _, feature := range sortedStringKeys(vector) {
			value := vector[feature]
			expected := float64(libraryCount[feature]) * float64(playedScenes) / float64(totalScenes)
			ratio := (expected + 2) / (float64(playedCount[feature]) + 2)
			weightedGap += math.Min(3.0, math.Log1p(ratio)) * value
			weight += value
		}
		if weight != 0 {
			gaps[sceneID] = weightedGap / weight
		} else {
			gaps[sceneID] = 0.0
		}
	}
	coverageRanks := lanePercentiles(gaps)
	performers := map[string][]string{}
	rows, err := db.Query(`SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, position`)
	if err != nil {
		return nil, nil, nil, err
	}
	for rows.Next() {
		var sceneID, performerID string
		if err := rows.Scan(&sceneID, &performerID); err != nil {
			rows.Close()
			return nil, nil, nil, err
		}
		performers[sceneID] = append(performers[sceneID], performerID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, nil, err
	}
	knownPerformers := map[string]bool{}
	for sceneID := range played {
		for _, performer := range performers[sceneID] {
			knownPerformers[performer] = true
		}
	}
	unknownPerformers := map[string]float64{}
	for sceneID := range sceneIDs {
		if len(performers[sceneID]) == 0 {
			unknownPerformers[sceneID] = 1.0
			continue
		}
		var unknown float64
		for _, performer := range performers[sceneID] {
			if !knownPerformers[performer] {
				unknown++
			}
		}
		unknownPerformers[sceneID] = unknown / float64(len(performers[sceneID]))
	}
	sceneStudios := map[string]string{}
	rows, err = db.Query(`SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL`)
	if err != nil {
		return nil, nil, nil, err
	}
	for rows.Next() {
		var sceneID, studioID string
		if err := rows.Scan(&sceneID, &studioID); err != nil {
			rows.Close()
			return nil, nil, nil, err
		}
		sceneStudios[sceneID] = studioID
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, nil, err
	}
	knownStudios := map[string]bool{}
	for sceneID := range played {
		if studioID, ok := sceneStudios[sceneID]; ok {
			knownStudios[studioID] = true
		}
	}
	unknownStudios := map[string]float64{}
	for sceneID := range sceneIDs {
		studioID, ok := sceneStudios[sceneID]
		if !ok || !knownStudios[studioID] {
			unknownStudios[sceneID] = 1.0
		} else {
			unknownStudios[sceneID] = 0.0
		}
	}
	return coverageRanks, unknownPerformers, unknownStudios, nil
}

// builtLaneClassification mirrors LaneClassification.
type builtLaneClassification struct {
	sceneID       string
	lane          string
	subtype       string // "" = None
	laneValue     float64
	qualification jVal
}

// laneContext carries the row-independent precomputed inputs for the
// per-scene classification loop (ranks, adventure context, played set).
type laneContext struct {
	contentRanks      map[string]float64
	neighborRanks     map[string]float64
	similarityRanks   map[string]float64
	performerRanks    map[string]float64
	studioRanks       map[string]float64
	fitRanks          map[string]float64
	coverageRanks     map[string]float64
	unknownPerformers map[string]float64
	unknownStudios    map[string]float64
	played            map[string]bool
}

// classifyScene computes the best_bets / revisit / discover / adventure
// rows for one eligible scene (the LanePolicy.classify per-scene body). The
// loop is row-independent: every input is a precomputed read-only map, so
// fixed-chunk parallel processing yields identical rows.
func (c *laneContext) classifyScene(sceneID string, score classificationScore) []builtLaneClassification {
	var classifications []builtLaneClassification
	reusable := map[string]float64{
		"content":              componentValue(score.components, "content"),
		"content_neighbor":     componentValue(score.components, "content_neighbor"),
		"performer_identity":   componentValue(score.components, "performer_identity"),
		"performer_similarity": componentValue(score.components, "performer_similarity"),
		"studio":               componentValue(score.components, "studio"),
		"structure":            componentValue(score.components, "structure"),
	}
	positives := map[string]float64{}
	negatives := map[string]float64{}
	for family, value := range reusable {
		if value >= 0.025 {
			positives[family] = value
		} else if value <= -0.025 {
			negatives[family] = value
		}
	}
	strongestAnchor := 0.0
	for _, value := range positives {
		if value > strongestAnchor {
			strongestAnchor = value
		}
	}
	contentRank := c.contentRanks[sceneID]
	neighborRank := c.neighborRanks[sceneID]
	similarityRank := c.similarityRanks[sceneID]
	performerRank := c.performerRanks[sceneID]
	studioRank := c.studioRanks[sceneID]
	relevance := (0.32*neighborRank + 0.10*similarityRank + 0.28*performerRank +
		0.20*contentRank + 0.10*studioRank) * (0.90 + 0.10*score.metadataConfidence)
	corroborated := neighborRank >= 0.60 && math.Max(performerRank, contentRank) >= 0.60
	directReliable := score.directAppeal > 0.10 && score.directConfidence >= 0.50
	bestBet := score.currentFit >= 0.18 && score.confidence >= 0.30 &&
		score.metadataConfidence >= 0.35 && relevance >= 0.60 &&
		(corroborated || directReliable) && !c.played[sceneID]
	if bestBet {
		classifications = append(classifications, builtLaneClassification{
			sceneID: sceneID, lane: "best_bets",
			laneValue: 0.55*relevance + 0.25*c.fitRanks[sceneID] + 0.20*score.confidence,
			qualification: jvObj(
				jvKey("current_fit", jvFloat(score.currentFit)),
				jvKey("confidence", jvFloat(score.confidence)),
				jvKey("metadata_confidence", jvFloat(score.metadataConfidence)),
				jvKey("relevance", jvFloat(relevance)),
				jvKey("content_percentile", jvFloat(contentRank)),
				jvKey("neighbor_percentile", jvFloat(neighborRank)),
				jvKey("neighbor_similarity_percentile", jvFloat(similarityRank)),
				jvKey("performer_percentile", jvFloat(performerRank)),
				jvKey("studio_percentile", jvFloat(studioRank)),
				jvKey("corroborated", jvBool(corroborated)),
				jvKey("direct_reliable", jvBool(directReliable)),
				jvKey("unseen", jvBool(true)),
			),
		})
	}
	signals := []string{}
	direct := score.components.get("direct")
	if direct.kind == jObj {
		for _, item := range direct.get("signals").arr {
			signals = append(signals, item.asString())
		}
	}
	durable := false
	for _, signal := range signals {
		if signal == "o" || signal == "thumb_up" || signal == "repeat" || signal == "scene_rating" || signal == "curation_rating" {
			durable = true
			break
		}
	}
	if score.directAppeal > 0.10 && score.directConfidence >= 0.35 &&
		score.recovery >= 0.10 && durable && c.played[sceneID] {
		durableSignals := jvArr()
		seen := map[string]bool{}
		for _, signal := range signals {
			if !seen[signal] {
				seen[signal] = true
				durableSignals.arr = append(durableSignals.arr, jvStr(signal))
			}
		}
		sort.SliceStable(durableSignals.arr, func(i, j int) bool {
			return durableSignals.arr[i].asString() < durableSignals.arr[j].asString()
		})
		classifications = append(classifications, builtLaneClassification{
			sceneID: sceneID, lane: "revisit",
			laneValue: score.directAppeal*score.directConfidence*score.recovery +
				0.25*score.currentFit,
			qualification: jvObj(
				jvKey("direct_appeal", jvFloat(score.directAppeal)),
				jvKey("direct_confidence", jvFloat(score.directConfidence)),
				jvKey("recovery", jvFloat(score.recovery)),
				jvKey("durable_signals", durableSignals),
			),
		})
	}
	if !bestBet && score.directConfidence < 0.35 && strongestAnchor >= 0.08 {
		subtype := "adjacent"
		if len(negatives) == 1 {
			subtype = "stretch"
		} else if score.confidence < 0.35 || score.metadataConfidence < 0.30 {
			subtype = "frontier"
		}
		var challenged jVal = jvNull()
		if len(negatives) > 0 {
			bestKey := ""
			bestValue := 0.0
			for family, value := range negatives {
				if bestKey == "" || value < bestValue {
					bestKey = family
					bestValue = value
				}
			}
			challenged = jvStr(bestKey)
		}
		classifications = append(classifications, builtLaneClassification{
			sceneID: sceneID, lane: "discover", subtype: subtype,
			laneValue: score.currentFit + 0.12*(1-score.confidence) + 0.5*strongestAnchor,
			qualification: jvObj(
				jvKey("positive_anchors", floatMapJVal(positives)),
				jvKey("negative_assumptions", floatMapJVal(negatives)),
				jvKey("challenged_assumption", challenged),
				jvKey("uncertainty", jvFloat(1-score.confidence)),
			),
		})
	}
	subtype := adventureSubtype(score, positives, negatives,
		reusable["structure"], c.coverageRanks[sceneID])
	distanceRank := 1 - similarityRank
	adventureValue := 0.38*c.coverageRanks[sceneID] + 0.25*distanceRank +
		0.17*c.unknownPerformers[sceneID] + 0.08*c.unknownStudios[sceneID] +
		0.12*score.metadataConfidence
	classifications = append(classifications, builtLaneClassification{
		sceneID: sceneID, lane: "adventure", subtype: subtype,
		laneValue: adventureValue,
		qualification: jvObj(
			jvKey("positive_anchors", floatMapJVal(positives)),
			jvKey("component_disagreement", floatMapJVal(negatives)),
			jvKey("uncertainty", jvFloat(1-score.confidence)),
			jvKey("coverage_gap_percentile", jvFloat(c.coverageRanks[sceneID])),
			jvKey("content_distance_percentile", jvFloat(distanceRank)),
			jvKey("unknown_performer_share", jvFloat(c.unknownPerformers[sceneID])),
			jvKey("unknown_studio", jvFloat(c.unknownStudios[sceneID])),
		),
	})
	return classifications
}

// laneClassify mirrors LanePolicy.classify and persists the rows.
func laneClassify(db dbx, modelID string, featureVersion string, progress func(processed, total int)) ([]builtLaneClassification, error) {
	scores, err := classificationData(db, modelID)
	if err != nil {
		return nil, err
	}
	eligibleScores := map[string]classificationScore{}
	for sceneID, score := range scores {
		if score.eligibility.get("eligible").truthy() {
			eligibleScores[sceneID] = score
		}
	}
	played, err := playedSceneIDs(db)
	if err != nil {
		return nil, err
	}
	contentRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 { return componentValue(s.components, "content") }))
	neighborRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 { return componentValue(s.components, "content_neighbor") }))
	similarityRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 {
		best := 0.0
		for _, item := range s.neighbors {
			if v := numberValue(item.get("similarity")); v > best {
				best = v
			}
		}
		return best
	}))
	performerRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 {
		return componentValue(s.components, "performer_identity") + componentValue(s.components, "performer_similarity")
	}))
	studioRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 { return componentValue(s.components, "studio") }))
	fitRanks := lanePercentiles(mapValues(eligibleScores, func(s classificationScore) float64 { return s.currentFit }))
	vectors, err := sceneContentVectorsAll(db, featureVersion)
	if err != nil {
		return nil, err
	}
	eligibleSet := map[string]bool{}
	for sceneID := range eligibleScores {
		eligibleSet[sceneID] = true
	}
	coverageRanks, unknownPerformers, unknownStudios, err := adventureContext(db, modelID, eligibleSet, vectors)
	if err != nil {
		return nil, err
	}
	sceneIDs := sortedStringKeys(eligibleScores)
	total := len(sceneIDs)
	var classifications []builtLaneClassification
	if total > 0 {
		context := &laneContext{
			contentRanks:      contentRanks,
			neighborRanks:     neighborRanks,
			similarityRanks:   similarityRanks,
			performerRanks:    performerRanks,
			studioRanks:       studioRanks,
			fitRanks:          fitRanks,
			coverageRanks:     coverageRanks,
			unknownPerformers: unknownPerformers,
			unknownStudios:    unknownStudios,
			played:            played,
		}
		// Each scene's classification depends only on its own score and the
		// precomputed ranks, so the loop is row-independent: run it in fixed
		// chunks (the kernel pattern) with progress ticks emitted in scene
		// order regardless of worker interleaving.
		progressReporter := newOrderedProgress()
		reporterDone := make(chan struct{})
		go func() {
			defer close(reporterDone)
			progressReporter.wait(reportPoints(total), func(completed int) {
				if progress != nil {
					progress(completed, maxInt(1, total))
				}
			})
		}()
		classifications = parallelChunks(total, nthreads(0), func(start, end int) []builtLaneClassification {
			var out []builtLaneClassification
			for _, sceneID := range sceneIDs[start:end] {
				out = append(out, context.classifyScene(sceneID, eligibleScores[sceneID])...)
				progressReporter.done()
			}
			return out
		})
		<-reporterDone
	}
	if progress != nil && total == 0 {
		progress(1, 1)
	}
	if err := lanePersist(db, modelID, classifications, eligibleScores); err != nil {
		return nil, err
	}
	return classifications, nil
}

// lanePersist mirrors LanePolicy._persist.
func lanePersist(db dbx, modelID string, classifications []builtLaneClassification,
	eligibleScores map[string]classificationScore) error {
	return withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `DELETE FROM model_scene_lane WHERE model_id=?`, modelID); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx, `DELETE FROM model_lane_candidate_cache WHERE model_id=?`, modelID); err != nil {
			return err
		}
		for _, item := range classifications {
			subtype := any(nil)
			if item.subtype != "" {
				subtype = item.subtype
			}
			if _, err := conn.ExecContext(ctx, `
INSERT INTO model_scene_lane(
    model_id, scene_id, lane, subtype, lane_value, qualification_json, appeal
) VALUES (?, ?, ?, ?, ?, ?, ?)`,
				modelID, item.sceneID, item.lane, subtype, item.laneValue,
				item.qualification.marshalSortedKeys(),
				eligibleScores[item.sceneID].appeal); err != nil {
				return err
			}
		}
		return nil
	})
}

// mapValues builds the percentile input dict for a classifier over the
// eligible scores.
func mapValues(scores map[string]classificationScore, fn func(classificationScore) float64) map[string]float64 {
	result := make(map[string]float64, len(scores))
	for sceneID, score := range scores {
		result[sceneID] = fn(score)
	}
	return result
}

// floatMapJVal builds an ordered jVal object from a float map (sorted keys
// for determinism; Python dict insertion order is the family iteration
// order, which is deterministic here).
func floatMapJVal(values map[string]float64) jVal {
	obj := jvObj()
	for _, key := range sortedStringKeys(values) {
		obj.set(key, jvFloat(values[key]))
	}
	return obj
}
