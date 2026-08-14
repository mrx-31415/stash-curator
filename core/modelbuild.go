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
	"strconv"
	"strings"
	"time"
)

const (
	performerSimilarityAffinityCutoff = 0.005
	modelBuildVersion                 = 4
)

// sceneLabel mirrors _SceneLabel.
type sceneLabel struct {
	outcome           float64
	confidence        float64
	effectiveEvidence float64
	signalTypes       []string
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

// clamp mirrors _clamp.
func clamp(value float64) float64 {
	return clampValue(value, -1, 1)
}

// modelSceneLabels mirrors PreferenceModelBuilder._scene_labels.
func modelSceneLabels(db dbx) (map[string]sceneLabel, error) {
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
		return nil, err
	}
	for rows.Next() {
		var sceneID, eventType, payloadJSON string
		var outcome, confidence float64
		if err := rows.Scan(&sceneID, &eventType, &outcome, &confidence, &payloadJSON); err != nil {
			rows.Close()
			return nil, err
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
		return nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, feedback_type, occurred_at_ms FROM feedback
WHERE reversed_by_id IS NULL AND feedback_type IN ('thumb_up', 'thumb_down')
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, feedbackType string
		var occurredAtMs int64
		if err := rows.Scan(&sceneID, &feedbackType, &occurredAtMs); err != nil {
			rows.Close()
			return nil, err
		}
		value := -1.0
		if feedbackType == "thumb_up" {
			value = 0.90
		}
		signals[sceneID] = append(signals[sceneID], signal{value, 1.0, feedbackType})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, value FROM feedback
WHERE reversed_by_id IS NULL AND feedback_type='curation_rating'
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var value sql.NullString
		if err := rows.Scan(&sceneID, &value); err != nil {
			rows.Close()
			return nil, err
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
		return nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, feedback_type, payload_json FROM feedback
WHERE reversed_by_id IS NULL
  AND feedback_type IN ('curation_pair_winner', 'curation_pair_loser')
ORDER BY scene_id, occurred_at_ms`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, feedbackType, payloadJSON string
		if err := rows.Scan(&sceneID, &feedbackType, &payloadJSON); err != nil {
			rows.Close()
			return nil, err
		}
		payload, parseErr := parseJSON([]byte(payloadJSON))
		if parseErr != nil {
			continue
		}
		selectionProbability := pythonFloatValue(payload.get("selection_probability"))
		if selectionProbability <= 0 {
			selectionProbability = 1.0
		}
		if selectionProbability > 1 {
			continue
		}
		predictedWinner := pythonFloatValue(payload.get("predicted_winner"))
		predictedLoser := pythonFloatValue(payload.get("predicted_loser"))
		isWinner := feedbackType == "curation_pair_winner"
		surprise := predictedLoser - predictedWinner
		if surprise < 0 {
			surprise = 0
		}
		confidence := 0.50 * (1.0 + 2.0*surprise) * math.Min(4.0, 1.0/selectionProbability)
		if confidence > 1.0 {
			confidence = 1.0
		}
		value := -1.0
		if isWinner {
			value = 1.0
		}
		signals[sceneID] = append(signals[sceneID], signal{value, confidence, feedbackType})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, rating100 FROM source_scene WHERE rating100 IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var rating100 int64
		if err := rows.Scan(&sceneID, &rating100); err != nil {
			rows.Close()
			return nil, err
		}
		signals[sceneID] = append(signals[sceneID], signal{
			clamp((float64(rating100) - 50) / 50), 0.90, "scene_rating",
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	labels := map[string]sceneLabel{}
	for sceneID, sceneSignals := range signals {
		confidences := make([]float64, 0, len(sceneSignals))
		products := make([]float64, 0, len(sceneSignals))
		for _, item := range sceneSignals {
			confidences = append(confidences, item.confidence)
			products = append(products, item.value*item.confidence)
		}
		evidence := sumFloats(confidences)
		if evidence <= 0 {
			continue
		}
		weighted := sumFloats(products)
		types := make([]string, 0, len(sceneSignals))
		for _, item := range sceneSignals {
			types = append(types, item.signalType)
		}
		labels[sceneID] = sceneLabel{
			outcome:           clamp(weighted / evidence),
			confidence:        1 - math.Exp(-evidence),
			effectiveEvidence: evidence,
			signalTypes:       types,
		}
	}
	return labels, nil
}

// modelTrainingLabels mirrors _training_labels.
func modelTrainingLabels(db dbx, labels map[string]sceneLabel) (map[string]sceneLabel, error) {
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
	result := map[string]sceneLabel{}
	for sceneID, label := range labels {
		if !metadataWrong[sceneID] {
			result[sceneID] = label
		}
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
	doc := jvObj(
		jvKey("labels", labelRows),
		jvKey("feedback", feedbackState),
		jvKey("exclusions", exclusions),
		jvKey("pruning", pruning),
		jvKey("tag_preferences", tagPreferences),
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
	for rows.Next() {
		var entityID, featureID, family, name string
		var value, confidence float64
		var metadataJSON string
		if err := rows.Scan(&entityID, &featureID, &family, &name, &value, &confidence, &metadataJSON); err != nil {
			rows.Close()
			return nil, err
		}
		metadata := jvObj()
		if parsed, err := parseJSON([]byte(metadataJSON)); err == nil {
			metadata = parsed
		}
		result[entityID] = append(result[entityID], storedFeature{
			featureID: featureID, family: family, name: name,
			value: value, confidence: confidence, metadata: metadata,
		})
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

// modelAffinities mirrors _affinities.
func modelAffinities(db dbx, sceneFeatures map[string][]storedFeature,
	labels map[string]sceneLabel, labelMean float64) (map[string]modelAffinity, error) {
	type accumulator struct {
		sceneID string
		weight  float64
		outcome float64
	}
	accumulators := map[string][]accumulator{}
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		for _, feature := range sceneFeatures[sceneID] {
			weight := label.confidence * feature.confidence * math.Abs(feature.value)
			accumulators[feature.featureID] = append(accumulators[feature.featureID], accumulator{
				sceneID: sceneID,
				weight:  weight,
				outcome: (label.outcome - labelMean) * copysign(1, feature.value),
			})
		}
	}
	contexts, err := modelSceneContexts(db)
	if err != nil {
		return nil, err
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
		support := sumFloats(weights)
		numerator := sumFloats(weightedOutcomes)
		affinity := numerator / (1.0 + support)
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
	termFeatures := map[string]string{}
	for _, features := range sceneFeatures {
		for _, feature := range features {
			if feature.family == "content" && strings.HasPrefix(feature.name, "desc:") {
				termFeatures[strings.TrimPrefix(feature.name, "desc:")] = feature.featureID
			}
		}
	}
	termRows, err := db.Query(`SELECT term, value FROM direct_term_preference ORDER BY term`)
	if err != nil {
		return nil, err
	}
	for termRows.Next() {
		var term string
		var directValue float64
		if err := termRows.Scan(&term, &directValue); err != nil {
			termRows.Close()
			return nil, err
		}
		featureID, ok := termFeatures[term]
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
	termRows.Close()
	if err := termRows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// preferenceContentVectors mirrors _preference_content_vectors.
func preferenceContentVectors(vectors map[string]map[string]float64,
	sceneFeatures map[string][]storedFeature, affinities map[string]modelAffinity) (map[string]map[string]float64, int) {
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
	maximum := 0.0
	for _, strength := range strengths {
		if strength > maximum {
			maximum = strength
		}
	}
	const generic = 0.0
	weighted := map[string]map[string]float64{}
	discriminative := 0
	for _, strength := range strengths {
		if strength > 0 {
			discriminative++
		}
	}
	for sceneID, vector := range vectors {
		values := map[string]float64{}
		for name, value := range vector {
			multiplier := 1.0
			if maximum > 0 {
				multiplier = generic + (1-generic)*strengths[name]/maximum
			}
			if multiplier > 1e-9 {
				values[name] = value * multiplier
			}
		}
		var normSquared float64
		for _, value := range values {
			normSquared += value * value
		}
		norm := math.Sqrt(normSquared)
		if norm == 0 {
			norm = 1.0
		}
		normalized := map[string]float64{}
		for name, value := range values {
			normalized[name] = value / norm
		}
		weighted[sceneID] = normalized
	}
	return weighted, discriminative
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
