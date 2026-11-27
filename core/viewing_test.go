package main

import (
	"database/sql"
	"fmt"
	"testing"
)

func viewingDB(t *testing.T) dbx {
	t.Helper()
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	for _, scene := range []string{"s1", "s2"} {
		mustExecT(t, db, `INSERT INTO source_scene(scene_id, source_hash) VALUES (?, 'x')`, scene)
	}
	return db
}

func mustExecT(t *testing.T, db dbx, q string, args ...any) {
	t.Helper()
	if _, err := db.Exec(q, args...); err != nil {
		t.Fatal(err)
	}
}

func stringsFrom(t *testing.T, db dbx, q string, args ...any) []string {
	t.Helper()
	rows, err := db.Query(q, args...)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var v string
		if err := rows.Scan(&v); err != nil {
			t.Fatal(err)
		}
		out = append(out, v)
	}
	return out
}

func choose(t *testing.T, db dbx, choice string, spans ...viewingSpan) viewingChange {
	t.Helper()
	change, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
		return setViewingChoice(conn, choice, spans, 9_000)
	})
	if err != nil {
		t.Fatal(err)
	}
	return change
}

func undo(t *testing.T, db dbx, change viewingChange) {
	t.Helper()
	if _, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
		return undoViewingChoice(conn, change.undoJSON())
	}); err != nil {
		t.Fatal(err)
	}
}

func playerSession(id, scene string, start int64) jVal {
	return jvObj(
		jvKey("event_type", jvStr("playback_session")),
		jvKey("session_id", jvStr(id)), jvKey("scene_id", jvStr(scene)),
		jvKey("started_at_ms", jvInt(start)), jvKey("ended_at_ms", jvInt(start+500)),
		jvKey("active_seconds", jvFloat(120)),
	)
}

// The pause keeps every player session; the ones from the pause just do not
// count, until they are counted again.
func TestPausedSessionsAreKeptAndCanBeCounted(t *testing.T) {
	db := viewingDB(t)
	on := jvObj(jvKey("pauseLearning", jvBool(true)))
	off := jvObj(jvKey("pauseLearning", jvBool(false)))
	if err := syncLearningPause(db, jvNull(), 1000); err != nil { // no settings: no change
		t.Fatal(err)
	}
	for _, step := range []struct {
		settings jVal
		at       int64
	}{{on, 1000}, {on, 1500}, {off, 2000}} {
		if err := syncLearningPause(db, step.settings, step.at); err != nil {
			t.Fatal(err)
		}
	}
	rules, err := loadViewingRules(db)
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 || rules[0].startedAtMs != 1000 || rules[0].endedAtMs != 2000 || rules[0].choice != choiceExclude {
		t.Fatalf("rules = %+v", rules)
	}
	if _, err := submitSessions(db, []jVal{playerSession("during", "s1", 1200), playerSession("after", "s1", 2500)}); err != nil {
		t.Fatal(err)
	}
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT session_id FROM play_session ORDER BY session_id`)); got != "[after during]" {
		t.Fatalf("stored sessions = %s", got)
	}
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT session_id FROM counted_play_session`)); got != "[after]" {
		t.Fatalf("counted sessions = %s", got)
	}
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT session_id FROM counted_behavior_event WHERE session_id IS NOT NULL`)); got != "[after]" {
		t.Fatalf("counted signals = %s", got)
	}
	choose(t, db, choiceInclude, viewingSpan{"", 1000, 2000})
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT session_id FROM counted_play_session ORDER BY session_id`)); got != "[after during]" {
		t.Fatalf("counted after counting the pause = %s", got)
	}
}

// The views and the Go decision agree: one scene's rule beats an all-scenes
// rule, and among equally specific rules the newest wins.
func TestViewingRuleOrderMatchesTheViews(t *testing.T) {
	db := viewingDB(t)
	for _, r := range []struct {
		scene      any
		start, end int64
		choice     string
	}{
		{nil, 100, 900, choiceExclude},  // a pause
		{"s1", 300, 400, choiceInclude}, // one watch counted again
		{nil, 350, 700, choiceExclude},  // a later period: does not beat s1's watch
		{nil, 600, 650, choiceInclude},  // newest all-scenes rule wins its span
		{"s2", 640, 660, choiceExclude}, // and loses to s2's own choice
	} {
		mustExecT(t, db, `INSERT INTO viewing_rule(scene_id, started_at_ms, ended_at_ms, choice, reason, created_at_ms)
VALUES (?, ?, ?, ?, 'chosen', 1)`, r.scene, r.start, r.end, r.choice)
	}
	ordinal := 0
	for at := int64(0); at <= 1000; at += 10 {
		for _, scene := range []string{"s1", "s2"} {
			mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, ?)`, scene, at, ordinal)
			ordinal++
		}
	}
	rules, err := loadViewingRules(db)
	if err != nil {
		t.Fatal(err)
	}
	counted := map[string]bool{}
	for _, key := range stringsFrom(t, db, `SELECT scene_id || ':' || played_at_ms FROM counted_source_play`) {
		counted[key] = true
	}
	for at := int64(0); at <= 1000; at += 10 {
		for _, scene := range []string{"s1", "s2"} {
			key := fmt.Sprintf("%s:%d", scene, at)
			if counted[key] != countedAt(rules, scene, at) {
				t.Fatalf("%s: view %v, Go %v", key, counted[key], countedAt(rules, scene, at))
			}
		}
	}
	for key, want := range map[string]bool{"s1:50": true, "s1:150": false, "s1:320": true, "s1:500": false, "s2:620": true, "s2:645": false, "s1:950": true} {
		if counted[key] != want {
			t.Fatalf("%s counted = %v, want %v", key, counted[key], want)
		}
	}
}

// A watch's choice replaces its earlier one, beats a pause, and undo puts
// back exactly the rules that were there.
func TestWatchChoiceAndUndo(t *testing.T) {
	db := viewingDB(t)
	mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', 1500, 0), ('s2', 1500, 0)`)
	if err := syncLearningPause(db, jvObj(jvKey("pauseLearning", jvBool(true))), 1000); err != nil {
		t.Fatal(err)
	}
	countedScenes := func() string {
		return fmt.Sprint(stringsFrom(t, db, `SELECT scene_id FROM counted_source_play ORDER BY scene_id`))
	}
	if got := countedScenes(); got != "[]" {
		t.Fatalf("paused = %s", got)
	}
	include := choose(t, db, choiceInclude, viewingSpan{"s1", 1400, 1600})
	if got := countedScenes(); got != "[s1]" {
		t.Fatalf("after counting s1 = %s", got)
	}
	exclude := choose(t, db, choiceExclude, viewingSpan{"s1", 1400, 1600})
	if len(exclude.removed) != 1 || exclude.removed[0].ruleID != include.added[0] {
		t.Fatalf("the second choice should replace the first: %+v", exclude)
	}
	if got := countedScenes(); got != "[]" {
		t.Fatalf("after not counting s1 = %s", got)
	}
	undo(t, db, exclude)
	if got := countedScenes(); got != "[s1]" {
		t.Fatalf("undo should count s1 again = %s", got)
	}
	undo(t, db, include)
	if got := countedScenes(); got != "[]" {
		t.Fatalf("undo should leave only the pause = %s", got)
	}
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT reason FROM viewing_rule`)); got != "[paused]" {
		t.Fatalf("rules left = %s", got)
	}
	// Undo never removes a pause, whatever it is handed.
	var pauseID int64
	if err := db.QueryRow(`SELECT rule_id FROM viewing_rule`).Scan(&pauseID); err != nil {
		t.Fatal(err)
	}
	undo(t, db, viewingChange{added: []int64{pauseID}})
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT reason FROM viewing_rule`)); got != "[paused]" {
		t.Fatalf("undo removed the pause: %s", got)
	}
}

// Forgetting a period deletes nothing: its plays drop out of the history
// Curator rebuilds from Stash and come back when the period is undone.
func TestForgetViewingIsReversible(t *testing.T) {
	db := viewingDB(t)
	mustExecT(t, db, `INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms, active_seconds, provenance, confidence, summary_json)
VALUES ('recent', 's1', 5000, 5100, 1, 'direct_player', 1, '{}')`)
	mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', 300, 0), ('s1', 5050, 1)`)
	if _, err := historicalRebuild(db, nil, nil); err != nil {
		t.Fatal(err)
	}
	imputed := func() string {
		return fmt.Sprint(stringsFrom(t, db, `SELECT started_at_ms FROM play_session WHERE provenance='historical_imputed' ORDER BY started_at_ms`))
	}
	before := imputed()
	got, err := forgetViewing(db, 4000, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if n := len(stringsFrom(t, db, `SELECT session_id FROM play_session WHERE session_id='recent'`)); n != 1 {
		t.Fatal("forgetting must not delete the player session")
	}
	if n := len(stringsFrom(t, db, `SELECT session_id FROM counted_play_session WHERE session_id='recent'`)); n != 0 {
		t.Fatal("the forgotten session still counts")
	}
	after := imputed()
	if after == before || len(stringsFrom(t, db, `SELECT 1 FROM play_session WHERE provenance='historical_imputed' AND started_at_ms >= 4000`)) != 0 {
		t.Fatalf("history still has the forgotten play: %s -> %s", before, after)
	}
	if _, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
		return undoViewingChoice(conn, got.get("undo"))
	}); err != nil {
		t.Fatal(err)
	}
	if imputed() != before {
		t.Fatalf("undo should rebuild the play: %s, want %s", imputed(), before)
	}
	if _, err := forgetViewing(db, 6000, 6000); err == nil {
		t.Fatal("an empty period must be refused")
	}
}

// Stash's per-scene play count loses only the plays that do not count.
func TestCountedScenePlayCount(t *testing.T) {
	db := viewingDB(t)
	mustExecT(t, db, `UPDATE source_scene SET play_count=5 WHERE scene_id='s1'`)
	mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', 100, 0), ('s1', 200, 1)`)
	choose(t, db, choiceExclude, viewingSpan{"s1", 150, 250})
	var n int
	if err := db.QueryRow(`SELECT play_count FROM counted_scene_play WHERE scene_id='s1'`).Scan(&n); err != nil || n != 4 {
		t.Fatalf("counted play_count = %d, %v", n, err)
	}
}

// Pause periods and forgotten periods from 0052 carry over as exclude rules.
func TestViewingRuleMigrationKeepsLearningPauses(t *testing.T) {
	db, _ := openTempDB(t)
	all, err := loadMigrations()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := queryMigrationStatus(db); err != nil { // creates schema_migration
		t.Fatal(err)
	}
	for _, m := range all {
		if m.version > 53 {
			break
		}
		if err := migrateOne(db, m, 1); err != nil {
			t.Fatal(err)
		}
	}
	mustExecT(t, db, `INSERT INTO learning_pause(started_at_ms, ended_at_ms, reason)
VALUES (100, 200, 'forgotten'), (300, 300, 'forgotten'), (500, NULL, 'paused')`)
	if err := migrate(db, 2); err != nil {
		t.Fatal(err)
	}
	rules, err := loadViewingRules(db)
	if err != nil {
		t.Fatal(err)
	}
	got := fmt.Sprint(rules)
	want := "[{1  100 200 exclude chosen 100} {2  300 301 exclude chosen 300} {3  500 -1 exclude paused 500}]"
	if got != want {
		t.Fatalf("rules = %s\nwant    %s", got, want)
	}
}

// One watch joins the sessions and the Stash play of one sitting; a Stash
// play from elsewhere is its own watch.
func TestViewingHistoryJoinsSessionsAndStashPlays(t *testing.T) {
	db := viewingDB(t)
	day := int64(86_400_000)
	now := 40 * day
	start := now - 2*3_600_000
	mustExecT(t, db, `INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms, active_seconds, provenance, confidence, summary_json)
VALUES ('a', 's1', ?, ?, 30, 'direct_player', 1, '{"lane":"best_bets","origin":"curator"}'),
       ('b', 's1', ?, ?, 90, 'direct_player', 1, '{"origin":"curator"}')`,
		start, start+60_000, start+120_000, start+300_000)
	mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', ?, 0), ('s2', ?, 0)`,
		start+200_000, now-5*day)
	if err := syncLearningPause(db, jvObj(jvKey("pauseLearning", jvBool(true))), now-day); err != nil {
		t.Fatal(err)
	}
	got, err := viewingHistory(db, 50, -1, now)
	if err != nil {
		t.Fatal(err)
	}
	items := got.get("items").arr
	if len(items) != 2 {
		t.Fatalf("items = %s", got.marshalCompact())
	}
	first, second := items[0], items[1]
	if first.get("scene_id").asString() != "s1" || first.get("source").asString() != "lane" ||
		first.get("lane").asString() != "best_bets" || first.get("watched_seconds").asString() != "120.0" ||
		first.get("stash_plays").asString() != "1" || first.get("counted").truthy() ||
		first.get("reason").asString() != "paused" {
		t.Fatalf("first = %s", first.marshalCompact())
	}
	if second.get("scene_id").asString() != "s2" || second.get("source").asString() != "history" ||
		second.get("watched_seconds").kind != jNull || !second.get("counted").truthy() {
		t.Fatalf("second = %s", second.marshalCompact())
	}
	if !got.get("paused").truthy() || got.get("paused_not_counted").asString() != "1" ||
		got.get("summary").get("counted").asString() != "1" || got.get("summary").get("not_counted").asString() != "1" {
		t.Fatalf("status = %s", got.marshalCompact())
	}
	// The returned span is what set_viewing_choice takes back.
	choose(t, db, choiceInclude, viewingSpan{"s1",
		pythonIntErrOr(first.get("started_at_ms"), -1), pythonIntErrOr(first.get("ended_at_ms"), -1)})
	got, err = viewingHistory(db, 1, -1, now)
	if err != nil {
		t.Fatal(err)
	}
	if !got.get("items").arr[0].get("counted").truthy() || !got.get("has_more").truthy() {
		t.Fatalf("after counting = %s", got.marshalCompact())
	}
	if n := len(stringsFrom(t, db, `SELECT session_id FROM counted_play_session WHERE provenance='direct_player'`)); n != 2 {
		t.Fatalf("both sessions of the watch should count, got %d", n)
	}
}

// A period choice replaces the earlier period choices it covers whole, but
// keeps pauses and every watch's own choice; undo brings the old ones back.
func TestPeriodChoiceReplacesCoveredPeriods(t *testing.T) {
	db := viewingDB(t)
	mustExecT(t, db, `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES ('s1', 150, 0), ('s2', 150, 0)`)
	inner := choose(t, db, choiceExclude, viewingSpan{"", 120, 180})
	choose(t, db, choiceInclude, viewingSpan{"", 50, 150}) // overlaps, not covered
	if err := syncLearningPause(db, jvObj(jvKey("pauseLearning", jvBool(true))), 130); err != nil {
		t.Fatal(err)
	}
	choose(t, db, choiceInclude, viewingSpan{"s1", 140, 160})
	wide := choose(t, db, choiceExclude, viewingSpan{"", 100, 200})
	if len(wide.removed) != 1 || wide.removed[0].ruleID != inner.added[0] {
		t.Fatalf("only the covered period should go: %+v", wide.removed)
	}
	reasons := func() string {
		return fmt.Sprint(stringsFrom(t, db, `SELECT COALESCE(scene_id, '*') || ':' || choice || ':' || reason FROM viewing_rule ORDER BY rule_id`))
	}
	if got := reasons(); got != "[*:include:chosen *:exclude:paused s1:include:chosen *:exclude:chosen]" {
		t.Fatalf("rules = %s", got)
	}
	if got := fmt.Sprint(stringsFrom(t, db, `SELECT scene_id FROM counted_source_play ORDER BY scene_id`)); got != "[s1]" {
		t.Fatalf("counted = %s (the watch's own choice should stand)", got)
	}
	undo(t, db, wide)
	if got := reasons(); got != "[*:exclude:chosen *:include:chosen *:exclude:paused s1:include:chosen]" {
		t.Fatalf("after undo = %s", got)
	}
}
