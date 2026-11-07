package main

import (
	"testing"
)

func TestLearningPauseFollowsTheSettingAndSkipsSessions(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	mustExec := func(q string, args ...any) {
		t.Helper()
		if _, err := db.Exec(q, args...); err != nil {
			t.Fatal(err)
		}
	}
	mustExec(`INSERT INTO source_scene(scene_id, source_hash) VALUES ('s1', 'x')`)
	on := jvObj(jvKey("pauseLearning", jvBool(true)))
	off := jvObj(jvKey("pauseLearning", jvBool(false)))
	// No settings (a task or hook): nothing changes.
	if err := syncLearningPause(db, jvNull(), 1000); err != nil {
		t.Fatal(err)
	}
	if err := syncLearningPause(db, on, 1000); err != nil {
		t.Fatal(err)
	}
	if err := syncLearningPause(db, on, 1500); err != nil { // still on: one period
		t.Fatal(err)
	}
	if err := syncLearningPause(db, off, 2000); err != nil {
		t.Fatal(err)
	}
	windows, err := loadPauseWindows(db)
	if err != nil {
		t.Fatal(err)
	}
	if len(windows) != 1 || windows[0] != (pauseWindow{1000, 2000}) {
		t.Fatalf("windows = %+v", windows)
	}
	session := func(id string, start int64) jVal {
		return jvObj(
			jvKey("event_type", jvStr("playback_session")),
			jvKey("session_id", jvStr(id)), jvKey("scene_id", jvStr("s1")),
			jvKey("started_at_ms", jvInt(start)), jvKey("ended_at_ms", jvInt(start+500)),
			jvKey("active_seconds", jvFloat(0.5)),
		)
	}
	n, err := submitSessions(db, []jVal{session("during", 1200), session("after", 2500)})
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	rows, err := db.Query(`SELECT session_id FROM play_session ORDER BY session_id`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
	}
	rows.Close()
	if n != 1 || len(ids) != 1 || ids[0] != "after" {
		t.Fatalf("recorded %d sessions: %v", n, ids)
	}
}

func TestForgetViewingRemovesSessionsAndSignalsInThePeriod(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	for _, q := range []string{
		`INSERT INTO source_scene(scene_id, source_hash) VALUES ('s1', 'x')`,
		`INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms, active_seconds, provenance, confidence, summary_json)
VALUES ('old', 's1', 100, 200, 1, 'direct_player', 1, '{}'), ('recent', 's1', 5000, 5100, 1, 'direct_player', 1, '{}')`,
		`INSERT INTO behavior_event(event_id, event_type, scene_id, occurred_at_ms, outcome, confidence, provenance, session_id, payload_json)
VALUES ('e-old', 'occasion_outcome', 's1', 200, -0.1, 0.5, 'direct_player', 'old', '{}'),
       ('e-recent', 'occasion_outcome', 's1', 5100, -0.1, 0.5, 'direct_player', 'recent', '{}')`,
	} {
		if _, err := db.Exec(q); err != nil {
			t.Fatal(err)
		}
	}
	got, err := forgetViewing(db, 4000, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if got.get("forgotten_sessions").asString() != "1" || got.get("forgotten_signals").asString() != "1" {
		t.Fatalf("result = %s", got.marshalCompact())
	}
	var left int
	if err := db.QueryRow(`SELECT count(*) FROM play_session WHERE session_id='old'`).Scan(&left); err != nil || left != 1 {
		t.Fatalf("older session should stay: %d, %v", left, err)
	}
	// Plays rebuilt from Stash's history drop out inside the period too.
	if _, err := db.Exec(`INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', 300, 0), ('s1', 5050, 1)`); err != nil {
		t.Fatal(err)
	}
	if _, err := historicalRebuild(db, nil, nil); err != nil {
		t.Fatal(err)
	}
	var imputed []int64
	rows, err := db.Query(`SELECT started_at_ms FROM play_session WHERE provenance='historical_imputed'`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var at int64
		if err := rows.Scan(&at); err != nil {
			t.Fatal(err)
		}
		imputed = append(imputed, at)
	}
	rows.Close()
	for _, at := range imputed {
		if at >= 4000 && at < 6000 {
			t.Fatalf("a forgotten play came back from history: %v", imputed)
		}
	}
	if len(imputed) == 0 {
		t.Fatal("the play outside the period should still be rebuilt")
	}
	if _, err := forgetViewing(db, 6000, 6000); err == nil {
		t.Fatal("an empty period must be refused")
	}
}
