// Explanation planning and realization — a port of
// curator/explanations/planner.py (Microplanner) and
// curator/explanations/catalog.py + render.py's _render/_slots. The
// realization catalog is read from the installed plugin's
// curator/explanations/realizations.json (same file the Python backend
// reads), so variant text stays in lockstep with the shipped copy.
package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

// reasonPriority mirrors Microplanner._PRIORITY.
var reasonPriority = map[string]int64{
	"direct.positive":              7,
	"appeal.performer_identity":    6,
	"appeal.content_neighbor":      5,
	"appeal.tag_declared_positive": 5,
	"appeal.tag_positive":          4,
	"appeal.studio":                3,
	"appeal.performer_similar":     2,
}

// evidenceUnit mirrors planner.EvidenceUnit.
type evidenceUnit struct {
	reason   *explanationReason
	family   string
	strength float64
}

// discoursePlan mirrors planner.DiscoursePlan.
type discoursePlan struct {
	lane     string
	subtype  string
	primary  evidenceUnit
	support  *evidenceUnit
	boundary *evidenceUnit
}

func (p *discoursePlan) shape() string {
	suffix := ""
	if p.support != nil {
		suffix += "_support"
	}
	if p.boundary != nil {
		suffix += "_boundary"
	}
	return "primary" + suffix
}

func (p *discoursePlan) selectedReasons() []*explanationReason {
	var reasons []*explanationReason
	reasons = append(reasons, p.primary.reason)
	if p.support != nil {
		reasons = append(reasons, p.support.reason)
	}
	if p.boundary != nil {
		reasons = append(reasons, p.boundary.reason)
	}
	return reasons
}

// plan mirrors Microplanner.plan.
func plan(reasons []*explanationReason) discoursePlan {
	var laneReason *explanationReason
	for _, r := range reasons {
		if r.code == "eligibility.lane" {
			laneReason = r
			break
		}
	}
	lane := "generic"
	subtype := ""
	if laneReason != nil {
		if v := laneReason.detail.get("lane"); v.kind != jNull && v.s != "" {
			lane = v.s
		}
		if v := laneReason.detail.get("subtype"); v.kind != jNull && v.s != "" {
			subtype = v.s
		}
	}
	positives := positiveUnits(reasons)
	primary := primaryUnit(positives, lane)
	var support *evidenceUnit
	for _, candidate := range positives {
		if candidate.reason != primary.reason && distinct(primary, candidate) {
			s := candidate
			support = &s
			break
		}
	}
	boundary := boundaryUnit(reasons, lane)
	return discoursePlan{lane: lane, subtype: subtype, primary: primary, support: support, boundary: boundary}
}

// positiveUnits mirrors Microplanner._positive_units.
func positiveUnits(reasons []*explanationReason) []evidenceUnit {
	units := make([]evidenceUnit, 0)
	for _, r := range reasons {
		if r.direction != "positive" {
			continue
		}
		if _, ok := reasonPriority[r.code]; !ok {
			continue
		}
		if !narratable(r) {
			continue
		}
		units = append(units, evidenceUnit{reason: r, family: familyOf(r.code), strength: r.magnitude * r.confidence})
	}
	sortUnits(units)
	return units
}

// sortUnits mirrors the _positive_units sort: (-strength, -priority, code,
// subject_id or "").
func sortUnits(units []evidenceUnit) {
	// insertion sort for stability parity with Python's sorted (stable)
	for i := 1; i < len(units); i++ {
		for j := i; j > 0 && lessUnit(units[j], units[j-1]); j-- {
			units[j], units[j-1] = units[j-1], units[j]
		}
	}
}

func lessUnit(a, b evidenceUnit) bool {
	if a.strength != b.strength {
		return a.strength > b.strength
	}
	pa, pb := reasonPriority[a.reason.code], reasonPriority[b.reason.code]
	if pa != pb {
		return pa > pb
	}
	if a.reason.code != b.reason.code {
		return a.reason.code < b.reason.code
	}
	return a.reason.subjectID.asString() < b.reason.subjectID.asString()
}

// primaryUnit mirrors Microplanner._primary.
func primaryUnit(positives []evidenceUnit, lane string) evidenceUnit {
	if lane == "revisit" {
		for _, unit := range positives {
			if unit.reason.code == "direct.positive" {
				return unit
			}
		}
	}
	if len(positives) > 0 {
		return positives[0]
	}
	return fallbackUnit(lane)
}

// boundaryUnit mirrors Microplanner._boundary.
func boundaryUnit(reasons []*explanationReason, lane string) *evidenceUnit {
	var exploration []evidenceUnit
	for _, r := range reasons {
		if strings.HasPrefix(r.code, "explore.") {
			exploration = append(exploration, evidenceUnit{reason: r, family: familyOf(r.code), strength: r.magnitude * r.confidence})
		}
	}
	sortUnits(exploration)
	if (lane == "discover" || lane == "adventure") && len(exploration) > 0 {
		unit := exploration[0]
		return &unit
	}
	var reservations []evidenceUnit
	for _, r := range reasons {
		if r.direction != "negative" {
			continue
		}
		switch r.code {
		case "appeal.tag_declared_negative", "appeal.tag_negative", "fit.cooldown", "fit.not_now":
			reservations = append(reservations, evidenceUnit{reason: r, family: familyOf(r.code), strength: r.magnitude * r.confidence})
		}
	}
	sortUnits(reservations)
	if len(reservations) > 0 {
		unit := reservations[0]
		return &unit
	}
	return nil
}

// distinct mirrors Microplanner._distinct.
func distinct(primary evidenceUnit, candidate evidenceUnit) bool {
	if primary.family == candidate.family {
		return false
	}
	primaryCode := primary.reason.code
	candidateCode := candidate.reason.code
	hasNeighbor := primaryCode == "appeal.content_neighbor" || candidateCode == "appeal.content_neighbor"
	hasTag := primaryCode == "appeal.tag_positive" || candidateCode == "appeal.tag_positive" ||
		primaryCode == "appeal.tag_declared_positive" || candidateCode == "appeal.tag_declared_positive"
	return !(hasNeighbor && hasTag)
}

// narratable mirrors Microplanner._narratable.
func narratable(r *explanationReason) bool {
	if r.code != "appeal.performer_similar" {
		return true
	}
	return number(r.detail.get("novelty_weight")) >= 0.5
}

// familyOf mirrors planner._family.
func familyOf(code string) string {
	if strings.HasPrefix(code, "appeal.performer_") {
		return "performer"
	}
	if strings.HasPrefix(code, "appeal.tag_") || code == "appeal.content_neighbor" {
		return "content"
	}
	if idx := strings.LastIndex(code, "."); idx >= 0 {
		return code[:idx]
	}
	return code
}

// fallbackUnit mirrors Microplanner._fallback_unit.
func fallbackUnit(lane string) evidenceUnit {
	r := &explanationReason{
		code: "fallback", direction: "unknown", magnitude: 0.0, confidence: 0.0,
		subjectType: jvNull(), subjectID: jvNull(), visibility: "standard",
		provenance: "microplanner_fallback", detail: jvObj(jvKey("lane", jvStr(lane))),
	}
	return evidenceUnit{reason: r, family: "fallback", strength: 0.0}
}

// realizationCatalog mirrors catalog.RealizationCatalog: evidence groups keyed
// by code, positions with variant strings.
type realizationCatalog struct {
	evidence map[string]map[string][]string
}

var catalogCache *realizationCatalog

// loadCatalog mirrors RealizationCatalog.load reading realizations.json from
// the curator package the way backend.py resolves it: the plugin directory
// first, then the parent package root (backend.py inserts both into sys.path).
func loadCatalog(pluginDir string) (*realizationCatalog, error) {
	if catalogCache != nil {
		return catalogCache, nil
	}
	var data []byte
	var err error
	for _, root := range []string{pluginDir, filepath.Dir(pluginDir)} {
		path := filepath.Join(root, "curator", "explanations", "realizations.json")
		data, err = os.ReadFile(path)
		if err == nil {
			break
		}
	}
	if err != nil {
		return nil, err
	}
	var payload struct {
		Version  int                            `json:"version"`
		Evidence map[string]map[string][]string `json:"evidence"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	if payload.Version != 1 {
		return nil, err
	}
	catalogCache = &realizationCatalog{evidence: payload.Evidence}
	return catalogCache, nil
}

// evidenceVariant mirrors RealizationCatalog.evidence_variant.
func (c *realizationCatalog) evidenceVariant(code, position string, slots map[string]string, seed string) (string, error) {
	group, ok := c.evidence[code]
	if !ok {
		group = c.evidence["fallback"]
	}
	variants, ok := group[position]
	if !ok {
		variants = group["lead"]
	}
	if len(variants) == 0 {
		return "", errMissingVariant
	}
	return chooseVariant(variants, seed+"\x00evidence\x00"+code+"\x00"+position, slots), nil
}

var errMissingVariant = &missingVariantError{}

type missingVariantError struct{}

func (e *missingVariantError) Error() string { return "missing evidence position" }

// planVariant mirrors RealizationCatalog.plan_variant (lane and seed are
// ignored by the Python implementation).
func planVariant(shape string, slots map[string]string) (string, error) {
	var parts []string
	switch shape {
	case "primary":
		parts = []string{"primary_cap"}
	case "primary_support":
		parts = []string{"primary_cap", "support_cap"}
	case "primary_boundary":
		parts = []string{"primary_cap", "boundary_cap"}
	case "primary_support_boundary":
		parts = []string{"primary_cap", "support_cap", "boundary_cap"}
	default:
		return "", errMissingVariant
	}
	joined := make([]string, 0, len(parts))
	for _, part := range parts {
		joined = append(joined, slots[part])
	}
	return strings.Join(joined, ". ") + ".", nil
}

// chooseVariant mirrors RealizationCatalog._choose: sha256(seed) first 4
// bytes big-endian mod len(variants), then format the slots.
func chooseVariant(variants []string, seed string, slots map[string]string) string {
	sum := sha256.Sum256([]byte(seed))
	index := int(sum[0])<<24 | int(sum[1])<<16 | int(sum[2])<<8 | int(sum[3])
	index %= len(variants)
	return formatSlots(variants[index], slots)
}

// formatSlots replaces {field} placeholders from the slot map.
func formatSlots(template string, slots map[string]string) string {
	var b strings.Builder
	for {
		start := strings.IndexByte(template, '{')
		if start < 0 {
			b.WriteString(template)
			break
		}
		b.WriteString(template[:start])
		end := strings.IndexByte(template[start:], '}')
		if end < 0 {
			b.WriteString(template[start:])
			break
		}
		field := template[start+1 : start+end]
		b.WriteString(slots[field])
		template = template[start+end+1:]
	}
	return b.String()
}

// baseSlots mirrors render._slots' base dict.
var baseSlots = map[string]string{
	"challenge":         "one less-certain part of your taste",
	"known":             "a familiar performer",
	"performer":         "a familiar performer",
	"precedent":         "a scene that worked for you",
	"precedent_outcome": "which worked for you",
	"precedents":        "nearby scenes you enjoyed",
	"profile":           "their overall profiles",
	"studio":            "a familiar studio",
	"tags":              "familiar elements",
	"target":            "a new performer",
}

// renderExplanation mirrors ExplanationService._render: plan the reasons,
// realize the primary/support/boundary evidence, and assemble the summary.
func renderExplanation(pluginDir string, db dbx, reasons []*explanationReason, seed string) (string, []*explanationReason, error) {
	catalog, err := loadCatalog(pluginDir)
	if err != nil {
		return "", nil, err
	}
	plan := plan(reasons)
	slots := make(map[string]string, 8)
	primary, err := realize(catalog, db, plan.primary, "lead", seed)
	if err != nil {
		return "", nil, err
	}
	slots["primary"] = primary
	slots["primary_cap"] = capitalize(primary)
	if plan.support != nil {
		support, err := realize(catalog, db, *plan.support, "support", seed)
		if err != nil {
			return "", nil, err
		}
		slots["support"] = support
		slots["support_cap"] = capitalize(support)
	}
	if plan.boundary != nil {
		boundary, err := realize(catalog, db, *plan.boundary, "boundary", seed)
		if err != nil {
			return "", nil, err
		}
		slots["boundary"] = boundary
		slots["boundary_cap"] = capitalize(boundary)
	}
	summary, err := planVariant(plan.shape(), slots)
	if err != nil {
		return "", nil, err
	}
	return summary, plan.selectedReasons(), nil
}

// realize mirrors render._realize.
func realize(catalog *realizationCatalog, db dbx, unit evidenceUnit, position, seed string) (string, error) {
	return catalog.evidenceVariant(unit.reason.code, position, slotsFor(db, unit.reason), seed)
}

// slotsFor mirrors render._slots.
func slotsFor(db dbx, r *explanationReason) map[string]string {
	slots := make(map[string]string, len(baseSlots))
	for key, value := range baseSlots {
		slots[key] = value
	}
	for key, value := range specificSlots(db, r) {
		slots[key] = value
	}
	return slots
}

// specificSlots mirrors render._specific_slots.
func specificSlots(db dbx, r *explanationReason) map[string]string {
	switch r.code {
	case "appeal.content_neighbor":
		return neighborSlots(r)
	case "appeal.performer_similar":
		return similaritySlots(db, r)
	case "appeal.performer_identity":
		return map[string]string{"performer": entityName(db, r.subjectID, "performer")}
	case "appeal.studio":
		return map[string]string{"studio": entityName(db, r.subjectID, "studio")}
	case "explore.challenge":
		return map[string]string{"challenge": challengePhrase(r.detail.get("challenged_assumption").asString())}
	}
	if strings.HasPrefix(r.code, "appeal.tag_") {
		return map[string]string{"tags": tagNames(r)}
	}
	return map[string]string{}
}

// neighborSlots mirrors render._neighbor_slots.
func neighborSlots(r *explanationReason) map[string]string {
	raw := r.detail.get("neighbors")
	var useful []jVal
	if raw.kind == jArr {
		for _, item := range raw.arr {
			if item.kind == jObj && number(item.get("outcome")) > 0 {
				useful = append(useful, item)
			}
		}
	}
	if len(useful) > 2 {
		useful = useful[:2]
	}
	titles := make([]string, 0, len(useful))
	for range useful {
		titles = append(titles, "an earlier scene")
	}
	var tags []string
	for _, item := range useful {
		for _, tag := range detailList(item.get("shared_tags")) {
			tags = append(tags, tag)
		}
	}
	tags = dedupe(tags)
	if len(tags) > 3 {
		tags = tags[:3]
	}
	precedent := "an earlier scene"
	if len(titles) > 0 {
		precedent = titles[0]
	}
	precedentOutcome := "from your history"
	if len(useful) > 0 {
		precedentOutcome = outcomePhrase(useful[0])
	}
	precedents := naturalList(titles)
	if len(precedents) == 0 {
		precedents = "nearby scenes you enjoyed"
	}
	tagText := naturalList(tags)
	if tagText == "" {
		tagText = "their content profile"
	}
	return map[string]string{
		"precedent":         precedent,
		"precedent_outcome": precedentOutcome,
		"precedents":        precedents,
		"tags":              tagText,
	}
}

// outcomePhrase mirrors render._outcome_phrase.
func outcomePhrase(neighbor jVal) string {
	outcome := number(neighbor.get("outcome"))
	if outcome >= 0.75 {
		return "which you enjoyed"
	}
	if outcome >= 0.45 {
		return "which you liked"
	}
	return "which you watched before"
}

// challengePhrase mirrors render._challenge_phrase.
func challengePhrase(value string) string {
	switch value {
	case "studio":
		return "a less familiar studio"
	case "performer":
		return "a less familiar performer"
	case "content":
		return "a less familiar content pattern"
	case "history":
		return "something outside your usual rotation"
	}
	return "one less-certain part of your taste"
}

// similaritySlots mirrors render._similarity_slots.
func similaritySlots(db dbx, r *explanationReason) map[string]string {
	matches := r.detail.get("matches")
	var knownID jVal = jvNull()
	if matches.kind == jArr && len(matches.arr) > 0 && matches.arr[0].kind == jObj {
		if id := matches.arr[0].get("performer_id"); id.kind == jStr && id.s != "" {
			knownID = jvStr(id.s)
		}
	}
	aspects := detailList(r.detail.get("shared_aspects"))
	description := strings.TrimSpace(r.detail.get("profile_description").asString())
	profile := naturalList(aspects)
	if profile == "" {
		profile = "their overall performer profiles"
	}
	if description != "" && description != "a similar overall performer profile" {
		profile = profile + ", reflected in " + description
	}
	return map[string]string{
		"known":   entityName(db, knownID, "performer"),
		"profile": profile,
		"target":  entityName(db, r.subjectID, "performer"),
	}
}

// tagNames mirrors render._tag_names.
func tagNames(r *explanationReason) string {
	names := detailList(r.detail.get("related_names"))
	if len(names) == 0 {
		name := strings.TrimSpace(r.detail.get("name").asString())
		if name == "" {
			name = "a relevant content pattern"
		}
		names = []string{name}
	}
	if len(names) > 3 {
		names = names[:3]
	}
	return naturalList(names)
}

// detailList mirrors render._detail_list.
func detailList(v jVal) []string {
	if v.kind != jArr {
		return nil
	}
	var result []string
	for _, item := range v.arr {
		text := strings.TrimSpace(item.asString())
		if text != "" {
			result = append(result, text)
		}
	}
	return result
}

// naturalList mirrors render._natural_list.
func naturalList(values []string) string {
	unique := dedupe(values)
	switch len(unique) {
	case 0:
		return ""
	case 1:
		return unique[0]
	case 2:
		return unique[0] + " and " + unique[1]
	}
	return strings.Join(unique[:len(unique)-1], ", ") + ", and " + unique[len(unique)-1]
}

func dedupe(values []string) []string {
	seen := make(map[string]bool, len(values))
	var result []string
	for _, value := range values {
		if !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

// entityName mirrors render._name.
func entityName(db dbx, id jVal, entityType string) string {
	if id.kind == jNull || id.s == "" {
		if entityType == "performer" {
			return "this performer"
		}
		return "this studio"
	}
	table := "source_performer"
	idColumn := "performer_id"
	if entityType != "performer" {
		table = "source_studio"
		idColumn = "studio_id"
	}
	var name sql.NullString
	err := db.QueryRow(`SELECT name FROM `+table+` WHERE `+idColumn+`=?`, id.s).Scan(&name)
	if err == nil && name.Valid && name.String != "" {
		return name.String
	}
	return id.s
}

// capitalize mirrors render._capitalize.
func capitalize(value string) string {
	if value == "" {
		return value
	}
	return strings.ToUpper(value[:1]) + value[1:]
}
