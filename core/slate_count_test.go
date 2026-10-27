package main

import (
	"fmt"
	"strings"
	"testing"
)

// The uncached lane count only fully checks lane scenes SQLite flags as
// suspects; every ineligibility reason must still be caught, and scenes that
// merely appear in an eligibility table (an upvote, an expired not-now, a
// kept pruning candidate) must still count.
func TestIneligibleLaneScenesMatchesFullEligibility(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := nowMs()
	day := int64(86_400_000)
	scenes := []string{"ok", "nofile", "unavailable", "down", "up", "notnow", "oldnotnow", "excluded",
		"expired", "reversed", "review", "keep", "blocked", "bbplayed", "revisitfresh", "revisitold", "otherplayed"}
	sourceLane := map[string]string{"bbplayed": "best_bets", "revisitfresh": "revisit", "revisitold": "revisit", "otherplayed": "stretch"}
	statements := []string{
		`INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms)
VALUES ('model', 'published', 'features', '{}', 0)`,
	}
	fixtures := []string{
		`INSERT INTO source_tag(tag_id, source_hash) VALUES ('bad', 'fixture'), ('fine', 'fixture')`,
		`INSERT INTO direct_tag_preference_history(preference_id, tag_id, value, occurred_at_ms, blocked)
VALUES ('p1', 'bad', -1, 1, 1), ('p2', 'fine', -1, 1, 0)`,
		`INSERT INTO direct_tag_preference(tag_id, preference_id, value, occurred_at_ms, blocked)
VALUES ('bad', 'p1', -1, 1, 1), ('fine', 'p2', -1, 1, 0)`,
		`INSERT INTO scene_tag(scene_id, tag_id) VALUES ('blocked', 'bad'), ('ok', 'fine')`,
		`UPDATE source_file SET available=0 WHERE scene_id='unavailable'`,
		`DELETE FROM source_file WHERE scene_id='nofile'`,
		fmt.Sprintf(`INSERT INTO feedback(feedback_id, scene_id, feedback_type, occurred_at_ms) VALUES
('f1', 'down', 'thumb_down', %d), ('f2', 'up', 'thumb_up', %d),
('f3', 'notnow', 'not_now', %d), ('f4', 'oldnotnow', 'not_now', %d)`, now-day, now-day, now-day, now-40*day),
		fmt.Sprintf(`INSERT INTO exclusion VALUES
('e1', 'scene', 'excluded', 'hidden', 1, NULL, NULL),
('e2', 'scene', 'expired', 'hidden', 1, %d, NULL),
('e3', 'scene', 'reversed', 'hidden', 1, NULL, 2)`, now-day),
		`INSERT INTO pruning_candidate VALUES ('review', 'review', 1, 1, NULL), ('keep', 'keep', 1, 1, NULL)`,
		fmt.Sprintf(`INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms, active_seconds, provenance, confidence)
VALUES ('s1', 'bbplayed', %[1]d, %[1]d, 60, 'direct_player', 1),
       ('s2', 'revisitfresh', %[1]d, %[1]d, 60, 'direct_player', 1),
       ('s3', 'revisitold', %[2]d, %[2]d, 60, 'direct_player', 1),
       ('s4', 'otherplayed', %[1]d, %[1]d, 60, 'direct_player', 1)`, now-day, now-200*day),
	}
	for i, scene := range scenes {
		lane := sourceLane[scene]
		if lane == "" {
			lane = "stretch"
		}
		statements = append(statements,
			fmt.Sprintf(`INSERT INTO source_scene(scene_id, source_hash) VALUES ('%s', 'fixture')`, scene),
			fmt.Sprintf(`INSERT INTO source_file(file_id, scene_id, source_hash) VALUES ('file-%s', '%s', 'fixture')`, scene, scene),
			fmt.Sprintf(`INSERT INTO model_lane_order(model_id, lane, ordering, position, scene_id, source_lane, utility)
VALUES ('model', 'for_you', 'varied', %d, '%s', '%s', 0)`, i, scene, lane))
	}
	for _, query := range append(statements, fixtures...) {
		if _, err := db.Exec(query); err != nil {
			t.Fatalf("%v\n%s", err, query)
		}
	}

	laneSQL := `SELECT scene_id, source_lane FROM model_lane_order WHERE model_id=? AND lane=? AND ordering=?`
	got, err := ineligibleLaneScenes(db, laneSQL, []any{"model", "for_you", "varied"}, now)
	if err != nil {
		t.Fatal(err)
	}
	all := make(map[string]bool, len(scenes))
	for _, scene := range scenes {
		all[scene] = true
	}
	eligibility, err := sceneEligibility(db, now, all)
	if err != nil {
		t.Fatal(err)
	}
	filter, err := directPlayFilters(db, now)
	if err != nil {
		t.Fatal(err)
	}
	var want []string
	for _, scene := range scenes {
		lane := sourceLane[scene]
		if lane == "" {
			lane = "stretch"
		}
		if !materializedRowIsEligible(scene, lane, eligibility, filter) {
			want = append(want, scene)
		}
	}
	var gotList []string
	for _, scene := range scenes {
		if got[scene] {
			gotList = append(gotList, scene)
		}
	}
	if strings.Join(gotList, ",") != strings.Join(want, ",") || len(got) != len(want) {
		t.Fatalf("ineligible = %v, full check = %v", gotList, want)
	}
	if expected := "nofile,unavailable,down,notnow,excluded,review,blocked,bbplayed,revisitfresh"; strings.Join(want, ",") != expected {
		t.Fatalf("fixture no longer covers every reason: %v", want)
	}
}

// The available-file probe behind lane eligibility must stay a covering
// index lookup; reading each source_file row cost more than the rest of it.
func TestAvailableFileProbeUsesPartialIndex(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	rows, err := db.Query(`EXPLAIN QUERY PLAN SELECT 1 FROM source_scene l
WHERE NOT EXISTS (SELECT 1 FROM source_file f WHERE f.scene_id=l.scene_id AND f.available=1)`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var plan []string
	for rows.Next() {
		var id, parent, unused int
		var detail string
		if err := rows.Scan(&id, &parent, &unused, &detail); err != nil {
			t.Fatal(err)
		}
		plan = append(plan, detail)
	}
	if !strings.Contains(strings.Join(plan, "\n"), "COVERING INDEX source_file_available_scene_idx") {
		t.Fatalf("plan does not use the partial index:\n%s", strings.Join(plan, "\n"))
	}
}
