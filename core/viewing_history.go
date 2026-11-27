// get_viewing_history: every watch Curator knows about, newest first, with
// whether it counts. A watch joins the player sessions Curator recorded for
// one scene in a row with the plays Stash recorded during them; a Stash play
// with no session (another device or app) is a watch of its own.
package main

import "sort"

const (
	// Sessions of one scene this close together are one watch: Stash rebuilds
	// its player, and a viewer steps away and back.
	watchJoinGapMs = 10 * 60_000
	// A Stash play this far outside a watch still belongs to it: Stash adds
	// the play once enough of the scene has played, not when it starts.
	watchPlaySlackMs = 2 * 60_000
	viewingSummaryMs = 30 * 86_400_000
)

type viewingWatch struct {
	sceneID        string
	startedAtMs    int64
	endedAtMs      int64 // last moment seen; the rule span ends one ms later
	watchedSeconds float64
	sessions       int
	stashPlays     int
	lane           string
	origin         string
}

type sessionRow struct {
	sceneID      string
	startedAtMs  int64
	endedAtMs    int64
	activeSecond float64
	lane         string
	origin       string
}

// loadViewingWatches builds every watch, oldest first per scene.
func loadViewingWatches(db dbx) ([]viewingWatch, error) {
	sessions := map[string][]sessionRow{}
	rows, err := db.Query(`
SELECT s.scene_id, s.started_at_ms, COALESCE(s.ended_at_ms, s.started_at_ms), s.active_seconds,
       COALESCE(json_extract(s.summary_json, '$.lane'), i.lane, ''),
       COALESCE(json_extract(s.summary_json, '$.origin'), '')
FROM play_session s LEFT JOIN impression i ON i.impression_id = s.impression_id
WHERE s.provenance = 'direct_player' AND ` + observedPlaybackSQL + `
ORDER BY s.scene_id, s.started_at_ms`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var r sessionRow
		if err := rows.Scan(&r.sceneID, &r.startedAtMs, &r.endedAtMs, &r.activeSecond, &r.lane, &r.origin); err != nil {
			rows.Close()
			return nil, err
		}
		sessions[r.sceneID] = append(sessions[r.sceneID], r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	plays := map[string][]int64{}
	rows, err = db.Query(`SELECT scene_id, played_at_ms FROM source_play ORDER BY scene_id, played_at_ms`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var scene string
		var at int64
		if err := rows.Scan(&scene, &at); err != nil {
			rows.Close()
			return nil, err
		}
		plays[scene] = append(plays[scene], at)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	scenes := make([]string, 0, len(sessions)+len(plays))
	seen := map[string]bool{}
	for scene := range sessions {
		scenes, seen[scene] = append(scenes, scene), true
	}
	for scene := range plays {
		if !seen[scene] {
			scenes = append(scenes, scene)
		}
	}
	sort.Strings(scenes)
	var watches []viewingWatch
	for _, scene := range scenes {
		var own []viewingWatch
		for _, s := range sessions[scene] {
			if n := len(own); n > 0 && s.startedAtMs-own[n-1].endedAtMs <= watchJoinGapMs {
				w := &own[n-1]
				w.endedAtMs = max(w.endedAtMs, s.endedAtMs)
				w.watchedSeconds += s.activeSecond
				w.sessions++
				if w.lane == "" {
					w.lane = s.lane
				}
				continue
			}
			own = append(own, viewingWatch{sceneID: scene, startedAtMs: s.startedAtMs, endedAtMs: s.endedAtMs,
				watchedSeconds: s.activeSecond, sessions: 1, lane: s.lane, origin: s.origin})
		}
		for _, at := range plays[scene] {
			matched := false
			for i := range own {
				w := &own[i]
				if w.sessions > 0 && at >= w.startedAtMs-watchPlaySlackMs && at <= w.endedAtMs+watchPlaySlackMs {
					w.stashPlays++
					w.startedAtMs = min(w.startedAtMs, at)
					w.endedAtMs = max(w.endedAtMs, at)
					matched = true
					break
				}
			}
			if !matched {
				own = append(own, viewingWatch{sceneID: scene, startedAtMs: at, endedAtMs: at, stashPlays: 1})
			}
		}
		watches = append(watches, own...)
	}
	return watches, nil
}

func watchStatus(rules []viewingRule, w viewingWatch) (bool, string) {
	rule := decideViewing(rules, w.sceneID, w.startedAtMs)
	if rule == nil || rule.choice == choiceInclude {
		return true, ""
	}
	return false, rule.reason
}

func watchJSON(rules []viewingRule, w viewingWatch) jVal {
	counted, reason := watchStatus(rules, w)
	source := "history" // a Stash play with no Curator session
	switch {
	case w.sessions > 0 && w.lane != "":
		source = "lane"
	case w.sessions > 0:
		source = "stash"
	}
	watched := jvNull()
	if w.sessions > 0 {
		watched = jvFloat(w.watchedSeconds)
	}
	reasonValue := jvNull()
	if reason != "" {
		reasonValue = jvStr(reason)
	}
	lane := jvNull()
	if w.lane != "" {
		lane = jvStr(w.lane)
	}
	return jvObj(
		jvKey("scene_id", jvStr(w.sceneID)),
		jvKey("started_at_ms", jvInt(w.startedAtMs)),
		jvKey("ended_at_ms", jvInt(w.endedAtMs+1)),
		jvKey("watched_seconds", watched),
		jvKey("source", jvStr(source)),
		jvKey("lane", lane),
		jvKey("stash_plays", jvInt(int64(w.stashPlays))),
		jvKey("counted", jvBool(counted)),
		jvKey("reason", reasonValue),
	)
}

// viewingHistory pages watches newest first: limit watches that started
// before beforeMs (every watch when beforeMs < 0).
func viewingHistory(db dbx, limit, beforeMs, nowMs int64) (jVal, error) {
	if limit < 1 || limit > 200 {
		limit = 50
	}
	rules, err := loadViewingRules(db)
	if err != nil {
		return jvNull(), err
	}
	watches, err := loadViewingWatches(db)
	if err != nil {
		return jvNull(), err
	}
	sort.SliceStable(watches, func(i, j int) bool {
		if watches[i].startedAtMs != watches[j].startedAtMs {
			return watches[i].startedAtMs > watches[j].startedAtMs
		}
		return watches[i].sceneID < watches[j].sceneID
	})
	items := jvArr()
	hasMore := false
	var summary struct{ watches, counted, notCounted int64 }
	watchedSeconds := 0.0
	pausedPending := int64(0)
	for _, w := range watches {
		counted, reason := watchStatus(rules, w)
		if reason == reasonPaused {
			pausedPending++
		}
		if w.startedAtMs >= nowMs-viewingSummaryMs {
			summary.watches++
			watchedSeconds += w.watchedSeconds
			if counted {
				summary.counted++
			} else {
				summary.notCounted++
			}
		}
		if beforeMs >= 0 && w.startedAtMs >= beforeMs {
			continue
		}
		if int64(len(items.arr)) == limit {
			hasMore = true
			continue
		}
		items.arr = append(items.arr, watchJSON(rules, w))
	}
	pauses := jvArr()
	pausedSince := jvNull()
	for _, r := range rules {
		if r.reason != reasonPaused || r.sceneID != "" {
			continue
		}
		pauses.arr = append(pauses.arr, ruleJSON(r))
		if r.endedAtMs < 0 {
			pausedSince = jvInt(r.startedAtMs)
		}
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("paused", jvBool(pausedSince.kind != jNull)),
		jvKey("paused_since_ms", pausedSince),
		jvKey("pause_periods", pauses),
		jvKey("paused_not_counted", jvInt(pausedPending)),
		jvKey("summary", jvObj(
			jvKey("days", jvInt(viewingSummaryMs/86_400_000)),
			jvKey("watches", jvInt(summary.watches)),
			jvKey("watched_seconds", jvFloat(watchedSeconds)),
			jvKey("counted", jvInt(summary.counted)),
			jvKey("not_counted", jvInt(summary.notCounted)),
		)),
		jvKey("items", items),
		jvKey("has_more", jvBool(hasMore)),
	), nil
}

func opGetViewingHistory(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_viewing_history", func(settings jVal) (jVal, error) {
		args := payload.get("args")
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		return viewingHistory(db, pythonIntErrOr(args.get("limit"), 50), pythonIntErrOr(args.get("before_ms"), -1), nowMs())
	})
}
