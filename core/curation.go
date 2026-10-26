// Curation ops: model impact and impact corrections — the Go mirror of
// curator/curation.py. Everything is deterministic (ORDER BY, sorted
// iteration, no RNG) so the differential gates compare against Python.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
)

func nowStrID(now int64) string {
	return fmt.Sprintf("%d-%s", now, uuid4())
}

// submitImpactCorrection mirrors curation.submit_impact_correction: a
// deliberate "this impact move is wrong" correction that pulls a wrongly
// promoted/demoted scene back toward its true appeal on the next build.
// 'up' (a demotion was wrong) writes an outcome +1 signal, 'down' writes -1.
// Only the latest active correction per scene counts — a new correction
// supersedes the previous one, so correcting twice is not additive.
func submitImpactCorrection(db dbx, sceneID, direction string) (jVal, error) {
	if sceneID == "" {
		return jvNull(), fmt.Errorf("scene_id is required")
	}
	if direction != "up" && direction != "down" {
		return jvNull(), fmt.Errorf("direction must be 'up' or 'down'")
	}
	var probe int
	err := db.QueryRow(`SELECT 1 FROM source_scene WHERE scene_id=?`, sceneID).Scan(&probe)
	if err == sql.ErrNoRows {
		return jvNull(), fmt.Errorf("unknown scene: %s", sceneID)
	}
	if err != nil {
		return jvNull(), err
	}
	now := nowMs()
	outcome := "-1"
	if direction == "up" {
		outcome = "1"
	}
	newID := nowStrID(now)
	err = withTxn(db, func(conn *sql.Conn) error {
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, 'impact_correction', ?, ?, NULL, NULL, '{}')`,
			newID, sceneID, outcome, now); err != nil {
			return err
		}
		// Supersede the earlier active correction: the new row is the reversal
		// target, so only the latest correction per scene is live (idempotent).
		if _, err := conn.ExecContext(context.Background(), `
UPDATE feedback SET reversed_by_id=? WHERE scene_id=? AND
  feedback_type='impact_correction' AND feedback_id != ? AND reversed_by_id IS NULL`,
			newID, sceneID, newID); err != nil {
			return err
		}
		return coordinatorRequest(conn, "impact_correction", now)
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(2)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("direction", jvStr(direction)),
	), nil
}

// opSubmitImpactCorrection mirrors backend.py's submit_impact_correction branch.
func opSubmitImpactCorrection(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_impact_correction",
		func(settings jVal) (jVal, error) { return submitImpactCorrectionBody(pluginDir, payload, settings) })
}

func submitImpactCorrectionBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return submitImpactCorrection(db, pythonStrOrEmpty(args.get("scene_id")), pythonStrOrEmpty(args.get("direction")))
}

// opGetCurationImpact mirrors backend.py's get_curation_impact branch.
func opGetCurationImpact(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_curation_impact",
		func(settings jVal) (jVal, error) { return curationImpactBody(pluginDir, payload, settings) })
}

func curationImpactBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return curationImpact(db)
}

// Impact report constants mirror curation.py's IMPACT_* values.
const (
	IMPACT_TOP_SCENES       = 5
	IMPACT_TOP_ENTITIES     = 4
	IMPACT_MIN_DELTA        = 0.01
	IMPACT_MIN_CONTRIBUTION = 0.0005
	IMPACT_SCENE_POOL       = 20
	// IMPACT_MAX_CONTRIBUTORS mirrors curation.IMPACT_MAX_CONTRIBUTORS: the
	// per-scene "Because" entities shown (plus direct).
	IMPACT_MAX_CONTRIBUTORS = 6
)

// impactFeedbackTypes mirrors curation.IMPACT_FEEDBACK_TYPES: the feedback
// types that teach the model's scene labels, used to tie a scene's move back
// to the user's own feedback on scenes carrying the same entities.
var impactFeedbackTypes = []string{
	"thumb_up",
	"thumb_down",
	"curation_rating",
	"impact_correction",
}

// curationImpact mirrors curation.curation_impact: diff the two most recent
// model artifacts and report the scenes, performers, and tags whose effective
// scores moved the most.
func curationImpact(db dbx) (jVal, error) {
	type modelRow struct {
		modelID        string
		basename       string
		publishedAtMs  int64
		featureVersion string
	}
	var models []modelRow
	rows, err := db.Query(`
		SELECT model_id, artifact_basename, published_at_ms, feature_version
		FROM model_version
		WHERE artifact_basename IS NOT NULL
		ORDER BY published_at_ms DESC
		LIMIT 2`)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var m modelRow
		if err := rows.Scan(&m.modelID, &m.basename, &m.publishedAtMs, &m.featureVersion); err != nil {
			rows.Close()
			return jvNull(), err
		}
		models = append(models, m)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	if len(models) < 2 {
		return jvObj(
			jvKey("available", jvBool(false)),
			jvKey("reason", jvStr("need two built models to measure impact")),
		), nil
	}
	newer, older := models[0], models[1]
	unavailable := func() jVal {
		return jvObj(
			jvKey("available", jvBool(false)),
			jvKey("reason", jvStr("model artifacts unavailable")),
		)
	}
	corePath, err := coreDatabasePath(db)
	if err != nil {
		return jvNull(), err
	}
	newerPath, err := artifactPath(corePath, newer.basename)
	if err != nil {
		return unavailable(), nil
	}
	olderPath, err := artifactPath(corePath, older.basename)
	if err != nil {
		return unavailable(), nil
	}
	var featureBasename string
	err = db.QueryRow(`SELECT artifact_basename FROM feature_build WHERE feature_version=?`, newer.featureVersion).Scan(&featureBasename)
	if err != nil {
		return unavailable(), nil
	}
	featurePath, err := artifactPath(corePath, featureBasename)
	if err != nil {
		return unavailable(), nil
	}

	appeals := func(path, modelID string) (map[string]float64, map[string]float64, error) {
		adb, err := sql.Open("sqlite3", readonlyArtifactURI(path, true))
		if err != nil {
			return nil, nil, err
		}
		defer adb.Close()
		appeal := map[string]float64{}
		direct := map[string]float64{}
		ar, err := adb.Query(`SELECT scene_id, general_appeal, direct_appeal FROM model_scene_score WHERE model_id=?`, modelID)
		if err != nil {
			return nil, nil, err
		}
		for ar.Next() {
			var sceneID string
			var value float64
			var directValue sql.NullFloat64
			if err := ar.Scan(&sceneID, &value, &directValue); err != nil {
				ar.Close()
				return nil, nil, err
			}
			appeal[sceneID] = value
			if directValue.Valid {
				direct[sceneID] = directValue.Float64
			}
		}
		ar.Close()
		return appeal, direct, ar.Err()
	}
	newAppeal, newDirect, err := appeals(newerPath, newer.modelID)
	if err != nil {
		return unavailable(), nil
	}
	oldAppeal, oldDirect, err := appeals(olderPath, older.modelID)
	if err != nil {
		return unavailable(), nil
	}
	var sceneEntries []impactEntry
	for sceneID, value := range newAppeal {
		oldValue, ok := oldAppeal[sceneID]
		if !ok {
			continue
		}
		delta := value - oldValue
		if math.Abs(delta) > IMPACT_MIN_DELTA {
			sceneEntries = append(sceneEntries, impactEntry{id: sceneID, delta: delta})
		}
	}
	// Candidate pools: the final lists keep only feedback-driven movers, so
	// scan a wider band before filtering.
	promotedPool := topEntries(sceneEntries, true, IMPACT_SCENE_POOL)
	demotedPool := topEntries(sceneEntries, false, IMPACT_SCENE_POOL)

	sceneMeta := map[string]*[3]*string{}
	chosen := make([]string, 0, len(promotedPool)+len(demotedPool))
	for _, e := range promotedPool {
		chosen = append(chosen, e.id)
	}
	for _, e := range demotedPool {
		chosen = append(chosen, e.id)
	}
	if len(chosen) > 0 {
		marks := strings.TrimSuffix(strings.Repeat("?,", len(chosen)), ",")
		args := make([]any, 0, len(chosen))
		for _, id := range chosen {
			args = append(args, id)
		}
		mr, err := db.Query(`
			SELECT ss.scene_id, ss.title, ss.scene_date, s.name
			FROM source_scene ss
			LEFT JOIN source_studio s ON s.studio_id = ss.studio_id
			WHERE ss.scene_id IN (`+marks+`)`, args...)
		if err != nil {
			return jvNull(), err
		}
		for mr.Next() {
			var sceneID string
			var titleVal, dateVal, studioVal sql.NullString
			if err := mr.Scan(&sceneID, &titleVal, &dateVal, &studioVal); err != nil {
				mr.Close()
				return jvNull(), err
			}
			var title, date, studio *string
			if titleVal.Valid {
				t := titleVal.String
				title = &t
			}
			if dateVal.Valid {
				d := dateVal.String
				date = &d
			}
			if studioVal.Valid {
				s := studioVal.String
				studio = &s
			}
			meta := [3]*string{title, date, studio}
			sceneMeta[sceneID] = &meta
		}
		mr.Close()
		if err := mr.Err(); err != nil {
			return jvNull(), err
		}
	}

	// Affinity features are versioned: the two models may build on different
	// feature versions, so each model's affinities resolve through its own
	// feature artifact and are keyed by entity id, not feature_id.
	var olderFeatureBasename string
	olderFeaturePath := ""
	if err := db.QueryRow(`SELECT artifact_basename FROM feature_build WHERE feature_version=?`, older.featureVersion).Scan(&olderFeatureBasename); err == nil {
		if p, perr := artifactPath(corePath, olderFeatureBasename); perr == nil {
			olderFeaturePath = p
		}
	}
	entityEffective := func(path, featurePath, modelID string) (map[string]float64, map[string]float64, error) {
		fdb, err := sql.Open("sqlite3", readonlyArtifactURI(featurePath, true))
		if err != nil {
			return nil, nil, err
		}
		names := map[string]string{}
		fr, err := fdb.Query(`SELECT feature_id, name FROM feature_definition`)
		if err != nil {
			fdb.Close()
			return nil, nil, err
		}
		for fr.Next() {
			var featureID, name string
			if err := fr.Scan(&featureID, &name); err != nil {
				fr.Close()
				fdb.Close()
				return nil, nil, err
			}
			names[featureID] = name
		}
		fr.Close()
		fdb.Close()
		adb, err := sql.Open("sqlite3", readonlyArtifactURI(path, true))
		if err != nil {
			return nil, nil, err
		}
		defer adb.Close()
		performers := map[string]float64{}
		tags := map[string]float64{}
		ar, err := adb.Query(`SELECT feature_id, affinity, confidence FROM feature_affinity WHERE model_id=?`, modelID)
		if err != nil {
			return nil, nil, err
		}
		for ar.Next() {
			var featureID string
			var affinity, confidence float64
			if err := ar.Scan(&featureID, &affinity, &confidence); err != nil {
				ar.Close()
				return nil, nil, err
			}
			name, ok := names[featureID]
			if !ok {
				continue
			}
			effective := affinity * confidence
			if strings.HasPrefix(name, "performer:") {
				performers[name[len("performer:"):]] = effective
			} else if strings.HasPrefix(name, "tag:") {
				tags[name[len("tag:"):]] = effective
			}
		}
		ar.Close()
		return performers, tags, ar.Err()
	}
	newPerformers, newTags, err := entityEffective(newerPath, featurePath, newer.modelID)
	if err != nil {
		return unavailable(), nil
	}
	var oldPerformers, oldTags map[string]float64
	if olderFeaturePath != "" {
		oldPerformers, oldTags, err = entityEffective(olderPath, olderFeaturePath, older.modelID)
		if err != nil {
			return unavailable(), nil
		}
	} else {
		oldPerformers, oldTags = map[string]float64{}, map[string]float64{}
	}
	// Entities have no noise floor: the top movers are informative even at
	// small magnitudes, and the UI labels weak signal explicitly.
	deltasByID := func(newer, older map[string]float64) map[string]float64 {
		out := map[string]float64{}
		for id, value := range newer {
			oldValue, ok := older[id]
			if !ok {
				continue
			}
			delta := value - oldValue
			if delta != 0.0 {
				out[id] = delta
			}
		}
		return out
	}
	performerDeltas := deltasByID(newPerformers, oldPerformers)
	tagDeltas := deltasByID(newTags, oldTags)
	performersUp, performersDown := ranked(entriesOf(performerDeltas), IMPACT_TOP_ENTITIES)
	tagsUp, tagsDown := ranked(entriesOf(tagDeltas), IMPACT_TOP_ENTITIES)

	performerNames := map[string]string{}
	pn, err := db.Query(`SELECT performer_id, name FROM source_performer`)
	if err != nil {
		return jvNull(), err
	}
	for pn.Next() {
		var performerID, name string
		if err := pn.Scan(&performerID, &name); err != nil {
			pn.Close()
			return jvNull(), err
		}
		performerNames[performerID] = name
	}
	pn.Close()
	tagNames := map[string]string{}
	tn, err := db.Query(`SELECT tag_id, COALESCE(name, '') AS name FROM source_tag`)
	if err != nil {
		return jvNull(), err
	}
	for tn.Next() {
		var tagID, name string
		if err := tn.Scan(&tagID, &name); err != nil {
			tn.Close()
			return jvNull(), err
		}
		tagNames[tagID] = name
	}
	tn.Close()

	// Scene "why": the entities whose effective affinity moved and that the
	// scene carries under the newest feature version. Contribution is the
	// entity's effective-affinity delta (presence is 0/1).
	contributionDeltas := map[string]float64{}
	for entityID, delta := range performerDeltas {
		if math.Abs(delta) > IMPACT_MIN_CONTRIBUTION {
			contributionDeltas["performer:"+entityID] = delta
		}
	}
	for entityID, delta := range tagDeltas {
		if math.Abs(delta) > IMPACT_MIN_CONTRIBUTION {
			contributionDeltas["tag:"+entityID] = delta
		}
	}
	type contributor struct {
		kind        string
		id          string
		name        string
		delta       float64
		viaFeedback int
	}
	sceneContributors := map[string][]contributor{}
	sceneBreakdowns := map[string]map[string]float64{}
	{
		fdb, err := sql.Open("sqlite3", readonlyArtifactURI(featurePath, true))
		if err != nil {
			return unavailable(), nil
		}
		sceneIDs := make([]string, 0, len(promotedPool)+len(demotedPool))
		for _, e := range promotedPool {
			sceneIDs = append(sceneIDs, e.id)
		}
		for _, e := range demotedPool {
			sceneIDs = append(sceneIDs, e.id)
		}
		// One batched query instead of one per scene: the pooled entity_id
		// lookups were individual full scans of the artifact (entity_feature
		// has no entity_id index and the predicate omits entity_type, so the
		// PK prefix cannot narrow them), which dominated the op on large
		// libraries. Contributors are sorted and truncated afterwards, so
		// row order is irrelevant and the output is unchanged.
		namesByScene := map[string][]string{}
		if len(sceneIDs) > 0 {
			marks := strings.TrimSuffix(strings.Repeat("?,", len(sceneIDs)), ",")
			args := make([]any, 0, len(sceneIDs)+1)
			args = append(args, newer.featureVersion)
			for _, sceneID := range sceneIDs {
				args = append(args, sceneID)
			}
			cr, err := fdb.Query(`
				SELECT ef.entity_id, fd.name
				FROM entity_feature ef
				JOIN feature_definition fd USING(feature_id)
				WHERE ef.feature_version=? AND ef.entity_id IN (`+marks+`)`, args...)
			if err != nil {
				fdb.Close()
				return unavailable(), nil
			}
			for cr.Next() {
				var sceneID, name string
				if err := cr.Scan(&sceneID, &name); err != nil {
					cr.Close()
					fdb.Close()
					return jvNull(), err
				}
				namesByScene[sceneID] = append(namesByScene[sceneID], name)
			}
			cr.Close()
			if err := cr.Err(); err != nil {
				fdb.Close()
				return jvNull(), err
			}
		}
		// viaFeedback counts the user's own model-teaching feedback on scenes
		// that carry the same entity, so the "why" shows whether a move is
		// tied to what was rated/picked (0 means it came only from a pair's
		// differing feature or a tag preference, not a rated scene).
		viaFeedback := func(entityKind, entityID string) int {
			table, column := "scene_tag", "tag_id"
			if entityKind == "performer" {
				table, column = "scene_performer", "performer_id"
			}
			marks := strings.TrimSuffix(strings.Repeat("?,", len(impactFeedbackTypes)), ",")
			args := make([]any, 0, len(impactFeedbackTypes)+1)
			args = append(args, entityID)
			for _, t := range impactFeedbackTypes {
				args = append(args, t)
			}
			var n int
			err := db.QueryRow(fmt.Sprintf(`
				SELECT COUNT(DISTINCT f.scene_id)
				FROM %s t
				JOIN feedback f ON f.scene_id = t.scene_id
				WHERE t.%s = ? AND f.reversed_by_id IS NULL AND f.feedback_type IN (%s)`,
				table, column, marks), args...).Scan(&n)
			if err != nil {
				return 0
			}
			return n
		}
		for _, sceneID := range sceneIDs {
			var cands []contributor
			directDelta := newDirect[sceneID] - oldDirect[sceneID]
			if math.Abs(directDelta) > IMPACT_MIN_CONTRIBUTION {
				cands = append(cands, contributor{kind: "direct", id: sceneID, name: "Your direct feedback", delta: directDelta})
			}
			for _, name := range namesByScene[sceneID] {
				delta, ok := contributionDeltas[name]
				if !ok {
					continue
				}
				c := contributor{delta: delta}
				if strings.HasPrefix(name, "performer:") {
					c.kind, c.id = "performer", name[len("performer:"):]
					if n, ok := performerNames[c.id]; ok {
						c.name = n
					} else {
						c.name = c.id
					}
				} else {
					c.kind, c.id = "tag", name[len("tag:"):]
					if n, ok := tagNames[c.id]; ok {
						c.name = n
					} else {
						c.name = c.id
					}
				}
				c.viaFeedback = viaFeedback(c.kind, c.id)
				cands = append(cands, c)
			}
			sort.Slice(cands, func(i, j int) bool {
				ai, aj := math.Abs(cands[i].delta), math.Abs(cands[j].delta)
				if ai != aj {
					return ai > aj
				}
				return cands[i].name < cands[j].name
			})
			if len(cands) > IMPACT_MAX_CONTRIBUTORS {
				cands = cands[:IMPACT_MAX_CONTRIBUTORS]
			}
			// Keep the direct-feedback entry first: it is the most specific.
			for i := 1; i < len(cands); i++ {
				if cands[i].kind == "direct" {
					cands[0], cands[i] = cands[i], cands[0]
					break
				}
			}
			sceneContributors[sceneID] = cands
		}
		// Approximate how much of each scene's move came from each source: the
		// user's own feedback, the generalization through tags, through
		// performers, and the residual (content similarity / studio /
		// structure). The model attributes a scene's feedback to every entity
		// it carries, so a single rating may nudge many tags at once.
		deltaByScene := map[string]float64{}
		for _, e := range promotedPool {
			deltaByScene[e.id] = e.delta
		}
		for _, e := range demotedPool {
			deltaByScene[e.id] = e.delta
		}
		for _, sceneID := range sceneIDs {
			var tagSum, performerSum float64
			directDelta := newDirect[sceneID] - oldDirect[sceneID]
			for _, name := range namesByScene[sceneID] {
				delta, ok := contributionDeltas[name]
				if !ok {
					continue
				}
				if strings.HasPrefix(name, "tag:") {
					tagSum += delta
				} else if strings.HasPrefix(name, "performer:") {
					performerSum += delta
				}
			}
			sceneDelta := deltaByScene[sceneID]
			sceneBreakdowns[sceneID] = map[string]float64{
				"your_feedback":        directDelta,
				"tag_preference":       tagSum,
				"performer_preference": performerSum,
				"content_similarity":   sceneDelta - directDelta - tagSum - performerSum,
			}
		}
		fdb.Close()
	}

	sceneEntryVal := func(e impactEntry) jVal {
		meta := sceneMeta[e.id]
		var title, date, studio jVal = jvNull(), jvNull(), jvNull()
		if meta != nil {
			title = jvStr(*meta[0])
			date = jvStr(*meta[1])
			studio = jvStr(*meta[2])
		}
		contribs := make([]jVal, 0, len(sceneContributors[e.id]))
		for _, c := range sceneContributors[e.id] {
			pairs := []jPair{
				jvKey("kind", jvStr(c.kind)),
				jvKey("id", jvStr(c.id)),
				jvKey("name", jvStr(c.name)),
				jvKey("delta", jvFloat(c.delta)),
			}
			if c.kind != "direct" {
				pairs = append(pairs, jvKey("via_feedback", jvInt(int64(c.viaFeedback))))
			}
			contribs = append(contribs, jvObj(pairs...))
		}
		bd := sceneBreakdowns[e.id]
		return jvObj(
			jvKey("scene_id", jvStr(e.id)),
			jvKey("title", title),
			jvKey("studio", studio),
			jvKey("date", date),
			jvKey("delta", jvFloat(e.delta)),
			jvKey("contributors", jVal{kind: jArr, arr: contribs}),
			jvKey("breakdown", jvObj(
				jvKey("your_feedback", jvFloat(bd["your_feedback"])),
				jvKey("tag_preference", jvFloat(bd["tag_preference"])),
				jvKey("performer_preference", jvFloat(bd["performer_preference"])),
				jvKey("content_similarity", jvFloat(bd["content_similarity"])),
			)),
		)
	}
	performerEntryVal := func(e impactEntry) jVal {
		name := jvNull()
		if n, ok := performerNames[e.id]; ok {
			name = jvStr(n)
		}
		return jvObj(
			jvKey("performer_id", jvStr(e.id)),
			jvKey("name", name),
			jvKey("delta", jvFloat(e.delta)),
		)
	}
	tagEntryVal := func(e impactEntry) jVal {
		name := jvNull()
		if n, ok := tagNames[e.id]; ok {
			name = jvStr(n)
		}
		return jvObj(
			jvKey("tag_id", jvStr(e.id)),
			jvKey("name", name),
			jvKey("delta", jvFloat(e.delta)),
		)
	}
	// Only feedback-driven movers are reported: a scene that moved purely
	// with the library re-sync (no direct feedback, no affinity move on
	// entities it carries) carries no signal about the user's taste.
	feedbackMovers := func(pool []impactEntry) []impactEntry {
		var out []impactEntry
		for _, e := range pool {
			if len(sceneContributors[e.id]) > 0 {
				out = append(out, e)
			}
		}
		if len(out) > IMPACT_TOP_SCENES {
			out = out[:IMPACT_TOP_SCENES]
		}
		return out
	}
	promoted := feedbackMovers(promotedPool)
	demoted := feedbackMovers(demotedPool)
	sceneGroup := func(up, down []impactEntry) jVal {
		return jvObj(jvKey("promoted", jvArrOf(up, sceneEntryVal)), jvKey("demoted", jvArrOf(down, sceneEntryVal)))
	}
	performerGroup := func(up, down []impactEntry) jVal {
		return jvObj(jvKey("promoted", jvArrOf(up, performerEntryVal)), jvKey("demoted", jvArrOf(down, performerEntryVal)))
	}
	tagGroup := func(up, down []impactEntry) jVal {
		return jvObj(jvKey("promoted", jvArrOf(up, tagEntryVal)), jvKey("demoted", jvArrOf(down, tagEntryVal)))
	}
	return jvObj(
		jvKey("available", jvBool(true)),
		jvKey("newer_model_id", jvStr(newer.modelID)),
		jvKey("older_model_id", jvStr(older.modelID)),
		jvKey("published_at_ms", jvInt(newer.publishedAtMs)),
		jvKey("scenes", sceneGroup(promoted, demoted)),
		jvKey("performers", performerGroup(performersUp, performersDown)),
		jvKey("tags", tagGroup(tagsUp, tagsDown)),
	), nil
}

func jvArrOf(entries []impactEntry, toVal func(impactEntry) jVal) jVal {
	out := make([]jVal, 0, len(entries))
	for _, e := range entries {
		out = append(out, toVal(e))
	}
	return jVal{kind: jArr, arr: out}
}

// impactEntry is one moved entity: id plus signed score delta.
type impactEntry struct {
	id    string
	delta float64
}

func entriesOf(deltas map[string]float64) []impactEntry {
	out := make([]impactEntry, 0, len(deltas))
	for id, delta := range deltas {
		out = append(out, impactEntry{id: id, delta: delta})
	}
	return out
}

// ranked splits deltas into the top upward movers (delta descending) and top
// downward movers (delta ascending), ties broken by id.
func ranked(entries []impactEntry, top int) (up, down []impactEntry) {
	return topEntries(entries, true, top), topEntries(entries, false, top)
}

func topEntries(entries []impactEntry, upward bool, top int) []impactEntry {
	filtered := make([]impactEntry, 0, len(entries))
	for _, e := range entries {
		if upward && e.delta > 0 {
			filtered = append(filtered, e)
		} else if !upward && e.delta < 0 {
			filtered = append(filtered, e)
		}
	}
	sort.Slice(filtered, func(i, j int) bool {
		if filtered[i].delta != filtered[j].delta {
			if upward {
				return filtered[i].delta > filtered[j].delta
			}
			return filtered[i].delta < filtered[j].delta
		}
		return filtered[i].id < filtered[j].id
	})
	if len(filtered) > top {
		filtered = filtered[:top]
	}
	return filtered
}
