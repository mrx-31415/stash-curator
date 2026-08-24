// Build-time artifact lifecycle — a port of curator/storage/artifacts.py's
// create_artifact, create_indexes, attach_build_sources, validate_artifact,
// publish_file, discard_artifact, and activate_artifact, used by the model
// build stages. The schemas mirror FEATURE_SCHEMA/MODEL_SCHEMA verbatim so
// the published artifact databases are byte-compatible with Python's.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// artifactFeatureSchema mirrors artifacts.FEATURE_SCHEMA.
const artifactFeatureSchema = `
CREATE TABLE artifact_meta (
    kind TEXT NOT NULL, generation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
) STRICT;
CREATE TABLE feature_definition (
    feature_id TEXT PRIMARY KEY, feature_version TEXT NOT NULL, family TEXT NOT NULL,
    name TEXT NOT NULL, provenance TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE TABLE entity_feature (
    feature_version TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    feature_id TEXT NOT NULL REFERENCES feature_definition(feature_id) ON DELETE CASCADE,
    value REAL NOT NULL, confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (feature_version, entity_type, entity_id, feature_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE scene_content_search (
    feature_version TEXT NOT NULL, feature_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    value REAL NOT NULL, PRIMARY KEY (feature_id, scene_id)
) STRICT, WITHOUT ROWID;
`

// artifactModelSchema mirrors artifacts.MODEL_SCHEMA.
const artifactModelSchema = `
CREATE TABLE artifact_meta (
    kind TEXT NOT NULL, generation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
) STRICT;
CREATE TABLE feature_affinity (
    model_id TEXT NOT NULL, feature_id TEXT NOT NULL,
    affinity REAL NOT NULL CHECK (affinity BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    effective_support REAL NOT NULL CHECK (effective_support >= 0),
    distinct_scene_count INTEGER NOT NULL CHECK (distinct_scene_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (model_id, feature_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE direct_scene_state (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    effective_evidence REAL NOT NULL CHECK (effective_evidence >= 0),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    residual REAL NOT NULL CHECK (residual BETWEEN -2 AND 2),
    PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_score (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    general_appeal REAL NOT NULL CHECK (general_appeal BETWEEN -1 AND 1),
    direct_appeal REAL NOT NULL CHECK (direct_appeal BETWEEN -1 AND 1),
    direct_confidence REAL NOT NULL CHECK (direct_confidence BETWEEN 0 AND 1),
    appeal REAL NOT NULL CHECK (appeal BETWEEN -1 AND 1),
    current_fit REAL NOT NULL CHECK (current_fit BETWEEN -1 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    metadata_confidence REAL NOT NULL CHECK (metadata_confidence BETWEEN 0 AND 1),
    recovery REAL NOT NULL CHECK (recovery BETWEEN 0 AND 1),
    components_json TEXT NOT NULL,
    classification_json TEXT NOT NULL DEFAULT '{}',
    eligibility_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (model_id, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_neighbor (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 4), neighbor_scene_id TEXT NOT NULL,
    similarity REAL NOT NULL, weight REAL NOT NULL, outcome REAL NOT NULL,
    PRIMARY KEY (model_id, scene_id, rank)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_performer_edge (
    model_id TEXT NOT NULL, performer_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 0 AND 2),
    similar_performer_id TEXT NOT NULL,
    similarity REAL NOT NULL, affinity REAL NOT NULL, confidence REAL NOT NULL,
    PRIMARY KEY (model_id, performer_id, rank)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_reason (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    reason_index INTEGER NOT NULL CHECK (reason_index >= 0), reason_code TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('positive','negative','unknown','neutral')),
    magnitude REAL NOT NULL CHECK (magnitude BETWEEN 0 AND 1),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    subject_type TEXT, subject_id TEXT,
    visibility TEXT NOT NULL CHECK (visibility IN ('standard','sensitive','private')),
    provenance TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, scene_id, reason_index)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_scene_lane (
    model_id TEXT NOT NULL, scene_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('for_you','best_bets','revisit','stretch','blind_spots','dormant')),
    subtype TEXT, lane_value REAL NOT NULL,
    qualification_json TEXT NOT NULL DEFAULT '{}', appeal REAL,
    PRIMARY KEY (model_id, scene_id, lane)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_candidate_cache (
    model_id TEXT NOT NULL, lane TEXT NOT NULL CHECK (lane IN ('best_bets','revisit','stretch','blind_spots','dormant')),
    candidates_json TEXT NOT NULL, candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0), PRIMARY KEY (model_id, lane)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_order (
    model_id TEXT NOT NULL, lane TEXT NOT NULL CHECK (lane IN ('for_you','best_bets','revisit','stretch','blind_spots','dormant')),
    ordering TEXT NOT NULL CHECK (ordering IN ('score_first','varied')),
    position INTEGER NOT NULL CHECK (position >= 0), scene_id TEXT NOT NULL,
    source_lane TEXT NOT NULL CHECK (source_lane IN ('best_bets','revisit','stretch','blind_spots','dormant')),
    utility REAL NOT NULL, ranking_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (model_id, lane, ordering, position),
    UNIQUE (model_id, lane, ordering, scene_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_lane_order_state (
    model_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
) STRICT, WITHOUT ROWID;
CREATE TABLE model_entity_dormancy (
    model_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('performer','tag','studio')),
    entity_id TEXT NOT NULL, last_played_at_ms INTEGER NOT NULL,
    positive_strength REAL NOT NULL, play_count INTEGER NOT NULL CHECK (play_count >= 0),
    distinct_scene_count INTEGER NOT NULL CHECK (distinct_scene_count >= 0),
    PRIMARY KEY (model_id, entity_type, entity_id)
) STRICT;
`

// splitSchemaStatements splits a schema script on top-level semicolons.
func splitSchemaStatements(script string) []string {
	var statements []string
	var buffer strings.Builder
	depth := 0
	for _, r := range script {
		switch r {
		case '(':
			depth++
		case ')':
			if depth > 0 {
				depth--
			}
		case ';':
			if depth == 0 {
				statement := strings.TrimSpace(buffer.String())
				if statement != "" {
					statements = append(statements, statement)
				}
				buffer.Reset()
				continue
			}
		}
		buffer.WriteRune(r)
	}
	if statement := strings.TrimSpace(buffer.String()); statement != "" {
		statements = append(statements, statement)
	}
	return statements
}

// createArtifact mirrors artifacts.create_artifact: a temp artifact database
// with artifact_meta and the kind's schema. Returns the open connection, the
// temporary path, and the final path.
func createArtifact(corePath, kind, identifier string) (dbx, string, string, error) {
	expected := "feature-" + identifier
	if kind == "model" {
		expected = identifier
	}
	final, err := artifactPath(corePath, expected+".sqlite3")
	if err != nil {
		return nil, "", "", err
	}
	if err := os.MkdirAll(filepath.Dir(final), 0o700); err != nil {
		return nil, "", "", err
	}
	temporary, err := artifactTempPath(corePath, "."+expected+"."+strings.ReplaceAll(uuid4(), "-", "")+".tmp")
	if err != nil {
		return nil, "", "", err
	}
	db, err := openDatabase(temporary, false, nil)
	if err != nil {
		return nil, "", "", err
	}
	for _, pragma := range []string{"PRAGMA journal_mode = OFF", "PRAGMA synchronous = OFF"} {
		if _, err := db.Exec(pragma); err != nil {
			db.Close()
			os.Remove(temporary)
			return nil, "", "", err
		}
	}
	if _, err := db.Exec(fmt.Sprintf("PRAGMA user_version=%d", artifactSchemaVersion)); err != nil {
		db.Close()
		os.Remove(temporary)
		return nil, "", "", err
	}
	schema := artifactFeatureSchema
	if kind == "model" {
		schema = artifactModelSchema
	}
	for _, statement := range splitSchemaStatements(schema) {
		if _, err := db.Exec(statement); err != nil {
			db.Close()
			os.Remove(temporary)
			return nil, "", "", err
		}
	}
	if _, err := db.Exec(
		`INSERT INTO artifact_meta(kind, generation_id, schema_version) VALUES (?, ?, ?)`,
		kind, identifier, artifactSchemaVersion); err != nil {
		db.Close()
		os.Remove(temporary)
		return nil, "", "", err
	}
	return db, temporary, final, nil
}

// artifactCreateIndexes mirrors artifacts.create_indexes.
func artifactCreateIndexes(db dbx, kind string) error {
	if kind == "feature" {
		for _, statement := range []string{
			`CREATE INDEX entity_feature_feature_idx ON entity_feature(feature_id)`,
			`CREATE INDEX scene_content_search_scene_idx ON scene_content_search(feature_version, scene_id, feature_id)`,
		} {
			if _, err := db.Exec(statement); err != nil {
				return err
			}
		}
		return nil
	}
	for _, statement := range []string{
		`CREATE INDEX model_scene_score_fit_idx ON model_scene_score(model_id, current_fit DESC)`,
		`CREATE INDEX model_scene_score_prune_idx ON model_scene_score(model_id, appeal, confidence, scene_id)`,
		`CREATE INDEX model_scene_lane_value_idx ON model_scene_lane(model_id, lane, lane_value DESC, scene_id)`,
		`CREATE INDEX model_scene_lane_appeal_idx ON model_scene_lane(model_id, scene_id, appeal)`,
	} {
		if _, err := db.Exec(statement); err != nil {
			return err
		}
	}
	return nil
}

// artifactValidate mirrors artifacts.validate_artifact.
func artifactValidate(db dbx, kind string, counts map[string]int64, checkIntegrity bool) (jVal, error) {
	integrity := "skipped"
	if checkIntegrity {
		var check string
		if err := db.QueryRow(`PRAGMA quick_check`).Scan(&check); err != nil {
			return jvNull(), err
		}
		integrity = check
	}
	var schemaVersion int64
	if err := db.QueryRow(`PRAGMA user_version`).Scan(&schemaVersion); err != nil {
		return jvNull(), err
	}
	if (checkIntegrity && integrity != "ok") || schemaVersion != artifactSchemaVersion {
		return jvNull(), fmt.Errorf("%s artifact validation failed: integrity=%s, schema=%d",
			kind, integrity, schemaVersion)
	}
	countsJSON := jvObj()
	for _, key := range sortedMapKeys(counts) {
		countsJSON.set(key, jvInt(counts[key]))
	}
	return jvObj(
		jvKey("integrity", jvStr(integrity)),
		jvKey("schema_version", jvInt(schemaVersion)),
		jvKey("counts", countsJSON),
	), nil
}

func sortedMapKeys(values map[string]int64) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// publishArtifactFile mirrors artifacts.publish_file: close the artifact,
// atomically rename the temp over the final path, return the size.
func publishArtifactFile(db dbx, temporary, final string) (int64, error) {
	if err := db.Close(); err != nil {
		return 0, err
	}
	if err := os.Rename(temporary, final); err != nil {
		return 0, err
	}
	info, err := os.Stat(final)
	if err != nil {
		return 0, err
	}
	return info.Size(), nil
}

// discardArtifact mirrors artifacts.discard_artifact.
func discardArtifact(db dbx, temporary string) {
	if db != nil {
		db.Close()
	}
	if temporary != "" {
		if err := os.Remove(temporary); err != nil && !os.IsNotExist(err) {
			warnLog("could not remove artifact temp: " + err.Error())
		}
	}
}

// activateArtifact mirrors artifacts.activate_artifact: re-attach a published
// artifact as the active generation and recreate the shadowing temp views.
func activateArtifact(db dbx, kind, path string) error {
	alias := kind + "_generation"
	tables := featureTables
	if kind == "model" {
		tables = modelTables
	}
	// Drop any existing views for the owned tables, then detach.
	for _, table := range tables {
		if _, err := db.Exec(fmt.Sprintf(`DROP VIEW IF EXISTS temp.%s`, quoteIdent(table))); err != nil {
			return err
		}
	}
	var attached int
	err := db.QueryRow(`SELECT count(*) FROM pragma_database_list WHERE name=?`, alias).Scan(&attached)
	if err != nil {
		return err
	}
	if attached > 0 {
		if _, err := db.Exec(`DETACH DATABASE ` + alias); err != nil {
			return err
		}
	}
	if _, err := db.Exec(`ATTACH DATABASE ? AS `+alias, readonlyArtifactURI(path, true)); err != nil {
		return err
	}
	var schemaVersion int
	if err := db.QueryRow(`PRAGMA ` + alias + `.user_version`).Scan(&schemaVersion); err != nil {
		return err
	}
	if !supportedArtifactSchemaVersions[schemaVersion] {
		return fmt.Errorf("unsupported active artifact schema: %s", filepath.Base(path))
	}
	tables, err = artifactTables(db, alias, tables)
	if err != nil {
		return err
	}
	for _, table := range tables {
		if _, err := db.Exec(fmt.Sprintf(`CREATE TEMP VIEW %s AS SELECT * FROM %s.%s`,
			quoteIdent(table), alias, quoteIdent(table))); err != nil {
			return err
		}
	}
	return nil
}
