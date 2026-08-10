// StashDB discovery cache operations — a port of curator/expand.py's
// ExpandService read path used by the network-layer ops: results
// (get_expand), performer_hunt (get_performer_hunt), targeted_similar +
// similar (get_external_similar). Byte-identity requires the same SQL row
// orders, the same float accumulation (neumaierSum for Python sum(),
// pyTanh/pyLog for the glibc math), and the same JSON key insertion order.
// The performer hunt fans pages out over a bounded stdlib worker pool; the
// merge stays deterministic (page order, first-seen rows).
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const performerHuntLimit = 1000

const remoteMultiHopWeight = 0.05

// expandService mirrors ExpandService: sidecar-backed StashDB discovery.
type expandService struct {
	db dbx
}

func newExpandService(db dbx) *expandService { return &expandService{db: db} }

// scoredScene mirrors one _score row: id, payload, score, sources (sorted),
// with an optional multi_hop_reach float.
type scoredScene struct {
	id            string
	payload       jVal
	score         float64
	sources       []string
	multiHopReach float64
	hasMultiHop   bool
}

// expandPerformerRow mirrors _score's performer_rows entries.
type expandPerformerRow struct {
	id      string
	payload jVal
	score   float64
	sources map[string]bool
}

// performerEvidence mirrors _performer_evidence's per-performer entry.
type performerEvidence struct {
	localID   string
	name      string
	favorite  bool
	playCount int64
	strength  float64
}

// ── performer profile helpers ─────────────────────────────────────────────

// cupAliases mirrors features/measurements.py CUP_ALIASES: cup → index.
var cupAliases = map[string]float64{
	"AA": 0, "A": 1, "B": 2, "C": 3, "D": 4, "DD": 5, "E": 5, "DDD": 6, "F": 6,
	"G": 7, "H": 8, "I": 9, "J": 10, "K": 11,
}

// augmentationCategory mirrors features/measurements.py augmentation_category.
func augmentationCategory(value jVal) (string, bool) {
	folded := strings.ToLower(strings.TrimSpace(pythonStrOrEmpty(value)))
	switch folded {
	case "yes", "y", "true", "fake", "enhanced", "augmented":
		return "augmented", true
	case "no", "n", "false", "natural", "none":
		return "natural", true
	}
	return "", false
}

// expandAge mirrors ExpandService._age: parse a birthdate and an optional
// recorded reference date; fractional years since birth.
func expandAge(value, recorded jVal) (float64, bool) {
	raw := strings.TrimSpace(pythonStrOrEmpty(value))
	if raw == "" {
		return 0, false
	}
	parts := strings.Split(raw, "-")
	year, err := strconv.Atoi(parts[0])
	if err != nil {
		return 0, false
	}
	month := 7
	if len(parts) > 1 {
		if month, err = strconv.Atoi(parts[1]); err != nil {
			return 0, false
		}
	}
	day := 1
	if len(parts) > 2 {
		if day, err = strconv.Atoi(parts[2]); err != nil {
			return 0, false
		}
	}
	var reference time.Time
	if recorded.truthy() {
		reference, err = time.Parse("2006-01-02", recorded.asString())
		if err != nil {
			return 0, false
		}
	} else {
		now := time.Now()
		reference = time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	}
	born := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	// Python's date() validates the range (month 13 raises); time.Date
	// normalizes instead, so reject normalized-out values the same way.
	if born.Year() != year || int(born.Month()) != month || born.Day() != day {
		return 0, false
	}
	days := int(reference.Sub(born).Hours() / 24)
	return math.Max(0.0, float64(days)/365.2425), true
}

// expandWithAge mirrors ExpandService._with_age.
func expandWithAge(profile *performerProfile, birthdate jVal) *performerProfile {
	age, ok := expandAge(birthdate, jvNull())
	if !ok {
		return profile
	}
	blocks := make(map[string]map[string]profileValue, len(profile.blocks)+1)
	for name, values := range profile.blocks {
		blocks[name] = values
	}
	blocks["age"] = map[string]profileValue{"age_recording": {value: age, confidence: 0.9}}
	result := &performerProfile{
		id:     profile.id,
		blocks: blocks,
		norms:  map[string]float64{},
		keys:   map[string]map[string]bool{},
	}
	finalizeProfileNorms(result)
	return result
}

// expandProfile mirrors ExpandService._profile: build a performer profile
// from a StashDB performer object, optionally dated at a recording.
func expandProfile(raw jVal, recorded jVal) *performerProfile {
	blocks := map[string]map[string]profileValue{}
	for _, item := range [][4]interface{}{
		{"ethnicity", "ethnicity", "ethnicity", 0.9},
		{"hair", "hair", "hair_color", 0.65},
		{"eyes", "eye", "eye_color", 0.9},
	} {
		block := item[0].(string)
		prefix := item[1].(string)
		field := item[2].(string)
		confidence := item[3].(float64)
		if raw.get(field).truthy() {
			values := blocks[block]
			if values == nil {
				values = map[string]profileValue{}
				blocks[block] = values
			}
			values[prefix+":"+strings.ToLower(raw.get(field).asString())] = profileValue{value: 1, confidence: confidence}
		}
	}
	measurements := map[string]profileValue{}
	if raw.get("band_size").truthy() {
		measurements["band_inches"] = profileValue{value: pythonFloatOr(raw.get("band_size"), 0), confidence: 1}
	}
	if raw.get("waist_size").truthy() {
		measurements["waist_inches"] = profileValue{value: pythonFloatOr(raw.get("waist_size"), 0), confidence: 1}
	}
	if raw.get("hip_size").truthy() {
		measurements["hip_inches"] = profileValue{value: pythonFloatOr(raw.get("hip_size"), 0), confidence: 1}
	}
	if cup, ok := cupAliases[strings.ToUpper(pythonStrOrEmpty(raw.get("cup_size")))]; ok {
		measurements["cup_index"] = profileValue{value: cup, confidence: 1}
	}
	if raw.get("waist_size").truthy() && raw.get("hip_size").truthy() {
		waist := pythonFloatOr(raw.get("waist_size"), 0)
		hip := pythonFloatOr(raw.get("hip_size"), 0)
		measurements["waist_to_hip"] = profileValue{value: waist / hip, confidence: 1}
	}
	if len(measurements) > 0 {
		blocks["measurements"] = measurements
	}
	if raw.get("height").truthy() {
		blocks["height"] = map[string]profileValue{
			"height_cm": {value: pythonFloatOr(raw.get("height"), 0), confidence: 1},
		}
	}
	if age, ok := expandAge(raw.get("birth_date"), recorded); ok {
		blocks["age"] = map[string]profileValue{"age_recording": {value: age, confidence: 0.9}}
	}
	if category, ok := augmentationCategory(raw.get("breast_type")); ok {
		blocks["augmentation"] = map[string]profileValue{category: {value: 1, confidence: 1}}
	}
	if raw.get("tattoos").truthy() {
		blocks["tattoos"] = map[string]profileValue{"present": {value: 1, confidence: 0.8}}
	}
	if raw.get("piercings").truthy() {
		blocks["piercings"] = map[string]profileValue{"present": {value: 1, confidence: 0.8}}
	}
	result := &performerProfile{
		id:     raw.get("id").asString(),
		blocks: blocks,
		norms:  map[string]float64{},
		keys:   map[string]map[string]bool{},
	}
	finalizeProfileNorms(result)
	return result
}

// finalizeProfileNorms computes the per-block norms and key sets the Python
// PerformerProfile __post_init__ derives (non-numeric blocks only).
func finalizeProfileNorms(p *performerProfile) {
	for block, values := range p.blocks {
		keys := map[string]bool{}
		for name := range values {
			keys[name] = true
		}
		p.keys[block] = keys
		if numericBlocks[block] {
			continue
		}
		squares := make([]float64, 0, len(values))
		for _, item := range values {
			squares = append(squares, pySquare(item.value))
		}
		p.norms[block] = math.Sqrt(neumaierSum(squares))
	}
}

// expandTagValue mirrors ExpandService._tag_value.
func expandTagValue(tag jVal, affinities map[string]float64) float64 {
	if value, ok := affinities["id:"+tag.get("id").asString()]; ok {
		return value
	}
	return affinities["name:"+strings.ToLower(pythonStrOrEmpty(tag.get("name")))]
}

// expandCastWeight mirrors ExpandService._cast_weight.
func expandCastWeight(count int) float64 {
	return math.Min(1.0, math.Sqrt(4.0/float64(maxInt(1, count))))
}

// expandWhy mirrors ExpandService._why.
func expandWhy(scene jVal, tagAffinity map[string]float64, identity, similarity float64, castCount int) jVal {
	type tagPair struct {
		value float64
		name  string
	}
	pairs := make([]tagPair, 0)
	for _, tag := range scene.get("tags").arr {
		value := expandTagValue(tag, tagAffinity)
		if value > 0 {
			pairs = append(pairs, tagPair{value: value, name: tag.get("name").asString()})
		}
	}
	sort.SliceStable(pairs, func(i, j int) bool { return pairs[i].value > pairs[j].value })
	if len(pairs) > 3 {
		pairs = pairs[:3]
	}
	reasons := jvArr()
	for _, pair := range pairs {
		reasons.arr = append(reasons.arr, jvStr(pair.name))
	}
	if identity > 0 {
		reasons.arr = append(reasons.arr, jvStr("a performer you already enjoy"))
	} else if similarity > 0 {
		reasons.arr = append(reasons.arr, jvStr("a performer close to your preferences"))
	}
	if castCount > 8 {
		reasons.arr = append(reasons.arr, jvStr("performer evidence reduced for the large compilation cast"))
	}
	return reasons
}

// ── anchor matching (performer hunt scoring) ──────────────────────────────

// compactTerm is one anchor comparison for a performer: the accumulated
// numerator/denominator and the cup penalty. Retaining the per-anchor block
// maps for every unique performer would hold ~1GB for the anchor set and
// scene casts of a large library (the maps dwarf the floats), so the terms
// stay compact and the chosen anchor's block maps are recomputed on demand
// in best (one anchor per call, same deterministic values).
type compactTerm struct {
	anchorIndex int
	numerator   float64
	denominator float64
	penalty     float64
}

// anchorMatch mirrors one _AnchorMatcher.best result: the combined value and
// the dated block similarities/weights (for the why attributes).
type anchorMatch struct {
	value        float64
	similarities map[string]float64
	usedWeights  map[string]float64
	evidence     *performerEvidence
}

type anchorPair struct {
	profile  *performerProfile
	evidence *performerEvidence
}

// anchorMatcher mirrors _AnchorMatcher.
type anchorMatcher struct {
	anchors   []anchorPair
	weights   map[string]float64
	ageWeight float64
	relevant  float64
	terms     map[string][]compactTerm
}

func newAnchorMatcher(anchors []anchorPair, weights map[string]float64) *anchorMatcher {
	relevant := 0.0
	for key, value := range weights {
		if key != "content" {
			relevant += value
		}
	}
	return &anchorMatcher{
		anchors:   anchors,
		weights:   weights,
		ageWeight: weights["age"],
		relevant:  relevant,
		terms:     map[string][]compactTerm{},
	}
}

// timeless mirrors _AnchorMatcher._timeless: scene-independent block terms.
func (m *anchorMatcher) timeless(performer jVal) []compactTerm {
	externalID := performer.get("id").asString()
	if cached, ok := m.terms[externalID]; ok {
		return cached
	}
	terms := m.computeTerms(performer)
	m.terms[externalID] = terms
	return terms
}

// undatedProfile mirrors the _timeless profile construction: the external
// performer's profile without the age block (the age term is added per
// recording date in best).
func undatedProfile(performer jVal) *performerProfile {
	profile := expandProfile(performer, jvNull())
	undated := &performerProfile{
		id:     profile.id,
		blocks: map[string]map[string]profileValue{},
		norms:  map[string]float64{},
		keys:   map[string]map[string]bool{},
	}
	for block, values := range profile.blocks {
		if block != "age" {
			undated.blocks[block] = values
		}
	}
	finalizeProfileNorms(undated)
	return undated
}

// computeTerms is the uncached term computation for one external performer.
// The per-anchor block maps are discarded here; best re-derives them only
// for the chosen anchor.
func (m *anchorMatcher) computeTerms(performer jVal) []compactTerm {
	undated := undatedProfile(performer)
	terms := make([]compactTerm, 0, len(m.anchors))
	for index, a := range m.anchors {
		similarities, used, ordered, weights := blockSimilaritiesAll(undated, a.profile, m.weights)
		products := make([]float64, 0, len(ordered))
		for _, block := range ordered {
			products = append(products, similarities[block]*used[block])
		}
		terms = append(terms, compactTerm{
			anchorIndex: index,
			numerator:   neumaierSum(products),
			denominator: neumaierSum(weights),
			penalty:     similarityPenalty(undated, a.profile),
		})
	}
	return terms
}

// precomputeTerms fills the term cache for every unique external performer
// with a bounded worker pool. Each performer is assigned to exactly one
// worker and writes its own result slot, so the cache fill afterwards is
// race-free and the term content is identical regardless of worker order
// (the anchor iteration order is fixed).
func (m *anchorMatcher) precomputeTerms(performers []jVal, workers int) {
	if len(performers) == 0 {
		return
	}
	terms := make([][]compactTerm, len(performers))
	if workers < 1 {
		workers = 1
	}
	ch := make(chan int)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range ch {
				terms[index] = m.computeTerms(performers[index])
			}
		}()
	}
	for i := range performers {
		ch <- i
	}
	close(ch)
	wg.Wait()
	for i, termSet := range terms {
		m.terms[performers[i].get("id").asString()] = termSet
	}
}

// best mirrors _AnchorMatcher.best: combine the timeless terms with a fresh
// age term for the recording date.
func (m *anchorMatcher) best(performer jVal, recorded jVal) (anchorMatch, bool) {
	terms := m.timeless(performer)
	if len(terms) == 0 {
		return anchorMatch{}, false
	}
	profile := expandProfile(performer, recorded)
	bestValue := -1.0
	bestIndex := -1
	chosenAge := 0.0
	hasAge := false
	for i := range terms {
		term := &terms[i]
		age, ageOK := 0.0, false
		if m.ageWeight > 0 {
			age, ageOK = blockSimilarity(profile, m.anchors[term.anchorIndex].profile, "age")
		}
		numerator := term.numerator
		denominator := term.denominator
		if ageOK {
			numerator += age * m.ageWeight
			denominator += m.ageWeight
		}
		similarity := 0.0
		if denominator != 0 {
			similarity = numerator / denominator
		}
		similarity *= term.penalty
		coverage := 0.0
		if m.relevant != 0 {
			coverage = math.Min(1.0, denominator/m.relevant)
		}
		value := similarity * math.Sqrt(coverage)
		if value > bestValue {
			bestValue, bestIndex, chosenAge, hasAge = value, i, age, ageOK
		}
	}
	if bestIndex < 0 {
		return anchorMatch{}, false
	}
	chosen := &terms[bestIndex]
	anchor := m.anchors[chosen.anchorIndex].profile
	// The compact terms discard the per-anchor block maps; re-derive them
	// for the chosen anchor on demand (one anchor per call). The undated
	// profile keeps Python's accumulation order: undated blocks sorted,
	// the age term appended last — identical values and order to the
	// timeless computation.
	undated := &performerProfile{
		id:     profile.id,
		blocks: map[string]map[string]profileValue{},
		norms:  map[string]float64{},
		keys:   map[string]map[string]bool{},
	}
	for block, values := range profile.blocks {
		if block != "age" {
			undated.blocks[block] = values
		}
	}
	finalizeProfileNorms(undated)
	similarities, usedWeights, ordered, _ := blockSimilaritiesAll(undated, anchor, m.weights)
	if hasAge {
		similarities["age"] = chosenAge
		usedWeights["age"] = m.ageWeight
		ordered = append(ordered, "age")
	}
	// combine_similarities: total = sum(sim*w)/sum(w) * penalty.
	products := make([]float64, 0, len(ordered))
	weightValues := make([]float64, 0, len(ordered))
	for _, block := range ordered {
		products = append(products, similarities[block]*usedWeights[block])
		weightValues = append(weightValues, usedWeights[block])
	}
	denominator := neumaierSum(weightValues)
	total := 0.0
	if denominator != 0 {
		total = neumaierSum(products) / denominator
	}
	total *= similarityPenalty(profile, anchor)
	coverage := 0.0
	if m.relevant != 0 {
		coverage = math.Min(1.0, denominator/m.relevant)
	}
	return anchorMatch{
		value:        total * math.Sqrt(coverage),
		similarities: similarities,
		usedWeights:  usedWeights,
		evidence:     m.anchors[chosen.anchorIndex].evidence,
	}, true
}

// ── scene matching and diversity ──────────────────────────────────────────

// expandSceneMatches mirrors ExpandService._scene_matches.
func expandSceneMatches(payload jVal, includeTags, excludeTags, performerNames, studioNames []string,
	performerQuery, studioQuery string, includeGroups, excludeGroups, blockedGroups []map[string]bool) bool {
	tags := map[string]bool{}
	for _, item := range payload.get("tags").arr {
		tags[strings.ToLower(pythonStrOrEmpty(item.get("name")))] = true
	}
	cast := map[string]bool{}
	for _, item := range payload.get("performers").arr {
		cast[strings.ToLower(pythonStrOrEmpty(item.get("performer").get("name")))] = true
	}
	studio := strings.ToLower(pythonStrOrEmpty(payload.get("studio").get("name")))
	if anyGroupIntersects(blockedGroups, tags) {
		return false
	}
	if len(includeTags) > 0 && !allGroupsIntersect(includeGroups, tags) {
		return false
	}
	if anyGroupIntersects(excludeGroups, tags) {
		return false
	}
	if len(performerNames) > 0 {
		for _, value := range performerNames {
			if !cast[strings.ToLower(value)] {
				return false
			}
		}
	}
	if len(studioNames) > 0 {
		wanted := map[string]bool{}
		for _, value := range studioNames {
			wanted[strings.ToLower(value)] = true
		}
		if !wanted[studio] {
			return false
		}
	}
	if performerQuery != "" {
		joined := ""
		for name := range cast {
			joined += " " + name
		}
		if !strings.Contains(joined, strings.ToLower(performerQuery)) {
			return false
		}
	}
	if studioQuery != "" && !strings.Contains(studio, strings.ToLower(studioQuery)) {
		return false
	}
	return true
}

func anyGroupIntersects(groups []map[string]bool, tags map[string]bool) bool {
	for _, group := range groups {
		for name := range group {
			if tags[name] {
				return true
			}
		}
	}
	return false
}

func allGroupsIntersect(groups []map[string]bool, tags map[string]bool) bool {
	for _, group := range groups {
		found := false
		for name := range group {
			if tags[name] {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

// expandDiverseScenes mirrors ExpandService._diverse_scenes: pick rows that
// avoid repeating the previous row's performers, falling back to the first.
func expandDiverseScenes(rows []jVal) []jVal {
	selected := make([]jVal, 0, len(rows))
	remaining := append([]jVal{}, rows...)
	for len(remaining) > 0 {
		previous := map[string]bool{}
		if len(selected) > 0 {
			for _, item := range selected[len(selected)-1].get("payload").get("performers").arr {
				previous[item.get("performer").get("id").asString()] = true
			}
		}
		index := 0
		for i, row := range remaining {
			overlap := false
			for _, item := range row.get("payload").get("performers").arr {
				if previous[item.get("performer").get("id").asString()] {
					overlap = true
					break
				}
			}
			if !overlap {
				index = i
				break
			}
		}
		selected = append(selected, remaining[index])
		remaining = append(remaining[:index], remaining[index+1:]...)
	}
	return selected
}

// blockedTagNameGroups mirrors ExpandService._blocked_tag_name_groups.
func (s *expandService) blockedTagNameGroups() ([]map[string]bool, error) {
	rows, err := s.db.Query(`SELECT tag_id FROM direct_tag_preference WHERE blocked=1`)
	if err != nil {
		return nil, err
	}
	blockedIDs := make([]string, 0)
	for rows.Next() {
		var tagID string
		if err := rows.Scan(&tagID); err != nil {
			return nil, err
		}
		blockedIDs = append(blockedIDs, tagID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(blockedIDs) == 0 {
		return nil, nil
	}
	sort.Strings(blockedIDs)
	placeholders := inClause(len(blockedIDs))
	args := make([]any, len(blockedIDs))
	for i, id := range blockedIDs {
		args[i] = id
	}
	nameRows, err := s.db.Query(`SELECT name FROM source_tag WHERE tag_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0)
	for nameRows.Next() {
		var name string
		if err := nameRows.Scan(&name); err != nil {
			return nil, err
		}
		names = append(names, name)
	}
	nameRows.Close()
	if err := nameRows.Err(); err != nil {
		return nil, err
	}
	return equivalentTagNames(s.db, names)
}

// annotateLocalMatch mirrors ExpandService._annotate_local_match.
func annotateLocalMatch(scene jVal, links jVal) jVal {
	externalID := scene.get("id").asString()
	sceneIDs := links.get("scene_ids")
	localSceneID := ""
	if v := sceneIDs.get(externalID); v.truthy() {
		localSceneID = v.asString()
	} else {
		for _, pair := range links.get("scenes").obj {
			if pair.val.asString() == externalID {
				localSceneID = pair.key
				break
			}
		}
	}
	matchType := ""
	if localSceneID != "" {
		matchType = "stashdb_id"
	}
	if localSceneID == "" {
		for _, fingerprint := range scene.get("fingerprints").arr {
			if !strings.EqualFold(pythonStrOrEmpty(fingerprint.get("algorithm")), "phash") {
				continue
			}
			value, ok := normalizePhash(fingerprint.get("hash"))
			if !ok {
				continue
			}
			if v := links.get("scene_phashes").get(value); v.truthy() {
				localSceneID = v.asString()
				matchType = "phash"
				break
			}
		}
	}
	if localSceneID == "" {
		return scene
	}
	result := cloneObj(scene)
	result.set("curator_local_match", jvObj(
		jvKey("type", jvStr(matchType)),
		jvKey("local_scene_id", jvStr(localSceneID)),
	))
	return result
}

func cloneObj(v jVal) jVal {
	return jVal{kind: jObj, obj: append([]jPair(nil), v.obj...)}
}

// matchesGender mirrors ExpandService._matches_gender.
func matchesGender(scene jVal, gender string) bool {
	if gender == "" {
		return true
	}
	wanted := strings.ToLower(gender)
	for _, item := range scene.get("performers").arr {
		if strings.ToLower(pythonStrOrEmpty(item.get("performer").get("gender"))) == wanted {
			return true
		}
	}
	return false
}

// payloadMatchesGender mirrors ExpandService._payload_matches_gender.
func payloadMatchesGender(payload jVal, entityType, gender string) bool {
	if entityType == "performer" {
		return strings.ToLower(pythonStrOrEmpty(payload.get("gender"))) == strings.ToLower(gender)
	}
	return matchesGender(payload, gender)
}

// ── external entity writes ────────────────────────────────────────────────

// mergeExternal mirrors ExpandService._merge_external: upsert discovered
// entities under BEGIN IMMEDIATE with the pool-preserving conflict clause.
func (s *expandService) mergeExternal(entityType string, items []scoredScene) error {
	now := nowMs()
	conn, err := s.db.Conn(context.Background())
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	stmt := `INSERT INTO external_entity(
  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool
) VALUES (?, ?, ?, ?, ?, ?, 'explore')
ON CONFLICT(entity_type, external_id) DO UPDATE SET
  payload_json=excluded.payload_json, score=excluded.score,
  sources_json=excluded.sources_json, fetched_at_ms=excluded.fetched_at_ms,
  pool=CASE WHEN pool='candidate' THEN 'candidate' ELSE excluded.pool END`
	for _, item := range items {
		sourcesJSON := "[]"
		if len(item.sources) > 0 {
			arr := jvArr()
			for _, src := range item.sources {
				arr.arr = append(arr.arr, jvStr(src))
			}
			sourcesJSON = arr.marshalCompact()
		}
		if _, err := conn.ExecContext(context.Background(), stmt,
			entityType, item.id, item.payload.marshalCompact(),
			item.score, sourcesJSON, now); err != nil {
			conn.ExecContext(context.Background(), "ROLLBACK")
			return err
		}
	}
	_, err = conn.ExecContext(context.Background(), "COMMIT")
	return err
}

// ── external content helpers ──────────────────────────────────────────────

// externalContent mirrors ExpandService._external_content: the scene's
// content vector keyed by StashDB tag ids (or local names), in feature order.
func (s *expandService) externalContent(sceneID string) (jVal, error) {
	featureVersion, err := currentFeatureVersion(s.db)
	if err != nil {
		return jvNull(), err
	}
	if featureVersion == "" {
		return jvObj(), nil
	}
	vectors, order, err := sceneContentVectors(s.db, featureVersion, map[string]bool{sceneID: true})
	if err != nil {
		return jvNull(), err
	}
	vector := vectors[sceneID]
	ordered := order[sceneID]
	localIDs := map[string]bool{}
	for _, name := range ordered {
		if strings.HasPrefix(name, "tag:") {
			localIDs[strings.TrimPrefix(name, "tag:")] = true
		}
	}
	if len(localIDs) == 0 {
		return jvObj(), nil
	}
	externalIDs, err := s.externalTagIDs(localIDs)
	if err != nil {
		return jvNull(), err
	}
	ids := sortedStringSet(localIDs)
	placeholders := inClause(len(ids))
	args := make([]any, len(ids))
	for i, id := range ids {
		args[i] = id
	}
	names := map[string]string{}
	nameRows, err := s.db.Query(`SELECT tag_id, name FROM source_tag WHERE tag_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return jvNull(), err
	}
	for nameRows.Next() {
		var tagID, name string
		if err := nameRows.Scan(&tagID, &name); err != nil {
			return jvNull(), err
		}
		names[tagID] = name
	}
	nameRows.Close()
	if err := nameRows.Err(); err != nil {
		return jvNull(), err
	}
	result := jvObj()
	for _, name := range ordered {
		localID := strings.TrimPrefix(name, "tag:")
		value, present := vector[name]
		_, nameOK := names[localID]
		if !present || !nameOK {
			continue
		}
		key := "name:" + strings.ToLower(names[localID])
		if external, ok := externalIDs[localID]; ok {
			key = "id:" + external
		}
		result.set(key, jvFloat(value))
	}
	return result, nil
}

// contentSpace mirrors _external_content_space's return: name mappings,
// weights, parents, and the parent weight.
type contentSpace struct {
	mappings     map[string][]string
	weights      map[string]float64
	parents      map[string][]string
	parentWeight float64
}

// externalContentSpace mirrors ExpandService._external_content_space.
func (s *expandService) externalContentSpace(featureVersion string) (*contentSpace, error) {
	var configJSON string
	err := s.db.QueryRow(`SELECT config_json FROM feature_build WHERE feature_version=?`,
		featureVersion).Scan(&configJSON)
	if err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	config := jvObj()
	if configJSON != "" {
		if parsed, err := parseJSON([]byte(configJSON)); err == nil {
			config = parsed
		}
	}
	total := maxInt64(1, scanCount(s.db, `SELECT count(*) FROM source_scene`))
	rows, err := s.db.Query(`
SELECT d.name, d.metadata_json, t.tag_id, t.name AS tag_name
FROM feature_definition d JOIN source_tag t ON d.name='tag:' || t.tag_id
WHERE d.feature_version=? AND d.family='content'`, featureVersion)
	if err != nil {
		return nil, err
	}
	type defRow struct {
		name      string
		frequency float64
		localID   string
		tagName   string
	}
	var defs []defRow
	tagIDs := map[string]bool{}
	for rows.Next() {
		var name, metadataJSON, tagID, tagName string
		if err := rows.Scan(&name, &metadataJSON, &tagID, &tagName); err != nil {
			return nil, err
		}
		metadata := jvObj()
		if parsed, err := parseJSON([]byte(metadataJSON)); err == nil {
			metadata = parsed
		}
		frequency := pythonFloatOr(metadata.get("document_frequency"), 0)
		defs = append(defs, defRow{name: name, frequency: frequency, localID: tagID, tagName: tagName})
		tagIDs[tagID] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	externalIDs, err := s.externalTagIDs(tagIDs)
	if err != nil {
		return nil, err
	}
	idfCap := pythonFloatOr(config.get("idf_cap"), 2.5)
	idfStrength := pythonFloatOr(config.get("idf_strength"), 0.5)
	oneOffPrior := pythonFloatOr(config.get("one_off_prior"), 2.0)
	mappings := map[string][]string{}
	weights := map[string]float64{}
	for _, def := range defs {
		rarity := math.Min(idfCap, 1+idfStrength*pyLog((float64(total)+1)/(def.frequency+1)))
		weight := rarity * def.frequency / (def.frequency + oneOffPrior)
		weights[def.name] = weight
		nameKey := "name:" + strings.ToLower(def.tagName)
		mappings[nameKey] = append(mappings[nameKey], def.name)
		if external, ok := externalIDs[def.localID]; ok {
			mappings["id:"+external] = append(mappings["id:"+external], def.name)
		}
	}
	parents := map[string][]string{}
	parentRows, err := s.db.Query(`SELECT tag_id, parent_tag_id FROM tag_parent`)
	if err != nil {
		return nil, err
	}
	for parentRows.Next() {
		var child, parent string
		if err := parentRows.Scan(&child, &parent); err != nil {
			return nil, err
		}
		childName := "tag:" + child
		parentName := "tag:" + parent
		if _, ok := weights[childName]; !ok {
			continue
		}
		if _, ok := weights[parentName]; !ok {
			continue
		}
		parents[childName] = append(parents[childName], parentName)
	}
	parentRows.Close()
	if err := parentRows.Err(); err != nil {
		return nil, err
	}
	return &contentSpace{
		mappings:     mappings,
		weights:      weights,
		parents:      parents,
		parentWeight: pythonFloatOr(config.get("parent_weight"), 0.35),
	}, nil
}

// externalCandidateContent mirrors ExpandService._external_candidate_content:
// a normalized content vector for an external scene's tags.
func externalCandidateContent(tags jVal, space *contentSpace) jVal {
	base := map[string]float64{}
	var baseOrder []string
	for _, tag := range tags.arr {
		seen := map[string]bool{}
		names := append([]string{}, space.mappings["id:"+tag.get("id").asString()]...)
		names = append(names, space.mappings["name:"+strings.ToLower(pythonStrOrEmpty(tag.get("name")))]...)
		for _, name := range names {
			if seen[name] {
				continue
			}
			seen[name] = true
			if _, ok := base[name]; !ok {
				baseOrder = append(baseOrder, name)
			}
			base[name] = 1.0
			for _, parent := range space.parents[name] {
				if _, ok := base[parent]; !ok {
					baseOrder = append(baseOrder, parent)
				}
				if base[parent] < space.parentWeight {
					base[parent] = space.parentWeight
				}
			}
		}
	}
	vector := map[string]float64{}
	var order []string
	squares := make([]float64, 0, len(baseOrder))
	for _, name := range baseOrder {
		value := base[name] * space.weights[name]
		vector[name] = value
		order = append(order, name)
		squares = append(squares, value*value)
	}
	norm := math.Sqrt(neumaierSum(squares))
	if norm == 0 {
		norm = 1.0
	}
	result := jvObj()
	for _, name := range order {
		result.set(name, jvFloat(vector[name]/norm))
	}
	return result
}

// externalTagIDs mirrors ExpandService._external_tag_ids: direct
// source_tag_stash_id rows, then the taxonomy index fallback.
func (s *expandService) externalTagIDs(localIDs map[string]bool) (map[string]string, error) {
	if len(localIDs) == 0 {
		return map[string]string{}, nil
	}
	ids := sortedStringSet(localIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	for _, id := range ids {
		args = append(args, id)
	}
	args = append(args, stashdbEndpoint)
	result := map[string]string{}
	rows, err := s.db.Query(`SELECT tag_id, stash_id FROM source_tag_stash_id WHERE tag_id IN (`+
		placeholders+`) AND lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))`, args...)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, stashID string
		if err := rows.Scan(&tagID, &stashID); err != nil {
			return nil, err
		}
		result[tagID] = stashID
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// The taxonomy index loads the snapshot tables once (mirroring Python's
	// TaxonomyIndex constructor); resolve() then queries only the per-tag
	// stash ids and matches against memory.
	taxonomy, err := newTaxonomyIndex(s.db)
	if err != nil {
		return nil, err
	}
	nameRows, err := s.db.Query(`SELECT tag_id, name FROM source_tag WHERE tag_id IN (`+placeholders+`)`, args[:len(ids)]...)
	if err != nil {
		return nil, err
	}
	// Collect the rows before resolving: the taxonomy resolve queries the
	// same single pooled connection, and a nested query while nameRows is
	// still open would deadlock against SetMaxOpenConns(1).
	pairs := make([]struct {
		tagID string
		name  string
	}, 0)
	for nameRows.Next() {
		var tagID, name string
		if err := nameRows.Scan(&tagID, &name); err != nil {
			return nil, err
		}
		pairs = append(pairs, struct {
			tagID string
			name  string
		}{tagID: tagID, name: name})
	}
	nameRows.Close()
	if err := nameRows.Err(); err != nil {
		return nil, err
	}
	for _, pair := range pairs {
		if _, ok := result[pair.tagID]; ok {
			continue
		}
		match, err := taxonomy.resolve(s.db, pair.tagID, pair.name)
		if err != nil {
			return nil, err
		}
		if match.externalTagID != "" && match.confidence >= 0.9 {
			result[pair.tagID] = match.externalTagID
		}
	}
	return result, nil
}

// probeTagIDs mirrors ExpandService._probe_tag_ids: mapped tag ids ordered
// by document-frequency rarity (weight as the tie-break), at most 10.
func (s *expandService) probeTagIDs(content jVal) ([]string, error) {
	// Python: sorted(content, key=content.__getitem__, reverse=True)
	keys := make([]string, 0, len(content.obj))
	for _, pair := range content.obj {
		keys = append(keys, pair.key)
	}
	sort.SliceStable(keys, func(i, j int) bool {
		return pythonFloatOr(content.get(keys[i]), 0) > pythonFloatOr(content.get(keys[j]), 0)
	})
	ordered := make([]string, 0)
	for _, key := range keys {
		if strings.HasPrefix(key, "id:") {
			ordered = append(ordered, strings.TrimPrefix(key, "id:"))
		}
	}
	if len(ordered) == 0 {
		return nil, nil
	}
	placeholders := inClause(len(ordered))
	args := make([]any, 0, len(ordered)+1)
	for _, id := range ordered {
		args = append(args, id)
	}
	args = append(args, stashdbEndpoint)
	localIDs := map[string]string{}
	rows, err := s.db.Query(`SELECT tag_id, stash_id FROM source_tag_stash_id
WHERE lower(rtrim(endpoint, '/'))=lower(rtrim(?, '/'))
  AND stash_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var tagID, stashID string
		if err := rows.Scan(&tagID, &stashID); err != nil {
			return nil, err
		}
		localIDs[stashID] = tagID
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	frequencies := map[string]float64{}
	if len(localIDs) > 0 {
		seen := map[string]bool{}
		valueIDs := make([]string, 0, len(localIDs))
		for _, tagID := range localIDs {
			if !seen[tagID] {
				seen[tagID] = true
				valueIDs = append(valueIDs, tagID)
			}
		}
		sort.Strings(valueIDs)
		valuePlaceholders := inClause(len(valueIDs))
		valueArgs := make([]any, 0, len(valueIDs))
		for _, tagID := range valueIDs {
			valueArgs = append(valueArgs, "tag:"+tagID)
		}
		freqRows, err := s.db.Query(`SELECT replace(name, 'tag:', '') AS local_id, metadata_json
FROM feature_definition
WHERE family='content' AND name IN (`+valuePlaceholders+`)`, valueArgs...)
		if err != nil {
			return nil, err
		}
		for freqRows.Next() {
			var localID, metadataJSON string
			if err := freqRows.Scan(&localID, &metadataJSON); err != nil {
				return nil, err
			}
			metadata := jvObj()
			if parsed, err := parseJSON([]byte(metadataJSON)); err == nil {
				metadata = parsed
			}
			frequency, err := pythonFloat(metadata.get("document_frequency"))
			if err != nil {
				continue
			}
			frequencies[localID] = frequency
		}
		freqRows.Close()
		if err := freqRows.Err(); err != nil {
			return nil, err
		}
	}
	sort.SliceStable(ordered, func(i, j int) bool {
		leftID := localIDs[ordered[i]]
		rightID := localIDs[ordered[j]]
		leftFreq, leftOK := frequencies[leftID]
		if !leftOK {
			leftFreq = 1e9
		}
		rightFreq, rightOK := frequencies[rightID]
		if !rightOK {
			rightFreq = 1e9
		}
		if leftFreq != rightFreq {
			return leftFreq < rightFreq
		}
		return -pythonFloatOr(content.get("id:"+ordered[i]), 0) < -pythonFloatOr(content.get("id:"+ordered[j]), 0)
	})
	if len(ordered) > 10 {
		ordered = ordered[:10]
	}
	return ordered, nil
}

// ── StashDB fetches ───────────────────────────────────────────────────────

// fetchPageSpec mirrors one _fetch probe: source, values, limit, modifier, sort.
type fetchPageSpec struct {
	source   string
	values   []string
	limit    int64
	modifier string
	sort     string
	since    string
}

// fetchScenes runs one _fetch pass (sequential pages), mirroring the Python
// loop exactly. Rows and sources are merged with first-seen semantics.
func fetchScenes(clientURL, apiKey string, spec fetchPageSpec, rows *sceneRows, sources map[string]map[string]bool) (int64, bool, error) {
	fetched := int64(0)
	page := int64(1)
	total := int64(0)
	pageSize := minInt64(250, spec.limit)
	for fetched < spec.limit {
		pageTotal, batch, err := fetchScenesPage(clientURL, apiKey, spec, page, pageSize)
		if err != nil {
			return 0, false, err
		}
		total = pageTotal
		accepted := batch
		if int64(len(accepted)) > spec.limit-fetched {
			accepted = batch[:spec.limit-fetched]
		}
		for _, scene := range accepted {
			identifier := scene.get("id").asString()
			rows.add(identifier, scene)
			sourceSet := sources[identifier]
			if sourceSet == nil {
				sourceSet = map[string]bool{}
				sources[identifier] = sourceSet
			}
			sourceSet[spec.source] = true
		}
		fetched += int64(len(accepted))
		if len(batch) == 0 || fetched >= total {
			break
		}
		page++
	}
	return total, fetched < total, nil
}

// fetchScenesPage executes one SCENES query page and returns (count, scenes).
func fetchScenesPage(clientURL, apiKey string, spec fetchPageSpec, page, pageSize int64) (int64, []jVal, error) {
	query := jvObj(
		jvKey("page", jvInt(page)),
		jvKey("per_page", jvInt(pageSize)),
		jvKey("sort", jvStr("TRENDING")),
		jvKey("direction", jvStr("DESC")),
	)
	if spec.source != "wildcard" {
		query.set("sort", jvStr(spec.sort))
		values := jvArr()
		for _, value := range spec.values {
			values.arr = append(values.arr, jvStr(value))
		}
		query.set(spec.source, jvObj(
			jvKey("value", values),
			jvKey("modifier", jvStr(spec.modifier)),
		))
	}
	if spec.since != "" && spec.source != "wildcard" {
		query.set("updated_at", jvObj(
			jvKey("value", jvStr(spec.since)),
			jvKey("modifier", jvStr("GREATER_THAN")),
		))
		query.set("sort", jvStr("UPDATED_AT"))
	}
	data, err := stashdbQuery(clientURL, apiKey, stashdbScenesQuery, jvObj(jvKey("input", query)))
	if err != nil {
		return 0, nil, err
	}
	scenesData := data.get("queryScenes")
	total := pythonInt(scenesData.get("count"))
	batch := append([]jVal{}, scenesData.get("scenes").arr...)
	return total, batch, nil
}

// fetchParallel mirrors _fetch with the pagination fanned out over a bounded
// stdlib worker pool: page 1 is fetched synchronously (its count fixes the
// page count), the remaining pages run in parallel, and results merge in
// page order so the output is identical to the sequential loop.
func fetchParallel(clientURL, apiKey string, spec fetchPageSpec, rows *sceneRows, sources map[string]map[string]bool, workers int) (int64, bool, error) {
	pageSize := minInt64(250, spec.limit)
	mergePage := func(pageTotal int64, accepted []jVal) {
		for _, scene := range accepted {
			identifier := scene.get("id").asString()
			rows.add(identifier, scene)
			sourceSet := sources[identifier]
			if sourceSet == nil {
				sourceSet = map[string]bool{}
				sources[identifier] = sourceSet
			}
			sourceSet[spec.source] = true
		}
	}
	total, batch, err := fetchScenesPage(clientURL, apiKey, spec, 1, pageSize)
	if err != nil {
		return 0, false, err
	}
	accepted := batch
	if int64(len(accepted)) > spec.limit {
		accepted = batch[:spec.limit]
	}
	mergePage(total, accepted)
	fetched := int64(len(accepted))
	if len(batch) == 0 || fetched >= total {
		return total, fetched < total, nil
	}
	pagesNeeded := (minInt64(total, spec.limit) + pageSize - 1) / pageSize
	type pageResult struct {
		total int64
		batch []jVal
		err   error
	}
	results := make([]pageResult, pagesNeeded)
	results[0] = pageResult{total: total, batch: accepted}
	if workers < 1 {
		workers = 1
	}
	pageCh := make(chan int64)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for p := range pageCh {
				pageTotal, pageBatch, err := fetchScenesPage(clientURL, apiKey, spec, p, pageSize)
				results[p-1] = pageResult{total: pageTotal, batch: pageBatch, err: err}
			}
		}()
	}
	for p := int64(2); p <= pagesNeeded; p++ {
		pageCh <- p
	}
	close(pageCh)
	wg.Wait()
	var firstErr error
	lastTotal := total
	for _, res := range results[1:] {
		if res.err != nil {
			if firstErr == nil {
				firstErr = res.err
			}
			continue
		}
		lastTotal = res.total
	}
	if firstErr != nil {
		return 0, false, firstErr
	}
	merged := fetched
	for _, res := range results[1:] {
		remaining := spec.limit - merged
		if remaining <= 0 {
			break
		}
		pageAccepted := res.batch
		if int64(len(pageAccepted)) > remaining {
			pageAccepted = res.batch[:remaining]
		}
		mergePage(res.total, pageAccepted)
		merged += int64(len(pageAccepted))
	}
	return lastTotal, merged < total, nil
}

// fetchProbes mirrors ExpandService._fetch_probes: each probe runs its own
// sequential page loop, and the probes run concurrently (Python's
// ThreadPoolExecutor). Results merge in probe order.
func fetchProbes(clientURL, apiKey string, probes []fetchPageSpec) (*sceneRows, map[string]map[string]bool, error) {
	rows := &sceneRows{m: map[string]jVal{}}
	sources := map[string]map[string]bool{}
	if len(probes) == 0 {
		return rows, sources, nil
	}
	type probeResult struct {
		rows    *sceneRows
		sources map[string]map[string]bool
		err     error
	}
	results := make([]probeResult, len(probes))
	var wg sync.WaitGroup
	for i, spec := range probes {
		wg.Add(1)
		go func(index int, spec fetchPageSpec) {
			defer wg.Done()
			probeRows := &sceneRows{m: map[string]jVal{}}
			probeSources := map[string]map[string]bool{}
			_, _, err := fetchScenes(clientURL, apiKey, spec, probeRows, probeSources)
			results[index] = probeResult{rows: probeRows, sources: probeSources, err: err}
		}(i, spec)
	}
	wg.Wait()
	for _, res := range results {
		if res.err != nil {
			return nil, nil, res.err
		}
		for _, id := range res.rows.order {
			rows.add(id, res.rows.m[id])
		}
		for identifier, values := range res.sources {
			sourceSet := sources[identifier]
			if sourceSet == nil {
				sourceSet = map[string]bool{}
				sources[identifier] = sourceSet
			}
			for value := range values {
				sourceSet[value] = true
			}
		}
	}
	return rows, sources, nil
}

// fetchPerformerPool mirrors ExpandService._fetch_performer_pool: union of
// popularity-ranked StashDB performer queries, run concurrently, merged by
// first-seen performer id.
func fetchPerformerPool(clientURL, apiKey string, target *performerProfile, gender, ethnicity, performedWith string) ([]jVal, error) {
	type querySpec struct {
		performedWith string
		ageLower      int64
		hasAge        bool
	}
	specs := []querySpec{{}}
	if performedWith != "" {
		specs = append(specs, querySpec{performedWith: performedWith})
	}
	if target != nil {
		if age, ok := target.blocks["age"]["age_recording"]; ok {
			lower := int64(age.value - 12)
			if lower >= 25 {
				specs = append(specs, querySpec{ageLower: lower, hasAge: true})
			}
		}
	}
	type poolResult struct {
		performers []jVal
		err        error
	}
	results := make([]poolResult, len(specs))
	var wg sync.WaitGroup
	for i, spec := range specs {
		wg.Add(1)
		go func(index int, spec querySpec) {
			defer wg.Done()
			query := jvObj(
				jvKey("page", jvInt(1)),
				jvKey("per_page", jvInt(500)),
				jvKey("sort", jvStr("POPULARITY")),
				jvKey("direction", jvStr("DESC")),
			)
			if gender != "" {
				query.set("gender", jvStr(gender))
			}
			if ethnicity != "" {
				query.set("ethnicity", jvStr(ethnicity))
			}
			if spec.performedWith != "" {
				query.set("performed_with", jvStr(spec.performedWith))
			}
			if spec.hasAge {
				query.set("age", jvObj(
					jvKey("value", jvInt(spec.ageLower)),
					jvKey("modifier", jvStr("GREATER_THAN")),
				))
			}
			data, err := stashdbQuery(clientURL, apiKey, stashdbPerformersQuery, jvObj(jvKey("input", query)))
			if err != nil {
				results[index] = poolResult{err: err}
				return
			}
			performers := append([]jVal{}, data.get("queryPerformers").get("performers").arr...)
			results[index] = poolResult{performers: performers}
		}(i, spec)
	}
	wg.Wait()
	pooled := map[string]jVal{}
	var order []string
	for _, res := range results {
		if res.err != nil {
			return nil, res.err
		}
		for _, performer := range res.performers {
			id := performer.get("id").asString()
			if _, ok := pooled[id]; !ok {
				pooled[id] = performer
				order = append(order, id)
			}
		}
	}
	out := make([]jVal, 0, len(order))
	for _, id := range order {
		out = append(out, pooled[id])
	}
	return out, nil
}

// ── scoring ───────────────────────────────────────────────────────────────

// performerEvidence mirrors _performer_evidence; the ordered keys preserve
// the SQL row order for the anchor list.
func (s *expandService) performerEvidence(modelID string, links jVal) (map[string]*performerEvidence, []string, error) {
	result := map[string]*performerEvidence{}
	var order []string
	rows, err := s.db.Query(`
WITH appeal AS (
  SELECT scene_id, max(appeal) AS value FROM model_scene_lane
  WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id
)
SELECT p.performer_id, p.name, p.favorite,
  COALESCE(SUM(s.play_count), 0) AS play_count,
  COALESCE(SUM(CASE WHEN s.play_count > 0 THEN a.value * s.play_count END)
    / NULLIF(SUM(CASE WHEN s.play_count > 0 THEN s.play_count END), 0), 0)
    AS observed_appeal
FROM source_performer p
LEFT JOIN scene_performer sp USING(performer_id)
LEFT JOIN source_scene s USING(scene_id)
LEFT JOIN appeal a USING(scene_id)
GROUP BY p.performer_id`, modelID)
	if err != nil {
		return nil, nil, err
	}
	performers := links.get("performers")
	for rows.Next() {
		var performerID, name string
		var favorite, playCount int64
		var observedAppeal float64
		if err := rows.Scan(&performerID, &name, &favorite, &playCount, &observedAppeal); err != nil {
			return nil, nil, err
		}
		externalID := ""
		if v := performers.get(performerID); v.truthy() {
			externalID = v.asString()
		}
		if externalID == "" {
			continue
		}
		plays := playCount
		strength := math.Min(1.0,
			boolFloat(favorite != 0)*0.55+
				math.Min(0.35, 0.12*math.Log1p(float64(plays)))*math.Max(0.0, math.Min(1.0, (observedAppeal+1)/2))+
				0.10*math.Max(0.0, observedAppeal))
		result[externalID] = &performerEvidence{
			localID:   performerID,
			name:      name,
			favorite:  favorite != 0,
			playCount: plays,
			strength:  strength,
		}
		order = append(order, externalID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	return result, order, nil
}

// profileMatch mirrors ExpandService._profile_match: combined similarity
// scaled by profile coverage.
func profileMatch(left, right *performerProfile, weights map[string]float64) (float64, float64) {
	total, _, used := performerSimilarity(left, right, weights)
	relevant := 0.0
	for key, value := range weights {
		if key != "content" {
			relevant += value
		}
	}
	coverage := 0.0
	if relevant != 0 {
		weightValues := make([]float64, 0, len(used))
		for _, value := range used {
			weightValues = append(weightValues, value)
		}
		coverage = math.Min(1.0, neumaierSum(weightValues)/relevant)
	}
	return total * math.Sqrt(coverage), coverage
}

// profileConflicts mirrors ExpandService._profile_conflicts.
func profileConflicts(left, right *performerProfile) []string {
	conflicts := []string{}
	leftCup, leftOK := profileValueAt(left, "measurements", "cup_index")
	rightCup, rightOK := profileValueAt(right, "measurements", "cup_index")
	if leftOK && rightOK && math.Abs(leftCup.value-rightCup.value) >= 2 {
		conflicts = append(conflicts, "cup size")
	}
	leftAug, leftHasAug := left.blocks["augmentation"]
	rightAug, rightHasAug := right.blocks["augmentation"]
	if leftHasAug && rightHasAug && len(leftAug) > 0 && len(rightAug) > 0 && !keysOverlap(leftAug, rightAug) {
		conflicts = append(conflicts, "augmentation")
	}
	leftAge, leftAgeOK := profileValueAt(left, "age", "age_recording")
	rightAge, rightAgeOK := profileValueAt(right, "age", "age_recording")
	if leftAgeOK && rightAgeOK && math.Abs(leftAge.value-rightAge.value) >= 12 {
		conflicts = append(conflicts, "age")
	}
	return conflicts
}

// score mirrors ExpandService._score: score every annotated scene and derive
// the external performer rows. The multi-hop reach blends when multiHopSeed
// is set. Returns the scene rows and the external performer rows.
func (s *expandService) score(scenes []jVal, sources map[string]map[string]bool,
	modelID, featureVersion string, links jVal, multiHopSeed jVal) ([]scoredScene, []scoredScene, error) {
	tagAffinity := map[string]float64{}
	rows, err := s.db.Query(`
SELECT ids.stash_id, t.name, a.affinity * a.confidence AS value
FROM feature_affinity a JOIN feature_definition d USING(feature_id)
JOIN source_tag t ON d.name='tag:' || t.tag_id
LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
  AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))
WHERE a.model_id=? AND d.feature_version=? AND d.family='content'`,
		stashdbEndpoint, modelID, featureVersion)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var stashID sql.NullString
		var name string
		var value float64
		if err := rows.Scan(&stashID, &name, &value); err != nil {
			return nil, nil, err
		}
		tagAffinity["name:"+strings.ToLower(name)] = value
		if stashID.Valid && stashID.String != "" {
			tagAffinity["id:"+stashID.String] = value
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	prefRows, err := s.db.Query(`
SELECT ids.stash_id, t.name, p.value
FROM direct_tag_preference p JOIN source_tag t USING(tag_id)
LEFT JOIN source_tag_stash_id ids ON ids.tag_id=t.tag_id
  AND lower(rtrim(ids.endpoint, '/'))=lower(rtrim(?, '/'))`, stashdbEndpoint)
	if err != nil {
		return nil, nil, err
	}
	for prefRows.Next() {
		var stashID sql.NullString
		var name string
		var value float64
		if err := prefRows.Scan(&stashID, &name, &value); err != nil {
			return nil, nil, err
		}
		nameKey := "name:" + strings.ToLower(name)
		if _, ok := tagAffinity[nameKey]; !ok {
			tagAffinity[nameKey] = value
		}
		if stashID.Valid && stashID.String != "" {
			idKey := "id:" + stashID.String
			if _, ok := tagAffinity[idKey]; !ok {
				tagAffinity[idKey] = value
			}
		}
	}
	prefRows.Close()
	if err := prefRows.Err(); err != nil {
		return nil, nil, err
	}
	externalStudioAppeal := map[string]float64{}
	appealRows, err := s.db.Query(`
WITH appeal AS (
  SELECT scene_id, max(appeal) AS value FROM model_scene_lane
  WHERE model_id=? AND appeal IS NOT NULL GROUP BY scene_id
)
SELECT s.studio_id, AVG(a.value) AS appeal
FROM source_scene s JOIN appeal a USING(scene_id)
WHERE s.studio_id IS NOT NULL GROUP BY s.studio_id`, modelID)
	if err != nil {
		return nil, nil, err
	}
	studios := links.get("studios")
	for appealRows.Next() {
		var studioID string
		var appeal float64
		if err := appealRows.Scan(&studioID, &appeal); err != nil {
			return nil, nil, err
		}
		if v := studios.get(studioID); v.truthy() {
			externalStudioAppeal[v.asString()] = appeal
		}
	}
	appealRows.Close()
	if err := appealRows.Err(); err != nil {
		return nil, nil, err
	}
	evidence, evidenceOrder, err := s.performerEvidence(modelID, links)
	if err != nil {
		return nil, nil, err
	}
	evidenceByLocal := map[string]*performerEvidence{}
	for _, item := range evidence {
		evidenceByLocal[item.localID] = item
	}
	anchorIDs := map[string]bool{}
	for _, item := range evidence {
		if item.strength > 0 {
			anchorIDs[item.localID] = true
		}
	}
	profiles, err := performerProfilesForIDs(s.db, featureVersion, anchorIDs)
	if err != nil {
		return nil, nil, err
	}
	localStudios := map[string]string{}
	for _, pair := range studios.obj {
		localStudios[pair.val.asString()] = pair.key
	}
	anchorPairs := make([]anchorPair, 0, len(evidenceOrder))
	for _, externalID := range evidenceOrder {
		item := evidence[externalID]
		profile, ok := profiles[item.localID]
		if !ok {
			continue
		}
		anchorPairs = append(anchorPairs, anchorPair{profile: profile, evidence: item})
	}
	weights := map[string]float64{}
	for _, item := range performerBlockWeights {
		weights[item.block] = item.weight
	}
	matcher := newAnchorMatcher(anchorPairs, weights)
	if os.Getenv("CURATOR_STATS") != "" {
		fmt.Fprintf(os.Stderr, "[stats] anchors=%d unique=%d\n", len(anchorPairs), 0)
	}

	// The dominant cost on large libraries is the anchor comparison: every
	// fetched scene's cast is measured against every positive-strength local
	// anchor. The terms are scene-independent, so they are precomputed once
	// per unique external performer with a bounded worker pool, then each
	// scene is scored in parallel. Results merge in scene order afterwards,
	// so the output is byte-identical to the sequential loop.
	uniquePerformers := make([]jVal, 0)
	seenPerformers := map[string]bool{}
	for _, scene := range scenes {
		for _, item := range scene.get("performers").arr {
			p := item.get("performer")
			id := p.get("id").asString()
			if evidence[id] == nil && !seenPerformers[id] {
				seenPerformers[id] = true
				uniquePerformers = append(uniquePerformers, p)
			}
		}
	}
	if os.Getenv("CURATOR_STATS") != "" {
		fmt.Fprintf(os.Stderr, "[stats] unique=%d\n", len(uniquePerformers))
	}
	t0 := time.Now()
	matcher.precomputeTerms(uniquePerformers, runtime.GOMAXPROCS(0))
	if os.Getenv("CURATOR_STATS") != "" {
		fmt.Fprintf(os.Stderr, "[stats] precompute=%.2fs\n", time.Since(t0).Seconds())
	}

	type castContribution struct {
		externalID string
		payload    jVal
		score      float64
	}
	type sceneWork struct {
		row          scoredScene
		castContribs []castContribution
	}
	work := make([]sceneWork, len(scenes))
	var bestCalls int64
	var bestTimeNs int64
	var bestMutex sync.Mutex
	workCh := make(chan int)
	var wg sync.WaitGroup
	workers := runtime.GOMAXPROCS(0)
	if workers < 1 {
		workers = 1
	}
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range workCh {
				scene := scenes[index]
				signals := make([]float64, 0, len(scene.get("tags").arr))
				for _, tag := range scene.get("tags").arr {
					signals = append(signals, expandTagValue(tag, tagAffinity))
				}
				sort.SliceStable(signals, func(i, j int) bool { return math.Abs(signals[i]) > math.Abs(signals[j]) })
				if len(signals) > 5 {
					signals = signals[:5]
				}
				tagValue := pyTanh(neumaierSum(signals))
				cast := make([]jVal, 0, len(scene.get("performers").arr))
				for _, item := range scene.get("performers").arr {
					cast = append(cast, item.get("performer"))
				}
				castWeight := expandCastWeight(len(cast))
				identity := 0.0
				for _, performer := range cast {
					if item := evidence[performer.get("id").asString()]; item != nil {
						if item.strength > identity {
							identity = item.strength
						}
					}
				}
				identity *= castWeight
				studio := scene.get("studio")
				if studio.kind != jObj {
					studio = jvObj()
				}
				studioValue := 0.0
				if v := studio.get("id"); v.truthy() {
					studioValue = externalStudioAppeal[v.asString()]
				}
				studioPayload := cloneObj(studio)
				if v := studio.get("id"); v.truthy() {
					if local, ok := localStudios[v.asString()]; ok {
						studioPayload.set("curator_local", jvObj(jvKey("id", jvStr(local))))
					}
				}
				similarityValue := 0.0
				contribs := make([]castContribution, 0, len(cast))
				for _, performer := range cast {
					externalID := performer.get("id").asString()
					local := evidence[externalID]
					recorded := scene.get("production_date")
					if !recorded.truthy() {
						recorded = scene.get("release_date")
					}
					match, hasMatch := anchorMatch{}, false
					if local == nil {
						if os.Getenv("CURATOR_STATS") != "" {
							tBest := time.Now()
							match, hasMatch = matcher.best(performer, recorded)
							bestMutex.Lock()
							bestCalls++
							bestTimeNs += time.Since(tBest).Nanoseconds()
							bestMutex.Unlock()
						} else {
							match, hasMatch = matcher.best(performer, recorded)
						}
					}
					strength := 0.0
					matchValue := 0.0
					if hasMatch {
						strength = match.evidence.strength
						matchValue = match.value
					}
					similarityValue = math.Max(similarityValue, matchValue*strength*castWeight)
					performerPayload := cloneObj(performer)
					if local != nil {
						performerPayload.set("curator_local", jvObj(
							jvKey("id", jvStr(local.localID)),
							jvKey("favorite", jvBool(local.favorite)),
							jvKey("play_count", jvInt(local.playCount)),
						))
					}
					if hasMatch && matchValue > 0 {
						blocks := make([]string, 0, len(match.similarities))
						for block := range match.similarities {
							blocks = append(blocks, block)
						}
						sort.SliceStable(blocks, func(i, j int) bool {
							return match.similarities[blocks[i]]*match.usedWeights[blocks[i]] >
								match.similarities[blocks[j]]*match.usedWeights[blocks[j]]
						})
						if len(blocks) > 3 {
							blocks = blocks[:3]
						}
						attributes := make([]string, 0, len(blocks))
						for _, block := range blocks {
							attributes = append(attributes, strings.ReplaceAll(block, "augmentation", "breast type"))
						}
						name := match.evidence.name
						if name == "" {
							name = "a performer you enjoy"
						}
						performerPayload.set("why", jvArr(jvStr("Similar to "+name+" in "+strings.Join(attributes, ", "))))
					}
					performerScore := 0.0
					if hasMatch {
						performerScore = matchValue * (0.7 + 0.3*strength)
					}
					contribs = append(contribs, castContribution{
						externalID: externalID,
						payload:    performerPayload,
						score:      performerScore,
					})
				}
				score := 0.45*tagValue + 0.25*identity + 0.10*studioValue + 0.20*similarityValue
				payload := cloneObj(scene)
				payload.set("studio", studioPayload)
				payload.set("why", expandWhy(scene, tagAffinity, identity, similarityValue, len(cast)))
				work[index] = sceneWork{
					row: scoredScene{
						id:      scene.get("id").asString(),
						payload: payload,
						score:   score,
						sources: sortedStringSet(sources[scene.get("id").asString()]),
					},
					castContribs: contribs,
				}
			}
		}()
	}
	for i := range scenes {
		workCh <- i
	}
	close(workCh)
	wg.Wait()
	if os.Getenv("CURATOR_STATS") != "" {
		fmt.Fprintf(os.Stderr, "[stats] scene-pool=%.2fs best=%d calls avg=%.3fms\n",
			time.Since(t0).Seconds(), bestCalls, float64(bestTimeNs)/1e6/float64(maxInt64(1, bestCalls)))
	}

	// Merge the cast contributions in scene order (Python's setdefault /
	// max / sources-union order), then render each scene's performers list
	// from the merged rows — exactly like the sequential loop.
	performerRows := map[string]*expandPerformerRow{}
	var performerOrder []string
	sceneRows := make([]scoredScene, 0, len(scenes))
	for _, w := range work {
		for _, contrib := range w.castContribs {
			externalID := contrib.externalID
			row := performerRows[externalID]
			if row == nil {
				row = &expandPerformerRow{
					id:      externalID,
					payload: contrib.payload,
					sources: map[string]bool{},
				}
				performerRows[externalID] = row
				performerOrder = append(performerOrder, externalID)
			}
			if contrib.score > row.score {
				row.score = contrib.score
			}
			for source := range sources[w.row.id] {
				row.sources[source] = true
			}
		}
		payload := w.row.payload
		performersJSON := jvArr()
		for _, contrib := range w.castContribs {
			// The rendered performer payload is the merged first-seen row.
			performersJSON.arr = append(performersJSON.arr,
				jvObj(jvKey("performer", performerRows[contrib.externalID].payload)))
		}
		payload.set("performers", performersJSON)
		sceneRows = append(sceneRows, w.row)
	}

	// Multi-hop reach blend (only when a seed is provided). The personalized
	// walk depends only on the seed, so it is computed once and reused for
	// every scene (Python re-walks per scene; the result is identical).
	performers := links.get("performers")
	if multiHopSeed.kind != jNull {
		mh := newMultiHop(s.db, modelID)
		if err := mh.load(); err != nil {
			return nil, nil, err
		}
		seedScores, err := mh.walk(multiHopSeed.asString())
		if err != nil {
			return nil, nil, err
		}
		for i := range sceneRows {
			row := &sceneRows[i]
			localIDs := map[string]bool{}
			for _, item := range row.payload.get("performers").arr {
				remote := item.get("performer")
				if remote.kind != jObj {
					continue
				}
				pid := remote.get("id")
				if !pid.truthy() {
					continue
				}
				if local := performers.get(pid.asString()); local.truthy() {
					localIDs[local.asString()] = true
				}
			}
			if len(localIDs) == 0 {
				continue
			}
			mhScore := 0.0
			for performerID := range localIDs {
				if score, ok := seedScores[performerID]; ok && score >= multiHopReachFloor && score > mhScore {
					mhScore = score
				}
			}
			row.multiHopReach = mhScore
			row.hasMultiHop = true
			row.score = row.score + remoteMultiHopWeight*mhScore
		}
	}

	ownedPerformers := map[string]bool{}
	for _, pair := range performers.obj {
		ownedPerformers[pair.val.asString()] = true
	}
	performerOutputs := make([]scoredScene, 0)
	for _, externalID := range performerOrder {
		if ownedPerformers[externalID] {
			continue
		}
		row := performerRows[externalID]
		performerOutputs = append(performerOutputs, scoredScene{
			id:      row.id,
			payload: row.payload,
			score:   row.score,
			sources: sortedStringSet(row.sources),
		})
	}
	return sceneRows, performerOutputs, nil
}

// ── helpers ───────────────────────────────────────────────────────────────

// sceneRows is an insertion-ordered scene map (Python dict semantics: the
// row order the fetch merges produce is part of the byte-identical output).
type sceneRows struct {
	m     map[string]jVal
	order []string
}

func (r *sceneRows) add(id string, scene jVal) {
	if _, ok := r.m[id]; !ok {
		r.m[id] = scene
		r.order = append(r.order, id)
	}
}

func (r *sceneRows) list() []jVal {
	out := make([]jVal, 0, len(r.order))
	for _, id := range r.order {
		out = append(out, r.m[id])
	}
	return out
}

func jvStrList(values []string) jVal {
	arr := jvArr()
	for _, value := range values {
		arr.arr = append(arr.arr, jvStr(value))
	}
	return arr
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func sortedStringSet(values map[string]bool) []string {
	out := make([]string, 0, len(values))
	for value := range values {
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}

// currentFeatureVersion mirrors FeatureStore.current_version: the attached
// feature generation id, else the published feature_build row.
func currentFeatureVersion(db dbx) (string, error) {
	if attached := attachedGenerationID(db, "feature"); attached != "" {
		return attached, nil
	}
	var version string
	err := db.QueryRow(`SELECT feature_version FROM feature_build WHERE status='published'`).Scan(&version)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return version, nil
}

// performerProfilesForIDs mirrors FeatureStore.performer_profiles restricted
// to a set of performer ids.
func performerProfilesForIDs(db dbx, featureVersion string, performerIDs map[string]bool) (map[string]*performerProfile, error) {
	if len(performerIDs) == 0 {
		return map[string]*performerProfile{}, nil
	}
	ids := sortedStringSet(performerIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, featureVersion)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT ef.entity_id, fd.family, fd.name, ef.value, ef.confidence
FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
WHERE ef.feature_version=? AND ef.entity_type='performer' AND fd.family LIKE 'profile:%'
  AND ef.entity_id IN (`+placeholders+`)
ORDER BY ef.entity_id, ef.feature_id`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	profiles := make(map[string]*performerProfile)
	for rows.Next() {
		var entityID, family, name string
		var value, confidence float64
		if err := rows.Scan(&entityID, &family, &name, &value, &confidence); err != nil {
			return nil, err
		}
		profile := profiles[entityID]
		if profile == nil {
			profile = &performerProfile{
				id:     entityID,
				blocks: map[string]map[string]profileValue{},
				norms:  map[string]float64{},
				keys:   map[string]map[string]bool{},
			}
			profiles[entityID] = profile
		}
		block := strings.TrimPrefix(family, "profile:")
		values := profile.blocks[block]
		if values == nil {
			values = map[string]profileValue{}
			profile.blocks[block] = values
			profile.keys[block] = map[string]bool{}
		}
		values[name] = profileValue{value: value, confidence: confidence}
		profile.keys[block][name] = true
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, profile := range profiles {
		finalizeProfileNorms(profile)
	}
	return profiles, nil
}
