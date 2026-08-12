// Legacy-generation compaction — a port of
// curator/storage/database.py's compact_legacy_generations (and its
// _compaction_targets / _validated_artifact / _logical_database_bytes
// helpers). Rebuildable core rows of superseded generations are deleted in
// restartable per-batch transactions, with progress and a persisted
// fingerprint-gated state blob in application_meta.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// legacyDerivedTables mirrors storage.database._LEGACY_DERIVED_TABLES; the
// order is the deletion order (feature_definition last; entity_feature
// cascades toward it).
var legacyDerivedTables = []struct {
	table            string
	generationColumn string
	keyColumns       []string
}{
	{"model_scene_reason", "model_id", []string{"model_id", "scene_id", "reason_index"}},
	{"model_lane_order", "model_id", []string{"model_id", "lane", "ordering", "position"}},
	{"model_scene_lane", "model_id", []string{"model_id", "scene_id", "lane"}},
	{"model_scene_score", "model_id", []string{"model_id", "scene_id"}},
	{"model_scene_neighbor", "model_id", []string{"model_id", "scene_id", "rank"}},
	{"direct_scene_state", "model_id", []string{"model_id", "scene_id"}},
	{"feature_affinity", "model_id", []string{"model_id", "feature_id"}},
	{"model_lane_candidate_cache", "model_id", []string{"model_id", "lane"}},
	{"model_lane_order_state", "model_id", []string{"model_id"}},
	{"scene_content_search", "feature_version", []string{"feature_id", "scene_id"}},
	{"entity_feature", "feature_version", []string{"feature_version", "entity_type", "entity_id", "feature_id"}},
	{"feature_definition", "feature_version", []string{"feature_id"}},
}

// validatedArtifact mirrors storage.database._validated_artifact: an
// immutable read-only open of the artifact, requiring artifact_meta to match
// (kind, generation_id), a supported schema version, the kind's table set,
// and a clean quick_check.
func validatedArtifact(path, kind, generationID string) error {
	fail := func(err error) error {
		if err != nil {
			return fmt.Errorf("invalid %s artifact: %s (%v)", kind, filepath.Base(path), err)
		}
		return fmt.Errorf("invalid %s artifact: %s", kind, filepath.Base(path))
	}
	db, err := sql.Open("sqlite3", readonlyArtifactURI(path, true))
	if err != nil {
		return fail(err)
	}
	defer db.Close()
	var metaKind, metaID string
	var schemaVersion int64
	err = db.QueryRow(`SELECT kind, generation_id, schema_version FROM artifact_meta`).
		Scan(&metaKind, &metaID, &schemaVersion)
	if err != nil || metaKind != kind || metaID != generationID ||
		!supportedArtifactSchemaVersions[int(schemaVersion)] {
		return fail(err)
	}
	tables := map[string]bool{}
	rows, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table'`)
	if err != nil {
		return fail(err)
	}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			rows.Close()
			return fail(err)
		}
		tables[name] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return fail(err)
	}
	required := featureTables
	if kind == "model" {
		required = modelTables
	}
	for _, table := range required {
		if !tables[table] {
			return fail(nil)
		}
	}
	var check string
	if err := db.QueryRow(`PRAGMA quick_check`).Scan(&check); err != nil || check != "ok" {
		return fail(nil)
	}
	return nil
}

// compactionTargets mirrors storage.database._compaction_targets: the
// published/superseded valid artifact generations (with the active-artifact
// guard), the retired model extras, and the fingerprint. Invalid basenames
// and invalid artifact contents are errors (Python propagates the
// StorageError); missing files and integrity-mismatched rows are skipped.
func compactionTargets(db dbx) ([]string, []string, string, error) {
	core, err := coreDatabasePath(db)
	if err != nil {
		return nil, nil, "", err
	}
	var featureIDs, modelIDs []string
	var validatedFeature, validatedModel []string
	for _, kind := range []string{"feature", "model"} {
		table, identifier := "feature_build", "feature_version"
		if kind == "model" {
			table, identifier = "model_version", "model_id"
		}
		rows, err := db.Query(fmt.Sprintf(`
SELECT %s, status, artifact_basename, validation_summary_json
FROM %s
WHERE status IN ('published', 'superseded')
  AND validation_status='valid' AND artifact_basename IS NOT NULL`, identifier, table))
		if err != nil {
			return nil, nil, "", err
		}
		active := false
		for rows.Next() {
			var generationID, status string
			var basename sql.NullString
			var summaryJSON sql.NullString
			if err := rows.Scan(&generationID, &status, &basename, &summaryJSON); err != nil {
				rows.Close()
				return nil, nil, "", err
			}
			if !basename.Valid {
				continue
			}
			summary := jvObj()
			if summaryJSON.Valid {
				if parsed, err := parseJSON([]byte(summaryJSON.String)); err == nil {
					summary = parsed
				}
			}
			path, err := artifactPath(core, basename.String)
			if err != nil {
				rows.Close()
				return nil, nil, "", err
			}
			if _, err := os.Stat(path); err != nil || summary.get("integrity").asString() != "ok" {
				continue
			}
			if err := validatedArtifact(path, kind, generationID); err != nil {
				rows.Close()
				return nil, nil, "", err
			}
			if kind == "feature" {
				featureIDs = append(featureIDs, generationID)
				validatedFeature = append(validatedFeature, generationID)
			} else {
				modelIDs = append(modelIDs, generationID)
				validatedModel = append(validatedModel, generationID)
			}
			active = active || status == "published"
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, nil, "", err
		}
		if !active {
			return nil, nil, "", fmt.Errorf("legacy compaction requires a valid active %s artifact", kind)
		}
	}
	rows, err := db.Query(`SELECT model_id FROM model_version
WHERE status='superseded' AND validation_status='retired' AND artifact_basename IS NULL`)
	if err != nil {
		return nil, nil, "", err
	}
	for rows.Next() {
		var modelID string
		if err := rows.Scan(&modelID); err != nil {
			rows.Close()
			return nil, nil, "", err
		}
		modelIDs = append(modelIDs, modelID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, "", err
	}
	return featureIDs, modelIDs, compactionFingerprint(validatedFeature, validatedModel), nil
}

// logicalDatabaseBytes mirrors storage.database._logical_database_bytes; the
// dbstat sum of used bytes, zero when the table is unavailable.
func logicalDatabaseBytes(db dbx) int64 {
	var total int64
	err := db.QueryRow(`SELECT coalesce(sum(pgsize-unused), 0) FROM dbstat(?)`, "main").Scan(&total)
	if err != nil {
		return 0
	}
	return total
}

// compactLegacyGenerations mirrors storage.database.compact_legacy_generations.
// maxBatches < 0 means unlimited (Python's None default).
func compactLegacyGenerations(db dbx, batchSize int, maxBatches int, progress func(done, total int)) (jVal, error) {
	if batchSize < 1 || batchSize > 50_000 {
		return jvNull(), fmt.Errorf("compaction batch size must be between 1 and 50000")
	}
	attached := map[string]bool{}
	rows, err := db.Query(`PRAGMA database_list`)
	if err != nil {
		return jvNull(), err
	}
	for rows.Next() {
		var seq int
		var name, file string
		if err := rows.Scan(&seq, &name, &file); err != nil {
			rows.Close()
			return jvNull(), err
		}
		attached[name] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	if attached["feature_generation"] || attached["model_generation"] {
		return jvNull(), fmt.Errorf("legacy compaction requires a core-only connection")
	}
	featureIDs, modelIDs, fingerprint, err := compactionTargets(db)
	if err != nil {
		return jvNull(), err
	}
	targetIDs := map[string][]string{"feature_version": featureIDs, "model_id": modelIDs}

	countRemaining := func() (int64, error) {
		var total int64
		for _, spec := range legacyDerivedTables {
			ids := targetIDs[spec.generationColumn]
			if len(ids) == 0 {
				continue
			}
			placeholders := strings.TrimSuffix(strings.Repeat("?,", len(ids)), ",")
			args := make([]any, len(ids))
			for i, id := range ids {
				args[i] = id
			}
			var count int64
			if err := db.QueryRow(fmt.Sprintf(
				`SELECT count(*) FROM %s WHERE %s IN (%s)`,
				spec.table, spec.generationColumn, placeholders), args...).Scan(&count); err != nil {
				return 0, err
			}
			total += count
		}
		return total, nil
	}

	targetRowCount, err := countRemaining()
	if err != nil {
		return jvNull(), err
	}
	if progress != nil {
		progress(0, maxInt(1, int(targetRowCount)))
	}
	previous := jvObj()
	var previousRow sql.NullString
	err = db.QueryRow(`SELECT value FROM application_meta WHERE key='legacy_compaction'`).Scan(&previousRow)
	if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	if previousRow.Valid {
		if parsed, err := parseJSON([]byte(previousRow.String)); err == nil {
			previous = parsed
		}
	}
	var rowsDeleted, logicalBytesRemoved int64
	if previous.get("fingerprint").asString() == fingerprint {
		rowsDeleted = pythonInt(previous.get("rows_deleted"))
		logicalBytesRemoved = pythonInt(previous.get("logical_bytes_removed"))
	}
	beforeBytes := logicalDatabaseBytes(db)
	var beforeFreelist int64
	if err := db.QueryRow(`PRAGMA freelist_count`).Scan(&beforeFreelist); err != nil {
		return jvNull(), err
	}
	batches := 0
	perTable := map[string]int64{}

	stopped := false
	for _, spec := range legacyDerivedTables {
		for _, generationID := range targetIDs[spec.generationColumn] {
			keys := strings.Join(spec.keyColumns, ", ")
			for {
				deleted := int64(0)
				txnErr := withTxn(db, func(conn *sql.Conn) error {
					ctx := context.Background()
					res, err := conn.ExecContext(ctx, fmt.Sprintf(`
DELETE FROM %s
WHERE %s=?
  AND (%s) IN (
    SELECT %s FROM %s
    WHERE %s=? LIMIT ?
  )`, spec.table, spec.generationColumn, keys, keys, spec.table, spec.generationColumn),
						generationID, generationID, batchSize)
					if err != nil {
						return err
					}
					deleted, err = res.RowsAffected()
					if err != nil {
						return err
					}
					if deleted > 0 {
						rowsDeleted += deleted
						perTable[spec.table] += deleted
						state := jvObj(
							jvKey("status", jvStr("in_progress")),
							jvKey("fingerprint", jvStr(fingerprint)),
							jvKey("rows_deleted", jvInt(rowsDeleted)),
						)
						_, err := conn.ExecContext(ctx, `
INSERT INTO application_meta(key, value) VALUES ('legacy_compaction', ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, state.marshalSortedKeys())
						return err
					}
					return nil
				})
				if txnErr != nil {
					return jvNull(), txnErr
				}
				if deleted == 0 {
					break
				}
				batches++
				if progress != nil {
					var sum int64
					for _, n := range perTable {
						sum += n
					}
					progress(int(sum), maxInt(1, int(targetRowCount)))
				}
				if maxBatches >= 0 && batches >= maxBatches {
					stopped = true
					break
				}
			}
			if stopped {
				break
			}
		}
		if stopped {
			break
		}
	}

	remainingRows, err := countRemaining()
	if err != nil {
		return jvNull(), err
	}
	if progress != nil && targetRowCount == 0 {
		progress(1, 1)
	}
	afterBytes := logicalDatabaseBytes(db)
	var pageSize int64
	if err := db.QueryRow(`PRAGMA page_size`).Scan(&pageSize); err != nil {
		return jvNull(), err
	}
	var afterFreelist int64
	if err := db.QueryRow(`PRAGMA freelist_count`).Scan(&afterFreelist); err != nil {
		return jvNull(), err
	}
	status := "in_progress"
	if remainingRows == 0 {
		status = "complete"
	}
	var perTableSum int64
	for _, n := range perTable {
		perTableSum += n
	}
	reclaimableAdded := (afterFreelist - beforeFreelist) * pageSize
	if reclaimableAdded < 0 {
		reclaimableAdded = 0
	}
	removed := logicalBytesRemoved + maxInt64(0, beforeBytes-afterBytes)
	result := jvObj(
		jvKey("status", jvStr(status)),
		jvKey("rows_deleted", jvInt(rowsDeleted)),
		jvKey("rows_deleted_this_run", jvInt(perTableSum)),
		jvKey("rows_remaining", jvInt(remainingRows)),
		jvKey("logical_bytes_removed", jvInt(removed)),
		jvKey("reclaimable_bytes_added", jvInt(reclaimableAdded)),
		jvKey("vacuum_required_to_shrink_file", jvBool(true)),
	)
	stored := cloneObj(result)
	stored.set("fingerprint", jvStr(fingerprint))
	if err := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
INSERT INTO application_meta(key, value) VALUES ('legacy_compaction', ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, stored.marshalSortedKeys())
		return err
	}); err != nil {
		return jvNull(), err
	}
	return result, nil
}

// compactionFingerprint computes the _compaction_targets fingerprint string
// (sha256 hex of NUL-joined sorted ids); kept separate for tests.
func compactionFingerprint(feature, model []string) string {
	sortedFeature := append([]string(nil), feature...)
	sort.Strings(sortedFeature)
	sortedModel := append([]string(nil), model...)
	sort.Strings(sortedModel)
	digest := sha256.Sum256([]byte(strings.Join(append(sortedFeature, sortedModel...), "\x00")))
	return hex.EncodeToString(digest[:])
}
