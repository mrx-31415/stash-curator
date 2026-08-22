// Curation ops: pairwise picks, verdicts, and model impact — the Go mirror
// of curator/curation.py. The pair loop surfaces deterministic pairs of
// unlabeled scenes across the tag, performer, studio, and orthogonal
// dimensions; picks write winner/loser labels into feedback that feed the
// model, and pair verdicts accumulate per dimension across rounds.
// Everything is deterministic (ORDER BY, sorted iteration, no RNG) so the
// differential gates compare byte-identically against Python.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
)

const curationMaxItemTags = 8

// curationExcludedCategories mirrors curation.EXCLUDED_CATEGORIES.
var curationExcludedCategories = map[string]bool{
	"Hair Color": true, "Hair Style": true, "Body Type": true, "Breasts": true,
	"Face": true, "Skin Tone": true, "Piercings": true, "Ass": true,
	"Genitals": true, "Height": true, "Tattoos": true, "Race": true,
}

type curationContext struct {
	labels          map[string]bool
	sceneIDs        map[string]bool
	sceneTags       map[string]map[string]bool
	scenePerformers map[string]map[string]bool
	performerCounts map[string]int64
	performerName   map[string]string
	studio          map[string]string
	sceneTitle      map[string]string
	sceneDate       map[string]string
	sceneDetails    map[string]string
	tagCat          map[string]string
	tagName         map[string]string
	counts          map[string]int64
	appeal          map[string]float64
	blockedScenes   map[string]bool
	metadataWrong   map[string]bool
	interactive     map[string]bool
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

// loadCurationContext mirrors curation.curation_context.
func loadCurationContext(db dbx) (*curationContext, error) {
	labels, err := modelSceneLabels(db)
	if err != nil {
		return nil, err
	}
	ctx := &curationContext{
		labels:          make(map[string]bool, len(labels)),
		sceneIDs:        map[string]bool{},
		sceneTags:       map[string]map[string]bool{},
		scenePerformers: map[string]map[string]bool{},
		performerCounts: map[string]int64{},
		performerName:   map[string]string{},
		studio:          map[string]string{},
		sceneTitle:      map[string]string{},
		sceneDate:       map[string]string{},
		sceneDetails:    map[string]string{},
		tagCat:          map[string]string{},
		tagName:         map[string]string{},
		counts:          map[string]int64{},
		appeal:          map[string]float64{},
		blockedScenes:   map[string]bool{},
		metadataWrong:   map[string]bool{},
		interactive:     map[string]bool{},
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

func curationStudioName(ctx *curationContext, sceneID string) string {
	if name := ctx.studio[sceneID]; name != "" {
		return name
	}
	return "?"
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

func nowStrID(now int64) string {
	return fmt.Sprintf("%d-%s", now, uuid4())
}

// ── Pairwise picks (mirror of the curation.py pair section) ────────────────

const (
	pairMinBudget         = 4
	pairMaxBudget         = 20
	pairDefaultBudget     = 10
	pairMaxCandidates     = 20_000
	pairSceneCap          = 2
	pairDimensionFitShare = 0.5
	// orthogonalCandidateMultiplier mirrors curation.ORTHOGONAL_CANDIDATE_MULTIPLIER.
	orthogonalCandidateMultiplier = 10
	// pairVerdictPrior mirrors curation.PAIR_VERDICT_PRIOR.
	pairVerdictPrior = 4.0
)

var pairDimensions = map[string]bool{
	"tag": true, "performer": true, "studio": true, "orthogonal": true,
}

var pairPickValues = map[string]bool{
	"a": true, "b": true, "tie": true, "skip": true, "flag": true,
}

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

// pairScore mirrors curation._pair_score. Coverage is the mean rarity over
// the symmetric difference, not the sum: summing rewards pairs that differ on
// many features, which spreads a single comparison's +-1 signal thin across
// all of them. Averaging instead favors pairs that differ on few but rare
// features, where one answer resolves something concrete.
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
	var coverageSum float64
	var diffCount int
	for tagID := range tagsA {
		if !tagsB[tagID] {
			coverageSum += ctx.rarity(tagID)
			diffCount++
		}
	}
	for tagID := range tagsB {
		if !tagsA[tagID] {
			coverageSum += ctx.rarity(tagID)
			diffCount++
		}
	}
	perfsA := ctx.scenePerformers[a]
	perfsB := ctx.scenePerformers[b]
	for performerID := range perfsA {
		if !perfsB[performerID] {
			coverageSum += pairRarity(ctx, performerID)
			diffCount++
		}
	}
	for performerID := range perfsB {
		if !perfsA[performerID] {
			coverageSum += pairRarity(ctx, performerID)
			diffCount++
		}
	}
	var coverage float64
	if diffCount > 0 {
		coverage = coverageSum / float64(diffCount)
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

// groupCleanScenes mirrors curation._group_clean_scenes: scenes missing `tag`
// that can serve as clean negative examples. For group tags (taxonomy
// category Group Makeup), a scene with 3+ performers is likely the untagged
// group activity, so it cannot vouch for "without tag".
func groupCleanScenes(ctx *curationContext, scenes []string, tag string) []string {
	if ctx.tagCat[tag] != "Group Makeup" {
		return scenes
	}
	out := make([]string, 0, len(scenes))
	for _, sceneID := range scenes {
		if len(ctx.scenePerformers[sceneID]) < 3 {
			out = append(out, sceneID)
		}
	}
	return out
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
	a, b  string
	score float64
	predA float64
	predB float64
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
		cellB = groupCleanScenes(ctx, cellB, contextTag)
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

// orthogonalPairs mirrors curation._orthogonal_pairs: candidates from the top
// orthogonalCandidateMultiplier x budget scenes, adjacent-paired. This
// deliberately over-generates — createPairRound's own pairScore ranking then
// picks the best `budget` of these; returning exactly `budget` pairs (as this
// used to) left that ranking nothing to choose between, since every
// generated pair used each scene exactly once and so always passed the
// per-scene cap.
func orthogonalPairs(ctx *curationContext, budget int, seen map[string]bool) []pairCandidate {
	unlabeled := pairUnlabeled(ctx, seen)
	sort.Slice(unlabeled, func(i, j int) bool {
		ci, cj := sceneCoverage(ctx, unlabeled[i]), sceneCoverage(ctx, unlabeled[j])
		if ci != cj {
			return ci > cj
		}
		return unlabeled[i] < unlabeled[j]
	})
	take := orthogonalCandidateMultiplier * budget
	if len(unlabeled) < take {
		take = len(unlabeled)
	}
	var out []pairCandidate
	for i := 0; i+1 < take; i += 2 {
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
	// Only answered pairs retire their scenes. Offering a pair used to burn
	// both scenes forever, so an abandoned round — or a stream that prefetches
	// ahead of the user — permanently consumed scenes nobody ever judged.
	seen := map[string]bool{}
	rows, err := db.Query(`SELECT scene_a FROM curation_pair WHERE status='answered'
UNION SELECT scene_b FROM curation_pair WHERE status='answered'`)
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
			jvKey("schema_version", jvInt(2)),
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
		jvKey("schema_version", jvInt(2)),
		jvKey("round_id", jvStr(roundID)),
		jvKey("dimension", jvStr(dimension)),
		jvKey("base_tag", baseTagVal),
		jvKey("context_tag", contextTagVal),
		jvKey("pairs", pairsOut),
		jvKey("policy", jvStr("conflict-first + coverage, dimension prior, IPS-corrected")),
	), nil
}

type pairRow struct {
	pairID      string
	sceneA      string
	sceneB      string
	dimension   string
	probability float64
	status      string
	winner      string
	payload     jVal
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

// answeredPairs mirrors curation._answered_pairs: every answered pair of this
// dimension, across all rounds, so verdicts accumulate instead of restarting.
func answeredPairs(db dbx, dimension string) ([]pairRow, error) {
	rows, err := db.Query(`
SELECT pair_id, scene_a, scene_b, winner, payload_json
FROM curation_pair
WHERE dimension=? AND status='answered' AND winner IN ('a', 'b')
ORDER BY pair_id`, dimension)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []pairRow
	for rows.Next() {
		var r pairRow
		var winner sql.NullString
		var payloadJSON string
		if err := rows.Scan(&r.pairID, &r.sceneA, &r.sceneB, &winner, &payloadJSON); err != nil {
			return nil, err
		}
		r.dimension = dimension
		r.status = "answered"
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

// shrunkRate mirrors curation._shrunk_rate.
func shrunkRate(wins, appearances int) float64 {
	if appearances <= 0 {
		return 0.5
	}
	half := pairVerdictPrior / 2.0
	return (float64(wins) + half) / (float64(appearances) + pairVerdictPrior)
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
			return jvNull(), fmt.Errorf("winner must be 'a', 'b', 'tie', 'skip', or 'flag'")
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
	// Picks write feedback rows like every other interaction, so they mark the
	// model dirty too; without this the round never reaches a build and "What
	// your picks moved" keeps reporting the previous build's diff. One request
	// per pick, not per call: the pending count is weighed against the update
	// threshold, and a round is many feedback events, not one.
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
					if err := coordinatorRequest(conn, "curation_picks", now); err != nil {
						return err
					}
				}
				skipped++
				continue
			}
			// A tie is "these two are equally appealing" — real Bradley-Terry
			// information that pulls the features which differed toward the
			// mean, so it carries a label like any other answer. It has no
			// winner, so the row keeps winner NULL; every consumer of
			// 'answered' already guards on winner IN ('a', 'b').
			tie := p.winner == "tie"
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
			type pairLabel struct {
				sceneID string
				value   string
				kind    string
			}
			labels := []pairLabel{
				{winnerScene, "10", "curation_pair_winner"},
				{loserScene, "0", "curation_pair_loser"},
			}
			if tie {
				labels = []pairLabel{
					{row.sceneA, "5", "curation_pair_tie"},
					{row.sceneB, "5", "curation_pair_tie"},
				}
			}
			for _, label := range labels {
				if _, err := conn.ExecContext(context.Background(), `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    reversed_by_id, impression_id, payload_json
) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)`,
					nowStrID(now), label.sceneID, label.kind, label.value, now, labelJSON); err != nil {
					return err
				}
			}
			var storedWinner any = p.winner
			if tie {
				storedWinner = nil
			}
			if _, err := conn.ExecContext(context.Background(),
				`UPDATE curation_pair SET status='answered', winner=?, occurred_at_ms=? WHERE pair_id=?`,
				storedWinner, now, p.pairID); err != nil {
				return err
			}
			if err := coordinatorRequest(conn, "curation_picks", now); err != nil {
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
		jvKey("schema_version", jvInt(2)),
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
	roundAnswered := 0
	for _, row := range rows {
		if row.status == "answered" && (row.winner == "a" || row.winner == "b") {
			roundAnswered++
		}
	}
	dimension := rows[0].dimension
	payload := roundPayload(db, roundID)
	baseTag := pythonStrOrEmpty(payload.get("base_tag_id"))
	contextTag := pythonStrOrEmpty(payload.get("context_tag_id"))
	answered, err := answeredPairs(db, dimension)
	if err != nil {
		return jvNull(), err
	}
	if dimension == "tag" {
		// Only the pairs testing this same hypothesis accumulate together.
		matching := []pairRow{}
		for _, row := range answered {
			if pythonStrOrEmpty(row.payload.get("base_tag_id")) == baseTag &&
				pythonStrOrEmpty(row.payload.get("context_tag_id")) == contextTag {
				matching = append(matching, row)
			}
		}
		answered = matching
	}
	base := jvObj(
		jvKey("schema_version", jvInt(2)),
		jvKey("round_id", jvStr(roundID)),
		jvKey("dimension", jvStr(dimension)),
		jvKey("n_answered", jvInt(int64(len(answered)))),
		jvKey("n_round", jvInt(int64(roundAnswered))),
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
				jvKey("win_rate", jvFloat(shrunkRate(wins[key], appearances[key]))),
			)
		case "studio":
			entry = jvObj(
				jvKey("studio", jvStr(key)),
				jvKey("wins", jvInt(int64(wins[key]))),
				jvKey("appearances", jvInt(int64(appearances[key]))),
				jvKey("win_rate", jvFloat(shrunkRate(wins[key], appearances[key]))),
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
				jvKey("win_rate", jvFloat(shrunkRate(wins[key], appearances[key]))),
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
)

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
	tn, err := db.Query(`SELECT tag_id, name FROM source_tag`)
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
		kind  string
		id    string
		name  string
		delta float64
	}
	sceneContributors := map[string][]contributor{}
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
		for _, sceneID := range sceneIDs {
			cr, err := fdb.Query(`
				SELECT fd.name
				FROM entity_feature ef
				JOIN feature_definition fd USING(feature_id)
				WHERE ef.feature_version=? AND ef.entity_id=?`, newer.featureVersion, sceneID)
			if err != nil {
				fdb.Close()
				return unavailable(), nil
			}
			var cands []contributor
			directDelta := newDirect[sceneID] - oldDirect[sceneID]
			if math.Abs(directDelta) > IMPACT_MIN_CONTRIBUTION {
				cands = append(cands, contributor{kind: "direct", id: sceneID, name: "Your direct feedback", delta: directDelta})
			}
			for cr.Next() {
				var name string
				if err := cr.Scan(&name); err != nil {
					cr.Close()
					fdb.Close()
					return jvNull(), err
				}
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
				cands = append(cands, c)
			}
			cr.Close()
			if err := cr.Err(); err != nil {
				fdb.Close()
				return jvNull(), err
			}
			sort.Slice(cands, func(i, j int) bool {
				ai, aj := math.Abs(cands[i].delta), math.Abs(cands[j].delta)
				if ai != aj {
					return ai > aj
				}
				return cands[i].name < cands[j].name
			})
			if len(cands) > 3 {
				cands = cands[:3]
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
			contribs = append(contribs, jvObj(
				jvKey("kind", jvStr(c.kind)),
				jvKey("id", jvStr(c.id)),
				jvKey("name", jvStr(c.name)),
				jvKey("delta", jvFloat(c.delta)),
			))
		}
		return jvObj(
			jvKey("scene_id", jvStr(e.id)),
			jvKey("title", title),
			jvKey("studio", studio),
			jvKey("date", date),
			jvKey("delta", jvFloat(e.delta)),
			jvKey("contributors", jVal{kind: jArr, arr: contribs}),
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
