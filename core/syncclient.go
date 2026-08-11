// Stash incremental sync client — a port of curator/sync/service.py's
// SyncService and curator/sync/repository.py's SyncRepository, driven by
// the paginated GraphQL operations in curator/graphql/operations.py. This
// is the second GraphQL client pattern: resumable initial/incremental/full
// reconciliation of tags, studios, performers, scenes, and plays. The task
// wiring that invokes it is Slice 3; this file only provides the surface.
// The source_hash column must match Python's sha256(asdict(sort_keys=True))
// byte-for-byte, so hashes serialize through the Python-compatible JSON
// writer (jsonv.go).
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ── GraphQL operations (byte-identical to curator/graphql/operations.py) ──

const syncCapabilitiesQuery = `
query CuratorCapabilities {
  version { version }
  queryType: __type(name: "Query") { fields { name } }
  sceneType: __type(name: "Scene") { fields { name } }
  performerType: __type(name: "Performer") { fields { name } }
  tagType: __type(name: "Tag") { fields { name } }
  sceneFilterType: __type(name: "SceneFilterType") { inputFields { name } }
}
`

const syncSceneFields = `
      id title details date rating100 updated_at play_count play_duration play_history o_history
      studio { id name favorite rating100 updated_at parent_studio { id name updated_at } }
      tags { id name updated_at }
      performers { id name updated_at }
      files { id duration }
      scene_markers {
        id seconds end_seconds
        primary_tag { id name updated_at }
        tags { id name updated_at }
      }
`

// syncOperation mirrors EntityOperation.
type syncOperation struct {
	entityType      string
	name            string
	document        string
	rootKey         string
	itemsKey        string
	sort            string
	incrementalOnly bool
	idsDocument     string
}

func syncUpdatedAt(entity syncSourceEntity) (string, bool) {
	value, ok := entity.entityUpdatedAt()
	return value, ok
}

func syncLastPlayedAt(entity syncSourceEntity) (string, bool) {
	scene, ok := entity.(*syncScene)
	if !ok || len(scene.playHistoryMs) == 0 {
		return "", false
	}
	max := scene.playHistoryMs[0]
	for _, value := range scene.playHistoryMs[1:] {
		if value > max {
			max = value
		}
	}
	return epochMsToISO(max), true
}

func epochMsToISO(ms int64) string {
	// Mirrors datetime.fromtimestamp(ms/1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ").
	seconds := ms / 1000
	remainder := ms % 1000
	if remainder < 0 {
		seconds--
		remainder += 1000
	}
	days := seconds / 86400
	secsOfDay := seconds % 86400
	if secsOfDay < 0 {
		days--
		secsOfDay += 86400
	}
	year, month, day := civilFromDays(days)
	hour := secsOfDay / 3600
	minute := (secsOfDay % 3600) / 60
	sec := secsOfDay % 60
	return fmt.Sprintf("%04d-%02d-%02dT%02d:%02d:%02dZ", year, month, day, hour, minute, sec)
}

// civilFromDays converts a day count since the Unix epoch to y/m/d
// (Howard Hinnant's civil calendar algorithm, matching Python's date).
func civilFromDays(z int64) (int, int, int) {
	z += 719468
	era := z / 146097
	if z < 0 {
		era = (z - 146096) / 146097
	}
	doe := z - era*146097
	yoe := (doe - doe/1460 + doe/36524 - doe/146096) / 365
	y := yoe + era*400
	doy := doe - (365*yoe + yoe/4 - yoe/100)
	mp := (5*doy + 2) / 153
	d := doy - (153*mp+2)/5 + 1
	m := mp
	if mp < 10 {
		m = mp + 3
	} else {
		m = mp - 9
	}
	if m <= 2 {
		y++
	}
	return int(y), int(m), int(d)
}

// syncScenePlaysFilter mirrors _played_since.
func syncPlayedSince(watermark string) jVal {
	criteria := jvObj(jvKey("play_count", jvObj(
		jvKey("value", jvInt(0)),
		jvKey("modifier", jvStr("GREATER_THAN")),
	)))
	if watermark != "" {
		criteria.set("last_played_at", jvObj(
			jvKey("value", jvStr(watermark)),
			jvKey("modifier", jvStr("GREATER_THAN")),
		))
	}
	return jvObj(jvKey("sceneFilter", criteria))
}

func syncIDsDocument(name, rootKey, itemsKey string) string {
	return fmt.Sprintf(`
query %s($page: Int!, $perPage: Int!) {
  %s(filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}) {
    count
    %s { id }
  }
}
`, name, rootKey, itemsKey)
}

var syncTagOperation = syncOperation{
	entityType: "tag",
	name:       "CuratorTags",
	document: `
query CuratorTags($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findTags(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    tags {
      id name updated_at stash_ids { endpoint stash_id }
      parents { id name updated_at }
    }
  }
}
`,
	rootKey:     "findTags",
	itemsKey:    "tags",
	sort:        "updated_at",
	idsDocument: syncIDsDocument("CuratorTagIds", "findTags", "tags"),
}

var syncStudioOperation = syncOperation{
	entityType: "studio",
	name:       "CuratorStudios",
	document: `
query CuratorStudios($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findStudios(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    studios {
      id name favorite rating100 updated_at
      parent_studio { id name updated_at }
    }
  }
}
`,
	rootKey:     "findStudios",
	itemsKey:    "studios",
	sort:        "updated_at",
	idsDocument: syncIDsDocument("CuratorStudioIds", "findStudios", "studios"),
}

var syncPerformerOperation = syncOperation{
	entityType: "performer",
	name:       "CuratorPerformers",
	document: `
query CuratorPerformers(
  $page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!
) {
  findPerformers(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    performers {
      id name gender favorite rating100 birthdate ethnicity country eye_color hair_color
      height_cm weight measurements fake_tits tattoos piercings updated_at
      tags { id name updated_at }
    }
  }
}
`,
	rootKey:     "findPerformers",
	itemsKey:    "performers",
	sort:        "updated_at",
	idsDocument: syncIDsDocument("CuratorPerformerIds", "findPerformers", "performers"),
}

var syncSceneOperation = syncOperation{
	entityType: "scene",
	name:       "CuratorScenes",
	document: `
query CuratorScenes($page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!) {
  findScenes(filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}) {
    count
    scenes {` + syncSceneFields + `
    }
  }
}
`,
	rootKey:     "findScenes",
	itemsKey:    "scenes",
	sort:        "updated_at",
	idsDocument: syncIDsDocument("CuratorSceneIds", "findScenes", "scenes"),
}

var syncScenePlaysOperation = syncOperation{
	entityType: "scene_play",
	name:       "CuratorScenePlays",
	document: `
query CuratorScenePlays(
  $page: Int!, $perPage: Int!, $sort: String!, $direction: SortDirectionEnum!,
  $sceneFilter: SceneFilterType
) {
  findScenes(
    filter: {page: $page, per_page: $perPage, sort: $sort, direction: $direction}
    scene_filter: $sceneFilter
  ) {
    count
    scenes {` + syncSceneFields + `
    }
  }
}
`,
	rootKey:         "findScenes",
	itemsKey:        "scenes",
	sort:            "last_played_at",
	incrementalOnly: true,
}

func syncOperations() []syncOperation {
	return []syncOperation{
		syncTagOperation,
		syncStudioOperation,
		syncPerformerOperation,
		syncSceneOperation,
		syncScenePlaysOperation,
	}
}

var syncFindDocuments = map[string]string{
	"tag": `
query CuratorFindTag($id: ID!) {
  findTag(id: $id) {
    id name updated_at stash_ids { endpoint stash_id }
    parents { id name updated_at }
  }
}
`,
	"studio": `
query CuratorFindStudio($id: ID!) {
  findStudio(id: $id) {
    id name favorite rating100 updated_at
    parent_studio { id name updated_at }
  }
}
`,
	"performer": `
query CuratorFindPerformer($id: ID!) {
  findPerformer(id: $id) {
    id name gender favorite rating100 birthdate ethnicity country eye_color hair_color
    height_cm weight measurements fake_tits tattoos piercings updated_at
    tags { id name updated_at }
  }
}
`,
	"scene": `
query CuratorFindScene($id: ID!) {
  findScene(id: $id) {` + syncSceneFields + `
  }
}
`,
}

var syncFindRoots = map[string]string{
	"tag": "findTag", "studio": "findStudio", "performer": "findPerformer", "scene": "findScene",
}

// ── adapters (mirror curator/graphql/adapters.py) ─────────────────────────

type syncStashID struct {
	endpoint string
	stashID  string
}

type syncTag struct {
	id        string
	name      *string
	updatedAt *string
	parents   []syncTag
	stashIDs  []syncStashID
}

type syncStudio struct {
	id        string
	name      *string
	updatedAt *string
	favorite  bool
	rating100 *int64
	parent    *syncStudio
}

type syncPerformer struct {
	id           string
	name         *string
	updatedAt    *string
	favorite     bool
	gender       *string
	rating100    *int64
	birthdate    *string
	ethnicity    *string
	country      *string
	eyeColor     *string
	hairColor    *string
	heightCM     *int64
	weightKG     *int64
	measurements *string
	augmentation *string
	tattoos      *string
	piercings    *string
	tags         []syncTag
}

type syncSourceFile struct {
	id              string
	durationSeconds *float64
}

type syncMarker struct {
	id         string
	seconds    float64
	endSeconds *float64
	primaryTag syncTag
	tags       []syncTag
}

type syncScene struct {
	id                  string
	title               *string
	details             *string
	sceneDate           *string
	rating100           *int64
	updatedAt           *string
	playCount           int64
	playDurationSeconds float64
	playHistoryMs       []int64
	oHistoryMs          []int64
	studio              *syncStudio
	tags                []syncTag
	performers          []syncPerformer
	files               []syncSourceFile
	markers             []syncMarker
}

type syncSourceEntity interface {
	entityType() string
	entityID() string
	entityUpdatedAt() (string, bool)
}

func (e *syncTag) entityType() string              { return "tag" }
func (e *syncTag) entityID() string                { return e.id }
func (e *syncTag) entityUpdatedAt() (string, bool) { return optionalString(e.updatedAt) }

func (e *syncStudio) entityType() string              { return "studio" }
func (e *syncStudio) entityID() string                { return e.id }
func (e *syncStudio) entityUpdatedAt() (string, bool) { return optionalString(e.updatedAt) }

func (e *syncPerformer) entityType() string              { return "performer" }
func (e *syncPerformer) entityID() string                { return e.id }
func (e *syncPerformer) entityUpdatedAt() (string, bool) { return optionalString(e.updatedAt) }

func (e *syncScene) entityType() string              { return "scene" }
func (e *syncScene) entityID() string                { return e.id }
func (e *syncScene) entityUpdatedAt() (string, bool) { return optionalString(e.updatedAt) }

func optionalString(value *string) (string, bool) {
	if value == nil {
		return "", false
	}
	return *value, true
}

func adaptSyncStashIDs(raw jVal) []syncStashID {
	out := make([]syncStashID, 0)
	for _, item := range raw.arr {
		if item.get("endpoint").truthy() && item.get("stash_id").truthy() {
			out = append(out, syncStashID{
				endpoint: item.get("endpoint").asString(),
				stashID:  item.get("stash_id").asString(),
			})
		}
	}
	return out
}

func adaptSyncTag(raw jVal, includeParents bool) syncTag {
	tag := syncTag{
		id:        raw.get("id").asString(),
		name:      optionalStringPtr(raw.get("name")),
		updatedAt: optionalStringPtr(raw.get("updated_at")),
		stashIDs:  adaptSyncStashIDs(raw.get("stash_ids")),
	}
	if includeParents {
		for _, parent := range raw.get("parents").arr {
			tag.parents = append(tag.parents, adaptSyncTag(parent, false))
		}
	}
	return tag
}

func adaptSyncStudio(raw jVal, includeParent bool) syncStudio {
	studio := syncStudio{
		id:        raw.get("id").asString(),
		name:      optionalStringPtr(raw.get("name")),
		updatedAt: optionalStringPtr(raw.get("updated_at")),
		favorite:  raw.get("favorite").truthy(),
		rating100: optionalIntPtr(raw.get("rating100")),
	}
	if includeParent && raw.get("parent_studio").kind == jObj {
		parent := adaptSyncStudio(raw.get("parent_studio"), false)
		studio.parent = &parent
	}
	return studio
}

func adaptSyncPerformer(raw jVal, includeDetails bool) syncPerformer {
	performer := syncPerformer{
		id:        raw.get("id").asString(),
		name:      optionalStringPtr(raw.get("name")),
		updatedAt: optionalStringPtr(raw.get("updated_at")),
		favorite:  raw.get("favorite").truthy(),
	}
	if includeDetails {
		performer.gender = optionalStringPtr(raw.get("gender"))
		performer.rating100 = optionalIntPtr(raw.get("rating100"))
		performer.birthdate = optionalStringPtr(raw.get("birthdate"))
		performer.ethnicity = optionalStringPtr(raw.get("ethnicity"))
		performer.country = optionalStringPtr(raw.get("country"))
		performer.eyeColor = optionalStringPtr(raw.get("eye_color"))
		performer.hairColor = optionalStringPtr(raw.get("hair_color"))
		performer.heightCM = optionalPositiveIntPtr(raw.get("height_cm"))
		performer.weightKG = optionalPositiveIntPtr(raw.get("weight"))
		performer.measurements = optionalStringPtr(raw.get("measurements"))
		performer.augmentation = optionalStringPtr(raw.get("fake_tits"))
		performer.tattoos = optionalStringPtr(raw.get("tattoos"))
		performer.piercings = optionalStringPtr(raw.get("piercings"))
	}
	for _, tag := range raw.get("tags").arr {
		performer.tags = append(performer.tags, adaptSyncTag(tag, false))
	}
	return performer
}

func adaptSyncScene(raw jVal) *syncScene {
	scene := &syncScene{
		id:                  raw.get("id").asString(),
		title:               optionalStringPtr(raw.get("title")),
		details:             optionalStringPtr(raw.get("details")),
		sceneDate:           optionalStringPtr(raw.get("date")),
		rating100:           optionalIntPtr(raw.get("rating100")),
		updatedAt:           optionalStringPtr(raw.get("updated_at")),
		playCount:           maxInt64(0, pythonInt(raw.get("play_count"))),
		playDurationSeconds: mathMax(0.0, pythonFloatOr(raw.get("play_duration"), 0)),
	}
	for _, value := range raw.get("play_history").arr {
		if ms, ok := epochMsOf(value); ok {
			scene.playHistoryMs = append(scene.playHistoryMs, ms)
		}
	}
	for _, value := range raw.get("o_history").arr {
		if ms, ok := epochMsOf(value); ok {
			scene.oHistoryMs = append(scene.oHistoryMs, ms)
		}
	}
	if studio := raw.get("studio"); studio.kind == jObj {
		adapted := adaptSyncStudio(studio, true)
		scene.studio = &adapted
	}
	for _, tag := range raw.get("tags").arr {
		scene.tags = append(scene.tags, adaptSyncTag(tag, false))
	}
	for _, performer := range raw.get("performers").arr {
		scene.performers = append(scene.performers, adaptSyncPerformer(performer, false))
	}
	for _, file := range raw.get("files").arr {
		sourceFile := syncSourceFile{id: file.get("id").asString()}
		if duration := file.get("duration"); duration.kind == jNum {
			value := pythonFloatOr(duration, 0)
			sourceFile.durationSeconds = &value
		}
		scene.files = append(scene.files, sourceFile)
	}
	for _, marker := range raw.get("scene_markers").arr {
		adapted := syncMarker{
			id:         marker.get("id").asString(),
			seconds:    pythonFloatOr(marker.get("seconds"), 0),
			primaryTag: adaptSyncTag(marker.get("primary_tag"), false),
		}
		if end := marker.get("end_seconds"); end.kind == jNum {
			value := pythonFloatOr(end, 0)
			adapted.endSeconds = &value
		}
		for _, tag := range marker.get("tags").arr {
			adapted.tags = append(adapted.tags, adaptSyncTag(tag, false))
		}
		scene.markers = append(scene.markers, adapted)
	}
	return scene
}

func optionalStringPtr(v jVal) *string {
	if v.kind != jStr || v.s == "" {
		return nil
	}
	value := v.s
	return &value
}

func optionalIntPtr(v jVal) *int64 {
	if v.kind != jNum || strings.ContainsAny(v.num, ".eE") {
		return nil
	}
	value := pythonInt(v)
	return &value
}

func optionalPositiveIntPtr(v jVal) *int64 {
	value := optionalIntPtr(v)
	if value == nil || *value <= 0 {
		return nil
	}
	return value
}

func epochMsOf(v jVal) (int64, bool) {
	if v.kind != jStr {
		return 0, false
	}
	// Mirrors adapters._epoch_ms: datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()*1000.
	parsed, err := parseISOTime(v.s)
	if err != nil {
		return 0, false
	}
	return parsed, true
}

// parseISOTime parses an ISO-8601 timestamp with an optional fractional
// seconds and Z/+hh:mm offset, returning Unix epoch milliseconds
// (truncated toward negative infinity, matching .timestamp()*1000 int()).
func parseISOTime(value string) (int64, error) {
	base := strings.ReplaceAll(value, "Z", "+00:00")
	// date and time split
	datePart := base
	timePart := ""
	offsetPart := ""
	if idx := strings.IndexByte(base, 'T'); idx >= 0 {
		datePart = base[:idx]
		rest := base[idx+1:]
		// offset can be +hh:mm, -hh:mm, or absent
		if len(rest) >= 6 {
			if rest[len(rest)-3] == ':' && (rest[len(rest)-6] == '+' || rest[len(rest)-6] == '-') {
				offsetPart = rest[len(rest)-6:]
				rest = rest[:len(rest)-6]
			}
		}
		timePart = rest
	}
	parts := strings.Split(datePart, "-")
	if len(parts) < 3 {
		return 0, errors.New("invalid date")
	}
	year, err1 := strconv.Atoi(parts[0])
	month, err2 := strconv.Atoi(parts[1])
	day, err3 := strconv.Atoi(parts[2])
	if err1 != nil || err2 != nil || err3 != nil {
		return 0, errors.New("invalid date")
	}
	hour, minute := 0, 0
	second := 0.0
	if timePart != "" {
		timeParts := strings.Split(timePart, ":")
		if len(timeParts) < 3 {
			return 0, errors.New("invalid time")
		}
		hour, err1 = strconv.Atoi(timeParts[0])
		minute, err2 = strconv.Atoi(timeParts[1])
		if err1 != nil || err2 != nil {
			return 0, errors.New("invalid time")
		}
		second, err3 = strconv.ParseFloat(timeParts[2], 64)
		if err3 != nil {
			return 0, errors.New("invalid time")
		}
	}
	offsetSeconds := int64(0)
	if offsetPart != "" {
		sign := 1
		if offsetPart[0] == '-' {
			sign = -1
		}
		offsetHours, err1 := strconv.Atoi(offsetPart[1:3])
		offsetMinutes, err2 := strconv.Atoi(offsetPart[4:6])
		if err1 != nil || err2 != nil {
			return 0, errors.New("invalid offset")
		}
		offsetSeconds = int64(sign) * int64(offsetHours*3600+offsetMinutes*60)
	}
	// Day count from the civil calendar (Python datetime ordinal math).
	days := civilDaysFromDate(year, month, day)
	secondsOfDay := int64(hour*3600 + minute*60 + int(second))
	// Truncate fractional seconds toward negative infinity for the micros.
	frac := second - float64(int(second))
	micros := int64(frac * 1e6)
	if micros < 0 {
		secondsOfDay--
		micros += 1000000
	}
	totalMicros := (days*86400+secondsOfDay)*1000000 + micros - offsetSeconds*1000000
	return totalMicros / 1000, nil
}

// civilDaysFromDate converts y/m/d to days since the Unix epoch (UTC
// midnight, so the day count is exact).
func civilDaysFromDate(year, month, day int) int64 {
	t := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	return t.Unix() / 86400
}

// adaptSyncEntity adapts one collection item by items_key.
func adaptSyncEntity(itemsKey string, raw jVal) syncSourceEntity {
	switch itemsKey {
	case "tags":
		tag := adaptSyncTag(raw, true)
		return &tag
	case "studios":
		studio := adaptSyncStudio(raw, true)
		return &studio
	case "performers":
		performer := adaptSyncPerformer(raw, true)
		return &performer
	case "scenes":
		return adaptSyncScene(raw)
	}
	return nil
}

// ── entity hashing (source_hash parity) ───────────────────────────────────

// syncHash mirrors repository._hash: sha256 of json.dumps(asdict(entity),
// sort_keys=True, separators=(",", ":")), serialized through the
// Python-compatible JSON writer so floats and nulls match byte-for-byte.
func syncHash(entity syncSourceEntity) string {
	return syncHashValue(syncAsdict(entity))
}

func syncHashValue(value jVal) string {
	digest := sha256.Sum256([]byte(value.marshalSortedKeys()))
	return hex.EncodeToString(digest[:])
}

// syncAsdict mirrors dataclasses.asdict: dataclass fields → keys, nested
// dataclasses → objects, tuples → arrays.
func syncAsdict(entity syncSourceEntity) jVal {
	switch e := entity.(type) {
	case *syncTag:
		return jvObj(
			jvKey("id", jvStr(e.id)),
			jvKey("name", jvOptionalString(e.name)),
			jvKey("updated_at", jvOptionalString(e.updatedAt)),
			jvKey("parents", syncAsdictTags(e.parents)),
			jvKey("stash_ids", syncAsdictStashIDs(e.stashIDs)),
		)
	case *syncStudio:
		parent := jvNull()
		if e.parent != nil {
			parent = syncAsdict(e.parent)
		}
		return jvObj(
			jvKey("id", jvStr(e.id)),
			jvKey("name", jvOptionalString(e.name)),
			jvKey("updated_at", jvOptionalString(e.updatedAt)),
			jvKey("favorite", jvBool(e.favorite)),
			jvKey("rating100", jvOptionalInt(e.rating100)),
			jvKey("parent", parent),
		)
	case *syncPerformer:
		return jvObj(
			jvKey("id", jvStr(e.id)),
			jvKey("name", jvOptionalString(e.name)),
			jvKey("updated_at", jvOptionalString(e.updatedAt)),
			jvKey("favorite", jvBool(e.favorite)),
			jvKey("gender", jvOptionalString(e.gender)),
			jvKey("rating100", jvOptionalInt(e.rating100)),
			jvKey("birthdate", jvOptionalString(e.birthdate)),
			jvKey("ethnicity", jvOptionalString(e.ethnicity)),
			jvKey("country", jvOptionalString(e.country)),
			jvKey("eye_color", jvOptionalString(e.eyeColor)),
			jvKey("hair_color", jvOptionalString(e.hairColor)),
			jvKey("height_cm", jvOptionalInt(e.heightCM)),
			jvKey("weight_kg", jvOptionalInt(e.weightKG)),
			jvKey("measurements", jvOptionalString(e.measurements)),
			jvKey("augmentation", jvOptionalString(e.augmentation)),
			jvKey("tattoos", jvOptionalString(e.tattoos)),
			jvKey("piercings", jvOptionalString(e.piercings)),
			jvKey("tags", syncAsdictTags(e.tags)),
		)
	case *syncScene:
		studio := jvNull()
		if e.studio != nil {
			studio = syncAsdict(e.studio)
		}
		playHistory := jvArr()
		for _, value := range e.playHistoryMs {
			playHistory.arr = append(playHistory.arr, jvInt(value))
		}
		oHistory := jvArr()
		for _, value := range e.oHistoryMs {
			oHistory.arr = append(oHistory.arr, jvInt(value))
		}
		files := jvArr()
		for _, file := range e.files {
			duration := jvNull()
			if file.durationSeconds != nil {
				duration = jvFloat(*file.durationSeconds)
			}
			files.arr = append(files.arr, jvObj(
				jvKey("id", jvStr(file.id)),
				jvKey("duration_seconds", duration),
			))
		}
		markers := jvArr()
		for _, marker := range e.markers {
			endSeconds := jvNull()
			if marker.endSeconds != nil {
				endSeconds = jvFloat(*marker.endSeconds)
			}
			markerTags := jvArr()
			for _, tag := range marker.tags {
				markerTags.arr = append(markerTags.arr, syncAsdict(&tag))
			}
			markers.arr = append(markers.arr, jvObj(
				jvKey("id", jvStr(marker.id)),
				jvKey("seconds", jvFloat(marker.seconds)),
				jvKey("end_seconds", endSeconds),
				jvKey("primary_tag", syncAsdict(&marker.primaryTag)),
				jvKey("tags", markerTags),
			))
		}
		tags := jvArr()
		for _, tag := range e.tags {
			tags.arr = append(tags.arr, syncAsdict(&tag))
		}
		performers := jvArr()
		for _, performer := range e.performers {
			performers.arr = append(performers.arr, syncAsdict(&performer))
		}
		return jvObj(
			jvKey("id", jvStr(e.id)),
			jvKey("title", jvOptionalString(e.title)),
			jvKey("details", jvOptionalString(e.details)),
			jvKey("scene_date", jvOptionalString(e.sceneDate)),
			jvKey("rating100", jvOptionalInt(e.rating100)),
			jvKey("updated_at", jvOptionalString(e.updatedAt)),
			jvKey("play_count", jvInt(e.playCount)),
			jvKey("play_duration_seconds", jvFloat(e.playDurationSeconds)),
			jvKey("play_history_ms", playHistory),
			jvKey("o_history_ms", oHistory),
			jvKey("studio", studio),
			jvKey("tags", tags),
			jvKey("performers", performers),
			jvKey("files", files),
			jvKey("markers", markers),
		)
	}
	return jvNull()
}

func syncAsdictTags(tags []syncTag) jVal {
	out := jvArr()
	for i := range tags {
		out.arr = append(out.arr, syncAsdict(&tags[i]))
	}
	return out
}

func syncAsdictStashIDs(ids []syncStashID) jVal {
	out := jvArr()
	for _, id := range ids {
		out.arr = append(out.arr, jvObj(
			jvKey("endpoint", jvStr(id.endpoint)),
			jvKey("stash_id", jvStr(id.stashID)),
		))
	}
	return out
}

func jvOptionalString(value *string) jVal {
	if value == nil {
		return jvNull()
	}
	return jvStr(*value)
}

func jvOptionalInt(value *int64) jVal {
	if value == nil {
		return jvNull()
	}
	return jvInt(*value)
}

// syncHashFile mirrors repository._hash for SourceFile and Marker rows.
func syncHashFile(file syncSourceFile) string {
	duration := jvNull()
	if file.durationSeconds != nil {
		duration = jvFloat(*file.durationSeconds)
	}
	return syncHashValue(jvObj(
		jvKey("id", jvStr(file.id)),
		jvKey("duration_seconds", duration),
	))
}

func syncHashMarker(marker syncMarker) string {
	endSeconds := jvNull()
	if marker.endSeconds != nil {
		endSeconds = jvFloat(*marker.endSeconds)
	}
	markerTags := jvArr()
	for i := range marker.tags {
		markerTags.arr = append(markerTags.arr, syncAsdict(&marker.tags[i]))
	}
	return syncHashValue(jvObj(
		jvKey("id", jvStr(marker.id)),
		jvKey("seconds", jvFloat(marker.seconds)),
		jvKey("end_seconds", endSeconds),
		jvKey("primary_tag", syncAsdict(&marker.primaryTag)),
		jvKey("tags", markerTags),
	))
}

// syncSourceHash returns the hash Python stores for any hashed row.
func syncSourceHash(entity syncSourceEntity) string {
	if scene, ok := entity.(*syncScene); ok {
		return syncHash(scene)
	}
	return syncHash(entity)
}

// ── sync repository (mirror curator/sync/repository.py) ───────────────────

const syncSweepPageSize = 5000

var syncEntityTables = map[string][2]string{
	"tag":       {"source_tag", "tag_id"},
	"studio":    {"source_studio", "studio_id"},
	"performer": {"source_performer", "performer_id"},
	"scene":     {"source_scene", "scene_id"},
}

// syncRepository mirrors SyncRepository.
type syncRepository struct {
	db dbx
}

func newSyncRepository(db dbx) *syncRepository { return &syncRepository{db: db} }

type syncRunRow struct {
	runID         string
	mode          string
	state         string
	serverVersion string
	startedAtMs   int64
}

func (r *syncRepository) resumableRun(mode string) (*syncRunRow, error) {
	var row syncRunRow
	err := r.db.QueryRow(`
SELECT run_id, mode, state, server_version, started_at_ms
FROM sync_run
WHERE mode = ? AND state IN ('running', 'failed')
ORDER BY started_at_ms DESC LIMIT 1`, mode).
		Scan(&row.runID, &row.mode, &row.state, &row.serverVersion, &row.startedAtMs)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &row, nil
}

func (r *syncRepository) startRun(runID, mode, serverVersion string, nowMs int64) error {
	return execImmediate(r.db,
		`INSERT INTO sync_run(run_id, mode, state, server_version, started_at_ms)
VALUES (?, ?, 'running', ?, ?)`, runID, mode, serverVersion, nowMs)
}

func (r *syncRepository) resumeRun(runID string) error {
	return execImmediate(r.db,
		`UPDATE sync_run SET state = 'running', error = NULL WHERE run_id = ?`, runID)
}

// prepareEntity returns the next page for an entity in this run, or -1 when
// the entity already completed (mirrors returning None).
func (r *syncRepository) prepareEntity(runID, entityType string, nowMs int64) (int64, bool, error) {
	var cursorRunID string
	var pageCursor *string
	var state string
	err := r.db.QueryRow(`SELECT run_id, page_cursor, state FROM sync_cursor WHERE entity_type = ?`,
		entityType).Scan(&cursorRunID, &pageCursor, &state)
	if err == sql.ErrNoRows {
		if err := execImmediate(r.db, `
INSERT INTO sync_cursor(
    entity_type, watermark, page_cursor, state, updated_at_ms,
    run_id, baseline_watermark, pending_watermark
) VALUES (?, NULL, '1', 'running', ?, ?, NULL, NULL)
ON CONFLICT(entity_type) DO UPDATE SET
    page_cursor = '1', state = 'running', updated_at_ms = excluded.updated_at_ms,
    run_id = excluded.run_id,
    baseline_watermark = sync_cursor.watermark, pending_watermark = NULL`,
			entityType, nowMs, runID); err != nil {
			return 0, false, err
		}
		if err := execImmediate(r.db, `
UPDATE sync_cursor
SET baseline_watermark = watermark
WHERE entity_type = ? AND baseline_watermark IS NULL`, entityType); err != nil {
			return 0, false, err
		}
		return 1, true, nil
	}
	if err != nil {
		return 0, false, err
	}
	if cursorRunID == runID && state == "complete" {
		return 0, false, nil
	}
	if cursorRunID == runID {
		if err := execImmediate(r.db, `
UPDATE sync_cursor SET state = 'running', updated_at_ms = ?
WHERE entity_type = ?`, nowMs, entityType); err != nil {
			return 0, false, err
		}
		page := int64(1)
		if pageCursor != nil {
			if parsed, err := parseInt64(*pageCursor); err == nil {
				page = parsed
			}
		}
		return page, true, nil
	}
	if err := execImmediate(r.db, `
INSERT INTO sync_cursor(
    entity_type, watermark, page_cursor, state, updated_at_ms,
    run_id, baseline_watermark, pending_watermark
) VALUES (?, NULL, '1', 'running', ?, ?, NULL, NULL)
ON CONFLICT(entity_type) DO UPDATE SET
    page_cursor = '1', state = 'running', updated_at_ms = excluded.updated_at_ms,
    run_id = excluded.run_id,
    baseline_watermark = sync_cursor.watermark, pending_watermark = NULL`,
		entityType, nowMs, runID); err != nil {
		return 0, false, err
	}
	if err := execImmediate(r.db, `
UPDATE sync_cursor
SET baseline_watermark = watermark
WHERE entity_type = ? AND baseline_watermark IS NULL`, entityType); err != nil {
		return 0, false, err
	}
	return 1, true, nil
}

func (r *syncRepository) cursorWatermarks(entityType string) (string, string, error) {
	var baseline, pending *string
	err := r.db.QueryRow(`SELECT baseline_watermark, pending_watermark FROM sync_cursor WHERE entity_type = ?`,
		entityType).Scan(&baseline, &pending)
	if err == sql.ErrNoRows {
		return "", "", nil
	}
	if err != nil {
		return "", "", err
	}
	baselineValue, pendingValue := "", ""
	if baseline != nil {
		baselineValue = *baseline
	}
	if pending != nil {
		pendingValue = *pending
	}
	return baselineValue, pendingValue, nil
}

func (r *syncRepository) savePage(runID, entityType string, items []syncSourceEntity,
	nextPage int64, pageHighWatermark string, nowMs int64, recordSeen bool) ([]string, error) {
	changed := make([]string, 0)
	conn, err := r.db.Conn(context.Background())
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return nil, err
	}
	fail := func(err error) ([]string, error) {
		conn.ExecContext(context.Background(), "ROLLBACK")
		return nil, err
	}
	for _, item := range items {
		changedFlag, err := syncUpsert(conn, item)
		if err != nil {
			return fail(err)
		}
		if changedFlag {
			changed = append(changed, item.entityID())
		}
		if recordSeen {
			if _, err := conn.ExecContext(context.Background(), `
INSERT OR IGNORE INTO sync_seen(run_id, entity_type, entity_id)
VALUES (?, ?, ?)`, runID, entityType, item.entityID()); err != nil {
				return fail(err)
			}
		}
	}
	var pending *string
	if err := conn.QueryRowContext(context.Background(), `SELECT pending_watermark FROM sync_cursor WHERE entity_type = ?`,
		entityType).Scan(&pending); err != nil {
		return fail(err)
	}
	pendingValue := ""
	if pending != nil {
		pendingValue = *pending
	}
	if pageHighWatermark != "" {
		if pendingValue == "" || pageHighWatermark > pendingValue {
			pendingValue = pageHighWatermark
		}
	}
	if _, err := conn.ExecContext(context.Background(), `
UPDATE sync_cursor
SET page_cursor = ?, pending_watermark = ?, updated_at_ms = ?
WHERE entity_type = ? AND run_id = ?`,
		int64ToString(nextPage), pendingValue, nowMs, entityType, runID); err != nil {
		return fail(err)
	}
	if _, err := conn.ExecContext(context.Background(), "COMMIT"); err != nil {
		return nil, err
	}
	return changed, nil
}

func (r *syncRepository) completeEntity(runID, entityType string, nowMs int64) error {
	return execImmediate(r.db, `
UPDATE sync_cursor
SET watermark = COALESCE(pending_watermark, watermark), page_cursor = NULL,
    state = 'complete', updated_at_ms = ?
WHERE entity_type = ? AND run_id = ?`, nowMs, entityType, runID)
}

func (r *syncRepository) entityCount(entityType string) (int64, error) {
	table := syncEntityTables[entityType][0]
	var count int64
	if err := r.db.QueryRow(`SELECT count(*) FROM ` + table).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}

func (r *syncRepository) upsertEntity(entity syncSourceEntity) (bool, error) {
	conn, err := r.db.Conn(context.Background())
	if err != nil {
		return false, err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return false, err
	}
	changed, err := syncUpsert(conn, entity)
	if err != nil {
		conn.ExecContext(context.Background(), "ROLLBACK")
		return false, err
	}
	if _, err := conn.ExecContext(context.Background(), "COMMIT"); err != nil {
		return false, err
	}
	return changed, nil
}

func (r *syncRepository) deleteEntity(entityType, entityID string) error {
	return r.deleteEntities(entityType, []string{entityID})
}

func (r *syncRepository) deleteAbsent(entityType string, present map[string]bool) ([]string, error) {
	table, column := syncEntityTables[entityType][0], syncEntityTables[entityType][1]
	rows, err := r.db.Query(`SELECT ` + column + ` FROM ` + table)
	if err != nil {
		return nil, err
	}
	deleted := make([]string, 0)
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		if !present[id] {
			deleted = append(deleted, id)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.Strings(deleted)
	if err := r.deleteEntities(entityType, deleted); err != nil {
		return nil, err
	}
	return deleted, nil
}

func (r *syncRepository) reconcile(runID string) error {
	conn, err := r.db.Conn(context.Background())
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	fail := func(err error) error {
		conn.ExecContext(context.Background(), "ROLLBACK")
		return err
	}
	for _, entityType := range []string{"scene", "performer", "tag", "studio"} {
		table, column := syncEntityTables[entityType][0], syncEntityTables[entityType][1]
		rows, err := conn.QueryContext(context.Background(), `
SELECT `+column+` FROM `+table+` WHERE NOT EXISTS (
    SELECT 1 FROM sync_seen
    WHERE run_id = ? AND entity_type = ? AND entity_id = `+column+`
)`, runID, entityType)
		if err != nil {
			return fail(err)
		}
		deleted := make([]string, 0)
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				return fail(err)
			}
			deleted = append(deleted, id)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return fail(err)
		}
		if err := syncDeleteEntitiesConn(conn, entityType, deleted); err != nil {
			return fail(err)
		}
	}
	if _, err := conn.ExecContext(context.Background(), "COMMIT"); err != nil {
		return err
	}
	return nil
}

func (r *syncRepository) deleteEntities(entityType string, deleted []string) error {
	if len(deleted) == 0 {
		return nil
	}
	conn, err := r.db.Conn(context.Background())
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	if err := syncDeleteEntitiesConn(conn, entityType, deleted); err != nil {
		conn.ExecContext(context.Background(), "ROLLBACK")
		return err
	}
	_, err = conn.ExecContext(context.Background(), "COMMIT")
	return err
}

func (r *syncRepository) finishRun(runID string, nowMs int64) error {
	return execImmediate(r.db, `
UPDATE sync_run SET state = 'complete', completed_at_ms = ?, error = NULL
WHERE run_id = ?`, nowMs, runID)
}

func (r *syncRepository) failRun(runID, entityType, errorText string, nowMs int64) error {
	if len(errorText) > 2000 {
		errorText = errorText[:2000]
	}
	if err := execImmediate(r.db, `
UPDATE sync_run SET state = 'failed', error = ? WHERE run_id = ?`, errorText, runID); err != nil {
		return err
	}
	if entityType == "" {
		return nil
	}
	return execImmediate(r.db, `
UPDATE sync_cursor SET state = 'failed', updated_at_ms = ?
WHERE entity_type = ? AND run_id = ?`, nowMs, entityType, runID)
}

// syncDeleteEntitiesConn mirrors repository._delete_entities: drop entities
// Stash no longer has, releasing the references SQLite does not cascade.
func syncDeleteEntitiesConn(conn *sql.Conn, entityType string, deleted []string) error {
	if len(deleted) == 0 {
		return nil
	}
	table, column := syncEntityTables[entityType][0], syncEntityTables[entityType][1]
	if _, err := conn.ExecContext(context.Background(), `CREATE TEMP TABLE IF NOT EXISTS deleted_entity(entity_id TEXT)`); err != nil {
		return err
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM deleted_entity`); err != nil {
		return err
	}
	for _, identifier := range deleted {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO deleted_entity(entity_id) VALUES (?)`, identifier); err != nil {
			return err
		}
	}
	switch entityType {
	case "tag":
		if _, err := conn.ExecContext(context.Background(), `
DELETE FROM scene_marker WHERE primary_tag_id IN (SELECT entity_id FROM deleted_entity)`); err != nil {
			return err
		}
	case "studio":
		if _, err := conn.ExecContext(context.Background(), `
UPDATE source_studio SET parent_studio_id = NULL WHERE parent_studio_id IN (SELECT entity_id FROM deleted_entity)`); err != nil {
			return err
		}
		if _, err := conn.ExecContext(context.Background(), `
UPDATE source_scene SET studio_id = NULL WHERE studio_id IN (SELECT entity_id FROM deleted_entity)`); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM `+table+` WHERE `+column+` IN (SELECT entity_id FROM deleted_entity)`); err != nil {
		return err
	}
	_, err := conn.ExecContext(context.Background(), `DELETE FROM deleted_entity`)
	return err
}

// ── entity upserts (mirror repository._upsert_*) ──────────────────────────

func syncUpsert(conn *sql.Conn, entity syncSourceEntity) (bool, error) {
	table, column := syncEntityTableFor(entity)
	var existing string
	err := conn.QueryRowContext(context.Background(), `SELECT source_hash FROM `+table+` WHERE `+column+`=?`,
		entity.entityID()).Scan(&existing)
	if err == nil && existing == syncHash(entity) {
		return false, nil
	}
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return false, err
	}
	switch e := entity.(type) {
	case *syncTag:
		if err := syncUpsertTag(conn, e, true); err != nil {
			return false, err
		}
	case *syncStudio:
		if err := syncUpsertStudio(conn, e, true); err != nil {
			return false, err
		}
	case *syncPerformer:
		if err := syncUpsertPerformer(conn, e, true); err != nil {
			return false, err
		}
	case *syncScene:
		if err := syncUpsertScene(conn, e); err != nil {
			return false, err
		}
	}
	return true, nil
}

func syncEntityTableFor(entity syncSourceEntity) (string, string) {
	switch entity.(type) {
	case *syncTag:
		return "source_tag", "tag_id"
	case *syncStudio:
		return "source_studio", "studio_id"
	case *syncPerformer:
		return "source_performer", "performer_id"
	case *syncScene:
		return "source_scene", "scene_id"
	}
	return "", ""
}

func syncUpsertTag(conn *sql.Conn, tag *syncTag, replaceParents bool) error {
	if !replaceParents {
		for i := range tag.parents {
			if err := syncUpsertTag(conn, &tag.parents[i], false); err != nil {
				return err
			}
		}
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_tag(tag_id, name, updated_at, source_hash)
VALUES (?, ?, ?, ?)
ON CONFLICT(tag_id) DO UPDATE SET
    name=COALESCE(excluded.name, source_tag.name),
    updated_at=COALESCE(excluded.updated_at, source_tag.updated_at)`,
			tag.id, jvOptionalStringPtr(tag.name), jvOptionalStringPtr(tag.updatedAt), syncHash(tag)); err != nil {
			return err
		}
		return nil
	}
	for i := range tag.parents {
		if err := syncUpsertTag(conn, &tag.parents[i], false); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_tag(tag_id, name, updated_at, source_hash) VALUES (?, ?, ?, ?)
ON CONFLICT(tag_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at,
    source_hash=excluded.source_hash`,
		tag.id, jvOptionalStringPtr(tag.name), jvOptionalStringPtr(tag.updatedAt), syncHash(tag)); err != nil {
		return err
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM tag_parent WHERE tag_id = ?`, tag.id); err != nil {
		return err
	}
	for _, parent := range tag.parents {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO tag_parent(tag_id, parent_tag_id) VALUES (?, ?)`,
			tag.id, parent.id); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM source_tag_stash_id WHERE tag_id = ?`, tag.id); err != nil {
		return err
	}
	seen := map[string]bool{}
	for _, stashID := range tag.stashIDs {
		if seen[stashID.endpoint] {
			continue
		}
		seen[stashID.endpoint] = true
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_tag_stash_id(tag_id, endpoint, stash_id)
VALUES (?, ?, ?)`, tag.id, stashID.endpoint, stashID.stashID); err != nil {
			return err
		}
	}
	return nil
}

func syncUpsertStudio(conn *sql.Conn, studio *syncStudio, replaceDetails bool) error {
	if studio.parent != nil {
		if err := syncUpsertStudio(conn, studio.parent, false); err != nil {
			return err
		}
	}
	parentID := jvNull()
	if studio.parent != nil {
		parentID = jvStr(studio.parent.id)
	}
	if !replaceDetails {
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_studio(studio_id, name, updated_at, source_hash)
VALUES (?, ?, ?, ?)
ON CONFLICT(studio_id) DO UPDATE SET
    name=COALESCE(excluded.name, source_studio.name),
    updated_at=COALESCE(excluded.updated_at, source_studio.updated_at)`,
			studio.id, jvOptionalStringPtr(studio.name), jvOptionalStringPtr(studio.updatedAt), syncHash(studio)); err != nil {
			return err
		}
		return nil
	}
	_, err := conn.ExecContext(context.Background(), `
INSERT INTO source_studio(
    studio_id, name, parent_studio_id, updated_at, source_hash, favorite, rating100
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(studio_id) DO UPDATE SET name=excluded.name,
    parent_studio_id=excluded.parent_studio_id, updated_at=excluded.updated_at,
    source_hash=excluded.source_hash, favorite=excluded.favorite,
    rating100=excluded.rating100`,
		studio.id, jvOptionalStringPtr(studio.name), jvOptionalStringPtrOf(parentID),
		jvOptionalStringPtr(studio.updatedAt), syncHash(studio), boolToInt(studio.favorite),
		jvOptionalIntPtr(studio.rating100))
	return err
}

func syncUpsertPerformer(conn *sql.Conn, performer *syncPerformer, replaceTags bool) error {
	for i := range performer.tags {
		if err := syncUpsertTag(conn, &performer.tags[i], false); err != nil {
			return err
		}
	}
	_, err := conn.ExecContext(context.Background(), `
INSERT INTO source_performer(
    performer_id, name, favorite, birthdate, ethnicity, country, eye_color,
    hair_color, height_cm, weight_kg, measurements, augmentation, tattoos,
    piercings, updated_at, source_hash, gender, rating100
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(performer_id) DO UPDATE SET name=excluded.name, favorite=excluded.favorite,
    birthdate=COALESCE(excluded.birthdate, source_performer.birthdate),
    ethnicity=COALESCE(excluded.ethnicity, source_performer.ethnicity),
    country=COALESCE(excluded.country, source_performer.country),
    eye_color=COALESCE(excluded.eye_color, source_performer.eye_color),
    hair_color=COALESCE(excluded.hair_color, source_performer.hair_color),
    height_cm=COALESCE(excluded.height_cm, source_performer.height_cm),
    weight_kg=COALESCE(excluded.weight_kg, source_performer.weight_kg),
    measurements=COALESCE(excluded.measurements, source_performer.measurements),
    augmentation=COALESCE(excluded.augmentation, source_performer.augmentation),
    tattoos=COALESCE(excluded.tattoos, source_performer.tattoos),
    piercings=COALESCE(excluded.piercings, source_performer.piercings),
    updated_at=excluded.updated_at, source_hash=excluded.source_hash,
    gender=COALESCE(excluded.gender, source_performer.gender),
    rating100=COALESCE(excluded.rating100, source_performer.rating100)`,
		performer.id, jvOptionalStringPtr(performer.name), boolToInt(performer.favorite),
		jvOptionalStringPtr(performer.birthdate), jvOptionalStringPtr(performer.ethnicity),
		jvOptionalStringPtr(performer.country), jvOptionalStringPtr(performer.eyeColor),
		jvOptionalStringPtr(performer.hairColor), jvOptionalIntPtr(performer.heightCM),
		jvOptionalIntPtr(performer.weightKG), jvOptionalStringPtr(performer.measurements),
		jvOptionalStringPtr(performer.augmentation), jvOptionalStringPtr(performer.tattoos),
		jvOptionalStringPtr(performer.piercings), jvOptionalStringPtr(performer.updatedAt),
		syncHash(performer), jvOptionalStringPtr(performer.gender),
		jvOptionalIntPtr(performer.rating100))
	if err != nil {
		return err
	}
	if replaceTags {
		if _, err := conn.ExecContext(context.Background(), `DELETE FROM performer_tag WHERE performer_id = ?`, performer.id); err != nil {
			return err
		}
		for _, tag := range performer.tags {
			if _, err := conn.ExecContext(context.Background(), `INSERT INTO performer_tag(performer_id, tag_id) VALUES (?, ?)`,
				performer.id, tag.id); err != nil {
				return err
			}
		}
	}
	return nil
}

func syncUpsertScene(conn *sql.Conn, scene *syncScene) error {
	if scene.studio != nil {
		if err := syncUpsertStudio(conn, scene.studio, false); err != nil {
			return err
		}
	}
	for i := range scene.tags {
		if err := syncUpsertTag(conn, &scene.tags[i], false); err != nil {
			return err
		}
	}
	for i := range scene.performers {
		performer := &scene.performers[i]
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_performer(
    performer_id, name, favorite, updated_at, source_hash
) VALUES (?, ?, 0, ?, ?)
ON CONFLICT(performer_id) DO UPDATE SET
    name=COALESCE(excluded.name, source_performer.name),
    updated_at=COALESCE(excluded.updated_at, source_performer.updated_at)`,
			performer.id, jvOptionalStringPtr(performer.name),
			jvOptionalStringPtr(performer.updatedAt), syncHash(performer)); err != nil {
			return err
		}
	}
	for i := range scene.markers {
		if err := syncUpsertTag(conn, &scene.markers[i].primaryTag, false); err != nil {
			return err
		}
		for j := range scene.markers[i].tags {
			if err := syncUpsertTag(conn, &scene.markers[i].tags[j], false); err != nil {
				return err
			}
		}
	}
	studioID := jvNull()
	if scene.studio != nil {
		studioID = jvStr(scene.studio.id)
	}
	if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_scene(
    scene_id, title, details, scene_date, studio_id, play_count,
    play_duration_seconds, rating100, updated_at, source_hash
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET title=excluded.title, details=excluded.details,
    scene_date=excluded.scene_date, studio_id=excluded.studio_id,
    play_count=excluded.play_count,
    play_duration_seconds=excluded.play_duration_seconds,
    rating100=excluded.rating100, updated_at=excluded.updated_at,
    source_hash=excluded.source_hash`,
		scene.id, jvOptionalStringPtr(scene.title), jvOptionalStringPtr(scene.details),
		jvOptionalStringPtr(scene.sceneDate), jvOptionalStringPtrOf(studioID),
		scene.playCount, scene.playDurationSeconds, jvOptionalIntPtr(scene.rating100),
		jvOptionalStringPtr(scene.updatedAt), syncHash(scene)); err != nil {
		return err
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM source_file WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for _, file := range scene.files {
		duration := jvNull()
		if file.durationSeconds != nil {
			duration = jvFloat(*file.durationSeconds)
		}
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO source_file(file_id, scene_id, duration_seconds, available, source_hash)
VALUES (?, ?, ?, 1, ?)
ON CONFLICT(file_id) DO UPDATE SET scene_id=excluded.scene_id,
    duration_seconds=excluded.duration_seconds, available=excluded.available,
    source_hash=excluded.source_hash`,
			file.id, scene.id, jvOptionalFloatPtr(duration), syncHashFile(file)); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM scene_performer WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for position, performer := range scene.performers {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO scene_performer(scene_id, performer_id, position) VALUES (?, ?, ?)`,
			scene.id, performer.id, position); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM scene_tag WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for _, tag := range scene.tags {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO scene_tag(scene_id, tag_id, provenance) VALUES (?, ?, 'scene')`,
			scene.id, tag.id); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM scene_marker WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for _, marker := range scene.markers {
		endSeconds := jvNull()
		if marker.endSeconds != nil {
			endSeconds = jvFloat(*marker.endSeconds)
		}
		if _, err := conn.ExecContext(context.Background(), `
INSERT INTO scene_marker(
    marker_id, scene_id, seconds, end_seconds, primary_tag_id, source_hash
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(marker_id) DO UPDATE SET scene_id=excluded.scene_id,
    seconds=excluded.seconds, end_seconds=excluded.end_seconds,
    primary_tag_id=excluded.primary_tag_id, source_hash=excluded.source_hash`,
			marker.id, scene.id, marker.seconds, jvOptionalFloatPtr(endSeconds),
			marker.primaryTag.id, syncHashMarker(marker)); err != nil {
			return err
		}
		if _, err := conn.ExecContext(context.Background(), `DELETE FROM marker_tag WHERE marker_id = ?`, marker.id); err != nil {
			return err
		}
		for _, tag := range marker.tags {
			if _, err := conn.ExecContext(context.Background(), `INSERT INTO marker_tag(marker_id, tag_id) VALUES (?, ?)`,
				marker.id, tag.id); err != nil {
				return err
			}
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM source_play WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for ordinal, timestamp := range scene.playHistoryMs {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO source_play(scene_id, played_at_ms, ordinal) VALUES (?, ?, ?)`,
			scene.id, timestamp, ordinal); err != nil {
			return err
		}
	}
	if _, err := conn.ExecContext(context.Background(), `DELETE FROM source_o WHERE scene_id = ?`, scene.id); err != nil {
		return err
	}
	for ordinal, timestamp := range scene.oHistoryMs {
		if _, err := conn.ExecContext(context.Background(), `INSERT INTO source_o(scene_id, occurred_at_ms, ordinal) VALUES (?, ?, ?)`,
			scene.id, timestamp, ordinal); err != nil {
			return err
		}
	}
	return nil
}

func jvOptionalStringPtr(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func jvOptionalIntPtr(value *int64) any {
	if value == nil {
		return nil
	}
	return *value
}

func jvOptionalFloatPtr(value jVal) any {
	if value.kind == jNull {
		return nil
	}
	return numberValue(value)
}

func jvOptionalStringPtrOf(value jVal) any {
	if value.kind == jNull {
		return nil
	}
	return value.asString()
}

// ── sync service (mirror curator/sync/service.py) ─────────────────────────

type syncCapabilities struct {
	serverVersion string
}

type syncResult struct {
	runID               string
	mode                string
	serverVersion       string
	resumed             bool
	entityCounts        map[string]int64
	changedEntityCounts map[string]int64
	sceneIDs            []string
	deletedEntityCounts map[string]int64
}

// probeSyncCapabilities mirrors SyncService's probe_capabilities.
func probeSyncCapabilities(clientURL string, headers map[string]string) (syncCapabilities, error) {
	data, err := graphqlQuery(clientURL, headers, syncCapabilitiesQuery, jvNull())
	if err != nil {
		return syncCapabilities{}, err
	}
	version := data.get("version")
	if version.kind != jObj || !version.get("version").truthy() {
		return syncCapabilities{}, errors.New("Stash did not return a compatible version response")
	}
	requirements := map[string][]string{
		"queryType":     {"findTags", "findStudios", "findPerformers", "findScenes"},
		"sceneType":     {"id", "updated_at", "play_count", "play_duration", "play_history", "o_history", "files", "scene_markers", "tags", "performers"},
		"performerType": {"id", "updated_at", "favorite", "weight", "fake_tits"},
		"tagType":       {"id", "updated_at", "stash_ids"},
	}
	for typeKey, required := range requirements {
		fieldKey := "fields"
		typeData := data.get(typeKey)
		if typeData.kind != jObj || typeData.get(fieldKey).kind != jArr {
			return syncCapabilities{}, fmt.Errorf("Stash capability probe is missing %s", typeKey)
		}
		available := map[string]bool{}
		for _, field := range typeData.get(fieldKey).arr {
			if field.get("name").truthy() {
				available[field.get("name").asString()] = true
			}
		}
		missing := make([]string, 0)
		for _, field := range required {
			if !available[field] {
				missing = append(missing, field)
			}
		}
		sort.Strings(missing)
		if len(missing) > 0 {
			return syncCapabilities{}, fmt.Errorf("Stash %s is missing required fields: %v", typeKey, missing)
		}
	}
	// sceneFilterType with play_count and last_played_at.
	sceneFilterType := data.get("sceneFilterType")
	if sceneFilterType.kind != jObj || sceneFilterType.get("inputFields").kind != jArr {
		return syncCapabilities{}, errors.New("Stash capability probe is missing sceneFilterType")
	}
	available := map[string]bool{}
	for _, field := range sceneFilterType.get("inputFields").arr {
		if field.get("name").truthy() {
			available[field.get("name").asString()] = true
		}
	}
	missing := make([]string, 0)
	for _, field := range []string{"play_count", "last_played_at"} {
		if !available[field] {
			missing = append(missing, field)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		return syncCapabilities{}, fmt.Errorf("Stash sceneFilterType is missing required fields: %v", missing)
	}
	return syncCapabilities{serverVersion: version.get("version").asString()}, nil
}

// syncService mirrors SyncService.
type syncService struct {
	clientURL string
	headers   map[string]string
	repo      *syncRepository
	pageSize  int64
	clockMs   func() int64
	idFactory func() string
	progress  func(entityType string, processed, total int64, position, entityCount int)
}

func newSyncService(clientURL string, headers map[string]string, repo *syncRepository, pageSize int64) (*syncService, error) {
	if pageSize < 1 {
		return nil, errors.New("page_size must be positive")
	}
	return &syncService{
		clientURL: clientURL,
		headers:   headers,
		repo:      repo,
		pageSize:  pageSize,
		clockMs:   nowMs,
		idFactory: uuid4,
	}, nil
}

func (s *syncService) sync(full, playsOnly bool) (syncResult, error) {
	if full && playsOnly {
		return syncResult{}, errors.New("full and plays_only are mutually exclusive")
	}
	runMode := "incremental"
	mode := runMode
	if playsOnly {
		mode = "plays"
	} else if full {
		runMode = "full"
		mode = "full"
	}
	capabilities, err := probeSyncCapabilities(s.clientURL, s.headers)
	if err != nil {
		return syncResult{}, err
	}
	existing, err := s.repo.resumableRun(runMode)
	if err != nil {
		return syncResult{}, err
	}
	resumed := existing != nil
	var runID string
	if existing == nil {
		runID = s.idFactory()
		if err := s.repo.startRun(runID, runMode, capabilities.serverVersion, s.clockMs()); err != nil {
			return syncResult{}, err
		}
	} else {
		runID = existing.runID
		if err := s.repo.resumeRun(runID); err != nil {
			return syncResult{}, err
		}
	}
	counts := map[string]int64{}
	changedCounts := map[string]int64{}
	deletedCounts := map[string]int64{}
	sceneIDs := map[string]bool{}
	operations := make([]syncOperation, 0)
	for _, operation := range syncOperations() {
		if full && operation.incrementalOnly {
			continue
		}
		operations = append(operations, operation)
	}
	if playsOnly {
		filtered := make([]syncOperation, 0)
		for _, operation := range operations {
			if operation.incrementalOnly {
				filtered = append(filtered, operation)
			}
		}
		operations = filtered
	}
	var currentEntity string
	runErr := func() error {
		for position, operation := range operations {
			currentEntity = operation.entityType
			count, ids, err := s.syncEntity(runID, operation, full, position, len(operations))
			if err != nil {
				return err
			}
			counts[currentEntity] = count
			changedCounts[currentEntity] = int64(len(ids))
			if operation.itemsKey == "scenes" {
				for _, id := range ids {
					sceneIDs[id] = true
				}
			}
		}
		currentEntity = ""
		if full {
			if err := s.repo.reconcile(runID); err != nil {
				return err
			}
		} else if !playsOnly {
			for _, operation := range operations {
				currentEntity = operation.entityType
				deleted, err := s.pruneDeleted(operation)
				if err != nil {
					return err
				}
				if len(deleted) > 0 {
					deletedCounts[operation.entityType] = int64(len(deleted))
				}
			}
			currentEntity = ""
		}
		return s.repo.finishRun(runID, s.clockMs())
	}()
	if runErr != nil {
		errorText := runErr.Error()
		if len(errorText) > 2000 {
			errorText = errorText[:2000]
		}
		if err := s.repo.failRun(runID, currentEntity, errorText, s.clockMs()); err != nil {
			return syncResult{}, err
		}
		return syncResult{}, runErr
	}
	sceneList := make([]string, 0, len(sceneIDs))
	for id := range sceneIDs {
		sceneList = append(sceneList, id)
	}
	sort.Strings(sceneList)
	return syncResult{
		runID:               runID,
		mode:                mode,
		serverVersion:       capabilities.serverVersion,
		resumed:             resumed,
		entityCounts:        counts,
		changedEntityCounts: changedCounts,
		sceneIDs:            sceneList,
		deletedEntityCounts: deletedCounts,
	}, nil
}

// pruneDeleted mirrors SyncService._prune_deleted.
func (s *syncService) pruneDeleted(operation syncOperation) ([]string, error) {
	if operation.idsDocument == "" {
		return nil, nil
	}
	localTotal, err := s.repo.entityCount(operation.entityType)
	if err != nil {
		return nil, err
	}
	probe, err := graphqlQuery(s.clientURL, s.headers, operation.idsDocument,
		jvObj(jvKey("page", jvInt(1)), jvKey("perPage", jvInt(0))))
	if err != nil {
		return nil, err
	}
	root := probe.get(operation.rootKey)
	remoteTotal := pythonInt(root.get("count"))
	if localTotal <= remoteTotal {
		return nil, nil
	}
	present := map[string]bool{}
	page := int64(1)
	for {
		data, err := graphqlQuery(s.clientURL, s.headers, operation.idsDocument,
			jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(syncSweepPageSize))))
		if err != nil {
			return nil, err
		}
		root := data.get(operation.rootKey)
		count := pythonInt(root.get("count"))
		items := root.get(operation.itemsKey)
		for _, item := range items.arr {
			present[item.get("id").asString()] = true
		}
		if len(items.arr) == 0 || int64(len(present)) >= count {
			break
		}
		page++
	}
	if len(present) == 0 {
		return nil, nil
	}
	return s.repo.deleteAbsent(operation.entityType, present)
}

// upsertEntity mirrors SyncService.upsert_entity (hook-triggered targeted sync).
func (s *syncService) upsertEntity(entityType, entityID string) (bool, error) {
	document, ok := syncFindDocuments[entityType]
	if !ok {
		return false, fmt.Errorf("unsupported entity type: %s", entityType)
	}
	data, err := graphqlQuery(s.clientURL, s.headers, document, jvObj(jvKey("id", jvStr(entityID))))
	if err != nil {
		return false, err
	}
	root := data.get(syncFindRoots[entityType])
	if root.kind != jObj {
		return false, fmt.Errorf("Stash did not return %s", syncFindRoots[entityType])
	}
	entity := adaptSyncEntity(syncEntityItemsKey(entityType), root)
	return s.repo.upsertEntity(entity)
}

func syncEntityItemsKey(entityType string) string {
	switch entityType {
	case "tag":
		return "tags"
	case "studio":
		return "studios"
	case "performer":
		return "performers"
	case "scene":
		return "scenes"
	}
	return ""
}

// deleteEntity mirrors SyncService.delete_entity.
func (s *syncService) deleteEntity(entityType, entityID string) error {
	if _, ok := syncFindDocuments[entityType]; !ok {
		return fmt.Errorf("unsupported entity type: %s", entityType)
	}
	return s.repo.deleteEntity(entityType, entityID)
}

// syncEntity mirrors SyncService._sync_entity: paginate one entity operation
// with the resume cursor, saving pages until the watermark is reached.
func (s *syncService) syncEntity(runID string, operation syncOperation, full bool, position, entityCount int) (int64, []string, error) {
	page, active, err := s.repo.prepareEntity(runID, operation.entityType, s.clockMs())
	if err != nil {
		return 0, nil, err
	}
	if !active {
		if s.progress != nil {
			s.progress(operation.entityType, 1, 1, position, entityCount)
		}
		return 0, nil, nil
	}
	baseline, _, err := s.repo.cursorWatermarks(operation.entityType)
	if err != nil {
		return 0, nil, err
	}
	processed := int64(0)
	ids := make([]string, 0)
	sortBy := operation.sort
	direction := "DESC"
	if full {
		sortBy = "id"
		direction = "ASC"
	}
	variables := jvObj()
	if operation.incrementalOnly {
		variables = syncPlayedSince(baseline)
	}
	for {
		variables.set("page", jvInt(page))
		variables.set("perPage", jvInt(s.pageSize))
		variables.set("sort", jvStr(sortBy))
		variables.set("direction", jvStr(direction))
		data, err := graphqlQuery(s.clientURL, s.headers, operation.document, variables)
		if err != nil {
			return 0, nil, err
		}
		root := data.get(operation.rootKey)
		total := pythonInt(root.get("count"))
		items := root.get(operation.itemsKey)
		adapted := make([]syncSourceEntity, 0, len(items.arr))
		timestamps := make([]string, 0)
		for _, item := range items.arr {
			entity := adaptSyncEntity(operation.itemsKey, item)
			if entity == nil {
				continue
			}
			adapted = append(adapted, entity)
			if watermark, ok := syncOperationWatermark(operation, entity); ok {
				timestamps = append(timestamps, watermark)
			}
		}
		pageHighWatermark := ""
		if len(timestamps) > 0 {
			pageHighWatermark = timestamps[0]
			for _, timestamp := range timestamps[1:] {
				if timestamp > pageHighWatermark {
					pageHighWatermark = timestamp
				}
			}
		}
		changed, err := s.repo.savePage(runID, operation.entityType, adapted,
			page+1, pageHighWatermark, s.clockMs(), full)
		if err != nil {
			return 0, nil, err
		}
		processed += int64(len(adapted))
		ids = append(ids, changed...)
		if s.progress != nil {
			s.progress(operation.entityType, minInt64(processed, total), total, position, entityCount)
		}
		reachedWatermark := false
		if !full && baseline != "" && len(timestamps) > 0 {
			minTimestamp := timestamps[0]
			for _, timestamp := range timestamps[1:] {
				if timestamp < minTimestamp {
					minTimestamp = timestamp
				}
			}
			reachedWatermark = minTimestamp <= baseline
		}
		exhausted := len(adapted) == 0 || page*s.pageSize >= total
		if reachedWatermark || exhausted {
			if err := s.repo.completeEntity(runID, operation.entityType, s.clockMs()); err != nil {
				return 0, nil, err
			}
			return processed, ids, nil
		}
		page++
	}
}

func syncOperationWatermark(operation syncOperation, entity syncSourceEntity) (string, bool) {
	if operation.itemsKey == "scenes" && operation.incrementalOnly {
		return syncLastPlayedAt(entity)
	}
	return entity.entityUpdatedAt()
}

// ── tiny helpers ──────────────────────────────────────────────────────────

func parseInt64(value string) (int64, error) {
	var parsed int64
	_, err := fmt.Sscanf(value, "%d", &parsed)
	return parsed, err
}

func int64ToString(value int64) string {
	return fmt.Sprintf("%d", value)
}
