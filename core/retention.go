// Generation retention — derived from storage.retention.prune_snapshots, but
// unbounded: every pass removes the whole backlog of superseded model and
// feature generations and sweeps artifact files no registry row references,
// so the <stem>-derived directory stays at the active generations plus the
// previous model however long Curator has been installed.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// orphanArtifactAge is how long an unreferenced artifact or temp file must
// sit unmodified before the sweep removes it. A build writes its temp file
// continuously and publishes by rename shortly before its registry update,
// so a build running in another process is never swept.
const orphanArtifactAge = 6 * time.Hour

// pruneSnapshots keeps the two newest models (the published one and its
// predecessor, which a reader opened before the publish may still have
// attached) and the features those or any building model use. Every older
// model and feature generation loses its artifact and registry row. A file
// that cannot be removed records cleanup_error and is retried on the next
// pass; an already-missing file counts as removed.
func pruneSnapshots(db dbx) error {
	core, err := coreDatabasePath(db)
	if err != nil {
		return err
	}
	retained, err := queryStrings(db, `
SELECT model_id FROM model_version
WHERE status IN ('published', 'superseded') AND artifact_basename IS NOT NULL
ORDER BY COALESCE(published_at_ms, created_at_ms) DESC LIMIT 2`)
	if err != nil {
		return err
	}
	keep := map[string]bool{}
	for _, modelID := range retained {
		keep[modelID] = true
	}
	models, err := retentionCandidates(db, `
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
	for _, item := range models {
		if keep[item.id] {
			continue
		}
		if err := removeArtifact(core, item.basename); err != nil {
			if err := recordCleanupError(db, "model_version", "model_id", item.id, err); err != nil {
				return err
			}
			continue
		}
		if err := retireModel(db, item.id); err != nil {
			return err
		}
	}
	// Referenced after the model pass, so features of models retired above
	// are free while those of kept, published and building models are not.
	referenced, err := queryStrings(db, `
SELECT DISTINCT feature_version FROM model_version
WHERE status IN ('published', 'building') OR artifact_basename IS NOT NULL`)
	if err != nil {
		return err
	}
	inUse := map[string]bool{}
	for _, version := range referenced {
		inUse[version] = true
	}
	features, err := retentionCandidates(db, `
SELECT feature_version, artifact_basename FROM feature_build
WHERE status IN ('superseded', 'failed')
ORDER BY COALESCE(published_at_ms, created_at_ms), feature_version`)
	if err != nil {
		return err
	}
	for _, item := range features {
		if inUse[item.id] {
			continue
		}
		if err := removeArtifact(core, item.basename); err != nil {
			if err := recordCleanupError(db, "feature_build", "feature_version", item.id, err); err != nil {
				return err
			}
			continue
		}
		if err := deleteFeatureGeneration(db, item.id); err != nil {
			return err
		}
	}
	return sweepOrphanArtifacts(db, core, time.Now())
}

type retentionCandidate struct {
	id       string
	basename string
}

func retentionCandidates(db dbx, query string) ([]retentionCandidate, error) {
	rows, err := db.Query(query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []retentionCandidate
	for rows.Next() {
		var id string
		var basename sql.NullString
		if err := rows.Scan(&id, &basename); err != nil {
			return nil, err
		}
		result = append(result, retentionCandidate{id, basename.String})
	}
	return result, rows.Err()
}

func queryStrings(db dbx, query string, args ...any) ([]string, error) {
	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []string
	for rows.Next() {
		var value string
		if err := rows.Scan(&value); err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

// removeArtifact deletes a generation's artifact file; a missing file (or no
// artifact at all) is already the desired state.
func removeArtifact(core, basename string) error {
	if basename == "" {
		return nil
	}
	path, err := artifactPath(core, basename)
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return nil
}

func recordCleanupError(db dbx, table, identifier, id string, cause error) error {
	return withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(),
			fmt.Sprintf(`UPDATE %s SET cleanup_error=? WHERE %s=?`, table, identifier),
			truncateString(cause.Error(), 2000), id)
		return err
	})
}

// retireModel deletes a model row whose artifact is gone. A pre-artifact
// model that still owns core rows only drops its basename: its cascade could
// be millions of rows in one transaction, so legacy compaction (which
// targets retired rows) deletes those in batches first and a later pass
// removes the row.
func retireModel(db dbx, modelID string) error {
	return withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, table := range modelTables {
			var legacy bool
			if err := conn.QueryRowContext(ctx, fmt.Sprintf(
				`SELECT EXISTS(SELECT 1 FROM main.%s WHERE model_id=?)`, quoteIdent(table)),
				modelID).Scan(&legacy); err != nil {
				return err
			}
			if legacy {
				_, err := conn.ExecContext(ctx, `
UPDATE model_version SET artifact_basename=NULL, validation_status='retired', cleanup_error=NULL
WHERE model_id=?`, modelID)
				return err
			}
		}
		_, err := conn.ExecContext(ctx, `DELETE FROM model_version WHERE model_id=?`, modelID)
		return err
	})
}

// deleteFeatureGeneration removes a feature row and any pre-artifact core
// rows of that version. The main. prefix is required: an attached artifact
// shadows these names with read-only temp views.
func deleteFeatureGeneration(db dbx, version string) error {
	return withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, statement := range []string{
			`DELETE FROM main.scene_content_search WHERE feature_version=?`,
			`DELETE FROM main.entity_feature WHERE feature_version=?`,
			`DELETE FROM main.feature_definition WHERE feature_version=?`,
			`DELETE FROM feature_build WHERE feature_version=?`,
		} {
			if _, err := conn.ExecContext(ctx, statement, version); err != nil {
				return err
			}
		}
		return nil
	})
}

// sweepOrphanArtifacts removes recognized artifact and temp files no registry
// row references: temp files of builds that were killed, and artifacts whose
// rows are gone. Files modified within orphanArtifactAge are left alone.
func sweepOrphanArtifacts(db dbx, core string, now time.Time) error {
	referenced, err := queryStrings(db, `
SELECT artifact_basename FROM feature_build WHERE artifact_basename IS NOT NULL
UNION SELECT artifact_basename FROM model_version WHERE artifact_basename IS NOT NULL`)
	if err != nil {
		return err
	}
	keep := map[string]bool{}
	for _, basename := range referenced {
		keep[basename] = true
	}
	for _, path := range recognizedArtifacts(core) {
		if keep[filepath.Base(path)] {
			continue
		}
		info, err := os.Lstat(path)
		if err != nil || now.Sub(info.ModTime()) < orphanArtifactAge {
			continue
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			warnLog("could not remove orphaned artifact: " + err.Error())
		}
	}
	return nil
}
