package main

import "testing"

func TestHomeRecapSummarizesTheWeekAndWhatIsNew(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	const day = int64(86_400_000)
	now := int64(1_800_000_000_000)
	exec := func(query string, args ...any) {
		t.Helper()
		if _, err := db.Exec(query, args...); err != nil {
			t.Fatal(err)
		}
	}
	exec(`INSERT INTO source_studio (studio_id, name, source_hash) VALUES ('st-old', 'Studio Old', 'h'), ('st-new', 'Studio New', 'h')`)
	exec(`INSERT INTO source_scene (scene_id, title, studio_id, rating100, source_hash, created_at_ms) VALUES
('old-fav', 'Old favourite', 'st-old', 90, 'h', ?),
('new-find', 'New find', 'st-new', 80, 'h', ?),
('meh', 'Meh', 'st-old', 40, 'h', ?),
('liked', 'Liked', 'st-old', NULL, 'h', ?),
('fresh', 'Fresh arrival', 'st-old', NULL, 'h', ?)`, now-90*day, now-30*day, now-30*day, now-30*day, now-day)
	exec(`INSERT INTO source_play (scene_id, played_at_ms, ordinal) VALUES ('old-fav', ?, 0)`, now-40*day)
	exec(`INSERT INTO impression (impression_id, requested_at_ms, lane, config_version) VALUES ('imp', ?, 'for_you', 'v')`, now-3*day)
	exec(`INSERT INTO play_session (session_id, scene_id, started_at_ms, active_seconds, provenance, confidence, impression_id) VALUES
('s1', 'old-fav', ?, 600, 'curator', 1, 'imp'),
('s2', 'new-find', ?, 900, 'curator', 1, 'imp'),
('s3', 'meh', ?, 120, 'curator', 1, 'imp'),
('s4', 'liked', ?, 300, 'curator', 1, 'imp'),
('s5', 'meh', ?, 60, 'stash', 1, NULL),
('s6', 'old-fav', ?, 999, 'curator', 1, 'imp')`, now-2*day, now-day, now-day, now-day, now-day, now-20*day)
	exec(`INSERT INTO feedback (feedback_id, scene_id, feedback_type, occurred_at_ms) VALUES
('f1', 'liked', 'thumb_up', ?), ('f2', 'meh', 'thumb_down', ?), ('f3', 'meh', 'reversal', ?)`, now-day, now-day, now-day)
	exec(`INSERT INTO source_tag (tag_id, name, source_hash) VALUES ('t1', 'Outdoor', 'h'), ('t2', 'Long take', 'h')`)
	exec(`INSERT INTO direct_tag_preference_history (preference_id, tag_id, value, occurred_at_ms) VALUES
('p1', 't1', 0.5, ?), ('p2', 't1', 1, ?), ('p3', 't2', -0.5, ?)`, now-3*day, now-2*day, now-day)
	exec(`UPDATE direct_tag_preference_history SET replaced_by_id='p2' WHERE preference_id='p1'`)
	exec(`INSERT INTO local_scene_match (scene_id, kind, value) VALUES ('fresh', 'stashdb_id', 'sdb-1')`)
	exec(`INSERT INTO external_whisparr_sent (endpoint, external_id, sent_at_ms) VALUES ('https://stashdb.org/graphql', 'sdb-1', ?)`, now-10*day)
	exec(`INSERT INTO model_version (model_id, status, feature_version, config_json, created_at_ms, published_at_ms) VALUES
('m-old', 'superseded', 'f', '{}', ?, ?), ('m-new', 'published', 'f', '{}', ?, ?)`, now-10*day, now-10*day, now-day, now-day)

	recap, err := homeRecap(db, now, 7, now-5*day)
	if err != nil {
		t.Fatal(err)
	}
	if got := pythonInt(recap.get("picks_watched")); got != 4 {
		t.Fatalf("picks watched = %d, want 4 (Curator sessions in the window, distinct scenes)", got)
	}
	if got := pythonInt(recap.get("rated_well")); got != 3 {
		t.Fatalf("rated well = %d, want 3 (two ratings of 70+ and one thumbs up)", got)
	}
	if got := number(recap.get("watched_seconds")); got != 1920 {
		t.Fatalf("watched seconds = %v, want 1920", got)
	}
	if got := len(recap.get("sessions").arr); got != 5 {
		t.Fatalf("sessions = %d, want every session in the window", got)
	}
	best := recap.get("best_find")
	if best.get("scene_id").asString() != "new-find" || best.get("studio").asString() != "Studio New" {
		t.Fatalf("best find = %v, want the pick from a studio never played before", best)
	}
	learned := recap.get("learned")
	if pythonInt(learned.get("feedback")) != 2 || pythonInt(learned.get("answers")) != 3 {
		t.Fatalf("learned = %v", learned)
	}
	tags := learned.get("tags").arr
	if len(tags) != 2 || tags[0].get("name").asString() != "Long take" || number(tags[1].get("value")) != 1 {
		t.Fatalf("tags = %v, want the newest standing answer per tag", learned.get("tags"))
	}
	since := recap.get("since")
	if pythonInt(since.get("new_scenes")) != 1 || pythonInt(since.get("whisparr_landed")) != 1 || pythonInt(since.get("model_updates")) != 1 {
		t.Fatalf("since = %v", since)
	}
	quiet, err := homeRecap(db, now, 7, 0)
	if err != nil {
		t.Fatal(err)
	}
	if quiet.get("since").kind != jNull {
		t.Fatalf("no since block without a previous visit: %v", quiet.get("since"))
	}
}
