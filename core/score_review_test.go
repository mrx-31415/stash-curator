package main

// Unit tests for get_score_review (core/score_review.go): appeal-ascending
// ordering, the max_appeal cap, paging math, live eligibility, impression
// recording, item shape, and the validation/model-required error paths.

import (
	"strings"
	"testing"
)

// scoreReviewSeed seeds a published model with score rows covering the
// review window, plus the rows sceneEligibility reads. s3 is hard-excluded,
// s4 carries a current thumb_down, and s8 has no available file. The review
// surface drops only current_thumb_down from eligibility: s4 is shown, s3
// and s8 are filtered from items and total.
func scoreReviewSeed(t *testing.T) dbx {
	t.Helper()
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	exec := func(query string, args ...any) {
		t.Helper()
		if _, err := db.Exec(query, args...); err != nil {
			t.Fatalf("seed %q: %v", query, err)
		}
	}
	exec(`INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms, published_at_ms)
VALUES ('model', 'published', 'features', '{}', 1, 1)`)
	exec(`INSERT INTO feature_build(feature_version, status, config_json, source_fingerprint, created_at_ms, published_at_ms)
VALUES ('features', 'published', '{}', 'source', 1, 1)`)
	scenes := []struct {
		id     string
		appeal float64
		file   bool
	}{
		{"s1", -0.9, true},
		{"s2", -0.6, true},
		{"s3", -0.4, true},
		{"s4", -0.2, true},
		{"s5", 0.0, true},
		{"s6", 0.1, true},
		{"s7", 0.3, true},
		{"s8", -0.5, false}, // no available file -> file_unavailable
	}
	for _, s := range scenes {
		exec(`INSERT INTO source_scene(scene_id, title, source_hash) VALUES (?, ?, ?)`, s.id, s.id, s.id)
		if s.file {
			exec(`INSERT INTO source_file(file_id, scene_id, available, source_hash) VALUES (?, ?, 1, ?)`, "f-"+s.id, s.id, s.id)
		}
		exec(`INSERT INTO model_scene_score(
model_id, scene_id, general_appeal, direct_appeal, direct_confidence, appeal,
current_fit, confidence, metadata_confidence, recovery, components_json, eligibility_json
) VALUES ('model', ?, ?, ?, 0.5, ?, ?, 0.8, 0.8, 0.5, ?, ?)`,
			s.id, s.appeal, s.appeal, s.appeal, s.appeal*0.5,
			`{"baseline":{"raw":0.0,"value":0.0}}`, `{"eligible":true}`)
	}
	exec(`INSERT INTO exclusion(exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms, reversed_at_ms, expires_at_ms)
VALUES ('ex-1', 'scene', 's3', 'hard', 1, NULL, NULL)`)
	exec(`INSERT INTO feedback(feedback_id, scene_id, feedback_type, value, occurred_at_ms, payload_json)
VALUES ('fb-1', 's4', 'thumb_down', NULL, 1, '{}')`)
	return db
}

// scoreReviewIDs returns the scene_id of each item in the response.
func scoreReviewIDs(t *testing.T, out jVal) []string {
	t.Helper()
	items := out.get("items")
	var ids []string
	for _, item := range items.arr {
		ids = append(ids, item.get("scene_id").asString())
	}
	return ids
}

func TestScoreReviewOrdersByAppealAscendingWithEligibility(t *testing.T) {
	db := scoreReviewSeed(t)
	out, err := getScoreReviewCore(db, jvObj(), 1, 20, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	// s3 hard-excluded, s8 no file; s4's current thumb_down does NOT exclude
	// on the review surface (it is exactly what the review is for). The
	// eligible tail is s1 (-0.9), s2 (-0.6), s4 (-0.2), s5 (0.0) in
	// appeal-ascending order.
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s1,s2,s4,s5" {
		t.Fatalf("items = %v, want [s1 s2 s4 s5]", got)
	}
	if out.get("total").asString() != "4" {
		t.Fatalf("total = %s, want 4", out.get("total").asString())
	}
	if out.get("page_size").asString() != "20" || out.get("page").asString() != "1" {
		t.Fatalf("page_size/page = %s/%s", out.get("page_size").asString(), out.get("page").asString())
	}
	if out.get("has_more").b {
		t.Fatalf("has_more = %s, want false", out.get("has_more").asString())
	}
	if out.get("model_version").asString() != "model" {
		t.Fatalf("model_version = %s, want model", out.get("model_version").asString())
	}
	// The response carries exactly the contract keys.
	wantKeys := []string{"items", "total", "page_size", "has_more", "page", "model_version"}
	for _, key := range wantKeys {
		if !out.has(key) {
			t.Errorf("response missing key %s", key)
		}
	}
	if len(out.obj) != len(wantKeys) {
		t.Errorf("response has %d keys, want %d", len(out.obj), len(wantKeys))
	}
}

func TestScoreReviewThumbDownDoesNotExcludeButOtherReasonsDo(t *testing.T) {
	db := scoreReviewSeed(t)
	exec := func(query string, args ...any) {
		t.Helper()
		if _, err := db.Exec(query, args...); err != nil {
			t.Fatalf("seed %q: %v", query, err)
		}
	}
	// s8 has no available file; adding a thumb_down on top must not make it
	// eligible — the wrapper drops current_thumb_down only, never the other
	// exclusion reasons.
	exec(`INSERT INTO feedback(feedback_id, scene_id, feedback_type, value, occurred_at_ms, payload_json)
VALUES ('fb-2', 's8', 'thumb_down', NULL, 1, '{}')`)
	out, err := getScoreReviewCore(db, jvObj(), 1, 20, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	// s4 (thumb_down only) is shown; s8 (thumb_down + file_unavailable) and
	// s3 (hard exclusion) stay hidden.
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s1,s2,s4,s5" {
		t.Fatalf("items = %v, want [s1 s2 s4 s5]", got)
	}
	if out.get("total").asString() != "4" {
		t.Fatalf("total = %s, want 4", out.get("total").asString())
	}
}

func TestScoreReviewOrdersDescending(t *testing.T) {
	db := scoreReviewSeed(t)
	out, err := getScoreReviewCore(db, jvObj(), 1, 20, 0, "desc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	// Descending within the window (appeal <= 0): s5 (0.0), s4 (-0.2),
	// s2 (-0.6), s1 (-0.9). s3 hard-excluded, s8 no file.
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s5,s4,s2,s1" {
		t.Fatalf("items = %v, want [s5 s4 s2 s1]", got)
	}
	if out.get("total").asString() != "4" {
		t.Fatalf("total = %s, want 4", out.get("total").asString())
	}
	// Descending paging: page 1 count 2 = s5, s4 (positions 0, 1).
	out, err = getScoreReviewCore(db, jvObj(), 1, 2, 0, "desc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s5,s4" {
		t.Fatalf("desc page 1 items = %v, want [s5 s4]", got)
	}
	if got := out.get("items").arr[1].get("position").asString(); got != "1" {
		t.Fatalf("desc page 1 second position = %s, want 1", got)
	}
}

func TestScoreReviewItemsMirrorSlateShape(t *testing.T) {
	db := scoreReviewSeed(t)
	out, err := getScoreReviewCore(db, jvObj(), 1, 20, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	items := out.get("items")
	if len(items.arr) == 0 {
		t.Fatal("no items")
	}
	item := items.arr[0]
	// First item: s1 with appeal -0.9.
	if item.get("scene_id").asString() != "s1" {
		t.Fatalf("first scene = %s", item.get("scene_id").asString())
	}
	if item.get("lane").asString() != "score_review" {
		t.Errorf("lane = %s", item.get("lane").asString())
	}
	if item.get("source_lane").asString() != "score_review" {
		t.Errorf("source_lane = %s", item.get("source_lane").asString())
	}
	if item.get("position").asString() != "0" {
		t.Errorf("position = %s", item.get("position").asString())
	}
	if item.get("final_utility").asString() != "-0.9" {
		t.Errorf("final_utility = %s, want -0.9 (the appeal)", item.get("final_utility").asString())
	}
	if item.get("appeal").asString() != "-0.9" {
		t.Errorf("appeal = %s", item.get("appeal").asString())
	}
	if item.get("current_fit").asString() != "-0.45" {
		t.Errorf("current_fit = %s", item.get("current_fit").asString())
	}
	if item.get("confidence").asString() != "0.8" {
		t.Errorf("confidence = %s", item.get("confidence").asString())
	}
	if item.get("lane_value").asString() != "-0.9" {
		t.Errorf("lane_value = %s", item.get("lane_value").asString())
	}
	if item.get("subtype").kind != jNull {
		t.Errorf("subtype = %s, want null", item.get("subtype").marshalCompact())
	}
	if item.get("qualification").marshalCompact() != "{}" {
		t.Errorf("qualification = %s", item.get("qualification").marshalCompact())
	}
	if item.get("penalties").marshalCompact() != `{"performer":0.0,"studio":0.0,"content":0.0,"history":0.0,"live_cooldown":0.0}` {
		t.Errorf("penalties = %s", item.get("penalties").marshalCompact())
	}
	if item.get("bonuses").marshalCompact() != `{"uncovered_content":0.0}` {
		t.Errorf("bonuses = %s", item.get("bonuses").marshalCompact())
	}
	if item.get("components").get("baseline").get("value").asString() != "0.0" {
		t.Errorf("components = %s", item.get("components").marshalCompact())
	}
	if item.get("eligibility").marshalCompact() != `{"eligible":true}` {
		t.Errorf("eligibility = %s", item.get("eligibility").marshalCompact())
	}
	if item.get("reason_ids").marshalCompact() != `["eligibility.lane"]` {
		t.Errorf("reason_ids = %s", item.get("reason_ids").marshalCompact())
	}
	if item.get("impression_id").kind != jStr || item.get("impression_id").asString() == "" {
		t.Errorf("impression_id = %s", item.get("impression_id").marshalCompact())
	}
}

func TestScoreReviewMaxAppealCap(t *testing.T) {
	db := scoreReviewSeed(t)
	out, err := getScoreReviewCore(db, jvObj(), 1, 20, -0.4, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	// Only appeals <= -0.4: s1, s2 (s5 at 0.0 is above the cap).
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s1,s2" {
		t.Fatalf("items = %v, want [s1 s2]", got)
	}
	if out.get("total").asString() != "2" {
		t.Fatalf("total = %s, want 2", out.get("total").asString())
	}
	// A cap that admits s6 (0.1) but not s7 (0.3); s4 (thumb_down) is
	// eligible on the review surface.
	out, err = getScoreReviewCore(db, jvObj(), 1, 20, 0.1, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s1,s2,s4,s5,s6" {
		t.Fatalf("items = %v, want [s1 s2 s4 s5 s6]", got)
	}
	if out.get("total").asString() != "5" {
		t.Fatalf("total = %s, want 5", out.get("total").asString())
	}
	// A cap below every appeal yields an empty page.
	out, err = getScoreReviewCore(db, jvObj(), 1, 20, -1.0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if len(out.get("items").arr) != 0 || out.get("total").asString() != "0" {
		t.Fatalf("expected empty review, got items=%d total=%s",
			len(out.get("items").arr), out.get("total").asString())
	}
	if out.get("has_more").b {
		t.Fatalf("has_more = %s, want false", out.get("has_more").asString())
	}
}

func TestScoreReviewPagingMath(t *testing.T) {
	db := scoreReviewSeed(t)
	// page 1, count 2: s1, s2, has_more (4 > 2).
	out, err := getScoreReviewCore(db, jvObj(), 1, 2, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s1,s2" {
		t.Fatalf("page 1 items = %v", got)
	}
	if !out.get("has_more").b {
		t.Fatalf("page 1 has_more = %s, want true", out.get("has_more").asString())
	}
	if got := out.get("items").arr[1].get("position").asString(); got != "1" {
		t.Fatalf("page 1 second position = %s, want 1", got)
	}
	// page 2, count 2: s4, s5 (positions 2 and 3), has_more false (4 > 4 is
	// false).
	out, err = getScoreReviewCore(db, jvObj(), 2, 2, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if got := scoreReviewIDs(t, out); strings.Join(got, ",") != "s4,s5" {
		t.Fatalf("page 2 items = %v", got)
	}
	if got := out.get("items").arr[0].get("position").asString(); got != "2" {
		t.Fatalf("page 2 first position = %s, want 2", got)
	}
	if out.get("has_more").b {
		t.Fatalf("page 2 has_more = %s, want false", out.get("has_more").asString())
	}
	// page 3, count 2: past the end -> empty items.
	out, err = getScoreReviewCore(db, jvObj(), 3, 2, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	if len(out.get("items").arr) != 0 {
		t.Fatalf("page 3 items = %v, want empty", scoreReviewIDs(t, out))
	}
	if out.get("total").asString() != "4" {
		t.Fatalf("page 3 total = %s, want 4", out.get("total").asString())
	}
}

func TestScoreReviewRecordsImpression(t *testing.T) {
	db := scoreReviewSeed(t)
	out, err := getScoreReviewCore(db, jvObj(), 1, 2, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	impressionID := out.get("items").arr[0].get("impression_id").asString()
	if impressionID == "" {
		t.Fatal("empty impression_id")
	}
	var lane, modelID, configVersion string
	if err := db.QueryRow(`SELECT lane, model_id, config_version FROM impression WHERE impression_id=?`,
		impressionID).Scan(&lane, &modelID, &configVersion); err != nil {
		t.Fatalf("impression row: %v", err)
	}
	if lane != "score_review" || modelID != "model" || configVersion != "builtin" {
		t.Fatalf("impression row = %s/%s/%s", lane, modelID, configVersion)
	}
	rows, err := db.Query(`SELECT scene_id, position, policy_score, reason_snapshot_json
FROM impression_item WHERE impression_id=? ORDER BY position`, impressionID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	type itemRow struct {
		sceneID string
		pos     int64
		score   float64
		reasons string
	}
	var got []itemRow
	for rows.Next() {
		var r itemRow
		if err := rows.Scan(&r.sceneID, &r.pos, &r.score, &r.reasons); err != nil {
			t.Fatal(err)
		}
		got = append(got, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	want := []itemRow{
		{"s1", 0, -0.9, `["eligibility.lane"]`},
		{"s2", 1, -0.6, `["eligibility.lane"]`},
	}
	if len(got) != len(want) {
		t.Fatalf("impression_item rows = %+v, want %+v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("impression_item[%d] = %+v, want %+v", i, got[i], want[i])
		}
	}
	// A second request with the same page records a distinct impression
	// (uuid4 per request, INSERT OR IGNORE keyed by impression_id).
	second, err := getScoreReviewCore(db, jvObj(), 1, 2, 0, "asc")
	if err != nil {
		t.Fatalf("getScoreReviewCore: %v", err)
	}
	secondID := second.get("items").arr[0].get("impression_id").asString()
	if secondID == impressionID {
		t.Fatal("second request reused the impression_id")
	}
	var count int
	if err := db.QueryRow(`SELECT count(*) FROM impression WHERE lane='score_review'`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 2 {
		t.Fatalf("score_review impressions = %d, want 2", count)
	}
}

func TestScoreReviewValidationAndModelRequired(t *testing.T) {
	db := scoreReviewSeed(t)
	for _, tc := range []struct {
		page, count int64
	}{
		{0, 20}, {1, 0}, {1, 501},
	} {
		if _, err := getScoreReviewCore(db, jvObj(), tc.page, tc.count, 0, "asc"); err == nil ||
			err.Error() != "invalid score review page" {
			t.Fatalf("page=%d count=%d: err = %v, want invalid score review page", tc.page, tc.count, err)
		}
	}
	// No published model -> the slate path's exact error.
	db2, _ := openTempDB(t)
	if err := migrate(db2, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	if _, err := getScoreReviewCore(db2, jvObj(), 1, 20, 0, "asc"); err == nil ||
		err.Error() != "no published model; run build-model first" {
		t.Fatalf("err = %v, want no published model", err)
	}
}
