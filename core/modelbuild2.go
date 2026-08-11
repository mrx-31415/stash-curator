// Model build back half — the scoring loop, kernel invocation, publication,
// and the coordinator drain, continuing core/modelbuild.go's labels/
// affinities port. The published model artifact tables are the oracle.
package main

import (
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
)

// buildModelScore mirrors _Score.
type buildModelScore struct {
	sceneID            string
	generalAppeal      float64
	directAppeal       float64
	directConfidence   float64
	appeal             float64
	currentFit         float64
	confidence         float64
	metadataConfidence float64
	recovery           float64
	components         jVal
	neighbors          []jVal
	eligibility        jVal
}

// featureArtifactPath mirrors _feature_artifact_path.
func featureArtifactPath(db dbx, featureVersion string) (string, error) {
	var basename sql.NullString
	err := db.QueryRow(`
SELECT artifact_basename FROM feature_build
WHERE feature_version=? AND validation_status='valid'`, featureVersion).Scan(&basename)
	if err != nil || !basename.Valid || basename.String == "" {
		return "", fmt.Errorf("feature artifact missing for %s", featureVersion)
	}
	core, err := coreDatabasePath(db)
	if err != nil {
		return "", err
	}
	return artifactPath(core, basename.String)
}

// directConfidenceOf mirrors curves.direct_confidence.
func directConfidenceOf(effectiveEvidence float64) float64 {
	if effectiveEvidence < 0 || math.IsInf(effectiveEvidence, 0) || math.IsNaN(effectiveEvidence) {
		return 0
	}
	return 1 - math.Exp(-effectiveEvidence/0.8)
}

// blendAppealOf mirrors curves.blend_appeal.
func blendAppealOf(general, direct, confidence float64) float64 {
	return clampValue((1-confidence)*general+confidence*direct, -1, 1)
}

// contentNeighbors invokes the content-neighbors kernel and derives the
// per-scene evidence (mirroring _content_neighbors).
func contentNeighbors(db dbx, featureVersion string, affinities map[string]modelAffinity,
	labels map[string]sceneLabel, labelMean float64, progressTotal int,
	report func(fraction float64)) (map[string]neighborEvidence, error) {
	artifactPath, err := featureArtifactPath(db, featureVersion)
	if err != nil {
		return nil, err
	}
	affinityPayload := jvObj()
	for _, featureID := range sortedStringKeys(affinities) {
		affinity := affinities[featureID]
		entry := jvObj(
			jvKey("affinity", jvFloat(affinity.affinity)),
			jvKey("confidence", jvFloat(affinity.confidence)),
		)
		for _, key := range []string{"learned_affinity", "learned_confidence"} {
			if v := affinity.contexts.get(key); v.kind != jNull {
				entry.set(key, jvFloat(numberValue(v)))
			}
		}
		affinityPayload.set(featureID, entry)
	}
	labelsPayload := jvObj()
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		labelsPayload.set(sceneID, jvArr(jvFloat(label.outcome), jvFloat(label.confidence)))
	}
	payload := jvObj(
		jvKey("db", jvStr(artifactPath)),
		jvKey("feature_version", jvStr(featureVersion)),
		jvKey("labels", labelsPayload),
		jvKey("label_mean", jvFloat(labelMean)),
		jvKey("affinities", affinityPayload),
		jvKey("config", jvObj(
			jvKey("min_similarity", jvFloat(0.05)),
			jvKey("neighbor_count", jvInt(12)),
			jvKey("confidence_scale", jvFloat(0.35)),
			jvKey("generic_weight", jvFloat(0.0)),
		)),
		jvKey("progress_total", jvInt(int64(progressTotal))),
	)
	if currentTrace() != nil {
		payload.set("profile", jvBool(true))
	}
	response, err := runCoreKernel("content-neighbors", payload)
	if err != nil {
		return nil, err
	}
	result := map[string]neighborEvidence{}
	for _, pair := range response.obj {
		neighbors := pair.val.get("neighbors")
		var selected []neighborTuple
		for _, raw := range neighbors.arr {
			if len(raw.arr) < 4 {
				continue
			}
			selected = append(selected, neighborTuple{
				sceneID:    raw.arr[0].asString(),
				similarity: numberValue(raw.arr[1]),
				weight:     numberValue(raw.arr[2]),
				outcome:    numberValue(raw.arr[3]),
			})
		}
		if len(selected) == 0 {
			result[pair.key] = neighborEvidence{}
			continue
		}
		result[pair.key] = deriveNeighborEvidence(selected, labelMean, 0.35)
	}
	return result, nil
}

// performerSimilarityScores invokes the performer-similarity kernel
// (mirroring _performer_similarity_scores).
func modelPerformerSimilarityScores(db dbx, featureVersion string,
	sceneFeatures map[string][]storedFeature, affinities map[string]modelAffinity) (jVal, error) {
	artifactPath, err := featureArtifactPath(db, featureVersion)
	if err != nil {
		return jvNull(), err
	}
	identityAffinity := map[string][2]float64{}
	for _, features := range sceneFeatures {
		for _, feature := range features {
			if feature.family != "performer_identity" {
				continue
			}
			if affinity, ok := affinities[feature.featureID]; ok {
				identityAffinity[strings.TrimPrefix(feature.name, "performer:")] = [2]float64{
					affinity.affinity * affinity.confidence, affinity.confidence,
				}
			}
		}
	}
	identityPayload := jvObj()
	for _, performerID := range sortedStringKeys(identityAffinity) {
		values := identityAffinity[performerID]
		identityPayload.set(performerID, jvArr(jvFloat(values[0]), jvFloat(values[1])))
	}
	blockWeights := jvObj()
	for _, item := range performerBlockWeights {
		blockWeights.set(item.block, jvFloat(item.weight))
	}
	numericScalesObj := jvObj()
	for key, value := range numericScales {
		numericScalesObj.set(key, jvFloat(value))
	}
	numericBlocks := jvArr()
	for _, block := range []string{"age", "height", "measurements"} {
		numericBlocks.arr = append(numericBlocks.arr, jvStr(block))
	}
	payload := jvObj(
		jvKey("db", jvStr(artifactPath)),
		jvKey("feature_version", jvStr(featureVersion)),
		jvKey("identity_affinity", identityPayload),
		jvKey("block_weights", blockWeights),
		jvKey("cutoff", jvFloat(performerSimilarityAffinityCutoff)),
		jvKey("numeric_blocks", numericBlocks),
		jvKey("numeric_scales", numericScalesObj),
	)
	if currentTrace() != nil {
		payload.set("profile", jvBool(true))
	}
	return runCoreKernel("performer-similarity", payload)
}

// performerProfileIDs reads the performer ids present in the feature artifact
// (FeatureStore.performer_profiles membership for metadata_confidence).
func performerProfileIDs(db dbx, featureVersion string) (map[string]bool, error) {
	rows, err := db.Query(`
SELECT DISTINCT entity_id FROM entity_feature
WHERE feature_version=? AND entity_type='performer'`, featureVersion)
	if err != nil {
		return nil, err
	}
	result := map[string]bool{}
	for rows.Next() {
		var entityID string
		if err := rows.Scan(&entityID); err != nil {
			rows.Close()
			return nil, err
		}
		result[entityID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// modelPrior mirrors _Prior.
type modelPrior struct {
	value      float64
	confidence float64
}

// performerPriors mirrors _performer_priors.
func performerPriors(db dbx) (map[string]modelPrior, error) {
	rows, err := db.Query(`SELECT performer_id, favorite, rating100 FROM source_performer`)
	if err != nil {
		return nil, err
	}
	result := map[string]modelPrior{}
	for rows.Next() {
		var performerID string
		var favorite int64
		var rating100 sql.NullInt64
		if err := rows.Scan(&performerID, &favorite, &rating100); err != nil {
			rows.Close()
			return nil, err
		}
		prior := 0.0
		if favorite != 0 {
			prior = 0.18
		}
		confidence := 0.0
		if rating100.Valid {
			prior += clamp((float64(rating100.Int64)-50)/50) * 0.10
			confidence = 0.75
		}
		if favorite != 0 {
			confidence = 0.90
		}
		result[performerID] = modelPrior{prior, confidence}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// studioPriors mirrors _studio_priors.
func studioPriors(db dbx) (map[string]modelPrior, error) {
	rows, err := db.Query(`SELECT studio_id FROM source_studio WHERE favorite=1`)
	if err != nil {
		return nil, err
	}
	result := map[string]modelPrior{}
	for rows.Next() {
		var studioID string
		if err := rows.Scan(&studioID); err != nil {
			rows.Close()
			return nil, err
		}
		result[studioID] = modelPrior{0.04, 0.70}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// asymmetric mirrors _asymmetric.
func asymmetric(values []float64) float64 {
	var positives []float64
	var negatives []float64
	for _, value := range values {
		if value > 0 {
			positives = append(positives, value)
		} else if value < 0 {
			negatives = append(negatives, value)
		}
	}
	sort.Sort(sort.Reverse(sort.Float64Slice(positives)))
	positive := 0.0
	if len(positives) > 0 {
		positive = positives[0]
		positive += 0.25 * sumFloats(positives[1:])
	}
	friction := 0.0
	if len(negatives) > 0 {
		friction = 0.25 * sumFloats(negatives) / float64(len(negatives))
	}
	return positive + friction
}

// recentContext mirrors _recent_context.
type recentContext struct {
	reference       int64
	performers      map[string]int64
	studios         map[string]int64
	scenePerformers map[string][]string
	sceneStudios    map[string]string
	notNow          map[string]int64
	recentByName    map[string][]struct {
		index int
		value float64
	}
	recentSceneIDs []string
	recentPlayed   []int64
	sceneVectors   map[string]map[string]float64
}

func buildRecentContext(db dbx, referenceAtMs int64, vectors map[string]map[string]float64) (*recentContext, error) {
	context := &recentContext{
		reference:       referenceAtMs,
		performers:      map[string]int64{},
		studios:         map[string]int64{},
		scenePerformers: map[string][]string{},
		sceneStudios:    map[string]string{},
		notNow:          map[string]int64{},
		recentByName: map[string][]struct {
			index int
			value float64
		}{},
		sceneVectors: vectors,
	}
	rows, err := db.Query(`SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, performerID string
		if err := rows.Scan(&sceneID, &performerID); err != nil {
			rows.Close()
			return nil, err
		}
		context.scenePerformers[sceneID] = append(context.scenePerformers[sceneID], performerID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, studioID string
		if err := rows.Scan(&sceneID, &studioID); err != nil {
			rows.Close()
			return nil, err
		}
		context.sceneStudios[sceneID] = studioID
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`
SELECT scene_id, max(occurred_at_ms) AS occurred_at_ms FROM feedback
WHERE feedback_type='not_now' AND reversed_by_id IS NULL GROUP BY scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var occurredAtMs int64
		if err := rows.Scan(&sceneID, &occurredAtMs); err != nil {
			rows.Close()
			return nil, err
		}
		context.notNow[sceneID] = occurredAtMs
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	cutoff := referenceAtMs - 30*86_400_000
	rows, err = db.Query(`
SELECT p.scene_id, max(p.played_at_ms) AS played_at, s.studio_id
FROM source_play p JOIN source_scene s ON s.scene_id=p.scene_id
WHERE p.played_at_ms >= ? GROUP BY p.scene_id ORDER BY played_at DESC LIMIT 200`, cutoff)
	if err != nil {
		return nil, err
	}
	type playRow struct {
		sceneID  string
		playedAt int64
		studioID string
	}
	var playRows []playRow
	for rows.Next() {
		var sceneID string
		var playedAt int64
		var studioID sql.NullString
		if err := rows.Scan(&sceneID, &playedAt, &studioID); err != nil {
			rows.Close()
			return nil, err
		}
		playRows = append(playRows, playRow{sceneID, playedAt, studioID.String})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, row := range playRows {
		if row.studioID != "" {
			if current, ok := context.studios[row.studioID]; !ok || row.playedAt > current {
				context.studios[row.studioID] = row.playedAt
			}
		}
		for _, performerID := range context.scenePerformers[row.sceneID] {
			if current, ok := context.performers[performerID]; !ok || row.playedAt > current {
				context.performers[performerID] = row.playedAt
			}
		}
		if vector, ok := vectors[row.sceneID]; ok {
			index := len(context.recentSceneIDs)
			context.recentSceneIDs = append(context.recentSceneIDs, row.sceneID)
			context.recentPlayed = append(context.recentPlayed, row.playedAt)
			for name, value := range vector {
				context.recentByName[name] = append(context.recentByName[name], struct {
					index int
					value float64
				}{index, value})
			}
		}
	}
	return context, nil
}

// satiation mirrors _satiation.
func satiation(db dbx, sceneID string, appeal float64, context *recentContext) float64 {
	if appeal <= 0 {
		return 0.0
	}
	reference := context.reference
	var performerPenalty float64
	for _, performerID := range context.scenePerformers[sceneID] {
		if timestamp, ok := context.performers[performerID]; ok {
			days := math.Max(0, float64(reference-timestamp)/86_400_000)
			if penalty := 0.06 * math.Exp(-days/7); penalty > performerPenalty {
				performerPenalty = penalty
			}
		}
	}
	var studioPenalty float64
	if studioID := context.sceneStudios[sceneID]; studioID != "" {
		if timestamp, ok := context.studios[studioID]; ok {
			days := math.Max(0, float64(reference-timestamp)/86_400_000)
			studioPenalty = 0.03 * math.Exp(-days/7)
		}
	}
	var contentPenalty float64
	candidate := context.sceneVectors[sceneID]
	if len(candidate) > 0 {
		dots := map[int]float64{}
		for name, value := range candidate {
			for _, entry := range context.recentByName[name] {
				dots[entry.index] += value * entry.value
			}
		}
		for index, cosine := range dots {
			if context.recentSceneIDs[index] == sceneID {
				continue
			}
			days := math.Max(0, float64(reference-context.recentPlayed[index])/86_400_000)
			if penalty := 0.04 * cosine * math.Exp(-days/7); penalty > contentPenalty {
				contentPenalty = penalty
			}
		}
	}
	return math.Min(0.12, appeal*(performerPenalty+studioPenalty+contentPenalty))
}

// notNowPenalty mirrors _not_now_penalty.
func notNowPenalty(sceneID string, referenceAtMs int64, context *recentContext) float64 {
	occurredAtMs, ok := context.notNow[sceneID]
	if !ok {
		return 0.0
	}
	ageDays := math.Max(0, float64(referenceAtMs-occurredAtMs)/86_400_000)
	if ageDays >= notNowDays {
		return 0.0
	}
	return 0.50 * (1 - ageDays/notNowDays)
}

// sceneEligibilityBuild mirrors scene_eligibility with include_temporary=False
// (the build never treats not_now as an exclusion).
func sceneEligibilityBuild(db dbx, referenceAtMs int64) (map[string]jVal, error) {
	allScenes := map[string]bool{}
	rows, err := db.Query(`SELECT scene_id FROM source_scene`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		if err := rows.Scan(&sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		allScenes[sceneID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	result, err := sceneEligibility(db, referenceAtMs, allScenes)
	if err != nil {
		return nil, err
	}
	out := map[string]jVal{}
	for sceneID, entry := range result {
		reasons := jvArr()
		for _, reason := range entry.reasons {
			if reason == "not_now" {
				continue
			}
			reasons.arr = append(reasons.arr, jvStr(reason))
		}
		out[sceneID] = jvObj(
			jvKey("eligible", jvBool(len(reasons.arr) == 0)),
			jvKey("reasons", reasons),
		)
	}
	return out, nil
}

// classificationPayload mirrors _classification_payload.
func classificationPayload(components jVal) jVal {
	payload := jvObj()
	for _, family := range []string{
		"content", "content_neighbor", "performer_identity",
		"performer_similarity", "studio", "structure",
	} {
		component := components.get(family)
		value := 0.0
		if component.kind == jObj {
			value = numberValue(component.get("value"))
		}
		payload.set(family, jvObj(jvKey("value", jvFloat(value))))
	}
	direct := components.get("direct")
	signals := jvArr()
	if direct.kind == jObj {
		for _, item := range direct.get("signals").arr {
			signals.arr = append(signals.arr, jvStr(item.asString()))
		}
	}
	payload.set("direct", jvObj(jvKey("signals", signals)))
	return payload
}

// edgeMatches mirrors _edge_matches.
func edgeMatches(entry jVal) ([]jVal, error) {
	matches := entry.get("matches")
	if matches.kind != jArr {
		return nil, fmt.Errorf("performer similarity result is missing matches")
	}
	return matches.arr, nil
}

// modelScores runs the scoring stage (mirroring _scores).
func buildModelScores(db dbx, featureVersion string, sceneFeatures map[string][]storedFeature,
	affinities map[string]modelAffinity, labels map[string]sceneLabel,
	trainingLabels map[string]sceneLabel, labelMean float64, referenceAtMs int64,
	report func(fraction float64)) ([]buildModelScore, jVal, error) {
	vectors, err := sceneContentVectorsAll(db, featureVersion)
	if err != nil {
		return nil, jvNull(), err
	}
	allSceneRows, err := db.Query(`SELECT scene_id FROM source_scene ORDER BY scene_id`)
	if err != nil {
		return nil, jvNull(), err
	}
	var allSceneIDs []string
	for allSceneRows.Next() {
		var sceneID string
		if err := allSceneRows.Scan(&sceneID); err != nil {
			allSceneRows.Close()
			return nil, jvNull(), err
		}
		allSceneIDs = append(allSceneIDs, sceneID)
	}
	allSceneRows.Close()
	if err := allSceneRows.Err(); err != nil {
		return nil, jvNull(), err
	}
	preferenceVectors, discriminative := preferenceContentVectors(vectors, sceneFeatures, affinities)
	progressTotal := len(preferenceVectors) + len(allSceneIDs)
	neighbors, err := contentNeighbors(db, featureVersion, affinities, trainingLabels,
		labelMean, progressTotal, report)
	if err != nil {
		return nil, jvNull(), err
	}
	performerSimilarity, err := modelPerformerSimilarityScores(db, featureVersion, sceneFeatures, affinities)
	if err != nil {
		return nil, jvNull(), err
	}
	baselineConfidences := make([]float64, 0, len(trainingLabels))
	for _, sceneID := range sortedStringKeys(trainingLabels) {
		baselineConfidences = append(baselineConfidences, trainingLabels[sceneID].confidence)
	}
	baselineSupport := sumFloats(baselineConfidences)
	baseline := labelMean * baselineSupport / (1.0 + baselineSupport)
	baseline = clampValue(baseline, -0.10, 0.10)
	lastPlayed := map[string]int64{}
	rows, err := db.Query(`SELECT scene_id, max(played_at_ms) AS last_played FROM source_play GROUP BY scene_id`)
	if err != nil {
		return nil, jvNull(), err
	}
	for rows.Next() {
		var sceneID string
		var lastPlayedMs int64
		if err := rows.Scan(&sceneID, &lastPlayedMs); err != nil {
			rows.Close()
			return nil, jvNull(), err
		}
		lastPlayed[sceneID] = lastPlayedMs
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, jvNull(), err
	}
	recentContext, err := buildRecentContext(db, referenceAtMs, vectors)
	if err != nil {
		return nil, jvNull(), err
	}
	eligibility, err := sceneEligibilityBuild(db, referenceAtMs)
	if err != nil {
		return nil, jvNull(), err
	}
	performerPriors, err := performerPriors(db)
	if err != nil {
		return nil, jvNull(), err
	}
	studioPriors, err := studioPriors(db)
	if err != nil {
		return nil, jvNull(), err
	}
	profiles, err := performerProfileIDs(db, featureVersion)
	if err != nil {
		return nil, jvNull(), err
	}
	var scores []buildModelScore
	totalScenes := len(allSceneIDs)
	for sceneIndex, sceneID := range allSceneIDs {
		features := sceneFeatures[sceneID]
		components := jvObj(jvKey("baseline", jvObj(
			jvKey("raw", jvFloat(baseline)),
			jvKey("value", jvFloat(baseline)),
			jvKey("training_outcome_mean", jvFloat(labelMean)),
			jvKey("effective_support", jvFloat(baselineSupport)),
		)))
		familyConfidences := map[string]float64{}
		for _, family := range []struct {
			name  string
			bound float64
		}{{"content", 0.35}, {"structure", 0.05}} {
			var contributions jVal = jvArr()
			for _, feature := range features {
				if feature.family != family.name {
					continue
				}
				affinity, ok := affinities[feature.featureID]
				if !ok {
					continue
				}
				value := feature.value * affinity.affinity * affinity.confidence
				contributions.arr = append(contributions.arr, jvObj(
					jvKey("feature_id", jvStr(feature.featureID)),
					jvKey("name", jvStr(feature.name)),
					jvKey("value", jvFloat(value)),
					jvKey("affinity", jvFloat(affinity.affinity)),
					jvKey("confidence", jvFloat(affinity.confidence)),
					jvKey("metadata", feature.metadata),
					jvKey("affinity_metadata", affinity.contexts),
				))
			}
			contributionValues := make([]float64, 0, len(contributions.arr))
			absValues := make([]float64, 0, len(contributions.arr))
			for _, item := range contributions.arr {
				value := numberValue(item.get("value"))
				contributionValues = append(contributionValues, value)
				absValues = append(absValues, math.Abs(value))
			}
			raw := sumFloats(contributionValues)
			contributionMass := sumFloats(absValues)
			var evidenceConfidence float64
			if contributionMass != 0 {
				weightedValues := make([]float64, 0, len(contributions.arr))
				for _, item := range contributions.arr {
					value := numberValue(item.get("value"))
					weightedValues = append(weightedValues, math.Abs(value)*numberValue(item.get("confidence")))
				}
				evidenceConfidence = sumFloats(weightedValues) / contributionMass
			}
			familyConfidences[family.name] = evidenceConfidence
			sorted := append([]jVal(nil), contributions.arr...)
			sort.SliceStable(sorted, func(i, j int) bool {
				a, b := sorted[i], sorted[j]
				absA, absB := math.Abs(numberValue(a.get("value"))), math.Abs(numberValue(b.get("value")))
				if absA != absB {
					return absA > absB
				}
				return a.get("name").asString() < b.get("name").asString()
			})
			if len(sorted) > 5 {
				sorted = sorted[:5]
			}
			top := jvArr(sorted...)
			if len(contributionValues) == 0 {
				components.set(family.name, jvObj(
					jvKey("raw", jvInt(0)),
					jvKey("value", jvInt(0)),
					jvKey("evidence_confidence", jvFloat(evidenceConfidence)),
					jvKey("top", top),
				))
			} else {
				components.set(family.name, jvObj(
					jvKey("raw", jvFloat(raw)),
					jvKey("value", jvFloat(clampValue(raw, -family.bound, family.bound))),
					jvKey("evidence_confidence", jvFloat(evidenceConfidence)),
					jvKey("top", top),
				))
			}
		}
		var performerItems []storedFeature
		for _, feature := range features {
			if feature.family == "performer_identity" {
				performerItems = append(performerItems, feature)
			}
		}
		identityValues := jvArr()
		similarityValues := jvArr()
		var identityRaw, similarityRaw, identityConfidence, similarityConfidence float64
		var identityValueList, similarityValueList []float64
		for _, feature := range performerItems {
			performerID := strings.TrimPrefix(feature.name, "performer:")
			affinity, hasAffinity := affinities[feature.featureID]
			learned := 0.0
			affinityConfidence := 0.0
			if hasAffinity {
				learned = affinity.affinity * affinity.confidence
				affinityConfidence = affinity.confidence
			}
			prior := performerPriors[performerID]
			identityValues.arr = append(identityValues.arr, jvObj(
				jvKey("performer_id", jvStr(performerID)),
				jvKey("value", jvFloat(learned+prior.value)),
				jvKey("learned", jvFloat(learned)),
				jvKey("prior", jvFloat(prior.value)),
				jvKey("confidence", jvFloat(math.Max(affinityConfidence, prior.confidence))),
			))
			identityConfidence = math.Max(identityConfidence, math.Max(affinityConfidence, prior.confidence))
			identityValueList = append(identityValueList, learned+prior.value)
			similarity := performerSimilarity.get(performerID)
			var simValue, simConfidence float64
			if similarity.kind == jObj {
				simValue = numberValue(similarity.get("value"))
				simConfidence = numberValue(similarity.get("confidence"))
			}
			noveltyWeight := math.Max(0.05, 1-identityConfidence)
			similarityItem := jvObj()
			for _, pair := range similarity.obj {
				similarityItem.set(pair.key, pair.val)
			}
			similarityItem.set("performer_id", jvStr(performerID))
			similarityItem.set("raw_value", jvFloat(simValue))
			similarityItem.set("value", jvFloat(simValue*noveltyWeight))
			similarityItem.set("confidence", jvFloat(simConfidence*noveltyWeight))
			similarityItem.set("identity_confidence", jvFloat(identityConfidence))
			similarityItem.set("novelty_weight", jvFloat(noveltyWeight))
			similarityValues.arr = append(similarityValues.arr, similarityItem)
			similarityValueList = append(similarityValueList, simValue*noveltyWeight)
			similarityConfidence = math.Max(similarityConfidence, simConfidence*noveltyWeight)
		}
		identityRaw = asymmetric(identityValueList)
		similarityRaw = asymmetric(similarityValueList)
		familyConfidences["performer_identity"] = identityConfidence
		familyConfidences["performer_similarity"] = similarityConfidence
		components.set("performer_identity", jvObj(
			jvKey("raw", jvFloat(identityRaw)),
			jvKey("value", jvFloat(clampValue(identityRaw, -0.30, 0.30))),
			jvKey("performers", identityValues),
			jvKey("evidence_confidence", jvFloat(identityConfidence)),
		))
		components.set("performer_similarity", jvObj(
			jvKey("raw", jvFloat(similarityRaw)),
			jvKey("value", jvFloat(clampValue(similarityRaw, -0.16, 0.16))),
			jvKey("performers", similarityValues),
			jvKey("evidence_confidence", jvFloat(similarityConfidence)),
		))
		var studioItems jVal = jvArr()
		var studioConfidence float64
		for _, feature := range features {
			if feature.family != "studio" {
				continue
			}
			studioID := strings.TrimPrefix(feature.name, "studio:")
			affinity, hasAffinity := affinities[feature.featureID]
			learned := 0.0
			affinityConfidence := 0.0
			if hasAffinity {
				learned = affinity.affinity * affinity.confidence
				affinityConfidence = affinity.confidence
			}
			prior := studioPriors[studioID]
			value := learned + prior.value
			confidence := math.Max(affinityConfidence, prior.confidence)
			studioItems.arr = append(studioItems.arr, jvObj(
				jvKey("studio_id", jvStr(studioID)),
				jvKey("value", jvFloat(value)),
				jvKey("learned", jvFloat(learned)),
				jvKey("prior", jvFloat(prior.value)),
				jvKey("confidence", jvFloat(confidence)),
			))
			studioConfidence = math.Max(studioConfidence, confidence)
		}
		studioValues := make([]float64, 0, len(studioItems.arr))
		for _, item := range studioItems.arr {
			studioValues = append(studioValues, numberValue(item.get("value")))
		}
		studioRaw := sumFloats(studioValues)
		familyConfidences["studio"] = studioConfidence
		if len(studioItems.arr) == 0 {
			components.set("studio", jvObj(
				jvKey("raw", jvInt(0)),
				jvKey("value", jvInt(0)),
				jvKey("studios", studioItems),
				jvKey("evidence_confidence", jvFloat(studioConfidence)),
			))
		} else {
			components.set("studio", jvObj(
				jvKey("raw", jvFloat(studioRaw)),
				jvKey("value", jvFloat(clampValue(studioRaw, -0.12, 0.12))),
				jvKey("studios", studioItems),
				jvKey("evidence_confidence", jvFloat(studioConfidence)),
			))
		}
		neighborData, hasNeighbors := neighbors[sceneID]
		if !hasNeighbors {
			neighborData = neighborEvidence{}
		}
		neighborValue := neighborData.value
		neighborOutcomeMean := neighborData.outcomeMean
		neighborLift := neighborData.lift
		neighborConfidence := neighborData.confidence
		neighborTotalWeight := neighborData.totalWeight
		if !hasNeighbors {
			neighborValue, neighborOutcomeMean, neighborLift, neighborConfidence, neighborTotalWeight = 0.0, labelMean, 0.0, 0.0, 0.0
		}
		familyConfidences["content_neighbor"] = neighborConfidence
		components.set("content_neighbor", jvObj(
			jvKey("raw", jvFloat(neighborValue)),
			jvKey("value", jvFloat(clampValue(neighborValue, -0.20, 0.20))),
			jvKey("outcome_mean", jvFloat(neighborOutcomeMean)),
			jvKey("training_outcome_mean", jvFloat(labelMean)),
			jvKey("lift", jvFloat(neighborLift)),
			jvKey("evidence_confidence", jvFloat(neighborConfidence)),
			jvKey("total_weight", jvFloat(neighborTotalWeight)),
			jvKey("vector_mode", jvStr("preference_discriminative")),
			jvKey("discriminative_tag_count", jvInt(int64(discriminative))),
		))
		var componentValues []float64
		for _, pair := range components.obj {
			if pair.val.kind == jObj {
				if value := pair.val.get("value"); value.kind == jNum {
					componentValues = append(componentValues, numberValue(value))
				}
			}
		}
		componentTotal := sumFloats(componentValues)
		general := clamp(componentTotal)
		direct := labels[sceneID]
		exactConfidence := directConfidenceOf(direct.effectiveEvidence)
		appeal := blendAppealOf(general, direct.outcome, exactConfidence)
		last, played := lastPlayed[sceneID]
		var recovery float64
		if !played {
			recovery = 1.0
		} else {
			days := math.Max(0, float64(referenceAtMs-last)/86_400_000)
			recovery = sceneRecovery(days)
		}
		cooldown := math.Max(0, appeal) * (1 - recovery)
		satiationValue := satiation(db, sceneID, appeal, recentContext)
		notNow := notNowPenalty(sceneID, referenceAtMs, recentContext)
		currentFit := clamp(appeal - cooldown - satiationValue - notNow)
		contentCount := len(vectors[sceneID])
		var performerProfileCount float64
		for _, item := range identityValues.arr {
			if profiles[item.get("performer_id").asString()] {
				performerProfileCount++
			}
		}
		metadataConfidence := 1 - math.Exp(-(float64(contentCount)+performerProfileCount+float64(len(studioItems.arr)))/5)
		type activeEvidence struct {
			value      float64
			confidence float64
		}
		var active []activeEvidence
		for _, family := range []string{"content", "structure", "performer_identity",
			"performer_similarity", "studio", "content_neighbor"} {
			familyConfidence := familyConfidences[family]
			component := components.get(family)
			if component.kind != jObj || familyConfidence <= 0 {
				continue
			}
			componentValue := math.Abs(numberValue(component.get("value")))
			if componentValue >= 0.005 {
				active = append(active, activeEvidence{componentValue, familyConfidence})
			}
		}
		activeValues := make([]float64, 0, len(active))
		activeWeighted := make([]float64, 0, len(active))
		for _, item := range active {
			activeValues = append(activeValues, item.value)
			activeWeighted = append(activeWeighted, item.value*item.confidence)
		}
		evidenceMass := sumFloats(activeValues)
		var evidenceConfidence float64
		if evidenceMass != 0 {
			evidenceConfidence = sumFloats(activeWeighted) / evidenceMass
		}
		breadth := 1 - math.Exp(-float64(len(active))/2)
		predictionConfidence := evidenceConfidence * (0.65 + 0.35*breadth)
		confidence := clampValue(exactConfidence+(1-exactConfidence)*predictionConfidence, 0, 1)
		directSignals := jvArr()
		for _, signal := range direct.signalTypes {
			directSignals.arr = append(directSignals.arr, jvStr(signal))
		}
		components.set("direct", jvObj(
			jvKey("value", jvFloat(direct.outcome)),
			jvKey("confidence", jvFloat(exactConfidence)),
			jvKey("effective_evidence", jvFloat(direct.effectiveEvidence)),
			jvKey("signals", directSignals),
			jvKey("residual", jvFloat(clampValue(direct.outcome-general, -2, 2))),
		))
		components.set("fit", jvObj(
			jvKey("cooldown", jvFloat(-cooldown)),
			jvKey("satiation", jvFloat(-satiationValue)),
			jvKey("not_now", jvFloat(-notNow)),
			jvKey("recovery", jvFloat(recovery)),
		))
		eligibilityValue, ok := eligibility[sceneID]
		if !ok {
			eligibilityValue = jvObj(
				jvKey("eligible", jvBool(false)),
				jvKey("reasons", jvArr(jvStr("missing"))),
			)
		}
		var neighborItems []jVal
		if hasNeighbors {
			neighborItems = neighborData.neighbors
		}
		scores = append(scores, buildModelScore{
			sceneID:            sceneID,
			generalAppeal:      general,
			directAppeal:       direct.outcome,
			directConfidence:   exactConfidence,
			appeal:             appeal,
			currentFit:         currentFit,
			confidence:         confidence,
			metadataConfidence: metadataConfidence,
			recovery:           recovery,
			components:         components,
			neighbors:          neighborItems,
			eligibility:        eligibilityValue,
		})
		progressIndex := len(preferenceVectors) + sceneIndex + 1
		if report != nil && (sceneIndex+1 == totalScenes || (sceneIndex+1)%250 == 0) {
			report(0.35 + 0.40*float64(progressIndex)/float64(maxInt(1, progressTotal)))
		}
	}
	return scores, performerSimilarity, nil
}
