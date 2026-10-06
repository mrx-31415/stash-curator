package main

import "testing"

func TestNamedMoodMigrationAndSelection(t *testing.T) {
	db, _ := openTempDB(t)
	defer db.Close()
	if _, err := queryMigrationStatus(db); err != nil {
		t.Fatal(err)
	}
	migrations, err := loadMigrations()
	if err != nil {
		t.Fatal(err)
	}
	for _, migration := range migrations {
		if migration.version < 38 {
			if err := migrateOne(db, migration, 1); err != nil {
				t.Fatal(err)
			}
		}
	}
	legacy := `{"page_size":12,"together_excluded_tags":[{"id":"parent","name":"Parent"}]}`
	if _, err := db.Exec(`UPDATE curator_config SET config_json=?`, legacy); err != nil {
		t.Fatal(err)
	}
	if err := migrate(db, 2); err != nil {
		t.Fatal(err)
	}
	config, err := sidecarConfig(db)
	if err != nil {
		t.Fatal(err)
	}
	cfg := config.get("config")
	tags, id := selectedMood(cfg, "together")
	if id != "together" || len(tags.arr) != 1 || tags.arr[0].get("id").s != "parent" || pythonInt(cfg.get("page_size")) != 12 {
		t.Fatalf("migration lost settings: %s", config.marshalCompact())
	}
	_, id = selectedMood(cfg, "deleted")
	if id != "" {
		t.Fatal("deleted mood stayed active")
	}
	if err := validateConfig(jvObj(jvKey("moods", jvArr()))); err != nil {
		t.Fatal(err)
	}
	mood := cfg.get("moods").arr[0]
	if err := validateConfig(jvObj(jvKey("moods", jvArr(mood, mood)))); err == nil {
		t.Fatal("duplicate mood accepted")
	}
}

func TestTogetherDescendants(t *testing.T) {
	db, _ := openTempDB(t)
	defer db.Close()
	if err := migrate(db, 1); err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{
		`INSERT INTO source_tag(tag_id,name,source_hash) VALUES ('parent','Parent','h'),('child','Child','h'),('grandchild','Grandchild','h'),('other','Other','h')`,
		`INSERT INTO tag_parent VALUES ('child','parent'),('grandchild','child'),('parent','grandchild')`,
		`INSERT INTO source_scene(scene_id,source_hash) VALUES ('direct','h'),('nested','h'),('allowed','h')`,
		`INSERT INTO scene_tag(scene_id,tag_id) VALUES ('direct','parent'),('nested','grandchild'),('allowed','other')`,
	} {
		if _, err := db.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	tags := jvArr(jvObj(jvKey("id", jvStr("parent")), jvKey("name", jvStr("Parent"))))
	blocked, err := togetherBlockedScenes(db, tags)
	if err != nil {
		t.Fatal(err)
	}
	if len(blocked) != 2 || !blocked["direct"] || !blocked["nested"] || blocked["allowed"] {
		t.Fatalf("blocked: %v", blocked)
	}
	empty, err := togetherBlockedScenes(db, jvArr())
	if err != nil || len(empty) != 0 {
		t.Fatalf("empty: %v, %v", empty, err)
	}
	if err := validateConfig(jvObj(jvKey("together_excluded_tags", tags))); err != nil {
		t.Fatal(err)
	}
	if err := validateConfig(jvObj(jvKey("together_excluded_tags", jvArr(jvStr("parent"))))); err == nil {
		t.Fatal("invalid tag accepted")
	}
}
