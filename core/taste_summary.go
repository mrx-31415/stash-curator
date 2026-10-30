// get_taste_summary — port of curator/taste_summary.py (Insights -> Your
// taste). A read-only summary of data Curator already keeps: top tags from
// the published model's affinities, trends and the recent shift as a tag's
// share of the scenes watched in a window of play history, and what sets you
// apart from the model's own watch-lift formula on every tag.
// Windows are anchored at the latest recorded play.
package main

import (
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
)

const (
	tasteWindowMs          = int64(90 * 86_400_000)
	tasteWindowCount       = 8
	tasteMinWindowScenes   = 5
	tasteMinTagScenes      = 3
	tasteBeliefConfidence  = 0.35
	tasteBeliefAffinity    = 0.15
	tasteTopLikes          = 8
	tasteTopDislikes       = 4
	tasteShiftCount        = 3
	tasteShiftMinDelta     = 0.05
	tasteShiftMinScenes    = 3
	tasteDormantCount      = 3
	tasteRediscoverGapMs   = int64(180 * 86_400_000)
	tasteRediscoveredCount = 6
	tasteReasonCount       = 5
	// What sets you apart: see APART_* and PASSED_* in taste_summary.py.
	tasteApartCount           = 6
	tasteApartMinWatchedShare = 0.015
	tasteApartMinWatched      = 5
	tastePassedCount          = 5
	tastePassedMinLibShare    = 0.03
	tastePassedMaxRatio       = 0.8
)

const tasteAffinitySQL = `
SELECT d.name, a.affinity, a.confidence
FROM feature_definition d
JOIN feature_affinity a ON a.feature_id=d.feature_id AND a.model_id=?
WHERE d.feature_version=? AND d.family='content'
ORDER BY d.name
`

const tasteContentTagSQL = `
SELECT DISTINCT st.scene_id, st.tag_id
FROM scene_tag st
JOIN tag_role r ON r.tag_id=st.tag_id AND r.config_version=? AND r.role='content'
WHERE st.provenance='scene'
ORDER BY st.scene_id, st.tag_id
`

const tasteDormantSQL = `
SELECT entity_type, entity_id, last_played_at_ms, positive_strength, play_count
FROM model_entity_dormancy
WHERE model_id=? AND play_count>=3 AND distinct_scene_count>=2 AND positive_strength>=0.10
ORDER BY positive_strength DESC, entity_type, entity_id
`

const tasteReasonSQL = `
SELECT CASE r.subject_type WHEN 'missing_tag' THEN 'tag' ELSE r.subject_type END AS kind,
       r.subject_id, a.polarity, count(DISTINCT a.answer_id) AS answers
FROM scene_reason r JOIN scene_reason_answer a ON a.answer_id=r.answer_id
WHERE r.subject_type<>'scene'
GROUP BY kind, r.subject_id, a.polarity
ORDER BY answers DESC, kind, r.subject_id
`

var tasteNameSQL = map[string]string{
	"tag":       `SELECT tag_id, COALESCE(NULLIF(name, ''), tag_id) FROM source_tag`,
	"performer": `SELECT performer_id, COALESCE(NULLIF(name, ''), performer_id) FROM source_performer`,
	"studio":    `SELECT studio_id, COALESCE(NULLIF(name, ''), studio_id) FROM source_studio`,
}

// tasteWatchLift is modelWatchLift's per-feature lift for one window.
func tasteWatchLift(withTag, watched, library, total int) float64 {
	base := float64(library) / float64(total)
	return math.Log(((float64(withTag) + watchLiftShrink*base) / (float64(watched) + watchLiftShrink)) / base)
}

func opGetTasteSummary(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_taste_summary", func(settings jVal) (jVal, error) {
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		summary, err := tasteSummary(db)
		if err != nil {
			return jvNull(), err
		}
		out := jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)))
		for _, pair := range summary.obj {
			out.set(pair.key, pair.val)
		}
		return out, nil
	})
}

type tasteTag struct {
	tagID, name          string
	affinity, confidence float64
	answer               sql.NullFloat64
	watched              int
}

type tasteShiftItem struct {
	tagID, name           string
	recent, before, delta float64
}

type tasteRediscovered struct {
	sceneID          string
	plays, returns   int
	longestGap, last int64
}

func tasteSummary(db dbx) (jVal, error) {
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model")
	}
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return jvNull(), err
	}
	configVersion, err := effectiveTagRoleConfigVersion(db)
	if err != nil {
		return jvNull(), err
	}
	names := map[string]map[string]string{}
	for kind, query := range tasteNameSQL {
		pairs, err := tasteStringPairs(db, query)
		if err != nil {
			return jvNull(), err
		}
		names[kind] = map[string]string{}
		for _, pair := range pairs {
			names[kind][pair[0]] = pair[1]
		}
	}
	var totalScenes int
	if err := db.QueryRow(`SELECT count(*) FROM source_scene`).Scan(&totalScenes); err != nil {
		return jvNull(), err
	}

	sceneTags := map[string][]string{}
	library := map[string]int{}
	tagPairs, err := tasteStringPairs(db, tasteContentTagSQL, configVersion)
	if err != nil {
		return jvNull(), err
	}
	for _, pair := range tagPairs {
		sceneTags[pair[0]] = append(sceneTags[pair[0]], pair[1])
		library[pair[1]]++
	}

	plays := map[string][]int64{}
	playRows, err := db.Query(`SELECT scene_id, played_at_ms FROM source_play ORDER BY scene_id, played_at_ms, ordinal`)
	if err != nil {
		return jvNull(), err
	}
	playCount := 0
	var firstMs, anchorMs int64
	for playRows.Next() {
		var sceneID string
		var at int64
		if err := playRows.Scan(&sceneID, &at); err != nil {
			playRows.Close()
			return jvNull(), err
		}
		if playCount == 0 || at < firstMs {
			firstMs = at
		}
		if playCount == 0 || at > anchorMs {
			anchorMs = at
		}
		playCount++
		plays[sceneID] = append(plays[sceneID], at)
	}
	playRows.Close()
	if err := playRows.Err(); err != nil {
		return jvNull(), err
	}
	hasPlays := playCount > 0

	// watchedBetween returns the scenes played in (start, end]; a nil start
	// is unbounded.
	watchedBetween := func(start *int64, end int64) map[string]bool {
		result := map[string]bool{}
		for sceneID, times := range plays {
			for _, at := range times {
				if (start == nil || *start < at) && at <= end {
					result[sceneID] = true
					break
				}
			}
		}
		return result
	}
	tagCounts := func(scenes map[string]bool) map[string]int {
		counts := map[string]int{}
		for sceneID := range scenes {
			for _, tagID := range sceneTags[sceneID] {
				counts[tagID]++
			}
		}
		return counts
	}

	type window struct {
		start, end int64
		scenes     int
		counts     map[string]int
	}
	var windows []window
	if hasPlays {
		for index := 0; index < tasteWindowCount; index++ {
			end := anchorMs - int64(tasteWindowCount-1-index)*tasteWindowMs
			start := end - tasteWindowMs
			if end < firstMs {
				continue
			}
			scenes := watchedBetween(&start, end)
			windows = append(windows, window{start: start, end: end, scenes: len(scenes), counts: tagCounts(scenes)})
		}
	}
	trend := func(tagID string) jVal {
		values := jvArr()
		for _, w := range windows {
			if w.scenes >= tasteMinWindowScenes {
				values.arr = append(values.arr, jvFloat(float64(w.counts[tagID])/float64(w.scenes)))
			} else {
				values.arr = append(values.arr, jvNull())
			}
		}
		return values
	}

	allWatched := map[string]bool{}
	for sceneID := range plays {
		allWatched[sceneID] = true
	}
	watchedCounts := tagCounts(allWatched)
	var likes, dislikes []tasteTag
	answers := map[string]float64{}
	answerRows, err := db.Query(`SELECT tag_id, value FROM direct_tag_preference`)
	if err != nil {
		return jvNull(), err
	}
	for answerRows.Next() {
		var tagID string
		var value float64
		if err := answerRows.Scan(&tagID, &value); err != nil {
			answerRows.Close()
			return jvNull(), err
		}
		answers[tagID] = value
	}
	answerRows.Close()
	if err := answerRows.Err(); err != nil {
		return jvNull(), err
	}
	tagRows, err := db.Query(tasteAffinitySQL, modelID, featureVersion)
	if err != nil {
		return jvNull(), err
	}
	for tagRows.Next() {
		var featureName string
		var item tasteTag
		if err := tagRows.Scan(&featureName, &item.affinity, &item.confidence); err != nil {
			tagRows.Close()
			return jvNull(), err
		}
		tagID, ok := strings.CutPrefix(featureName, "tag:")
		if !ok || library[tagID] < tasteMinTagScenes {
			continue
		}
		if item.confidence < tasteBeliefConfidence || math.Abs(item.affinity) < tasteBeliefAffinity {
			continue
		}
		item.tagID, item.name, item.watched = tagID, names["tag"][tagID], watchedCounts[tagID]
		if item.name == "" {
			item.name = tagID
		}
		if value, answered := answers[tagID]; answered {
			item.answer = sql.NullFloat64{Float64: value, Valid: true}
		}
		if item.affinity > 0 {
			likes = append(likes, item)
		} else {
			dislikes = append(dislikes, item)
		}
	}
	tagRows.Close()
	if err := tagRows.Err(); err != nil {
		return jvNull(), err
	}
	// Likes that define what you watch: most-watched first. Dislikes are
	// rarely watched, so they rank by how strongly the model holds them.
	sort.SliceStable(likes, func(i, j int) bool {
		a, b := likes[i], likes[j]
		if a.watched != b.watched {
			return a.watched > b.watched
		}
		if a.affinity != b.affinity {
			return a.affinity > b.affinity
		}
		return tasteNameLess(a.name, a.tagID, b.name, b.tagID)
	})
	sort.SliceStable(dislikes, func(i, j int) bool {
		a, b := dislikes[i], dislikes[j]
		if as, bs := a.affinity*a.confidence, b.affinity*b.confidence; as != bs {
			return as < bs
		}
		return tasteNameLess(a.name, a.tagID, b.name, b.tagID)
	})
	tagList := func(items []tasteTag, limit int) jVal {
		out := jvArr()
		for index, item := range items {
			if index == limit {
				break
			}
			answer := jvNull()
			if item.answer.Valid {
				answer = jvFloat(item.answer.Float64)
			}
			out.arr = append(out.arr, jvObj(
				jvKey("tag_id", jvStr(item.tagID)),
				jvKey("name", jvStr(item.name)),
				jvKey("affinity", jvFloat(item.affinity)),
				jvKey("confidence", jvFloat(item.confidence)),
				jvKey("answer", answer),
				jvKey("watched_scenes", jvInt(int64(item.watched))),
				jvKey("trend", trend(item.tagID)),
			))
		}
		return out
	}

	var rising, fading []tasteShiftItem
	if hasPlays {
		recentStart := anchorMs - tasteWindowMs
		recent := watchedBetween(&recentStart, anchorMs)
		before := watchedBetween(nil, recentStart)
		if len(recent) >= tasteMinWindowScenes && len(before) >= tasteMinWindowScenes {
			recentCounts, beforeCounts := tagCounts(recent), tagCounts(before)
			for _, tagID := range sortedStringKeys(library) {
				if library[tagID] < tasteMinTagScenes || recentCounts[tagID]+beforeCounts[tagID] < tasteShiftMinScenes {
					continue
				}
				now := float64(recentCounts[tagID]) / float64(len(recent))
				then := float64(beforeCounts[tagID]) / float64(len(before))
				name := names["tag"][tagID]
				if name == "" {
					name = tagID
				}
				item := tasteShiftItem{tagID: tagID, name: name, recent: now, before: then, delta: now - then}
				if item.delta >= tasteShiftMinDelta {
					rising = append(rising, item)
				} else if item.delta <= -tasteShiftMinDelta {
					fading = append(fading, item)
				}
			}
		}
	}
	sortShift := func(items []tasteShiftItem, sign float64) jVal {
		sort.SliceStable(items, func(i, j int) bool {
			a, b := items[i], items[j]
			if a.delta != b.delta {
				return sign*a.delta < sign*b.delta
			}
			if an, bn := strings.ToLower(a.name), strings.ToLower(b.name); an != bn {
				return an < bn
			}
			return a.tagID < b.tagID
		})
		out := jvArr()
		for index, item := range items {
			if index == tasteShiftCount {
				break
			}
			out.arr = append(out.arr, jvObj(
				jvKey("tag_id", jvStr(item.tagID)),
				jvKey("name", jvStr(item.name)),
				jvKey("recent", jvFloat(item.recent)),
				jvKey("before", jvFloat(item.before)),
				jvKey("delta", jvFloat(item.delta)),
			))
		}
		return out
	}

	dormant := jvArr()
	if hasPlays {
		rows, err := db.Query(tasteDormantSQL, modelID)
		if err != nil {
			return jvNull(), err
		}
		for rows.Next() && len(dormant.arr) < tasteDormantCount {
			var kind, entityID string
			var lastPlayed, playTotal int64
			var strength float64
			if err := rows.Scan(&kind, &entityID, &lastPlayed, &strength, &playTotal); err != nil {
				rows.Close()
				return jvNull(), err
			}
			days := math.Max(0, float64(anchorMs-lastPlayed)/86_400_000)
			if entityDormancy(days) < 0.5 {
				continue
			}
			name := names[kind][entityID]
			if name == "" {
				name = entityID
			}
			dormant.arr = append(dormant.arr, jvObj(
				jvKey("entity_type", jvStr(kind)),
				jvKey("entity_id", jvStr(entityID)),
				jvKey("name", jvStr(name)),
				jvKey("last_played_at_ms", jvInt(lastPlayed)),
				jvKey("play_count", jvInt(playTotal)),
			))
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}

	var found []tasteRediscovered
	for sceneID, times := range plays {
		item := tasteRediscovered{sceneID: sceneID, plays: len(times), last: times[len(times)-1]}
		for index := 1; index < len(times); index++ {
			gap := times[index] - times[index-1]
			if gap >= tasteRediscoverGapMs {
				item.returns++
			}
			if gap > item.longestGap {
				item.longestGap = gap
			}
		}
		if item.returns > 0 {
			found = append(found, item)
		}
	}
	sort.Slice(found, func(i, j int) bool {
		a, b := found[i], found[j]
		if a.returns != b.returns {
			return a.returns > b.returns
		}
		if a.longestGap != b.longestGap {
			return a.longestGap > b.longestGap
		}
		return a.sceneID < b.sceneID
	})
	rediscovered := jvArr()
	for index, item := range found {
		if index == tasteRediscoveredCount {
			break
		}
		var title string
		if err := db.QueryRow(`SELECT COALESCE(title, '') FROM source_scene WHERE scene_id=?`, item.sceneID).Scan(&title); err != nil && err != sql.ErrNoRows {
			return jvNull(), err
		}
		rediscovered.arr = append(rediscovered.arr, jvObj(
			jvKey("scene_id", jvStr(item.sceneID)),
			jvKey("plays", jvInt(int64(item.plays))),
			jvKey("returns", jvInt(int64(item.returns))),
			jvKey("longest_gap_ms", jvInt(item.longestGap)),
			jvKey("last_played_at_ms", jvInt(item.last)),
			jvKey("title", jvStr(title)),
		))
	}

	type apartTag struct {
		tagID string
		lift  float64
	}
	var apart, passed []apartTag
	if len(allWatched) > 0 {
		minWatched := max(tasteApartMinWatched, int(math.Ceil(tasteApartMinWatchedShare*float64(len(allWatched)))))
		for _, tagID := range sortedStringKeys(library) {
			watched := watchedCounts[tagID]
			lift := tasteWatchLift(watched, len(allWatched), library[tagID], totalScenes)
			if watched >= minWatched && lift > 0 {
				apart = append(apart, apartTag{tagID, lift})
			}
			if float64(library[tagID])/float64(totalScenes) >= tastePassedMinLibShare && lift <= math.Log(tastePassedMaxRatio) {
				passed = append(passed, apartTag{tagID, lift})
			}
		}
	}
	tagName := func(tagID string) string {
		if name := names["tag"][tagID]; name != "" {
			return name
		}
		return tagID
	}
	apartList := func(items []apartTag, sign float64, limit int) jVal {
		sort.SliceStable(items, func(i, j int) bool {
			a, b := items[i], items[j]
			if a.lift != b.lift {
				return sign*a.lift < sign*b.lift
			}
			return tasteNameLess(tagName(a.tagID), a.tagID, tagName(b.tagID), b.tagID)
		})
		out := jvArr()
		for index, item := range items {
			if index == limit {
				break
			}
			out.arr = append(out.arr, jvObj(
				jvKey("tag_id", jvStr(item.tagID)),
				jvKey("name", jvStr(tagName(item.tagID))),
				jvKey("lift", jvFloat(item.lift)),
				jvKey("watched_share", jvFloat(float64(watchedCounts[item.tagID])/float64(len(allWatched)))),
				jvKey("library_share", jvFloat(float64(library[item.tagID])/float64(totalScenes))),
			))
		}
		return out
	}

	hits, misses := jvArr(), jvArr()
	reasonRows, err := db.Query(tasteReasonSQL)
	if err != nil {
		return jvNull(), err
	}
	for reasonRows.Next() {
		var kind, subjectID string
		var polarity, answers int64
		if err := reasonRows.Scan(&kind, &subjectID, &polarity, &answers); err != nil {
			reasonRows.Close()
			return jvNull(), err
		}
		bucket := &hits
		if polarity <= 0 {
			bucket = &misses
		}
		if len(bucket.arr) == tasteReasonCount {
			continue
		}
		name := names[kind][subjectID]
		if name == "" {
			name = subjectID
		}
		bucket.arr = append(bucket.arr, jvObj(
			jvKey("subject_type", jvStr(kind)),
			jvKey("subject_id", jvStr(subjectID)),
			jvKey("name", jvStr(name)),
			jvKey("answers", jvInt(answers)),
		))
	}
	reasonRows.Close()
	if err := reasonRows.Err(); err != nil {
		return jvNull(), err
	}

	var answeredTags, reasonAnswers int64
	if err := db.QueryRow(`SELECT count(*) FROM direct_tag_preference`).Scan(&answeredTags); err != nil {
		return jvNull(), err
	}
	if err := db.QueryRow(`SELECT count(*) FROM scene_reason_answer`).Scan(&reasonAnswers); err != nil {
		return jvNull(), err
	}
	first, asOf := jvNull(), jvNull()
	if hasPlays {
		first, asOf = jvInt(firstMs), jvInt(anchorMs)
	}
	windowList := jvArr()
	for _, w := range windows {
		windowList.arr = append(windowList.arr, jvObj(
			jvKey("start_ms", jvInt(w.start)),
			jvKey("end_ms", jvInt(w.end)),
			jvKey("scenes", jvInt(int64(w.scenes))),
		))
	}
	return jvObj(
		jvKey("model_id", jvStr(modelID)),
		jvKey("totals", jvObj(
			jvKey("plays", jvInt(int64(playCount))),
			jvKey("scenes_played", jvInt(int64(len(allWatched)))),
			jvKey("library_scenes", jvInt(int64(totalScenes))),
			jvKey("first_played_at_ms", first),
			jvKey("as_of_ms", asOf),
			jvKey("answered_tags", jvInt(answeredTags)),
			jvKey("reason_answers", jvInt(reasonAnswers)),
		)),
		jvKey("windows", windowList),
		jvKey("likes", tagList(likes, tasteTopLikes)),
		jvKey("dislikes", tagList(dislikes, tasteTopDislikes)),
		jvKey("shift", jvObj(
			jvKey("rising", sortShift(rising, -1)),
			jvKey("fading", sortShift(fading, 1)),
		)),
		jvKey("dormant", dormant),
		jvKey("rediscovered", rediscovered),
		jvKey("apart", jvObj(
			jvKey("more", apartList(apart, -1, tasteApartCount)),
			jvKey("passed", apartList(passed, 1, tastePassedCount)),
		)),
		jvKey("reasons", jvObj(jvKey("hits", hits), jvKey("misses", misses))),
	), nil
}

// tasteNameLess orders by case-folded name, then id.
func tasteNameLess(aName, aID, bName, bID string) bool {
	if an, bn := strings.ToLower(aName), strings.ToLower(bName); an != bn {
		return an < bn
	}
	return aID < bID
}

// tasteStringPairs reads a two-string-column query.
func tasteStringPairs(db dbx, query string, args ...any) ([][2]string, error) {
	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var pairs [][2]string
	for rows.Next() {
		var pair [2]string
		if err := rows.Scan(&pair[0], &pair[1]); err != nil {
			return nil, err
		}
		pairs = append(pairs, pair)
	}
	return pairs, rows.Err()
}
