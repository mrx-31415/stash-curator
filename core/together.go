package main

func requestedMoodID(args jVal) string {
	if args.has("mood_id") {
		return argsString(args, "mood_id", "")
	}
	if args.get("together_mode").truthy() {
		return "together"
	}
	return ""
}

func selectedMood(config jVal, id string) (jVal, string) {
	for _, mood := range config.get("moods").arr {
		if mood.get("id").asString() == id {
			return mood.get("excluded_tags"), id
		}
	}
	return jvArr(), ""
}

// Descendants are resolved from current metadata on every request. UNION
// deduplicates shared descendants and terminates even with cyclic tag parents.
func togetherBlockedScenes(db dbx, tags jVal) (map[string]bool, error) {
	blocked := make(map[string]bool)
	if len(tags.arr) == 0 {
		return blocked, nil
	}
	args := make([]any, len(tags.arr))
	for i, tag := range tags.arr {
		args[i] = tag.get("id").asString()
	}
	rows, err := db.Query(`WITH RECURSIVE excluded(tag_id) AS (
SELECT tag_id FROM source_tag WHERE tag_id IN (`+inClause(len(args))+`)
UNION SELECT tp.tag_id FROM tag_parent tp JOIN excluded e ON tp.parent_tag_id=e.tag_id
) SELECT DISTINCT st.scene_id FROM scene_tag st JOIN excluded e ON st.tag_id=e.tag_id`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		blocked[id] = true
	}
	return blocked, rows.Err()
}
