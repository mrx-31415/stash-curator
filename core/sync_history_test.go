package main

import (
	"database/sql"
	"reflect"
	"testing"
)

func TestHistoryTimestampBounds(t *testing.T) {
	for _, tc := range []struct {
		value string
		want  int64
		valid bool
	}{
		{"0001-01-01T00:00:00Z", 0, false},
		{"1969-12-31T23:59:59Z", 0, false},
		{"1970-01-01T00:00:00+01:00", 0, false},
		{"1970-01-01T00:00:00Z", 0, true},
		{"1969-12-31T23:00:00-01:00", 0, true},
		{"2026-01-01T00:00:00Z", 1767225600000, true},
		{"invalid", 0, false},
	} {
		t.Run(tc.value, func(t *testing.T) {
			got, valid := epochMsOf(jvStr(tc.value))
			if got != tc.want || valid != tc.valid {
				t.Fatalf("got (%d, %v), want (%d, %v)", got, valid, tc.want, tc.valid)
			}
		})
	}
}

func TestSyncSkipsNegativeHistoryTimestamps(t *testing.T) {
	for _, mixed := range []bool{false, true} {
		db, _ := openTempDB(t)
		if err := migrate(db, 1); err != nil {
			t.Fatal(err)
		}
		history := jvArr(jvStr("0001-01-01T00:00:00Z"), jvStr("1969-12-31T23:59:59Z"))
		var expected []int64
		if mixed {
			history.arr = append(history.arr, jvStr("1970-01-01T00:00:00Z"), jvStr("2026-01-01T00:00:00Z"))
			expected = []int64{0, 1767225600000}
		}
		scene := adaptSyncScene(jvObj(
			jvKey("id", jvStr("synthetic")),
			jvKey("date", jvStr("1950-01-01")),
			jvKey("play_count", jvInt(10)),
			jvKey("play_duration", jvInt(123)),
			jvKey("play_history", history), jvKey("o_history", history),
		))
		if err := withTxn(db, func(conn *sql.Conn) error { return syncUpsertScene(conn, scene) }); err != nil {
			t.Fatal(err)
		}
		for _, query := range []string{
			"SELECT played_at_ms FROM source_play ORDER BY ordinal",
			"SELECT occurred_at_ms FROM source_o ORDER BY ordinal",
		} {
			rows, err := db.Query(query)
			if err != nil {
				t.Fatal(err)
			}
			var got []int64
			for rows.Next() {
				var timestamp int64
				if err := rows.Scan(&timestamp); err != nil {
					t.Fatal(err)
				}
				got = append(got, timestamp)
			}
			err = rows.Err()
			rows.Close()
			if err != nil || !reflect.DeepEqual(got, expected) {
				t.Fatalf("%s: got %v, want %v; error %v", query, got, expected, err)
			}
		}
		var count int
		var duration float64
		var date string
		if err := db.QueryRow("SELECT play_count, play_duration_seconds, scene_date FROM source_scene").Scan(&count, &duration, &date); err != nil {
			t.Fatal(err)
		}
		if count != 10 || duration != 123 || date != "1950-01-01" {
			t.Fatalf("changed source metadata: %d, %v, %s", count, duration, date)
		}
	}
}
