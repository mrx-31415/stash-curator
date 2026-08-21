// Versioned explanation payload builder (apiSchemaVersion 2) — the Go mirror
// of curator/explanations/breakdown.py. The backend owns the score semantics,
// fact ranking, materiality, units, and deterministic summary. Materiality
// thresholds are mirrored module constants (plain package vars), not frontend
// rules or config-backed model inputs.
package main

import (
	"math"
	"sort"
)

// Materiality thresholds — mirrored from curator/explanations/breakdown.py.
const (
	explanationMaterialContent  = 0.05
	explanationMaterialPerformer = 0.05
	explanationMaterialStudio   = 0.05
	explanationMaterialSimilar  = 0.05
	explanationMaterialDirect   = 0.05
	explanationMaterialResidual = 0.10
	explanationMaterialFit      = 0.01
	explanationMaterialCaution  = 0.05
)

// fingerprintAxis mirrors breakdown.FINGERPRINT_AXES.
type fingerprintAxis struct {
	key   string
	label string
}

var explanationFingerprintAxes = []fingerprintAxis{
	{"content", "Content"},
	{"performers", "Performers"},
	{"studios", "Studios"},
	{"similar_scenes", "Similar scenes"},
	{"direct_history", "Direct history"},
	{"metadata_coverage", "Metadata coverage"},
}

// fingerprintTones mirrors breakdown.FINGERPRINT_TONES.
var explanationFingerprintTones = map[string]string{
	"content":          "support",
	"performers":       "support",
	"studios":          "support",
	"similar_scenes":   "support",
	"direct_history":   "support",
	"metadata_coverage": "neutral",
}

func clampFloat(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// explanationComponentValue mirrors breakdown._component_value.
func explanationsComponentValue(score *fullSceneScore, name string, def float64) float64 {
	component := score.components.get(name)
	if component.kind != jObj {
		return def
	}
	return number(component.get("value"))
}

// componentHasEvidence mirrors breakdown._component_has_evidence.
func componentHasEvidence(score *fullSceneScore, name string) bool {
	component := score.components.get(name)
	if component.kind != jObj {
		return false
	}
	return component.has("value")
}

// percentileRank mirrors breakdown._percentile_rank.
func percentileRank(sceneID, lane string, orderedValues []pair) float64 {
	_ = lane
	if len(orderedValues) == 0 {
		return 0.0
	}
	// Copy and sort by (value, id) ascending to match Python's sort.
	type kv struct {
		id    string
		value float64
	}
	ordered := make([]kv, 0, len(orderedValues))
	for _, p := range orderedValues {
		ordered = append(ordered, kv{id: p.id, value: p.value})
	}
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].value != ordered[j].value {
			return ordered[i].value < ordered[j].value
		}
		return ordered[i].id < ordered[j].id
	})
	denominator := maxInt(1, len(ordered)-1)
	start := 0
	for start < len(ordered) {
		end := start + 1
		for end < len(ordered) && ordered[end].value == ordered[start].value {
			end++
		}
		percentile := float64((start+end-1)/2) / float64(denominator)
		for _, item := range ordered[start:end] {
			if item.id == sceneID {
				return percentile
			}
		}
		start = end
	}
	return 0.0
}

type pair struct {
	id    string
	value float64
}

// evidenceFingerprint mirrors breakdown._evidence_fingerprint.
func evidenceFingerprint(score *fullSceneScore, components map[string]float64, directHistory, metadataCoverage float64) jVal {
	values := map[string]float64{
		"content":           components["content"],
		"performers":        components["performers"],
		"studios":           components["studios"],
		"similar_scenes":    components["similar_scenes"],
		"direct_history":    directHistory,
		"metadata_coverage": metadataCoverage,
	}
	evidenceKeys := map[string][]string{
		"content":           {"content"},
		"performers":        {"performer_identity", "performer_similarity"},
		"studios":           {"studio"},
		"similar_scenes":    {"content_neighbor"},
		"direct_history":    {"direct"},
		"metadata_coverage": {},
	}
	axes := jvObj()
	for _, axis := range explanationFingerprintAxes {
		raw := values[axis.key]
		present := axis.key == "metadata_coverage"
		if !present {
			for _, key := range evidenceKeys[axis.key] {
				if componentHasEvidence(score, key) {
					present = true
					break
				}
			}
		}
		axes.set(axis.key, jvObj(
			jvKey("label", jvStr(axis.label)),
			jvKey("strength", jvFloat(clampFloat(math.Abs(raw), 0.0, 1.0))),
			jvKey("tone", jvStr(explanationFingerprintTones[axis.key])),
			jvKey("present", jvBool(present)),
		))
	}
	return jvObj(jvKey("axes", axes))
}

// componentsRows mirrors breakdown._components_rows.
func componentsRows(score *fullSceneScore) jVal {
	content := clampFloat(math.Abs(explanationsComponentValue(score, "content", 0.0)), 0.0, 1.0)
	performers := clampFloat(math.Abs(explanationsComponentValue(score, "performer_identity", 0.0)+explanationsComponentValue(score, "performer_similarity", 0.0)), 0.0, 1.0)
	studio := clampFloat(math.Abs(explanationsComponentValue(score, "studio", 0.0)), 0.0, 1.0)
	direct := clampFloat(math.Abs(explanationsComponentValue(score, "direct", 0.0)), 0.0, 1.0)
	rightNow := clampFloat(score.currentFit, -1.0, 1.0)
	confidence := clampFloat(score.confidence, 0.0, 1.0)
	return jvArr(
		jvObj(jvKey("key", jvStr("content_similarity")), jvKey("label", jvStr("Content similarity")), jvKey("value", jvFloat(content)), jvKey("unit", jvStr("similarity"))),
		jvObj(jvKey("key", jvStr("performer_match")), jvKey("label", jvStr("Performer match")), jvKey("value", jvFloat(performers)), jvKey("unit", jvStr("similarity"))),
		jvObj(jvKey("key", jvStr("studio_appeal")), jvKey("label", jvStr("Studio appeal")), jvKey("value", jvFloat(studio)), jvKey("unit", jvStr("appeal"))),
		jvObj(jvKey("key", jvStr("direct_feedback")), jvKey("label", jvStr("Direct feedback")), jvKey("value", jvFloat(direct)), jvKey("unit", jvStr("appeal"))),
		jvObj(jvKey("key", jvStr("right_now_fit")), jvKey("label", jvStr("Right-now fit")), jvKey("value", jvFloat(rightNow)), jvKey("unit", jvStr("appeal"))),
		jvObj(jvKey("key", jvStr("confidence")), jvKey("label", jvStr("Confidence")), jvKey("value", jvFloat(confidence)), jvKey("unit", jvStr("percent"))),
	)
}

// rankedReasons mirrors breakdown._ranked_reasons.
func rankedReasons(reasons []*explanationReason) []*explanationReason {
	var support, caution, neutral []*explanationReason
	for _, r := range reasons {
		switch r.direction {
		case "positive":
			support = append(support, r)
		case "negative":
			caution = append(caution, r)
		default:
			neutral = append(neutral, r)
		}
	}
	key := func(r *explanationReason) (float64, string, string) {
		return -(r.magnitude * r.confidence), r.code, r.subjectID.asString()
	}
	less := func(i, j *explanationReason) bool {
		ai, aj, ak := key(i)
		bi, bj, bk := key(j)
		if ai != bi {
			return ai < bi
		}
		if aj != bj {
			return aj < bj
		}
		return ak < bk
	}
	sort.SliceStable(support, func(i, j int) bool { return less(support[i], support[j]) })
	sort.SliceStable(caution, func(i, j int) bool { return less(caution[i], caution[j]) })
	sort.SliceStable(neutral, func(i, j int) bool { return less(neutral[i], neutral[j]) })
	result := make([]*explanationReason, 0, len(reasons))
	result = append(result, support...)
	result = append(result, caution...)
	result = append(result, neutral...)
	return result
}

// explanations_laneContext mirrors breakdown._lane_context.
func explanations_laneContext(lane, subtype string, qualification jVal, laneRank float64) jVal {
	if lane == "" {
		return jvObj()
	}
	var subtypeVal jVal = jvNull()
	if subtype != "" {
		subtypeVal = jvStr(subtype)
	}
	context := jvObj(
		jvKey("lane", jvStr(lane)),
		jvKey("subtype", subtypeVal),
		jvKey("rank", jvFloat(laneRank)),
	)
	qual := qualification
	if qual.kind != jObj {
		qual = jvObj()
	}
	switch lane {
	case "revisit":
		context.set("facets", jvObj(
			jvKey("direct_appeal", jvFloat(clampFloat(math.Abs(number(qual.get("direct_appeal"))), 0.0, 1.0))),
			jvKey("direct_confidence", jvFloat(clampFloat(number(qual.get("direct_confidence")), 0.0, 1.0))),
			jvKey("recovery", jvFloat(clampFloat(number(qual.get("recovery")), 0.0, 1.0))),
			jvKey("durable_signals", qual.get("durable_signals")),
		))
		context.set("intent", jvStr("revisit"))
	case "best_bets":
		context.set("facets", jvObj(
			jvKey("current_fit", jvFloat(clampFloat(number(qual.get("current_fit")), -1.0, 1.0))),
			jvKey("confidence", jvFloat(clampFloat(number(qual.get("confidence")), 0.0, 1.0))),
			jvKey("metadata_confidence", jvFloat(clampFloat(number(qual.get("metadata_confidence")), 0.0, 1.0))),
			jvKey("relevance", jvFloat(clampFloat(number(qual.get("relevance")), 0.0, 1.0))),
			jvKey("corroborated", jvBool(qual.get("corroborated").truthy())),
			jvKey("direct_reliable", jvBool(qual.get("direct_reliable").truthy())),
		))
		context.set("intent", jvStr("best_bet"))
	case "stretch":
		context.set("facets", jvObj(
			jvKey("anchor_features", qual.get("anchor_features")),
			jvKey("challenged_feature", qual.get("challenged_feature")),
			jvKey("challenge_kind", qual.get("challenge_kind")),
			jvKey("anchor_strength", jvFloat(clampFloat(math.Abs(number(qual.get("anchor_strength"))), 0.0, 1.0))),
			jvKey("challenge_distance", jvFloat(clampFloat(number(qual.get("challenge_distance")), 0.0, 1.0))),
		))
		context.set("intent", jvStr("challenge"))
	case "blind_spots":
		context.set("facets", jvObj(
			jvKey("dark_facets", qual.get("dark_facets")),
			jvKey("corroborating_types", qual.get("corroborating_types")),
		))
		context.set("intent", jvStr("coverage"))
	case "dormant":
		context.set("facets", jvObj(
			jvKey("dormant_entity", qual.get("dormant_entity")),
			jvKey("days_since_played", qual.get("days_since_played")),
		))
		context.set("intent", jvStr("dormancy"))
	}
	return context
}

// buildExplanationV2 assembles the exact apiSchemaVersion 2 payload.
func buildExplanationV2(score *fullSceneScore, summary string, reasons []*explanationReason, lane, subtype string, qualification jVal, laneRank float64) jVal {
	components := map[string]float64{
		"content":        clampFloat(math.Abs(explanationsComponentValue(score, "content", 0.0)), 0.0, 1.0),
		"performers":     clampFloat(math.Abs(explanationsComponentValue(score, "performer_identity", 0.0)+explanationsComponentValue(score, "performer_similarity", 0.0)), 0.0, 1.0),
		"studios":        clampFloat(math.Abs(explanationsComponentValue(score, "studio", 0.0)), 0.0, 1.0),
		"similar_scenes": clampFloat(math.Abs(explanationsComponentValue(score, "content_neighbor", 0.0)), 0.0, 1.0),
	}
	directHistory := clampFloat(math.Abs(explanationsComponentValue(score, "direct", 0.0)), 0.0, 1.0)
	metadataCoverage := clampFloat(score.metadataConfidence, 0.0, 1.0)
	rank := clampFloat(laneRank, 0.0, 1.0)

	scores := jvObj(
		jvKey("appeal", jvObj(jvKey("value", jvFloat(score.appeal)), jvKey("unit", jvStr("signed")))),
		jvKey("current_fit", jvObj(jvKey("value", jvFloat(score.currentFit)), jvKey("unit", jvStr("signed")))),
		jvKey("confidence", jvObj(jvKey("value", jvFloat(score.confidence)), jvKey("unit", jvStr("percent")))),
		jvKey("rank", jvObj(jvKey("value", jvFloat(rank)), jvKey("unit", jvStr("percent")))),
	)
	evidence := evidenceFingerprint(score, components, directHistory, metadataCoverage)

	reasonArr := jvArr()
	for _, r := range rankedReasons(reasons) {
		reasonArr.arr = append(reasonArr.arr, reasonJSON(r))
	}
	return jvObj(
		jvKey("apiSchemaVersion", jvInt(2)),
		jvKey("summary", jvStr(summary)),
		jvKey("components", componentsRows(score)),
		jvKey("reasons", reasonArr),
		jvKey("lane_context", explanations_laneContext(lane, subtype, qualification, rank)),
		jvKey("scores", scores),
		jvKey("evidence_fingerprint", evidence),
	)
}
