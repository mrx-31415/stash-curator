package main

import (
	"context"
	"database/sql"
	"fmt"
	"testing"

	sqlite "github.com/mattn/go-sqlite3"
)

// Candidate loading reads every lane-classified scene; a library larger than
// SQLite's bound-variable limit must still load performers, studios and
// content vectors for all of them.
func TestBuildCandidatesLargeLibrary(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	const sceneCount = 1201
	classifications := make([]*greedyCandidate, sceneCount)
	if err := withTxn(db, func(conn *sql.Conn) error {
		for _, query := range []string{
			`INSERT INTO model_version(model_id, status, feature_version, config_json, created_at_ms)
VALUES ('model', 'building', 'features', '{}', 0)`,
			`INSERT INTO feature_definition(feature_id, feature_version, family, name, provenance)
VALUES ('content:tag', 'features', 'content', 'tag', 'fixture')`,
			`INSERT INTO source_studio(studio_id, source_hash) VALUES ('parent', 'fixture')`,
			`INSERT INTO source_studio(studio_id, parent_studio_id, source_hash) VALUES ('studio', 'parent', 'fixture')`,
			`INSERT INTO source_performer(performer_id, source_hash) VALUES ('performer', 'fixture')`,
		} {
			if _, err := conn.ExecContext(context.Background(), query); err != nil {
				return err
			}
		}
		for i := range classifications {
			sceneID := fmt.Sprintf("scene-%04d", i)
			classifications[i] = &greedyCandidate{sceneID: sceneID, content: map[string]float64{}}
			for _, query := range []string{
				`INSERT INTO source_scene(scene_id, studio_id, source_hash) VALUES (?, 'studio', 'fixture')`,
				`INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, 'performer', 0)`,
				`INSERT INTO entity_feature(feature_version, entity_type, entity_id, feature_id, value, confidence)
VALUES ('features', 'scene', ?, 'content:tag', 1, 1)`,
			} {
				if _, err := conn.ExecContext(context.Background(), query, sceneID); err != nil {
					return err
				}
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	limitVariables(t, db, 999)

	candidates, err := buildCandidates(db, "model", classifications)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range candidates {
		if len(c.performers) != 1 || c.studioGroup != "parent" || c.content["tag"] != 1 {
			t.Fatalf("candidate %s = performers %v, studio %q, content %v", c.sceneID, c.performers, c.studioGroup, c.content)
		}
	}
}

// limitVariables lowers the bound-parameter limit on the single pooled
// connection so tests exceed it with small fixtures.
func limitVariables(t *testing.T, db dbx, limit int) {
	t.Helper()
	conn, err := db.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if err := conn.Raw(func(driver any) error {
		driver.(*sqlite.SQLiteConn).SetLimit(sqlite.SQLITE_LIMIT_VARIABLE_NUMBER, limit)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}
