package main

import (
	"database/sql"
	"reflect"
	"sort"
	"testing"
)

func TestNewArrivalsWindowWidensAndFilters(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	const nowMs = int64(1768435200000) // 2026-01-15T00:00:00Z
	scenes := []struct {
		id        string
		createdAt jVal
		organized bool
	}{
		{"a", jvStr("2026-01-14T12:00:00Z"), true},
		{"b", jvStr("2026-01-10T00:00:00+00:00"), true},
		{"c", jvStr("2026-01-13T00:00:00Z"), false},
		{"d", jvStr("2026-01-12T00:00:00Z"), true},
		{"e", jvStr("2025-12-01T00:00:00Z"), true},
		{"f", jvStr("2025-11-01T00:00:00Z"), true},
		{"g", jvNull(), true},
	}
	eligible := map[string]bool{}
	for _, scene := range scenes {
		adapted := adaptSyncScene(jvObj(
			jvKey("id", jvStr(scene.id)),
			jvKey("created_at", scene.createdAt),
			jvKey("organized", jvBool(scene.organized)),
		))
		if err := withTxn(db, func(conn *sql.Conn) error { return syncUpsertScene(conn, adapted) }); err != nil {
			t.Fatal(err)
		}
		eligible[scene.id] = scene.id != "f"
	}
	played := map[string]bool{"d": true}
	ids := func(includeUnorganized bool, minScenes int) []string {
		got, err := newArrivalsContext(db, eligible, played, nowMs, includeUnorganized, 14, minScenes)
		if err != nil {
			t.Fatal(err)
		}
		keys := make([]string, 0, len(got))
		for id := range got {
			keys = append(keys, id)
		}
		sort.Strings(keys)
		return keys
	}
	for _, tc := range []struct {
		name               string
		includeUnorganized bool
		minScenes          int
		want               []string
	}{
		// a and b are inside the window; c is unorganized, d played, e too
		// old, f ineligible, g has no added date.
		{"window", false, 2, []string{"a", "b"}},
		{"widens to the most recent", false, 3, []string{"a", "b", "e"}},
		{"widening stops at the candidates", false, 50, []string{"a", "b", "e"}},
		{"unorganized included", true, 2, []string{"a", "b", "c"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := ids(tc.includeUnorganized, tc.minScenes); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got %v, want %v", got, tc.want)
			}
		})
	}
	got, err := newArrivalsContext(db, eligible, played, nowMs, false, 14, 2)
	if err != nil {
		t.Fatal(err)
	}
	if arrival := got["a"]; arrival.addedAtMs != 1768392000000 || arrival.daysSinceAdded != 0.5 {
		t.Fatalf("unexpected arrival for a: %+v", arrival)
	}
}
