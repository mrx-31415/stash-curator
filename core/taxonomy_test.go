package main

import "testing"

func TestEquivalentTagNamesKeepsUnmappedLocalTags(t *testing.T) {
	for _, unmapped := range []any{nil, ""} {
		db, _ := openTempDB(t)
		if err := migrate(db, 1); err != nil {
			t.Fatal(err)
		}
		_, err := db.Exec(`
INSERT INTO source_tag(tag_id,name,source_hash) VALUES ('parent','Parent','p'),('child','Child','c');
INSERT INTO tag_parent(tag_id,parent_tag_id) VALUES ('child','parent');
INSERT INTO taxonomy_snapshot VALUES ('snapshot','https://example.test/graphql',1,0,1);
INSERT INTO application_meta VALUES ('taxonomy_snapshot_id','snapshot');
INSERT INTO taxonomy_tag VALUES ('snapshot','external','External Child',NULL);
INSERT INTO taxonomy_tag_alias VALUES ('snapshot','external','Child Alias');
INSERT INTO tag_taxonomy_match(local_tag_id,snapshot_id,external_tag_id,match_method,confidence)
VALUES ('parent','snapshot',?,'unmapped',0),('child','snapshot','external','name',1);`, unmapped)
		if err != nil {
			t.Fatal(err)
		}
		groups, err := equivalentTagNames(db, []string{"Parent"})
		if err != nil {
			t.Fatalf("unmapped ID %v: %v", unmapped, err)
		}
		if len(groups) != 1 || len(groups[0]) != 4 {
			t.Fatalf("lost local names, descendants or aliases: %v", groups)
		}
		for _, name := range []string{"parent", "child", "external child", "child alias"} {
			if !groups[0][name] {
				t.Fatalf("missing %q: %v", name, groups)
			}
		}
	}
}
