// Artifact attach/views — a port of curator/storage/artifacts.py's
// attach_active_artifacts and attach_build_sources. Published feature/model
// generations are ATTACHed read-only (immutable) and their tables shadow the
// core-schema copies through TEMP VIEWs, so queries read the published
// artifact uniformly. Table lists and schema constants mirror the Python
// module exactly; views are only created over tables the artifact actually
// has, keeping old-schema artifacts safe.
package main

import (
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const artifactSchemaVersion = 3

var supportedArtifactSchemaVersions = map[int]bool{1: true, 2: true, 3: true}

var featureTables = []string{"feature_definition", "entity_feature", "scene_content_search"}

var modelTables = []string{
	"feature_affinity",
	"direct_scene_state",
	"model_scene_score",
	"model_scene_neighbor",
	"model_performer_edge",
	"model_scene_reason",
	"model_scene_lane",
	"model_lane_candidate_cache",
	"model_lane_order",
	"model_lane_order_state",
	"model_entity_dormancy",
}

// finalArtifactName matches artifacts._FINAL_NAME.
var finalArtifactName = regexp.MustCompile(`^(feature-fv-[0-9a-f]{20}|model-[0-9a-f]{20})\.sqlite3$`)

// coreDatabasePath mirrors artifacts.database_path: the main database file.
func coreDatabasePath(db dbx) (string, error) {
	rows, err := db.Query(`PRAGMA database_list`)
	if err != nil {
		return "", err
	}
	defer rows.Close()
	for rows.Next() {
		var name, file string
		var seq int
		if err := rows.Scan(&seq, &name, &file); err != nil {
			return "", err
		}
		if name == "main" {
			if file == "" {
				return "", fmt.Errorf("generation artifacts require a file-backed core database")
			}
			return realpath(file), nil
		}
	}
	return "", fmt.Errorf("no main database")
}

// cacheDirectory mirrors artifacts.cache_directory: <stem>-derived next to
// the core database (Path.with_name(f"{stem}-derived"), where stem drops only
// the final suffix).
func cacheDirectory(corePath string) string {
	stem := strings.TrimSuffix(filepath.Base(corePath), filepath.Ext(corePath))
	return filepath.Join(filepath.Dir(corePath), stem+"-derived")
}

// artifactPath mirrors artifacts.artifact_path: validates the basename and
// rejects symlink escapes.
func artifactPath(corePath, basename string) (string, error) {
	if filepath.Base(basename) != basename || !finalArtifactName.MatchString(basename) {
		return "", fmt.Errorf("invalid artifact basename: %s", basename)
	}
	directory := cacheDirectory(corePath)
	if info, err := os.Lstat(directory); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return "", fmt.Errorf("unsafe derived-cache directory: %s", directory)
		}
	}
	path := filepath.Join(directory, basename)
	if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("unsafe artifact path: %s", basename)
	}
	return path, nil
}

// tempArtifactName mirrors artifacts._TEMP_NAME.
var tempArtifactName = regexp.MustCompile(`^\.(feature-fv-[0-9a-f]{20}|model-[0-9a-f]{20})\.[0-9a-f]{32}\.tmp$`)

// artifactTempPath mirrors artifacts.artifact_path with temporary=True.
func artifactTempPath(corePath, basename string) (string, error) {
	if filepath.Base(basename) != basename || !tempArtifactName.MatchString(basename) {
		return "", fmt.Errorf("invalid artifact basename: %s", basename)
	}
	directory := cacheDirectory(corePath)
	if info, err := os.Lstat(directory); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return "", fmt.Errorf("unsafe derived-cache directory: %s", directory)
		}
	}
	path := filepath.Join(directory, basename)
	if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("unsafe artifact path: %s", basename)
	}
	return path, nil
}

// readonlyArtifactURI mirrors artifacts._readonly_uri with immutable=1 for
// published artifacts.
func readonlyArtifactURI(path string, immutable bool) string {
	suffix := ""
	if immutable {
		suffix = "&immutable=1"
	}
	u := url.URL{Scheme: "file", Path: path}
	u.RawQuery = "mode=ro" + suffix
	return u.String()
}

// attachActiveArtifacts mirrors artifacts.attach_active_artifacts: attach the
// published feature/model generations and create the shadowing temp views.
func attachActiveArtifacts(db dbx) error {
	present, err := tableColumns(db, "feature_build")
	if err != nil {
		return err
	}
	if _, ok := present["artifact_basename"]; !ok {
		return nil
	}
	corePath, err := coreDatabasePath(db)
	if err != nil {
		return err
	}
	type attach struct {
		alias  string
		tables []string
		table  string
		query  string
	}
	attaches := []attach{
		{"feature_generation", featureTables, "feature_build",
			`SELECT artifact_basename FROM feature_build WHERE status='published' AND validation_status='valid'`},
		{"model_generation", modelTables, "model_version",
			`SELECT artifact_basename FROM model_version WHERE status='published' AND validation_status='valid'`},
	}
	for _, a := range attaches {
		var basename sql.NullString
		err := db.QueryRow(a.query).Scan(&basename)
		if err == sql.ErrNoRows {
			continue
		}
		if err != nil {
			return err
		}
		if !basename.Valid || basename.String == "" {
			continue
		}
		path, err := artifactPath(corePath, basename.String)
		if err != nil {
			return err
		}
		if _, err := os.Stat(path); err != nil {
			return fmt.Errorf("active artifact is missing: %s", filepath.Base(path))
		}
		if _, err := db.Exec(`ATTACH DATABASE ? AS `+a.alias, readonlyArtifactURI(path, true)); err != nil {
			return err
		}
		var schemaVersion int
		if err := db.QueryRow(`PRAGMA ` + a.alias + `.user_version`).Scan(&schemaVersion); err != nil {
			return err
		}
		if !supportedArtifactSchemaVersions[schemaVersion] {
			return fmt.Errorf("unsupported active artifact schema: %s", filepath.Base(path))
		}
		tables, err := artifactTables(db, a.alias, a.tables)
		if err != nil {
			return err
		}
		for _, table := range tables {
			if _, err := db.Exec(fmt.Sprintf(`CREATE TEMP VIEW %s AS SELECT * FROM %s.%s`,
				quoteIdent(table), a.alias, quoteIdent(table))); err != nil {
				return err
			}
		}
	}
	return nil
}

// attachBuildSources mirrors artifacts.attach_build_sources: attach the core
// database (read-only, mutable) plus the feature generation, shadowing every
// non-owned core table and the feature tables with temp views.
func attachBuildSources(db dbx, corePath, featurePath string) error {
	owned := make(map[string]bool, len(modelTables)+len(featureTables))
	for _, table := range modelTables {
		owned[table] = true
	}
	for _, table := range featureTables {
		owned[table] = true
	}
	if _, err := db.Exec(`ATTACH DATABASE ? AS core`, readonlyArtifactURI(corePath, false)); err != nil {
		return err
	}
	if _, err := db.Exec(`ATTACH DATABASE ? AS feature_generation`, readonlyArtifactURI(featurePath, true)); err != nil {
		return err
	}
	rows, err := db.Query(`SELECT name FROM core.sqlite_master WHERE type='table' ORDER BY name`)
	if err != nil {
		return err
	}
	// Collect the names first and close the rows before executing the view
	// creation: the op connection is pinned to a single sqlite connection
	// (mirroring Python), so an Exec while the rows are still open would
	// deadlock against itself.
	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			rows.Close()
			return err
		}
		if owned[name] || strings.HasPrefix(name, "sqlite_") {
			continue
		}
		names = append(names, name)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, name := range names {
		if _, err := db.Exec(fmt.Sprintf(`CREATE TEMP VIEW %s AS SELECT * FROM core.%s`,
			quoteIdent(name), quoteIdent(name))); err != nil {
			return err
		}
	}
	for _, table := range featureTables {
		if _, err := db.Exec(fmt.Sprintf(`CREATE TEMP VIEW %s AS SELECT * FROM feature_generation.%s`,
			quoteIdent(table), quoteIdent(table))); err != nil {
			return err
		}
	}
	return nil
}

// artifactTables mirrors artifacts._artifact_tables: only the tables the
// attached artifact actually has.
func artifactTables(db dbx, alias string, tables []string) ([]string, error) {
	rows, err := db.Query(`SELECT name FROM ` + alias + `.sqlite_master WHERE type='table'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	present := make(map[string]bool)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		present[name] = true
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var result []string
	for _, table := range tables {
		if present[table] {
			result = append(result, table)
		}
	}
	return result, nil
}

// tableColumns returns the column names of a table via PRAGMA table_info.
func tableColumns(db dbx, table string) (map[string]bool, error) {
	rows, err := db.Query(`PRAGMA table_info(` + quoteIdent(table) + `)`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]bool)
	for rows.Next() {
		var cid, notnull, pk int
		var name, typ string
		var dflt any
		if err := rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk); err != nil {
			return nil, err
		}
		result[name] = true
	}
	return result, rows.Err()
}

// quoteIdent mirrors artifacts._quote.
func quoteIdent(identifier string) string {
	return `"` + strings.ReplaceAll(identifier, `"`, `""`) + `"`
}
