// get_lane_scene_page — a port of plugin/backend.py's _lane_scene_page: one
// page of a lane as a Stash scene list, for the Curator Lane filter on
// Stash's own scenes page, optionally recorded as an impression of the lane.
package main

import "fmt"

const laneSceneIDsQuery = `query CuratorLaneSceneIds(
  $filter: FindFilterType, $scene_filter: SceneFilterType, $scene_ids: [Int!]
) {
  findScenes(filter: $filter, scene_filter: $scene_filter, scene_ids: $scene_ids) { scenes { id } }
}`

// laneSceneOrder mirrors SlateBuilder.lane_order: every scene the lane ranks
// and could show now, in lane order. Each item carries only what the draw and
// impressions need (scene, source lane, utility).
func laneSceneOrder(db dbx, modelID, lane string, diversityEnabled bool) ([]*recommendationItem, error) {
	materialized, err := scanExists(db, `SELECT 1 FROM model_lane_order_state WHERE model_id=?`, modelID)
	if err != nil {
		return nil, err
	}
	entries := []*recommendationItem{}
	if materialized {
		ordering, queryScoreFirst := laneOrdering(lane, diversityEnabled)
		var count int64
		if queryScoreFirst {
			count = scanInt(db, `SELECT count(*) FROM model_scene_lane WHERE model_id=? AND lane=?`, modelID, lane)
		} else {
			count = scanInt(db, `SELECT count(*) FROM model_lane_order WHERE model_id=? AND lane=? AND ordering=?`, modelID, lane, ordering)
		}
		if count == 0 {
			return entries, nil
		}
		now := nowMs()
		filter, err := directPlayFilters(db, now)
		if err != nil {
			return nil, err
		}
		rows, err := materializedLaneRows(db, modelID, lane, count, diversityEnabled, nil, now, filter)
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			entries = append(entries, &recommendationItem{sceneID: row.sceneID, sourceLane: row.sourceLane, finalUtility: row.utility})
		}
		return entries, nil
	}
	var count int64
	if lane == "for_you" {
		count = scanInt(db, `SELECT count(DISTINCT scene_id) FROM model_scene_lane WHERE model_id=?`, modelID)
	} else {
		count = scanInt(db, `SELECT count(DISTINCT scene_id) FROM model_scene_lane WHERE model_id=? AND lane=?`, modelID, lane)
	}
	if count == 0 {
		return entries, nil
	}
	built, err := recommend(db, modelID, lane, count, diversityEnabled, 0, nil)
	if err != nil {
		return nil, err
	}
	for _, item := range built.items {
		entries = append(entries, &recommendationItem{sceneID: item.sceneID, sourceLane: item.sourceLane, finalUtility: item.finalUtility})
	}
	return entries, nil
}

func opGetLaneScenePage(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_lane_scene_page", func(settings jVal) (jVal, error) {
		args := payload.get("args")
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		lane := argsString(args, "lane", "")
		if !slateLanes[lane] {
			return jvNull(), fmt.Errorf("unknown lane: %s", lane)
		}
		page, perPage := int64(1), int64(40)
		if args.has("page") {
			page = pythonInt(args.get("page"))
		}
		if args.has("per_page") {
			perPage = pythonInt(args.get("per_page"))
		}
		if page < 1 || perPage < -1 {
			return jvNull(), fmt.Errorf("invalid scene page")
		}
		direction := "DESC"
		if args.has("direction") {
			direction = args.get("direction").asString()
		}
		if direction != "ASC" && direction != "DESC" {
			return jvNull(), fmt.Errorf("direction must be ASC or DESC")
		}
		order := argsString(args, "order", "stash")
		if order != "rank" && order != "picks" && order != "stash" {
			return jvNull(), fmt.Errorf("order must be rank, picks, or stash")
		}
		ranked := order != "stash"
		config, err := sidecarConfig(db)
		if err != nil {
			return jvNull(), err
		}
		modelID, err := currentModelID(db)
		if err != nil {
			return jvNull(), err
		}
		if modelID == "" {
			return jvNull(), fmt.Errorf("no published model; run build-model first")
		}
		cfg := config.get("config")
		entries, err := laneSceneOrder(db, modelID, lane, cfg.get("diversity_enabled").truthy())
		if err != nil {
			return jvNull(), err
		}
		now := nowMs()
		if order == "picks" && args.get("draw_seed").truthy() {
			drawAtMs := now
			if args.get("draw_at_ms").kind != jNull {
				drawAtMs = pythonInt(args.get("draw_at_ms"))
			}
			entries, err = drawSlate(db, lane, entries, args.get("draw_seed").asString(), drawAtMs,
				pythonInt(cfg.get("page_size")), pythonInt(cfg.get("rotation_cooldown_days")))
			if err != nil {
				return jvNull(), err
			}
		}
		filter := args.get("filter")
		if filter.kind != jObj {
			filter = jvObj()
		}
		sceneFilter, sceneIDs := args.get("scene_filter"), args.get("scene_ids")
		if !sceneFilter.truthy() {
			sceneFilter = jvNull()
		}
		if !sceneIDs.truthy() {
			sceneIDs = jvNull()
		}
		// Curator's orders need Stash only to narrow the lane; any other sort is Stash's.
		if !ranked || sceneFilter.kind != jNull || filter.get("q").truthy() || sceneIDs.kind != jNull {
			query := jVal{kind: jObj, obj: append([]jPair(nil), filter.obj...)}
			query.set("page", jvInt(1))
			query.set("per_page", jvInt(-1))
			if ranked {
				query.set("sort", jvStr("title"))
				query.set("direction", jvStr("ASC"))
			}
			base, headers := stashConnection(payload)
			data, err := graphqlQuery(base, headers, laneSceneIDsQuery, jvObj(
				jvKey("filter", query), jvKey("scene_filter", sceneFilter), jvKey("scene_ids", sceneIDs)))
			if err != nil {
				return jvNull(), err
			}
			var matching []string
			for _, scene := range data.get("findScenes").get("scenes").arr {
				matching = append(matching, scene.get("id").asString())
			}
			narrowed := []*recommendationItem{}
			if ranked {
				keep := make(map[string]bool, len(matching))
				for _, id := range matching {
					keep[id] = true
				}
				for _, entry := range entries {
					if keep[entry.sceneID] {
						narrowed = append(narrowed, entry)
					}
				}
			} else {
				inLane := make(map[string]*recommendationItem, len(entries))
				for _, entry := range entries {
					inLane[entry.sceneID] = entry
				}
				for _, id := range matching {
					if entry, ok := inLane[id]; ok {
						narrowed = append(narrowed, entry)
					}
				}
			}
			entries = narrowed
		}
		if ranked && direction == "ASC" {
			for left, right := 0, len(entries)-1; left < right; left, right = left+1, right-1 {
				entries[left], entries[right] = entries[right], entries[left]
			}
		}
		start := int64(0)
		pageEntries := entries
		if perPage >= 0 {
			start = minInt64((page-1)*perPage, int64(len(entries)))
			pageEntries = entries[start:minInt64(page*perPage, int64(len(entries)))]
		}
		impressionID := argsOptionalString(args, "impression_id")
		if impressionID.kind != jNull && len(pageEntries) > 0 {
			items := make([]*recommendationItem, len(pageEntries))
			for i, entry := range pageEntries {
				items[i] = &recommendationItem{sceneID: entry.sceneID, position: start + int64(i),
					finalUtility: entry.finalUtility, reasonIDs: []string{"eligibility.lane"}}
			}
			context := jvObj(jvKey("order", jvStr(order)), jvKey("surface", jvStr("stash_scene_list")))
			if err := recordImpression(db, impressionID.asString(), lane, modelID, items, now, context); err != nil {
				return jvNull(), err
			}
		}
		pageIDs := make([]string, len(pageEntries))
		for i, entry := range pageEntries {
			pageIDs[i] = entry.sceneID
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("model_id", jvStr(modelID)),
			jvKey("lane", jvStr(lane)),
			jvKey("impression_id", impressionID),
			jvKey("scene_ids", jvStrList(pageIDs)),
			jvKey("count", jvInt(int64(len(entries)))),
		), nil
	})
}
