// get_home_recap — what happened with Curator lately, for the welcome strip
// and the weekly recap on For You. A read-only summary over plays, ratings,
// feedback, tag answers and model updates; it never writes.
package main

import (
	"database/sql"
	"sort"
	"strings"
)

const (
	homeRecapDayMs       = 86_400_000
	homeRecapMaxSessions = 2000
	homeRecapGoodRating  = 70
	homeRecapTagsShown   = 4
)

func opGetHomeRecap(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_home_recap", func(settings jVal) (jVal, error) {
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		args := payload.get("args")
		days := argsInt(args, "window_days", 7)
		if days < 1 {
			days = 1
		}
		if days > 62 {
			days = 62
		}
		// end_ms ends the window early, for a past month's Rewind.
		end := nowMs()
		if requested := argsInt(args, "end_ms", 0); requested > 0 && requested < end {
			end = requested
		}
		recap, err := homeRecap(db, end, days, argsInt(args, "since_ms", 0))
		if err != nil {
			return jvNull(), err
		}
		out := jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)))
		for _, pair := range recap.obj {
			out.set(pair.key, pair.val)
		}
		return out, nil
	})
}

// homeRecap summarizes the window ending at now; sinceMs > 0 adds what is
// new since the person's previous visit.
func homeRecap(db dbx, now, days, sinceMs int64) (jVal, error) {
	start := now - days*homeRecapDayMs
	sessions := jvArr()
	picked := map[string]bool{}
	var watchedSeconds float64
	rows, err := db.Query(`SELECT scene_id, started_at_ms, active_seconds, impression_id IS NOT NULL
FROM play_session WHERE started_at_ms >= ? AND started_at_ms <= ?
ORDER BY started_at_ms LIMIT ?`, start, now, homeRecapMaxSessions)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var sceneID string
		var startedAt int64
		var seconds float64
		var curator bool
		if err := rows.Scan(&sceneID, &startedAt, &seconds, &curator); err != nil {
			rows.Close()
			return jvNull(), err
		}
		if curator {
			picked[sceneID] = true
			watchedSeconds += seconds
		}
		sessions.arr = append(sessions.arr, jvObj(
			jvKey("started_at_ms", jvInt(startedAt)),
			jvKey("seconds", jvFloat(seconds)),
			jvKey("curator", jvBool(curator)),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}

	ratedWell := 0
	for sceneID := range picked {
		good, err := homeRecapRatedWell(db, sceneID, start)
		if err != nil {
			return jvNull(), err
		}
		if good {
			ratedWell++
		}
	}
	bestFind, err := homeRecapBestFind(db, picked, start)
	if err != nil {
		return jvNull(), err
	}
	learned, err := homeRecapLearned(db, start, now)
	if err != nil {
		return jvNull(), err
	}
	explored, err := homeRecapExplored(db, start, now)
	if err != nil {
		return jvNull(), err
	}
	out := jvObj(
		jvKey("now_ms", jvInt(now)),
		jvKey("window_start_ms", jvInt(start)),
		jvKey("window_days", jvInt(days)),
		jvKey("picks_watched", jvInt(int64(len(picked)))),
		jvKey("rated_well", jvInt(int64(ratedWell))),
		jvKey("watched_seconds", jvFloat(watchedSeconds)),
		jvKey("sessions", sessions),
		jvKey("best_find", bestFind),
		jvKey("learned", learned),
		jvKey("explored", explored),
	)
	if sinceMs > 0 {
		since, err := homeRecapSince(db, sinceMs)
		if err != nil {
			return jvNull(), err
		}
		out.set("since", since)
	}
	return out, nil
}

// A pick went well when it is rated well in Stash or got a thumbs up that
// was not taken back during the window.
func homeRecapRatedWell(db dbx, sceneID string, start int64) (bool, error) {
	var rating sql.NullInt64
	err := db.QueryRow(`SELECT rating100 FROM source_scene WHERE scene_id=?`, sceneID).Scan(&rating)
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	if rating.Valid && rating.Int64 >= homeRecapGoodRating {
		return true, nil
	}
	var liked int
	err = db.QueryRow(`SELECT COUNT(*) FROM feedback
WHERE scene_id=? AND feedback_type='thumb_up' AND reversed_by_id IS NULL AND occurred_at_ms >= ?`, sceneID, start).Scan(&liked)
	return liked > 0, err
}

// The best Curator pick from a studio the person had never played before
// the window: highest rating first, then the most watching.
func homeRecapBestFind(db dbx, picked map[string]bool, start int64) (jVal, error) {
	type find struct {
		sceneID, title, studio string
		rating                 int64
		seconds                float64
	}
	var best *find
	for sceneID := range picked {
		var title, studioID, studio sql.NullString
		var rating sql.NullInt64
		err := db.QueryRow(`SELECT s.title, s.studio_id, st.name, s.rating100
FROM source_scene s LEFT JOIN source_studio st ON st.studio_id = s.studio_id
WHERE s.scene_id=?`, sceneID).Scan(&title, &studioID, &studio, &rating)
		if err == sql.ErrNoRows {
			continue
		}
		if err != nil {
			return jvNull(), err
		}
		if !studioID.Valid || !studio.Valid || strings.TrimSpace(studio.String) == "" {
			continue
		}
		var before int
		if err := db.QueryRow(`SELECT COUNT(*) FROM source_play p JOIN source_scene s ON s.scene_id = p.scene_id
WHERE s.studio_id=? AND p.played_at_ms < ?`, studioID.String, start).Scan(&before); err != nil {
			return jvNull(), err
		}
		if before > 0 {
			continue
		}
		var seconds float64
		if err := db.QueryRow(`SELECT COALESCE(SUM(active_seconds), 0) FROM play_session
WHERE scene_id=? AND started_at_ms >= ?`, sceneID, start).Scan(&seconds); err != nil {
			return jvNull(), err
		}
		candidate := &find{sceneID, title.String, studio.String, rating.Int64, seconds}
		if best == nil || candidate.rating > best.rating ||
			(candidate.rating == best.rating && (candidate.seconds > best.seconds ||
				(candidate.seconds == best.seconds && candidate.sceneID < best.sceneID))) {
			best = candidate
		}
	}
	if best == nil {
		return jvNull(), nil
	}
	return jvObj(
		jvKey("scene_id", jvStr(best.sceneID)),
		jvKey("title", jvStr(best.title)),
		jvKey("studio", jvStr(best.studio)),
	), nil
}

// What the person taught Curator in the window: feedback that still
// stands, tag answers, and the most recent distinct tags answered.
func homeRecapLearned(db dbx, start, now int64) (jVal, error) {
	var feedback, answers int64
	if err := db.QueryRow(`SELECT COUNT(*) FROM feedback
WHERE occurred_at_ms >= ? AND occurred_at_ms <= ? AND reversed_by_id IS NULL
AND feedback_type IN ('thumb_up', 'thumb_down', 'not_now', 'never_show', 'metadata_wrong')`, start, now).Scan(&feedback); err != nil {
		return jvNull(), err
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM direct_tag_preference_history
WHERE occurred_at_ms >= ? AND occurred_at_ms <= ?`, start, now).Scan(&answers); err != nil {
		return jvNull(), err
	}
	tags := jvArr()
	rows, err := db.Query(`SELECT h.tag_id, COALESCE(t.name, ''), h.value, h.blocked
FROM direct_tag_preference_history h LEFT JOIN source_tag t ON t.tag_id = h.tag_id
WHERE h.occurred_at_ms >= ? AND h.occurred_at_ms <= ? AND h.replaced_by_id IS NULL
ORDER BY h.occurred_at_ms DESC, h.preference_id`, start, now)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	seen := map[string]bool{}
	for rows.Next() && len(tags.arr) < homeRecapTagsShown {
		var tagID, name string
		var value sql.NullFloat64
		var blocked bool
		if err := rows.Scan(&tagID, &name, &value, &blocked); err != nil {
			return jvNull(), err
		}
		if seen[tagID] || name == "" {
			continue
		}
		seen[tagID] = true
		answer := jvNull()
		if value.Valid {
			answer = jvFloat(value.Float64)
		}
		tags.arr = append(tags.arr, jvObj(
			jvKey("tag_id", jvStr(tagID)),
			jvKey("name", jvStr(name)),
			jvKey("value", answer),
			jvKey("blocked", jvBool(blocked)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(jvKey("feedback", jvInt(feedback)), jvKey("answers", jvInt(answers)), jvKey("tags", tags)), nil
}

// What is new since the previous visit: scenes added to the library (and
// how many of them came from a Whisparr send), and model updates.
func homeRecapSince(db dbx, sinceMs int64) (jVal, error) {
	var newScenes, whisparr, updates int64
	if err := db.QueryRow(`SELECT COUNT(*) FROM source_scene WHERE created_at_ms > ?`, sinceMs).Scan(&newScenes); err != nil {
		return jvNull(), err
	}
	if err := db.QueryRow(`SELECT COUNT(DISTINCT s.scene_id) FROM source_scene s
JOIN local_scene_match m ON m.scene_id = s.scene_id AND m.kind = 'stashdb_id'
JOIN external_whisparr_sent w ON w.external_id = m.value
WHERE s.created_at_ms > ?`, sinceMs).Scan(&whisparr); err != nil {
		return jvNull(), err
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM model_version
WHERE published_at_ms IS NOT NULL AND published_at_ms > ?`, sinceMs).Scan(&updates); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("since_ms", jvInt(sinceMs)),
		jvKey("new_scenes", jvInt(newScenes)),
		jvKey("whisparr_landed", jvInt(whisparr)),
		jvKey("model_updates", jvInt(updates)),
	), nil
}

// Where the window's watching went: the studios watched most, and how much
// of it was a studio or performer the person had never played before.
func homeRecapExplored(db dbx, start, now int64) (jVal, error) {
	type watched struct {
		sceneID string
		seconds float64
	}
	var scenes []watched
	rows, err := db.Query(`SELECT scene_id, SUM(active_seconds) FROM play_session
WHERE started_at_ms >= ? AND started_at_ms <= ? GROUP BY scene_id ORDER BY scene_id`, start, now)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var entry watched
		if err := rows.Scan(&entry.sceneID, &entry.seconds); err != nil {
			rows.Close()
			return jvNull(), err
		}
		scenes = append(scenes, entry)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	playedBefore := func(query string, id string) (bool, error) {
		var count int
		err := db.QueryRow(query, id, start).Scan(&count)
		return count > 0, err
	}
	type studioTally struct {
		name   string
		scenes int64
		good   int64
	}
	studios := map[string]*studioTally{}
	newStudios := map[string]bool{}
	newPerformers := map[string]bool{}
	var total, fresh float64
	for _, entry := range scenes {
		total += entry.seconds
		var studioID, studio sql.NullString
		var rating sql.NullInt64
		err := db.QueryRow(`SELECT s.studio_id, st.name, s.rating100 FROM source_scene s
LEFT JOIN source_studio st ON st.studio_id = s.studio_id WHERE s.scene_id=?`, entry.sceneID).Scan(&studioID, &studio, &rating)
		if err == sql.ErrNoRows {
			continue
		}
		if err != nil {
			return jvNull(), err
		}
		isNew := false
		if studioID.Valid && studio.Valid && strings.TrimSpace(studio.String) != "" {
			tally := studios[studioID.String]
			if tally == nil {
				tally = &studioTally{name: studio.String}
				studios[studioID.String] = tally
			}
			tally.scenes++
			if rating.Valid && rating.Int64 >= homeRecapGoodRating {
				tally.good++
			}
			before, err := playedBefore(`SELECT COUNT(*) FROM source_play p JOIN source_scene s ON s.scene_id = p.scene_id
WHERE s.studio_id=? AND p.played_at_ms < ?`, studioID.String)
			if err != nil {
				return jvNull(), err
			}
			if !before {
				newStudios[studioID.String] = true
				isNew = true
			}
		}
		performers, err := db.Query(`SELECT performer_id FROM scene_performer WHERE scene_id=? ORDER BY performer_id`, entry.sceneID)
		if err != nil {
			return jvNull(), err
		}
		var ids []string
		for performers.Next() {
			var id string
			if err := performers.Scan(&id); err != nil {
				performers.Close()
				return jvNull(), err
			}
			ids = append(ids, id)
		}
		performers.Close()
		for _, id := range ids {
			before, err := playedBefore(`SELECT COUNT(*) FROM source_play p JOIN scene_performer sp ON sp.scene_id = p.scene_id
WHERE sp.performer_id=? AND p.played_at_ms < ?`, id)
			if err != nil {
				return jvNull(), err
			}
			if !before {
				newPerformers[id] = true
				isNew = true
			}
		}
		if isNew {
			fresh += entry.seconds
		}
	}
	ranked := make([]string, 0, len(studios))
	for id := range studios {
		ranked = append(ranked, id)
	}
	sort.Slice(ranked, func(i, j int) bool {
		a, b := studios[ranked[i]], studios[ranked[j]]
		if a.scenes != b.scenes {
			return a.scenes > b.scenes
		}
		if a.good != b.good {
			return a.good > b.good
		}
		return ranked[i] < ranked[j]
	})
	top := jvArr()
	for _, id := range ranked[:minInt(3, len(ranked))] {
		top.arr = append(top.arr, jvObj(
			jvKey("studio_id", jvStr(id)),
			jvKey("name", jvStr(studios[id].name)),
			jvKey("scenes", jvInt(studios[id].scenes)),
			jvKey("rated_well", jvInt(studios[id].good)),
		))
	}
	return jvObj(
		jvKey("top_studios", top),
		jvKey("new_studios", jvInt(int64(len(newStudios)))),
		jvKey("new_performers", jvInt(int64(len(newPerformers)))),
		jvKey("watched_seconds", jvFloat(total)),
		jvKey("new_seconds", jvFloat(fresh)),
	), nil
}
