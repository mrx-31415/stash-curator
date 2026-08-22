package main

import "testing"

// TestEffectiveTagRoleConfigVersion covers issue #238: a plugin update can
// leave the published model's tag_role rows under an older FeatureConfig
// fingerprint (the model predates the last config change and no rebuild has
// run). The effective version must fall back to the most complete legacy
// config_version so the taste profile and tag-role surfaces are not silently
// empty, and must prefer the current fingerprint once a rebuild writes rows
// for it.
func TestEffectiveTagRoleConfigVersion(t *testing.T) {
	db, _ := openTempDB(t)
	defer db.Close()
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	// No tag_role rows at all → no effective version (never built).
	got, err := effectiveTagRoleConfigVersion(db)
	if err != nil {
		t.Fatal(err)
	}
	if got != "" {
		t.Fatalf("empty tag_role: got %q, want empty", got)
	}
	// Only a legacy config_version → fall back to the most complete legacy.
	if _, err := db.Exec(`INSERT INTO source_tag(tag_id, name, source_hash)
		VALUES ('t1', 'test tag', 'hash')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO tag_role(tag_id, config_version, role, resolution_reason)
		VALUES ('t1', 'cfg-legacy-old', 'content', 'test')`); err != nil {
		t.Fatal(err)
	}
	got, err = effectiveTagRoleConfigVersion(db)
	if err != nil {
		t.Fatal(err)
	}
	if got != "cfg-legacy-old" {
		t.Fatalf("legacy only: got %q, want cfg-legacy-old", got)
	}
	// Current fingerprint present → the running binary wins.
	current := "cfg-" + featureFingerprint()[:20]
	if _, err := db.Exec(`INSERT INTO tag_role(tag_id, config_version, role, resolution_reason)
		VALUES ('t1', ?, 'content', 'test')`, current); err != nil {
		t.Fatal(err)
	}
	got, err = effectiveTagRoleConfigVersion(db)
	if err != nil {
		t.Fatal(err)
	}
	if got != current {
		t.Fatalf("current present: got %q, want %q", got, current)
	}
}
