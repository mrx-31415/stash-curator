// Live scene eligibility shared by slate selection and the similar paths —
// a port of curator/model/boundaries.py scene_eligibility and
// curator/model/curves.py scene_recovery.
package main

import (
	"math"
	"sort"
	"strings"
)

// model config constants used by the read path (curator/config.py ModelConfig).
const (
	cooldownCenterDays = 90.0
	cooldownWidthDays  = 15.0
	notNowDays         = 30.0
)

// sceneRecovery mirrors curator/model/curves.py scene_recovery with the
// default ModelConfig: exponent clamped to [-60, 60] before the logistic.
func sceneRecovery(daysSincePlayed float64) float64 {
	if daysSincePlayed < 0 || math.IsInf(daysSincePlayed, 0) || math.IsNaN(daysSincePlayed) {
		return 0
	}
	exponent := -(daysSincePlayed - cooldownCenterDays) / cooldownWidthDays
	exponent = math.Max(-60.0, math.Min(60.0, exponent))
	return 1 / (1 + pyExp(exponent))
}

// eligibilityResult mirrors the {"eligible": bool, "reasons": [...]} value
// scene_eligibility returns per scene.
type eligibilityResult struct {
	eligible bool
	reasons  []string
}

// inClause builds a SQLite IN (...) placeholder list for n values.
func inClause(n int) string {
	return strings.Repeat("?,", n-1) + "?"
}

// sceneEligibility mirrors curator/model/boundaries.py scene_eligibility
// with include_temporary=True (the read path never disables it).
func sceneEligibility(db dbx, referenceAtMs int64, sceneIDs map[string]bool) (map[string]eligibilityResult, error) {
	latestFeedback := make(map[string]string)
	notNow := make(map[string]int64)
	rows, err := db.Query(`SELECT scene_id, feedback_type, occurred_at_ms FROM feedback
WHERE reversed_by_id IS NULL ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID, feedbackType string
		var occurredAtMs int64
		if err := rows.Scan(&sceneID, &feedbackType, &occurredAtMs); err != nil {
			return nil, err
		}
		if feedbackType == "thumb_up" || feedbackType == "thumb_down" {
			latestFeedback[sceneID] = feedbackType
		} else if feedbackType == "not_now" {
			notNow[sceneID] = occurredAtMs
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	excluded := make(map[string]bool)
	rows, err = db.Query(`SELECT entity_id FROM exclusion WHERE entity_type='scene'
AND reversed_at_ms IS NULL AND (expires_at_ms IS NULL OR expires_at_ms > ?)`, referenceAtMs)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var entityID string
		if err := rows.Scan(&entityID); err != nil {
			return nil, err
		}
		excluded[entityID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	pruning := make(map[string]string)
	rows, err = db.Query(`SELECT scene_id, state FROM pruning_candidate`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, state string
		if err := rows.Scan(&sceneID, &state); err != nil {
			return nil, err
		}
		pruning[sceneID] = state
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var scenes []string
	if sceneIDs == nil {
		rows, err = db.Query(`SELECT scene_id FROM source_scene`)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			if err := rows.Scan(&sceneID); err != nil {
				return nil, err
			}
			scenes = append(scenes, sceneID)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	} else {
		scenes = make([]string, 0, len(sceneIDs))
		for sceneID := range sceneIDs {
			scenes = append(scenes, sceneID)
		}
		sort.Strings(scenes)
	}

	blockedTagIDs := make([]string, 0)
	rows, err = db.Query(`SELECT tag_id FROM direct_tag_preference WHERE blocked=1`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			return nil, err
		}
		blockedTagIDs = append(blockedTagIDs, tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.Strings(blockedTagIDs)

	notNowMs := int64(notNowDays * 86_400_000)
	available := make(map[string]bool)
	blockedScenes := make(map[string]bool)
	for start := 0; start < len(scenes); start += 500 {
		chunk := scenes[start:minInt(start+500, len(scenes))]
		placeholders := inClause(len(chunk))
		args := make([]any, len(chunk))
		for i, sceneID := range chunk {
			args[i] = sceneID
		}
		rows, err = db.Query(`SELECT DISTINCT scene_id FROM source_file
WHERE available=1 AND scene_id IN (`+placeholders+`)`, args...)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			if err := rows.Scan(&sceneID); err != nil {
				return nil, err
			}
			available[sceneID] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		if len(blockedTagIDs) > 0 {
			tagArgs := make([]any, 0, len(chunk)+len(blockedTagIDs))
			for _, sceneID := range chunk {
				tagArgs = append(tagArgs, sceneID)
			}
			for _, tagID := range blockedTagIDs {
				tagArgs = append(tagArgs, tagID)
			}
			rows, err = db.Query(`SELECT DISTINCT scene_id FROM scene_tag
WHERE scene_id IN (`+placeholders+`) AND tag_id IN (`+inClause(len(blockedTagIDs))+`)`, tagArgs...)
			if err != nil {
				return nil, err
			}
			for rows.Next() {
				var sceneID string
				if err := rows.Scan(&sceneID); err != nil {
					return nil, err
				}
				blockedScenes[sceneID] = true
			}
			rows.Close()
			if err := rows.Err(); err != nil {
				return nil, err
			}
		}
	}

	result := make(map[string]eligibilityResult, len(scenes))
	for _, sceneID := range scenes {
		reasons := make([]string, 0, 6)
		if !available[sceneID] {
			reasons = append(reasons, "file_unavailable")
		}
		if excluded[sceneID] {
			reasons = append(reasons, "hard_exclusion")
		}
		if state, ok := pruning[sceneID]; ok && (state == "review" || state == "remove") {
			reasons = append(reasons, "pruning_"+state)
		}
		if latestFeedback[sceneID] == "thumb_down" {
			reasons = append(reasons, "current_thumb_down")
		}
		notNowAt, hasNotNow := notNow[sceneID]
		if !hasNotNow {
			notNowAt = -notNowMs
		}
		if referenceAtMs-notNowAt < notNowMs {
			reasons = append(reasons, "not_now")
		}
		if blockedScenes[sceneID] && len(reasons) == 0 {
			reasons = append(reasons, "blocked_tag")
		}
		result[sceneID] = eligibilityResult{eligible: len(reasons) == 0, reasons: reasons}
	}
	return result, nil
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// eligibilityJSON builds the {"eligible": bool, "reasons": [...]} value for
// one scene in Python's key order.
func eligibilityJSON(result eligibilityResult) jVal {
	reasons := jvArr()
	for _, reason := range result.reasons {
		reasons.arr = append(reasons.arr, jvStr(reason))
	}
	return jvObj(
		jvKey("eligible", jvBool(result.eligible)),
		jvKey("reasons", reasons),
	)
}
