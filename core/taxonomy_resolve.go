// StashDB taxonomy index — a port of curator/taxonomy/store.py's
// TaxonomyIndex.resolve: resolve a local tag id/name to an external StashDB
// tag id via stable stash_ids or a unique name/alias match in the active
// taxonomy snapshot. The category-role map mirrors
// curator/taxonomy/stashdb_category_roles.json (embedded to keep the binary
// static and dependency-free).
package main

import (
	"database/sql"
	"net/url"
	"sort"
	"strings"
)

// taxonomyMatch mirrors TaxonomyMatch on the fields externalTagIDs needs.
type taxonomyMatch struct {
	externalTagID      string
	externalCategoryID string
	confidence         float64
	method             string
	ambiguityCount     int
}

// isStashdbEndpoint mirrors taxonomy.store._is_stashdb.
func isStashdbEndpoint(endpoint string) bool {
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return false
	}
	return strings.EqualFold(parsed.Hostname(), "stashdb.org")
}

// taxonomyIndexResolve mirrors TaxonomyIndex.resolve for a single local tag.
func taxonomyIndexResolve(db dbx, localTagID, name string) (taxonomyMatch, error) {
	var snapshotID string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`).Scan(&snapshotID)
	if err == sql.ErrNoRows {
		return taxonomyMatch{method: "unmapped"}, nil
	}
	if err != nil {
		return taxonomyMatch{}, err
	}
	// external_ids from source_tag_stash_id filtered to stashdb.org.
	externalIDs := map[string]bool{}
	rows, err := db.Query(`SELECT endpoint, stash_id FROM source_tag_stash_id WHERE tag_id=?`, localTagID)
	if err != nil {
		return taxonomyMatch{}, err
	}
	for rows.Next() {
		var endpoint, stashID string
		if err := rows.Scan(&endpoint, &stashID); err != nil {
			return taxonomyMatch{}, err
		}
		if isStashdbEndpoint(endpoint) {
			externalIDs[stashID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return taxonomyMatch{}, err
	}
	// tags: {tag_id: (category_id, name)} from the active snapshot.
	tagIDs := map[string]string{} // tag_id -> category_id ("" when null)
	tagNames := map[string]string{}
	taxRows, err := db.Query(`SELECT tag_id, category_id, name FROM taxonomy_tag WHERE snapshot_id=?`, snapshotID)
	if err != nil {
		return taxonomyMatch{}, err
	}
	for taxRows.Next() {
		var tagID string
		var categoryID sql.NullString
		var tagName string
		if err := taxRows.Scan(&tagID, &categoryID, &tagName); err != nil {
			return taxonomyMatch{}, err
		}
		tagIDs[tagID] = categoryID.String
		tagNames[tagID] = tagName
	}
	taxRows.Close()
	if err := taxRows.Err(); err != nil {
		return taxonomyMatch{}, err
	}
	names := map[string]map[string]bool{}
	for tagID, tagName := range tagNames {
		normalized := normalizeTagName(tagName)
		if names[normalized] == nil {
			names[normalized] = map[string]bool{}
		}
		names[normalized][tagID] = true
	}
	aliasRows, err := db.Query(`SELECT tag_id, alias FROM taxonomy_tag_alias WHERE snapshot_id=?`, snapshotID)
	if err != nil {
		return taxonomyMatch{}, err
	}
	for aliasRows.Next() {
		var tagID, alias string
		if err := aliasRows.Scan(&tagID, &alias); err != nil {
			return taxonomyMatch{}, err
		}
		normalized := normalizeTagName(alias)
		if names[normalized] == nil {
			names[normalized] = map[string]bool{}
		}
		names[normalized][tagID] = true
	}
	aliasRows.Close()
	if err := aliasRows.Err(); err != nil {
		return taxonomyMatch{}, err
	}

	known := make([]string, 0)
	for id := range externalIDs {
		if _, ok := tagIDs[id]; ok {
			known = append(known, id)
		}
	}
	sort.Strings(known)
	if len(known) == 1 {
		return taxonomyMatchFor(tagIDs, known[0], "stable_id", 1.0), nil
	}
	if len(known) > 1 {
		return taxonomyMatch{method: "ambiguous_stable_id", ambiguityCount: len(known)}, nil
	}
	candidates := make([]string, 0)
	for id := range names[normalizeTagName(name)] {
		candidates = append(candidates, id)
	}
	sort.Strings(candidates)
	if len(candidates) == 1 {
		return taxonomyMatchFor(tagIDs, candidates[0], "unique_name_or_alias", 0.9), nil
	}
	if len(candidates) > 1 {
		return taxonomyMatch{method: "ambiguous_name", ambiguityCount: len(candidates)}, nil
	}
	return taxonomyMatch{method: "unmapped"}, nil
}

// taxonomyMatchFor mirrors TaxonomyIndex._match.
func taxonomyMatchFor(tagIDs map[string]string, tagID, method string, confidence float64) taxonomyMatch {
	categoryID := tagIDs[tagID]
	return taxonomyMatch{
		externalTagID:      tagID,
		externalCategoryID: categoryID,
		confidence:         confidence,
		method:             method,
	}
}
