// get_impression_measurement — issue #146 Channel B: the shown-never-played
// pre-condition gate. A port of backend.py's _impression_measurement: reads
// impression_item (shown), the positive-action union (played), and the
// never-shown corpus, and reports per-bucket counts plus the display-time
// policy_score distribution. Read-only; deliberately not wired into the
// model build.
package main

import (
	"math"
)

// observedPlaybackSQL is defined in slate.go.

// pyRoundDigits reproduces CPython's round(f, ndigits) for |f| < 1e16: it
// scales by 10^ndigits, rounds half-to-even, then divides back (the exact
// algorithm in CPython's double_round for this magnitude range).
func pyRoundDigits(f float64, digits int) float64 {
	scale := math.Pow10(digits)
	return math.RoundToEven(f*scale) / scale
}

func opGetImpressionMeasurement(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_impression_measurement",
		func(settings jVal) (jVal, error) { return getImpressionMeasurementBody(pluginDir, payload, settings) })
}

func getImpressionMeasurementBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()

	// Mirrors builder.py's positive-action-per-impression UNION
	// (curator/model/builder.py:1006-1011 / core/modelbuild.go:760-765):
	// a played or thumbed scene links to the impression that surfaced it.
	played := make(map[[2]string]bool)
	rows, err := db.Query(`
SELECT scene_id, impression_id FROM play_session
WHERE impression_id IS NOT NULL
  AND provenance='direct_player' AND ` + observedPlaybackSQL + `
UNION
SELECT scene_id, impression_id FROM feedback
WHERE impression_id IS NOT NULL
  AND feedback_type='thumb_up' AND reversed_by_id IS NULL`)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	for rows.Next() {
		var sceneID, impressionID string
		if err := rows.Scan(&sceneID, &impressionID); err != nil {
			return jvNull(), err
		}
		played[[2]string{sceneID, impressionID}] = true
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	rows.Close()

	type shownItem struct {
		sceneID      string
		impressionID string
		policyScore  float64
	}
	items := []shownItem{}
	itemRows, err := db.Query(`SELECT scene_id, impression_id, policy_score FROM impression_item`)
	if err != nil {
		return jvNull(), err
	}
	defer itemRows.Close()
	for itemRows.Next() {
		var item shownItem
		if err := itemRows.Scan(&item.sceneID, &item.impressionID, &item.policyScore); err != nil {
			return jvNull(), err
		}
		items = append(items, item)
	}
	if err := itemRows.Err(); err != nil {
		return jvNull(), err
	}

	var neverShown int64
	if err := db.QueryRow(`
SELECT count(*) FROM source_scene
WHERE scene_id NOT IN (SELECT scene_id FROM impression_item)`).Scan(&neverShown); err != nil {
		return jvNull(), err
	}

	bucket := func(selected []shownItem) jVal {
		if len(selected) == 0 {
			return jvObj(
				jvKey("count", jvInt(0)),
				jvKey("mean_policy_score", jvNull()),
				jvKey("max_policy_score", jvNull()),
			)
		}
		sum := 0.0
		maxScore := selected[0].policyScore
		for _, item := range selected {
			sum += item.policyScore
			if item.policyScore > maxScore {
				maxScore = item.policyScore
			}
		}
		return jvObj(
			jvKey("count", jvInt(int64(len(selected)))),
			jvKey("mean_policy_score", jvFloat(pyRoundDigits(sum/float64(len(selected)), 6))),
			jvKey("max_policy_score", jvFloat(pyRoundDigits(maxScore, 6))),
		)
	}

	playedItems := []shownItem{}
	skippedItems := []shownItem{}
	for _, item := range items {
		if played[[2]string{item.sceneID, item.impressionID}] {
			playedItems = append(playedItems, item)
		} else {
			skippedItems = append(skippedItems, item)
		}
	}

	shownPlayRate := jvNull()
	if len(items) > 0 {
		shownPlayRate = jvFloat(pyRoundDigits(float64(len(playedItems))/float64(len(items)), 6))
	}

	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("buckets", jvObj(
			jvKey("shown", bucket(items)),
			jvKey("played", bucket(playedItems)),
			jvKey("skipped", bucket(skippedItems)),
			jvKey("never_shown", jvObj(
				jvKey("count", jvInt(neverShown)),
				jvKey("mean_policy_score", jvNull()),
				jvKey("max_policy_score", jvNull()),
			)),
		)),
		jvKey("shown_play_rate", shownPlayRate),
	), nil
}
