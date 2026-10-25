package main

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
)

// A schema-5 artifact's packed performer_profile rows must load exactly the
// profiles the entity_feature join yields for older artifacts.
func TestPackedPerformerProfilesMatchEntityFeatures(t *testing.T) {
	db, err := sql.Open("sqlite3", fileURI(filepath.Join(t.TempDir(), "feature.sqlite3"), false))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	for _, statement := range splitSchemaStatements(artifactFeatureSchema) {
		if _, err := db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	const version = "fv-test"
	features := []featureRow{
		{entityType: "performer", entityID: "10", family: "profile:age", name: "age_years", value: 27.25, confidence: 0.8},
		{entityType: "performer", entityID: "10", family: "profile:content", name: "tag:1", value: 0.1, confidence: 1},
		{entityType: "performer", entityID: "10", family: "profile:content", name: "tag:2", value: 1.0 / 3, confidence: 1},
		{entityType: "performer", entityID: "10", family: "profile:hair", name: "hair:Ünïcode \"q\"", value: 1, confidence: 0.65},
		{entityType: "performer", entityID: "10", family: "affinity", name: "not-a-profile", value: 2, confidence: 1},
		{entityType: "performer", entityID: "2", family: "profile:height", name: "height_cm", value: 170, confidence: 1},
		{entityType: "performer", entityID: "2", family: "profile:measurements", name: "cup_index", value: 5e-07, confidence: 0.85},
		{entityType: "performer", entityID: "3", family: "profile:content", name: "tag:1", value: -0.5, confidence: 0.2},
		{entityType: "scene", entityID: "10", family: "content", name: "tag:1", value: 1, confidence: 1},
	}
	sort.SliceStable(features, func(i, j int) bool {
		a, b := features[i], features[j]
		if a.entityType != b.entityType {
			return a.entityType < b.entityType
		}
		if a.entityID != b.entityID {
			return a.entityID < b.entityID
		}
		if a.family != b.family {
			return a.family < b.family
		}
		return a.name < b.name
	})
	conn, err := db.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defined := map[string]bool{}
	for _, feature := range features {
		id := featureID(version, feature.entityType, feature.family, feature.name)
		if !defined[id] {
			defined[id] = true
			if _, err := conn.ExecContext(context.Background(), `INSERT INTO feature_definition(
feature_id, feature_version, family, name, provenance) VALUES (?, ?, ?, ?, 'test')`,
				id, version, feature.family, feature.name); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO entity_feature VALUES (?, ?, ?, ?, ?, ?)`,
			version, feature.entityType, feature.entityID, id, feature.value, feature.confidence); err != nil {
			t.Fatal(err)
		}
	}
	for _, profile := range performerProfileJSON(features) {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO performer_profile VALUES (?, ?, ?)`,
			version, profile[0], profile[1]); err != nil {
			t.Fatal(err)
		}
	}
	conn.Close()

	load := func() (map[string]*performerProfile, map[string]*performerProfile, map[string]*performerProfile) {
		t.Helper()
		all, err := loadPerformerProfiles(db, version, nil)
		if err != nil {
			t.Fatal(err)
		}
		some, err := performerProfilesForIDs(db, version, map[string]bool{"2": true, "3": true, "missing": true})
		if err != nil {
			t.Fatal(err)
		}
		build, err := readProfiles(db, version, numericBlocks)
		if err != nil {
			t.Fatal(err)
		}
		return all, some, build
	}
	if packed, err := hasPerformerProfiles(db, version); err != nil || !packed {
		t.Fatalf("performer_profile not detected: %v", err)
	}
	if packed, err := hasPerformerProfiles(db, "fv-other"); err != nil || packed {
		t.Fatalf("performer_profile used for a version it has no rows for: %v", err)
	}
	packedAll, packedSome, packedBuild := load()
	if _, err := db.Exec(`DROP TABLE performer_profile`); err != nil {
		t.Fatal(err)
	}
	if packed, err := hasPerformerProfiles(db, version); err != nil || packed {
		t.Fatalf("dropped performer_profile still detected: %v", err)
	}
	joinedAll, joinedSome, joinedBuild := load()

	if len(packedAll) != 3 || len(packedSome) != 2 || packedAll["10"].blocks["affinity"] != nil {
		t.Fatalf("unexpected profiles: all=%d some=%d", len(packedAll), len(packedSome))
	}
	if got := packedAll["10"].blocks["hair"]["hair:Ünïcode \"q\""]; got.value != 1 || got.confidence != 0.65 {
		t.Fatalf("unicode feature name did not round-trip: %+v", got)
	}
	for label, pair := range map[string][2]map[string]*performerProfile{
		"all": {packedAll, joinedAll}, "ids": {packedSome, joinedSome}, "build": {packedBuild, joinedBuild},
	} {
		if !reflect.DeepEqual(pair[0], pair[1]) {
			t.Errorf("%s: packed profiles differ from entity_feature profiles:\n%s\n%s",
				label, fmt.Sprint(pair[0]), fmt.Sprint(pair[1]))
		}
	}
}
