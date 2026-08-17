// Model build final stages — publication, the top-level build, the
// coordinator drain, and post-build retention, completing the
// PreferenceModelBuilder port (curator/model/builder.py, storage/models.py,
// storage/retention.py, model/updates.py).
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// drainResult mirrors ModelBuildResult on the fields task modes read.
type drainResult struct {
	modelID        string
	featureVersion string
	sceneCount     int64
	labeledCount   int64
	reused         bool
	stageTimingsMs map[string]int64
	stageMemory    map[string]jVal
}

// modelStoreStartBuild mirrors ModelStore.start_build.
func modelStoreStartBuild(db dbx, modelID, featureVersion, configJSON, syncWatermark string, createdAtMs int64) error {
	return withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
INSERT INTO model_version(
    model_id, status, feature_version, config_json, sync_watermark, created_at_ms
) VALUES (?, 'building', ?, ?, ?, ?)`,
			modelID, featureVersion, configJSON, sqlNullable(syncWatermark, syncWatermark != ""), createdAtMs)
		return err
	})
}

// modelStoreFail mirrors ModelStore.fail.
func modelStoreFail(db dbx, modelID string) error {
	return withTxn(db, func(conn *sql.Conn) error {
		res, err := conn.ExecContext(context.Background(),
			`UPDATE model_version SET status='failed' WHERE model_id=? AND status='building'`,
			modelID)
		if err != nil {
			return err
		}
		rows, err := res.RowsAffected()
		if err != nil {
			return err
		}
		if rows != 1 {
			return fmt.Errorf("model is not a building model: %s", modelID)
		}
		return nil
	})
}

// modelPublish mirrors PreferenceModelBuilder._publish, recording the
// database_writing / lane_classification / varied_ordering / indexing /
// validation / publication stage timings into rec (the caller's build
// recorder) and returning them as the stage map.
func modelPublish(db dbx, modelID, featureVersion string, affinities map[string]modelAffinity,
	labels map[string]sceneLabel, scores []buildModelScore, performerSimilarity jVal,
	nowMs int64, report func(fraction float64), rec *stageRecorder) (map[string]int64, error) {
	var scoresByScene map[string]buildModelScore
	var artifact dbx
	var temporary, final string
	published := false
	fail := func(err error) (map[string]int64, error) {
		if !published {
			discardArtifact(artifact, temporary)
			if _, statErr := os.Stat(temporary); os.IsNotExist(statErr) {
				os.Remove(final)
			}
		}
		return nil, err
	}
	// database_writing: Python's writing_started boundary — scores_by_scene
	// through the five insert batches (including create_artifact and
	// attach_build_sources, which sit between writing_started and the first
	// insert in Python too).
	databaseWritingStarted := time.Now()
	scoresByScene = map[string]buildModelScore{}
	for _, score := range scores {
		scoresByScene[score.sceneID] = score
	}
	featurePath, err := featureArtifactPath(db, featureVersion)
	if err != nil {
		return nil, err
	}
	corePath, err := coreDatabasePath(db)
	if err != nil {
		return nil, err
	}
	artifact, temporary, final, err = createArtifact(corePath, "model", modelID)
	if err != nil {
		return nil, err
	}
	if err := attachBuildSources(artifact, corePath, featurePath); err != nil {
		discardArtifact(artifact, temporary)
		return nil, err
	}
	// feature_affinity
	affinityRows := make([][]any, 0, len(affinities))
	for _, featureID := range sortedStringKeys(affinities) {
		affinity := affinities[featureID]
		affinityRows = append(affinityRows, []any{
			modelID, featureID, affinity.affinity, affinity.confidence, affinity.support,
			affinity.sceneCount, affinity.contexts.marshalSortedKeys(),
		})
	}
	if err := insertArtifactRows(artifact, `
INSERT INTO feature_affinity(
    model_id, feature_id, affinity, confidence, effective_support,
    distinct_scene_count, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?)`, affinityRows); err != nil {
		return fail(err)
	}
	if report != nil {
		report(0.78)
	}
	// direct_scene_state
	var stateRows [][]any
	for _, sceneID := range sortedStringKeys(labels) {
		label := labels[sceneID]
		score, ok := scoresByScene[sceneID]
		if !ok {
			continue
		}
		stateRows = append(stateRows, []any{
			modelID, sceneID, label.absoluteOutcome, label.absoluteEvidence,
			directConfidenceOf(label.absoluteEvidence),
			clampValue(label.absoluteOutcome-score.generalAppeal, -2, 2),
		})
	}
	if err := insertArtifactRows(artifact, `
INSERT INTO direct_scene_state(
    model_id, scene_id, direct_appeal, effective_evidence, confidence, residual
) VALUES (?, ?, ?, ?, ?, ?)`, stateRows); err != nil {
		return fail(err)
	}
	if report != nil {
		report(0.81)
	}
	// model_scene_score
	scoreRows := make([][]any, 0, len(scores))
	neighborRows := make([][]any, 0)
	for _, score := range scores {
		scoreRows = append(scoreRows, []any{
			modelID, score.sceneID, score.generalAppeal, score.directAppeal,
			score.directConfidence, score.appeal, score.currentFit, score.confidence,
			score.metadataConfidence, score.recovery,
			score.components.marshalSortedKeys(),
			classificationPayload(score.components).marshalSortedKeys(),
			score.eligibility.marshalSortedKeys(),
		})
		for rank, neighbor := range score.neighbors {
			neighborRows = append(neighborRows, []any{
				modelID, score.sceneID, rank, neighbor.get("scene_id").asString(),
				numberValue(neighbor.get("similarity")), numberValue(neighbor.get("weight")),
				numberValue(neighbor.get("outcome")),
			})
		}
	}
	if err := insertArtifactRows(artifact, `
INSERT INTO model_scene_score(
    model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
    appeal, current_fit, confidence, metadata_confidence, recovery,
    components_json, classification_json, eligibility_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, scoreRows); err != nil {
		return fail(err)
	}
	if err := insertArtifactRows(artifact, `
INSERT INTO model_scene_neighbor(
    model_id, scene_id, rank, neighbor_scene_id, similarity, weight, outcome
) VALUES (?, ?, ?, ?, ?, ?, ?)`, neighborRows); err != nil {
		return fail(err)
	}
	if report != nil {
		report(0.85)
	}
	// model_performer_edge
	var edgeRows [][]any
	for _, performerID := range sortedStringKeys(jvKeys(performerSimilarity)) {
		entry := performerSimilarity.get(performerID)
		matches, err := edgeMatches(entry)
		if err != nil {
			return fail(err)
		}
		for rank, match := range matches {
			edgeRows = append(edgeRows, []any{
				modelID, performerID, rank, match.get("performer_id").asString(),
				numberValue(match.get("similarity")), numberValue(match.get("affinity")),
				numberValue(match.get("confidence")),
			})
		}
	}
	if err := insertArtifactRows(artifact, `
INSERT INTO model_performer_edge(
    model_id, performer_id, rank, similar_performer_id,
    similarity, affinity, confidence
) VALUES (?, ?, ?, ?, ?, ?, ?)`, edgeRows); err != nil {
		return fail(err)
	}
	rec.set("database_writing", elapsedMs(databaseWritingStarted))
	// Lanes + slate inside the artifact. indexing spans from just before lane
	// classification through index creation (Python's indexing_started).
	indexingStarted := time.Now()
	if err := rec.stage("lane_classification", "model.lane_classification", func() error {
		_, err := laneClassify(artifact, modelID, featureVersion, func(processed, total int) {
			if report != nil {
				report(0.85 + 0.02*float64(processed)/float64(maxInt(1, total)))
			}
		})
		return err
	}); err != nil {
		return fail(err)
	}
	rec.set("score_first_ordering", 0)
	recordDurationMs(currentTrace(), "python", "model.score_first_ordering", 0)
	if err := rec.stage("varied_ordering", "model.varied_ordering", func() error {
		_, err := materializeLanes(artifact, modelID, true, func(processed, total int) {
			if report != nil {
				report(0.87 + 0.04*float64(processed)/float64(maxInt(1, total)))
			}
		})
		return err
	}); err != nil {
		return fail(err)
	}
	rec.set("reason_generation", 0)
	recordDurationMs(currentTrace(), "python", "model.reason_generation", 0)
	if report != nil {
		report(0.94)
	}
	if err := rec.stage("sqlite_index_creation", "model.sqlite_index_creation", func() error {
		return artifactCreateIndexes(artifact, "model")
	}); err != nil {
		return fail(err)
	}
	rec.set("indexing", elapsedMs(indexingStarted))
	if report != nil {
		report(0.96)
	}
	var storedCount, laneCount int64
	var summary jVal
	if err := rec.stage("validation", "", func() error {
		if err := artifact.QueryRow(`SELECT count(*) FROM model_scene_score WHERE model_id=?`, modelID).Scan(&storedCount); err != nil {
			return err
		}
		if err := artifact.QueryRow(`SELECT count(*) FROM model_scene_lane WHERE model_id=?`, modelID).Scan(&laneCount); err != nil {
			return err
		}
		var laneState int
		err := artifact.QueryRow(`SELECT 1 FROM model_lane_order_state WHERE model_id=?`, modelID).Scan(&laneState)
		if storedCount != int64(len(scores)) || (err != nil && err != sql.ErrNoRows) {
			return fmt.Errorf("model validation failed: scores=%d/%d, lane state=%v",
				storedCount, len(scores), err == nil)
		}
		var vErr error
		summary, vErr = artifactValidate(artifact, "model", map[string]int64{
			"scenes": storedCount, "lanes": laneCount, "reason_scenes": 0, "reasons": 0,
		}, false)
		return vErr
	}); err != nil {
		return fail(err)
	}
	if report != nil {
		report(0.97)
	}
	if err := rec.stage("publication", "", func() error {
		size, err := publishArtifactFile(artifact, temporary, final)
		if err != nil {
			return err
		}
		artifact = nil
		if err := withTxn(db, func(conn *sql.Conn) error {
			ctx := context.Background()
			if _, err := conn.ExecContext(ctx,
				`UPDATE model_version SET status='superseded' WHERE status='published'`); err != nil {
				return err
			}
			if _, err := conn.ExecContext(ctx, `
UPDATE model_version SET status='published', published_at_ms=?,
    artifact_basename=?, artifact_schema_version=?, artifact_bytes=?,
    scene_count=?, lane_count=?, reason_scene_count=?, reason_count=?,
    validation_status='valid', validation_summary_json=?,
    cleanup_error=NULL
WHERE model_id=?`,
				nowMs, filepath.Base(final), artifactSchemaVersion, size,
				storedCount, laneCount, 0, 0, summary.marshalSortedKeys(), modelID); err != nil {
				return err
			}
			_, err := conn.ExecContext(ctx, `
INSERT INTO application_meta(key, value) VALUES ('current_model_id', ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, modelID)
			return err
		}); err != nil {
			return err
		}
		published = true
		return activateArtifact(db, "model", final)
	}); err != nil {
		return nil, err
	}
	if report != nil {
		report(0.98)
	}
	return rec.timingsMap(), nil
}

// modelConfigCanonical mirrors json.dumps(asdict(CuratorConfig),
// sort_keys=True): the feature/model/ranking sub-configs as ordered dicts.
func modelConfigCanonical() string {
	config := jvObj(
		jvKey("feature", modelFeatureConfig()),
		jvKey("model", modelSubConfig()),
		jvKey("ranking", rankingSubConfig()),
		jvKey("random_seed", jvInt(31415)),
	)
	return config.marshalSortedKeys()
}

func parseJSONOr(raw string) jVal {
	parsed, err := parseJSON([]byte(raw))
	if err != nil {
		return jvObj()
	}
	return parsed
}

// modelFeatureConfig mirrors asdict(FeatureConfig) as a jVal object.
func modelFeatureConfig() jVal {
	parsed, err := parseJSON([]byte(featureConfigCanonicalJSON()))
	if err != nil {
		return jvObj()
	}
	return parsed
}

// modelSubConfig mirrors asdict(ModelConfig) with the defaults.
func modelSubConfig() jVal {
	return jvObj(
		jvKey("affinity_confidence_scale", jvFloat(3.0)),
		jvKey("affinity_prior", jvFloat(1.0)),
		jvKey("algorithm_version", jvInt(6)),
		jvKey("baseline_bound", jvFloat(0.10)),
		jvKey("content_bound", jvFloat(0.35)),
		jvKey("cooldown_center_days", jvFloat(90.0)),
		jvKey("cooldown_width_days", jvFloat(15.0)),
		jvKey("curation_pair_confidence", jvFloat(0.50)),
		jvKey("curation_pair_ips_cap", jvFloat(4.0)),
		jvKey("curation_pair_surprise_bonus", jvFloat(2.0)),
		jvKey("curation_rating_confidence", jvFloat(0.80)),
		jvKey("direct_confidence_scale", jvFloat(0.8)),
		jvKey("minimum_neighbor_similarity", jvFloat(0.05)),
		jvKey("neighbor_bound", jvFloat(0.2)),
		jvKey("neighbor_confidence_scale", jvFloat(0.35)),
		jvKey("neighbor_count", jvInt(12)),
		jvKey("neighbor_generic_weight", jvFloat(0.0)),
		jvKey("not_now_days", jvFloat(30.0)),
		jvKey("not_now_penalty", jvFloat(0.50)),
		jvKey("performer_favorite_prior", jvFloat(0.18)),
		jvKey("performer_identity_bound", jvFloat(0.30)),
		jvKey("performer_rating_bound", jvFloat(0.10)),
		jvKey("performer_similarity_bound", jvFloat(0.16)),
		jvKey("performer_similarity_novelty_floor", jvFloat(0.05)),
		jvKey("satiation_bound", jvFloat(0.12)),
		jvKey("scene_rating_confidence", jvFloat(0.90)),
		jvKey("structure_bound", jvFloat(0.05)),
		jvKey("studio_bound", jvFloat(0.12)),
		jvKey("studio_favorite_prior", jvFloat(0.04)),
	)
}

// rankingSubConfig mirrors asdict(RankingConfig) with the defaults.
func rankingSubConfig() jVal {
	return jvObj(
		jvKey("adjacent_shared_performers", jvBool(false)),
		jvKey("best_bet_anchor_percentile", jvFloat(0.60)),
		jvKey("best_bet_confidence", jvFloat(0.30)),
		jvKey("best_bet_fit", jvFloat(0.18)),
		jvKey("best_bet_metadata_confidence", jvFloat(0.35)),
		jvKey("best_bet_neighbor_percentile", jvFloat(0.60)),
		jvKey("best_bet_relevance", jvFloat(0.60)),
		jvKey("content_penalty", jvFloat(0.14)),
		jvKey("discover_anchor", jvFloat(0.08)),
		jvKey("for_you_pattern", jvStrList(forYouPattern)),
		jvKey("history_content_penalty", jvFloat(0.05)),
		jvKey("history_performer_penalty", jvFloat(0.04)),
		jvKey("history_size", jvInt(50)),
		jvKey("history_studio_penalty", jvFloat(0.03)),
		jvKey("page_size", jvInt(20)),
		jvKey("performer_repeat_penalty", jvFloat(0.06)),
		jvKey("relax_adjacent_when_exhausted", jvBool(false)),
		jvKey("revisit_direct_confidence", jvFloat(0.35)),
		jvKey("studio_penalty", jvFloat(0.08)),
		jvKey("uncovered_content_bonus", jvFloat(0.03)),
	)
}

// modelBuild runs the full PreferenceModelBuilder pipeline, recording the
// Python-era stage timings (feature_* merged from the shared recorder, plus
// labels/affinities/similarity/scoring, the modelPublish map, cleanup, and
// total) and the per-stage memory snapshots into the drain result.
func modelBuild(db dbx, nowMs int64, progress func(processed, total int)) (drainResult, error) {
	report := func(fraction float64) {
		if progress != nil {
			progress(int(pyRound(fraction*1000)), 1000)
		}
	}
	rec := newStageRecorder()
	timings := map[string]int64{}
	started := time.Now()
	var featureVersion string
	err := rec.stage("", "model.features", func() error {
		var err error
		featureVersion, _, err = featureBuild(db, nowMs, rec, func(fraction float64) {
			report(0.25 * fraction)
		})
		return err
	})
	if err != nil {
		return drainResult{}, err
	}
	report(0.25)
	referenceAtMs := (nowMs / 86_400_000) * 86_400_000
	var labels map[string]sceneLabel
	var trainingLabels map[string]sceneLabel
	err = rec.stage("labels", "model.labels", func() error {
		var err error
		labels, err = modelSceneLabels(db)
		if err != nil {
			return err
		}
		trainingLabels, err = modelTrainingLabels(db, labels)
		return err
	})
	if err != nil {
		return drainResult{}, err
	}
	report(0.30)
	evidenceFingerprint, err := modelEvidenceFingerprint(db, labels)
	if err != nil {
		return drainResult{}, err
	}
	sourceFingerprint, err := modelSourceFingerprint(db)
	if err != nil {
		return drainResult{}, err
	}
	if os.Getenv("CURATOR_DEBUG_MODEL_DIGEST") != "" {
		fmt.Fprintf(os.Stderr, "DEBUG model digest: fv=%s ev=%s src=%s cfg=%s cutoff=%g ver=%d ref=%d\n",
			featureVersion, evidenceFingerprint, sourceFingerprint, modelConfigCanonical(),
			performerSimilarityAffinityCutoff, modelBuildVersion, referenceAtMs)
	}
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s\x00%s\x00%g\x00%d\x00%d",
		featureVersion, evidenceFingerprint, sourceFingerprint, modelConfigCanonical(),
		performerSimilarityAffinityCutoff, modelBuildVersion, referenceAtMs)))
	modelID := fmt.Sprintf("model-%s", hexEncode(digest[:])[:20])
	var status string
	var validationStatus sql.NullString
	var basename sql.NullString
	err = db.QueryRow(`SELECT status, artifact_basename, validation_status FROM model_version WHERE model_id=?`,
		modelID).Scan(&status, &basename, &validationStatus)
	if err == nil && status == "published" && validationStatus.Valid && validationStatus.String == "valid" && basename.Valid {
		core, pathErr := coreDatabasePath(db)
		if pathErr == nil {
			path, pathErr := artifactPath(core, basename.String)
			if pathErr == nil {
				if _, statErr := os.Stat(path); statErr == nil {
					if err := withTxn(db, func(conn *sql.Conn) error {
						_, err := conn.ExecContext(context.Background(),
							`UPDATE model_version SET reuse_count=reuse_count+1 WHERE model_id=?`, modelID)
						return err
					}); err != nil {
						return drainResult{}, err
					}
					report(1.0)
					rec.set("total", elapsedMs(started))
					return drainResult{
						modelID:        modelID,
						featureVersion: featureVersion,
						reused:         true,
						stageTimingsMs: rec.timingsMap(),
						stageMemory:    rec.stageMemory(),
					}, nil
				}
			}
		}
	} else if err != nil && err != sql.ErrNoRows {
		return drainResult{}, err
	}
	modelConfigJSON := jvObj(
		jvKey("config", parseJSONOr(modelConfigCanonical())),
		jvKey("model_build_version", jvInt(modelBuildVersion)),
		jvKey("reference_at_ms", jvInt(referenceAtMs)),
	)
	if err == nil {
		// The row already exists (a superseded, failed, or in-flight build of
		// the same digest). Python's builder flips it back to 'building'
		// instead of inserting; the plain INSERT would collide on the key.
		if uerr := withTxn(db, func(conn *sql.Conn) error {
			_, uerr := conn.ExecContext(context.Background(),
				`UPDATE model_version SET status='building' WHERE model_id=?`, modelID)
			return uerr
		}); uerr != nil {
			return drainResult{}, uerr
		}
	} else if err := modelStoreStartBuild(db, modelID, featureVersion, modelConfigJSON.marshalSortedKeys(),
		modelSyncWatermark(db), nowMs); err != nil {
		return drainResult{}, err
	}
	var sceneFeatures map[string][]storedFeature
	var affinities map[string]modelAffinity
	var labelMean float64
	err = rec.stage("affinities", "model.affinities", func() error {
		var err error
		sceneFeatures, err = modelStoredFeatures(db, featureVersion, "scene")
		if err != nil {
			return err
		}
		labelMean = modelLabelMean(trainingLabels)
		affinities, err = modelAffinities(db, sceneFeatures, trainingLabels, labelMean)
		return err
	})
	if err != nil {
		modelStoreFail(db, modelID)
		return drainResult{}, err
	}
	report(0.35)
	stageStarted := time.Now()
	scores, performerSimilarity, scoreTimings, err := buildModelScores(db, featureVersion, sceneFeatures,
		affinities, labels, trainingLabels, labelMean, referenceAtMs, report)
	if err != nil {
		modelStoreFail(db, modelID)
		return drainResult{}, err
	}
	scoreTotal := elapsedMs(stageStarted)
	scoring := maxInt64(0, scoreTotal-scoreTimings["similarity"])
	rec.set("similarity", scoreTimings["similarity"])
	rec.set("scoring", scoring)
	timings["similarity"] = scoreTimings["similarity"]
	timings["scoring"] = scoring
	recordStageSpan("model.scores", stageStarted)
	report(0.35)
	var publishTimings map[string]int64
	err = rec.stage("", "model.publish", func() error {
		var err error
		publishTimings, err = modelPublish(db, modelID, featureVersion, affinities, labels,
			scores, performerSimilarity, nowMs, report, rec)
		return err
	})
	if err != nil {
		modelStoreFail(db, modelID)
		return drainResult{}, err
	}
	report(0.98)
	if err := rec.stage("cleanup", "", func() error {
		return pruneSnapshots(db)
	}); err != nil {
		return drainResult{}, err
	}
	report(1.0)
	var sceneCount int64
	if err := db.QueryRow(`SELECT count(*) FROM model_scene_score WHERE model_id=?`, modelID).Scan(&sceneCount); err != nil {
		return drainResult{}, err
	}
	for key, value := range publishTimings {
		timings[key] = value
	}
	for key, value := range rec.timingsMap() {
		timings[key] = value
	}
	rec.set("total", elapsedMs(started))
	timings["total"] = elapsedMs(started)
	return drainResult{
		modelID:        modelID,
		featureVersion: featureVersion,
		sceneCount:     sceneCount,
		labeledCount:   int64(len(labels)),
		reused:         false,
		stageTimingsMs: timings,
		stageMemory:    rec.stageMemory(),
	}, nil
}

// elapsedMs returns whole milliseconds since started (Python's integer
// duration rounding for the stage timings).
func elapsedMsSince(started time.Time) int64 {
	return time.Since(started).Milliseconds()
}

// pruneSnapshots mirrors storage.retention.prune_snapshots (limit=1): retain
// the top-2 models and delete the oldest superseded/failed snapshot.
func pruneSnapshots(db dbx) error {
	retained := map[string]bool{}
	rows, err := db.Query(`
SELECT model_id FROM model_version
WHERE status IN ('published', 'superseded')
ORDER BY COALESCE(published_at_ms, created_at_ms) DESC LIMIT 2`)
	if err != nil {
		return err
	}
	for rows.Next() {
		var modelID string
		if err := rows.Scan(&modelID); err != nil {
			rows.Close()
			return err
		}
		retained[modelID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	rows, err = db.Query(`
SELECT model_id, artifact_basename FROM model_version
WHERE status IN ('superseded', 'failed') OR (
    status='building' AND created_at_ms < COALESCE(
        (SELECT max(created_at_ms) FROM model_version WHERE status='published'),
        created_at_ms
    )
)
ORDER BY COALESCE(published_at_ms, created_at_ms), model_id`)
	if err != nil {
		return err
	}
	type snapshot struct {
		modelID  string
		basename string
	}
	var modelRows []snapshot
	for rows.Next() {
		var modelID string
		var basename sql.NullString
		if err := rows.Scan(&modelID, &basename); err != nil {
			rows.Close()
			return err
		}
		if !retained[modelID] {
			modelRows = append(modelRows, snapshot{modelID, basename.String})
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	// Retain the newest (limit=1 deletes the oldest), mirroring Python's
	// model_deletes = model_rows[:limit] with the query's ASC order.
	if len(modelRows) > 1 {
		modelRows = modelRows[:1]
	}
	core, err := coreDatabasePath(db)
	if err != nil {
		return err
	}
	var deletedModels []string
	for _, item := range modelRows {
		if item.basename != "" {
			path, err := artifactPath(core, item.basename)
			if err == nil {
				if err := os.Remove(path); err != nil {
					if err := withTxn(db, func(conn *sql.Conn) error {
						_, err := conn.ExecContext(context.Background(),
							`UPDATE model_version SET cleanup_error=? WHERE model_id=?`,
							truncateString(err.Error(), 2000), item.modelID)
						return err
					}); err != nil {
						return err
					}
					continue
				}
			}
			deletedModels = append(deletedModels, item.modelID)
		}
	}
	if len(deletedModels) > 0 {
		if err := withTxn(db, func(conn *sql.Conn) error {
			for _, modelID := range deletedModels {
				if _, err := conn.ExecContext(context.Background(), `
UPDATE model_version SET artifact_basename=NULL, validation_status='retired', cleanup_error=NULL
WHERE model_id=?`, modelID); err != nil {
					return err
				}
			}
			return nil
		}); err != nil {
			return err
		}
	}
	return nil
}

// modelUpdateStateRow mirrors the model_update_state read used by drain.
type modelUpdateStateRow struct {
	requestedGeneration int64
	publishedGeneration int64
	requestedAtMs       sql.NullInt64
	lastStartedAtMs     sql.NullInt64
	lastFinishedAtMs    sql.NullInt64
	lastDurationMs      sql.NullInt64
	lastCause           sql.NullString
	lastError           sql.NullString
	stageTimingsJSON    string
}

// coordinatorDrain mirrors ModelUpdateCoordinator.drain.
func coordinatorDrain(db dbx, force bool, maxBuilds int, progress func(processed, total int)) ([]drainResult, error) {
	var built []drainResult
	for i := 0; i < maxBuilds; i++ {
		var generation int64
		shouldBreak := false
		err := withTxn(db, func(conn *sql.Conn) error {
			ctx := context.Background()
			var state modelUpdateStateRow
			err := conn.QueryRowContext(ctx,
				`SELECT requested_generation, published_generation, requested_at_ms,
last_started_at_ms, last_finished_at_ms, last_duration_ms, last_cause, last_error,
stage_timings_json FROM model_update_state WHERE singleton=1`).
				Scan(&state.requestedGeneration, &state.publishedGeneration, &state.requestedAtMs,
					&state.lastStartedAtMs, &state.lastFinishedAtMs, &state.lastDurationMs,
					&state.lastCause, &state.lastError, &state.stageTimingsJSON)
			if err != nil {
				return err
			}
			now := nowMs()
			requestedAtMs := now
			if state.requestedAtMs.Valid {
				requestedAtMs = state.requestedAtMs.Int64
			}
			building := state.lastStartedAtMs.Valid &&
				(!state.lastFinishedAtMs.Valid || state.lastStartedAtMs.Int64 > state.lastFinishedAtMs.Int64) &&
				!state.lastError.Valid &&
				now-state.lastStartedAtMs.Int64 < 6*3_600_000
			pending := state.requestedGeneration > state.publishedGeneration
			if !pending || building || (!force && now-requestedAtMs < 2_000) {
				shouldBreak = true
				return nil
			}
			generation = state.requestedGeneration
			_, err = conn.ExecContext(ctx,
				`UPDATE model_update_state SET last_started_at_ms=?, last_error=NULL WHERE singleton=1`,
				now)
			return err
		})
		if err != nil {
			return nil, err
		}
		if shouldBreak {
			break
		}
		started := time.Now().UnixNano()
		result, buildErr := modelBuild(db, nowMs(), func(processed, total int) {
			if progress != nil {
				progress(processed, total)
			}
		})
		if buildErr != nil {
			if err := withTxn(db, func(conn *sql.Conn) error {
				_, err := conn.ExecContext(context.Background(),
					`UPDATE model_update_state SET last_error=? WHERE singleton=1`,
					truncateString(buildErr.Error(), 2000))
				return err
			}); err != nil {
				return nil, err
			}
			return nil, buildErr
		}
		durationMs := int64(pyRound(float64(time.Now().UnixNano()-started) / 1_000_000))
		timingsJSON := jvObj()
		for _, key := range sortedStringKeys(result.stageTimingsMs) {
			timingsJSON.set(key, jvInt(result.stageTimingsMs[key]))
		}
		if err := withTxn(db, func(conn *sql.Conn) error {
			_, err := conn.ExecContext(context.Background(), `
UPDATE model_update_state SET published_generation=?,
    last_finished_at_ms=?, last_duration_ms=?, last_error=NULL,
    stage_timings_json=?
WHERE singleton=1`,
				generation, nowMs(), durationMs, timingsJSON.marshalSortedKeys())
			return err
		}); err != nil {
			return nil, err
		}
		built = append(built, result)
	}
	return built, nil
}

func hexEncode(value []byte) string {
	const hexDigits = "0123456789abcdef"
	out := make([]byte, len(value)*2)
	for i, b := range value {
		out[i*2] = hexDigits[b>>4]
		out[i*2+1] = hexDigits[b&0x0F]
	}
	return string(out)
}

func jvKeys(v jVal) map[string]bool {
	keys := map[string]bool{}
	for _, pair := range v.obj {
		keys[pair.key] = true
	}
	return keys
}
