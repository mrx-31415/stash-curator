// SlateBuilder.materialize — a port of curator/ranking/slate.py's materialize
// (the `prepare` task mode and the lane-materialization step of the build
// task). Reuses the runtime slate's candidate loading (lanePolicyLoad,
// buildCandidates) and ranking config constants, then writes the greedy
// score_first/varied orderings into model_lane_order plus the
// model_lane_order_state marker.
package main

import (
	"container/heap"
	"context"
	"database/sql"
	"sort"
	"time"
)

// lanes mirrors policy.LANES (order matters for the returned counts dict).
var lanes = []string{"best_bets", "revisit", "stretch", "blind_spots", "dormant"}

// orderingEntry mirrors one _build_order result row.
type orderingEntry struct {
	candidate *greedyCandidate
	utility   float64
	penalties jVal
	bonuses   jVal
}

// heapEntry mirrors _build_order's heap tuple (-utility, scene_id, lane, version).
type heapEntry struct {
	negUtility float64
	sceneID    string
	lane       string
	version    int
}

type heapQueue []heapEntry

func (h heapQueue) Len() int { return len(h) }
func (h heapQueue) Less(i, j int) bool {
	if h[i].negUtility != h[j].negUtility {
		return h[i].negUtility < h[j].negUtility
	}
	if h[i].sceneID != h[j].sceneID {
		return h[i].sceneID < h[j].sceneID
	}
	return h[i].lane < h[j].lane
}
func (h heapQueue) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *heapQueue) Push(x any)   { *h = append(*h, x.(heapEntry)) }
func (h *heapQueue) Pop() any {
	old := *h
	n := len(old)
	item := old[n-1]
	*h = old[:n-1]
	return item
}

// buildOrdering mirrors slate._build_order.
func buildOrdering(lane string, candidates []*greedyCandidate, varied bool) []orderingEntry {
	type key struct{ sceneID, lane string }
	byKey := make(map[key]*greedyCandidate, len(candidates))
	for _, c := range candidates {
		byKey[key{c.sceneID, c.lane}] = c
	}
	utilities := make(map[key]float64, len(byKey))
	for k, c := range byKey {
		u := c.laneValue
		if varied && len(c.content) > 0 {
			u += rankingUncoveredContentBonus
		}
		utilities[k] = u
	}
	versions := make(map[key]int, len(byKey))
	heaps := map[key]heapQueue{}
	selectorsOf := func(c *greedyCandidate) []key {
		result := []key{{"all", ""}}
		if lane == "for_you" {
			result = append(result, key{"lane", c.lane})
		} else if lane == "stretch" {
			if dim := stretchDimension(c); dim != "" {
				result = append(result, key{"dimension", dim})
			}
		} else if lane == "blind_spots" {
			if facet := blindSpotFacet(c); facet != "" {
				result = append(result, key{"facet", facet})
			}
		} else if lane == "dormant" {
			if entity := dormantEntity(c); entity != "" {
				result = append(result, key{"entity", entity})
			}
		}
		return result
	}
	// At most stretch_per_dimension (default 1) card per challenged dimension
	// per page: round-robin the target selector through every distinct
	// dimension present.
	dimensions := stretchDimensions(lane, candidates, varied)
	// At most blind_spot_per_facet card per dark facet per page — unconditional
	// (not gated like stretch's varied param): blind_spots is not a
	// QUERIED_SCORE_FIRST_LANES member, so both orderings materialize through
	// this same path, matching how the adventure subtype rotation it replaces
	// always applied here too.
	facets := blindSpotFacets(lane, candidates)
	// At most dormant_per_entity card per dormant entity per page — same
	// reasoning as facets above.
	entities := dormantEntities(lane, candidates)
	push := func(k key) {
		c := byKey[k]
		entry := heapEntry{-utilities[k], c.sceneID, c.lane, versions[k]}
		for _, selector := range selectorsOf(c) {
			queue := heaps[selector]
			heap.Push(&queue, entry)
			heaps[selector] = queue
		}
	}
	for k := range byKey {
		push(k)
	}
	selectedSceneIDs := map[string]bool{}
	seenPerformers := map[string]bool{}
	seenStudios := map[string]bool{}
	coveredFeatures := map[string]bool{}
	performerPenalized := map[key]bool{}
	studioPenalized := map[key]bool{}
	coveredShare := make(map[key]float64, len(byKey))
	contentTotals := make(map[key]float64, len(byKey))
	performerIndex := map[string]map[key]bool{}
	studioIndex := map[string]map[key]bool{}
	featureIndex := map[string][]struct {
		key   key
		share float64
	}{}
	if varied {
		for k, c := range byKey {
			for _, performer := range c.performers {
				if performerIndex[performer] == nil {
					performerIndex[performer] = map[key]bool{}
				}
				performerIndex[performer][k] = true
			}
			if c.studioGroup != "" {
				if studioIndex[c.studioGroup] == nil {
					studioIndex[c.studioGroup] = map[key]bool{}
				}
				studioIndex[c.studioGroup][k] = true
			}
			var total float64
			for _, value := range c.content {
				total += absF64(value)
			}
			contentTotals[k] = total
			if total > 0 {
				for feature, value := range c.content {
					featureIndex[feature] = append(featureIndex[feature], struct {
						key   key
						share float64
					}{k, absF64(value) / total})
				}
			}
		}
	}
	pop := func(selector key, previous *greedyCandidate, allowAdjacent bool) *greedyCandidate {
		var deferred []heapEntry
		queue := heaps[selector]
		var chosen *greedyCandidate
		for len(queue) > 0 {
			entry := heap.Pop(&queue).(heapEntry)
			k := key{entry.sceneID, entry.lane}
			c, ok := byKey[k]
			if !ok || entry.version != versions[k] || selectedSceneIDs[c.sceneID] {
				continue
			}
			if varied && previous != nil && !allowAdjacent && intersects(performerSet(c.performers), performerSet(previous.performers)) {
				deferred = append(deferred, entry)
				continue
			}
			chosen = c
			break
		}
		for _, entry := range deferred {
			heap.Push(&queue, entry)
		}
		heaps[selector] = queue
		return chosen
	}
	var ordered []orderingEntry
	var previous *greedyCandidate
	sceneIDs := map[string]bool{}
	for _, c := range candidates {
		sceneIDs[c.sceneID] = true
	}
	for len(selectedSceneIDs) < len(sceneIDs) {
		targetLane := slateTarget(lane, int64(len(ordered)), 0)
		var wanted key
		if lane == "stretch" && len(dimensions) > 0 {
			wanted = key{"dimension", dimensions[(len(ordered)/maxInt(1, rankingStretchPerDimension))%len(dimensions)]}
		} else if lane == "blind_spots" && len(facets) > 0 {
			wanted = key{"facet", facets[(len(ordered)/maxInt(1, rankingBlindSpotPerFacet))%len(facets)]}
		} else if lane == "dormant" && len(entities) > 0 {
			wanted = key{"entity", entities[(len(ordered)/maxInt(1, rankingDormantPerEntity))%len(entities)]}
		} else if lane == "for_you" {
			wanted = key{"lane", targetLane}
		} else {
			wanted = key{"all", ""}
		}
		chosen := pop(wanted, previous, false)
		if chosen == nil {
			chosen = pop(key{"all", ""}, previous, false)
		}
		if chosen == nil {
			chosen = pop(key{"all", ""}, previous, true)
		}
		if chosen == nil {
			break
		}
		k := key{chosen.sceneID, chosen.lane}
		penalties := jvObj(
			jvKey("performer", jvFloat(0.0)),
			jvKey("studio", jvFloat(0.0)),
			jvKey("content", jvFloat(0.0)),
			jvKey("history", jvFloat(0.0)),
			jvKey("live_cooldown", jvFloat(0.0)),
		)
		if performerPenalized[k] {
			penalties.set("performer", jvFloat(rankingPerformerRepeatPenalty))
		}
		if studioPenalized[k] {
			penalties.set("studio", jvFloat(rankingStudioPenalty))
		}
		if varied && coveredShare[k] > 0 {
			penalties.set("content", jvFloat(rankingContentPenalty*coveredShare[k]))
		}
		bonuses := jvObj(jvKey("uncovered_content", jvFloat(0.0)))
		if varied && len(chosen.content) > 0 {
			bonuses.set("uncovered_content", jvFloat(rankingUncoveredContentBonus*(1-coveredShare[k])))
		}
		ordered = append(ordered, orderingEntry{chosen, utilities[k], penalties, bonuses})
		selectedSceneIDs[chosen.sceneID] = true
		previous = chosen
		if !varied {
			continue
		}
		changed := map[key]bool{}
		for _, performer := range performerSetKeys(chosen.performers) {
			if seenPerformers[performer] {
				continue
			}
			seenPerformers[performer] = true
			for affected := range performerIndex[performer] {
				if performerPenalized[affected] {
					continue
				}
				performerPenalized[affected] = true
				utilities[affected] -= rankingPerformerRepeatPenalty
				changed[affected] = true
			}
		}
		if chosen.studioGroup != "" && !seenStudios[chosen.studioGroup] {
			seenStudios[chosen.studioGroup] = true
			for affected := range studioIndex[chosen.studioGroup] {
				if studioPenalized[affected] {
					continue
				}
				studioPenalized[affected] = true
				utilities[affected] -= rankingStudioPenalty
				changed[affected] = true
			}
		}
		for feature := range chosen.content {
			if coveredFeatures[feature] {
				continue
			}
			coveredFeatures[feature] = true
			for _, item := range featureIndex[feature] {
				coveredShare[item.key] += item.share
				utilities[item.key] -= (rankingContentPenalty + rankingUncoveredContentBonus) * item.share
				changed[item.key] = true
			}
		}
		for affected := range changed {
			if selectedSceneIDs[byKey[affected].sceneID] {
				continue
			}
			versions[affected]++
			push(affected)
		}
	}
	return ordered
}

// performerSetKeys returns the sorted performer ids of a candidate's set.
func performerSetKeys(performers []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, p := range performers {
		if !seen[p] {
			seen[p] = true
			out = append(out, p)
		}
	}
	sort.Strings(out)
	return out
}

// materializeLanes mirrors SlateBuilder.materialize: writes the greedy
// orderings and the order-state marker, returning the per-lane candidate
// counts in LANES order. Without force, an existing model_lane_order_state
// row short-circuits to the persisted counts.
func materializeLanes(db dbx, modelID string, force bool, progress func(completed, total int)) (jVal, error) {
	var one int
	err := db.QueryRow(`SELECT 1 FROM model_lane_order_state WHERE model_id=?`, modelID).Scan(&one)
	if err == nil && !force {
		// Python's fast path builds the dict from "SELECT lane, count(*)
		// ... GROUP BY lane" in the row order SQLite returns, so zero-count
		// lanes are absent and the key order follows the scan.
		rows, err := db.Query(`SELECT lane, count(*) FROM model_scene_lane
WHERE model_id=? GROUP BY lane`, modelID)
		if err != nil {
			return jvNull(), err
		}
		counts := jvObj()
		for rows.Next() {
			var lane string
			var count int64
			if err := rows.Scan(&lane, &count); err != nil {
				rows.Close()
				return jvNull(), err
			}
			counts.set(lane, jvInt(count))
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
		if progress != nil {
			progress(1, 1)
		}
		return counts, nil
	}
	if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	sourceLanes := map[string]bool{}
	for _, lane := range lanes {
		sourceLanes[lane] = true
	}
	classifications, err := lanePolicyLoad(db, modelID, sourceLanes)
	if err != nil {
		return jvNull(), err
	}
	candidates, err := buildCandidates(db, modelID, classifications)
	if err != nil {
		return jvNull(), err
	}
	counts := jvObj()
	for _, lane := range lanes {
		count := int64(0)
		for _, c := range candidates {
			if c.lane == lane {
				count++
			}
		}
		counts.set(lane, jvInt(count))
	}
	completed := 0
	if err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx,
			`DELETE FROM model_lane_order_state WHERE model_id=?`, modelID); err != nil {
			return err
		}
		_, err := conn.ExecContext(ctx,
			`DELETE FROM model_lane_order WHERE model_id=?`, modelID)
		return err
	}); err != nil {
		return jvNull(), err
	}
	timings := map[string]int64{"score_first_ordering": 0, "varied_ordering": 0}
	allLanes := append(append([]string(nil), lanes...), "for_you")
	// One progress tick per (lane, ordering) pair below: queried score-first
	// lanes materialize only "varied"; every other lane (including for_you)
	// also materializes "score_first".
	total := 0
	for _, lane := range allLanes {
		if queriedScoreFirstLanes[lane] {
			total++
		} else {
			total += 2
		}
	}
	for _, lane := range allLanes {
		laneCandidates := make([]*greedyCandidate, 0, len(candidates))
		for _, c := range candidates {
			if lane == "for_you" || c.lane == lane {
				laneCandidates = append(laneCandidates, c)
			}
		}
		orderings := []struct {
			name   string
			varied bool
		}{{"varied", true}}
		if !queriedScoreFirstLanes[lane] {
			orderings = append([]struct {
				name   string
				varied bool
			}{{"score_first", false}}, orderings...)
		}
		for _, ordering := range orderings {
			started := time.Now().UnixNano()
			ordered := buildOrdering(lane, laneCandidates, ordering.varied)
			timings[ordering.name+"_ordering"] += (time.Now().UnixNano() - started) / 1_000_000
			if err := withTxn(db, func(conn *sql.Conn) error {
				ctx := context.Background()
				for position, entry := range ordered {
					rankingJSON := jvObj(
						jvKey("penalties", entry.penalties),
						jvKey("bonuses", entry.bonuses),
					)
					if _, err := conn.ExecContext(ctx, `
INSERT INTO model_lane_order(
    model_id, lane, ordering, position, scene_id,
    source_lane, utility, ranking_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
						modelID, lane, ordering.name, position, entry.candidate.sceneID,
						entry.candidate.lane, entry.utility, rankingJSON.marshalCompact()); err != nil {
						return err
					}
				}
				return nil
			}); err != nil {
				return jvNull(), err
			}
			completed++
			if progress != nil {
				progress(completed, total)
			}
		}
	}
	if err := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(),
			`INSERT INTO model_lane_order_state(model_id, created_at_ms) VALUES (?, ?)`,
			modelID, nowMs())
		return err
	}); err != nil {
		return jvNull(), err
	}
	if t := currentTrace(); t != nil {
		recordDurationMs(t, "python", "ranking.score_first_ordering", timings["score_first_ordering"])
		recordDurationMs(t, "python", "ranking.varied_ordering", timings["varied_ordering"])
	}
	return counts, nil
}

// prepareLanesTask mirrors backend.py's _prepare_lanes wrapper.
func prepareLanesTask(db dbx, modelID string, force bool, progress func(completed, total int)) (jVal, error) {
	var counts jVal
	err := pythonSpan("task.prepare_pages", func() error {
		var err error
		counts, err = materializeLanes(db, modelID, force, progress)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	return counts, nil
}

// classifyLanesTask mirrors backend.py's _classify_lanes: the published lane
// count read from the attached artifact views.
func classifyLanesTask(db dbx, modelID string, progress func(processed, total int)) (int64, error) {
	var count int64
	err := db.QueryRow(`SELECT count(*) FROM model_scene_lane WHERE model_id=?`, modelID).Scan(&count)
	if err != nil {
		return 0, err
	}
	if progress != nil {
		progress(1, 1)
	}
	return count, nil
}
