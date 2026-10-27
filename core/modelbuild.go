// Model build — a port of curator/model/builder.py's PreferenceModelBuilder:
// labels, evidence fingerprint, model-id derivation with reuse, affinities,
// scoring (with the compiled-core kernels invoked by re-exec), and the
// artifact publication (feature_affinity / direct_scene_state /
// model_scene_score / model_scene_neighbor / model_performer_edge + lane
// classification + slate materialization + validation + sidecar supersede).
// The published model artifact is the oracle.
package main

import (
	"bufio"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"math"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	performerSimilarityAffinityCutoff = 0.005
	modelBuildVersion                 = 4
	affinityPrior                     = 1.0
	affinitySiblingPrior              = 1.0
	// Mirrors ModelConfig.impact_correction_confidence: a deliberate "this
	// impact move is wrong" correction is direct evidence about the scene's own
	// appeal, so it sits below a fresh rating but above an implicit signal.
	impactCorrectionConfidence = 0.60
	// Mirrors ModelConfig.implicit_skip_* in curator/config.py (#146 Channel A).
	// The base is kept far below explicit feedback (thumbs, ratings) so
	// implicit signal never outranks it; the issue author flagged it may need
	// to be even weaker after live measurement.
	implicitSkipConfidence    = 0.075
	implicitSkipSurpriseBonus = 2.0
	implicitSkipIPSCap        = 2.0
)

// sceneLabel mirrors _SceneLabel: outcome/confidence/effectiveEvidence cover
// every signal and drive affinity learning; the absolute* fields are what
// materializes as a scene's own appeal. Every current label signal is
// absolute, so the two agree; pairwise evidence (implicit skips) enters
// affinities as matched pair events instead of labels.
type sceneLabel struct {
	outcome           float64
	confidence        float64
	effectiveEvidence float64
	signalTypes       []string
	absoluteOutcome   float64
	absoluteEvidence  float64
}

// storedFeature mirrors features.store.StoredFeature.
type storedFeature struct {
	featureID  string
	family     string
	name       string
	value      float64
	confidence float64
	metadata   jVal
}

// modelAffinity mirrors _Affinity.
type modelAffinity struct {
	featureID  string
	affinity   float64
	confidence float64
	support    float64
	sceneCount int64
	contexts   jVal
}

func clampValue(value, low, high float64) float64 {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}

// softBound mirrors _soft_bound: bound a component without collapsing
// ordering at the cap. Exact below knee*bound — where a hard clamp was
// inactive anyway — then smoothly asymptotic to bound. A hard clamp maps
// every strong scene to the identical value, and appeal is ranked and
// thresholded directly (prune, sentiment review), so those ties lose real
// information. 1-exp(-t) rather than tanh: same shape, and the exponential
// already agrees bit-for-bit across the Go/Python boundary, which the
// artifact parity gate requires.
func softBound(value, bound float64) float64 {
	const knee = 0.8
	kneeAt := knee * bound
	head := bound - kneeAt
	magnitude := math.Abs(value)
	if magnitude <= kneeAt || head <= 0 {
		return clampValue(value, -bound, bound)
	}
	return math.Copysign(kneeAt+head*(1-math.Exp(-(magnitude-kneeAt)/head)), value)
}

// clamp mirrors _clamp.
func clamp(value float64) float64 {
	return clampValue(value, -1, 1)
}

// modelSceneLabels mirrors PreferenceModelBuilder._scene_labels.
// sceneReasonFlipValue and sceneReasonFlipConfidence mirror
// ModelConfig.scene_reason_flip_value and scene_reason_flip_confidence.
const (
	sceneReasonFlipValue      = 0.5
	sceneReasonFlipConfidence = 0.5
)

// sceneOnlySignal mirrors builder.py SCENE_ONLY_SIGNAL: a "Just this scene"
// answer, which moves the scene's own appeal but never reaches training.
const sceneOnlySignal = "scene_reason_scene"

// modelSceneLabels mirrors _scene_labels. The second map mirrors
// _training_overrides: for scenes with a "Just this scene" signal, the label
// without it (absent when nothing else is left).
func modelSceneLabels(db dbx) (map[string]sceneLabel, map[string]*sceneLabel, error) {
	type signal struct {
		value      float64
		confidence float64
		signalType string
	}
	signals := map[string][]signal{}
	rows, err := db.Query(`
SELECT scene_id, event_type, outcome, confidence, payload_json FROM behavior_event
WHERE scene_id IS NOT NULL AND outcome IS NOT NULL ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID, eventType, payloadJSON string
		var outcome, confidence float64
		if err := rows.Scan(&sceneID, &eventType, &outcome, &confidence, &payloadJSON); err != nil {
			rows.Close()
			return nil, nil, err
		}
		signalType := eventType
		if parsed, err := parseJSON([]byte(payloadJSON)); err == nil {
			if v := parsed.get("primary_signal"); v.kind == jStr && v.s != "" {
				signalType = v.s
			}
		}
		signals[sceneID] = append(signals[sceneID], signal{outcome, confidence, signalType})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, feedback_type, occurred_at_ms FROM feedback
WHERE reversed_by_id IS NULL AND feedback_type IN ('thumb_up', 'thumb_down')
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID, feedbackType string
		var occurredAtMs int64
		if err := rows.Scan(&sceneID, &feedbackType, &occurredAtMs); err != nil {
			rows.Close()
			return nil, nil, err
		}
		value := -1.0
		if feedbackType == "thumb_up" {
			value = 0.90
		}
		signals[sceneID] = append(signals[sceneID], signal{value, 1.0, feedbackType})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, value FROM feedback
WHERE reversed_by_id IS NULL AND feedback_type='curation_rating'
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID string
		var value sql.NullString
		if err := rows.Scan(&sceneID, &value); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if !value.Valid {
			continue
		}
		rating, parseErr := strconv.ParseInt(value.String, 10, 64)
		if parseErr != nil || rating < 0 || rating > 10 {
			continue
		}
		signals[sceneID] = append(signals[sceneID], signal{
			clamp((float64(rating) - 5) / 5), 0.80, "curation_rating",
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	rows, err = db.Query(`SELECT scene_id, rating100 FROM source_scene WHERE rating100 IS NOT NULL`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID string
		var rating100 int64
		if err := rows.Scan(&sceneID, &rating100); err != nil {
			rows.Close()
			return nil, nil, err
		}
		signals[sceneID] = append(signals[sceneID], signal{
			clamp((float64(rating100) - 50) / 50), 0.90, "scene_rating",
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, value FROM feedback
WHERE reversed_by_id IS NULL AND feedback_type='impact_correction'
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID string
		var value sql.NullString
		if err := rows.Scan(&sceneID, &value); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if !value.Valid {
			continue
		}
		outcome, parseErr := strconv.ParseFloat(value.String, 64)
		if parseErr != nil || (outcome != 1.0 && outcome != -1.0) {
			continue
		}
		// A deliberate "this impact move is wrong" correction is direct
		// evidence about the scene's own appeal: +1 pulls a wrongly demoted
		// scene back up, -1 pulls a wrongly promoted one back down.
		signals[sceneID] = append(signals[sceneID], signal{
			outcome, impactCorrectionConfidence, "impact_correction",
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	// Why these? answers about the scene itself (mirrors _scene_labels): a
	// thumb's value and confidence; "Just this scene" stays out of training.
	rows, err = db.Query(`
SELECT a.scene_id, a.polarity, a.flipped, a.flip_strength,
       EXISTS (SELECT 1 FROM scene_reason r
               WHERE r.answer_id=a.answer_id AND r.subject_type='scene') AS only_scene
FROM scene_reason_answer a
ORDER BY a.scene_id, a.occurred_at_ms, a.answer_id`)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var sceneID, flipStrength string
		var polarity, flipped, onlyScene int64
		if err := rows.Scan(&sceneID, &polarity, &flipped, &flipStrength, &onlyScene); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if onlyScene == 0 && flipped == 0 {
			continue
		}
		// "Just this scene" is a thumb about this scene; a flip is a mild
		// correction (mirrors scene_reason_flip_value/confidence).
		var item signal
		if onlyScene != 0 || flipStrength == "strong" {
			// A strong flip ("Not for me" / "I'd really like this") is a thumb.
			item = signal{-1.0, 1.0, "scene_reason_flip"}
			if onlyScene != 0 {
				item.signalType = sceneOnlySignal
			}
			if polarity > 0 {
				item.value = 0.90
			}
		} else {
			item = signal{-sceneReasonFlipValue, sceneReasonFlipConfidence, "scene_reason_flip"}
			if polarity > 0 {
				item.value = sceneReasonFlipValue
			}
		}
		signals[sceneID] = append(signals[sceneID], item)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	aggregate := func(sceneSignals []signal) (sceneLabel, bool) {
		confidences := make([]float64, 0, len(sceneSignals))
		products := make([]float64, 0, len(sceneSignals))
		absoluteConfidences := make([]float64, 0, len(sceneSignals))
		absoluteProducts := make([]float64, 0, len(sceneSignals))
		for _, item := range sceneSignals {
			confidences = append(confidences, item.confidence)
			products = append(products, item.value*item.confidence)
			absoluteConfidences = append(absoluteConfidences, item.confidence)
			absoluteProducts = append(absoluteProducts, item.value*item.confidence)
		}
		evidence := sumFloats(confidences)
		if evidence <= 0 {
			return sceneLabel{}, false
		}
		weighted := sumFloats(products)
		types := make([]string, 0, len(sceneSignals))
		for _, item := range sceneSignals {
			types = append(types, item.signalType)
		}
		absoluteEvidence := sumFloats(absoluteConfidences)
		absoluteOutcome := 0.0
		if absoluteEvidence > 0 {
			absoluteOutcome = sumFloats(absoluteProducts) / absoluteEvidence
		}
		return sceneLabel{
			outcome:           clamp(weighted / evidence),
			confidence:        1 - math.Exp(-evidence),
			effectiveEvidence: evidence,
			signalTypes:       types,
			absoluteOutcome:   clamp(absoluteOutcome),
			absoluteEvidence:  absoluteEvidence,
		}, true
	}
	labels := map[string]sceneLabel{}
	overrides := map[string]*sceneLabel{}
	for sceneID, sceneSignals := range signals {
		if label, ok := aggregate(sceneSignals); ok {
			labels[sceneID] = label
		}
		sceneOnly := false
		kept := make([]signal, 0, len(sceneSignals))
		for _, item := range sceneSignals {
			if item.signalType == sceneOnlySignal {
				sceneOnly = true
			} else {
				kept = append(kept, item)
			}
		}
		if sceneOnly {
			if label, ok := aggregate(kept); ok {
				overrides[sceneID] = &label
			} else {
				overrides[sceneID] = nil
			}
		}
	}
	return labels, overrides, nil
}

// metadataWrongScenes mirrors _metadata_wrong_scenes.
func metadataWrongScenes(db dbx) (map[string]bool, error) {
	rows, err := db.Query(`
SELECT DISTINCT scene_id FROM feedback
WHERE feedback_type='metadata_wrong' AND reversed_by_id IS NULL`)
	if err != nil {
		return nil, err
	}
	metadataWrong := map[string]bool{}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		metadataWrong[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return metadataWrong, nil
}

// modelTrainingLabels mirrors _training_labels: no "metadata is wrong" scene,
// and a scene's "Just this scene" answers left out.
func modelTrainingLabels(db dbx, labels map[string]sceneLabel, overrides map[string]*sceneLabel) (map[string]sceneLabel, error) {
	metadataWrong, err := metadataWrongScenes(db)
	if err != nil {
		return nil, err
	}
	result := map[string]sceneLabel{}
	for sceneID, label := range labels {
		if metadataWrong[sceneID] {
			continue
		}
		if override, ok := overrides[sceneID]; ok {
			if override != nil {
				result[sceneID] = *override
			}
			continue
		}
		result[sceneID] = label
	}
	return result, nil
}

// modelLabelMean mirrors _label_mean.
func modelLabelMean(labels map[string]sceneLabel) float64 {
	confidences := make([]float64, 0, len(labels))
	products := make([]float64, 0, len(labels))
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		confidences = append(confidences, label.confidence)
		products = append(products, label.outcome*label.confidence)
	}
	support := sumFloats(confidences)
	if support <= 0 {
		return 0.0
	}
	return sumFloats(products) / support
}

// modelAbsoluteLabelMean mirrors _absolute_label_mean: the population
// baseline for modelAffinities' general per-scene loop, scoped to the
// absolute channel like that loop.
func modelAbsoluteLabelMean(labels map[string]sceneLabel) float64 {
	confidences := make([]float64, 0, len(labels))
	products := make([]float64, 0, len(labels))
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		if label.absoluteEvidence <= 0 {
			continue
		}
		confidence := 1 - math.Exp(-label.absoluteEvidence)
		confidences = append(confidences, confidence)
		products = append(products, confidence*label.absoluteOutcome)
	}
	support := sumFloats(confidences)
	if support <= 0 {
		return 0.0
	}
	return sumFloats(products) / support
}

// modelEvidenceFingerprint mirrors _evidence_fingerprint.
func modelEvidenceFingerprint(db dbx, labels map[string]sceneLabel) (string, error) {
	labelRows := jvArr()
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		types := jvArr()
		for _, t := range label.signalTypes {
			types.arr = append(types.arr, jvStr(t))
		}
		labelRows.arr = append(labelRows.arr, jvArr(
			jvStr(sceneID), jvFloat(label.outcome), jvFloat(label.confidence),
			jvFloat(label.effectiveEvidence), types,
			jvFloat(label.absoluteOutcome), jvFloat(label.absoluteEvidence),
		))
	}
	feedbackState := jvArr()
	rows, err := db.Query(`
SELECT feedback_id, scene_id, feedback_type, value, occurred_at_ms, reversed_by_id, payload_json
FROM feedback ORDER BY feedback_id`)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var feedbackID, sceneID, feedbackType string
		var value, reversedBy sql.NullString
		var occurredAtMs int64
		var payloadJSON string
		if err := rows.Scan(&feedbackID, &sceneID, &feedbackType, &value, &occurredAtMs, &reversedBy, &payloadJSON); err != nil {
			rows.Close()
			return "", err
		}
		feedbackValue := jvNull()
		if value.Valid {
			feedbackValue = jvStr(value.String)
		}
		reversedValue := jvNull()
		if reversedBy.Valid {
			reversedValue = jvStr(reversedBy.String)
		}
		feedbackState.arr = append(feedbackState.arr, jvArr(
			jvStr(feedbackID), jvStr(sceneID), jvStr(feedbackType),
			feedbackValue, jvInt(occurredAtMs), reversedValue, jvStr(payloadJSON),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", err
	}
	exclusions := jvArr()
	rows, err = db.Query(`SELECT * FROM exclusion ORDER BY exclusion_id`)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		columns, err := rows.Columns()
		if err != nil {
			rows.Close()
			return "", err
		}
		values := make([]any, len(columns))
		scanned := make([]any, len(columns))
		for i := range columns {
			scanned[i] = &values[i]
		}
		if err := rows.Scan(scanned...); err != nil {
			rows.Close()
			return "", err
		}
		row := jvArr()
		for _, value := range values {
			row.arr = append(row.arr, fingerprintValue(value))
		}
		exclusions.arr = append(exclusions.arr, row)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", err
	}
	pruning := jvArr()
	rows, err = db.Query(`SELECT * FROM pruning_candidate ORDER BY scene_id`)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		columns, err := rows.Columns()
		if err != nil {
			rows.Close()
			return "", err
		}
		values := make([]any, len(columns))
		scanned := make([]any, len(columns))
		for i := range columns {
			scanned[i] = &values[i]
		}
		if err := rows.Scan(scanned...); err != nil {
			rows.Close()
			return "", err
		}
		row := jvArr()
		for _, value := range values {
			row.arr = append(row.arr, fingerprintValue(value))
		}
		pruning.arr = append(pruning.arr, row)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", err
	}
	tagPreferences := jvArr()
	rows, err = db.Query(`
SELECT tag_id, preference_id, value, occurred_at_ms
FROM direct_tag_preference ORDER BY tag_id`)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var tagID, preferenceID string
		var value float64
		var occurredAtMs int64
		if err := rows.Scan(&tagID, &preferenceID, &value, &occurredAtMs); err != nil {
			rows.Close()
			return "", err
		}
		tagPreferences.arr = append(tagPreferences.arr, jvArr(
			jvStr(tagID), jvStr(preferenceID), jvFloat(value), jvInt(occurredAtMs),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", err
	}
	// Why these? reasons feed modelSceneReasons, so a new answer must change
	// the model_id or the build would reuse the previous artifact.
	sceneReasons := jvArr()
	rows, err = db.Query(`
SELECT r.answer_id, r.subject_type, r.subject_id, a.polarity
FROM scene_reason r JOIN scene_reason_answer a ON a.answer_id=r.answer_id
ORDER BY r.answer_id, r.subject_type, r.subject_id`)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var answerID, subjectType, subjectID string
		var polarity int64
		if err := rows.Scan(&answerID, &subjectType, &subjectID, &polarity); err != nil {
			rows.Close()
			return "", err
		}
		sceneReasons.arr = append(sceneReasons.arr, jvArr(
			jvStr(answerID), jvStr(subjectType), jvStr(subjectID), jvInt(polarity),
		))
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", err
	}
	doc := jvObj(
		jvKey("labels", labelRows),
		jvKey("feedback", feedbackState),
		jvKey("exclusions", exclusions),
		jvKey("pruning", pruning),
		jvKey("tag_preferences", tagPreferences),
		jvKey("scene_reasons", sceneReasons),
	)
	return sha256Hex(doc.marshalSortedKeys()), nil
}

// modelSyncWatermark mirrors _sync_watermark.
func modelSyncWatermark(db dbx) string {
	var watermark sql.NullString
	if err := db.QueryRow(`SELECT max(watermark) FROM sync_cursor WHERE state='complete'`).Scan(&watermark); err != nil {
		return ""
	}
	if !watermark.Valid {
		return ""
	}
	return watermark.String
}

// modelSourceFingerprint mirrors _source_fingerprint (4 tables).
func modelSourceFingerprint(db dbx) (string, error) {
	digest := sha256.New()
	for _, spec := range []struct {
		label     string
		statement string
	}{
		{"source_play", `SELECT scene_id, max(played_at_ms) FROM source_play GROUP BY scene_id ORDER BY scene_id`},
		{"source_performer", `SELECT performer_id, favorite, rating100 FROM source_performer ORDER BY performer_id`},
		{"source_studio", `SELECT studio_id, favorite FROM source_studio ORDER BY studio_id`},
		{"source_file", `SELECT scene_id, max(available) FROM source_file GROUP BY scene_id ORDER BY scene_id`},
	} {
		if err := fingerprintTable(db, digest, spec.label, spec.statement); err != nil {
			return "", err
		}
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

// modelStoredFeatures mirrors FeatureStore.entity_features.
func modelStoredFeatures(db dbx, featureVersion, entityType string) (map[string][]storedFeature, error) {
	rows, err := db.Query(`
SELECT ef.entity_id, ef.feature_id, fd.family, fd.name, ef.value,
       ef.confidence, fd.metadata_json
FROM entity_feature ef
JOIN feature_definition fd ON fd.feature_id = ef.feature_id
WHERE ef.feature_version = ? AND ef.entity_type = ?
ORDER BY ef.entity_id, fd.family, fd.name`, featureVersion, entityType)
	if err != nil {
		return nil, err
	}
	result := map[string][]storedFeature{}
	definitions := map[string]storedFeature{}
	for rows.Next() {
		var entityID, featureID, family, name string
		var value, confidence float64
		var metadataJSON string
		if err := rows.Scan(&entityID, &featureID, &family, &name, &value, &confidence, &metadataJSON); err != nil {
			rows.Close()
			return nil, err
		}
		feature, seen := definitions[featureID]
		if !seen {
			metadata := jvObj()
			if parsed, err := parseJSON([]byte(metadataJSON)); err == nil {
				metadata = parsed
			}
			// Definitions are immutable and shared by every scene using the feature.
			feature = storedFeature{featureID: featureID, family: family, name: name, metadata: metadata}
			definitions[featureID] = feature
		}
		feature.value, feature.confidence = value, confidence
		result[entityID] = append(result[entityID], feature)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// modelSceneContexts mirrors _scene_contexts.
type sceneContext struct {
	studioID   string
	performers []string
}

func modelSceneContexts(db dbx) (map[string]sceneContext, error) {
	contexts := map[string]sceneContext{}
	rows, err := db.Query(`SELECT scene_id, studio_id FROM source_scene ORDER BY scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var studioID sql.NullString
		if err := rows.Scan(&sceneID, &studioID); err != nil {
			rows.Close()
			return nil, err
		}
		contexts[sceneID] = sceneContext{studioID: studioID.String}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, performerID string
		if err := rows.Scan(&sceneID, &performerID); err != nil {
			rows.Close()
			return nil, err
		}
		context := contexts[sceneID]
		context.performers = append(context.performers, performerID)
		contexts[sceneID] = context
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return contexts, nil
}

// pairEvent mirrors _PairEvent: one implicit comparison (a played or thumbed
// card beating an earlier card it was shown below).
type pairEvent struct {
	winnerScene string
	loserScene  string
	confidence  float64
}

// modelImplicitSkipEvents mirrors _implicit_skip_events (#146 Channel A):
// when a recommended scene is played or thumbed, the earlier-position cards
// in the same impression are treated as weak pairwise losers. Surprise uses
// the stored policy_score (surprise = max(0, loser_score - winner_score));
// confidence uses the implicit base, so implicit signal never outranks
// explicit feedback. Trigger is played or
// thumbed only. Pairs are virtual (build-time only).
func modelImplicitSkipEvents(db dbx) ([]pairEvent, error) {
	metadataWrong, err := metadataWrongScenes(db)
	if err != nil {
		return nil, err
	}
	type winner struct{ sceneID, impressionID string }
	winners := map[string]winner{}
	rows, err := db.Query(`
SELECT ps.scene_id, ps.impression_id FROM play_session ps
WHERE ps.impression_id IS NOT NULL
  AND ps.provenance='direct_player' AND ` + observedPlaybackSQL + `
UNION
SELECT f.scene_id, f.impression_id FROM feedback f
WHERE f.impression_id IS NOT NULL
  AND f.feedback_type='thumb_up' AND f.reversed_by_id IS NULL`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, impressionID string
		if err := rows.Scan(&sceneID, &impressionID); err != nil {
			rows.Close()
			return nil, err
		}
		if metadataWrong[sceneID] {
			continue
		}
		if _, exists := winners[sceneID]; exists {
			continue
		}
		winners[sceneID] = winner{sceneID, impressionID}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	winnerScenes := make([]string, 0, len(winners))
	for sceneID := range winners {
		winnerScenes = append(winnerScenes, sceneID)
	}
	sort.Strings(winnerScenes)
	var events []pairEvent
	for _, winnerScene := range winnerScenes {
		impressionID := winners[winnerScene].impressionID
		rows, err := db.Query(`
SELECT scene_id, position, policy_score FROM impression_item
WHERE impression_id=? ORDER BY position`, impressionID)
		if err != nil {
			return nil, err
		}
		type item struct {
			sceneID     string
			position    int64
			policyScore float64
		}
		var items []item
		for rows.Next() {
			var sceneID string
			var position int64
			var policyScore float64
			if err := rows.Scan(&sceneID, &position, &policyScore); err != nil {
				rows.Close()
				return nil, err
			}
			items = append(items, item{sceneID, position, policyScore})
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		winnerPosition := int64(-1)
		winnerScore := 0.0
		for _, it := range items {
			if it.sceneID == winnerScene {
				winnerPosition = it.position
				winnerScore = it.policyScore
				break
			}
		}
		if winnerPosition < 0 {
			continue
		}
		for _, it := range items {
			if it.position >= winnerPosition || it.sceneID == winnerScene {
				continue
			}
			surprise := it.policyScore - winnerScore
			if surprise < 0 {
				surprise = 0
			}
			confidence := implicitSkipConfidence * (1.0 + implicitSkipSurpriseBonus*surprise) *
				math.Min(implicitSkipIPSCap, 1.0)
			if confidence > 1.0 {
				confidence = 1.0
			}
			events = append(events, pairEvent{winnerScene, it.sceneID, confidence})
		}
	}
	return events, nil
}

// modelAffinities mirrors _affinities.
func modelAffinities(db dbx, sceneFeatures map[string][]storedFeature,
	labels map[string]sceneLabel, absoluteLabelMean float64) (map[string]modelAffinity, error) {
	type accumulator struct {
		sceneID string
		weight  float64
		outcome float64
	}
	accumulators := map[string][]accumulator{}
	// Absolute channel only: pairwise evidence is accumulated as matched pairs
	// below, where shared features cancel by construction.
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		if label.absoluteEvidence <= 0 {
			continue
		}
		absoluteConfidence := 1 - math.Exp(-label.absoluteEvidence)
		for _, feature := range sceneFeatures[sceneID] {
			weight := absoluteConfidence * feature.confidence * math.Abs(feature.value)
			accumulators[feature.featureID] = append(accumulators[feature.featureID], accumulator{
				sceneID: sceneID,
				weight:  weight,
				outcome: (label.absoluteOutcome - absoluteLabelMean) * copysign(1, feature.value),
			})
		}
	}
	// Pairwise comparisons: matched winner/loser, so a feature both scenes
	// share is skipped entirely (no numerator or support contribution) — only
	// what differed between the two scenes carries information. No labelMean
	// subtraction: the comparison already isolates the signal.
	pairEvents, err := modelImplicitSkipEvents(db)
	if err != nil {
		return nil, err
	}
	for _, event := range pairEvents {
		winnerFeatures := map[string]storedFeature{}
		for _, f := range sceneFeatures[event.winnerScene] {
			winnerFeatures[f.featureID] = f
		}
		loserFeatures := map[string]storedFeature{}
		for _, f := range sceneFeatures[event.loserScene] {
			loserFeatures[f.featureID] = f
		}
		var winnerOnly, loserOnly []string
		for featureID := range winnerFeatures {
			if _, shared := loserFeatures[featureID]; !shared {
				winnerOnly = append(winnerOnly, featureID)
			}
		}
		for featureID := range loserFeatures {
			if _, shared := winnerFeatures[featureID]; !shared {
				loserOnly = append(loserOnly, featureID)
			}
		}
		sort.Strings(winnerOnly)
		sort.Strings(loserOnly)
		for _, featureID := range winnerOnly {
			feature := winnerFeatures[featureID]
			weight := event.confidence * feature.confidence * math.Abs(feature.value)
			accumulators[featureID] = append(accumulators[featureID], accumulator{
				sceneID: event.winnerScene,
				weight:  weight,
				outcome: copysign(1, feature.value),
			})
		}
		for _, featureID := range loserOnly {
			feature := loserFeatures[featureID]
			weight := event.confidence * feature.confidence * math.Abs(feature.value)
			accumulators[featureID] = append(accumulators[featureID], accumulator{
				sceneID: event.loserScene,
				weight:  weight,
				outcome: -copysign(1, feature.value),
			})
		}
	}
	contexts, err := modelSceneContexts(db)
	if err != nil {
		return nil, err
	}
	supports := map[string]float64{}
	numerators := map[string]float64{}
	for featureID, values := range accumulators {
		weights := make([]float64, 0, len(values))
		weightedOutcomes := make([]float64, 0, len(values))
		for _, item := range values {
			weights = append(weights, item.weight)
			weightedOutcomes = append(weightedOutcomes, item.weight*item.outcome)
		}
		supports[featureID] = sumFloats(weights)
		numerators[featureID] = sumFloats(weightedOutcomes)
	}
	siblingPriors, err := modelSiblingPriors(db, sceneFeatures, supports, numerators)
	if err != nil {
		return nil, err
	}
	lift, err := modelWatchLift(db, sceneFeatures)
	if err != nil {
		return nil, err
	}
	reasons, err := modelSceneReasons(db, sceneFeatures)
	if err != nil {
		return nil, err
	}
	for featureID, term := range reasons {
		current := lift[featureID]
		lift[featureID] = watchLiftTerm{support: current.support + term.support, numerator: current.numerator + term.numerator}
	}
	result := map[string]modelAffinity{}
	for featureID, values := range accumulators {
		studios := map[string]bool{}
		performers := map[string]bool{}
		scenes := map[string]bool{}
		weights := make([]float64, 0, len(values))
		weightedOutcomes := make([]float64, 0, len(values))
		for _, item := range values {
			weights = append(weights, item.weight)
			weightedOutcomes = append(weightedOutcomes, item.weight*item.outcome)
			scenes[item.sceneID] = true
			if context, ok := contexts[item.sceneID]; ok {
				if context.studioID != "" {
					studios[context.studioID] = true
				}
				for _, performer := range context.performers {
					performers[performer] = true
				}
			}
		}
		liftTerm := lift[featureID]
		support := supports[featureID] + liftTerm.support
		numerator := numerators[featureID] + liftTerm.numerator
		// Shrink toward what the tag's siblings say rather than toward zero;
		// mirrors PreferenceModelBuilder._sibling_priors' use in _affinities.
		priorPseudo := affinityPrior * affinitySiblingPrior * siblingPriors[featureID]
		affinity := (numerator + priorPseudo) / (affinityPrior + support)
		result[featureID] = modelAffinity{
			featureID:  featureID,
			affinity:   clamp(affinity),
			confidence: 1 - math.Exp(-support/3.0),
			support:    support,
			sceneCount: int64(len(scenes)),
			contexts: jvObj(
				jvKey("studios", jvInt(int64(len(studios)))),
				jvKey("performers", jvInt(int64(len(performers)))),
			),
		}
	}
	// Tags never on a labelled scene can still be avoided (or chosen) when
	// browsing; watch lift alone speaks for them.
	for _, featureID := range sortedStringKeys(lift) {
		if _, labelled := accumulators[featureID]; labelled {
			continue
		}
		term := lift[featureID]
		result[featureID] = modelAffinity{
			featureID:  featureID,
			affinity:   clamp(term.numerator / (affinityPrior + term.support)),
			confidence: 1 - math.Exp(-term.support/3.0),
			support:    term.support,
			sceneCount: 0,
			contexts: jvObj(
				jvKey("studios", jvInt(0)),
				jvKey("performers", jvInt(0)),
			),
		}
	}
	tagFeatures := map[string]string{}
	for _, features := range sceneFeatures {
		for _, feature := range features {
			if feature.family == "content" {
				if tagID := feature.metadata.get("tag_id").asString(); tagID != "" {
					tagFeatures[tagID] = feature.featureID
				}
			}
		}
	}
	rows, err := db.Query(`SELECT tag_id, value FROM direct_tag_preference ORDER BY tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID string
		var directValue float64
		if err := rows.Scan(&tagID, &directValue); err != nil {
			rows.Close()
			return nil, err
		}
		featureID, ok := tagFeatures[tagID]
		if !ok {
			continue
		}
		learned, exists := result[featureID]
		if !exists {
			learned = modelAffinity{featureID: featureID}
		}
		directSupport := 8.0
		blended := clamp((learned.affinity*learned.support + directValue*directSupport) /
			(learned.support + directSupport))
		contextJSON := jvObj()
		for _, pair := range learned.contexts.obj {
			contextJSON.set(pair.key, pair.val)
		}
		contextJSON.set("declared_preference", jvFloat(directValue))
		contextJSON.set("learned_affinity", jvFloat(learned.affinity))
		contextJSON.set("learned_confidence", jvFloat(learned.confidence))
		result[featureID] = modelAffinity{
			featureID:  featureID,
			affinity:   blended,
			confidence: math.Max(learned.confidence, 0.9),
			support:    learned.support + directSupport,
			sceneCount: learned.sceneCount,
			contexts:   contextJSON,
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := inheritTagPreferences(db, tagFeatures, result); err != nil {
		return nil, err
	}
	return result, nil
}

// watchLiftSupport mirrors ModelConfig.watch_lift_support,
// entityWatchLiftSupport mirrors ModelConfig.entity_watch_lift_support, and
// watchLiftShrink mirrors WATCH_LIFT_SHRINK.
const (
	watchLiftSupport       = 2.0
	entityWatchLiftSupport = 2.0
	watchLiftShrink        = 10.0
)

type watchLiftTerm struct{ support, numerator float64 }

// modelWatchLift mirrors PreferenceModelBuilder._watch_lift: per tag,
// performer, and studio feature, pseudo-evidence from how much more often it
// is on watched scenes than in the library. Outcome labels only say how a
// chosen scene went; lift sees the choice itself.
func modelWatchLift(db dbx, sceneFeatures map[string][]storedFeature) (map[string]watchLiftTerm, error) {
	terms := map[string]watchLiftTerm{}
	weights := map[string]float64{}
	for family, weight := range map[string]float64{
		"content": watchLiftSupport, "performer_identity": entityWatchLiftSupport, "studio": entityWatchLiftSupport,
	} {
		if weight > 0 {
			weights[family] = weight
		}
	}
	if len(weights) == 0 {
		return terms, nil
	}
	watched := map[string]bool{}
	rows, err := db.Query(`SELECT DISTINCT scene_id FROM source_play`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		if _, ok := sceneFeatures[sceneID]; ok {
			watched[sceneID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(watched) == 0 {
		return terms, nil
	}
	library := map[string]int{}
	chosen := map[string]int{}
	familyOf := map[string]string{}
	for sceneID, features := range sceneFeatures {
		seen := map[string]bool{}
		for _, feature := range features {
			if _, lifted := weights[feature.family]; !lifted || seen[feature.featureID] {
				continue
			}
			seen[feature.featureID] = true
			familyOf[feature.featureID] = feature.family
			library[feature.featureID]++
			if watched[sceneID] {
				chosen[feature.featureID]++
			}
		}
	}
	total, watchedCount := float64(len(sceneFeatures)), float64(len(watched))
	for _, featureID := range sortedStringKeys(library) {
		base := float64(library[featureID]) / total
		withTag := float64(chosen[featureID])
		lift := math.Log(((withTag + watchLiftShrink*base) / (watchedCount + watchLiftShrink)) / base)
		mass := math.Max(withTag, watchedCount*base)
		pseudo := weights[familyOf[featureID]] * mass / (mass + watchLiftShrink)
		terms[featureID] = watchLiftTerm{support: pseudo, numerator: pseudo * math.Tanh(lift)}
	}
	return terms, nil
}

// sceneReasonSupport mirrors ModelConfig.scene_reason_support.
const sceneReasonSupport = 2.0

// modelSceneReasons mirrors PreferenceModelBuilder._scene_reason_evidence:
// each Why these? subject adds sceneReasonSupport pseudo-observations at the
// answer's polarity to its tag, performer, or studio feature; a missing tag
// counts as that tag, and the scene itself carries nothing.
func modelSceneReasons(db dbx, sceneFeatures map[string][]storedFeature) (map[string]watchLiftTerm, error) {
	terms := map[string]watchLiftTerm{}
	if sceneReasonSupport <= 0 {
		return terms, nil
	}
	subjects := map[[2]string]string{}
	for _, features := range sceneFeatures {
		for _, feature := range features {
			switch feature.family {
			case "content":
				if tagID := feature.metadata.get("tag_id").asString(); tagID != "" {
					subjects[[2]string{"tag", tagID}] = feature.featureID
				}
			case "performer_identity":
				subjects[[2]string{"performer", strings.TrimPrefix(feature.name, "performer:")}] = feature.featureID
			case "studio":
				subjects[[2]string{"studio", strings.TrimPrefix(feature.name, "studio:")}] = feature.featureID
			}
		}
	}
	rows, err := db.Query(`
SELECT r.subject_type, r.subject_id, a.polarity
FROM scene_reason r JOIN scene_reason_answer a ON a.answer_id=r.answer_id
ORDER BY a.occurred_at_ms, a.answer_id, r.subject_type, r.subject_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var kind, subjectID string
		var polarity int64
		if err := rows.Scan(&kind, &subjectID, &polarity); err != nil {
			return nil, err
		}
		if kind == "missing_tag" {
			kind = "tag"
		}
		featureID, ok := subjects[[2]string{kind, subjectID}]
		if !ok {
			continue
		}
		term := terms[featureID]
		terms[featureID] = watchLiftTerm{
			support:   term.support + sceneReasonSupport,
			numerator: term.numerator + sceneReasonSupport*float64(polarity),
		}
	}
	return terms, rows.Err()
}

// inheritedSupport is half a direct answer: an unanswered tag takes its nearest
// answered ancestors' mean answer as a weaker prior. A replay on real answers
// found a parent's answer predicts a child's far better than learned history.
const inheritedSupport = 4.0

// inheritTagPreferences mirrors PreferenceModelBuilder._inherit_tag_preferences.
// Only tags without their own answer inherit, from the nearest generation of
// ancestors holding any non-Never answer.
func inheritTagPreferences(db dbx, tagFeatures map[string]string, result map[string]modelAffinity) error {
	answers := map[string]float64{}
	answered := map[string]bool{}
	rows, err := db.Query(`SELECT tag_id, value, blocked FROM direct_tag_preference ORDER BY tag_id`)
	if err != nil {
		return err
	}
	for rows.Next() {
		var tagID string
		var value float64
		var blocked int64
		if err := rows.Scan(&tagID, &value, &blocked); err != nil {
			rows.Close()
			return err
		}
		answered[tagID] = true
		if blocked == 0 {
			answers[tagID] = value
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if len(answers) == 0 {
		return nil
	}
	parents := map[string][]string{}
	rows, err = db.Query(`SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id`)
	if err != nil {
		return err
	}
	for rows.Next() {
		var tagID, parentTagID string
		if err := rows.Scan(&tagID, &parentTagID); err != nil {
			rows.Close()
			return err
		}
		parents[tagID] = append(parents[tagID], parentTagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, tagID := range sortedStringKeys(tagFeatures) {
		if answered[tagID] || len(parents[tagID]) == 0 {
			continue
		}
		seen := map[string]bool{tagID: true}
		frontier := parents[tagID]
		var sources []string
		for len(frontier) > 0 && len(sources) == 0 {
			var next []string
			for _, parentTagID := range frontier {
				if seen[parentTagID] {
					continue
				}
				seen[parentTagID] = true
				if _, ok := answers[parentTagID]; ok {
					sources = append(sources, parentTagID)
				}
				next = append(next, parents[parentTagID]...)
			}
			frontier = next
		}
		if len(sources) == 0 {
			continue
		}
		sort.Strings(sources)
		var total float64
		for _, source := range sources {
			total += answers[source]
		}
		inherited := total / float64(len(sources))
		featureID := tagFeatures[tagID]
		learned, exists := result[featureID]
		if !exists {
			learned = modelAffinity{featureID: featureID}
		}
		contextJSON := jvObj()
		for _, pair := range learned.contexts.obj {
			contextJSON.set(pair.key, pair.val)
		}
		from := jvArr()
		for _, source := range sources {
			from.arr = append(from.arr, jvStr(source))
		}
		contextJSON.set("inherited_preference", jvFloat(inherited))
		contextJSON.set("inherited_from", from)
		contextJSON.set("learned_affinity", jvFloat(learned.affinity))
		contextJSON.set("learned_confidence", jvFloat(learned.confidence))
		result[featureID] = modelAffinity{
			featureID: featureID,
			affinity: clamp((learned.affinity*learned.support + inherited*inheritedSupport) /
				(learned.support + inheritedSupport)),
			confidence: math.Max(learned.confidence, 0.6),
			support:    learned.support + inheritedSupport,
			sceneCount: learned.sceneCount,
			contexts:   contextJSON,
		}
	}
	return nil
}

// The content-neighbors kernel builds its own vectors; scoring only needs
// the number of learned content dimensions from _preference_content_vectors.
func preferenceContentDimensions(sceneFeatures map[string][]storedFeature, affinities map[string]modelAffinity) int {
	strengths := map[string]float64{}
	for _, sceneID := range sortedStringKeys(sceneFeatures) {
		for _, feature := range sceneFeatures[sceneID] {
			if feature.family != "content" {
				continue
			}
			if _, seen := strengths[feature.name]; seen {
				continue
			}
			var learnedAffinity, learnedConfidence float64
			if affinity, ok := affinities[feature.featureID]; ok {
				learnedAffinity = affinity.affinity
				if v := affinity.contexts.get("learned_affinity"); v.kind != jNull {
					learnedAffinity = numberValue(v)
				}
				learnedConfidence = affinity.confidence
				if v := affinity.contexts.get("learned_confidence"); v.kind != jNull {
					learnedConfidence = numberValue(v)
				}
			}
			strengths[feature.name] = math.Max(0, learnedAffinity) * learnedConfidence
		}
	}
	discriminative := 0
	for _, strength := range strengths {
		if strength > 0 {
			discriminative++
		}
	}
	return discriminative
}

func copysign(x, y float64) float64 {
	if y < 0 || (y == 0 && math.Signbit(y)) {
		return -math.Abs(x)
	}
	return math.Abs(x)
}

// numberValue mirrors _number: float for numeric values, else 0.0.
func numberValue(v jVal) float64 {
	if v.kind == jNum {
		f, err := pythonFloat(v)
		if err != nil {
			return 0
		}
		return f
	}
	return 0.0
}

// sceneContentVectorsAll mirrors FeatureStore.scene_content_vectors for all
// scenes.
func sceneContentVectorsAll(db dbx, featureVersion string) (map[string]map[string]float64, error) {
	rows, err := db.Query(`
SELECT ef.entity_id, fd.name, ef.value
FROM entity_feature ef JOIN feature_definition fd ON fd.feature_id = ef.feature_id
WHERE ef.feature_version = ? AND ef.entity_type = 'scene' AND fd.family = 'content'
ORDER BY ef.entity_id, fd.name`, featureVersion)
	if err != nil {
		return nil, err
	}
	result := map[string]map[string]float64{}
	for rows.Next() {
		var entityID, name string
		var value float64
		if err := rows.Scan(&entityID, &name, &value); err != nil {
			rows.Close()
			return nil, err
		}
		if result[entityID] == nil {
			result[entityID] = map[string]float64{}
		}
		result[entityID][name] = value
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// runCoreKernel invokes this binary's kernel stage with the payload JSON and
// returns the {"result": ...} value (mirroring curator.core.run_core). When a
// trace is active the payload already carries profile: true (modelbuild2.go),
// so the kernel emits {"span": ...} NDJSON lines; fold them into the trace as
// "core"-category spans, converting the kernel's process-relative offsets
// back from the spawn point (curator/core.py parity).
func runCoreKernel(mode string, payload jVal) (jVal, error) {
	exe, err := os.Executable()
	if err != nil {
		return jvNull(), err
	}
	cmd := exec.Command(exe, mode)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return jvNull(), err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return jvNull(), err
	}
	cmd.Stderr = os.Stderr
	spawnStartedNs := time.Now().UnixNano()
	if err := cmd.Start(); err != nil {
		return jvNull(), err
	}
	if _, err := stdin.Write([]byte(payload.marshalCompact())); err != nil {
		return jvNull(), err
	}
	stdin.Close()
	var result jVal = jvNull()
	scanner := bufio.NewScanner(stdout)
	// The scoring kernel's result line holds per-scene payloads and can
	// exceed the 64 KiB default token limit on large libraries.
	scanner.Buffer(make([]byte, 0, 1<<20), 256<<20)
	for scanner.Scan() {
		line := scanner.Bytes()
		parsed, err := parseJSON(line)
		if err != nil {
			continue
		}
		if v := parsed.get("result"); v.kind != jNull {
			result = v
		}
		if v := parsed.get("span"); v.kind != jNull {
			if t := currentTrace(); t != nil {
				name := v.get("name").asString()
				offsetUs := numberValue(v.get("offset_us"))
				durUs := numberValue(v.get("dur_us"))
				t.record("core", name, spawnStartedNs+int64(offsetUs)*1000, int64(durUs)*1000, jvNull())
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return jvNull(), err
	}
	if err := cmd.Wait(); err != nil {
		return jvNull(), fmt.Errorf("compiled core failed (%s, exit %v)", mode, err)
	}
	return result, nil
}

// neighborEvidence mirrors _neighbor_evidence.
type neighborEvidence struct {
	value       float64
	outcomeMean float64
	lift        float64
	confidence  float64
	totalWeight float64
	neighbors   []jVal
}

type neighborTuple struct {
	sceneID    string
	similarity float64
	weight     float64
	outcome    float64
}

func deriveNeighborEvidence(selected []neighborTuple, labelMean, confidenceScale float64) neighborEvidence {
	var denominator float64
	for _, item := range selected {
		denominator += item.weight
	}
	outcomeMean := 0.0
	if denominator != 0 {
		var weighted float64
		for _, item := range selected {
			weighted += item.weight * item.outcome
		}
		outcomeMean = weighted / denominator
	}
	lift := 0.0
	if denominator != 0 {
		lift = outcomeMean - labelMean
	}
	confidence := 0.0
	if denominator != 0 {
		confidence = 1 - math.Exp(-denominator/confidenceScale)
	}
	var neighbors []jVal
	for _, item := range selected {
		if len(neighbors) >= 5 {
			break
		}
		neighbors = append(neighbors, jvObj(
			jvKey("scene_id", jvStr(item.sceneID)),
			jvKey("similarity", jvFloat(item.similarity)),
			jvKey("weight", jvFloat(item.weight)),
			jvKey("outcome", jvFloat(item.outcome)),
		))
	}
	return neighborEvidence{
		value:       lift * confidence,
		outcomeMean: outcomeMean,
		lift:        lift,
		confidence:  confidence,
		totalWeight: denominator,
		neighbors:   neighbors,
	}
}

// modelSiblingPriors mirrors PreferenceModelBuilder._sibling_priors: a tag's
// prior is the support-weighted mean of its siblings' unsmoothed affinities,
// itself excluded. Tags with no parent, and tags whose siblings carry no
// support, are absent and keep the previous zero prior.
func modelSiblingPriors(
	db dbx,
	sceneFeatures map[string][]storedFeature,
	supports, numerators map[string]float64,
) (map[string]float64, error) {
	priors := map[string]float64{}
	if affinitySiblingPrior <= 0 {
		return priors, nil
	}
	featureOfTag := map[string]string{}
	for _, features := range sceneFeatures {
		for _, feature := range features {
			if feature.family != "content" {
				continue
			}
			if tagID := feature.metadata.get("tag_id").asString(); tagID != "" {
				if _, seen := featureOfTag[tagID]; !seen {
					featureOfTag[tagID] = feature.featureID
				}
			}
		}
	}
	if len(featureOfTag) == 0 {
		return priors, nil
	}
	parents := map[string][]string{}
	children := map[string][]string{}
	rows, err := db.Query(`SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, parentTagID string
		if err := rows.Scan(&tagID, &parentTagID); err != nil {
			rows.Close()
			return nil, err
		}
		parents[tagID] = append(parents[tagID], parentTagID)
		children[parentTagID] = append(children[parentTagID], tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	tagIDs := make([]string, 0, len(parents))
	for tagID := range parents {
		tagIDs = append(tagIDs, tagID)
	}
	sort.Strings(tagIDs)
	for _, tagID := range tagIDs {
		featureID, ok := featureOfTag[tagID]
		if !ok {
			continue
		}
		siblingSet := map[string]bool{}
		for _, parentTagID := range parents[tagID] {
			for _, sibling := range children[parentTagID] {
				if sibling != tagID {
					siblingSet[sibling] = true
				}
			}
		}
		siblings := make([]string, 0, len(siblingSet))
		for sibling := range siblingSet {
			siblings = append(siblings, sibling)
		}
		// sort: these feed floating-point sums that must stay byte-identical
		// run to run and against the Python oracle.
		sort.Strings(siblings)
		weight := 0.0
		total := 0.0
		for _, sibling := range siblings {
			siblingFeature, ok := featureOfTag[sibling]
			if !ok {
				continue
			}
			support := supports[siblingFeature]
			if support <= 0 {
				continue
			}
			affinity := numerators[siblingFeature] / (affinityPrior + support)
			total += affinity * support
			weight += support
		}
		if weight > 0 {
			priors[featureID] = total / weight
		}
	}
	return priors, nil
}
