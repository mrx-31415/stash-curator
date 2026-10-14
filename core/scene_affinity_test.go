package main

import (
	"database/sql"
	"fmt"
	"strings"
	"testing"
)

type sceneAffinityQueryRecorder struct {
	dbx
	query string
	args  []any
}

func (db *sceneAffinityQueryRecorder) Query(query string, args ...any) (*sql.Rows, error) {
	db.query, db.args = query, args
	return db.dbx.Query(query, args...)
}

func TestSceneAffinityIndexedLookup(t *testing.T) {
	db, _ := openTempDB(t)
	defer db.Close()
	for _, query := range []string{
		`CREATE TABLE model_scene_score(model_id TEXT,scene_id TEXT,appeal REAL,confidence REAL,PRIMARY KEY(model_id,scene_id)) WITHOUT ROWID`,
		`CREATE INDEX model_scene_score_prune_idx ON model_scene_score(model_id,appeal,confidence,scene_id)`,
	} {
		if _, err := db.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	ids := jvArr()
	for i := 0; i < 4000; i++ {
		id := fmt.Sprint(i)
		ids.arr = append(ids.arr, jvStr(id))
		if _, err := db.Exec(`INSERT INTO model_scene_score VALUES('m',?,0.2,0.8)`, id); err != nil {
			t.Fatal(err)
		}
	}
	recorder := &sceneAffinityQueryRecorder{dbx: db}
	rows, err := sceneAffinityRows(recorder, "m", ids, jvObj(jvKey("sort", jvBool(true)), jvKey("criterion", jvObj(jvKey("modifier", jvStr("GREATER_THAN")), jvKey("value", jvFloat(.15))))))
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 4000 || rows[0].id != "0" || rows[3999].id != "3999" {
		t.Fatal("Equal scores must preserve native order")
	}
	if strings.Contains(recorder.query, "json_each") || len(recorder.args) != 1 {
		t.Fatal("Sorting must scan narrow scores once, not join the ID list")
	}
	_, err = sceneAffinityRows(recorder, "m", jvArr(jvStr("0"), jvStr("missing")), jvObj())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(recorder.query, "json_each") {
		t.Fatal("Badges must only look up requested IDs")
	}
}
