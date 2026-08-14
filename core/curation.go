// Curation ops: get_curation_batch, submit_curation_ratings,
// get_curation_verdict, and get_tag_context_candidates — the Go mirror of
// curator/curation.py. Hypothesis mode draws a stratified 2x2 sample around a
// (base tag x context tag) pair with calibration anchors; explore mode
// greedily maximizes NEW interactive-tag coverage (rarity-weighted, studio
// penalty). Ratings live in feedback as feedback_type='curation_rating' with
// the batch/cell in payload_json; verdicts use a batch's own ratings only.
// Everything is deterministic (ORDER BY, sorted iteration, no RNG) so the
// differential gates compare byte-identically against Python.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

const (
	curationMinBudget               = 1
	curationMaxBudget               = 40
	curationDefaultBudget           = 20
	curationRatingMin               = 0
	curationRatingMax               = 10
	curationConfirmDelta            = 0.15
	curationConfirmMinN             = 10
	curationAnchorBandSize           = 200
	curationMaxItemTags             = 8
	curationDefaultMinSupport       = 20
	curationContrastMinLabeled      = 4
	curationExploreAnchors          = 3
	curationHypothesisAnchorFraction = 0.15
	curationHypothesisControlFraction = 0.15
	curationMaxLibraryRate           = 0.30
	curationContrastEvidenceScale    = 8.0
)

// suggestionExcludedCategories mirrors curation.SUGGESTION_EXCLUDED_CATEGORIES.
var suggestionExcludedCategories = map[string]bool{
	"Clothing": true, "Moods": true, "Locations": true, "Shot Type": true,
	"Surfaces": true, "Misc": true, "Accessories": true,
}

// curationExcludedCategories mirrors curation.EXCLUDED_CATEGORIES.
var curationExcludedCategories = map[string]bool{
	"Hair Color": true, "Hair Style": true, "Body Type": true, "Breasts": true,
	"Face": true, "Skin Tone": true, "Piercings": true, "Ass": true,
	"Genitals": true, "Height": true, "Tattoos": true, "Race": true,
}

// curationReasonTypes mirrors curation.REASON_TYPES.
var curationReasonTypes = map[string]bool{
	"metadata_wrong": true, "not_now": true, "contradicts_hypothesis": true,
	"performer_driven": true,
}

// curationHypothesisCells mirrors curation.HYPOTHESIS_CELLS.
var curationHypothesisCells = []string{"L&T", "L&!T", "!L&T", "!L&!T", "anchor"}

type curationItem struct {
	sceneID string
	cell    string
	anchor  bool
}

type curationContext struct {
	labels        map[string]bool
	sceneIDs      map[string]bool
	sceneTags       map[string]map[string]bool
	scenePerformers map[string]map[string]bool
	performerCounts map[string]int64
	performerName   map[string]string
	studio          map[string]string
	sceneTitle    map[string]string
	sceneDate     map[string]string
	sceneDetails  map[string]string
	tagCat        map[string]string
	tagName       map[string]string
	counts        map[string]int64
	appeal        map[string]float64
	blockedScenes map[string]bool
	metadataWrong map[string]bool
	interactive   map[string]bool
}

func (c *curationContext) rarity(tagID string) float64 {
	n := c.counts[tagID]
	if n < 1 {
		n = 1
	}
	return 1.0 / math.Sqrt(float64(n))
}

func (c *curationContext) isInteractive(tagID string) bool {
	return c.interactive[tagID]
}

func curationHalfUp(value float64) int64 {
	return int64(value + 0.5)
}

func curationMean(values []float64) float64 {
	if len(values) == 0 {
		return 0.0
	}
	var total float64
	for _, v := range values {
		total += v
	}
	return total / float64(len(values))
}

// loadCurationContext mirrors curation.curation_context.
func loadCurationContext(db dbx) (*curationContext, error) {
	labels, err := modelSceneLabels(db)
	if err != nil {
		return nil, err
	}
	ctx := &curationContext{
		labels:        make(map[string]bool, len(labels)),
		sceneIDs:      map[string]bool{},
		sceneTags:       map[string]map[string]bool{},
		scenePerformers: map[string]map[string]bool{},
		performerCounts: map[string]int64{},
		performerName:   map[string]string{},
		studio:          map[string]string{},
		sceneTitle:    map[string]string{},
		sceneDate:     map[string]string{},
		sceneDetails:  map[string]string{},
		tagCat:        map[string]string{},
		tagName:       map[string]string{},
		counts:        map[string]int64{},
		appeal:        map[string]float64{},
		blockedScenes: map[string]bool{},
		metadataWrong: map[string]bool{},
		interactive:   map[string]bool{},
	}
	for sceneID := range labels {
		ctx.labels[sceneID] = true
	}
	rows, err := db.Query(`SELECT scene_id FROM source_scene ORDER BY scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		ctx.sceneIDs[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, tag_id FROM scene_tag ORDER BY scene_id, tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, tagID string
		if err := rows.Scan(&sceneID, &tagID); err != nil {
			rows.Close()
			return nil, err
		}
		if ctx.sceneTags[sceneID] == nil {
			ctx.sceneTags[sceneID] = map[string]bool{}
		}
		ctx.sceneTags[sceneID][tagID] = true
		ctx.counts[tagID]++
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, performerID string
		if err := rows.Scan(&sceneID, &performerID); err != nil {
			rows.Close()
			return nil, err
		}
		if ctx.scenePerformers[sceneID] == nil {
			ctx.scenePerformers[sceneID] = map[string]bool{}
		}
		ctx.scenePerformers[sceneID][performerID] = true
		ctx.performerCounts[performerID]++
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT performer_id, name FROM source_performer ORDER BY performer_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var performerID, name string
		if err := rows.Scan(&performerID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		ctx.performerName[performerID] = name
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`
SELECT ss.scene_id, ss.title, ss.scene_date, ss.details, s.name FROM source_scene ss
LEFT JOIN source_studio s ON s.studio_id=ss.studio_id
ORDER BY ss.scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var title, sceneDate, details, name sql.NullString
		if err := rows.Scan(&sceneID, &title, &sceneDate, &details, &name); err != nil {
			rows.Close()
			return nil, err
		}
		if name.Valid {
			ctx.studio[sceneID] = name.String
		}
		if title.Valid {
			ctx.sceneTitle[sceneID] = title.String
		}
		if sceneDate.Valid {
			ctx.sceneDate[sceneID] = sceneDate.String
		}
		if details.Valid {
			ctx.sceneDetails[sceneID] = details.String
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT tag_id, name FROM source_tag ORDER BY tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, name sql.NullString
		if err := rows.Scan(&tagID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		tagName := tagID.String
		if name.Valid && name.String != "" {
			tagName = name.String
		}
		ctx.tagName[tagID.String] = tagName
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var snapshot sql.NullString
	if err := db.QueryRow(
		`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`,
	).Scan(&snapshot); err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	if snapshot.Valid {
		rows, err = db.Query(`
SELECT ttm.local_tag_id, c.name AS category
FROM tag_taxonomy_match ttm
JOIN taxonomy_category c
  ON c.category_id=ttm.external_category_id
 AND c.snapshot_id=ttm.snapshot_id
WHERE ttm.snapshot_id=?
ORDER BY ttm.local_tag_id`, snapshot.String)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var localTagID, category string
			if err := rows.Scan(&localTagID, &category); err != nil {
				rows.Close()
				return nil, err
			}
			ctx.tagCat[localTagID] = category
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	rows, err = db.Query(
		`SELECT tag_id FROM direct_tag_preference WHERE blocked=1 ORDER BY tag_id`,
	)
	if err != nil {
		return nil, err
	}
	var blockedTags []string
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			rows.Close()
			return nil, err
		}
		blockedTags = append(blockedTags, tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(blockedTags) > 0 {
		placeholders := strings.TrimSuffix(strings.Repeat("?,", len(blockedTags)), ",")
		args := make([]any, len(blockedTags))
		for i, tagID := range blockedTags {
			args[i] = tagID
		}
		rows, err = db.Query(
			`SELECT DISTINCT scene_id FROM scene_tag WHERE tag_id IN (`+placeholders+`)`,
			args...,
		)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			if err := rows.Scan(&sceneID); err != nil {
				rows.Close()
				return nil, err
			}
			ctx.blockedScenes[sceneID] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	rows, err = db.Query(`
SELECT DISTINCT scene_id FROM feedback
WHERE feedback_type='metadata_wrong' AND reversed_by_id IS NULL`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		ctx.metadataWrong[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var modelID sql.NullString
	if err := db.QueryRow(`
SELECT model_id FROM model_version WHERE status='published'
ORDER BY published_at_ms DESC LIMIT 1`).Scan(&modelID); err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	if modelID.Valid {
		rows, err = db.Query(
			`SELECT scene_id, general_appeal FROM model_scene_score WHERE model_id=?`,
			modelID.String,
		)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			var appeal float64
			if err := rows.Scan(&sceneID, &appeal); err != nil {
				rows.Close()
				return nil, err
			}
			ctx.appeal[sceneID] = appeal
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	for tagID, category := range ctx.tagCat {
		if !curationExcludedCategories[category] {
			ctx.interactive[tagID] = true
		}
	}
	return ctx, nil
}

func curationUnlabeledPool(ctx *curationContext, scenes map[string]bool) []string {
	var out []string
	for sceneID := range scenes {
		if !ctx.labels[sceneID] && !ctx.blockedScenes[sceneID] && !ctx.metadataWrong[sceneID] {
			out = append(out, sceneID)
		}
	}
	sort.Strings(out)
	return out
}

func curationStudioName(ctx *curationContext, sceneID string) string {
	if name := ctx.studio[sceneID]; name != "" {
		return name
	}
	return "?"
}

// curationRoundRobin mirrors curation._round_robin: one scene per studio
// before repeats, deterministic order.
func curationRoundRobin(pool []string, quota int, ctx *curationContext) []string {
	byStudio := map[string][]string{}
	for _, sceneID := range pool {
		name := curationStudioName(ctx, sceneID)
		byStudio[name] = append(byStudio[name], sceneID)
	}
	names := make([]string, 0, len(byStudio))
	for name, sids := range byStudio {
		sort.Strings(sids)
		names = append(names, name)
	}
	sort.Strings(names)
	var chosen []string
	for _, name := range names {
		if len(chosen) >= quota {
			break
		}
		chosen = append(chosen, byStudio[name][0])
		byStudio[name] = byStudio[name][1:]
	}
	for len(chosen) < quota {
		progressed := false
		for _, name := range names {
			if len(chosen) >= quota {
				break
			}
			if len(byStudio[name]) > 0 {
				chosen = append(chosen, byStudio[name][0])
				byStudio[name] = byStudio[name][1:]
				progressed = true
			}
		}
		if !progressed {
			break
		}
	}
	return chosen
}

// curationAnchorBand mirrors curation._anchor_band: the appeal middle band.
func curationAnchorBand(pool []string, ctx *curationContext) []string {
	ordered := append([]string(nil), pool...)
	sort.Slice(ordered, func(i, j int) bool {
		a, b := ctx.appeal[ordered[i]], ctx.appeal[ordered[j]]
		if a != b {
			return a < b
		}
		return ordered[i] < ordered[j]
	})
	mid := len(ordered) / 2
	lo := mid - curationAnchorBandSize
	if lo < 0 {
		lo = 0
	}
	hi := mid + curationAnchorBandSize
	if hi > len(ordered) {
		hi = len(ordered)
	}
	return ordered[lo:hi]
}

func curationItemTags(ctx *curationContext, sceneID string) jVal {
	var tags []string
	for tagID := range ctx.sceneTags[sceneID] {
		if ctx.isInteractive(tagID) {
			tags = append(tags, tagID)
		}
	}
	sort.Slice(tags, func(i, j int) bool {
		a, b := ctx.tagName[tags[i]], ctx.tagName[tags[j]]
		if a == "" {
			a = tags[i]
		}
		if b == "" {
			b = tags[j]
		}
		if a != b {
			return a < b
		}
		return tags[i] < tags[j]
	})
	if len(tags) > curationMaxItemTags {
		tags = tags[:curationMaxItemTags]
	}
	out := jvArr()
	for _, tagID := range tags {
		category := jvNull()
		if cat := ctx.tagCat[tagID]; cat != "" {
			category = jvStr(cat)
		}
		name := ctx.tagName[tagID]
		if name == "" {
			name = tagID
		}
		out.arr = append(out.arr, jvObj(
			jvKey("tag_id", jvStr(tagID)),
			jvKey("name", jvStr(name)),
			jvKey("category", category),
		))
	}
	return out
}

// curationSelectHypothesis mirrors curation.select_hypothesis.
func curationSelectHypothesis(
	ctx *curationContext, baseTag, contextTag string, budget int,
) ([]curationItem, map[string]int64) {
	base := map[string]bool{}
	context := map[string]bool{}
	for sceneID, tags := range ctx.sceneTags {
		if tags[baseTag] {
			base[sceneID] = true
		}
		if tags[contextTag] {
			context[sceneID] = true
		}
	}
	pools := map[string][]string{}
	var poolKeys []string
	for _, cell := range []struct {
		name  string
		scenes map[string]bool
	}{
		{"L&T", intersect(base, context)},
		{"L&!T", difference(base, context)},
		{"!L&T", difference(context, base)},
		{"!L&!T", difference(ctx.sceneIDs, union(base, context))},
	} {
		pool := curationUnlabeledPool(ctx, cell.scenes)
		pools[cell.name] = pool
		poolKeys = append(poolKeys, cell.name)
	}
	anchors := curationHalfUp(float64(budget) * curationHypothesisAnchorFraction)
	if anchors < 1 {
		anchors = 1
	}
	controls := curationHalfUp(float64(budget) * curationHypothesisControlFraction)
	if controls < 1 {
		controls = 1
	}
	if controls > int64(budget)-anchors {
		controls = int64(budget) - anchors
	}
	contrast := int64(budget) - anchors - controls
	contrastLT := contrast/2 + contrast%2
	contrastLNT := contrast / 2
	items := []curationItem{}
	for _, cell := range []struct {
		name  string
		quota int64
	}{
		{"L&T", contrastLT},
		{"L&!T", contrastLNT},
		{"!L&T", controls},
	} {
		for _, sceneID := range curationRoundRobin(pools[cell.name], int(cell.quota), ctx) {
			items = append(items, curationItem{sceneID: sceneID, cell: cell.name})
		}
	}
	anchorPool := curationAnchorBand(pools["!L&!T"], ctx)
	for _, sceneID := range curationRoundRobin(anchorPool, int(anchors), ctx) {
		items = append(items, curationItem{sceneID: sceneID, cell: "anchor", anchor: true})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].cell != items[j].cell {
			return items[i].cell < items[j].cell
		}
		return items[i].sceneID < items[j].sceneID
	})
	pool := map[string]int64{}
	for _, name := range poolKeys {
		pool[name] = int64(len(pools[name]))
	}
	return items, pool
}

func intersect(a, b map[string]bool) map[string]bool {
	out := map[string]bool{}
	for k := range a {
		if b[k] {
			out[k] = true
		}
	}
	return out
}

func difference(a, b map[string]bool) map[string]bool {
	out := map[string]bool{}
	for k := range a {
		if !b[k] {
			out[k] = true
		}
	}
	return out
}

func union(a, b map[string]bool) map[string]bool {
	out := map[string]bool{}
	for k := range a {
		out[k] = true
	}
	for k := range b {
		out[k] = true
	}
	return out
}

// curationSelectExplore mirrors curation.select_explore.
func curationSelectExplore(
	ctx *curationContext, budget int,
) ([]curationItem, map[string]int64) {
	pool := curationUnlabeledPool(ctx, ctx.sceneIDs)
	anchors := curationExploreAnchors
	if budget/2 < anchors {
		anchors = budget / 2
	}
	exploreBudget := budget - anchors
	tagScenes := map[string][]string{}
	for _, sceneID := range pool {
		for tagID := range ctx.sceneTags[sceneID] {
			if ctx.isInteractive(tagID) {
				tagScenes[tagID] = append(tagScenes[tagID], sceneID)
			}
		}
	}
	value := map[string]float64{}
	for _, sceneID := range pool {
		var total float64
		for tagID := range ctx.sceneTags[sceneID] {
			if ctx.isInteractive(tagID) {
				total += ctx.rarity(tagID)
			}
		}
		value[sceneID] = total
	}
	covered := map[string]bool{}
	chosenSet := map[string]bool{}
	chosenStudios := map[string]bool{}
	var chosen []string
	for len(chosen) < exploreBudget {
		best, bestValue := "", -1.0
		for _, sceneID := range pool {
			if chosenSet[sceneID] {
				continue
			}
			v := value[sceneID]
			if chosenStudios[curationStudioName(ctx, sceneID)] {
				v *= 0.5
			}
			if v > bestValue {
				best, bestValue = sceneID, v
			}
		}
		if best == "" || bestValue <= 0 {
			break
		}
		chosen = append(chosen, best)
		chosenSet[best] = true
		chosenStudios[curationStudioName(ctx, best)] = true
		for tagID := range ctx.sceneTags[best] {
			if ctx.isInteractive(tagID) && !covered[tagID] {
				covered[tagID] = true
				for _, other := range tagScenes[tagID] {
					if _, ok := value[other]; ok {
						value[other] -= ctx.rarity(tagID)
					}
				}
			}
		}
	}
	var anchorPool []string
	for _, sceneID := range pool {
		if !chosenSet[sceneID] {
			anchorPool = append(anchorPool, sceneID)
		}
	}
	items := []curationItem{}
	for _, sceneID := range chosen {
		items = append(items, curationItem{sceneID: sceneID, cell: "explore"})
	}
	for _, sceneID := range curationRoundRobin(curationAnchorBand(anchorPool, ctx), anchors, ctx) {
		items = append(items, curationItem{sceneID: sceneID, cell: "anchor", anchor: true})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].cell != items[j].cell {
			return items[i].cell < items[j].cell
		}
		return items[i].sceneID < items[j].sceneID
	})
	return items, map[string]int64{
		"candidates":       int64(len(pool)),
		"interactive_tags": int64(len(ctx.interactive)),
	}
}

// createCurationBatch mirrors curation.create_batch.
func createCurationBatch(db dbx, mode, baseTagID, contextTagID string, budget int) (jVal, error) {
	if mode != "hypothesis" && mode != "explore" {
		return jvNull(), fmt.Errorf("mode must be 'hypothesis' or 'explore'")
	}
	if budget < curationMinBudget || budget > curationMaxBudget {
		return jvNull(), fmt.Errorf("budget must be from %d to %d", curationMinBudget, curationMaxBudget)
	}
	if mode == "hypothesis" {
		if baseTagID == "" || contextTagID == "" {
			return jvNull(), fmt.Errorf("hypothesis mode requires base_tag_id and context_tag_id")
		}
		if baseTagID == contextTagID {
			return jvNull(), fmt.Errorf("base_tag_id and context_tag_id must differ")
		}
	}
	for _, tagID := range []string{baseTagID, contextTagID} {
		if tagID == "" {
			continue
		}
		var probe int
		err := db.QueryRow(`SELECT 1 FROM source_tag WHERE tag_id=?`, tagID).Scan(&probe)
		if err == sql.ErrNoRows {
			return jvNull(), fmt.Errorf("unknown tag: %s", tagID)
		}
		if err != nil {
			return jvNull(), err
		}
	}
	ctx, err := loadCurationContext(db)
	if err != nil {
		return jvNull(), err
	}
	var items []curationItem
	var pool map[string]int64
	var policy string
	if mode == "hypothesis" {
		items, pool = curationSelectHypothesis(ctx, baseTagID, contextTagID, budget)
		anchors := 0
		for _, item := range items {
			if item.anchor {
				anchors++
			}
		}
		policy = fmt.Sprintf(
			"stratified 2x2, studio round-robin, unlabeled only, %d calibration anchors",
			anchors,
		)
	} else {
		items, pool = curationSelectExplore(ctx, budget)
		policy = "max-coverage interactive tags, rarity-weighted, studio penalty, unlabeled only"
	}
	batchID := uuid4()
	now := nowMs()
	payloadJSON, err := marshalSorted(policy, pool)
	if err != nil {
		return jvNull(), err
	}
	err = withTxn(db, func(conn *sql.Conn) error {
		var baseArg, contextArg any
		if baseTagID != "" {
			baseArg = baseTagID
		}
		if contextTagID != "" {
			contextArg = contextTagID
		}
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO curation_batch(
    batch_id, mode, base_tag_id, context_tag_id, budget, status,
    created_at_ms, payload_json
) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)`,
			batchID, mode, baseArg, contextArg, budget, now, payloadJSON); err != nil {
			return err
		}
		for _, item := range items {
			anchor := 0
			if item.anchor {
				anchor = 1
			}
			if _, err := conn.ExecContext(context.Background(), `
INSERT INTO curation_batch_item(batch_id, scene_id, cell, anchor)
VALUES (?, ?, ?, ?)`, batchID, item.sceneID, item.cell, anchor); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	itemsOut := jvArr()
	for _, item := range items {
		titleVal, studioVal, dateVal, detailsVal := jvNull(), jvNull(), jvNull(), jvNull()
		if title := ctx.sceneTitle[item.sceneID]; title != "" {
			titleVal = jvStr(title)
		}
		if studio := ctx.studio[item.sceneID]; studio != "" {
			studioVal = jvStr(studio)
		}
		if date := ctx.sceneDate[item.sceneID]; date != "" {
			dateVal = jvStr(date)
		}
		if details := ctx.sceneDetails[item.sceneID]; details != "" {
			detailsVal = jvStr(details)
		}
		itemsOut.arr = append(itemsOut.arr, jvObj(
			jvKey("scene_id", jvStr(item.sceneID)),
			jvKey("cell", jvStr(item.cell)),
			jvKey("anchor", jvBool(item.anchor)),
			jvKey("title", titleVal),
			jvKey("studio", studioVal),
			jvKey("date", dateVal),
			jvKey("details", detailsVal),
			jvKey("tags", curationItemTags(ctx, item.sceneID)),
		))
	}
	baseVal, contextVal := jvNull(), jvNull()
	if baseTagID != "" {
		baseVal = jvStr(baseTagID)
	}
	if contextTagID != "" {
		contextVal = jvStr(contextTagID)
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("batch_id", jvStr(batchID)),
		jvKey("mode", jvStr(mode)),
		jvKey("base_tag_id", baseVal),
		jvKey("context_tag_id", contextVal),
		jvKey("budget", jvInt(int64(budget))),
		jvKey("items", itemsOut),
		jvKey("pool", poolToJVal(pool)),
		jvKey("policy", jvStr(policy)),
	), nil
}

func marshalSorted(policy string, pool map[string]int64) (string, error) {
	payload := jvObj(
		jvKey("policy", jvStr(policy)),
		jvKey("pool", poolToJVal(pool)),
	)
	return payload.marshalSortedKeys(), nil
}

func poolToJVal(pool map[string]int64) jVal {
	out := jvObj()
	for _, key := range sortedMapKeys(pool) {
		out.obj = append(out.obj, jPair{key: key, val: jvInt(pool[key])})
	}
	return out
}


func curationBatchItems(db dbx, batchID string) (map[string]struct {
	cell   string
	rated  bool
}, error) {
	rows, err := db.Query(
		`SELECT scene_id, cell, rated FROM curation_batch_item WHERE batch_id=?`,
		batchID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]struct {
		cell  string
		rated bool
	}{}
	for rows.Next() {
		var sceneID, cell string
		var rated int64
		if err := rows.Scan(&sceneID, &cell, &rated); err != nil {
			return nil, err
		}
		out[sceneID] = struct {
			cell  string
			rated bool
		}{cell: cell, rated: rated != 0}
	}
	return out, rows.Err()
}

// submitCurationRatings mirrors curation.submit_ratings.
func submitCurationRatings(db dbx, batchID string, ratings jVal) (jVal, error) {
	if batchID == "" {
		return jvNull(), fmt.Errorf("batch_id is required")
	}
	var status string
	err := db.QueryRow(
		`SELECT status FROM curation_batch WHERE batch_id=?`, batchID,
	).Scan(&status)
	if err == sql.ErrNoRows {
		return jvNull(), fmt.Errorf("unknown batch: %s", batchID)
	}
	if err != nil {
		return jvNull(), err
	}
	if status != "open" {
		return jvNull(), fmt.Errorf("batch is not open: %s", status)
	}
	items, err := curationBatchItems(db, batchID)
	if err != nil {
		return jvNull(), err
	}
	if len(items) == 0 {
		return jvNull(), fmt.Errorf("unknown batch: %s", batchID)
	}
	seen := map[string]bool{}
	type normalizedRating struct {
		sceneID string
		value   int64
		reason  string
		hasReason bool
	}
	var normalized []normalizedRating
	if ratings.kind != jArr {
		return jvNull(), fmt.Errorf("ratings must be a list")
	}
	for _, entry := range ratings.arr {
		if entry.kind != jObj {
			return jvNull(), fmt.Errorf("each rating must be an object with scene_id, value, and reason")
		}
		sceneID := pythonStrOrEmpty(entry.get("scene_id"))
		if sceneID == "" {
			return jvNull(), fmt.Errorf("scene is not in this batch: %s", sceneID)
		}
		item, ok := items[sceneID]
		if !ok {
			return jvNull(), fmt.Errorf("scene is not in this batch: %s", sceneID)
		}
		if seen[sceneID] {
			return jvNull(), fmt.Errorf("duplicate rating for scene: %s", sceneID)
		}
		if item.rated {
			return jvNull(), fmt.Errorf("scene already rated in this batch: %s", sceneID)
		}
		rawValue := entry.get("value")
		if rawValue.kind == jBool || rawValue.kind != jNum || rawValue.kindName() != "int" {
			return jvNull(), fmt.Errorf("rating value must be an integer")
		}
		value, err := strconv.ParseInt(rawValue.num, 10, 64)
		if err != nil {
			return jvNull(), fmt.Errorf("rating value must be an integer")
		}
		if value < curationRatingMin || value > curationRatingMax {
			return jvNull(), fmt.Errorf("rating value must be from %d to %d",
				curationRatingMin, curationRatingMax)
		}
		reason := entry.get("reason")
		reasonStr := ""
		hasReason := false
		if reason.kind != jNull {
			if reason.kind != jStr {
				return jvNull(), fmt.Errorf("unknown rating reason: %s", curationValueStr(reason))
			}
			if !curationReasonTypes[reason.s] {
				return jvNull(), fmt.Errorf("unknown rating reason: %s", reason.s)
			}
			reasonStr = reason.s
			hasReason = true
		}
		seen[sceneID] = true
		normalized = append(normalized, normalizedRating{
			sceneID: sceneID, value: value, reason: reasonStr, hasReason: hasReason,
		})
	}
	if len(normalized) == 0 {
		return jvNull(), fmt.Errorf("ratings must not be empty")
	}
	now := nowMs()
	err = withTxn(db, func(conn *sql.Conn) error {
		for _, rating := range normalized {
			item := items[rating.sceneID]
			payload := jvObj(
				jvKey("batch_id", jvStr(batchID)),
				jvKey("cell", jvStr(item.cell)),
			)
			if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, 'curation_rating', ?, ?, NULL, NULL, ?)`,
				nowStrID(now), rating.sceneID, strconv.FormatInt(rating.value, 10), now,
				payload.marshalSortedKeys()); err != nil {
				return err
			}
			if rating.hasReason {
				if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, ?, NULL, ?, NULL, NULL, '{}')`,
					nowStrID(now), rating.sceneID, rating.reason, now); err != nil {
					return err
				}
			}
			if _, err := conn.ExecContext(context.Background(), `
UPDATE curation_batch_item SET rated=1 WHERE batch_id=? AND scene_id=?`,
				batchID, rating.sceneID); err != nil {
				return err
			}
		}
		var remaining int64
		if err := conn.QueryRowContext(context.Background(), `
SELECT count(*) FROM curation_batch_item WHERE batch_id=? AND rated=0`,
			batchID).Scan(&remaining); err != nil {
			return err
		}
		if remaining == 0 {
			if _, err := conn.ExecContext(context.Background(), `
UPDATE curation_batch SET status='rated' WHERE batch_id=?`, batchID); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	statusOut := "open"
	remaining, err := curationRemaining(db, batchID)
	if err != nil {
		return jvNull(), err
	}
	if remaining == 0 {
		statusOut = "rated"
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("accepted", jvInt(int64(len(normalized)))),
		jvKey("batch_status", jvStr(statusOut)),
	), nil
}

func curationRemaining(db dbx, batchID string) (int64, error) {
	var remaining int64
	err := db.QueryRow(
		`SELECT count(*) FROM curation_batch_item WHERE batch_id=? AND rated=0`,
		batchID,
	).Scan(&remaining)
	return remaining, err
}

func nowStrID(now int64) string {
	return fmt.Sprintf("%d-%s", now, uuid4())
}

// curationBatchRatings mirrors curation._batch_ratings. Ratings marked with a
// reason (metadata_wrong or contradicts_hypothesis) are excluded: those scenes
// are not valid instances of the cell they were sorted into.
func curationBatchRatings(db dbx, batchID string) (map[string]float64, error) {
	excluded := map[string]bool{}
	rows, err := db.Query(`
SELECT DISTINCT scene_id FROM feedback
WHERE feedback_type IN ('metadata_wrong', 'contradicts_hypothesis', 'performer_driven')
  AND reversed_by_id IS NULL`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		excluded[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := map[string]float64{}
	rows, err = db.Query(`
SELECT scene_id, value, payload_json FROM feedback
WHERE feedback_type='curation_rating' AND reversed_by_id IS NULL`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID string
		var value, payloadJSON sql.NullString
		if err := rows.Scan(&sceneID, &value, &payloadJSON); err != nil {
			return nil, err
		}
		if !value.Valid {
			continue
		}
		if excluded[sceneID] {
			continue
		}
		payload, err := parseJSON([]byte(payloadJSON.String))
		if err != nil {
			continue
		}
		if pythonStrOrEmpty(payload.get("batch_id")) != batchID {
			continue
		}
		rating, err := strconv.ParseInt(value.String, 10, 64)
		if err != nil || rating < curationRatingMin || rating > curationRatingMax {
			continue
		}
		out[sceneID] = (float64(rating) - 5) / 5
	}
	return out, rows.Err()
}

// curationVerdict mirrors curation.verdict.
func curationVerdict(db dbx, batchID string) (jVal, error) {
	if batchID == "" {
		return jvNull(), fmt.Errorf("batch_id is required")
	}
	var mode string
	var baseTagID, contextTagID sql.NullString
	err := db.QueryRow(`
SELECT mode, base_tag_id, context_tag_id FROM curation_batch WHERE batch_id=?`,
		batchID).Scan(&mode, &baseTagID, &contextTagID)
	if err == sql.ErrNoRows {
		return jvNull(), fmt.Errorf("unknown batch: %s", batchID)
	}
	if err != nil {
		return jvNull(), err
	}
	items, err := curationBatchItems(db, batchID)
	if err != nil {
		return jvNull(), err
	}
	outcomes, err := curationBatchRatings(db, batchID)
	if err != nil {
		return jvNull(), err
	}
	if mode == "hypothesis" {
		byCell := map[string]*struct {
			values []float64
		}{}
		for _, cell := range curationHypothesisCells {
			byCell[cell] = &struct{ values []float64 }{}
		}
		for sceneID, item := range items {
			if outcome, ok := outcomes[sceneID]; ok {
				byCell[item.cell].values = append(byCell[item.cell].values, outcome)
			}
		}
		cells := jvArr()
		for _, cell := range curationHypothesisCells {
			values := byCell[cell].values
			mean := jvNull()
			if len(values) > 0 {
				mean = jvFloat(curationMean(values))
			}
			cells.arr = append(cells.arr, jvObj(
				jvKey("cell", jvStr(cell)),
				jvKey("n", jvInt(int64(len(values)))),
				jvKey("mean_outcome", mean),
			))
		}
		contrast := jvObj()
		if len(byCell["L&T"].values) > 0 && len(byCell["L&!T"].values) > 0 {
			delta := curationMean(byCell["L&T"].values) - curationMean(byCell["L&!T"].values)
			nTotal := int64(len(byCell["L&T"].values) + len(byCell["L&!T"].values))
			contrast = jvObj(
				jvKey("delta", jvFloat(delta)),
				jvKey("n_total", jvInt(nTotal)),
				jvKey("confirmed", jvBool(mathAbs(delta) >= curationConfirmDelta && nTotal >= curationConfirmMinN)),
			)
		}
		suggested := jvNull()
		if len(byCell["L&T"].values) > 0 {
			mean := curationMean(byCell["L&T"].values)
			value := float64(curationHalfUp(mean*2)) / 2.0
			if value > 1.0 {
				value = 1.0
			}
			if value < -1.0 {
				value = -1.0
			}
			baseVal, contextVal := "", ""
			if baseTagID.Valid {
				baseVal = baseTagID.String
			}
			if contextTagID.Valid {
				contextVal = contextTagID.String
			}
			suggested = jvObj(
				jvKey("base_tag_id", jvStr(baseVal)),
				jvKey("context_tag_id", jvStr(contextVal)),
				jvKey("value", jvFloat(value)),
			)
		}
		return jvObj(
			jvKey("schema_version", jvInt(1)),
			jvKey("batch_id", jvStr(batchID)),
			jvKey("mode", jvStr(mode)),
			jvKey("cells", cells),
			jvKey("contrast", contrast),
			jvKey("suggested_rule", suggested),
		), nil
	}
	// explore mode
	tagRows := map[string][]float64{}
	ratedScenes := make([]string, 0, len(outcomes))
	for sceneID := range outcomes {
		ratedScenes = append(ratedScenes, sceneID)
	}
	sort.Strings(ratedScenes)
	if len(ratedScenes) > 0 {
		placeholders := strings.TrimSuffix(strings.Repeat("?,", len(ratedScenes)), ",")
		args := make([]any, len(ratedScenes))
		for i, sceneID := range ratedScenes {
			args[i] = sceneID
		}
		rows, err := db.Query(
			`SELECT scene_id, tag_id FROM scene_tag WHERE scene_id IN (`+placeholders+`) ORDER BY scene_id, tag_id`,
			args...,
		)
		if err != nil {
			return jvNull(), err
		}
		for rows.Next() {
			var sceneID, tagID string
			if err := rows.Scan(&sceneID, &tagID); err != nil {
				rows.Close()
				return jvNull(), err
			}
			tagRows[tagID] = append(tagRows[tagID], outcomes[sceneID])
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}
	ctx, err := loadCurationContext(db)
	if err != nil {
		return jvNull(), err
	}
	type tagEntry struct {
		tagID    string
		mean     float64
	}
	var entries []tagEntry
	for tagID, values := range tagRows {
		if len(values) >= 2 {
			entries = append(entries, tagEntry{tagID: tagID, mean: curationMean(values)})
		}
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].mean != entries[j].mean {
			return entries[i].mean > entries[j].mean
		}
		return entries[i].tagID < entries[j].tagID
	})
	entryJVal := func(entry tagEntry) jVal {
		category := jvNull()
		if cat := ctx.tagCat[entry.tagID]; cat != "" {
			category = jvStr(cat)
		}
		name := ctx.tagName[entry.tagID]
		if name == "" {
			name = entry.tagID
		}
		return jvObj(
			jvKey("tag_id", jvStr(entry.tagID)),
			jvKey("name", jvStr(name)),
			jvKey("category", category),
			jvKey("n", jvInt(int64(len(tagRows[entry.tagID])))),
			jvKey("mean_outcome", jvFloat(entry.mean)),
		)
	}
	top := jvArr()
	for _, entry := range entries[:minInt(len(entries), 10)] {
		top.arr = append(top.arr, entryJVal(entry))
	}
	bottom := jvArr()
	for i := len(entries) - 1; i >= 0 && len(bottom.arr) < 10; i-- {
		bottom.arr = append(bottom.arr, entryJVal(entries[i]))
	}
	values := make([]float64, 0, len(outcomes))
	for _, outcome := range outcomes {
		values = append(values, outcome)
	}
	summaryMean := jvNull()
	if len(values) > 0 {
		summaryMean = jvFloat(curationMean(values))
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("batch_id", jvStr(batchID)),
		jvKey("mode", jvStr(mode)),
		jvKey("summary", jvObj(
			jvKey("n", jvInt(int64(len(values)))),
			jvKey("mean_outcome", summaryMean),
		)),
		jvKey("top_tags", top),
		jvKey("bottom_tags", bottom),
	), nil
}

// tagContextCandidatesBody mirrors curation.tag_context_candidates.
func tagContextCandidatesBody(db dbx, tagID string, minSupport int) (jVal, error) {
	if tagID == "" {
		return jvNull(), fmt.Errorf("tag_id is required")
	}
	var probe int
	err := db.QueryRow(`SELECT 1 FROM source_tag WHERE tag_id=?`, tagID).Scan(&probe)
	if err == sql.ErrNoRows {
		return jvNull(), fmt.Errorf("unknown tag: %s", tagID)
	}
	if err != nil {
		return jvNull(), err
	}
	if minSupport < 1 {
		return jvNull(), fmt.Errorf("min_support must be at least 1")
	}
	ctx, err := loadCurationContext(db)
	if err != nil {
		return jvNull(), err
	}
	labels, err := modelSceneLabels(db)
	if err != nil {
		return jvNull(), err
	}
	baseScenes := map[string]bool{}
	for sceneID, tags := range ctx.sceneTags {
		if tags[tagID] {
			baseScenes[sceneID] = true
		}
	}
	labeledBase := map[string]float64{}
	for sceneID := range baseScenes {
		if label, ok := labels[sceneID]; ok {
			labeledBase[sceneID] = label.outcome
		}
	}
	cooc := map[string]int64{}
	for sceneID := range baseScenes {
		for t := range ctx.sceneTags[sceneID] {
			if t != tagID && ctx.isInteractive(t) {
				cooc[t]++
			}
		}
	}
	rowsOut := jvArr()
	type candidate struct {
		tagID     string
		cooccur   int64
		contrast  *float64
	}
	var candidates []candidate
	for t, n := range cooc {
		if n < int64(minSupport) {
			continue
		}
		totalScenes := float64(len(ctx.sceneIDs))
		if totalScenes < 1 {
			totalScenes = 1
		}
		if float64(ctx.counts[t])/totalScenes >= curationMaxLibraryRate {
			continue // ubiquitous tags cannot discriminate any relationship
		}
		if strings.HasPrefix(ctx.tagName[t], "[") {
			continue // sync-artifact tags ([Timestamp: Synced]...) are junk
		}
		if suggestionExcludedCategories[ctx.tagCat[t]] {
			continue // weak-interaction categories are not hypotheses
		}
		var withT, withoutT []float64
		for sceneID, outcome := range labeledBase {
			if ctx.sceneTags[sceneID][t] {
				withT = append(withT, outcome)
			} else {
				withoutT = append(withoutT, outcome)
			}
		}
		cand := candidate{tagID: t, cooccur: n}
		if len(labeledBase) >= curationContrastMinLabeled && len(withT) > 0 && len(withoutT) > 0 {
			raw := curationMean(withT) - curationMean(withoutT)
			evidence := float64(minInt(len(withT), len(withoutT)))
			factor := evidence / curationContrastEvidenceScale
			if factor > 1.0 {
				factor = 1.0
			}
			delta := raw * factor
			cand.contrast = &delta
		}
		candidates = append(candidates, cand)
	}
	sort.Slice(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		aPos := a.contrast != nil && *a.contrast > 0
		bPos := b.contrast != nil && *b.contrast > 0
		if aPos != bPos {
			return aPos
		}
		aC, bC := 0.0, 0.0
		if a.contrast != nil {
			aC = *a.contrast
		}
		if b.contrast != nil {
			bC = *b.contrast
		}
		if aC != bC {
			return aC > bC
		}
		if a.cooccur != b.cooccur {
			return a.cooccur > b.cooccur
		}
		return ctx.tagName[a.tagID] < ctx.tagName[b.tagID]
	})
	for _, cand := range candidates {
		category := jvNull()
		if cat := ctx.tagCat[cand.tagID]; cat != "" {
			category = jvStr(cat)
		}
		name := ctx.tagName[cand.tagID]
		if name == "" {
			name = cand.tagID
		}
		contrast := jvNull()
		if cand.contrast != nil {
			contrast = jvFloat(*cand.contrast)
		}
		rowsOut.arr = append(rowsOut.arr, jvObj(
			jvKey("tag_id", jvStr(cand.tagID)),
			jvKey("name", jvStr(name)),
			jvKey("category", category),
			jvKey("cooccurrence", jvInt(cand.cooccur)),
			jvKey("rate", jvFloat(float64(cand.cooccur)/float64(maxInt64(1, int64(len(baseScenes)))))),
			jvKey("labeled_n", jvInt(int64(len(withCount(ctx, cand.tagID, labeledBase))))),
			jvKey("contrast", contrast),
		))
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("tag_id", jvStr(tagID)),
		jvKey("items", rowsOut),
	), nil
}

func withCount(ctx *curationContext, tagID string, labeledBase map[string]float64) []string {
	var out []string
	for sceneID := range labeledBase {
		if ctx.sceneTags[sceneID][tagID] {
			out = append(out, sceneID)
		}
	}
	return out
}

// curationValueStr mirrors str(value) for decoded JSON values in error text.
func curationValueStr(v jVal) string {
	switch v.kind {
	case jStr:
		return v.s
	case jNum:
		return v.num
	case jBool:
		if v.b {
			return "True"
		}
		return "False"
	default:
		return v.kindName()
	}
}


// opGetCurationBatch mirrors backend.py's get_curation_batch branch.
func opGetCurationBatch(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_curation_batch",
		func(settings jVal) (jVal, error) { return curationBatchBody(pluginDir, payload, settings) })
}

func curationBatchBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	mode := pythonStrOrEmpty(args.get("mode"))
	baseTagID := pythonStrOrEmpty(args.get("base_tag_id"))
	contextTagID := pythonStrOrEmpty(args.get("context_tag_id"))
	budget := int(argsInt(args, "budget", curationDefaultBudget))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return createCurationBatch(db, mode, baseTagID, contextTagID, budget)
}

// opSubmitCurationRatings mirrors backend.py's submit_curation_ratings branch.
func opSubmitCurationRatings(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_curation_ratings",
		func(settings jVal) (jVal, error) { return submitCurationRatingsBody(pluginDir, payload, settings) })
}

func submitCurationRatingsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	batchID := pythonStrOrEmpty(args.get("batch_id"))
	ratings := args.get("ratings")
	if ratings.kind != jArr {
		return jvNull(), fmt.Errorf("ratings must be a list")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return submitCurationRatings(db, batchID, ratings)
}

// opGetCurationVerdict mirrors backend.py's get_curation_verdict branch.
func opGetCurationVerdict(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_curation_verdict",
		func(settings jVal) (jVal, error) { return curationVerdictBody(pluginDir, payload, settings) })
}

func curationVerdictBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	batchID := pythonStrOrEmpty(args.get("batch_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return curationVerdict(db, batchID)
}

// opGetTagContextCandidates mirrors backend.py's get_tag_context_candidates branch.
func opGetTagContextCandidates(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_tag_context_candidates",
		func(settings jVal) (jVal, error) { return tagContextCandidatesBodyOp(pluginDir, payload, settings) })
}

func tagContextCandidatesBodyOp(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	tagID := pythonStrOrEmpty(args.get("tag_id"))
	minSupport := int(argsInt(args, "min_support", curationDefaultMinSupport))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return tagContextCandidatesBody(db, tagID, minSupport)
}

// keep the json import used (marshal helpers reference it indirectly).

// ── Pairwise picks (mirror of the curation.py pair section) ────────────────

const (
	pairMinBudget          = 4
	pairMaxBudget          = 20
	pairDefaultBudget      = 10
	pairMaxCandidates      = 20_000
	pairSceneCap           = 2
	pairDimensionFitShare  = 0.5
	pairEloK               = 16.0
	pairEloInitial         = 1500.0
)

var pairDimensions = map[string]bool{
	"tag": true, "performer": true, "studio": true, "orthogonal": true,
}

var pairPickValues = map[string]bool{"a": true, "b": true, "skip": true, "flag": true}

func pairRarity(ctx *curationContext, performerID string) float64 {
	n := ctx.performerCounts[performerID]
	if n < 1 {
		n = 1
	}
	return 1.0 / math.Sqrt(float64(n))
}

func sceneCoverage(ctx *curationContext, sceneID string) float64 {
	// Capped: the top few rare tags/performers decide coverage, so a scene
	// with many common tags does not outrank one with rare fetish tags.
	tags := make([]string, 0, len(ctx.sceneTags[sceneID]))
	for tagID := range ctx.sceneTags[sceneID] {
		if ctx.isInteractive(tagID) {
			tags = append(tags, tagID)
		}
	}
	sort.Slice(tags, func(i, j int) bool {
		ri, rj := ctx.rarity(tags[i]), ctx.rarity(tags[j])
		if ri != rj {
			return ri > rj
		}
		return tags[i] < tags[j]
	})
	if len(tags) > 5 {
		tags = tags[:5]
	}
	perfs := make([]string, 0, len(ctx.scenePerformers[sceneID]))
	for performerID := range ctx.scenePerformers[sceneID] {
		perfs = append(perfs, performerID)
	}
	sort.Slice(perfs, func(i, j int) bool {
		ri, rj := pairRarity(ctx, perfs[i]), pairRarity(ctx, perfs[j])
		if ri != rj {
			return ri > rj
		}
		return perfs[i] < perfs[j]
	})
	if len(perfs) > 3 {
		perfs = perfs[:3]
	}
	var total float64
	for _, tagID := range tags {
		total += ctx.rarity(tagID)
	}
	for _, performerID := range perfs {
		total += pairRarity(ctx, performerID)
	}
	return total
}

func pairScore(ctx *curationContext, a, b, dimension string) (score, predA, predB float64) {
	predA = ctx.appeal[a]
	predB = ctx.appeal[b]
	conflict := 1.0 / (1.0 + mathAbs(predA-predB))
	tagsA := map[string]bool{}
	tagsB := map[string]bool{}
	for tagID := range ctx.sceneTags[a] {
		if ctx.isInteractive(tagID) {
			tagsA[tagID] = true
		}
	}
	for tagID := range ctx.sceneTags[b] {
		if ctx.isInteractive(tagID) {
			tagsB[tagID] = true
		}
	}
	var coverage float64
	for tagID := range tagsA {
		if !tagsB[tagID] {
			coverage += ctx.rarity(tagID)
		}
	}
	for tagID := range tagsB {
		if !tagsA[tagID] {
			coverage += ctx.rarity(tagID)
		}
	}
	perfsA := ctx.scenePerformers[a]
	perfsB := ctx.scenePerformers[b]
	for performerID := range perfsA {
		if !perfsB[performerID] {
			coverage += pairRarity(ctx, performerID)
		}
	}
	for performerID := range perfsB {
		if !perfsA[performerID] {
			coverage += pairRarity(ctx, performerID)
		}
	}
	var shared int
	switch dimension {
	case "tag":
		for performerID := range perfsA {
			if perfsB[performerID] {
				shared++
			}
		}
	case "performer", "studio":
		for tagID := range tagsA {
			if tagsB[tagID] {
				shared++
			}
		}
	}
	fit := 1.0 + pairDimensionFitShare*float64(shared)
	return conflict * coverage * fit, predA, predB
}

func pairUnlabeled(ctx *curationContext, seen map[string]bool) []string {
	var out []string
	for sceneID := range ctx.sceneIDs {
		if !ctx.labels[sceneID] && !ctx.blockedScenes[sceneID] && !ctx.metadataWrong[sceneID] && !seen[sceneID] {
			out = append(out, sceneID)
		}
	}
	sort.Strings(out)
	return out
}

type pairCandidate struct {
	a, b   string
	score  float64
	predA  float64
	predB  float64
}

func pairCandidates(ctx *curationContext, dimension, baseTag, contextTag, performerID string, seen map[string]bool) []pairCandidate {
	unlabeled := pairUnlabeled(ctx, seen)
	var out []pairCandidate
	if dimension == "tag" && baseTag != "" && contextTag != "" {
		var cellA, cellB []string
		for _, sceneID := range unlabeled {
			tags := ctx.sceneTags[sceneID]
			hasBase := tags[baseTag]
			hasCtx := tags[contextTag]
			if hasBase && hasCtx {
				cellA = append(cellA, sceneID)
			} else if hasBase && !hasCtx {
				cellB = append(cellB, sceneID)
			}
		}
		for _, a := range cellA {
			for _, b := range cellB {
				if len(out) >= pairMaxCandidates {
					return out
				}
				out = append(out, pairCandidate{a: a, b: b})
			}
		}
		return out
	}
	if dimension == "performer" && performerID != "" {
		var cellA []string
		for _, sceneID := range unlabeled {
			if ctx.scenePerformers[sceneID][performerID] {
				cellA = append(cellA, sceneID)
			}
		}
		for _, a := range cellA {
			tagsA := ctx.sceneTags[a]
			for _, b := range unlabeled {
				if b == a || ctx.scenePerformers[b][performerID] {
					continue
				}
				if !tagSetsIntersect(tagsA, ctx.sceneTags[b]) {
					continue
				}
				if len(out) >= pairMaxCandidates {
					return out
				}
				out = append(out, pairCandidate{a: a, b: b})
			}
		}
		return out
	}
	for i := 0; i < len(unlabeled); i++ {
		a := unlabeled[i]
		tagsA := ctx.sceneTags[a]
		perfsA := ctx.scenePerformers[a]
		studioA := curationStudioName(ctx, a)
		for j := i + 1; j < len(unlabeled); j++ {
			if len(out) >= pairMaxCandidates {
				return out
			}
			b := unlabeled[j]
			tagsB := ctx.sceneTags[b]
			switch dimension {
			case "performer":
				if setIntersect(perfsA, ctx.scenePerformers[b]) {
					continue
				}
				if !tagSetsIntersect(tagsA, tagsB) {
					continue
				}
			case "studio":
				if studioA == curationStudioName(ctx, b) {
					continue
				}
				if !tagSetsIntersect(tagsA, tagsB) {
					continue
				}
			default: // tag without explicit cells
				if mapEqual(tagsA, tagsB) {
					continue
				}
			}
			out = append(out, pairCandidate{a: a, b: b})
		}
	}
	return out
}

func setIntersect(a, b map[string]bool) bool {
	for k := range a {
		if b[k] {
			return true
		}
	}
	return false
}

func tagSetsIntersect(a, b map[string]bool) bool {
	for k := range a {
		if b[k] {
			return true
		}
	}
	return false
}

func mapEqual(a, b map[string]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if !b[k] {
			return false
		}
	}
	return true
}

func orthogonalPairs(ctx *curationContext, budget int, seen map[string]bool) []pairCandidate {
	unlabeled := pairUnlabeled(ctx, seen)
	sort.Slice(unlabeled, func(i, j int) bool {
		ci, cj := sceneCoverage(ctx, unlabeled[i]), sceneCoverage(ctx, unlabeled[j])
		if ci != cj {
			return ci > cj
		}
		return unlabeled[i] < unlabeled[j]
	})
	take := 2 * budget
	if len(unlabeled) < take {
		take = len(unlabeled)
	}
	var out []pairCandidate
	for i := 0; i+1 < take && len(out) < budget; i += 2 {
		out = append(out, pairCandidate{a: unlabeled[i], b: unlabeled[i+1]})
	}
	return out
}

func pairSceneMeta(ctx *curationContext, sceneID string) jVal {
	titleVal, studioVal, dateVal, detailsVal := jvNull(), jvNull(), jvNull(), jvNull()
	if title := ctx.sceneTitle[sceneID]; title != "" {
		titleVal = jvStr(title)
	}
	if studio := ctx.studio[sceneID]; studio != "" {
		studioVal = jvStr(studio)
	}
	if date := ctx.sceneDate[sceneID]; date != "" {
		dateVal = jvStr(date)
	}
	if details := ctx.sceneDetails[sceneID]; details != "" {
		detailsVal = jvStr(details)
	}
	performers := jvArr()
	performerIDs := make([]string, 0, len(ctx.scenePerformers[sceneID]))
	for performerID := range ctx.scenePerformers[sceneID] {
		performerIDs = append(performerIDs, performerID)
	}
	sort.Strings(performerIDs)
	for _, performerID := range performerIDs {
		name := ctx.performerName[performerID]
		if name == "" {
			name = performerID
		}
		performers.arr = append(performers.arr, jvObj(
			jvKey("performer_id", jvStr(performerID)),
			jvKey("name", jvStr(name)),
		))
	}
	return jvObj(
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("title", titleVal),
		jvKey("studio", studioVal),
		jvKey("date", dateVal),
		jvKey("details", detailsVal),
		jvKey("performers", performers),
		jvKey("tags", curationItemTags(ctx, sceneID)),
	)
}

// createPairRound mirrors curation.create_pair_round.
func createPairRound(db dbx, dimension string, budget int, baseTagID, contextTagID, performerID string) (jVal, error) {
	if !pairDimensions[dimension] {
		return jvNull(), fmt.Errorf("dimension must be one of tag, performer, studio, orthogonal")
	}
	if budget < pairMinBudget || budget > pairMaxBudget {
		return jvNull(), fmt.Errorf("budget must be from %d to %d", pairMinBudget, pairMaxBudget)
	}
	if dimension == "tag" {
		for _, tagID := range []string{baseTagID, contextTagID} {
			if tagID == "" {
				continue
			}
			var probe int
			err := db.QueryRow(`SELECT 1 FROM source_tag WHERE tag_id=?`, tagID).Scan(&probe)
			if err == sql.ErrNoRows {
				return jvNull(), fmt.Errorf("unknown tag: %s", tagID)
			}
			if err != nil {
				return jvNull(), err
			}
		}
	}
	if dimension == "performer" && performerID != "" {
		var probe int
		err := db.QueryRow(`SELECT 1 FROM source_performer WHERE performer_id=?`, performerID).Scan(&probe)
		if err == sql.ErrNoRows {
			return jvNull(), fmt.Errorf("unknown performer: %s", performerID)
		}
		if err != nil {
			return jvNull(), err
		}
	}
	ctx, err := loadCurationContext(db)
	if err != nil {
		return jvNull(), err
	}
	seen := map[string]bool{}
	rows, err := db.Query(`SELECT scene_a FROM curation_pair UNION SELECT scene_b FROM curation_pair`)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return jvNull(), err
		}
		seen[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	var candidates []pairCandidate
	if dimension == "orthogonal" {
		candidates = orthogonalPairs(ctx, budget, seen)
	} else {
		candidates = pairCandidates(ctx, dimension, baseTagID, contextTagID, performerID, seen)
	}
	scored := []pairCandidate{}
	for _, cand := range candidates {
		score, predA, predB := pairScore(ctx, cand.a, cand.b, dimension)
		if score <= 0 {
			continue
		}
		scored = append(scored, pairCandidate{a: cand.a, b: cand.b, score: score, predA: predA, predB: predB})
	}
	emptyRoundID := uuid4()
	if len(scored) == 0 {
		return jvObj(
			jvKey("schema_version", jvInt(1)),
			jvKey("round_id", jvStr(emptyRoundID)),
			jvKey("dimension", jvStr(dimension)),
			jvKey("pairs", jvArr()),
			jvKey("policy", jvStr("no candidate pairs above zero information")),
		), nil
	}
	var total float64
	for _, cand := range scored {
		total += cand.score
	}
	sort.Slice(scored, func(i, j int) bool {
		if scored[i].score != scored[j].score {
			return scored[i].score > scored[j].score
		}
		if scored[i].a != scored[j].a {
			return scored[i].a < scored[j].a
		}
		return scored[i].b < scored[j].b
	})
	selected := []pairCandidate{}
	sceneUses := map[string]int{}
	for _, cand := range scored {
		if sceneUses[cand.a] >= pairSceneCap || sceneUses[cand.b] >= pairSceneCap {
			continue
		}
		selected = append(selected, pairCandidate{
			a: cand.a, b: cand.b, score: cand.score / total, predA: cand.predA, predB: cand.predB,
		})
		sceneUses[cand.a]++
		sceneUses[cand.b]++
		if len(selected) >= budget {
			break
		}
	}
	roundID := uuid4()
	err = withTxn(db, func(conn *sql.Conn) error {
		for _, cand := range selected {
			payload := jvObj(
				jvKey("dimension", jvStr(dimension)),
				jvKey("predicted_a", jvFloat(cand.predA)),
				jvKey("predicted_b", jvFloat(cand.predB)),
			)
			if baseTagID != "" {
				payload.obj = append(payload.obj, jvKey("base_tag_id", jvStr(baseTagID)))
			}
			if contextTagID != "" {
				payload.obj = append(payload.obj, jvKey("context_tag_id", jvStr(contextTagID)))
			}
			if performerID != "" {
				payload.obj = append(payload.obj, jvKey("performer_id", jvStr(performerID)))
			}
			if _, err := conn.ExecContext(context.Background(), `
INSERT INTO curation_pair(
    pair_id, round_id, scene_a, scene_b, dimension,
    selection_probability, status, winner, occurred_at_ms, payload_json
) VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?)`,
				uuid4(), roundID, cand.a, cand.b, dimension, cand.score, payload.marshalSortedKeys()); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	rows, err = db.Query(
		`SELECT pair_id FROM curation_pair WHERE round_id=? ORDER BY rowid`, roundID,
	)
	if err != nil {
		return jvNull(), err
	}
	var pairIDs []string
	for rows.Next() {
		var pairID string
		if err := rows.Scan(&pairID); err != nil {
			rows.Close()
			return jvNull(), err
		}
		pairIDs = append(pairIDs, pairID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	pairsOut := jvArr()
	for i, cand := range selected {
		pairsOut.arr = append(pairsOut.arr, jvObj(
			jvKey("pair_id", jvStr(pairIDs[i])),
			jvKey("scene_a", pairSceneMeta(ctx, cand.a)),
			jvKey("scene_b", pairSceneMeta(ctx, cand.b)),
			jvKey("predicted_a", jvFloat(cand.predA)),
			jvKey("predicted_b", jvFloat(cand.predB)),
			jvKey("selection_probability", jvFloat(cand.score)),
		))
	}
	baseTagVal, contextTagVal := jvNull(), jvNull()
	if dimension == "tag" && baseTagID != "" {
		name := ctx.tagName[baseTagID]
		if name == "" {
			name = baseTagID
		}
		baseTagVal = jvObj(jvKey("tag_id", jvStr(baseTagID)), jvKey("name", jvStr(name)))
	}
	if dimension == "tag" && contextTagID != "" {
		name := ctx.tagName[contextTagID]
		if name == "" {
			name = contextTagID
		}
		contextTagVal = jvObj(jvKey("tag_id", jvStr(contextTagID)), jvKey("name", jvStr(name)))
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("round_id", jvStr(roundID)),
		jvKey("dimension", jvStr(dimension)),
		jvKey("base_tag", baseTagVal),
		jvKey("context_tag", contextTagVal),
		jvKey("pairs", pairsOut),
		jvKey("policy", jvStr("conflict-first + coverage, dimension prior, IPS-corrected")),
	), nil
}

type pairRow struct {
	pairID     string
	sceneA     string
	sceneB     string
	dimension  string
	probability float64
	status     string
	winner     string
	payload    jVal
}

func pairRows(db dbx, roundID string) ([]pairRow, error) {
	rows, err := db.Query(`
SELECT pair_id, scene_a, scene_b, dimension, selection_probability,
       status, winner, payload_json
FROM curation_pair WHERE round_id=? ORDER BY pair_id`, roundID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []pairRow
	for rows.Next() {
		var r pairRow
		var probability float64
		var winner sql.NullString
		var payloadJSON string
		if err := rows.Scan(&r.pairID, &r.sceneA, &r.sceneB, &r.dimension, &probability,
			&r.status, &winner, &payloadJSON); err != nil {
			return nil, err
		}
		r.probability = probability
		if winner.Valid {
			r.winner = winner.String
		}
		payload, err := parseJSON([]byte(payloadJSON))
		if err != nil {
			payload = jvObj()
		}
		r.payload = payload
		out = append(out, r)
	}
	return out, rows.Err()
}

func updateElo(conn *sql.Conn, sceneA, sceneB, winner string, now int64) error {
	current := func(sceneID string) float64 {
		var elo sql.NullFloat64
		err := conn.QueryRowContext(context.Background(),
			`SELECT elo FROM curation_pair_elo WHERE scene_id=?`, sceneID).Scan(&elo)
		if err == nil && elo.Valid {
			return elo.Float64
		}
		return pairEloInitial
	}
	ra, rb := current(sceneA), current(sceneB)
	ea := 1.0 / (1.0 + math.Pow(10.0, (rb-ra)/400.0))
	eb := 1.0 - ea
	if winner == "a" {
		ra += pairEloK * (1.0 - ea)
		rb += pairEloK * (0.0 - eb)
	} else {
		ra += pairEloK * (0.0 - ea)
		rb += pairEloK * (1.0 - eb)
	}
	for _, pair := range []struct {
		sceneID string
		elo     float64
	}{{sceneA, ra}, {sceneB, rb}} {
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO curation_pair_elo(scene_id, elo, updated_at_ms)
VALUES (?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET elo=excluded.elo, updated_at_ms=excluded.updated_at_ms`,
			pair.sceneID, pair.elo, now); err != nil {
			return err
		}
	}
	return nil
}

// submitPicks mirrors curation.submit_picks.
func submitPicks(db dbx, roundID string, picks jVal) (jVal, error) {
	if roundID == "" {
		return jvNull(), fmt.Errorf("round_id is required")
	}
	rows, err := pairRows(db, roundID)
	if err != nil {
		return jvNull(), err
	}
	if len(rows) == 0 {
		return jvNull(), fmt.Errorf("unknown round: %s", roundID)
	}
	byID := map[string]pairRow{}
	for _, row := range rows {
		byID[row.pairID] = row
	}
	if picks.kind != jArr {
		return jvNull(), fmt.Errorf("picks must be a list")
	}
	seen := map[string]bool{}
	type pick struct {
		pairID string
		winner string
		scene  string
	}
	var normalized []pick
	for _, entry := range picks.arr {
		if entry.kind != jObj {
			return jvNull(), fmt.Errorf("each pick must be an object with pair_id and winner")
		}
		pairID := pythonStrOrEmpty(entry.get("pair_id"))
		row, ok := byID[pairID]
		if !ok {
			return jvNull(), fmt.Errorf("pair is not in this round: %s", pairID)
		}
		if seen[pairID] {
			return jvNull(), fmt.Errorf("duplicate pick for pair: %s", pairID)
		}
		if row.status != "open" {
			return jvNull(), fmt.Errorf("pair already answered: %s", pairID)
		}
		winner := pythonStrOrEmpty(entry.get("winner"))
		if !pairPickValues[winner] {
			return jvNull(), fmt.Errorf("winner must be 'a', 'b', 'skip', or 'flag'")
		}
		scene := pythonStrOrEmpty(entry.get("scene"))
		if winner == "flag" && scene != "a" && scene != "b" {
			return jvNull(), fmt.Errorf("winner 'flag' requires a scene of 'a' or 'b'")
		}
		seen[pairID] = true
		normalized = append(normalized, pick{pairID: pairID, winner: winner, scene: scene})
	}
	if len(normalized) == 0 {
		return jvNull(), fmt.Errorf("picks must not be empty")
	}
	now := nowMs()
	accepted, skipped := 0, 0
	err = withTxn(db, func(conn *sql.Conn) error {
		for _, p := range normalized {
			row := byID[p.pairID]
			if p.winner == "skip" || p.winner == "flag" {
				if _, err := conn.ExecContext(context.Background(),
					`UPDATE curation_pair SET status='skipped' WHERE pair_id=?`, p.pairID); err != nil {
					return err
				}
				if p.winner == "flag" {
					flaggedScene := row.sceneA
					if p.scene == "b" {
						flaggedScene = row.sceneB
					}
					if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, 'metadata_wrong', NULL, ?, NULL, NULL, '{}')`,
						nowStrID(now), flaggedScene, now); err != nil {
						return err
					}
				}
				skipped++
				continue
			}
			winnerScene := row.sceneA
			loserScene := row.sceneB
			if p.winner == "b" {
				winnerScene, loserScene = row.sceneB, row.sceneA
			}
			predWinner := pythonFloatValue(row.payload.get("predicted_a"))
			predLoser := pythonFloatValue(row.payload.get("predicted_b"))
			if p.winner == "b" {
				predWinner, predLoser = predLoser, predWinner
			}
			labelPayload := jvObj(
				jvKey("pair_id", jvStr(p.pairID)),
				jvKey("round_id", jvStr(roundID)),
				jvKey("dimension", jvStr(row.dimension)),
				jvKey("predicted_winner", jvFloat(predWinner)),
				jvKey("predicted_loser", jvFloat(predLoser)),
				jvKey("selection_probability", jvFloat(row.probability)),
			)
			labelJSON := labelPayload.marshalSortedKeys()
			for _, label := range []struct {
				sceneID string
				value   string
				kind    string
			}{
				{winnerScene, "10", "curation_pair_winner"},
				{loserScene, "0", "curation_pair_loser"},
			} {
				if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)`,
					nowStrID(now), label.sceneID, label.kind, label.value, now, labelJSON); err != nil {
					return err
				}
			}
			if _, err := conn.ExecContext(context.Background(),
				`UPDATE curation_pair SET status='answered', winner=?, occurred_at_ms=? WHERE pair_id=?`,
				p.winner, now, p.pairID); err != nil {
				return err
			}
			if err := updateElo(conn, row.sceneA, row.sceneB, p.winner, now); err != nil {
				return err
			}
			accepted++
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	roundStatus := "open"
	if accepted+skipped == len(rows) {
		roundStatus = "answered"
	}
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("accepted", jvInt(int64(accepted))),
		jvKey("skipped", jvInt(int64(skipped))),
		jvKey("round_status", jvStr(roundStatus)),
	), nil
}

func pythonFloatOrZero(v jVal) jVal {
	if v.kind == jNum {
		return v
	}
	return jvFloat(0.0)
}

func roundPayload(db dbx, roundID string) jVal {
	var payloadJSON string
	err := db.QueryRow(`
SELECT payload_json FROM curation_pair WHERE round_id=?
ORDER BY pair_id LIMIT 1`, roundID).Scan(&payloadJSON)
	if err != nil {
		return jvObj()
	}
	payload, err := parseJSON([]byte(payloadJSON))
	if err != nil {
		return jvObj()
	}
	return payload
}

func pairCellOf(db dbx, sceneID, baseTag, contextTag string) string {
	rows, err := db.Query(`SELECT tag_id FROM scene_tag WHERE scene_id=?`, sceneID)
	if err != nil {
		return "neither"
	}
	defer rows.Close()
	tags := map[string]bool{}
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			return "neither"
		}
		tags[tagID] = true
	}
	hasBase := baseTag != "" && tags[baseTag]
	hasCtx := contextTag != "" && tags[contextTag]
	if hasBase && hasCtx {
		return "L&T"
	}
	if hasBase {
		return "L&!T"
	}
	if hasCtx {
		return "!L&T"
	}
	return "neither"
}

// pairVerdict mirrors curation.pair_verdict.
func pairVerdict(db dbx, roundID string) (jVal, error) {
	if roundID == "" {
		return jvNull(), fmt.Errorf("round_id is required")
	}
	rows, err := pairRows(db, roundID)
	if err != nil {
		return jvNull(), err
	}
	if len(rows) == 0 {
		return jvNull(), fmt.Errorf("unknown round: %s", roundID)
	}
	answered := []pairRow{}
	for _, row := range rows {
		if row.status == "answered" && (row.winner == "a" || row.winner == "b") {
			answered = append(answered, row)
		}
	}
	dimension := rows[0].dimension
	payload := roundPayload(db, roundID)
	baseTag := pythonStrOrEmpty(payload.get("base_tag_id"))
	contextTag := pythonStrOrEmpty(payload.get("context_tag_id"))
	base := jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("round_id", jvStr(roundID)),
		jvKey("dimension", jvStr(dimension)),
		jvKey("n_answered", jvInt(int64(len(answered)))),
	)
	if dimension == "tag" {
		wins := map[string]int{}
		for _, row := range answered {
			winnerScene := row.sceneA
			if row.winner == "b" {
				winnerScene = row.sceneB
			}
			cell := pairCellOf(db, winnerScene, baseTag, contextTag)
			wins[cell]++
		}
		cells := jvArr()
		for _, cell := range []string{"L&T", "L&!T", "!L&T", "neither"} {
			cells.arr = append(cells.arr, jvObj(
				jvKey("cell", jvStr(cell)),
				jvKey("wins", jvInt(int64(wins[cell]))),
			))
		}
		contrast := jvObj()
		if wins["L&T"]+wins["L&!T"] > 0 {
			contrast = jvObj(
				jvKey("delta", jvInt(int64(wins["L&T"]-wins["L&!T"]))),
				jvKey("n", jvInt(int64(wins["L&T"]+wins["L&!T"]))),
			)
		}
		base.obj = append(base.obj, jvKey("cells", cells), jvKey("contrast", contrast))
		return base, nil
	}
	names := map[string]string{}
	if dimension == "orthogonal" {
		rows, err := db.Query(`SELECT tag_id, name FROM source_tag`)
		if err != nil {
			return jvNull(), err
		}
		for rows.Next() {
			var tagID, name string
			if err := rows.Scan(&tagID, &name); err != nil {
				rows.Close()
				return jvNull(), err
			}
			names[tagID] = name
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}
	appearances := map[string]int{}
	wins := map[string]int{}
	for _, row := range answered {
		winnerScene := row.sceneA
		loserScene := row.sceneB
		if row.winner == "b" {
			winnerScene, loserScene = row.sceneB, row.sceneA
		}
		if dimension == "orthogonal" {
			tagsW := pairSceneTags(db, winnerScene)
			tagsL := pairSceneTags(db, loserScene)
			for tagID := range tagsW {
				if !tagsL[tagID] {
					wins[tagID]++
					appearances[tagID]++
				}
			}
			for tagID := range tagsL {
				if !tagsW[tagID] {
					appearances[tagID]++
				}
			}
			continue
		}
		// performer and studio: count appearances for both sides.
		for _, sceneID := range []string{row.sceneA, row.sceneB} {
			for _, key := range pairEntityKeys(db, sceneID, dimension) {
				appearances[key]++
			}
		}
		for _, key := range pairEntityKeys(db, winnerScene, dimension) {
			wins[key]++
		}
	}
	items := jvArr()
	keys := make([]string, 0, len(appearances))
	for key := range appearances {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if appearances[key] < 2 {
			continue
		}
		var entry jVal
		switch dimension {
		case "performer":
			entry = jvObj(
				jvKey("performer_id", jvStr(key)),
				jvKey("wins", jvInt(int64(wins[key]))),
				jvKey("appearances", jvInt(int64(appearances[key]))),
				jvKey("win_rate", jvFloat(float64(wins[key])/float64(appearances[key]))),
			)
		case "studio":
			entry = jvObj(
				jvKey("studio", jvStr(key)),
				jvKey("wins", jvInt(int64(wins[key]))),
				jvKey("appearances", jvInt(int64(appearances[key]))),
				jvKey("win_rate", jvFloat(float64(wins[key])/float64(appearances[key]))),
			)
		default: // orthogonal
			name := key
			if n := names[key]; n != "" {
				name = n
			}
			entry = jvObj(
				jvKey("tag_id", jvStr(key)),
				jvKey("name", jvStr(name)),
				jvKey("wins", jvInt(int64(wins[key]))),
				jvKey("appearances", jvInt(int64(appearances[key]))),
				jvKey("win_rate", jvFloat(float64(wins[key])/float64(appearances[key]))),
			)
		}
		items.arr = append(items.arr, entry)
	}
	sort.Slice(items.arr, func(i, j int) bool {
		a, b := items.arr[i], items.arr[j]
		aRate, bRate := pythonFloatValue(a.get("win_rate")), pythonFloatValue(b.get("win_rate"))
		if aRate != bRate {
			return aRate > bRate
		}
		var aKey, bKey string
		switch dimension {
		case "performer":
			aKey, bKey = pythonStrOrEmpty(a.get("performer_id")), pythonStrOrEmpty(b.get("performer_id"))
		case "studio":
			aKey, bKey = pythonStrOrEmpty(a.get("studio")), pythonStrOrEmpty(b.get("studio"))
		default:
			aKey, bKey = pythonStrOrEmpty(a.get("tag_id")), pythonStrOrEmpty(b.get("tag_id"))
		}
		return aKey < bKey
	})
	base.obj = append(base.obj, jvKey("items", items))
	return base, nil
}

func pairSceneTags(db dbx, sceneID string) map[string]bool {
	rows, err := db.Query(`SELECT tag_id FROM scene_tag WHERE scene_id=?`, sceneID)
	if err != nil {
		return map[string]bool{}
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			return map[string]bool{}
		}
		out[tagID] = true
	}
	return out
}

func pairEntityKeys(db dbx, sceneID, dimension string) []string {
	var query string
	if dimension == "performer" {
		query = `SELECT performer_id FROM scene_performer WHERE scene_id=?`
	} else {
		query = `SELECT s.name FROM source_scene ss JOIN source_studio s ON s.studio_id=ss.studio_id WHERE ss.scene_id=?`
	}
	rows, err := db.Query(query, sceneID)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var key string
		if err := rows.Scan(&key); err != nil {
			return nil
		}
		out = append(out, key)
	}
	return out
}

// opGetCurationPicks mirrors backend.py's get_curation_picks branch.
func opGetCurationPicks(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_curation_picks",
		func(settings jVal) (jVal, error) { return curationPicksBody(pluginDir, payload, settings) })
}

func curationPicksBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	dimension := pythonStrOrEmpty(args.get("dimension"))
	budget := int(argsInt(args, "budget", pairDefaultBudget))
	baseTagID := pythonStrOrEmpty(args.get("base_tag_id"))
	contextTagID := pythonStrOrEmpty(args.get("context_tag_id"))
	performerID := pythonStrOrEmpty(args.get("performer_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return createPairRound(db, dimension, budget, baseTagID, contextTagID, performerID)
}

// opSubmitCurationPicks mirrors backend.py's submit_curation_picks branch.
func opSubmitCurationPicks(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_curation_picks",
		func(settings jVal) (jVal, error) { return submitCurationPicksBody(pluginDir, payload, settings) })
}

func submitCurationPicksBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	roundID := pythonStrOrEmpty(args.get("round_id"))
	picks := args.get("picks")
	if picks.kind != jArr {
		return jvNull(), fmt.Errorf("picks must be a list")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return submitPicks(db, roundID, picks)
}

// opGetCurationPairVerdict mirrors backend.py's get_curation_pair_verdict branch.
func opGetCurationPairVerdict(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_curation_pair_verdict",
		func(settings jVal) (jVal, error) { return curationPairVerdictBody(pluginDir, payload, settings) })
}

func curationPairVerdictBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	roundID := pythonStrOrEmpty(args.get("round_id"))
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	return pairVerdict(db, roundID)
}
