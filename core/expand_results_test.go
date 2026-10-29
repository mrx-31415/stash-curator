package main

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

type expandChangeBeforePage struct {
	dbx
	change func() error
}

func (db *expandChangeBeforePage) Query(query string, args ...any) (*sql.Rows, error) {
	if strings.HasPrefix(query, "SELECT e.external_id") && db.change != nil {
		change := db.change
		db.change = nil
		if err := change(); err != nil {
			return nil, err
		}
	}
	return db.dbx.Query(query, args...)
}

func expandResultsFixture(t testing.TB, count int) dbx {
	t.Helper()
	db, err := openDatabase(filepath.Join(t.TempDir(), "curator.sqlite3"), false, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	if err := migrate(db, 1700000000000); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO expand_cache VALUES (1, 'model', 1000, 2000, ?, 0)`, count); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < count; i++ {
		payload := jvObj(
			jvKey("id", jvStr(fmt.Sprintf("ext-%04d", i))),
			jvKey("title", jvStr(fmt.Sprintf("Scene %d", i))),
			jvKey("details", jvStr(strings.Repeat("description ", 100))),
			jvKey("release_date", jvStr(fmt.Sprintf("2026-01-%02d", i%28+1))),
			jvKey("tags", jvArr()),
			jvKey("performers", jvArr(jvObj(jvKey("performer", jvObj(
				jvKey("id", jvStr(fmt.Sprintf("p%d", i%5))),
				jvKey("gender", jvStr("FEMALE")),
			))))),
		)
		if _, err := db.Exec(`INSERT INTO external_entity(entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool)
VALUES ('scene', ?, ?, ?, '[]', 1000, 'candidate')`, payload.get("id").asString(), payload.marshalCompact(), float64(count-i)/float64(count)); err != nil {
			t.Fatal(err)
		}
	}
	return db
}

func BenchmarkExpandResults(b *testing.B) {
	db := expandResultsFixture(b, 3423)
	serve := func() {
		if _, err := expandResults(db, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, true, -1, 20, jvNull()); err != nil {
			b.Fatal(err)
		}
	}
	serve()
	b.ResetTimer()
	b.ReportAllocs()
	for b.Loop() {
		serve()
	}
}

func TestExpandOrderingCache(t *testing.T) {
	db := expandResultsFixture(t, 12)
	serve := func(page int64, sortBy string, tags []string, links jVal) jVal {
		t.Helper()
		result, err := expandResults(db, "scene", page, sortBy, jvNull(), false, "", tags, nil, nil, nil, "", "", true, true, -1, 5, links)
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	for _, sortBy := range []string{"match", "newest"} {
		for _, page := range []int64{1, 2, 3, 4} {
			if _, err := db.Exec(`DELETE FROM application_meta WHERE key='expand_order:v2:scene'`); err != nil {
				t.Fatal(err)
			}
			cold := serve(page, sortBy, nil, jvNull())
			warm := serve(page, sortBy, nil, jvNull())
			if cold.marshalCompact() != warm.marshalCompact() {
				t.Fatalf("cached page %d (%s) changed results", page, sortBy)
			}
		}
	}
	serve(1, "match", nil, jvNull())
	// A candidate can change without its fetched timestamp changing.
	if _, err := db.Exec(`UPDATE external_entity SET score=2 WHERE external_id='ext-0011'`); err != nil {
		t.Fatal(err)
	}
	if got := serve(1, "match", nil, jvNull()).get("items").arr[0].get("id").asString(); got != "ext-0011" {
		t.Fatalf("score update reused stale ordering: %s", got)
	}
	if got := serve(1, "match", []string{"absent"}, jvNull()).get("total").asString(); got != "0" {
		t.Fatalf("filter reused stale ordering: total %s", got)
	}
	links := linksFixture(map[string]string{"ext-0011": "local"}, map[string]string{})
	if got := serve(1, "match", nil, links).get("total").asString(); got != "11" {
		t.Fatalf("new library match was not excluded: total %s", got)
	}
	serve(1, "match", nil, links)
	if _, err := db.Exec(`INSERT INTO external_shortlist(entity_type, external_id, score, sources_json, payload_json, added_at_ms)
VALUES ('scene', 'ext-0000', 1, '[]', '{}', 1000)`); err != nil {
		t.Fatal(err)
	}
	if !serve(1, "match", nil, links).get("items").arr[0].get("shortlisted").truthy() {
		t.Fatal("cached ordering did not reflect shortlist change")
	}
	if _, err := db.Exec(`INSERT INTO direct_term_preference_history(preference_id,term,value,blocked,occurred_at_ms)
VALUES ('block','description',-1,1,1000)`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO direct_term_preference(term,preference_id,value,blocked,occurred_at_ms)
VALUES ('description','block',-1,1,1000)`); err != nil {
		t.Fatal(err)
	}
	if got := serve(1, "match", nil, links).get("total").asString(); got != "11" {
		t.Fatalf("legacy term answer filtered candidates: total %s", got)
	}
	if got := serve(1, "newest", nil, links).get("total").asString(); got != "11" {
		t.Fatalf("legacy term answer filtered a new ordering: total %s", got)
	}
}

func TestExpandCandidateRevisions(t *testing.T) {
	db := expandResultsFixture(t, 2)
	revision := func(entityType string) int64 {
		t.Helper()
		var value int64
		if err := db.QueryRow(`SELECT revision FROM expand_candidate_revision WHERE entity_type=?`, entityType).Scan(&value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	steps := []struct {
		query            string
		scene, performer int64
	}{
		{`UPDATE external_entity SET fetched_at_ms=2000`, 2, 0},
		{`UPDATE external_entity SET score=score, payload_json=payload_json`, 2, 0},
		{`UPDATE external_entity SET payload_json='{}' WHERE external_id='ext-0000'`, 3, 0},
		{`UPDATE external_entity SET pool='explore' WHERE external_id='ext-0000'`, 4, 0},
		{`UPDATE external_entity SET score=0.5 WHERE external_id='ext-0000'`, 4, 0},
		{`UPDATE external_entity SET pool='candidate' WHERE external_id='ext-0000'`, 5, 0},
		{`UPDATE external_entity SET entity_type='performer' WHERE external_id='ext-0000'`, 6, 1},
		{`DELETE FROM external_entity WHERE external_id='ext-0000'`, 6, 2},
		{`INSERT INTO external_entity(entity_type,external_id,payload_json,score,sources_json,fetched_at_ms,pool) VALUES ('performer','new','{}',1,'[]',1000,'candidate')`, 6, 3},
	}
	for _, step := range steps {
		if _, err := db.Exec(step.query); err != nil {
			t.Fatal(err)
		}
		if scene, performer := revision("scene"), revision("performer"); scene != step.scene || performer != step.performer {
			t.Fatalf("%s: revisions (%d,%d), want (%d,%d)", step.query, scene, performer, step.scene, step.performer)
		}
	}
}

func TestExpandOrderingAfterPoolChange(t *testing.T) {
	db := expandResultsFixture(t, 4)
	serve := func() jVal {
		t.Helper()
		result, err := expandResults(db, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, true, -1, 20, jvNull())
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	serve()
	if _, err := db.Exec(`UPDATE external_entity SET pool='explore' WHERE external_id='ext-0000'`); err != nil {
		t.Fatal(err)
	}
	if result := serve(); len(result.get("items").arr) != 3 || result.get("items").arr[0].get("id").asString() != "ext-0001" {
		t.Fatal("pool change reused cached ordering")
	}
	if _, err := db.Exec(`DELETE FROM external_entity WHERE external_id='ext-0001'`); err != nil {
		t.Fatal(err)
	}
	if len(serve().get("items").arr) != 2 {
		t.Fatal("deleted candidate remained cached")
	}
}

func TestExpandOrderingChangedDuringCacheHit(t *testing.T) {
	db := expandResultsFixture(t, 4)
	serve := func(connection dbx) jVal {
		t.Helper()
		result, err := expandResults(connection, "scene", 1, "match", jvNull(), false, "", nil, nil, nil, nil, "", "", true, true, -1, 2, jvNull())
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	serve(db)
	changing := &expandChangeBeforePage{dbx: db, change: func() error {
		_, err := db.Exec(`UPDATE external_entity SET score=2 WHERE external_id='ext-0003'`)
		return err
	}}
	for _, connection := range []dbx{changing, db} {
		if serve(connection).get("items").arr[0].get("id").asString() != "ext-0003" {
			t.Fatal("concurrent candidate change served stale ordering")
		}
	}
}
