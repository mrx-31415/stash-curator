// get_explanation — a port of backend.py's get_explanation dispatch,
// ExplanationService.explain_scene (curator/explanations/render.py), the
// ReasonGraphStore runtime derivation (curator/explanations/reasons.py), the
// microplanner (curator/explanations/planner.py), and the realization catalog
// (curator/explanations/catalog.py + realizations.json). Published artifacts
// leave model_scene_reason empty, so the requested reasons are derived from
// the score row and rendered deterministically.
package main

import (
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
)

// explanationReason mirrors reasons.Reason (asdict order: code, direction,
// magnitude, confidence, subject_type, subject_id, visibility, provenance,
// detail, model_id, feature_version).
type explanationReason struct {
	code           string
	direction      string
	magnitude      float64
	confidence     float64
	subjectType    jVal
	subjectID      jVal
	visibility     string
	provenance     string
	detail         jVal
	modelID        string
	featureVersion string
}

func reasonJSON(r *explanationReason) jVal {
	return jvObj(
		jvKey("code", jvStr(r.code)),
		jvKey("direction", jvStr(r.direction)),
		jvKey("magnitude", jvFloat(r.magnitude)),
		jvKey("confidence", jvFloat(r.confidence)),
		jvKey("subject_type", r.subjectType),
		jvKey("subject_id", r.subjectID),
		jvKey("visibility", jvStr(r.visibility)),
		jvKey("provenance", jvStr(r.provenance)),
		jvKey("detail", r.detail),
		jvKey("model_id", jvStr(r.modelID)),
		jvKey("feature_version", jvStr(r.featureVersion)),
	)
}

func optStr(v jVal) jVal {
	if v.kind == jNull {
		return jvNull()
	}
	return jvStr(v.asString())
}

// number mirrors reasons._number: float for numeric values, else 0.0.
func number(v jVal) float64 {
	if v.kind == jNum {
		f, err := pythonFloat(v)
		if err != nil {
			return 0
		}
		return f
	}
	return 0.0
}

// direction mirrors reasons._direction.
func direction(value float64) string {
	if value > 1e-9 {
		return "positive"
	}
	if value < -1e-9 {
		return "negative"
	}
	return "neutral"
}

// visibility mirrors ReasonGraphStore._visibility.
func reasonVisibility(code string) string {
	if code == "appeal.performer_similar" {
		return "sensitive"
	}
	if strings.HasPrefix(code, "direct.") || strings.HasPrefix(code, "fit.") {
		return "private"
	}
	return "standard"
}

// reason builds a Reason via ReasonGraphStore._reason.
func reason(score *fullSceneScore, featureVersion, code string, value, conf float64, subjectType string, subjectID jVal, provenance string, detail jVal) *explanationReason {
	return &explanationReason{
		code:           code,
		direction:      direction(value),
		magnitude:      math.Min(1.0, math.Abs(value)),
		confidence:     mathMax(0.0, math.Min(1.0, conf)),
		subjectType:    optStr(jvStr(subjectType)),
		subjectID:      subjectID,
		visibility:     reasonVisibility(code),
		provenance:     provenance,
		detail:         detail,
		modelID:        score.modelID,
		featureVersion: featureVersion,
	}
}

// fullSceneScore carries every ModelSceneScore field the reason derivation
// needs.
type fullSceneScore struct {
	modelID          string
	sceneID          string
	directAppeal     float64
	directConfidence float64
	appeal           float64
	currentFit       float64
	confidence       float64
	components       jVal
	neighbors        []jVal
}

// fullScores mirrors RecommendationModelStore.scores for the reason path.
func fullScores(db dbx, modelID string, sceneIDs map[string]bool) (map[string]*fullSceneScore, error) {
	result := make(map[string]*fullSceneScore)
	if len(sceneIDs) == 0 {
		return result, nil
	}
	ids := sortedKeys(sceneIDs)
	placeholders := inClause(len(ids))
	args := make([]any, 0, len(ids)+1)
	args = append(args, modelID)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := db.Query(`SELECT model_id, scene_id, general_appeal, direct_appeal, direct_confidence,
    appeal, current_fit, confidence, metadata_confidence, recovery,
    components_json
FROM model_scene_score WHERE model_id=? AND scene_id IN (`+placeholders+`) ORDER BY scene_id`, args...)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var modelID2, sceneID, componentsJSON string
		var generalAppeal, directAppeal, directConfidence, appeal, currentFit, confidence, metadataConfidence, recovery float64
		if err := rows.Scan(&modelID2, &sceneID, &generalAppeal, &directAppeal, &directConfidence,
			&appeal, &currentFit, &confidence, &metadataConfidence, &recovery, &componentsJSON); err != nil {
			rows.Close()
			return nil, err
		}
		components, err := parseJSON([]byte(componentsJSON))
		if err != nil {
			components = jvNull()
		}
		result[sceneID] = &fullSceneScore{
			modelID:          modelID2,
			sceneID:          sceneID,
			directAppeal:     directAppeal,
			directConfidence: directConfidence,
			appeal:           appeal,
			currentFit:       currentFit,
			confidence:       confidence,
			components:       components,
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	neighborRows, err := db.Query(`SELECT scene_id, neighbor_scene_id, similarity, weight, outcome
FROM model_scene_neighbor WHERE model_id=? AND scene_id IN (`+placeholders+`) ORDER BY scene_id, rank`, args...)
	if err != nil {
		return nil, err
	}
	defer neighborRows.Close()
	for neighborRows.Next() {
		var sceneID, neighborID string
		var similarity, weight, outcome float64
		if err := neighborRows.Scan(&sceneID, &neighborID, &similarity, &weight, &outcome); err != nil {
			return nil, err
		}
		if score, ok := result[sceneID]; ok {
			score.neighbors = append(score.neighbors, jvObj(
				jvKey("scene_id", jvStr(neighborID)),
				jvKey("similarity", jvFloat(similarity)),
				jvKey("weight", jvFloat(weight)),
				jvKey("outcome", jvFloat(outcome)),
			))
		}
	}
	if err := neighborRows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

// neighborContext mirrors ReasonGraphStore._prepare_neighbor_context
// (targeted=True): per-scene content features with tag names, scene titles,
// and the content preference map.
type neighborContext struct {
	contentFeatures   map[string]map[string]featureValue // scene -> name -> (value, tagName)
	sceneTitles       map[string]string
	contentPreference map[string]float64
}

type featureValue struct {
	value   float64
	tagName string
}

func prepareNeighborContext(db dbx, modelID, featureVersion string, scores map[string]*fullSceneScore) (*neighborContext, error) {
	contextIDs := make(map[string]bool, len(scores))
	for sceneID := range scores {
		contextIDs[sceneID] = true
	}
	for _, score := range scores {
		for _, neighbor := range score.neighbors {
			if id := neighbor.get("scene_id"); id.kind == jStr && id.s != "" {
				contextIDs[id.s] = true
			}
		}
	}
	vectors, _, err := sceneContentVectors(db, featureVersion, contextIDs)
	if err != nil {
		return nil, err
	}
	names := make(map[string]bool)
	for _, vector := range vectors {
		for name := range vector {
			names[name] = true
		}
	}
	tagNames := make(map[string]string)
	if len(names) > 0 {
		sortedNames := make([]string, 0, len(names))
		for name := range names {
			sortedNames = append(sortedNames, name)
		}
		sort.Strings(sortedNames)
		placeholders := inClause(len(sortedNames))
		args := make([]any, 0, len(sortedNames)+1)
		args = append(args, featureVersion)
		for _, name := range sortedNames {
			args = append(args, name)
		}
		rows, err := db.Query(`SELECT name, metadata_json FROM feature_definition
WHERE feature_version=? AND family='content' AND name IN (`+placeholders+`)`, args...)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var name, metadataJSON string
			if err := rows.Scan(&name, &metadataJSON); err != nil {
				return nil, err
			}
			metadata, err := parseJSON([]byte(metadataJSON))
			if err != nil {
				metadata = jvNull()
			}
			tagNames[name] = metadata.get("tag_name").asString()
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	contentFeatures := make(map[string]map[string]featureValue, len(vectors))
	for sceneID, vector := range vectors {
		features := make(map[string]featureValue, len(vector))
		for name, value := range vector {
			features[name] = featureValue{value: value, tagName: tagNames[name]}
		}
		contentFeatures[sceneID] = features
	}
	sceneTitles := make(map[string]string)
	if len(contextIDs) > 0 {
		ids := sortedKeys(contextIDs)
		placeholders := inClause(len(ids))
		args := make([]any, len(ids))
		for i, id := range ids {
			args[i] = id
		}
		rows, err := db.Query(`SELECT scene_id, title FROM source_scene WHERE scene_id IN (`+placeholders+`)`, args...)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var sceneID string
			var title sql.NullString
			if err := rows.Scan(&sceneID, &title); err != nil {
				return nil, err
			}
			if title.Valid && title.String != "" {
				sceneTitles[sceneID] = title.String
			} else {
				sceneTitles[sceneID] = sceneID
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	contentPreference := make(map[string]float64)
	prefRows, err := db.Query(`SELECT fd.name, fa.affinity, fa.confidence FROM feature_affinity fa
JOIN feature_definition fd ON fd.feature_id=fa.feature_id
WHERE fa.model_id=? AND fd.family='content'`, modelID)
	if err != nil {
		return nil, err
	}
	for prefRows.Next() {
		var name string
		var affinity, confidence float64
		if err := prefRows.Scan(&name, &affinity, &confidence); err != nil {
			return nil, err
		}
		contentPreference[name] = mathMax(0.0, affinity*confidence)
	}
	prefRows.Close()
	if err := prefRows.Err(); err != nil {
		return nil, err
	}
	return &neighborContext{
		contentFeatures:   contentFeatures,
		sceneTitles:       sceneTitles,
		contentPreference: contentPreference,
	}, nil
}

// sceneReasons mirrors ReasonGraphStore._scene_reasons.
func sceneReasons(db dbx, score *fullSceneScore, featureVersion string, ctx *neighborContext) []*explanationReason {
	var reasons []*explanationReason
	contentReasons(score, featureVersion, ctx, &reasons)
	performerReasons(db, score, featureVersion, &reasons)
	studioReasons(score, featureVersion, &reasons)
	neighborReason(score, featureVersion, ctx, &reasons)
	directReasons(score, featureVersion, &reasons)
	fitReasons(score, featureVersion, &reasons)
	if len(reasons) == 0 {
		reasons = append(reasons, &explanationReason{
			code: "fallback", direction: "neutral", magnitude: 0.0, confidence: score.confidence,
			subjectType: jvNull(), subjectID: jvNull(), visibility: "standard",
			provenance: "model_baseline",
			detail: jvObj(
				jvKey("appeal", jvFloat(score.appeal)),
				jvKey("current_fit", jvFloat(score.currentFit)),
				jvKey("confidence", jvFloat(score.confidence)),
			),
			modelID: score.modelID, featureVersion: featureVersion,
		})
	}
	sort.SliceStable(reasons, func(i, j int) bool {
		li, lj := reasons[i], reasons[j]
		pi, pj := 1, 1
		if li.direction == "positive" {
			pi = 0
		}
		if lj.direction == "positive" {
			pj = 0
		}
		if pi != pj {
			return pi < pj
		}
		if li.magnitude != lj.magnitude {
			return li.magnitude > lj.magnitude
		}
		if li.code != lj.code {
			return li.code < lj.code
		}
		return li.subjectID.asString() < lj.subjectID.asString()
	})
	return reasons
}

// contentReasons mirrors ReasonGraphStore._content_reasons.
func contentReasons(score *fullSceneScore, featureVersion string, ctx *neighborContext, reasons *[]*explanationReason) {
	content := score.components.get("content")
	top := content.get("top")
	if content.kind != jObj || top.kind != jArr {
		return
	}
	relatedNames := map[string][]string{"positive": {}, "negative": {}}
	for _, raw := range top.arr {
		if raw.kind != jObj {
			continue
		}
		value := number(raw.get("value"))
		metadata := raw.get("metadata")
		if metadata.kind != jObj {
			metadata = jvObj()
		}
		name := strings.TrimSpace(metadata.get("tag_name").asString())
		direction := "negative"
		if value > 0 {
			direction = "positive"
		}
		if math.Abs(value) >= 1e-6 && name != "" && !containsString(relatedNames[direction], name) {
			relatedNames[direction] = append(relatedNames[direction], name)
		}
	}
	for _, raw := range top.arr {
		if raw.kind != jObj {
			continue
		}
		value := number(raw.get("value"))
		if math.Abs(value) < 1e-6 {
			continue
		}
		metadata := raw.get("metadata")
		if metadata.kind != jObj {
			metadata = jvObj()
		}
		affinityMetadata := raw.get("affinity_metadata")
		if affinityMetadata.kind != jObj {
			affinityMetadata = jvObj()
		}
		declared := affinityMetadata.get("declared_preference")
		var code string
		if declared.kind != jNull {
			if value > 0 {
				code = "appeal.tag_declared_positive"
			} else {
				code = "appeal.tag_declared_negative"
			}
		} else if value > 0 {
			code = "appeal.tag_positive"
		} else {
			code = "appeal.tag_negative"
		}
		var subjectID jVal = jvNull()
		if metadata.get("tag_id").truthy() {
			subjectID = jvStr(metadata.get("tag_id").asString())
		}
		provenance := "learned_feature_affinity"
		if declared.kind != jNull {
			provenance = "declared_tag_preference"
		}
		dir := direction(value)
		related := jvArr()
		for _, name := range relatedNames[dir][:minInt(3, len(relatedNames[dir]))] {
			related.arr = append(related.arr, jvStr(name))
		}
		*reasons = append(*reasons, reason(score, featureVersion, code, value, number(raw.get("confidence")),
			"tag", subjectID, provenance, jvObj(
				jvKey("name", jvStr(defaultString(metadata.get("tag_name").asString(), "this content pattern"))),
				jvKey("related_names", related),
				jvKey("contribution", jvFloat(value)),
				jvKey("support", metadata.get("document_frequency")),
				jvKey("declared_preference", declared),
			)))
	}
}

func defaultString(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

// performerReasons mirrors ReasonGraphStore._performer_reasons.
func performerReasons(db dbx, score *fullSceneScore, featureVersion string, reasons *[]*explanationReason) {
	identity := score.components.get("performer_identity")
	performers := identity.get("performers")
	if identity.kind == jObj && performers.kind == jArr {
		for _, raw := range performers.arr {
			if raw.kind != jObj {
				continue
			}
			value := number(raw.get("value"))
			if math.Abs(value) < 1e-6 {
				continue
			}
			var subjectID jVal = jvNull()
			if raw.get("performer_id").truthy() {
				subjectID = jvStr(raw.get("performer_id").asString())
			}
			*reasons = append(*reasons, reason(score, featureVersion, "appeal.performer_identity", value, score.confidence,
				"performer", subjectID, "performer_identity_model", raw))
		}
	}
	similar := score.components.get("performer_similarity")
	performers = similar.get("performers")
	if similar.kind != jObj || performers.kind != jArr {
		return
	}
	for _, raw := range performers.arr {
		if raw.kind != jObj {
			continue
		}
		value := number(raw.get("value"))
		matches := raw.get("matches")
		if math.Abs(value) < 1e-6 || matches.kind != jArr || len(matches.arr) == 0 {
			continue
		}
		var subjectID jVal = jvNull()
		if raw.get("performer_id").truthy() {
			subjectID = jvStr(raw.get("performer_id").asString())
		}
		orderedMatches := supportingMatches(matches, value)
		representative := orderedMatches.arr[0]
		detail := jvObj(
			jvKey("matches", orderedMatches),
			jvKey("value", jvFloat(value)),
			jvKey("similarity", representative.get("similarity")),
			jvKey("shared_aspects", sharedAspects(representative)),
			jvKey("block_similarities", representative.get("blocks")),
			jvKey("profile_description", jvStr(profileDescription(db, featureVersion, subjectID))),
			jvKey("raw_value", raw.get("raw_value")),
			jvKey("identity_confidence", raw.get("identity_confidence")),
			jvKey("novelty_weight", raw.get("novelty_weight")),
		)
		*reasons = append(*reasons, reason(score, featureVersion, "appeal.performer_similar", value, score.confidence,
			"performer", subjectID, "performer_profile_similarity", detail))
	}
}

// supportingMatches mirrors ReasonGraphStore._supporting_matches.
func supportingMatches(matches jVal, value float64) jVal {
	type rankedMatch struct {
		agrees bool
		impact float64
		id     string
		raw    jVal
	}
	valid := make([]rankedMatch, 0, len(matches.arr))
	for _, raw := range matches.arr {
		if raw.kind != jObj {
			continue
		}
		affinity := number(raw.get("affinity"))
		agrees := affinity*value > 0
		impact := math.Abs(affinity) * pyCube(number(raw.get("similarity")))
		valid = append(valid, rankedMatch{agrees: agrees, impact: impact, id: raw.get("performer_id").asString(), raw: raw})
	}
	sort.SliceStable(valid, func(i, j int) bool {
		if valid[i].agrees != valid[j].agrees {
			return !valid[i].agrees
		}
		if valid[i].impact != valid[j].impact {
			return valid[i].impact > valid[j].impact
		}
		return valid[i].id < valid[j].id
	})
	result := jvArr()
	for _, item := range valid {
		result.arr = append(result.arr, item.raw)
	}
	return result
}

// sharedAspects mirrors ReasonGraphStore._shared_aspects.
func sharedAspects(match jVal) jVal {
	blocks := match.get("blocks")
	result := jvArr()
	if blocks.kind != jObj {
		return result
	}
	labels := map[string]string{
		"content":      "the kinds of scenes they appear in",
		"measurements": "body measurements and proportions",
		"height":       "height",
		"age":          "age at recording",
		"augmentation": "augmentation profile",
		"ethnicity":    "ethnicity",
		"hair":         "hair color",
		"tattoos":      "tattoo profile",
		"piercings":    "piercing profile",
		"eyes":         "eye color",
	}
	type aspect struct {
		similarity float64
		label      string
	}
	ranked := make([]aspect, 0)
	for _, pair := range blocks.obj {
		block := pair.key
		sim := number(pair.val)
		if sim <= 0.05 {
			continue
		}
		label := labels[block]
		if label == "" {
			label = strings.ReplaceAll(block, "_", " ")
		}
		ranked = append(ranked, aspect{similarity: sim, label: label})
	}
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].similarity != ranked[j].similarity {
			return ranked[i].similarity > ranked[j].similarity
		}
		return ranked[i].label < ranked[j].label
	})
	for _, item := range ranked[:minInt(3, len(ranked))] {
		result.arr = append(result.arr, jvStr(item.label))
	}
	return result
}

// profileDescription mirrors ReasonGraphStore._profile_description.
func profileDescription(db dbx, featureVersion string, performerID jVal) string {
	if performerID.kind == jNull || performerID.s == "" {
		return "a similar overall performer profile"
	}
	rows, err := db.Query(`SELECT fd.family, fd.name, ef.value FROM entity_feature ef
JOIN feature_definition fd ON fd.feature_id=ef.feature_id
WHERE ef.feature_version=? AND ef.entity_type='performer'
  AND ef.entity_id=? AND fd.family LIKE 'profile:%'`, featureVersion, performerID.s)
	if err != nil {
		return "a similar overall performer profile"
	}
	defer rows.Close()
	values := make(map[string]float64)
	for rows.Next() {
		var family, name string
		var value float64
		if err := rows.Scan(&family, &name, &value); err != nil {
			return "a similar overall performer profile"
		}
		values[family+"\x00"+name] = value
	}
	var phrases []string
	height, ok := values["profile:height\x00height_cm"]
	if ok {
		switch {
		case height < 160:
			phrases = append(phrases, "shorter stature")
		case height > 175:
			phrases = append(phrases, "taller stature")
		default:
			phrases = append(phrases, "similar height")
		}
	}
	cup, ok := values["profile:measurements\x00cup_index"]
	if ok {
		switch {
		case cup >= 5:
			phrases = append(phrases, "fuller bust")
		case cup <= 2:
			phrases = append(phrases, "smaller bust")
		default:
			phrases = append(phrases, "mid-range bust")
		}
	}
	ratio, ok := values["profile:measurements\x00waist_to_hip"]
	if ok {
		switch {
		case ratio <= 0.72:
			phrases = append(phrases, "pronounced waist-to-hip proportions")
		case ratio >= 0.84:
			phrases = append(phrases, "straighter waist-to-hip proportions")
		default:
			phrases = append(phrases, "balanced waist-to-hip proportions")
		}
	}
	if _, ok := values["profile:tattoos\x00present"]; ok {
		phrases = append(phrases, "visible tattoos")
	}
	if len(phrases) == 0 {
		return "a similar overall performer profile"
	}
	return strings.Join(phrases[:minInt(3, len(phrases))], ", ")
}

// studioReasons mirrors ReasonGraphStore._studio_reasons.
func studioReasons(score *fullSceneScore, featureVersion string, reasons *[]*explanationReason) {
	studio := score.components.get("studio")
	studios := studio.get("studios")
	if studio.kind != jObj || studios.kind != jArr {
		return
	}
	for _, raw := range studios.arr {
		if raw.kind != jObj {
			continue
		}
		value := number(raw.get("value"))
		if math.Abs(value) < 1e-6 {
			continue
		}
		var subjectID jVal = jvNull()
		if raw.get("studio_id").truthy() {
			subjectID = jvStr(raw.get("studio_id").asString())
		}
		*reasons = append(*reasons, reason(score, featureVersion, "appeal.studio", value, score.confidence,
			"studio", subjectID, "studio_affinity", jvObj(jvKey("studio_id", subjectID))))
	}
}

// neighborReason mirrors ReasonGraphStore._neighbor_reason.
func neighborReason(score *fullSceneScore, featureVersion string, ctx *neighborContext, reasons *[]*explanationReason) {
	neighbor := score.components.get("content_neighbor")
	value := 0.0
	if neighbor.kind == jObj {
		value = number(neighbor.get("value"))
	}
	if math.Abs(value) < 1e-6 || len(score.neighbors) == 0 {
		return
	}
	target := ctx.contentFeatures[score.sceneID]
	enriched := jvArr()
	for _, rawNeighbor := range score.neighbors[:minInt(3, len(score.neighbors))] {
		neighbor := jVal{kind: jObj, obj: append([]jPair(nil), rawNeighbor.obj...)}
		neighborID := neighbor.get("scene_id").asString()
		other := ctx.contentFeatures[neighborID]
		maximumPreference := 0.0
		for _, pref := range ctx.contentPreference {
			if pref > maximumPreference {
				maximumPreference = pref
			}
		}
		type rankedShared struct {
			score    float64
			name     string
			strength float64
		}
		var ranked []rankedShared
		for name := range target {
			otherValue, ok := other[name]
			if !ok {
				continue
			}
			preference := ctx.contentPreference[name]
			if maximumPreference > 0 && preference <= 0 {
				continue
			}
			multiplier := 1.0
			if maximumPreference > 0 {
				multiplier = preference / maximumPreference
			}
			itemScore := math.Min(target[name].value, otherValue.value) * multiplier
			display := target[name].tagName
			if display == "" {
				display = strings.TrimPrefix(name, "tag:")
			}
			ranked = append(ranked, rankedShared{score: itemScore, name: display, strength: preference})
		}
		sort.Slice(ranked, func(i, j int) bool {
			if ranked[i].score != ranked[j].score {
				return ranked[i].score > ranked[j].score
			}
			return ranked[i].name < ranked[j].name
		})
		title := ctx.sceneTitles[neighborID]
		if title == "" {
			title = neighborID
		}
		neighbor.set("title", jvStr(title))
		sharedTags := jvArr()
		sharedEvidence := jvArr()
		for _, item := range ranked[:minInt(4, len(ranked))] {
			sharedTags.arr = append(sharedTags.arr, jvStr(item.name))
			sharedEvidence.arr = append(sharedEvidence.arr, jvObj(
				jvKey("name", jvStr(item.name)),
				jvKey("preference_strength", jvFloat(item.strength)),
			))
		}
		neighbor.set("shared_tags", sharedTags)
		neighbor.set("shared_tag_evidence", sharedEvidence)
		enriched.arr = append(enriched.arr, neighbor)
	}
	var subjectID jVal = jvNull()
	if len(score.neighbors) > 0 {
		if id := score.neighbors[0].get("scene_id"); id.kind == jStr && id.s != "" {
			subjectID = jvStr(id.s)
		}
	}
	*reasons = append(*reasons, reason(score, featureVersion, "appeal.content_neighbor", value, score.confidence,
		"scene", subjectID, "content_neighbor_model", jvObj(jvKey("neighbors", enriched))))
}

// directReasons mirrors ReasonGraphStore._direct_reasons.
func directReasons(score *fullSceneScore, featureVersion string, reasons *[]*explanationReason) {
	direct := score.components.get("direct")
	if direct.kind != jObj || score.directConfidence <= 0 {
		return
	}
	code := "direct.negative"
	if score.directAppeal > 0 {
		code = "direct.positive"
	}
	*reasons = append(*reasons, reason(score, featureVersion, code, score.directAppeal, score.directConfidence,
		"scene", jvStr(score.sceneID), "exact_scene_outcomes", jvObj(
			jvKey("signals", direct.get("signals")),
			jvKey("effective_evidence", direct.get("effective_evidence")),
		)))
	residual := number(direct.get("residual"))
	if math.Abs(residual) >= 0.10 {
		*reasons = append(*reasons, reason(score, featureVersion, "direct.residual", residual, score.directConfidence,
			"scene", jvStr(score.sceneID), "direct_model_residual", jvObj(jvKey("residual", jvFloat(residual)))))
	}
}

// fitReasons mirrors ReasonGraphStore._fit_reasons.
func fitReasons(score *fullSceneScore, featureVersion string, reasons *[]*explanationReason) {
	fit := score.components.get("fit")
	if fit.kind != jObj {
		return
	}
	for _, pair := range [][2]string{{"cooldown", "fit.cooldown"}, {"satiation", "fit.satiation"}, {"not_now", "fit.not_now"}} {
		value := number(fit.get(pair[0]))
		if math.Abs(value) <= 1e-6 {
			continue
		}
		*reasons = append(*reasons, reason(score, featureVersion, pair[1], value, 1.0,
			"scene", jvStr(score.sceneID), "current_fit_adjustment", jvObj(
				jvKey(pair[0], jvFloat(value)),
				jvKey("recovery", fit.get("recovery")),
			)))
	}
}

// deriveReasons mirrors ReasonGraphStore.derive for one scene set.
func deriveReasons(db dbx, modelID string, sceneIDs map[string]bool) (map[string][]*explanationReason, error) {
	scores, err := fullScores(db, modelID, sceneIDs)
	if err != nil {
		return nil, err
	}
	var featureVersion string
	err = db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion)
	if err != nil {
		return nil, err
	}
	ctx, err := prepareNeighborContext(db, modelID, featureVersion, scores)
	if err != nil {
		return nil, err
	}
	result := make(map[string][]*explanationReason, len(scores))
	for sceneID, score := range scores {
		result[sceneID] = sceneReasons(db, score, featureVersion, ctx)
	}
	return result, nil
}

// storedReasons mirrors ReasonGraphStore.reasons (the persisted path).
func storedReasons(db dbx, modelID, sceneID string) ([]*explanationReason, bool, error) {
	var featureVersion string
	err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, false, fmt.Errorf("unknown model: %s", modelID)
		}
		return nil, false, err
	}
	rows, err := db.Query(`SELECT reason_code, direction, magnitude, confidence,
    subject_type, subject_id, visibility, provenance, detail_json
FROM model_scene_reason
WHERE model_id=? AND scene_id=? ORDER BY reason_index`, modelID, sceneID)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	var reasons []*explanationReason
	for rows.Next() {
		var code, direction, visibility, provenance string
		var magnitude, confidence float64
		var subjectType, subjectID sql.NullString
		var detailJSON string
		if err := rows.Scan(&code, &direction, &magnitude, &confidence, &subjectType, &subjectID, &visibility, &provenance, &detailJSON); err != nil {
			return nil, false, err
		}
		detail, err := parseJSON([]byte(detailJSON))
		if err != nil {
			detail = jvNull()
		}
		var subjectTypeVal, subjectIDVal jVal = jvNull(), jvNull()
		if subjectType.Valid {
			subjectTypeVal = jvStr(subjectType.String)
		}
		if subjectID.Valid {
			subjectIDVal = jvStr(subjectID.String)
		}
		reasons = append(reasons, &explanationReason{
			code: code, direction: direction, magnitude: magnitude, confidence: confidence,
			subjectType:    subjectTypeVal,
			subjectID:      subjectIDVal,
			visibility:     visibility,
			provenance:     provenance,
			detail:         detail,
			modelID:        modelID,
			featureVersion: featureVersion,
		})
	}
	return reasons, len(reasons) > 0, rows.Err()
}

func opGetExplanation(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_explanation",
		func(settings jVal) (jVal, error) { return getExplanationBody(pluginDir, payload, settings) })
}

func getExplanationBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model")
	}
	sceneID := argsString(payload.get("args"), "scene_id", "")
	reasons, found, err := storedReasons(db, modelID, sceneID)
	if err != nil {
		return jvNull(), err
	}
	if !found {
		derived, err := deriveReasons(db, modelID, map[string]bool{sceneID: true})
		if err != nil {
			return jvNull(), err
		}
		reasons = derived[sceneID]
	}
	summary, selected, err := renderExplanation(pluginDir, db, reasons, modelID+"\x00"+sceneID)
	if err != nil {
		return jvNull(), err
	}
	all := jvArr()
	for _, r := range reasons {
		all.arr = append(all.arr, reasonJSON(r))
	}
	supporting := jvArr()
	for _, r := range selected {
		supporting.arr = append(supporting.arr, reasonJSON(r))
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("model_id", jvStr(modelID)),
		jvKey("scene_id", jvStr(sceneID)),
		jvKey("summary", jvStr(summary)),
		jvKey("reasons", all),
		jvKey("supporting_reasons", supporting),
	), nil
}
