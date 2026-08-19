// Lane classification — a port of curator/ranking/policy.py's LanePolicy:
// percentile ranks over the family components, the Blind Spots context
// (dark studio/tag facets, regularized against the library's play rate),
// and the per-scene best_bets / revisit / stretch / blind_spots
// classification persisted to model_scene_lane. Runs on the model artifact
// connection (reads through the attached core + feature views).
package main

import (
	"context"
	"database/sql"
	"math"
	"sort"
	"strings"
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

// darkFacet mirrors one dark_facets entry.
type darkFacet struct {
	facetType    string
	id           string
	name         string
	libraryCount int64
	playedCount  int64
	darkness     float64
}

// blindSpotSceneData mirrors one scene's precomputed Blind Spots ingredients:
// its dark facets (already sorted by darkness descending, so index 0 is the
// facet lane_value and the diversity rotation both key on) and its content
// feature count (the dark_min_features floor).
type blindSpotSceneData struct {
	darkFacets          []darkFacet
	contentFeatureCount int
}

// darkPoolStats mirrors _blind_spot_context.darkness_of: the regularized
// darkness for one facet's scene set, shrunk toward the library base rate
// (alpha = dark_prior_strength) rather than an unregularized mean, so a
// facet with few scenes does not get an unbounded darkness score just
// because none of its handful of scenes happen to be played yet.
func darkPoolStats(scenes map[string]bool, played map[string]bool, baseRate, alpha float64) (float64, int64, int64) {
	libraryCount := int64(len(scenes))
	var playedCount int64
	for sceneID := range scenes {
		if played[sceneID] {
			playedCount++
		}
	}
	if baseRate <= 0 {
		return 0.0, libraryCount, playedCount
	}
	rate := (float64(playedCount) + alpha*baseRate) / (float64(libraryCount) + alpha)
	darkness := 1 - rate/baseRate
	if darkness < 0 {
		darkness = 0
	}
	if darkness > 1 {
		darkness = 1
	}
	return darkness, libraryCount, playedCount
}

// blindSpotContext mirrors LanePolicy._blind_spot_context: which studio and
// confirmed-tag facets are underexplored relative to the library's overall
// play rate, and how many of each scene's facet types corroborate each
// other. See docs/workpackage-lane-redesign.md ("Blind Spots").
func blindSpotContext(db dbx, sceneIDs map[string]bool, featureVersion string) (map[string]blindSpotSceneData, error) {
	featuresByScene, err := modelStoredFeatures(db, featureVersion, "scene")
	if err != nil {
		return nil, err
	}
	played, err := playedSceneIDs(db)
	if err != nil {
		return nil, err
	}

	contentFeatureCount := map[string]int{}
	tagScenes := map[string]map[string]bool{}
	tagNames := map[string]string{}
	for sceneID, features := range featuresByScene {
		for _, feature := range features {
			if feature.family != "content" {
				continue
			}
			contentFeatureCount[sceneID]++
			metadata := feature.metadata
			reason := metadata.get("role_reason").asString()
			if metadata.get("tag_id").kind == jNull || !strings.HasPrefix(reason, "stashdb_") {
				continue
			}
			if tagScenes[feature.featureID] == nil {
				tagScenes[feature.featureID] = map[string]bool{}
			}
			tagScenes[feature.featureID][sceneID] = true
			name := metadata.get("tag_name").asString()
			if name == "" {
				name = feature.name
			}
			tagNames[feature.featureID] = name
		}
	}

	sceneStudio := map[string]string{}
	studioScenes := map[string]map[string]bool{}
	studioNames := map[string]string{}
	rows, err := db.Query(`
		SELECT s.scene_id, s.studio_id, st.name
		FROM source_scene s
		JOIN source_studio st ON st.studio_id = s.studio_id
		WHERE s.studio_id IS NOT NULL
	`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, studioID string
		var name sql.NullString
		if err := rows.Scan(&sceneID, &studioID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		sceneStudio[sceneID] = studioID
		if studioScenes[studioID] == nil {
			studioScenes[studioID] = map[string]bool{}
		}
		studioScenes[studioID][sceneID] = true
		studioNames[studioID] = name.String
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	totalScenes := maxInt(1, len(featuresByScene))
	playedScenes := 0
	for sceneID := range featuresByScene {
		if played[sceneID] {
			playedScenes++
		}
	}
	baseRate := float64(playedScenes) / float64(totalScenes)
	const alpha = 20.0
	const darkThreshold = 0.55
	const darkMinLibrary = 60
	const darkMaxLibrary = 500

	darkPool := func(pool map[string]map[string]bool) map[string]darkFacet {
		result := map[string]darkFacet{}
		for facetID, scenes := range pool {
			darkness, libraryCount, playedCount := darkPoolStats(scenes, played, baseRate, alpha)
			if darkness >= darkThreshold && libraryCount >= darkMinLibrary && libraryCount <= darkMaxLibrary {
				result[facetID] = darkFacet{
					libraryCount: libraryCount, playedCount: playedCount, darkness: darkness,
				}
			}
		}
		return result
	}
	darkTags := darkPool(tagScenes)
	darkStudios := darkPool(studioScenes)

	result := map[string]blindSpotSceneData{}
	for sceneID := range sceneIDs {
		var facets []darkFacet
		for _, feature := range featuresByScene[sceneID] {
			if feature.family != "content" {
				continue
			}
			dark, ok := darkTags[feature.featureID]
			if !ok {
				continue
			}
			facets = append(facets, darkFacet{
				facetType: "tag", id: feature.featureID, name: tagNames[feature.featureID],
				libraryCount: dark.libraryCount, playedCount: dark.playedCount, darkness: dark.darkness,
			})
		}
		if studioID, ok := sceneStudio[sceneID]; ok {
			if dark, ok := darkStudios[studioID]; ok {
				facets = append(facets, darkFacet{
					facetType: "studio", id: studioID, name: studioNames[studioID],
					libraryCount: dark.libraryCount, playedCount: dark.playedCount, darkness: dark.darkness,
				})
			}
		}
		sort.SliceStable(facets, func(i, j int) bool {
			if facets[i].darkness != facets[j].darkness {
				return facets[i].darkness > facets[j].darkness
			}
			return facets[i].id < facets[j].id
		})
		result[sceneID] = blindSpotSceneData{
			darkFacets: facets, contentFeatureCount: contentFeatureCount[sceneID],
		}
	}
	return result, nil
}

// dormancyRow mirrors one model_entity_dormancy row.
type dormancyRow struct {
	lastPlayedAtMs     int64
	positiveStrength   float64
	playCount          int64
	distinctSceneCount int64
}

// dormantContext mirrors LanePolicy._dormant_context: per-scene strongest
// qualifying dormant entity (a performer, studio, or confirmed tag the user
// used to watch a lot of, hasn't touched in a while, and whose scenes
// model_entity_dormancy shows a real positive history for). now_ms is
// evaluated live, not frozen at build — see
// docs/workpackage-lane-redesign.md ("Dormant", "Evaluated at slate time,
// not frozen at build").
func dormantContext(db dbx, modelID string, sceneIDs map[string]bool, nowMs int64) (map[string]dormantCandidate, error) {
	dormancyRows := map[[2]string]dormancyRow{}
	rows, err := db.Query(`
SELECT entity_type, entity_id, last_played_at_ms, positive_strength, play_count, distinct_scene_count
FROM model_entity_dormancy WHERE model_id=?`, modelID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var entityType, entityID string
		var row dormancyRow
		if err := rows.Scan(&entityType, &entityID, &row.lastPlayedAtMs, &row.positiveStrength,
			&row.playCount, &row.distinctSceneCount); err != nil {
			rows.Close()
			return nil, err
		}
		dormancyRows[[2]string{entityType, entityID}] = row
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(dormancyRows) == 0 {
		return map[string]dormantCandidate{}, nil
	}

	sceneEntities := map[string][][2]string{}
	addEntity := func(sceneID, entityType, entityID string) {
		sceneEntities[sceneID] = append(sceneEntities[sceneID], [2]string{entityType, entityID})
	}
	performerRows, err := db.Query(`SELECT scene_id, performer_id FROM scene_performer`)
	if err != nil {
		return nil, err
	}
	for performerRows.Next() {
		var sceneID, performerID string
		if err := performerRows.Scan(&sceneID, &performerID); err != nil {
			performerRows.Close()
			return nil, err
		}
		addEntity(sceneID, "performer", performerID)
	}
	performerRows.Close()
	if err := performerRows.Err(); err != nil {
		return nil, err
	}
	studioRows, err := db.Query(`SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	for studioRows.Next() {
		var sceneID, studioID string
		if err := studioRows.Scan(&sceneID, &studioID); err != nil {
			studioRows.Close()
			return nil, err
		}
		addEntity(sceneID, "studio", studioID)
	}
	studioRows.Close()
	if err := studioRows.Err(); err != nil {
		return nil, err
	}
	tagRows, err := db.Query(`SELECT scene_id, tag_id FROM scene_tag`)
	if err != nil {
		return nil, err
	}
	for tagRows.Next() {
		var sceneID, tagID string
		if err := tagRows.Scan(&sceneID, &tagID); err != nil {
			tagRows.Close()
			return nil, err
		}
		addEntity(sceneID, "tag", tagID)
	}
	tagRows.Close()
	if err := tagRows.Err(); err != nil {
		return nil, err
	}

	names := map[string]map[string]string{"performer": {}, "studio": {}, "tag": {}}
	loadNames := func(query, entityType string) error {
		rows, err := db.Query(query)
		if err != nil {
			return err
		}
		for rows.Next() {
			var id string
			var name sql.NullString
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return err
			}
			names[entityType][id] = name.String
		}
		rows.Close()
		return rows.Err()
	}
	if err := loadNames(`SELECT performer_id, name FROM source_performer`, "performer"); err != nil {
		return nil, err
	}
	if err := loadNames(`SELECT studio_id, name FROM source_studio`, "studio"); err != nil {
		return nil, err
	}
	if err := loadNames(`SELECT tag_id, name FROM source_tag`, "tag"); err != nil {
		return nil, err
	}

	result := map[string]dormantCandidate{}
	for sceneID := range sceneIDs {
		var best dormantCandidate
		for _, entity := range sceneEntities[sceneID] {
			entityType, entityID := entity[0], entity[1]
			row, ok := dormancyRows[[2]string{entityType, entityID}]
			if !ok {
				continue
			}
			if row.playCount < 3 || row.distinctSceneCount < 2 || row.positiveStrength < 0.10 {
				continue
			}
			daysSincePlayed := math.Max(0.0, float64(nowMs-row.lastPlayedAtMs)/86_400_000)
			dormancy := entityDormancy(daysSincePlayed)
			if dormancy < 0.5 {
				continue
			}
			if !best.found || row.positiveStrength > best.positiveStrength ||
				(row.positiveStrength == best.positiveStrength && entityID < best.entityID) {
				name := names[entityType][entityID]
				if name == "" {
					name = entityID
				}
				best = dormantCandidate{
					found: true, entityType: entityType, entityID: entityID,
					name:             name,
					daysSincePlayed:  daysSincePlayed,
					positiveStrength: row.positiveStrength,
					supportingPlays:  row.playCount,
					dormancy:         dormancy,
				}
			}
		}
		if best.found {
			result[sceneID] = best
		}
	}
	return result, nil
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
// per-scene classification loop (ranks, Blind Spots context, played set).
type laneContext struct {
	contentRanks    map[string]float64
	neighborRanks   map[string]float64
	similarityRanks map[string]float64
	performerRanks  map[string]float64
	studioRanks     map[string]float64
	fitRanks        map[string]float64
	blindSpots      map[string]blindSpotSceneData
	dormant         map[string]dormantCandidate
	played          map[string]bool
}

// dormantCandidate mirrors one scene's strongest qualifying dormant entity.
type dormantCandidate struct {
	found            bool
	entityType       string
	entityID         string
	name             string
	daysSincePlayed  float64
	positiveStrength float64
	supportingPlays  int64
	dormancy         float64
}

// stretchRaw mirrors policy.classify's per-scene stretch_raw entry: the
// ingredients Stretch's lane_value needs, collected before the global
// percentile pass that normalizes anchor_strength and challenge_distance
// (the latter separately per challenge kind).
type stretchRaw struct {
	sceneID           string
	anchorFeatures    []jVal
	challengedFeature jVal
	challengeKind     string
	anchorStrength    float64
	challengeDistance float64
}

// classifyScene computes the best_bets / revisit / blind_spots rows for one
// eligible scene (the LanePolicy.classify per-scene body), plus the deferred
// Stretch ingredients (if the scene qualifies) for the caller's global
// percentile pass. The loop is row-independent: every input is a
// precomputed read-only map, so fixed-chunk parallel processing yields
// identical rows.
func (c *laneContext) classifyScene(sceneID string, score classificationScore) ([]builtLaneClassification, *stretchRaw) {
	var classifications []builtLaneClassification
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
	var stretch *stretchRaw
	stretchContributors := score.components.get("stretch_contributors")
	positivePool := stretchContributors.get("positive").arr
	negativePool := stretchContributors.get("negative").arr
	var anchors []jVal
	for _, item := range positivePool {
		if numberValue(item.get("affinity")) >= 0.015 && numberValue(item.get("confidence")) >= 0.5 {
			anchors = append(anchors, item)
		}
	}
	type challengeCandidate struct {
		item jVal
		kind string
	}
	var challenges []challengeCandidate
	for _, item := range negativePool {
		if numberValue(item.get("affinity")) <= -0.015 && numberValue(item.get("confidence")) >= 0.5 {
			challenges = append(challenges, challengeCandidate{item, "tested_negative"})
		}
	}
	for _, item := range append(append([]jVal{}, positivePool...), negativePool...) {
		if numberValue(item.get("effective_support")) < 0.5 {
			challenges = append(challenges, challengeCandidate{item, "untested"})
		}
	}
	if !bestBet && score.directConfidence < 0.35 && len(anchors) > 0 && len(challenges) > 0 &&
		score.currentFit >= 0.0 {
		best := challenges[0]
		bestAbs := math.Abs(numberValue(best.item.get("value")))
		bestFeatureID := best.item.get("feature_id").asString()
		for _, candidate := range challenges[1:] {
			candidateAbs := math.Abs(numberValue(candidate.item.get("value")))
			candidateFeatureID := candidate.item.get("feature_id").asString()
			if candidateAbs > bestAbs || (candidateAbs == bestAbs && candidateFeatureID > bestFeatureID) {
				best = candidate
				bestAbs = candidateAbs
				bestFeatureID = candidateFeatureID
			}
		}
		var challengeDistance float64
		if best.kind == "tested_negative" {
			challengeDistance = math.Abs(numberValue(best.item.get("affinity"))) * numberValue(best.item.get("confidence"))
		} else {
			challengeDistance = 1 - numberValue(best.item.get("confidence"))
		}
		anchorStrength := 0.0
		for _, item := range anchors {
			anchorStrength += numberValue(item.get("value"))
		}
		stretch = &stretchRaw{
			sceneID:           sceneID,
			anchorFeatures:    anchors,
			challengedFeature: best.item,
			challengeKind:     best.kind,
			anchorStrength:    anchorStrength,
			challengeDistance: challengeDistance,
		}
	}
	blindSpot := c.blindSpots[sceneID]
	facetTypes := map[string]bool{}
	for _, facet := range blindSpot.darkFacets {
		facetTypes[facet.facetType] = true
	}
	if !c.played[sceneID] && blindSpot.contentFeatureCount >= 4 && len(facetTypes) >= 2 {
		maxDarkness := 0.0
		for _, facet := range blindSpot.darkFacets {
			if facet.darkness > maxDarkness {
				maxDarkness = facet.darkness
			}
		}
		blindSpotValue := maxDarkness * (1 + 0.15*float64(len(facetTypes)-1)) *
			score.metadataConfidence * (1 + math.Max(0, score.appeal))
		neverPlayed := true
		for _, facet := range blindSpot.darkFacets {
			if facet.playedCount != 0 {
				neverPlayed = false
				break
			}
		}
		subtype := "under_played"
		if neverPlayed {
			subtype = "never_played"
		}
		darkFacetsJSON := jvArr()
		for _, facet := range blindSpot.darkFacets {
			darkFacetsJSON.arr = append(darkFacetsJSON.arr, jvObj(
				jvKey("facet_type", jvStr(facet.facetType)),
				jvKey("id", jvStr(facet.id)),
				jvKey("name", jvStr(facet.name)),
				jvKey("library_count", jvInt(facet.libraryCount)),
				jvKey("played_count", jvInt(facet.playedCount)),
				jvKey("darkness", jvFloat(facet.darkness)),
			))
		}
		classifications = append(classifications, builtLaneClassification{
			sceneID: sceneID, lane: "blind_spots", subtype: subtype,
			laneValue: blindSpotValue,
			qualification: jvObj(
				jvKey("dark_facets", darkFacetsJSON),
				jvKey("corroborating_types", jvInt(int64(len(facetTypes)))),
			),
		})
	}
	dormant := c.dormant[sceneID]
	if !c.played[sceneID] && dormant.found {
		classifications = append(classifications, builtLaneClassification{
			sceneID: sceneID, lane: "dormant", subtype: dormant.entityType,
			laneValue: dormant.positiveStrength * c.fitRanks[sceneID],
			qualification: jvObj(
				jvKey("dormant_entity", jvObj(
					jvKey("type", jvStr(dormant.entityType)),
					jvKey("id", jvStr(dormant.entityID)),
					jvKey("name", jvStr(dormant.name)),
				)),
				jvKey("days_since_played", jvInt(pyRound(dormant.daysSincePlayed))),
				jvKey("positive_strength", jvFloat(dormant.positiveStrength)),
				jvKey("supporting_plays", jvInt(dormant.supportingPlays)),
				jvKey("dormancy", jvFloat(dormant.dormancy)),
			),
		})
	}
	return classifications, stretch
}

// laneClassify mirrors LanePolicy.classify and persists the rows.
func laneClassify(db dbx, modelID string, featureVersion string, nowMs int64, progress func(processed, total int)) ([]builtLaneClassification, error) {
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
	eligibleSet := map[string]bool{}
	for sceneID := range eligibleScores {
		eligibleSet[sceneID] = true
	}
	blindSpots, err := blindSpotContext(db, eligibleSet, featureVersion)
	if err != nil {
		return nil, err
	}
	dormant, err := dormantContext(db, modelID, eligibleSet, nowMs)
	if err != nil {
		return nil, err
	}
	sceneIDs := sortedStringKeys(eligibleScores)
	total := len(sceneIDs)
	var classifications []builtLaneClassification
	if total > 0 {
		context := &laneContext{
			contentRanks:    contentRanks,
			neighborRanks:   neighborRanks,
			similarityRanks: similarityRanks,
			performerRanks:  performerRanks,
			studioRanks:     studioRanks,
			fitRanks:        fitRanks,
			dormant:         dormant,
			blindSpots:      blindSpots,
			played:          played,
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
		type sceneClassifyResult struct {
			classifications []builtLaneClassification
			stretch         *stretchRaw
		}
		results := parallelChunks(total, nthreads(0), func(start, end int) []sceneClassifyResult {
			out := make([]sceneClassifyResult, 0, end-start)
			for _, sceneID := range sceneIDs[start:end] {
				rows, stretch := context.classifyScene(sceneID, eligibleScores[sceneID])
				out = append(out, sceneClassifyResult{rows, stretch})
				progressReporter.done()
			}
			return out
		})
		<-reporterDone
		stretchBySceneID := map[string]*stretchRaw{}
		for _, result := range results {
			classifications = append(classifications, result.classifications...)
			if result.stretch != nil {
				stretchBySceneID[result.stretch.sceneID] = result.stretch
			}
		}
		// Stretch's lane_value needs a global percentile pass, so it is
		// assembled after the per-scene loop: anchor_strength is normalized
		// across every qualifying scene, while challenge_distance is
		// normalized separately within each challenge kind (tested_negative
		// vs untested), since the two kinds use incomparable distance
		// formulas. See docs/workpackage-lane-redesign.md defect 1.
		anchorValues := map[string]float64{}
		testedNegativeDistances := map[string]float64{}
		untestedDistances := map[string]float64{}
		for sceneID, raw := range stretchBySceneID {
			anchorValues[sceneID] = raw.anchorStrength
			if raw.challengeKind == "tested_negative" {
				testedNegativeDistances[sceneID] = raw.challengeDistance
			} else {
				untestedDistances[sceneID] = raw.challengeDistance
			}
		}
		anchorPercentiles := lanePercentiles(anchorValues)
		challengePercentiles := lanePercentiles(testedNegativeDistances)
		for sceneID, percentile := range lanePercentiles(untestedDistances) {
			challengePercentiles[sceneID] = percentile
		}
		for _, sceneID := range sortedStringKeys(stretchBySceneID) {
			raw := stretchBySceneID[sceneID]
			anchorFeatures := jvArr()
			for _, item := range raw.anchorFeatures {
				anchorFeatures.arr = append(anchorFeatures.arr, jvObj(
					jvKey("feature_id", item.get("feature_id")),
					jvKey("name", item.get("name")),
					jvKey("value", jvFloat(numberValue(item.get("value")))),
				))
			}
			classifications = append(classifications, builtLaneClassification{
				sceneID: sceneID, lane: "stretch", subtype: raw.challengeKind,
				laneValue: anchorPercentiles[sceneID] * challengePercentiles[sceneID],
				qualification: jvObj(
					jvKey("anchor_features", anchorFeatures),
					jvKey("challenged_feature", jvObj(
						jvKey("feature_id", raw.challengedFeature.get("feature_id")),
						jvKey("name", raw.challengedFeature.get("name")),
						jvKey("facet_type", raw.challengedFeature.get("facet_type")),
						jvKey("affinity", jvFloat(numberValue(raw.challengedFeature.get("affinity")))),
						jvKey("confidence", jvFloat(numberValue(raw.challengedFeature.get("confidence")))),
					)),
					jvKey("challenge_kind", jvStr(raw.challengeKind)),
					jvKey("anchor_strength", jvFloat(raw.anchorStrength)),
					jvKey("challenge_distance", jvFloat(raw.challengeDistance)),
				),
			})
		}
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
