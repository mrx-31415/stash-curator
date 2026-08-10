// equivalent_tag_names — a port of curator/taxonomy/store.py's
// equivalent_tag_names: expand selected tag names through taxonomy aliases
// and the local tag hierarchy into frozenset groups of normalized names.
package main

import (
	"sort"
	"strings"
)

// normalizeTagName mirrors taxonomy._normalize: casefold + collapse runs of
// whitespace to single spaces.
func normalizeTagName(value string) string {
	return strings.Join(strings.Fields(strings.ToLower(value)), " ")
}

// equivalentTagNames mirrors taxonomy.store.equivalent_tag_names: one group
// per input value; each group is the set of normalized local + taxonomy names
// for the resolved local tag ids (including descendants).
func equivalentTagNames(db dbx, values []string) ([]map[string]bool, error) {
	var snapshotID string
	var hasSnapshot bool
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`).Scan(&snapshotID)
	if err == nil {
		hasSnapshot = true
	} else if err != nil {
		hasSnapshot = false
	}
	groups := make([]map[string]bool, 0, len(values))
	for _, value := range values {
		normalized := normalizeTagName(value)
		localIDs := make(map[string]bool)
		rows, err := db.Query(`SELECT tag_id FROM source_tag WHERE lower(name)=?`, normalized)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var tagID string
			if err := rows.Scan(&tagID); err != nil {
				return nil, err
			}
			localIDs[tagID] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		taxonomyNames := make(map[string]bool)
		var taxonomyIDs map[string]bool
		if hasSnapshot {
			taxonomyIDs, taxonomyNames, err = taxonomyResolve(db, snapshotID, normalized)
			if err != nil {
				return nil, err
			}
			if len(taxonomyIDs) > 0 {
				externalIDs := make([]string, 0, len(taxonomyIDs))
				for id := range taxonomyIDs {
					externalIDs = append(externalIDs, id)
				}
				sort.Strings(externalIDs)
				placeholders := inClause(len(externalIDs))
				args := make([]any, 0, len(externalIDs)+1)
				args = append(args, snapshotID)
				for _, id := range externalIDs {
					args = append(args, id)
				}
				rows, err := db.Query(`SELECT local_tag_id FROM tag_taxonomy_match
WHERE snapshot_id=? AND external_tag_id IN (`+placeholders+`)`, args...)
				if err != nil {
					return nil, err
				}
				for rows.Next() {
					var localTagID string
					if err := rows.Scan(&localTagID); err != nil {
						return nil, err
					}
					if localTagID != "" {
						localIDs[localTagID] = true
					}
				}
				rows.Close()
				if err := rows.Err(); err != nil {
					return nil, err
				}
			}
		}
		// 3 ─ walk tag_parent for all descendants
		queue := make([]string, 0, len(localIDs))
		for id := range localIDs {
			queue = append(queue, id)
		}
		for len(queue) > 0 {
			parent := queue[len(queue)-1]
			queue = queue[:len(queue)-1]
			childRows, err := db.Query(`SELECT tag_id FROM tag_parent WHERE parent_tag_id=?`, parent)
			if err != nil {
				return nil, err
			}
			for childRows.Next() {
				var child string
				if err := childRows.Scan(&child); err != nil {
					return nil, err
				}
				if !localIDs[child] {
					localIDs[child] = true
					queue = append(queue, child)
				}
			}
			childRows.Close()
			if err := childRows.Err(); err != nil {
				return nil, err
			}
		}
		// 4 ─ local names for every resolved id
		if len(localIDs) > 0 {
			ids := make([]string, 0, len(localIDs))
			for id := range localIDs {
				ids = append(ids, id)
			}
			sort.Strings(ids)
			placeholders := inClause(len(ids))
			args := make([]any, len(ids))
			for i, id := range ids {
				args[i] = id
			}
			rows, err := db.Query(`SELECT name FROM source_tag WHERE tag_id IN (`+placeholders+`)`, args...)
			if err != nil {
				return nil, err
			}
			for rows.Next() {
				var name string
				if err := rows.Scan(&name); err != nil {
					return nil, err
				}
				taxonomyNames[normalizeTagName(name)] = true
			}
			rows.Close()
			if err := rows.Err(); err != nil {
				return nil, err
			}
			// 5 ─ taxonomy names/aliases for every local id
			if hasSnapshot {
				external := make([]string, 0)
				rows, err := db.Query(`SELECT external_tag_id FROM tag_taxonomy_match
WHERE snapshot_id=? AND local_tag_id IN (`+placeholders+`)`, append([]any{snapshotID}, args...)...)
				if err != nil {
					return nil, err
				}
				for rows.Next() {
					var externalID string
					if err := rows.Scan(&externalID); err != nil {
						return nil, err
					}
					if externalID != "" {
						external = append(external, externalID)
					}
				}
				rows.Close()
				if err := rows.Err(); err != nil {
					return nil, err
				}
				for _, extID := range external {
					names, err := taxonomyTagNames(db, snapshotID, extID)
					if err != nil {
						return nil, err
					}
					for name := range names {
						taxonomyNames[name] = true
					}
				}
			}
		}
		taxonomyNames[normalized] = true
		groups = append(groups, taxonomyNames)
	}
	return groups, nil
}

// taxonomyResolve mirrors steps 2 (taxonomy ids) and the taxonomy names
// collection for those ids.
func taxonomyResolve(db dbx, snapshotID, normalized string) (map[string]bool, map[string]bool, error) {
	taxonomyIDs := make(map[string]bool)
	rows, err := db.Query(`SELECT tag_id FROM taxonomy_tag WHERE snapshot_id=? AND lower(name)=?
UNION
SELECT tag_id FROM taxonomy_tag_alias WHERE snapshot_id=? AND lower(alias)=?`,
		snapshotID, normalized, snapshotID, normalized)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			return nil, nil, err
		}
		taxonomyIDs[tagID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	names := make(map[string]bool)
	for tagID := range taxonomyIDs {
		tagNames, err := taxonomyTagNames(db, snapshotID, tagID)
		if err != nil {
			return nil, nil, err
		}
		for name := range tagNames {
			names[name] = true
		}
	}
	return taxonomyIDs, names, nil
}

// taxonomyTagNames mirrors the name/alias union query for one taxonomy tag.
func taxonomyTagNames(db dbx, snapshotID, tagID string) (map[string]bool, error) {
	rows, err := db.Query(`SELECT name FROM taxonomy_tag WHERE snapshot_id=? AND tag_id=?
UNION ALL
SELECT alias FROM taxonomy_tag_alias WHERE snapshot_id=? AND tag_id=?`,
		snapshotID, tagID, snapshotID, tagID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]bool)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		result[normalizeTagName(name)] = true
	}
	return result, rows.Err()
}
