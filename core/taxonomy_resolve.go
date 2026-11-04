// StashDB taxonomy index — a port of curator/taxonomy/store.py's
// TaxonomyIndex.resolve: resolve a local tag id/name to an external StashDB
// tag id via stable stash_ids or a unique name/alias match in the active
// taxonomy snapshot. The category-role map mirrors
// curator/taxonomy/stashdb_category_roles.json (embedded to keep the binary
// static and dependency-free).
package main

import (
	"database/sql"
	_ "embed"
	"net/url"
	"sort"
	"strings"
)

//go:embed stashdb_performer_tags.json
var performerTagsJSON []byte

// performerTags is the parsed stashdb_performer_tags.json resource
// (taxonomy.store's PEOPLE_CATEGORY_GROUP, PEOPLE_EXCLUDED_CATEGORY_IDS and
// NATIONALITY_TAG_IDS). It only labels tags for display and never feeds tag
// roles, features or categoryRoleFingerprint.
var performerTags = struct {
	peopleGroup        string
	excludedCategories map[string]bool
	nationalityTags    map[string]bool
}{}

func init() {
	parsed, err := parseJSON(performerTagsJSON)
	if err != nil {
		panic("core: invalid embedded stashdb_performer_tags.json: " + err.Error())
	}
	performerTags.peopleGroup = parsed.get("people_group").asString()
	performerTags.excludedCategories = map[string]bool{}
	for _, item := range parsed.get("excluded_categories").arr {
		performerTags.excludedCategories[item.get("id").asString()] = true
	}
	performerTags.nationalityTags = map[string]bool{}
	for _, item := range parsed.get("nationality_tags").arr {
		performerTags.nationalityTags[item.get("id").asString()] = true
	}
}

// taxonomyMatch mirrors TaxonomyMatch.
type taxonomyMatch struct {
	snapshotID         string
	role               string
	externalTagID      string
	externalCategoryID string
	confidence         float64
	method             string
	ambiguityCount     int
}

// isStashdbEndpoint mirrors taxonomy.store._is_stashdb.
func isStashdbEndpoint(endpoint string) bool {
	if strings.EqualFold(strings.TrimRight(endpoint, "/"), strings.TrimRight(stashdbEndpoint, "/")) {
		return true
	}
	if !strings.EqualFold(stashdbEndpoint, "https://stashdb.org/graphql") {
		return false
	}
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return false
	}
	return strings.EqualFold(parsed.Hostname(), "stashdb.org")
}

// taxonomyIndex mirrors TaxonomyIndex: the active snapshot's tag ids,
// categories, and normalized names/aliases loaded once, so resolve() runs
// against memory instead of re-scanning the taxonomy tables per tag.
type taxonomyIndex struct {
	snapshotID string
	tags       map[string]string          // tag_id -> category_id ("" when null)
	names      map[string]map[string]bool // normalized name/alias -> tag ids
}

// newTaxonomyIndex mirrors TaxonomyIndex.__init__.
func newTaxonomyIndex(db dbx) (*taxonomyIndex, error) {
	var snapshotID string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`).Scan(&snapshotID)
	if err == sql.ErrNoRows {
		return &taxonomyIndex{}, nil
	}
	if err != nil {
		return nil, err
	}
	index := &taxonomyIndex{
		snapshotID: snapshotID,
		tags:       map[string]string{},
		names:      map[string]map[string]bool{},
	}
	taxRows, err := db.Query(`SELECT tag_id, category_id, name FROM taxonomy_tag WHERE snapshot_id=?`, snapshotID)
	if err != nil {
		return nil, err
	}
	for taxRows.Next() {
		var tagID string
		var categoryID sql.NullString
		var tagName string
		if err := taxRows.Scan(&tagID, &categoryID, &tagName); err != nil {
			return nil, err
		}
		index.tags[tagID] = categoryID.String
		normalized := normalizeTagName(tagName)
		if index.names[normalized] == nil {
			index.names[normalized] = map[string]bool{}
		}
		index.names[normalized][tagID] = true
	}
	taxRows.Close()
	if err := taxRows.Err(); err != nil {
		return nil, err
	}
	aliasRows, err := db.Query(`SELECT tag_id, alias FROM taxonomy_tag_alias WHERE snapshot_id=?`, snapshotID)
	if err != nil {
		return nil, err
	}
	for aliasRows.Next() {
		var tagID, alias string
		if err := aliasRows.Scan(&tagID, &alias); err != nil {
			return nil, err
		}
		normalized := normalizeTagName(alias)
		if index.names[normalized] == nil {
			index.names[normalized] = map[string]bool{}
		}
		index.names[normalized][tagID] = true
	}
	aliasRows.Close()
	if err := aliasRows.Err(); err != nil {
		return nil, err
	}
	return index, nil
}

// resolve mirrors TaxonomyIndex.resolve for a single local tag.
func (t *taxonomyIndex) resolve(db dbx, localTagID, name string) (taxonomyMatch, error) {
	if t.snapshotID == "" {
		return taxonomyMatch{snapshotID: t.snapshotID, method: "unmapped"}, nil
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
	return t.resolveExternal(externalIDs, name), nil
}

// resolveExternal is resolve with the tag's StashDB stash_ids already loaded,
// for callers that resolve many tags at once.
func (t *taxonomyIndex) resolveExternal(externalIDs map[string]bool, name string) taxonomyMatch {
	if t.snapshotID == "" {
		return taxonomyMatch{snapshotID: t.snapshotID, method: "unmapped"}
	}
	known := make([]string, 0)
	for id := range externalIDs {
		if _, ok := t.tags[id]; ok {
			known = append(known, id)
		}
	}
	sort.Strings(known)
	if len(known) == 1 {
		return taxonomyMatchFor(t, known[0], "stable_id", 1.0)
	}
	if len(known) > 1 {
		return taxonomyMatch{snapshotID: t.snapshotID, method: "ambiguous_stable_id", ambiguityCount: len(known)}
	}
	candidates := make([]string, 0)
	for id := range t.names[normalizeTagName(name)] {
		candidates = append(candidates, id)
	}
	sort.Strings(candidates)
	if len(candidates) == 1 {
		return taxonomyMatchFor(t, candidates[0], "unique_name_or_alias", 0.9)
	}
	if len(candidates) > 1 {
		return taxonomyMatch{snapshotID: t.snapshotID, method: "ambiguous_name", ambiguityCount: len(candidates)}
	}
	return taxonomyMatch{snapshotID: t.snapshotID, method: "unmapped"}
}

// taxonomyMatchFor mirrors TaxonomyIndex._match.
func taxonomyMatchFor(index *taxonomyIndex, tagID, method string, confidence float64) taxonomyMatch {
	categoryID := index.tags[tagID]
	role := categoryRoles.defaultRole
	if r, ok := categoryRoles.roles[categoryID]; ok {
		role = r
	}
	return taxonomyMatch{
		snapshotID:         index.snapshotID,
		role:               role,
		externalTagID:      tagID,
		externalCategoryID: categoryID,
		confidence:         confidence,
		method:             method,
	}
}

// performerDescribingTagIDs mirrors taxonomy.store.performer_describing_tag_ids:
// the local tags (id -> name) whose StashDB tag sits in a PEOPLE-group
// category other than the excluded ones, or is a listed nationality tag.
func performerDescribingTagIDs(db dbx, tags map[string]string) (map[string]bool, error) {
	result := map[string]bool{}
	index, err := newTaxonomyIndex(db)
	if err != nil || index.snapshotID == "" || len(tags) == 0 {
		return result, err
	}
	people := map[string]bool{}
	rows, err := db.Query(`SELECT category_id FROM taxonomy_category WHERE snapshot_id=? AND group_name=?`,
		index.snapshotID, performerTags.peopleGroup)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var categoryID string
		if err := rows.Scan(&categoryID); err != nil {
			rows.Close()
			return nil, err
		}
		if !performerTags.excludedCategories[categoryID] {
			people[categoryID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	externalIDs := map[string]map[string]bool{}
	idRows, err := db.Query(`SELECT tag_id, endpoint, stash_id FROM source_tag_stash_id`)
	if err != nil {
		return nil, err
	}
	for idRows.Next() {
		var tagID, endpoint, stashID string
		if err := idRows.Scan(&tagID, &endpoint, &stashID); err != nil {
			idRows.Close()
			return nil, err
		}
		if isStashdbEndpoint(endpoint) {
			if externalIDs[tagID] == nil {
				externalIDs[tagID] = map[string]bool{}
			}
			externalIDs[tagID][stashID] = true
		}
	}
	idRows.Close()
	if err := idRows.Err(); err != nil {
		return nil, err
	}
	for tagID, name := range tags {
		match := index.resolveExternal(externalIDs[tagID], name)
		if match.externalTagID == "" {
			continue
		}
		if performerTags.nationalityTags[match.externalTagID] || people[match.externalCategoryID] {
			result[tagID] = true
		}
	}
	return result, nil
}
