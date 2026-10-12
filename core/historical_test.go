package main

import (
	"context"
	"database/sql"
	"fmt"
	"testing"

	sqlite "github.com/mattn/go-sqlite3"
)

func TestHistoricalRebuildLargeSelection(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	const selectedCount = 1201
	ids := make([]string, selectedCount)
	for i := range ids {
		ids[i] = fmt.Sprintf("scene-%04d", i)
	}
	ids[0] += "\"\\é"
	if err := withTxn(db, func(conn *sql.Conn) error {
		for _, id := range append(append([]string{}, ids...), "unselected") {
			for index, query := range []string{
				`INSERT INTO source_scene(scene_id, play_duration_seconds, source_hash) VALUES (?, 180, 'fixture')`,
				`INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, 1700000000000, 0)`,
				`INSERT INTO source_o(scene_id, occurred_at_ms, ordinal) VALUES (?, 1700000000000, 0), (?, 1700086400000, 1)`,
			} {
				args := []any{id}
				if index == 2 {
					args = append(args, id)
				}
				if _, err := conn.ExecContext(context.Background(), query, args...); err != nil {
					return err
				}
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	conn, err := db.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	err = conn.Raw(func(driver any) error {
		driver.(*sqlite.SQLiteConn).SetLimit(sqlite.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
		return nil
	})
	conn.Close()
	if err != nil {
		t.Fatal(err)
	}
	assertResult := func(result historicalBuildResult, count int) {
		t.Helper()
		if result.sceneCount != int64(count) || result.sessionCount != int64(count) || result.outcomeCount != int64(count*2) {
			t.Fatalf("rebuild result = %+v, want %d scenes/sessions and %d outcomes", result, count, count*2)
		}
	}
	result, err := historicalRebuild(db, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	assertResult(result, selectedCount+1)
	result, err = historicalRebuild(db, []string{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	assertResult(result, 0)
	if _, err := db.Exec(`UPDATE source_scene SET play_duration_seconds=240`); err != nil {
		t.Fatal(err)
	}
	selection := append(append([]string{}, ids...), ids[0], "missing-scene")
	for range 2 {
		lastProcessed, lastTotal := 0, 0
		result, err = historicalRebuild(db, selection, func(processed, total int) {
			if processed < lastProcessed || processed > total {
				t.Fatalf("invalid progress: %d/%d after %d", processed, total, lastProcessed)
			}
			lastProcessed, lastTotal = processed, total
		})
		if err != nil {
			t.Fatalf("large selected rebuild: %v", err)
		}
		assertResult(result, selectedCount)
		if lastProcessed != selectedCount*2 || lastTotal != selectedCount*2 {
			t.Fatalf("final progress = %d/%d", lastProcessed, lastTotal)
		}
	}
	for _, check := range []struct {
		query string
		want  int
	}{
		{`SELECT count(*) FROM play_session`, selectedCount + 1},
		{`SELECT count(*) FROM behavior_event`, (selectedCount + 1) * 2},
		{`SELECT count(*) FROM play_session WHERE scene_id != 'unselected' AND active_seconds=240`, selectedCount},
		{`SELECT count(*) FROM play_session WHERE scene_id='unselected' AND active_seconds=180`, 1},
	} {
		var count int
		if err := db.QueryRow(check.query).Scan(&count); err != nil {
			t.Fatal(err)
		}
		if count != check.want {
			t.Fatalf("%s = %d, want %d", check.query, count, check.want)
		}
	}
	if _, err := db.Exec(`CREATE TRIGGER fail_historical_outcome BEFORE INSERT ON behavior_event
WHEN NEW.scene_id='scene-1200' BEGIN SELECT RAISE(ABORT, 'test failure'); END;
UPDATE source_scene SET play_duration_seconds=300`); err != nil {
		t.Fatal(err)
	}
	if _, err := historicalRebuild(db, selection, nil); err == nil {
		t.Fatal("expected reconstruction write to fail")
	}
	var preserved int
	if err := db.QueryRow(`SELECT count(*) FROM play_session WHERE active_seconds=240`).Scan(&preserved); err != nil {
		t.Fatal(err)
	}
	if preserved != selectedCount {
		t.Fatalf("failed rebuild preserved %d sessions, want %d", preserved, selectedCount)
	}
}
