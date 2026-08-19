// Prune/exclusion write ops and the prune-tag Stash mutation — ports of
// backend.py's set_prune_tag branch and CuratorAPI's pruning_queue /
// prune_candidates / dismiss_prune_candidate / update_pruning / exclusions /
// reverse_exclusion / record_prune_tags / reconcile_prune_tag.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"strings"
	"time"
)

// pythonSpan runs fn under an active trace recording a "python" span of the
// same name the Python side records, mirroring profiler.span().
func pythonSpan(name string, fn func() error) error {
	if t := currentTrace(); t != nil {
		started := time.Now().UnixNano()
		err := fn()
		t.record("python", name, started, time.Now().UnixNano()-started, jvNull())
		return err
	}
	return fn()
}

// ── pruning queue / candidates ──────────────────────────────────────────────

func opGetPruningQueue(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_pruning_queue",
		func(settings jVal) (jVal, error) { return getPruningQueueBody(pluginDir, payload, settings) })
}

func getPruningQueueBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	rows, err := db.Query(`
SELECT p.scene_id, p.state, p.created_at_ms, p.updated_at_ms, p.reason,
       s.title
FROM pruning_candidate p LEFT JOIN source_scene s USING(scene_id)
WHERE p.state IN ('review', 'remove') ORDER BY p.updated_at_ms DESC`)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var sceneID, state, reason, title string
		var createdAtMs, updatedAtMs int64
		if err := rows.Scan(&sceneID, &state, &createdAtMs, &updatedAtMs, &reason, &title); err != nil {
			return jvNull(), err
		}
		items.arr = append(items.arr, jvObj(
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("state", jvStr(state)),
			jvKey("created_at_ms", jvInt(createdAtMs)),
			jvKey("updated_at_ms", jvInt(updatedAtMs)),
			jvKey("reason", jvStr(reason)),
			jvKey("title", jvStr(title)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("items", items),
	), nil
}

func opGetPruneCandidates(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_prune_candidates",
		func(settings jVal) (jVal, error) { return getPruneCandidatesBody(pluginDir, payload, settings) })
}

// pruneCandidates mirrors CuratorAPI.prune_candidates.
func pruneCandidates(db dbx, view string, aggressiveness float64, page, pageSize int64,
	tagName string, modelID string) (jVal, error) {
	if view != "candidates" && view != "tagged" && view != "explicit" && view != "suspects" && view != "breadth" {
		return jvNull(), fmt.Errorf("unknown prune view")
	}
	if page < 1 || pageSize < 1 || pageSize > 100 {
		return jvNull(), fmt.Errorf("invalid prune page")
	}
	if aggressiveness < 0 || aggressiveness > 1 {
		return jvNull(), fmt.Errorf("aggressiveness must be between 0 and 1")
	}
	tagged := map[string]bool{}
	err := pythonSpan("prune.tagged", func() error {
		rows, err := db.Query(`
SELECT scene_id FROM scene_tag WHERE tag_id IN (
  SELECT tag_id FROM source_tag WHERE lower(name)=lower(?)
)`, tagName)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var sceneID string
			if err := rows.Scan(&sceneID); err != nil {
				return err
			}
			tagged[sceneID] = true
		}
		return rows.Err()
	})
	if err != nil {
		return jvNull(), err
	}
	states := map[string]string{}
	stateRows, err := db.Query(`SELECT scene_id, state FROM pruning_candidate`)
	if err != nil {
		return jvNull(), err
	}
	for stateRows.Next() {
		var sceneID, state string
		if err := stateRows.Scan(&sceneID, &state); err != nil {
			stateRows.Close()
			return jvNull(), err
		}
		states[sceneID] = state
	}
	stateRows.Close()
	if err := stateRows.Err(); err != nil {
		return jvNull(), err
	}
	explicit := map[string]bool{}
	for sceneID, state := range states {
		if state == "review" {
			explicit[sceneID] = true
		}
	}
	err = pythonSpan("prune.explicit", func() error {
		rows, err := db.Query(`
SELECT f.scene_id FROM feedback f
WHERE f.reversed_by_id IS NULL
AND f.feedback_type IN ('thumb_down', 'never_show')
AND f.occurred_at_ms=(
  SELECT max(f2.occurred_at_ms) FROM feedback f2
  WHERE f2.scene_id=f.scene_id AND f2.reversed_by_id IS NULL
  AND f2.feedback_type IN ('thumb_up', 'thumb_down', 'never_show')
)`)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var sceneID string
			if err := rows.Scan(&sceneID); err != nil {
				return err
			}
			explicit[sceneID] = true
		}
		return rows.Err()
	})
	if err != nil {
		return jvNull(), err
	}
	appealLimit := -0.18 + 0.13*aggressiveness
	confidenceLimit := 0.55 - 0.20*aggressiveness
	type scoreRow struct {
		appeal     float64
		confidence float64
	}
	scores := map[string]scoreRow{}
	if view != "tagged" {
		err = pythonSpan("prune.scores", func() error {
			rows, err := db.Query(`
SELECT scene_id, appeal, confidence FROM model_scene_score
WHERE model_id=? AND appeal<=? AND confidence>=?
UNION
SELECT scene_id, appeal, confidence FROM model_scene_score
WHERE model_id=? AND scene_id IN (
  SELECT scene_id FROM pruning_candidate WHERE state='review'
)`, modelID, appealLimit, confidenceLimit, modelID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var sceneID string
				var appeal, confidence float64
				if err := rows.Scan(&sceneID, &appeal, &confidence); err != nil {
					return err
				}
				scores[sceneID] = scoreRow{appeal, confidence}
			}
			return rows.Err()
		})
		if err != nil {
			return jvNull(), err
		}
	}
	suspects := map[string]bool{}
	for sceneID, score := range scores {
		if score.appeal <= appealLimit && score.confidence >= confidenceLimit &&
			states[sceneID] != "keep" {
			suspects[sceneID] = true
		}
	}
	breadth := map[string]bool{}
	breadthSceneStudio := map[string]string{}
	type breadthStat struct {
		libraryCount, playedCount int64
	}
	breadthStudioStats := map[string]breadthStat{}
	breadthStudioNames := map[string]string{}
	err = pythonSpan("prune.breadth", func() error {
		played, err := playedSceneIDs(db)
		if err != nil {
			return err
		}
		studioScenes := map[string]map[string]bool{}
		rows, err := db.Query(`
SELECT s.scene_id, s.studio_id, st.name
FROM source_scene s JOIN source_studio st ON st.studio_id = s.studio_id
WHERE s.studio_id IS NOT NULL`)
		if err != nil {
			return err
		}
		for rows.Next() {
			var sceneID, studioID string
			var name sql.NullString
			if err := rows.Scan(&sceneID, &studioID, &name); err != nil {
				rows.Close()
				return err
			}
			if studioScenes[studioID] == nil {
				studioScenes[studioID] = map[string]bool{}
			}
			studioScenes[studioID][sceneID] = true
			breadthStudioNames[studioID] = name.String
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
		var totalScenes int64
		if err := db.QueryRow(`SELECT count(*) FROM source_scene`).Scan(&totalScenes); err != nil {
			return err
		}
		if totalScenes < 1 {
			totalScenes = 1
		}
		baseRate := float64(len(played)) / float64(totalScenes)
		const alpha = 20.0
		const darkThreshold = 0.55
		const darkMaxLibrary = 500
		if baseRate > 0 {
			for studioID, scenes := range studioScenes {
				darkness, libraryCount, playedCount := darkPoolStats(scenes, played, baseRate, alpha)
				if libraryCount <= darkMaxLibrary || darkness < darkThreshold {
					continue
				}
				breadthStudioStats[studioID] = breadthStat{libraryCount, playedCount}
				for sceneID := range scenes {
					if states[sceneID] == "keep" {
						continue
					}
					breadth[sceneID] = true
					breadthSceneStudio[sceneID] = studioID
				}
			}
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	selected := map[string]bool{}
	switch view {
	case "candidates":
		for id := range explicit {
			selected[id] = true
		}
		for id := range suspects {
			selected[id] = true
		}
		for id := range breadth {
			selected[id] = true
		}
	case "tagged":
		for id := range tagged {
			selected[id] = true
		}
	case "explicit":
		for id := range explicit {
			selected[id] = true
		}
	case "suspects":
		for id := range suspects {
			selected[id] = true
		}
	case "breadth":
		for id := range breadth {
			selected[id] = true
		}
	}
	if view != "tagged" {
		for id := range tagged {
			delete(selected, id)
		}
	}
	ordered := make([]string, 0, len(selected))
	for id := range selected {
		ordered = append(ordered, id)
	}
	sort.SliceStable(ordered, func(i, j int) bool {
		a, b := ordered[i], ordered[j]
		aExplicit := !explicit[a]
		bExplicit := !explicit[b]
		if aExplicit != bExplicit {
			return !aExplicit
		}
		aScore, aHas := scores[a]
		bScore, bHas := scores[b]
		var aAppeal, bAppeal float64
		if aHas {
			aAppeal = aScore.appeal
		}
		if bHas {
			bAppeal = bScore.appeal
		}
		if aAppeal != bAppeal {
			return aAppeal < bAppeal
		}
		return a < b
	})
	start := (page - 1) * pageSize
	end := start + pageSize
	if end > int64(len(ordered)) {
		end = int64(len(ordered))
	}
	if start > int64(len(ordered)) {
		start = int64(len(ordered))
	}
	pageIDs := ordered[start:end]
	rowMap := map[string]struct {
		title     string
		playCount jVal
	}{}
	if len(pageIDs) > 0 {
		placeholders := strings.TrimSuffix(strings.Repeat("?,", len(pageIDs)), ",")
		args := make([]any, len(pageIDs))
		for i, id := range pageIDs {
			args[i] = id
		}
		rows, err := db.Query(fmt.Sprintf(
			`SELECT scene_id, title, play_count FROM source_scene WHERE scene_id IN (%s)`,
			placeholders), args...)
		if err != nil {
			return jvNull(), err
		}
		for rows.Next() {
			var sceneID, title string
			var playCount sql.NullInt64
			if err := rows.Scan(&sceneID, &title, &playCount); err != nil {
				rows.Close()
				return jvNull(), err
			}
			pc := jvNull()
			if playCount.Valid {
				pc = jvInt(playCount.Int64)
			}
			rowMap[sceneID] = struct {
				title     string
				playCount jVal
			}{title, pc}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}
	items := jvArr()
	for _, sceneID := range pageIDs {
		row, ok := rowMap[sceneID]
		var title string
		var playCount jVal = jvInt(0)
		if ok {
			title = row.title
			playCount = row.playCount
		}
		score, hasScore := scores[sceneID]
		var appeal, confidence jVal = jvNull(), jvNull()
		if hasScore {
			appeal = jvFloat(score.appeal)
			confidence = jvFloat(score.confidence)
		}
		evidence := jvArr()
		if explicit[sceneID] {
			evidence.arr = append(evidence.arr, jvStr("Explicit negative feedback"))
		}
		if suspects[sceneID] {
			evidence.arr = append(evidence.arr, jvStr("Low predicted Appeal with supporting evidence"))
		}
		if breadth[sceneID] {
			studioID := breadthSceneStudio[sceneID]
			stat := breadthStudioStats[studioID]
			studioName := breadthStudioNames[studioID]
			if studioName == "" {
				studioName = studioID
			}
			evidence.arr = append(evidence.arr, jvStr(fmt.Sprintf(
				"Broad, low-engagement studio (%s): owns %d, played %d",
				studioName, stat.libraryCount, stat.playedCount)))
		}
		items.arr = append(items.arr, jvObj(
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("title", jvStr(title)),
			jvKey("play_count", playCount),
			jvKey("appeal", appeal),
			jvKey("confidence", confidence),
			jvKey("tagged", jvBool(tagged[sceneID])),
			jvKey("explicit", jvBool(explicit[sceneID])),
			jvKey("suspect", jvBool(suspects[sceneID])),
			jvKey("breadth", jvBool(breadth[sceneID])),
			jvKey("evidence", evidence),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(modelID)),
		jvKey("view", jvStr(view)),
		jvKey("aggressiveness", jvFloat(aggressiveness)),
		jvKey("tag_name", jvStr(tagName)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(pageSize)),
		jvKey("total", jvInt(int64(len(ordered)))),
		jvKey("items", items),
	), nil
}

func getPruneCandidatesBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	view := pythonStrOrEmpty(args.get("view"))
	if view == "" {
		view = "candidates"
	}
	aggressiveness := pythonFloatOr(args.get("aggressiveness"), 0)
	page := argsInt(args, "page", 1)
	pageSize := argsInt(args, "page_size", 20)
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
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model")
	}
	return pruneCandidates(db, view, aggressiveness, page, pageSize,
		cfg.get("prune_tag_name").asString(), modelID)
}

// ── prune writes ────────────────────────────────────────────────────────────

func opDismissPruneCandidate(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "dismiss_prune_candidate",
		func(settings jVal) (jVal, error) { return dismissPruneCandidateBody(pluginDir, payload, settings) })
}

func dismissPruneCandidateBody(pluginDir string, payload, settings jVal) (jVal, error) {
	sceneID := pythonStrOrEmpty(payload.get("args").get("scene_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	now := nowMs()
	err = withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
VALUES (?, 'keep', ?, ?, 'Dismissed model suspect')
ON CONFLICT(scene_id) DO UPDATE SET state='keep',
    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason`,
			sceneID, now, now)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("dismissed", jvBool(true)),
	), nil
}

func opUpdatePruning(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "update_pruning",
		func(settings jVal) (jVal, error) { return updatePruningBody(pluginDir, payload, settings) })
}

func updatePruningBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	sceneID := pythonStrOrEmpty(args.get("scene_id"))
	state := pythonStrOrEmpty(args.get("state"))
	if state != "keep" && state != "remove" {
		return jvNull(), fmt.Errorf("pruning state must be keep or remove")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	now := nowMs()
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		res, err := conn.ExecContext(ctx,
			`UPDATE pruning_candidate SET state=?, updated_at_ms=? WHERE scene_id=?`,
			state, now, sceneID)
		if err != nil {
			return err
		}
		rows, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if rows != 1 {
			return fmt.Errorf("scene is not in the pruning queue: %s", sceneID)
		}
		return coordinatorRequest(conn, "pruning_decision", now)
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("state", jvStr(state)),
	), nil
}

func opGetExclusions(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_exclusions",
		func(settings jVal) (jVal, error) { return getExclusionsBody(pluginDir, payload, settings) })
}

func getExclusionsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	rows, err := db.Query(`
SELECT e.entity_id AS scene_id, e.created_at_ms, s.title
FROM exclusion e LEFT JOIN source_scene s ON s.scene_id=e.entity_id
WHERE e.entity_type='scene' AND e.exclusion_type='never_show'
  AND e.reversed_at_ms IS NULL
ORDER BY e.created_at_ms DESC`)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var sceneID, title string
		var createdAtMs int64
		if err := rows.Scan(&sceneID, &createdAtMs, &title); err != nil {
			return jvNull(), err
		}
		items.arr = append(items.arr, jvObj(
			jvKey("scene_id", jvStr(sceneID)),
			jvKey("created_at_ms", jvInt(createdAtMs)),
			jvKey("title", jvStr(title)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("items", items),
	), nil
}

func opReverseExclusion(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "reverse_exclusion",
		func(settings jVal) (jVal, error) { return reverseExclusionBody(pluginDir, payload, settings) })
}

func reverseExclusionBody(pluginDir string, payload, settings jVal) (jVal, error) {
	sceneID := pythonStrOrEmpty(payload.get("args").get("scene_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	now := nowMs()
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		res, err := conn.ExecContext(ctx,
			`UPDATE exclusion SET reversed_at_ms=?
WHERE entity_type='scene' AND entity_id=? AND exclusion_type='never_show'
  AND reversed_at_ms IS NULL`, now, sceneID)
		if err != nil {
			return err
		}
		rows, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if rows != 1 {
			return fmt.Errorf("scene is not actively excluded: %s", sceneID)
		}
		return coordinatorRequest(conn, "exclusion_reversed", now)
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("reversed", jvBool(true)),
	), nil
}

// ── prune tag (Stash mutation) ──────────────────────────────────────────────

// Prune-tag query documents, byte-identical to backend.py.
const findPruneTagQuery = `
query CuratorFindPruneTag($name: String!) {
  findTags(filter: {q: $name, per_page: 20}) { tags { id name } }
}
`
const createPruneTagQuery = `
mutation CuratorCreatePruneTag($input: TagCreateInput!) {
  tagCreate(input: $input) { id name }
}
`
const updatePruneTagQuery = `
mutation CuratorUpdatePruneTag($input: BulkSceneUpdateInput!) {
  bulkSceneUpdate(input: $input) { id }
}
`

func opSetPruneTag(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "set_prune_tag",
		func(settings jVal) (jVal, error) { return setPruneTagBody(pluginDir, payload, settings) })
}

func setPruneTagBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	sceneIDsV := args.get("scene_ids")
	if sceneIDsV.kind != jArr || len(sceneIDsV.arr) < 1 || len(sceneIDsV.arr) > 100 {
		return jvNull(), fmt.Errorf("scene_ids must contain 1 to 100 scenes")
	}
	sceneIDs := make([]string, 0, len(sceneIDsV.arr))
	seen := map[string]bool{}
	for _, v := range sceneIDsV.arr {
		id := v.asString()
		if !seen[id] {
			seen[id] = true
			sceneIDs = append(sceneIDs, id)
		}
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
	cfg := config.get("config")
	tagName := cfg.get("prune_tag_name").asString()
	base, headers := stashConnection(payload)
	data, err := graphqlQuery(base, headers, findPruneTagQuery,
		jvObj(jvKey("name", jvStr(tagName))))
	if err != nil {
		return jvNull(), err
	}
	found := data.get("findTags").get("tags")
	tag := jvNull()
	for _, item := range found.arr {
		if pythonLower(item.get("name").asString()) == pythonLower(tagName) {
			tag = item
			break
		}
	}
	if tag.kind == jNull {
		data, err := graphqlQuery(base, headers, createPruneTagQuery,
			jvObj(jvKey("input", jvObj(jvKey("name", jvStr(tagName))))))
		if err != nil {
			return jvNull(), err
		}
		tag = data.get("tagCreate")
	}
	tagID := tag.get("id").asString()
	tagged := args.get("tagged").truthy()
	mode := "REMOVE"
	if tagged {
		mode = "ADD"
	}
	ids := jvArr()
	for _, id := range sceneIDs {
		ids.arr = append(ids.arr, jvStr(id))
	}
	_, err = graphqlQuery(base, headers, updatePruneTagQuery,
		jvObj(jvKey("input", jvObj(
			jvKey("ids", ids),
			jvKey("tag_ids", jvObj(
				jvKey("ids", jvArr(jvStr(tagID))),
				jvKey("mode", jvStr(mode)),
			)),
		))))
	if err != nil {
		return jvNull(), err
	}
	if err := recordPruneTags(db, sceneIDs, tagged, tagID, tagName); err != nil {
		return jvNull(), err
	}
	outIDs := jvArr()
	for _, id := range sceneIDs {
		outIDs.arr = append(outIDs.arr, jvStr(id))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("scene_ids", outIDs),
		jvKey("tagged", jvBool(tagged)),
		jvKey("tag_id", jvStr(tagID)),
		jvKey("tag_name", jvStr(tagName)),
	), nil
}

// recordPruneTags mirrors CuratorAPI.record_prune_tags.
func recordPruneTags(db dbx, sceneIDs []string, tagged bool, tagID, tagName string) error {
	return withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		now := nowMs()
		if _, err := conn.ExecContext(ctx, `
INSERT INTO source_tag(tag_id, name, source_hash) VALUES (?, ?, 'curator-prune')
ON CONFLICT(tag_id) DO UPDATE SET name=excluded.name`, tagID, tagName); err != nil {
			return err
		}
		if tagged {
			for _, sceneID := range sceneIDs {
				if _, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO scene_tag(scene_id, tag_id, provenance)
VALUES (?, ?, 'scene')`, sceneID, tagID); err != nil {
					return err
				}
				if _, err := conn.ExecContext(ctx, `
INSERT INTO pruning_candidate(
    scene_id, state, created_at_ms, updated_at_ms, reason
)
VALUES (?, 'remove', ?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET state='remove',
    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason`,
					sceneID, now, now, "Tagged "+tagName); err != nil {
					return err
				}
			}
		} else {
			for _, sceneID := range sceneIDs {
				if _, err := conn.ExecContext(ctx,
					`DELETE FROM scene_tag WHERE scene_id=? AND tag_id=?`,
					sceneID, tagID); err != nil {
					return err
				}
				if _, err := conn.ExecContext(ctx,
					`DELETE FROM pruning_candidate WHERE scene_id=? AND state='remove'`,
					sceneID); err != nil {
					return err
				}
			}
		}
		return nil
	})
}

// reconcilePruneTag mirrors CuratorAPI.reconcile_prune_tag; used by the
// sync-build task modes.
func reconcilePruneTag(db dbx, tagName string) (bool, error) {
	tagged := map[string]bool{}
	rows, err := db.Query(`
SELECT st.scene_id FROM scene_tag st JOIN source_tag t USING(tag_id)
WHERE lower(t.name)=lower(?)`, tagName)
	if err != nil {
		return false, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return false, err
		}
		tagged[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return false, err
	}
	now := nowMs()
	reason := "Tagged " + tagName
	changed := false
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		res, err := conn.ExecContext(ctx, `
DELETE FROM pruning_candidate
WHERE state='remove' AND scene_id NOT IN (
    SELECT st.scene_id FROM scene_tag st JOIN source_tag t USING(tag_id)
    WHERE lower(t.name)=lower(?)
)`, tagName)
		if err != nil {
			return err
		}
		deleted, err := res.RowsAffected()
		if err != nil {
			return err
		}
		changed = deleted > 0
		for sceneID := range tagged {
			res, err := conn.ExecContext(ctx, `
INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
VALUES (?, 'remove', ?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET state='remove',
    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason
WHERE pruning_candidate.state!='remove'
    OR pruning_candidate.reason IS NOT excluded.reason`,
				sceneID, now, now, reason)
			if err != nil {
				return err
			}
			rows, err := res.RowsAffected()
			if err != nil {
				return err
			}
			changed = changed || rows > 0
		}
		return nil
	})
	return changed, err
}
