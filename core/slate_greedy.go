// The non-materialized slate path — a port of SlateBuilder.recommend's
// greedy recompute branch (curator/ranking/slate.py): prepared-slate cache,
// lane candidate cache, live eligibility filtering, and the deterministic
// greedy selection with variety penalties. Runs when a model's lanes are not
// materialized or exploration is non-zero.
package main

import (
	"database/sql"
	"fmt"
	"math"
	"sort"
)

// ranking config constants (curator/config.py RankingConfig + patterns).
const (
	rankingHistorySize             = 50
	rankingPerformerRepeatPenalty  = 0.06
	rankingStudioPenalty           = 0.08
	rankingContentPenalty          = 0.14
	rankingHistoryPerformerPenalty = 0.04
	rankingHistoryStudioPenalty    = 0.03
	rankingHistoryContentPenalty   = 0.05
	rankingUncoveredContentBonus   = 0.03
	rankingStretchPerDimension     = 1
	rankingBlindSpotPerFacet       = 1
	rankingDormantPerEntity        = 1
)

var forYouPattern = []string{
	"best_bets", "best_bets", "revisit", "best_bets", "stretch",
	"best_bets", "best_bets", "stretch", "best_bets", "revisit",
	"best_bets", "stretch", "best_bets", "best_bets", "revisit",
	"best_bets", "stretch", "best_bets", "blind_spots", "dormant",
}

var familiarPattern = []string{
	"best_bets", "best_bets", "revisit", "best_bets", "stretch",
	"best_bets", "best_bets", "revisit", "best_bets", "best_bets",
}

var adventurousPattern = []string{
	"best_bets", "best_bets", "revisit", "stretch", "best_bets",
	"stretch", "blind_spots", "best_bets", "stretch", "blind_spots",
}


// greedyCandidate mirrors slate._Candidate.
type greedyCandidate struct {
	sceneID       string
	lane          string
	subtype       string
	laneValue     float64
	qualification jVal
	performers    []string
	studioGroup   string // "" when none
	content       map[string]float64
	contentOrder  []string // insertion order (SQL/JSON order) for serialization
}

// stretchDimension mirrors _stretch_dimension: the challenged feature id, for
// the per-dimension Stretch rotation.
func stretchDimension(c *greedyCandidate) string {
	challenged := c.qualification.get("challenged_feature")
	if challenged.kind != jObj {
		return ""
	}
	return challenged.get("feature_id").asString()
}

// stretchDimensions mirrors the sorted-distinct-dimension precompute shared
// by _build_order and recommend()'s greedy loop. Gated on enabled (varied in
// buildOrdering, diversityEnabled in the greedy loop): stretch is a
// QUERIED_SCORE_FIRST_LANES member, so its score_first ordering is never
// materialized through buildOrdering (only answered live by a plain
// laneValue-sorted query) — this rotation must stay out of that path so the
// two stay equivalent.
func stretchDimensions(lane string, candidates []*greedyCandidate, enabled bool) []string {
	if lane != "stretch" || !enabled {
		return nil
	}
	seen := map[string]bool{}
	for _, c := range candidates {
		if dim := stretchDimension(c); dim != "" {
			seen[dim] = true
		}
	}
	dims := make([]string, 0, len(seen))
	for dim := range seen {
		dims = append(dims, dim)
	}
	sort.Strings(dims)
	return dims
}

// blindSpotFacet mirrors _blind_spot_facet: the strongest dark facet's id,
// for the per-facet Blind Spots rotation. classifyScene sorts dark_facets by
// darkness descending, so the first entry is the facet driving lane_value
// (lane_value uses max(darkness)); the same facet doubles as the rotation
// key.
func blindSpotFacet(c *greedyCandidate) string {
	facets := c.qualification.get("dark_facets")
	if facets.kind != jArr || len(facets.arr) == 0 {
		return ""
	}
	top := facets.arr[0]
	if top.kind != jObj {
		return ""
	}
	return top.get("id").asString()
}

// blindSpotFacets mirrors the sorted-distinct-facet precompute shared by
// buildOrdering and recommend()'s greedy loop. Unconditional (no varied /
// diversityEnabled gate like stretchDimensions): blind_spots is not a
// QUERIED_SCORE_FIRST_LANES member, so there is no live SQL path this needs
// to stay equivalent to.
func blindSpotFacets(lane string, candidates []*greedyCandidate) []string {
	if lane != "blind_spots" {
		return nil
	}
	seen := map[string]bool{}
	for _, c := range candidates {
		if facet := blindSpotFacet(c); facet != "" {
			seen[facet] = true
		}
	}
	facets := make([]string, 0, len(seen))
	for facet := range seen {
		facets = append(facets, facet)
	}
	sort.Strings(facets)
	return facets
}

// dormantEntity mirrors _dormant_entity: the dormant entity's id, for the
// per-entity Dormant rotation.
func dormantEntity(c *greedyCandidate) string {
	entity := c.qualification.get("dormant_entity")
	if entity.kind != jObj {
		return ""
	}
	return entity.get("id").asString()
}

// dormantEntities mirrors the sorted-distinct-entity precompute shared by
// buildOrdering and recommend()'s greedy loop. Unconditional, like
// blindSpotFacets: dormant is not a QUERIED_SCORE_FIRST_LANES member either.
func dormantEntities(lane string, candidates []*greedyCandidate) []string {
	if lane != "dormant" {
		return nil
	}
	seen := map[string]bool{}
	for _, c := range candidates {
		if entity := dormantEntity(c); entity != "" {
			seen[entity] = true
		}
	}
	entities := make([]string, 0, len(seen))
	for entity := range seen {
		entities = append(entities, entity)
	}
	sort.Strings(entities)
	return entities
}

// recommendGreedy mirrors SlateBuilder.recommend's recompute branch.
// sceneFilter, when non-nil, additionally gates the live candidate pool
// (get_slate's include/exclude tag, performer, studio, and gender filters);
// the prepared-slate cache (a previous unfiltered recommend()'s saved
// result) is bypassed on both read and write when a filter is active, since
// it isn't filter-keyed and would otherwise leak an unfiltered slate into a
// filtered response or vice versa.
func recommendGreedy(db dbx, modelID, lane string, count int64, diversityEnabled bool, exploration float64, sceneFilter func(string) bool) (builtSlate, error) {
	var preparedSlate *builtSlate
	if exploration == 0 && sceneFilter == nil {
		slate, ok, err := loadPreparedSlate(db, modelID, lane, count, diversityEnabled)
		if err != nil {
			return builtSlate{}, err
		}
		if ok {
			if slate != nil && int64(len(slate.items)) >= count {
				return *slate, nil
			}
			preparedSlate = slate
		}
	}
	sourceLanes := map[string]bool{lane: true}
	if lane == "for_you" {
		for _, l := range forYouPattern {
			sourceLanes[l] = true
		}
		if exploration != 0 {
			pattern := familiarPattern
			if exploration > 0 {
				pattern = adventurousPattern
			}
			for _, l := range pattern {
				sourceLanes[l] = true
			}
		}
	}
	candidates, err := loadCandidates(db, modelID, sourceLanes)
	if err != nil {
		return builtSlate{}, err
	}
	now := nowMs()
	candidateIDs := make(map[string]bool, len(candidates))
	for _, c := range candidates {
		candidateIDs[c.sceneID] = true
	}
	eligibility, err := sceneEligibility(db, now, candidateIDs)
	if err != nil {
		return builtSlate{}, err
	}
	// recommend()'s direct_plays query has no OBSERVED_PLAYBACK_SQL filter
	// (unlike _direct_play_filters).
	directPlays := make(map[string]int64)
	rows, err := db.Query(`SELECT scene_id, max(ended_at_ms) AS last_played FROM play_session
WHERE provenance='direct_player' GROUP BY scene_id`)
	if err != nil {
		return builtSlate{}, err
	}
	for rows.Next() {
		var sceneID string
		var lastPlayed int64
		if err := rows.Scan(&sceneID, &lastPlayed); err != nil {
			return builtSlate{}, err
		}
		directPlays[sceneID] = lastPlayed
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return builtSlate{}, err
	}
	unrecovered := make(map[string]bool)
	for sceneID, playedAt := range directPlays {
		days := float64(now-playedAt) / 86_400_000
		if days < 0 {
			days = 0
		}
		if sceneRecovery(days) < 0.10 {
			unrecovered[sceneID] = true
		}
	}
	live := make([]*greedyCandidate, 0, len(candidates))
	for _, c := range candidates {
		state, ok := eligibility[c.sceneID]
		if !ok {
			state = eligibilityResult{}
		}
		_, played := directPlays[c.sceneID]
		if !state.eligible ||
			(c.lane == "best_bets" && played) ||
			(c.lane == "revisit" && unrecovered[c.sceneID]) ||
			(sceneFilter != nil && !sceneFilter(c.sceneID)) {
			continue
		}
		live = append(live, c)
	}
	liveFit, liveCooldown, err := liveCurrentFit(db, modelID, directPlayFilter{plays: directPlays}, now)
	if err != nil {
		return builtSlate{}, err
	}
	candidateLookup := make(map[string]*greedyCandidate, len(live))
	for _, c := range live {
		candidateLookup[c.sceneID+"\x00"+c.lane] = c
	}
	var prefixItems []*recommendationItem
	if preparedSlate != nil {
		for _, item := range preparedSlate.items {
			if _, ok := candidateLookup[item.sceneID+"\x00"+item.sourceLane]; ok {
				prefixItems = append(prefixItems, item)
			}
		}
	}
	selected := make([]*greedyCandidate, 0, len(prefixItems))
	for _, item := range prefixItems {
		selected = append(selected, candidateLookup[item.sceneID+"\x00"+item.sourceLane])
	}
	var selectedUtilities []utility
	var diagnostics []string

	// history context (diversity on): performers, studios, content vectors.
	historyPerformers := map[string]bool{}
	historyStudios := map[string]bool{}
	var historyVectors []map[string]float64
	if diversityEnabled {
		hp, hs, hv, err := historyContext(db, candidates)
		if err != nil {
			return builtSlate{}, err
		}
		historyPerformers, historyStudios, historyVectors = hp, hs, hv
	}
	historySimilarities := make(map[string]float64)
	if diversityEnabled && len(historyVectors) > 0 {
		for _, c := range candidates {
			best := 0.0
			for _, vector := range historyVectors {
				best = mathMax(best, cosine(c.content, vector))
			}
			historySimilarities[c.sceneID] = best
		}
	}
	selectedSceneIDs := make(map[string]bool, len(selected))
	for _, c := range selected {
		selectedSceneIDs[c.sceneID] = true
	}
	seenPerformers := map[string]bool{}
	for _, c := range selected {
		for _, p := range c.performers {
			seenPerformers[p] = true
		}
	}
	seenStudios := map[string]bool{}
	for _, c := range selected {
		if c.studioGroup != "" {
			seenStudios[c.studioGroup] = true
		}
	}
	coveredContent := map[string]bool{}
	for _, c := range selected {
		for name := range c.content {
			coveredContent[name] = true
		}
	}
	// _pair_similarities mirrors the per-recommend memoization; the cached
	// value keeps the FIRST call's left/right direction, like Python.
	pairSimilarities := make(map[string]float64)
	pairSim := func(left, right *greedyCandidate) float64 {
		var key string
		if left.sceneID <= right.sceneID {
			key = left.sceneID + "\x00" + right.sceneID
		} else {
			key = right.sceneID + "\x00" + left.sceneID
		}
		if v, ok := pairSimilarities[key]; ok {
			return v
		}
		v := cosine(left.content, right.content)
		pairSimilarities[key] = v
		return v
	}
	contentSimilarities := make(map[string]float64)
	if diversityEnabled {
		for _, c := range candidates {
			best := 0.0
			for _, previous := range selected {
				best = mathMax(best, pairSim(c, previous))
			}
			contentSimilarities[c.sceneID] = best
		}
	}

	// At most stretch_per_dimension card per challenged dimension per page —
	// mirrors buildOrdering's rotation for this greedy path's own separate
	// selection loop (the live-recompute / filtered case).
	dimensions := stretchDimensions(lane, live, diversityEnabled)
	// At most blind_spot_per_facet card per dark facet per page — unconditional,
	// see blindSpotFacets.
	facets := blindSpotFacets(lane, live)
	// At most dormant_per_entity card per dormant entity per page — same
	// reasoning as facets above.
	entities := dormantEntities(lane, live)
	for position := int64(len(selected)); position < count; position++ {
		targetLane := slateTarget(lane, position, exploration)
		targetDimension := ""
		if lane == "stretch" && len(dimensions) > 0 {
			targetDimension = dimensions[(int(position)/maxInt(1, rankingStretchPerDimension))%len(dimensions)]
		}
		targetFacet := ""
		if lane == "blind_spots" && len(facets) > 0 {
			targetFacet = facets[(int(position)/maxInt(1, rankingBlindSpotPerFacet))%len(facets)]
		}
		targetEntity := ""
		if lane == "dormant" && len(entities) > 0 {
			targetEntity = entities[(int(position)/maxInt(1, rankingDormantPerEntity))%len(entities)]
		}
		remaining := make([]*greedyCandidate, 0, len(live))
		for _, c := range live {
			if !selectedSceneIDs[c.sceneID] {
				remaining = append(remaining, c)
			}
		}
		preferred := make([]*greedyCandidate, 0, len(remaining))
		for _, c := range remaining {
			if c.lane == targetLane &&
				(targetDimension == "" || stretchDimension(c) == targetDimension) &&
				(targetFacet == "" || blindSpotFacet(c) == targetFacet) &&
				(targetEntity == "" || dormantEntity(c) == targetEntity) {
				preferred = append(preferred, c)
			}
		}
		var pool []*greedyCandidate
		if len(preferred) > 0 {
			pool = preferred
		} else {
			pool = make([]*greedyCandidate, 0, len(remaining))
			for _, c := range remaining {
				if c.lane == targetLane {
					pool = append(pool, c)
				}
			}
			if len(pool) == 0 {
				pool = remaining
			}
		}
		type ranked struct {
			final float64
			scene string
			cand  *greedyCandidate
			util  utility
		}
		rankedList := make([]ranked, 0, len(pool))
		for _, c := range pool {
			u, ok := greedyUtility(c, selected, diversityEnabled, historyPerformers, historyStudios, seenPerformers, seenStudios, coveredContent, historyVectors, historySimilarities, contentSimilarities[c.sceneID], liveCooldown)
			if !ok {
				continue
			}
			rankedList = append(rankedList, ranked{final: u.final, scene: c.sceneID, cand: c, util: u})
		}
		if len(rankedList) == 0 {
			// relax_adjacent_when_exhausted is False in the default config, so
			// the relaxation branch is unreachable with the shipped config.
			diagnostics = append(diagnostics, fmt.Sprintf("position %d: candidate pool exhausted", position))
			break
		}
		best := rankedList[0]
		for _, r := range rankedList[1:] {
			if r.final > best.final || (r.final == best.final && r.scene < best.scene) {
				best = r
			}
		}
		chosen := best.cand
		selected = append(selected, chosen)
		selectedSceneIDs[chosen.sceneID] = true
		selectedUtilities = append(selectedUtilities, best.util)
		if diversityEnabled {
			for _, p := range chosen.performers {
				seenPerformers[p] = true
			}
			if chosen.studioGroup != "" {
				seenStudios[chosen.studioGroup] = true
			}
			for name := range chosen.content {
				coveredContent[name] = true
			}
			for _, c := range remaining {
				if selectedSceneIDs[c.sceneID] {
					continue
				}
				contentSimilarities[c.sceneID] = mathMax(contentSimilarities[c.sceneID], pairSim(c, chosen))
			}
		}
	}

	newSelected := selected[len(prefixItems):]
	newSceneIDs := make(map[string]bool, len(newSelected))
	for _, c := range newSelected {
		newSceneIDs[c.sceneID] = true
	}
	scores, err := modelScores(db, modelID, newSceneIDs)
	if err != nil {
		return builtSlate{}, err
	}
	items := make([]*recommendationItem, 0, len(selected))
	items = append(items, prefixItems...)
	for offset, chosen := range newSelected {
		position := int64(len(prefixItems) + offset)
		score, ok := scores[chosen.sceneID]
		if !ok {
			continue
		}
		util := selectedUtilities[offset]
		reasons := []string{"eligibility.lane"}
		for _, pair := range util.penalties.obj {
			if pair.val.kind == jNum && floatValue(pair.val) > 0 {
				reasons = append(reasons, "diversity."+pair.key)
			}
		}
		currentFit := score.currentFit
		if v, ok := liveFit[chosen.sceneID]; ok {
			currentFit = v
		}
		items = append(items, &recommendationItem{
			sceneID:       chosen.sceneID,
			lane:          lane,
			sourceLane:    chosen.lane,
			subtype:       optString(chosen.subtype),
			position:      position,
			appeal:        score.appeal,
			currentFit:    currentFit,
			confidence:    score.confidence,
			laneValue:     chosen.laneValue,
			finalUtility:  util.final,
			penalties:     util.penalties,
			bonuses:       util.bonuses,
			components:    score.components,
			neighbors:     score.neighbors,
			eligibility:   score.eligibility,
			qualification: chosen.qualification,
			reasonIDs:     reasons,
		})
	}
	slate := builtSlate{
		modelID:     modelID,
		lane:        lane,
		items:       items,
		diagnostics: diagnostics,
		timingsMs: map[string]int64{
			"classifications": 0, "candidates": 0, "eligibility": 0,
			"history": 0, "selection": 0, "items": 0, "total": 0,
		},
	}
	if exploration == 0 && sceneFilter == nil {
		if err := savePreparedSlate(db, modelID, lane, diversityEnabled, &slate); err != nil {
			return builtSlate{}, err
		}
	}
	return slate, nil
}

func optString(s string) jVal {
	if s == "" {
		return jvNull()
	}
	return jvStr(s)
}

// slateTarget mirrors SlateBuilder._target.
func slateTarget(lane string, position int64, exploration float64) string {
	if lane == "for_you" {
		base := forYouPattern
		alternative := familiarPattern
		if exploration > 0 {
			alternative = adventurousPattern
		}
		mixedSlots := int(math.Round(math.Abs(float64(exploration))*float64(len(base))))
		useAlternative := (position*7)%int64(len(base)) < int64(mixedSlots)
		pattern := base
		if useAlternative {
			pattern = alternative
		}
		return pattern[position%int64(len(base))]
	}
	return lane
}

// loadPreparedSlate mirrors SlateBuilder._load_prepared_slate; ok is false
// when the cache row is absent or stale (> 1h).
func loadPreparedSlate(db dbx, modelID, lane string, count int64, diversityEnabled bool) (*builtSlate, bool, error) {
	key := slateKey(modelID, lane, diversityEnabled)
	var value string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, key).Scan(&value)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	payload, err := parseJSON([]byte(value))
	if err != nil {
		return nil, false, err
	}
	createdAtMs := pythonInt(payload.get("created_at_ms"))
	if nowMs()-createdAtMs > 3_600_000 {
		return nil, false, nil
	}
	rawItems := payload.get("items")
	items := make([]*recommendationItem, 0, len(rawItems.arr))
	for _, raw := range rawItems.arr {
		items = append(items, recommendationItemFromPayload(raw))
	}
	if len(items) == 0 {
		slate := builtSlate{modelID: modelID, lane: lane, items: nil, timingsMs: map[string]int64{"precomputed": 1, "total": 0}}
		return &slate, true, nil
	}
	sceneIDs := make(map[string]bool, len(items))
	for _, item := range items {
		sceneIDs[item.sceneID] = true
	}
	eligibility, err := sceneEligibility(db, nowMs(), sceneIDs)
	if err != nil {
		return nil, false, err
	}
	ids := sortedKeys(sceneIDs)
	args := make([]any, 0, len(ids)+1)
	args = append(args, createdAtMs)
	for _, id := range ids {
		args = append(args, id)
	}
	changed := make(map[string]bool)
	rows, err := db.Query(`SELECT scene_id FROM play_session
WHERE ended_at_ms>=? AND scene_id IN (`+inClause(len(ids))+`)
AND (provenance<>'direct_player' OR `+observedPlaybackSQL+`)`, args...)
	if err != nil {
		return nil, false, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			return nil, false, err
		}
		changed[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	selected := make([]*recommendationItem, 0, len(items))
	position := int64(0)
	for _, item := range items {
		if changed[item.sceneID] {
			continue
		}
		state, ok := eligibility[item.sceneID]
		if !ok {
			state = eligibilityResult{}
		}
		if !state.eligible {
			continue
		}
		cp := *item
		cp.position = position
		selected = append(selected, &cp)
		position++
	}
	if int64(len(selected)) > count {
		selected = selected[:count]
	}
	slate := builtSlate{modelID: modelID, lane: lane, items: selected, timingsMs: map[string]int64{"precomputed": 1, "total": 0}}
	return &slate, true, nil
}

// recommendationItemFromPayload mirrors SlateBuilder._recommendation_item.
func recommendationItemFromPayload(payload jVal) *recommendationItem {
	item := &recommendationItem{
		sceneID:       payload.get("scene_id").asString(),
		lane:          payload.get("lane").asString(),
		sourceLane:    payload.get("source_lane").asString(),
		subtype:       payload.get("subtype"),
		position:      pythonInt(payload.get("position")),
		appeal:        floatValue(payload.get("appeal")),
		currentFit:    floatValue(payload.get("current_fit")),
		confidence:    floatValue(payload.get("confidence")),
		laneValue:     floatValue(payload.get("lane_value")),
		finalUtility:  floatValue(payload.get("final_utility")),
		penalties:     payload.get("penalties"),
		bonuses:       payload.get("bonuses"),
		components:    payload.get("components"),
		neighbors:     payload.get("neighbors"),
		eligibility:   payload.get("eligibility"),
		qualification: payload.get("qualification"),
	}
	for _, id := range payload.get("reason_ids").arr {
		item.reasonIDs = append(item.reasonIDs, id.asString())
	}
	return item
}

func slateKey(modelID, lane string, diversityEnabled bool) string {
	suffix := ""
	if !diversityEnabled {
		suffix = ":unshuffled"
	}
	return "slate:" + modelID + ":" + lane + suffix
}

// savePreparedSlate mirrors SlateBuilder._save_prepared_slate.
func savePreparedSlate(db dbx, modelID, lane string, diversityEnabled bool, slate *builtSlate) error {
	items := jvArr()
	for _, item := range slate.items {
		items.arr = append(items.arr, recommendationItemDict(item))
	}
	payload := jvObj(
		jvKey("created_at_ms", jvInt(nowMs())),
		jvKey("items", items),
	)
	return execImmediate(db, `INSERT INTO application_meta(key, value) VALUES (?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, slateKey(modelID, lane, diversityEnabled), payload.marshalCompact())
}

// loadCandidates mirrors the _load_prepared + LanePolicy.load + _candidates
// chain: the model_lane_candidate_cache rows when complete, else
// model_scene_lane classifications enriched with content vectors, performers,
// and studios.
func loadCandidates(db dbx, modelID string, sourceLanes map[string]bool) ([]*greedyCandidate, error) {
	candidates, ok, err := loadPreparedCandidates(db, modelID, sourceLanes)
	if err != nil {
		return nil, err
	}
	if ok {
		return candidates, nil
	}
	classifications, err := lanePolicyLoad(db, modelID, sourceLanes)
	if err != nil {
		return nil, err
	}
	if len(classifications) == 0 {
		// policy.classify writes model_scene_lane; the read interface always
		// has a classified model, so this is a defensive mirror.
		return nil, fmt.Errorf("no lane classifications for model %s", modelID)
	}
	candidates, err = buildCandidates(db, modelID, classifications)
	if err != nil {
		return nil, err
	}
	if err := savePreparedCandidates(db, modelID, sourceLanes, candidates); err != nil {
		return nil, err
	}
	return candidates, nil
}

// loadPreparedCandidates mirrors SlateBuilder._load_prepared.
func loadPreparedCandidates(db dbx, modelID string, sourceLanes map[string]bool) ([]*greedyCandidate, bool, error) {
	lanes := make([]string, 0, len(sourceLanes))
	for lane := range sourceLanes {
		lanes = append(lanes, lane)
	}
	sort.Strings(lanes)
	placeholders := inClause(len(lanes))
	args := make([]any, 0, len(lanes)+1)
	args = append(args, modelID)
	for _, lane := range lanes {
		args = append(args, lane)
	}
	rows, err := db.Query(`SELECT lane, candidates_json, candidate_count FROM model_lane_candidate_cache
WHERE model_id=? AND lane IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, false, err
	}
	type cacheRow struct {
		lane       string
		candidates string
		count      int64
	}
	var cached []cacheRow
	for rows.Next() {
		var r cacheRow
		if err := rows.Scan(&r.lane, &r.candidates, &r.count); err != nil {
			return nil, false, err
		}
		cached = append(cached, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	present := make(map[string]bool, len(cached))
	for _, r := range cached {
		present[r.lane] = true
	}
	if len(present) != len(sourceLanes) {
		return nil, false, nil
	}
	expected := make(map[string]int64)
	rows, err = db.Query(`SELECT lane, count(*) AS candidate_count FROM model_scene_lane
WHERE model_id=? AND lane IN (`+placeholders+`) GROUP BY lane`, args...)
	if err != nil {
		return nil, false, err
	}
	for rows.Next() {
		var lane string
		var count int64
		if err := rows.Scan(&lane, &count); err != nil {
			return nil, false, err
		}
		expected[lane] = count
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	for _, r := range cached {
		if r.count != expected[r.lane] {
			return nil, false, nil
		}
	}
	var result []*greedyCandidate
	for _, r := range cached {
		payload, err := parseJSON([]byte(r.candidates))
		if err != nil {
			return nil, false, err
		}
		for _, raw := range payload.arr {
			result = append(result, greedyCandidateFromPayload(raw))
		}
	}
	return result, true, nil
}

// greedyCandidateFromPayload mirrors _load_prepared's _Candidate constructor.
func greedyCandidateFromPayload(raw jVal) *greedyCandidate {
	c := &greedyCandidate{
		sceneID:       raw.get("scene_id").asString(),
		lane:          raw.get("lane").asString(),
		subtype:       raw.get("subtype").asString(),
		laneValue:     floatValue(raw.get("lane_value")),
		qualification: raw.get("qualification"),
		content:       map[string]float64{},
	}
	content := raw.get("content")
	if content.kind == jObj {
		c.content = make(map[string]float64, len(content.obj))
		for _, pair := range content.obj {
			c.content[pair.key] = floatValue(pair.val)
			c.contentOrder = append(c.contentOrder, pair.key)
		}
	}
	for _, p := range raw.get("performers").arr {
		c.performers = append(c.performers, p.asString())
	}
	c.studioGroup = raw.get("studio_group").asString()
	return c
}

// savePreparedCandidates mirrors SlateBuilder._save_prepared_candidates.
func savePreparedCandidates(db dbx, modelID string, sourceLanes map[string]bool, candidates []*greedyCandidate) error {
	lanes := make([]string, 0, len(sourceLanes))
	for lane := range sourceLanes {
		lanes = append(lanes, lane)
	}
	for _, lane := range lanes {
		payload := jvArr()
		count := int64(0)
		for _, c := range candidates {
			if c.lane != lane {
				continue
			}
			performers := jvArr()
			for _, p := range c.performers {
				performers.arr = append(performers.arr, jvStr(p))
			}
			var studioGroup jVal = jvNull()
			if c.studioGroup != "" {
				studioGroup = jvStr(c.studioGroup)
			}
			payload.arr = append(payload.arr, jvObj(
				jvKey("scene_id", jvStr(c.sceneID)),
				jvKey("lane", jvStr(c.lane)),
				jvKey("subtype", optString(c.subtype)),
				jvKey("lane_value", jvFloat(c.laneValue)),
				jvKey("qualification", c.qualification),
				jvKey("performers", performers),
				jvKey("studio_group", studioGroup),
				jvKey("content", floatsObj(c)),
			))
			count++
		}
		if err := execImmediate(db, `INSERT INTO model_lane_candidate_cache(
    model_id, lane, candidates_json, candidate_count, created_at_ms
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(model_id, lane) DO UPDATE SET
    candidates_json=excluded.candidates_json,
    candidate_count=excluded.candidate_count,
    created_at_ms=excluded.created_at_ms`, modelID, lane, payload.marshalCompact(), count, nowMs()); err != nil {
			return err
		}
	}
	return nil
}

// floatsObj serializes a candidate's content dict in insertion order
// (Python dict order), not sorted.
func floatsObj(c *greedyCandidate) jVal {
	obj := jvObj()
	seen := make(map[string]bool, len(c.contentOrder))
	for _, key := range c.contentOrder {
		if seen[key] {
			continue
		}
		seen[key] = true
		obj.set(key, jvFloat(c.content[key]))
	}
	// Defensive: keys present in the map but not in the order slice.
	for key := range c.content {
		if !seen[key] {
			obj.set(key, jvFloat(c.content[key]))
		}
	}
	return obj
}

// lanePolicyLoad mirrors LanePolicy.load: model_scene_lane rows ordered by
// lane_value DESC, scene_id.
func lanePolicyLoad(db dbx, modelID string, sourceLanes map[string]bool) ([]*greedyCandidate, error) {
	lanes := make([]string, 0, len(sourceLanes))
	for lane := range sourceLanes {
		lanes = append(lanes, lane)
	}
	sort.Strings(lanes)
	placeholders := inClause(len(lanes))
	args := make([]any, 0, len(lanes)+1)
	args = append(args, modelID)
	for _, lane := range lanes {
		args = append(args, lane)
	}
	rows, err := db.Query(`SELECT scene_id, lane, subtype, lane_value, qualification_json
FROM model_scene_lane WHERE model_id=? AND lane IN (`+placeholders+`)
ORDER BY lane_value DESC, scene_id`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []*greedyCandidate
	for rows.Next() {
		var sceneID, lane string
		var subtype sql.NullString
		var laneValue float64
		var qualificationJSON string
		if err := rows.Scan(&sceneID, &lane, &subtype, &laneValue, &qualificationJSON); err != nil {
			return nil, err
		}
		qualification, err := parseJSON([]byte(qualificationJSON))
		if err != nil {
			qualification = jvNull()
		}
		result = append(result, &greedyCandidate{
			sceneID:       sceneID,
			lane:          lane,
			subtype:       subtype.String,
			laneValue:     laneValue,
			qualification: qualification,
			content:       map[string]float64{},
		})
	}
	return result, rows.Err()
}

// buildCandidates mirrors SlateBuilder._candidates.
func buildCandidates(db dbx, modelID string, classifications []*greedyCandidate) ([]*greedyCandidate, error) {
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return nil, err
	}
	sceneIDs := make(map[string]bool, len(classifications))
	for _, c := range classifications {
		sceneIDs[c.sceneID] = true
	}
	vectors, vectorOrder, err := sceneContentVectors(db, featureVersion, sceneIDs)
	if err != nil {
		return nil, err
	}
	for _, c := range classifications {
		c.content = vectors[c.sceneID]
		c.contentOrder = vectorOrder[c.sceneID]
		if c.content == nil {
			c.content = map[string]float64{}
			c.contentOrder = nil
		}
	}
	if len(sceneIDs) > 0 {
		ids := sortedKeys(sceneIDs)
		placeholders := inClause(len(ids))
		args := make([]any, len(ids))
		for i, id := range ids {
			args[i] = id
		}
		rows, err := db.Query(`SELECT scene_id, performer_id FROM scene_performer
WHERE scene_id IN (`+placeholders+`) ORDER BY scene_id, position`, args...)
		if err != nil {
			return nil, err
		}
		performers := make(map[string][]string)
		for rows.Next() {
			var sceneID, performerID string
			if err := rows.Scan(&sceneID, &performerID); err != nil {
				return nil, err
			}
			performers[sceneID] = append(performers[sceneID], performerID)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		studioRows, err := db.Query(`SELECT s.scene_id, s.studio_id, st.parent_studio_id
FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
WHERE s.scene_id IN (`+placeholders+`)`, args...)
		if err != nil {
			return nil, err
		}
		studios := make(map[string]string)
		for studioRows.Next() {
			var sceneID string
			var studioID, parentStudioID sql.NullString
			if err := studioRows.Scan(&sceneID, &studioID, &parentStudioID); err != nil {
				return nil, err
			}
			group := ""
			if studioID.Valid {
				group = studioID.String
				if parentStudioID.Valid {
					group = parentStudioID.String
				}
			}
			studios[sceneID] = group
		}
		studioRows.Close()
		if err := studioRows.Err(); err != nil {
			return nil, err
		}
		for _, c := range classifications {
			c.performers = performers[c.sceneID]
			c.studioGroup = studios[c.sceneID]
		}
	}
	return classifications, nil
}

// sceneContentVectors mirrors FeatureStore.scene_content_vectors; the order
// slice records each vector's insertion order (SQL row order), matching the
// Python dict insertion order that cosine accumulation and serialization
// depend on.
func sceneContentVectors(db dbx, featureVersion string, sceneIDs map[string]bool) (map[string]map[string]float64, map[string][]string, error) {
	result := make(map[string]map[string]float64)
	order := make(map[string][]string)
	if len(sceneIDs) == 0 {
		return result, order, nil
	}
	ids := sortedKeys(sceneIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, featureVersion)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT ef.entity_id, fd.name, ef.value
FROM entity_feature ef
JOIN feature_definition fd ON fd.feature_id=ef.feature_id
WHERE ef.feature_version=? AND ef.entity_type='scene' AND fd.family='content'
  AND ef.entity_id IN (`+placeholders+`)
ORDER BY ef.entity_id, fd.name`, args...)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var entityID, name string
		var value float64
		if err := rows.Scan(&entityID, &name, &value); err != nil {
			return nil, nil, err
		}
		vector := result[entityID]
		if vector == nil {
			vector = make(map[string]float64)
			result[entityID] = vector
		}
		vector[name] = value
		order[entityID] = append(order[entityID], name)
	}
	return result, order, rows.Err()
}

// historyContext mirrors SlateBuilder._history_context using the candidates'
// content vectors as the cached vector store.
func historyContext(db dbx, candidates []*greedyCandidate) (map[string]bool, map[string]bool, []map[string]float64, error) {
	cachedVectors := make(map[string]map[string]float64, len(candidates))
	for _, c := range candidates {
		cachedVectors[c.sceneID] = c.content
	}
	rows, err := db.Query(`SELECT scene_id FROM recommendation_history ORDER BY shown_at_ms DESC LIMIT ?`, rankingHistorySize)
	if err != nil {
		return nil, nil, nil, err
	}
	var sceneIDs []string
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			return nil, nil, nil, err
		}
		sceneIDs = append(sceneIDs, sceneID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, nil, err
	}
	if len(sceneIDs) == 0 {
		return map[string]bool{}, map[string]bool{}, nil, nil
	}
	placeholders := inClause(len(sceneIDs))
	args := make([]any, len(sceneIDs))
	for i, id := range sceneIDs {
		args[i] = id
	}
	performers := make(map[string]bool)
	perfRows, err := db.Query(`SELECT performer_id FROM scene_performer WHERE scene_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, nil, nil, err
	}
	for perfRows.Next() {
		var performerID string
		if err := perfRows.Scan(&performerID); err != nil {
			return nil, nil, nil, err
		}
		performers[performerID] = true
	}
	perfRows.Close()
	if err := perfRows.Err(); err != nil {
		return nil, nil, nil, err
	}
	studios := make(map[string]bool)
	studioRows, err := db.Query(`SELECT COALESCE(st.parent_studio_id, s.studio_id)
FROM source_scene s LEFT JOIN source_studio st ON st.studio_id=s.studio_id
WHERE s.scene_id IN (`+placeholders+`) AND s.studio_id IS NOT NULL`, args...)
	if err != nil {
		return nil, nil, nil, err
	}
	for studioRows.Next() {
		var studioID string
		if err := studioRows.Scan(&studioID); err != nil {
			return nil, nil, nil, err
		}
		studios[studioID] = true
	}
	studioRows.Close()
	if err := studioRows.Err(); err != nil {
		return nil, nil, nil, err
	}
	var vectors []map[string]float64
	for _, sceneID := range sceneIDs[:minInt(10, len(sceneIDs))] {
		if v, ok := cachedVectors[sceneID]; ok {
			vectors = append(vectors, v)
		}
	}
	return performers, studios, vectors, nil
}

// greedyUtility mirrors SlateBuilder._utility.
func greedyUtility(c *greedyCandidate, selected []*greedyCandidate, diversityEnabled bool,
	historyPerformers, historyStudios, seenPerformers, seenStudios, coveredContent map[string]bool,
	historyVectors []map[string]float64, historySimilarities map[string]float64,
	contentSimilarity float64, liveCooldown map[string]float64) (utility, bool) {
	if diversityEnabled && len(selected) > 0 {
		previous := selected[len(selected)-1]
		prevSet := performerSet(previous.performers)
		for _, p := range c.performers {
			if prevSet[p] {
				return utility{}, false
			}
		}
	}
	penalties := jvObj(
		jvKey("performer", jvFloat(0.0)),
		jvKey("studio", jvFloat(0.0)),
		jvKey("content", jvFloat(0.0)),
		jvKey("history", jvFloat(0.0)),
		jvKey("live_cooldown", jvFloat(0.0)),
	)
	penalties.set("live_cooldown", jvFloat(liveCooldown[c.sceneID]))
	uncoveredShare := 0.0
	if diversityEnabled {
		cSet := performerSet(c.performers)
		if intersects(cSet, seenPerformers) {
			penalties.set("performer", jvFloat(rankingPerformerRepeatPenalty))
		}
		if c.studioGroup != "" && seenStudios[c.studioGroup] {
			penalties.set("studio", jvFloat(rankingStudioPenalty))
		}
		penalties.set("content", jvFloat(rankingContentPenalty*contentSimilarity))
		history := 0.0
		if intersects(cSet, historyPerformers) {
			history += rankingHistoryPerformerPenalty
		}
		if c.studioGroup != "" && historyStudios[c.studioGroup] {
			history += rankingHistoryStudioPenalty
		}
		if len(historyVectors) > 0 {
			history += rankingHistoryContentPenalty * historySimilarities[c.sceneID]
		}
		penalties.set("history", jvFloat(history))
		if len(c.content) > 0 {
			uncovered := 0
			for name := range c.content {
				if !coveredContent[name] {
					uncovered++
				}
			}
			uncoveredShare = float64(uncovered) / float64(len(c.content))
		}
	}
	bonuses := jvObj(jvKey("uncovered_content", jvFloat(rankingUncoveredContentBonus*uncoveredShare)))
	// Python: final = lane_value + sum(bonuses.values()) - sum(penalties.values())
	// (both sums are CPython 3.12+ Neumaier sums).
	penaltyValues := []float64{
		floatValue(penalties.get("performer")),
		floatValue(penalties.get("studio")),
		floatValue(penalties.get("content")),
		floatValue(penalties.get("history")),
		floatValue(penalties.get("live_cooldown")),
	}
	final := c.laneValue + sumFloats([]float64{floatValue(bonuses.get("uncovered_content"))}) - sumFloats(penaltyValues)
	return utility{final: final, penalties: penalties, bonuses: bonuses}, true
}

type utility struct {
	final     float64
	penalties jVal
	bonuses   jVal
}

func performerSet(performers []string) map[string]bool {
	set := make(map[string]bool, len(performers))
	for _, p := range performers {
		set[p] = true
	}
	return set
}

func intersects(a map[string]bool, b map[string]bool) bool {
	for key := range a {
		if b[key] {
			return true
		}
	}
	return false
}

// cosine mirrors SlateBuilder._cosine: dot over the left dict's insertion
// order, norms via sqrt.
func cosine(left, right map[string]float64) float64 {
	if len(left) == 0 || len(right) == 0 {
		return 0.0
	}
	dot := 0.0
	for name, value := range left {
		dot += value * right[name]
	}
	var leftSquares []float64
	for _, value := range left {
		leftSquares = append(leftSquares, value*value)
	}
	leftNorm := math.Sqrt(sumFloats(leftSquares))
	var rightSquares []float64
	for _, value := range right {
		rightSquares = append(rightSquares, value*value)
	}
	rightNorm := math.Sqrt(sumFloats(rightSquares))
	if leftNorm == 0 || rightNorm == 0 {
		return 0.0
	}
	return dot / (leftNorm * rightNorm)
}
