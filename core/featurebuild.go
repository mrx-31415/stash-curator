// Feature build — a port of curator/features/builder.py's FeatureBuilder:
// the deterministic feature-version derivation, tag-role resolution, scene
// and performer feature construction, and the artifact/sidecar publication.
// The published feature artifact and the sidecar tag_role /
// tag_taxonomy_match / feature_build rows must be byte-identical to Python's.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Feature-config constants mirroring FeatureConfig defaults (config.py).
const (
	markerWeight = 0.45
	parentWeight = 0.35
	idfStrength  = 0.5
	idfCap       = 2.5
	oneOffPrior  = 2.0
)

// Description-term constants mirroring features/builder.py.
const (
	descMinDF            = 5
	descMaxDFFraction    = 0.70
	descMaxTermsPerScene = 15
	descBoost            = 3.0
)

var descTokenRegex = regexp.MustCompile(`[a-zA-Z]{3,}`)

// descStopwords mirrors features/builder.py _DESCRIPTION_STOPWORDS.
var descStopwords = map[string]bool{
	"the": true, "a": true, "an": true, "is": true, "are": true, "was": true, "were": true, "be": true,
	"been": true, "being": true, "have": true, "has": true, "had": true, "do": true, "does": true, "did": true,
	"will": true, "would": true, "shall": true, "should": true, "may": true, "might": true, "must": true, "can": true,
	"could": true, "i": true, "me": true, "my": true, "we": true, "our": true, "you": true, "your": true,
	"he": true, "him": true, "his": true, "she": true, "her": true, "it": true, "its": true, "they": true,
	"them": true, "their": true, "this": true, "that": true, "these": true, "those": true, "and": true, "but": true,
	"or": true, "nor": true, "not": true, "so": true, "if": true, "then": true, "else": true, "when": true,
	"up": true, "down": true, "in": true, "out": true, "on": true, "off": true, "over": true, "under": true,
	"again": true, "further": true, "once": true, "here": true, "there": true, "all": true, "both": true, "each": true,
	"few": true, "more": true, "most": true, "other": true, "some": true, "such": true, "no": true, "only": true,
	"own": true, "same": true, "just": true, "about": true, "after": true, "also": true, "as": true, "at": true,
	"before": true, "between": true, "by": true, "during": true, "for": true, "from": true, "into": true, "of": true,
	"than": true, "to": true, "very": true, "with": true, "well": true, "get": true, "got": true, "go": true,
	"goes": true, "back": true, "still": true, "too": true, "way": true, "even": true, "now": true, "new": true,
	"see": true, "take": true, "make": true, "like": true, "come": true, "know": true, "want": true, "think": true,
	"really": true, "much": true, "one": true, "two": true, "who": true, "how": true, "which": true, "what": true,
	"where": true, "why": true, "herself": true, "himself": true, "itself": true, "themselves": true, "any": true, "anything": true,
	"everyone": true, "everything": true, "let": true, "scene": true, "watch": true, "enjoy": true, "don": true, "doesn": true,
	"isn": true, "wasn": true, "weren": true, "aren": true, "couldn": true, "wouldn": true, "shouldn": true, "haven": true,
	"hasn": true, "hadn": true, "https": true, "http": true, "www": true, "com": true, "org": true, "net": true,
}

// featureRow mirrors features/builder.py _Feature.
type featureRow struct {
	entityType string
	entityID   string
	family     string
	name       string
	value      float64
	confidence float64
	metadata   jVal
}

// fingerprintTable mirrors features/builder._fingerprint_table: rows are
// JSON-encoded in batches of 1000 with ensure_ascii=False.
func fingerprintTable(db dbx, digest interface{ Write([]byte) (int, error) }, label, statement string) error {
	if _, err := digest.Write([]byte(label + "\x00")); err != nil {
		return err
	}
	batch := jvArr()
	flush := func() error {
		if len(batch.arr) == 0 {
			return nil
		}
		if _, err := digest.Write([]byte(batch.marshalCompactUTF8())); err != nil {
			return err
		}
		batch = jvArr()
		return nil
	}
	rows, err := db.Query(statement)
	if err != nil {
		return err
	}
	for rows.Next() {
		columns, err := rows.Columns()
		if err != nil {
			rows.Close()
			return err
		}
		values := make([]any, len(columns))
		scanned := make([]any, len(columns))
		for i := range columns {
			scanned[i] = &values[i]
		}
		if err := rows.Scan(scanned...); err != nil {
			rows.Close()
			return err
		}
		row := jvArr()
		for _, value := range values {
			row.arr = append(row.arr, fingerprintValue(value))
		}
		batch.arr = append(batch.arr, row)
		if len(batch.arr) == 1_000 {
			if err := flush(); err != nil {
				rows.Close()
				return err
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if err := flush(); err != nil {
		return err
	}
	if _, err := digest.Write([]byte("\n")); err != nil {
		return err
	}
	return nil
}

// fingerprintValue maps a scanned SQL value to its Python JSON form
// (str/int/float/None).
func fingerprintValue(value any) jVal {
	switch t := value.(type) {
	case nil:
		return jvNull()
	case string:
		return jvStr(t)
	case []byte:
		return jvStr(string(t))
	case int64:
		return jvInt(t)
	case float64:
		return jvFloat(t)
	case bool:
		return jvBool(t)
	}
	return jvNull()
}

// featureBuildPayload is the feature-build kernel stage input.
type featureBuildPayload struct {
	DB    string `json:"db"`
	NowMs int64  `json:"now_ms"`
}

// runFeatureBuild serves the "feature-build" kernel command: run the
// FeatureBuilder pipeline against a writable sidecar and emit the resulting
// feature version as NDJSON.
func runFeatureBuild() {
	var payload featureBuildPayload
	if err := json.NewDecoder(os.Stdin).Decode(&payload); err != nil {
		fail("feature-build: invalid payload: %v", err)
	}
	db, err := openDatabase(payload.DB, false, nil)
	if err != nil {
		fail("feature-build: open %s: %v", payload.DB, err)
	}
	defer db.Close()
	if err := migrate(db, payload.NowMs); err != nil {
		fail("feature-build: migrate: %v", err)
	}
	version, reused, err := featureBuild(db, payload.NowMs, func(fraction float64) {
		_ = writeJSONLine(map[string]any{"progress": fraction})
	})
	if err != nil {
		fail("feature-build: %v", err)
	}
	if err := writeJSONLine(map[string]any{"result": map[string]any{
		"feature_version": version,
		"reused":          reused,
	}}); err != nil {
		fail("feature-build: write result: %v", err)
	}
}

// runModelBuild serves the "model-build" kernel command: run the full
// PreferenceModelBuilder pipeline against a writable sidecar and emit the
// model id as NDJSON.
func runModelBuild() {
	var payload featureBuildPayload
	if err := json.NewDecoder(os.Stdin).Decode(&payload); err != nil {
		fail("model-build: invalid payload: %v", err)
	}
	db, err := openDatabase(payload.DB, false, nil)
	if err != nil {
		fail("model-build: open %s: %v", payload.DB, err)
	}
	defer db.Close()
	if err := migrate(db, payload.NowMs); err != nil {
		fail("model-build: migrate: %v", err)
	}
	result, err := modelBuild(db, payload.NowMs, func(processed, total int) {
		fraction := 1.0
		if total > 0 {
			fraction = float64(processed) / float64(total)
		}
		_ = writeJSONLine(map[string]any{"progress": fraction})
	})
	if err != nil {
		fail("model-build: %v", err)
	}
	if err := writeJSONLine(map[string]any{"result": map[string]any{
		"model_id":        result.modelID,
		"feature_version": result.featureVersion,
		"reused":          result.reused,
		"scene_count":     result.sceneCount,
	}}); err != nil {
		fail("model-build: write result: %v", err)
	}
}

// featureSourceFingerprint mirrors FeatureBuilder._source_fingerprint.
func featureSourceFingerprint(db dbx) (string, error) {
	digest := sha256.New()
	for _, spec := range []struct {
		label     string
		statement string
	}{
		{"source_tag", "SELECT tag_id, name FROM source_tag ORDER BY tag_id"},
		{"source_performer", `SELECT performer_id, birthdate, ethnicity, eye_color, hair_color,
       height_cm, weight_kg, measurements, augmentation, tattoos, piercings
FROM source_performer ORDER BY performer_id`},
		{"source_scene", "SELECT scene_id, scene_date, studio_id FROM source_scene ORDER BY scene_id"},
		{"scene_performer", "SELECT scene_id, performer_id FROM scene_performer ORDER BY scene_id, performer_id"},
		{"scene_tag", "SELECT scene_id, tag_id, provenance FROM scene_tag ORDER BY scene_id, tag_id, provenance"},
		{"scene_marker", "SELECT marker_id, scene_id, primary_tag_id FROM scene_marker ORDER BY marker_id"},
		{"marker_tag", "SELECT marker_id, tag_id FROM marker_tag ORDER BY marker_id, tag_id"},
		{"tag_parent", "SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id"},
		{"source_tag_stash_id", "SELECT tag_id, endpoint, stash_id FROM source_tag_stash_id ORDER BY tag_id, endpoint"},
	} {
		if err := fingerprintTable(db, digest, spec.label, spec.statement); err != nil {
			return "", err
		}
	}
	var snapshotID string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_snapshot_id'`).Scan(&snapshotID)
	if err != nil && err != sql.ErrNoRows {
		return "", err
	}
	if _, err := digest.Write([]byte(fmt.Sprintf("taxonomy_snapshot\x00%s\n", snapshotID))); err != nil {
		return "", err
	}
	if _, err := digest.Write([]byte("taxonomy_category_roles\x00" + categoryRoleFingerprint() + "\n")); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

// tagRoleResult mirrors features/tag_roles.py TagRoleResult.
type tagRoleResult struct {
	role     string
	reason   string
	taxonomy taxonomyMatch
}

// tagRules mirror FeatureConfig.tag_rules (config.py), in order.
var tagRules = []struct{ match, pattern, role string }{
	{"prefix", "[Workflow:", "workflow_administrative"},
	{"prefix", "[Technical:", "quality_technical"},
	{"exact", "[Curator: Ignore]", "ignored"},
	{"regex", `\b(?:blonde?|brunette|redhead|black hair|brown hair|dyed hair)\b`, "performer_attribute"},
	{"regex", `\b(?:blue|brown|green|hazel|gr[ae]y) eyes?\b`, "performer_attribute"},
	{"regex", `\b(?:caucasian|asian|latina?|ebony)\b|\b(?:black|white|pale|medium|dark) skin\b`, "performer_attribute"},
	{"regex", `\b(?:big|small|medium|huge|tiny) (?:ass|tits|boobs|breasts)\b`, "performer_attribute"},
	{"regex", `\b(?:fake|natural) (?:tits|boobs|breasts)\b|\baugmentation\b`, "performer_attribute"},
	{"regex", `\b(?:tattoos?|piercings?)\b`, "performer_attribute"},
	{"regex", `^(?:athletic(?: body| woman)?|bubble butt|trimmed)$`, "performer_attribute"},
}

var compiledTagRules = func() []struct {
	match, pattern, role string
	compiled             *regexp.Regexp
} {
	out := make([]struct {
		match, pattern, role string
		compiled             *regexp.Regexp
	}, len(tagRules))
	for i, rule := range tagRules {
		var compiled *regexp.Regexp
		if rule.match == "regex" {
			compiled = regexp.MustCompile(rule.pattern)
		}
		out[i] = struct {
			match, pattern, role string
			compiled             *regexp.Regexp
		}{rule.match, rule.pattern, rule.role, compiled}
	}
	return out
}()

// resolveTagRole mirrors TagRoleResolver.resolve.
func resolveTagRole(tagID, name string, taxonomy taxonomyMatch) tagRoleResult {
	folded := strings.ToLower(strings.TrimSpace(name))
	for _, rule := range compiledTagRules {
		if rule.match == "regex" {
			continue
		}
		applies := (rule.match == "exact" && folded == strings.ToLower(rule.pattern)) ||
			(rule.match == "prefix" && strings.HasPrefix(folded, strings.ToLower(rule.pattern)))
		if applies {
			return tagRoleResult{rule.role, "configured_" + rule.match + "_rule:" + rule.pattern, taxonomy}
		}
	}
	if taxonomy.role != "" {
		categoryID := taxonomy.externalCategoryID
		if categoryID == "" {
			categoryID = "None"
		}
		return tagRoleResult{taxonomy.role,
			fmt.Sprintf("stashdb_%s:%s", taxonomy.method, categoryID), taxonomy}
	}
	for _, rule := range compiledTagRules {
		if rule.match != "regex" || rule.compiled == nil {
			continue
		}
		if rule.compiled.MatchString(strings.TrimSpace(name)) {
			return tagRoleResult{rule.role, "configured_regex_rule:" + rule.pattern, taxonomy}
		}
	}
	if strings.HasPrefix(strings.TrimSpace(name), "[") && strings.HasSuffix(strings.TrimSpace(name), "]") {
		return tagRoleResult{"workflow_administrative", "bracketed_automation_default", taxonomy}
	}
	return tagRoleResult{"content", "content_default", taxonomy}
}

// resolveTagRoles mirrors FeatureBuilder._resolve_tag_roles.
func resolveTagRoles(db dbx) (map[string]tagRoleResult, error) {
	index, err := newTaxonomyIndex(db)
	if err != nil {
		return nil, err
	}
	type tagRow struct {
		tagID string
		name  string
	}
	rows, err := db.Query(`SELECT tag_id, name FROM source_tag ORDER BY tag_id`)
	if err != nil {
		return nil, err
	}
	var tags []tagRow
	for rows.Next() {
		var tagID, name string
		if err := rows.Scan(&tagID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		tags = append(tags, tagRow{tagID, name})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	roles := make(map[string]tagRoleResult, len(tags))
	for _, tag := range tags {
		match, err := index.resolve(db, tag.tagID, tag.name)
		if err != nil {
			return nil, err
		}
		roles[tag.tagID] = resolveTagRole(tag.tagID, tag.name, match)
	}
	return roles, nil
}

// parseMeasurements mirrors features/measurements.py parse_measurements.
var measurementPattern = regexp.MustCompile(`^\s*(\d{2,3})\s*([A-Za-z]{1,3})?\s*[-/]\s*(\d{2,3}(?:\.\d+)?)\s*[-/]\s*(\d{2,3}(?:\.\d+)?)\s*$`)

// bodyMeasurements mirrors BodyMeasurements on the fields the build needs.
type bodyMeasurements struct {
	bandInches  float64
	cupIndex    float64
	hasCup      bool
	waistInches float64
	hipInches   float64
	waistToHip  float64
	confidence  float64
}

func parseMeasurements(value string) *bodyMeasurements {
	if value == "" {
		return nil
	}
	match := measurementPattern.FindStringSubmatch(value)
	if match == nil {
		return nil
	}
	band, _ := strconv.ParseFloat(match[1], 64)
	waist, _ := strconv.ParseFloat(match[3], 64)
	hips, _ := strconv.ParseFloat(match[4], 64)
	if !(20 <= band && band <= 70) || !(15 <= waist && waist <= 70) || !(20 <= hips && hips <= 80) {
		return nil
	}
	cupRaw := strings.ToUpper(match[2])
	cup, hasCup := cupAliases[cupRaw]
	confidence := 0.95
	if cupRaw == "DD" || cupRaw == "DDD" {
		confidence = 0.85
	}
	if !hasCup {
		confidence = 0.75
	}
	return &bodyMeasurements{
		bandInches:  band,
		cupIndex:    cup,
		hasCup:      hasCup,
		waistInches: waist,
		hipInches:   hips,
		waistToHip:  waist / hips,
		confidence:  confidence,
	}
}

// presenceCategory mirrors features/measurements.py presence_category.
func presenceCategory(value string) string {
	folded := strings.ToLower(strings.TrimSpace(value))
	if folded == "none" || folded == "no" || folded == "n" || folded == "false" {
		return "absent"
	}
	return "present"
}

// sceneFeatures mirrors FeatureBuilder._scene_features.
// sceneFeatureRows constructs the content-family feature rows for one scene
// (the FeatureBuilder._scene_features per-scene body): weighted tag +
// description-term values, normalized, with confidence from document
// frequency. Every input is a precomputed read-only map, so the scene pass
// is row-independent: fixed-chunk parallel processing yields identical rows.
func sceneFeatureRows(sceneID string, baseVectors map[string]map[string]float64,
	documentFrequency map[string]int64, descByScene map[string][]string,
	descIDF map[string]float64, descDocumentFrequency map[string]int64, tagNames map[string]string,
	roles map[string]tagRoleResult, total int) []featureRow {
	weighted := map[string]float64{}
	for tagID, base := range baseVectors[sceneID] {
		frequency := documentFrequency[tagID]
		rarity := math.Min(idfCap, 1+idfStrength*math.Log(float64(total+1)/float64(frequency+1)))
		shrinkage := float64(frequency) / (float64(frequency) + oneOffPrior)
		weighted[tagID] = base * rarity * shrinkage
	}
	if terms, ok := descByScene[sceneID]; ok {
		limit := descMaxTermsPerScene
		if len(terms) < limit {
			limit = len(terms)
		}
		for _, term := range terms[:limit] {
			idf := descIDF[term]
			if idf <= 0 {
				continue
			}
			freq := descDocumentFrequency[term]
			if freq == 0 {
				freq = 1
			}
			weighted["desc:"+term] = descBoost * idf / (float64(freq) + oneOffPrior)
		}
	}
	var normSquared float64
	for _, value := range weighted {
		normSquared += value * value
	}
	norm := math.Sqrt(normSquared)
	if norm == 0 {
		norm = 1.0
	}
	var features []featureRow
	var tagKeys []string
	for key := range weighted {
		if !strings.HasPrefix(key, "desc:") {
			tagKeys = append(tagKeys, key)
		}
	}
	sort.Strings(tagKeys)
	for _, tagID := range tagKeys {
		frequency := documentFrequency[tagID]
		confidence := math.Min(1.0, float64(frequency)/3)
		features = append(features, featureRow{
			entityType: "scene",
			entityID:   sceneID,
			family:     "content",
			name:       "tag:" + tagID,
			value:      weighted[tagID] / norm,
			confidence: confidence,
			metadata: jvObj(
				jvKey("tag_id", jvStr(tagID)),
				jvKey("tag_name", jvStr(tagNames[tagID])),
				jvKey("document_frequency", jvInt(frequency)),
				jvKey("role_reason", jvStr(roles[tagID].reason)),
			),
		})
	}
	var descKeys []string
	for key := range weighted {
		if strings.HasPrefix(key, "desc:") {
			descKeys = append(descKeys, key)
		}
	}
	sort.Strings(descKeys)
	for _, key := range descKeys {
		term := strings.TrimPrefix(key, "desc:")
		frequency := descDocumentFrequency[term]
		if frequency == 0 {
			frequency = 1
		}
		features = append(features, featureRow{
			entityType: "scene",
			entityID:   sceneID,
			family:     "content",
			name:       key,
			value:      weighted[key] / norm,
			confidence: math.Min(1.0, float64(frequency)/3),
			metadata:   jvObj(jvKey("document_frequency", jvInt(frequency))),
		})
	}
	return features
}

func sceneFeatures(db dbx, roles map[string]tagRoleResult, progress func(fraction float64)) ([]featureRow, error) {
	sceneRows, err := db.Query(`SELECT scene_id FROM source_scene ORDER BY scene_id`)
	if err != nil {
		return nil, err
	}
	var sceneIDs []string
	for sceneRows.Next() {
		var sceneID string
		if err := sceneRows.Scan(&sceneID); err != nil {
			sceneRows.Close()
			return nil, err
		}
		sceneIDs = append(sceneIDs, sceneID)
	}
	sceneRows.Close()
	if err := sceneRows.Err(); err != nil {
		return nil, err
	}
	direct := map[string]map[string]bool{}
	rows, err := db.Query(`SELECT scene_id, tag_id FROM scene_tag WHERE provenance='scene' ORDER BY scene_id, tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, tagID string
		if err := rows.Scan(&sceneID, &tagID); err != nil {
			rows.Close()
			return nil, err
		}
		if roles[tagID].role == "content" {
			if direct[sceneID] == nil {
				direct[sceneID] = map[string]bool{}
			}
			direct[sceneID][tagID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	marker := map[string]map[string]bool{}
	rows, err = db.Query(`
SELECT sm.scene_id, sm.primary_tag_id AS tag_id FROM scene_marker sm
WHERE sm.primary_tag_id IS NOT NULL
UNION
SELECT sm.scene_id, mt.tag_id FROM scene_marker sm
JOIN marker_tag mt ON mt.marker_id = sm.marker_id
ORDER BY scene_id, tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, tagID string
		if err := rows.Scan(&sceneID, &tagID); err != nil {
			rows.Close()
			return nil, err
		}
		if roles[tagID].role == "content" {
			if marker[sceneID] == nil {
				marker[sceneID] = map[string]bool{}
			}
			marker[sceneID][tagID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	parents := map[string]map[string]bool{}
	rows, err = db.Query(`SELECT tag_id, parent_tag_id FROM tag_parent ORDER BY tag_id, parent_tag_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, parentID string
		if err := rows.Scan(&tagID, &parentID); err != nil {
			rows.Close()
			return nil, err
		}
		if roles[parentID].role == "content" {
			if parents[tagID] == nil {
				parents[tagID] = map[string]bool{}
			}
			parents[tagID][parentID] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	baseVectors := map[string]map[string]float64{}
	for _, sceneID := range sceneIDs {
		values := map[string]float64{}
		for tagID := range direct[sceneID] {
			values[tagID] = 1.0
			for parent := range parents[tagID] {
				if v := values[parent]; v < parentWeight {
					values[parent] = parentWeight
				}
			}
		}
		for tagID := range marker[sceneID] {
			if v := values[tagID]; v < markerWeight {
				values[tagID] = markerWeight
			}
			for parent := range parents[tagID] {
				combined := markerWeight * parentWeight
				if v := values[parent]; v < combined {
					values[parent] = combined
				}
			}
		}
		baseVectors[sceneID] = values
	}
	documentFrequency := map[string]int64{}
	for _, values := range baseVectors {
		for tagID := range values {
			documentFrequency[tagID]++
		}
	}
	tagNames := map[string]string{}
	rows, err = db.Query(`SELECT tag_id, name FROM source_tag`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, name string
		if err := rows.Scan(&tagID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		tagNames[tagID] = name
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	total := maxInt(1, len(sceneIDs))
	descDocumentFrequency := map[string]int64{}
	descByScene := map[string][]string{}
	rows, err = db.Query(`SELECT scene_id, details FROM source_scene WHERE details IS NOT NULL AND details != ''`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var details string
		if err := rows.Scan(&sceneID, &details); err != nil {
			rows.Close()
			return nil, err
		}
		var terms []string
		seen := map[string]bool{}
		for _, token := range descTokenRegex.FindAllString(details, -1) {
			token = strings.ToLower(token)
			if !descStopwords[token] && !seen[token] {
				seen[token] = true
				terms = append(terms, token)
				descDocumentFrequency[token]++
			}
		}
		if len(terms) > 0 {
			descByScene[sceneID] = terms
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	descIDF := map[string]float64{}
	for term, freq := range descDocumentFrequency {
		if freq < descMinDF || float64(freq) > float64(total)*descMaxDFFraction {
			continue
		}
		descIDF[term] = math.Min(idfCap, 1+idfStrength*math.Log(float64(total+1)/float64(freq+1)))
	}
	// Each scene's content rows depend only on its own vector and the
	// precomputed frequency maps, so the pass is row-independent: run it in
	// fixed chunks (the kernel pattern) with progress ticks emitted in scene
	// order.
	var features []featureRow
	sceneCount := len(sceneIDs)
	progressReporter := newOrderedProgress()
	reporterDone := make(chan struct{})
	go func() {
		defer close(reporterDone)
		progressReporter.wait(reportPoints(sceneCount), func(completed int) {
			if progress != nil {
				progress(0.10 + 0.30*float64(completed)/float64(maxInt(1, sceneCount)))
			}
		})
	}()
	features = parallelChunks(sceneCount, nthreads(0), func(start, end int) []featureRow {
		var out []featureRow
		for _, sceneID := range sceneIDs[start:end] {
			out = append(out, sceneFeatureRows(sceneID, baseVectors, documentFrequency,
				descByScene, descIDF, descDocumentFrequency, tagNames, roles, total)...)
			progressReporter.done()
		}
		return out
	})
	<-reporterDone
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
		features = append(features, featureRow{
			entityType: "scene",
			entityID:   sceneID,
			family:     "performer_identity",
			name:       "performer:" + performerID,
			value:      1.0,
			confidence: 1.0,
			metadata:   jvObj(jvKey("performer_id", jvStr(performerID))),
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, studio_id FROM source_scene WHERE studio_id IS NOT NULL ORDER BY scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID, studioID string
		if err := rows.Scan(&sceneID, &studioID); err != nil {
			rows.Close()
			return nil, err
		}
		features = append(features, featureRow{
			entityType: "scene",
			entityID:   sceneID,
			family:     "studio",
			name:       "studio:" + studioID,
			value:      1.0,
			confidence: 1.0,
			metadata:   jvObj(jvKey("studio_id", jvStr(studioID))),
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(`SELECT scene_id, count(*) AS performer_count FROM scene_performer GROUP BY scene_id HAVING count(*) > 1 ORDER BY scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var sceneID string
		var performerCount int64
		if err := rows.Scan(&sceneID, &performerCount); err != nil {
			rows.Close()
			return nil, err
		}
		features = append(features, featureRow{
			entityType: "scene",
			entityID:   sceneID,
			family:     "structure",
			name:       "multiple_performers",
			value:      math.Min(1.0, float64(performerCount-1)/3),
			confidence: 1.0,
			metadata:   jvObj(jvKey("performer_count", jvInt(performerCount))),
		})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return features, nil
}

// performerFeatures mirrors FeatureBuilder._performer_features.
func performerFeatures(db dbx, sceneFeatures []featureRow, progress func(fraction float64)) ([]featureRow, error) {
	contentByScene := map[string][]featureRow{}
	for _, feature := range sceneFeatures {
		if feature.entityType == "scene" && feature.family == "content" {
			contentByScene[feature.entityID] = append(contentByScene[feature.entityID], feature)
		}
	}
	scenesByPerformer := map[string][]string{}
	rows, err := db.Query(`SELECT performer_id, scene_id FROM scene_performer ORDER BY performer_id, scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var performerID, sceneID string
		if err := rows.Scan(&performerID, &sceneID); err != nil {
			rows.Close()
			return nil, err
		}
		scenesByPerformer[performerID] = append(scenesByPerformer[performerID], sceneID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var features []featureRow
	for _, performerID := range sortedStringKeys(scenesByPerformer) {
		sceneIDs := scenesByPerformer[performerID]
		aggregate := map[string]float64{}
		for _, sceneID := range sceneIDs {
			for _, feature := range contentByScene[sceneID] {
				aggregate[feature.name] += feature.value
			}
		}
		var normSquared float64
		for _, value := range aggregate {
			normSquared += value * value
		}
		norm := math.Sqrt(normSquared)
		if norm == 0 {
			norm = 1.0
		}
		for _, name := range sortedStringKeys(aggregate) {
			features = append(features, featureRow{
				entityType: "performer",
				entityID:   performerID,
				family:     "profile:content",
				name:       name,
				value:      aggregate[name] / norm,
				confidence: math.Min(1.0, float64(len(sceneIDs))/5),
				metadata:   jvObj(jvKey("scene_count", jvInt(int64(len(sceneIDs))))),
			})
		}
	}
	ages := map[string][]float64{}
	rows, err = db.Query(`
SELECT sp.performer_id, p.birthdate, s.scene_date
FROM scene_performer sp JOIN source_performer p ON p.performer_id=sp.performer_id
JOIN source_scene s ON s.scene_id=sp.scene_id
WHERE p.birthdate IS NOT NULL AND s.scene_date IS NOT NULL
ORDER BY sp.performer_id, s.scene_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var performerID, birthdate, sceneDate string
		if err := rows.Scan(&performerID, &birthdate, &sceneDate); err != nil {
			rows.Close()
			return nil, err
		}
		born, errBorn := time.Parse("2006-01-02", birthdate)
		recorded, errRecorded := time.Parse("2006-01-02", sceneDate)
		if errBorn != nil || errRecorded != nil {
			continue
		}
		age := float64(recorded.Unix()-born.Unix()) / 86_400 / 365.2425
		if age >= 18 && age <= 100 {
			ages[performerID] = append(ages[performerID], age)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	fallbackAugmented := map[string]bool{}
	rows, err = db.Query(`
SELECT sp.performer_id, count(DISTINCT sp.scene_id) AS support
FROM scene_performer sp JOIN scene_tag st ON st.scene_id=sp.scene_id
JOIN source_tag t ON t.tag_id=st.tag_id
WHERE lower(t.name) LIKE '%augmentation%' OR lower(t.name) LIKE '%fake tits%'
GROUP BY sp.performer_id HAVING count(DISTINCT sp.scene_id) >= 2`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var performerID string
		var support int64
		if err := rows.Scan(&performerID, &support); err != nil {
			rows.Close()
			return nil, err
		}
		fallbackAugmented[performerID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	type performerRow struct {
		performerID  string
		ethnicity    string
		eyeColor     string
		hairColor    string
		heightCM     *float64
		weightKG     *float64
		measurements string
		augmentation string
		tattoos      string
		piercings    string
	}
	var performerRows []performerRow
	rows, err = db.Query(`
SELECT performer_id, ethnicity, country, eye_color, hair_color, height_cm,
       weight_kg, measurements, augmentation, tattoos, piercings
FROM source_performer ORDER BY performer_id`)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var performerID string
		var ethnicity, country, eyeColor, hairColor, measurements, augmentation, tattoos, piercings sql.NullString
		var heightCM, weightKG sql.NullFloat64
		if err := rows.Scan(&performerID, &ethnicity, &country, &eyeColor, &hairColor,
			&heightCM, &weightKG, &measurements, &augmentation, &tattoos, &piercings); err != nil {
			rows.Close()
			return nil, err
		}
		row := performerRow{
			performerID:  performerID,
			ethnicity:    ethnicity.String,
			eyeColor:     eyeColor.String,
			hairColor:    hairColor.String,
			measurements: measurements.String,
			augmentation: augmentation.String,
			tattoos:      tattoos.String,
			piercings:    piercings.String,
		}
		if heightCM.Valid {
			row.heightCM = &heightCM.Float64
		}
		if weightKG.Valid {
			row.weightKG = &weightKG.Float64
		}
		performerRows = append(performerRows, row)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for position, row := range performerRows {
		performerID := row.performerID
		measurements := parseMeasurements(row.measurements)
		numeric := []struct {
			name       string
			value      float64
			confidence float64
		}{}
		if row.weightKG != nil {
			numeric = append(numeric, struct {
				name       string
				value      float64
				confidence float64
			}{"weight_kg", *row.weightKG, 1.0})
		}
		if measurements != nil {
			numeric = append(numeric,
				struct {
					name       string
					value      float64
					confidence float64
				}{"band_inches", measurements.bandInches, measurements.confidence},
				struct {
					name       string
					value      float64
					confidence float64
				}{"waist_inches", measurements.waistInches, measurements.confidence},
				struct {
					name       string
					value      float64
					confidence float64
				}{"hip_inches", measurements.hipInches, measurements.confidence},
				struct {
					name       string
					value      float64
					confidence float64
				}{"waist_to_hip", measurements.waistToHip, measurements.confidence},
			)
			if measurements.hasCup {
				numeric = append(numeric, struct {
					name       string
					value      float64
					confidence float64
				}{"cup_index", measurements.cupIndex, measurements.confidence})
			}
		}
		sort.SliceStable(numeric, func(i, j int) bool { return numeric[i].name < numeric[j].name })
		for _, item := range numeric {
			features = append(features, featureRow{
				entityType: "performer",
				entityID:   performerID,
				family:     "profile:measurements",
				name:       item.name,
				value:      item.value,
				confidence: item.confidence,
				metadata:   jvObj(),
			})
		}
		if row.heightCM != nil {
			features = append(features, featureRow{
				entityType: "performer",
				entityID:   performerID,
				family:     "profile:height",
				name:       "height_cm",
				value:      *row.heightCM,
				confidence: 1.0,
				metadata:   jvObj(),
			})
		}
		if samples := ages[performerID]; len(samples) > 0 {
			var sum float64
			for _, sample := range samples {
				sum += sample
			}
			features = append(features, featureRow{
				entityType: "performer",
				entityID:   performerID,
				family:     "profile:age",
				name:       "age_recording",
				value:      sum / float64(len(samples)),
				confidence: math.Min(1.0, float64(len(samples))/3),
				metadata:   jvObj(jvKey("sample_size", jvInt(int64(len(samples))))),
			})
		}
		for _, category := range []struct {
			block, prefix, raw string
			confidence         float64
		}{
			{"hair", "hair", row.hairColor, 0.65},
			{"ethnicity", "ethnicity", row.ethnicity, 0.9},
			{"eyes", "eye", row.eyeColor, 0.9},
		} {
			raw := strings.TrimSpace(category.raw)
			if raw != "" {
				features = append(features, featureRow{
					entityType: "performer",
					entityID:   performerID,
					family:     "profile:" + category.block,
					name:       category.prefix + ":" + strings.ToLower(raw),
					value:      1.0,
					confidence: category.confidence,
					metadata:   jvObj(jvKey("display", jvStr(raw))),
				})
			}
		}
		for _, block := range []struct{ block, raw string }{
			{"tattoos", row.tattoos},
			{"piercings", row.piercings},
		} {
			if block.raw == "" {
				continue
			}
			category := presenceCategory(block.raw)
			if category != "" {
				features = append(features, featureRow{
					entityType: "performer",
					entityID:   performerID,
					family:     "profile:" + block.block,
					name:       category,
					value:      1.0,
					confidence: 0.8,
					metadata:   jvObj(),
				})
			}
		}
		augmentation, _ := augmentationCategory(jvStr(row.augmentation))
		confidence := 1.0
		provenance := "performer_metadata"
		if augmentation == "" && fallbackAugmented[performerID] {
			augmentation = "augmented"
			confidence = 0.55
			provenance = "repeated_scene_tags"
		}
		if augmentation != "" {
			features = append(features, featureRow{
				entityType: "performer",
				entityID:   performerID,
				family:     "profile:augmentation",
				name:       augmentation,
				value:      1.0,
				confidence: confidence,
				metadata:   jvObj(jvKey("provenance", jvStr(provenance))),
			})
		}
		if progress != nil && (position+1 == len(performerRows) || (position+1)%250 == 0) {
			progress(0.45 + 0.15*float64(position+1)/float64(maxInt(1, len(performerRows))))
		}
	}
	return features, nil
}

func sortedStringKeys[T any](values map[string]T) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// featureID mirrors FeatureBuilder._feature_id.
func featureID(featureVersion, entityType, family, name string) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s", entityType, family, name)))
	return fmt.Sprintf("%s-%s", featureVersion, hex.EncodeToString(digest[:])[:24])
}

// featureBuild runs the FeatureBuilder pipeline and returns the feature
// version plus whether the published feature was reused.
func featureBuild(db dbx, nowMs int64, progress func(fraction float64)) (string, bool, error) {
	sourceFingerprint, err := featureSourceFingerprint(db)
	if err != nil {
		return "", false, err
	}
	if progress != nil {
		progress(0.05)
	}
	versionHash := sha256.Sum256([]byte(sourceFingerprint + "\x00" + featureConfigCanonicalJSON()))
	featureVersion := fmt.Sprintf("fv-%s", hex.EncodeToString(versionHash[:])[:20])
	var status string
	var validationStatus sql.NullString
	var basename sql.NullString
	err = db.QueryRow(`SELECT status, artifact_basename, validation_status FROM feature_build WHERE feature_version = ?`,
		featureVersion).Scan(&status, &basename, &validationStatus)
	if err == nil && status == "published" && validationStatus.Valid && validationStatus.String == "valid" && basename.Valid {
		corePath, pathErr := coreDatabasePath(db)
		if pathErr == nil {
			path, pathErr := artifactPath(corePath, basename.String)
			if pathErr == nil {
				if _, statErr := os.Stat(path); statErr == nil {
					if err := withTxn(db, func(conn *sql.Conn) error {
						_, err := conn.ExecContext(context.Background(),
							`UPDATE feature_build SET reuse_count=reuse_count+1 WHERE feature_version=?`,
							featureVersion)
						return err
					}); err != nil {
						return "", false, err
					}
					if progress != nil {
						progress(1.0)
					}
					return featureVersion, true, nil
				}
			}
		}
	} else if err != nil && err != sql.ErrNoRows {
		return "", false, err
	}
	insertErr := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
INSERT INTO feature_build(
    feature_version, status, config_json, source_fingerprint, created_at_ms
) VALUES (?, 'building', ?, ?, ?)
ON CONFLICT(feature_version) DO UPDATE SET status='building', error=NULL`,
			featureVersion, featureConfigCanonicalJSON(), sourceFingerprint, nowMs)
		return err
	})
	if insertErr != nil {
		return "", false, insertErr
	}
	roles, err := resolveTagRoles(db)
	if err != nil {
		return "", false, err
	}
	if progress != nil {
		progress(0.10)
	}
	sceneFeatures, err := sceneFeatures(db, roles, progress)
	if err != nil {
		return "", false, err
	}
	if progress != nil {
		progress(0.45)
	}
	performerFeatures, err := performerFeatures(db, sceneFeatures, progress)
	if err != nil {
		return "", false, err
	}
	if progress != nil {
		progress(0.60)
	}
	allFeatures := append(append([]featureRow(nil), sceneFeatures...), performerFeatures...)
	if err := featurePublish(db, featureVersion, sourceFingerprint, roles, allFeatures, nowMs, progress); err != nil {
		failErr := withTxn(db, func(conn *sql.Conn) error {
			_, err := conn.ExecContext(context.Background(),
				`UPDATE feature_build SET status='failed', error=? WHERE feature_version=?`,
				truncateString(err.Error(), 2000), featureVersion)
			return err
		})
		if failErr != nil {
			return "", false, failErr
		}
		return "", false, err
	}
	if progress != nil {
		progress(1.0)
	}
	return featureVersion, false, nil
}

// featurePublish mirrors FeatureBuilder._publish.
func featurePublish(db dbx, featureVersion, sourceFingerprint string, roles map[string]tagRoleResult,
	features []featureRow, nowMs int64, progress func(fraction float64)) error {
	configVersion := "cfg-" + featureFingerprint()[:20]
	type definition struct {
		featureID string
		metadata  jVal
	}
	definitions := map[string]definition{}
	for _, feature := range features {
		key := feature.entityType + "\x00" + feature.family + "\x00" + feature.name
		if _, ok := definitions[key]; !ok {
			definitions[key] = definition{
				featureID: featureID(featureVersion, feature.entityType, feature.family, feature.name),
				metadata:  feature.metadata,
			}
		}
	}
	sceneIDs := map[string]bool{}
	performerIDs := map[string]bool{}
	for _, feature := range features {
		if feature.entityType == "scene" {
			sceneIDs[feature.entityID] = true
		} else {
			performerIDs[feature.entityID] = true
		}
	}
	sceneCount := int64(len(sceneIDs))
	performerCount := int64(len(performerIDs))
	corePath, err := coreDatabasePath(db)
	if err != nil {
		return err
	}
	artifact, temporary, final, err := createArtifact(corePath, "feature", featureVersion)
	if err != nil {
		return err
	}
	published := false
	fail := func(err error) error {
		if !published {
			discardArtifact(artifact, temporary)
			if _, statErr := os.Stat(temporary); os.IsNotExist(statErr) {
				os.Remove(final)
			}
		}
		return err
	}
	if err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx,
			`DELETE FROM tag_role WHERE config_version = ?`, configVersion); err != nil {
			return err
		}
		sortedRoleIDs := make([]string, 0, len(roles))
		for tagID := range roles {
			sortedRoleIDs = append(sortedRoleIDs, tagID)
		}
		sort.Strings(sortedRoleIDs)
		for _, tagID := range sortedRoleIDs {
			result := roles[tagID]
			if _, err := conn.ExecContext(ctx, `
INSERT INTO tag_role(tag_id, config_version, role, resolution_reason)
VALUES (?, ?, ?, ?)`, tagID, configVersion, result.role, result.reason); err != nil {
				return err
			}
		}
		for _, tagID := range sortedRoleIDs {
			taxonomy := roles[tagID].taxonomy
			if taxonomy.snapshotID == "" {
				continue
			}
			externalTagID := any(nil)
			if taxonomy.externalTagID != "" {
				externalTagID = taxonomy.externalTagID
			}
			externalCategoryID := any(nil)
			if taxonomy.externalCategoryID != "" {
				externalCategoryID = taxonomy.externalCategoryID
			}
			if _, err := conn.ExecContext(ctx, `
INSERT INTO tag_taxonomy_match(
    local_tag_id, snapshot_id, external_tag_id, external_category_id,
    match_method, confidence, ambiguity_count
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(local_tag_id, snapshot_id) DO UPDATE SET
    external_tag_id=excluded.external_tag_id,
    external_category_id=excluded.external_category_id,
    match_method=excluded.match_method,
    confidence=excluded.confidence,
    ambiguity_count=excluded.ambiguity_count`,
				tagID, taxonomy.snapshotID, externalTagID, externalCategoryID,
				taxonomy.method, taxonomy.confidence, taxonomy.ambiguityCount); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return fail(err)
	}
	if err := withTxn(artifact, func(conn *sql.Conn) error {
		ctx := context.Background()
		definitionKeys := make([]string, 0, len(definitions))
		for key := range definitions {
			definitionKeys = append(definitionKeys, key)
		}
		sort.Strings(definitionKeys)
		for _, key := range definitionKeys {
			parts := strings.SplitN(key, "\x00", 3)
			definition := definitions[key]
			if _, err := conn.ExecContext(ctx, `
INSERT INTO feature_definition(
    feature_id, feature_version, family, name, provenance, metadata_json
) VALUES (?, ?, ?, ?, 'feature_builder', ?)`,
				definition.featureID, featureVersion, parts[1], parts[2],
				definition.metadata.marshalSortedKeys()); err != nil {
				return err
			}
		}
		sortedFeatures := append([]featureRow(nil), features...)
		sort.SliceStable(sortedFeatures, func(i, j int) bool {
			a, b := sortedFeatures[i], sortedFeatures[j]
			if a.entityType != b.entityType {
				return a.entityType < b.entityType
			}
			if a.entityID != b.entityID {
				return a.entityID < b.entityID
			}
			if a.family != b.family {
				return a.family < b.family
			}
			return a.name < b.name
		})
		for _, feature := range sortedFeatures {
			key := feature.entityType + "\x00" + feature.family + "\x00" + feature.name
			if _, err := conn.ExecContext(ctx, `
INSERT INTO entity_feature(
    feature_version, entity_type, entity_id, feature_id, value, confidence
) VALUES (?, ?, ?, ?, ?, ?)`,
				featureVersion, feature.entityType, feature.entityID, definitions[key].featureID,
				feature.value, feature.confidence); err != nil {
				return err
			}
		}
		for _, feature := range sortedFeatures {
			if feature.entityType != "scene" || feature.family != "content" {
				continue
			}
			key := feature.entityType + "\x00" + feature.family + "\x00" + feature.name
			if _, err := conn.ExecContext(ctx, `
INSERT INTO scene_content_search(
    feature_version, feature_id, scene_id, value
) VALUES (?, ?, ?, ?)`,
				featureVersion, definitions[key].featureID, feature.entityID, feature.value); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return fail(err)
	}
	if progress != nil {
		progress(0.75)
	}
	if err := artifactCreateIndexes(artifact, "feature"); err != nil {
		return fail(err)
	}
	if progress != nil {
		progress(0.85)
	}
	var storedScene, storedPerformer, storedFeatures int64
	err = artifact.QueryRow(`
SELECT
    (SELECT count(DISTINCT entity_id) FROM entity_feature
     WHERE feature_version=? AND entity_type='scene'),
    (SELECT count(DISTINCT entity_id) FROM entity_feature
     WHERE feature_version=? AND entity_type='performer'),
    (SELECT count(*) FROM feature_definition WHERE feature_version=?)`,
		featureVersion, featureVersion, featureVersion).Scan(&storedScene, &storedPerformer, &storedFeatures)
	if err != nil {
		return fail(err)
	}
	if storedScene != sceneCount || storedPerformer != performerCount || storedFeatures != int64(len(definitions)) {
		return fail(fmt.Errorf("feature validation failed: expected (%d, %d, %d), stored (%d, %d, %d)",
			sceneCount, performerCount, len(definitions), storedScene, storedPerformer, storedFeatures))
	}
	summary, err := artifactValidate(artifact, "feature", map[string]int64{
		"scenes": sceneCount, "performers": performerCount, "features": int64(len(definitions)),
	}, true)
	if err != nil {
		return fail(err)
	}
	if progress != nil {
		progress(0.93)
	}
	size, err := publishArtifactFile(artifact, temporary, final)
	if err != nil {
		return fail(err)
	}
	artifact = nil
	if err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx,
			`UPDATE feature_build SET status='superseded' WHERE status='published'`); err != nil {
			return err
		}
		_, err := conn.ExecContext(ctx, `
UPDATE feature_build SET status='published', source_fingerprint=?,
    published_at_ms=?, error=NULL, scene_count=?, performer_count=?,
    feature_count=?, artifact_basename=?, artifact_schema_version=?,
    artifact_bytes=?, validation_status='valid',
    validation_summary_json=?, cleanup_error=NULL
WHERE feature_version=?`,
			sourceFingerprint, nowMs, sceneCount, performerCount, int64(len(definitions)),
			filepath.Base(final), artifactSchemaVersion, size,
			summary.marshalSortedKeys(), featureVersion)
		return err
	}); err != nil {
		return fail(err)
	}
	published = true
	if err := activateArtifact(db, "feature", final); err != nil {
		return err
	}
	if progress != nil {
		progress(0.98)
	}
	return nil
}
