// External links cache — a port of plugin/backend.py's _external_links read
// path: a state-hashed map of local entities to their StashDB ids, cached
// under application_meta while Stash reports an unchanged library. The cache
// row's JSON must match Python byte-for-byte (sorted state keys, insertion
// ordered links), so the differential harness can pin the cache write.
//
// Beyond Python, a changed state no longer forces a full library walk: the
// per-entity records behind the cache are patched with only the entities
// Stash reports as updated since the saved state (incrementalLinkRecords),
// falling back to the walk whenever the result could differ from one.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const externalLinksCacheKey = "external_links"

// externalLinkRecordsKey holds the per-entity records behind the links
// cache. It is a separate row so the external_links value stays
// byte-identical to Python's.
const externalLinkRecordsKey = "external_link_records"

// externalLinksState mirrors backend.py's _external_links_state: a compact
// JSON description of the linked library, with sorted keys exactly like
// json.dumps(sort_keys=True, separators=(",", ":")).
func externalLinksState(payload jVal) (string, error) {
	base, headers := stashConnection(payload)
	data, err := graphqlQuery(base, headers, externalLinksStateQuery,
		jvObj(jvKey("endpoint", jvStr(stashdbEndpoint))))
	if err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(`{"endpoint":`)
	b.WriteString(marshalJSONString(stashdbEndpoint))
	b.WriteString(`,"performers":`)
	writeLinksKindState(&b, data, "performers")
	b.WriteString(`,"scenes":`)
	writeLinksKindState(&b, data, "scenes")
	b.WriteString(`,"studios":`)
	writeLinksKindState(&b, data, "studios")
	b.WriteString(`}`)
	return b.String(), nil
}

// writeLinksKindState mirrors {kind: [int(count), str((items[:1] or
// [{}])[0].get("updated_at") or "")]}.
func writeLinksKindState(b *strings.Builder, data jVal, kind string) {
	collection := data.get(kind)
	count := pythonInt(collection.get("count"))
	items := collection.get(kind)
	updated := ""
	if items.kind == jArr && len(items.arr) > 0 {
		updated = pythonStrOrEmpty(items.arr[0].get("updated_at"))
	}
	b.WriteString(`[`)
	b.WriteString(strconv.FormatInt(count, 10))
	b.WriteString(`,`)
	b.WriteString(marshalJSONString(updated))
	b.WriteString(`]`)
}

// cachedExternalLinks mirrors backend.py's _cached_external_links: the
// cached links dict when the stored state matches, else nothing.
func cachedExternalLinks(db dbx, state string) (jVal, bool, error) {
	var raw string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, externalLinksCacheKey).Scan(&raw)
	if err == sql.ErrNoRows {
		return jvNull(), false, nil
	}
	if err != nil {
		return jvNull(), false, err
	}
	payload, err := parseJSON([]byte(raw))
	if err != nil {
		return jvNull(), false, nil // JSONDecodeError -> None
	}
	if state != "" && payload.get("state").asString() != state {
		return jvNull(), false, nil
	}
	links := payload.get("links")
	if links.kind == jObj {
		return links, true, nil
	}
	return jvNull(), false, nil
}

// externalLinks mirrors backend.py's _external_links: scan every linked
// entity for its StashDB id (and scene phashes), caching the result under
// application_meta when a connection is available. The result object has
// keys scenes, scene_ids, scene_phashes, performers, studios in that order,
// and each map's keys are inserted in scan order — the byte-identical cache
// row depends on that.
func externalLinks(payload jVal, db dbx) (jVal, error) {
	return externalLinksImpl(payload, db, false, nil)
}

// externalLinksRefresh mirrors _external_links with refresh=True: skip the
// cache read but still compute the state and write the cache row. progress,
// when non-nil, receives (processed, total) page ticks over the paginated
// walk (issue #110: the expand-refresh bar used to sit at 5% for the whole
// library walk).
func externalLinksRefresh(payload jVal, db dbx, progress func(processed, total int)) (jVal, error) {
	return externalLinksImpl(payload, db, true, progress)
}

// linkRecord is one entity the stash_id_endpoint filter returned: its
// StashDB id ("" when no stash_id matches the endpoint exactly) and, for
// scenes, its normalized file phashes in first-seen order.
type linkRecord struct {
	ID       string   `json:"i"`
	External string   `json:"e,omitempty"`
	Phashes  []string `json:"p,omitempty"`
}

// linkRecords is every linked entity per kind in ascending id order, saved
// beside the links cache under the library state it was read at. The links
// object is a pure function of it (buildExternalLinks), so a changed library
// can be patched with only the entities edited since that state.
type linkRecords struct {
	State      string       `json:"state"`
	Scenes     []linkRecord `json:"scenes"`
	Performers []linkRecord `json:"performers"`
	Studios    []linkRecord `json:"studios"`
}

var linkKinds = []string{"scenes", "performers", "studios"}

func (r *linkRecords) kind(kind string) *[]linkRecord {
	switch kind {
	case "scenes":
		return &r.Scenes
	case "performers":
		return &r.Performers
	default:
		return &r.Studios
	}
}

// linksPage is one externalLinksQuery (or externalLinksChangedQuery) page:
// each kind's records plus its reported count.
type linksPage struct {
	counts  map[string]int64
	records linkRecords
	err     error
}

func fetchLinksPage(base string, headers map[string]string, query string, variables jVal) linksPage {
	data, err := graphqlQuery(base, headers, query, variables)
	if err != nil {
		return linksPage{err: err}
	}
	result := linksPage{counts: map[string]int64{}}
	for _, kind := range linkKinds {
		collection := data.get(kind)
		result.counts[kind] = pythonInt(collection.get("count"))
		target := result.records.kind(kind)
		for _, row := range collection.get(kind).arr {
			*target = append(*target, parseLinkRow(kind, row))
		}
	}
	return result
}

func parseLinkRow(kind string, row jVal) linkRecord {
	record := linkRecord{ID: row.get("id").asString()}
	for _, item := range row.get("stash_ids").arr {
		if strings.EqualFold(strings.TrimRight(item.get("endpoint").asString(), "/"),
			strings.TrimRight(stashdbEndpoint, "/")) {
			record.External = item.get("stash_id").asString()
			break
		}
	}
	if kind == "scenes" {
		seen := map[string]bool{}
		for _, file := range row.get("files").arr {
			for _, fingerprint := range file.get("fingerprints").arr {
				if !strings.EqualFold(pythonStrOrEmpty(fingerprint.get("type")), "phash") {
					continue
				}
				if value, ok := normalizePhash(fingerprint.get("value")); ok && !seen[value] {
					seen[value] = true
					record.Phashes = append(record.Phashes, value)
				}
			}
		}
	}
	return record
}

// buildExternalLinks turns records into the links object exactly like the
// sequential id-ordered walk: per-kind maps keep the first position and the
// last value, scene_phashes keeps the first scene that reported a value.
func buildExternalLinks(records *linkRecords) jVal {
	scenes, sceneIDs, scenePhashes, performers, studios := jvObj(), jvObj(), jvObj(), jvObj(), jvObj()
	indexes := make([]map[string]int, 5)
	for i := range indexes {
		indexes[i] = make(map[string]int)
	}
	for _, record := range records.Scenes {
		if record.External != "" {
			putLink(&scenes, indexes[0], record.ID, jvStr(record.External), false)
			putLink(&sceneIDs, indexes[1], record.External, jvStr(record.ID), false)
		}
		for _, phash := range record.Phashes {
			putLink(&scenePhashes, indexes[2], phash, jvStr(record.ID), true)
		}
	}
	for _, record := range records.Performers {
		if record.External != "" {
			putLink(&performers, indexes[3], record.ID, jvStr(record.External), false)
		}
	}
	for _, record := range records.Studios {
		if record.External != "" {
			putLink(&studios, indexes[4], record.ID, jvStr(record.External), false)
		}
	}
	return jvObj(
		jvKey("scenes", scenes),
		jvKey("scene_ids", sceneIDs),
		jvKey("scene_phashes", scenePhashes),
		jvKey("performers", performers),
		jvKey("studios", studios),
	)
}

func putLink(target *jVal, index map[string]int, key string, val jVal, keepFirst bool) {
	if position, exists := index[key]; exists {
		if !keepFirst {
			target.obj[position].val = val
		}
		return
	}
	index[key] = len(target.obj)
	target.obj = append(target.obj, jPair{key: key, val: val})
}

func externalLinksImpl(payload jVal, db dbx, refresh bool, progress func(processed, total int)) (jVal, error) {
	state := ""
	var err error
	base, headers := stashConnection(payload)
	if db != nil {
		state, err = externalLinksState(payload)
		if err != nil {
			return jvNull(), err
		}
		if !refresh {
			// Reuse the last scan while the linked library is unchanged: the
			// saved state is compared against the current one, and a mismatch
			// falls through so newly-linked entities appear.
			if cached, ok, err := cachedExternalLinks(db, state); err != nil {
				return jvNull(), err
			} else if ok {
				return cached, nil
			}
			// One edited entity changes the state; patch the saved records
			// with only the entities edited since then instead of walking
			// the whole library inside an interactive request.
			records, ok, err := incrementalLinkRecords(base, headers, db, state)
			if err != nil {
				return jvNull(), err
			}
			if ok {
				return saveExternalLinks(db, records)
			}
		}
	}
	records, err := walkLinkRecords(base, headers, progress)
	if err != nil {
		return jvNull(), err
	}
	if db == nil {
		return buildExternalLinks(records), nil
	}
	records.State = state
	return saveExternalLinks(db, records)
}

// walkLinkRecords reads every linked entity. Page 1 is fetched synchronously:
// its counts fix the page set (the fetchParallel pattern). The remaining
// pages run over a bounded worker pool and are concatenated in page order,
// so the records keep Stash's ascending id order.
func walkLinkRecords(base string, headers map[string]string, progress func(processed, total int)) (*linkRecords, error) {
	const pageSize = int64(500)
	variables := func(page int64) jVal {
		return jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(pageSize)),
			jvKey("endpoint", jvStr(stashdbEndpoint)))
	}
	first := fetchLinksPage(base, headers, externalLinksQuery, variables(1))
	if first.err != nil {
		return nil, first.err
	}
	total := int64(0)
	for _, kind := range linkKinds {
		if count := first.counts[kind]; count > total {
			total = count
		}
	}
	pagesNeeded := (total + pageSize - 1) / pageSize
	if pagesNeeded < 1 {
		pagesNeeded = 1
	}
	pages := make([]linksPage, pagesNeeded)
	pages[0] = first
	if pagesNeeded > 1 {
		workers := nthreads(0)
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
					pages[p-1] = fetchLinksPage(base, headers, externalLinksQuery, variables(p))
				}
			}()
		}
		for p := int64(2); p <= pagesNeeded; p++ {
			pageCh <- p
		}
		close(pageCh)
		wg.Wait()
	}
	records := &linkRecords{}
	for index, page := range pages {
		if page.err != nil {
			return nil, page.err
		}
		for _, kind := range linkKinds {
			*records.kind(kind) = append(*records.kind(kind), *page.records.kind(kind)...)
		}
		if progress != nil {
			processed := int64(index+1) * pageSize
			if processed > total {
				processed = total
			}
			progress(int(processed), int(total))
		}
	}
	return records, nil
}

// maxIncrementalLinkPages bounds the incremental patch; a larger edit (a
// bulk scrape or identify run) is cheaper to re-walk in parallel.
const maxIncrementalLinkPages = 4

// incrementalLinkRecords patches the saved records up to state. It reports
// false whenever the result could differ from a full walk: no saved records,
// an unparseable state, too many edits, or a per-kind record count that no
// longer matches Stash's count. Deleted and unlinked entities only show up
// as a count mismatch, so they always fall back to the walk.
func incrementalLinkRecords(base string, headers map[string]string, db dbx, state string) (*linkRecords, bool, error) {
	var raw string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, externalLinkRecordsKey).Scan(&raw)
	if err == sql.ErrNoRows {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	var records linkRecords
	if json.Unmarshal([]byte(raw), &records) != nil || records.State == "" {
		return nil, false, nil
	}
	previous, err1 := parseJSON([]byte(records.State))
	current, err2 := parseJSON([]byte(state))
	if err1 != nil || err2 != nil {
		return nil, false, nil
	}
	variables := jvObj(jvKey("perPage", jvInt(500)), jvKey("endpoint", jvStr(stashdbEndpoint)))
	for _, kind := range linkKinds {
		before, after := previous.get(kind), current.get(kind)
		if len(before.arr) != 2 || len(after.arr) != 2 {
			return nil, false, nil
		}
		since := after.arr[1].asString() // nothing is newer: unchanged kind
		if !deepEqual(before, after) {
			updated := before.arr[1].asString()
			if updated == "" {
				since = "1970-01-01T00:00:00Z"
			} else {
				// GREATER_THAN is strict at one-second resolution; re-read the
				// boundary second so a same-second edit is not missed.
				parsed, err := time.Parse(time.RFC3339, updated)
				if err != nil {
					return nil, false, nil
				}
				since = parsed.Add(-time.Second).UTC().Format(time.RFC3339)
			}
		}
		variables.set(strings.TrimSuffix(kind, "s")+"Since", jvStr(since))
	}
	changed := linkRecords{}
	for page := int64(1); ; page++ {
		variables.set("page", jvInt(page))
		result := fetchLinksPage(base, headers, externalLinksChangedQuery, variables)
		if result.err != nil {
			return nil, false, result.err
		}
		more := false
		for _, kind := range linkKinds {
			*changed.kind(kind) = append(*changed.kind(kind), *result.records.kind(kind)...)
			if result.counts[kind] > int64(len(*changed.kind(kind))) && len(*result.records.kind(kind)) > 0 {
				more = true
			}
		}
		if !more {
			break
		}
		if page >= maxIncrementalLinkPages {
			return nil, false, nil
		}
	}
	for _, kind := range linkKinds {
		target := records.kind(kind)
		*target = mergeLinkRecords(*target, *changed.kind(kind))
		if int64(len(*target)) != pythonInt(current.get(kind).arr[0]) {
			return nil, false, nil
		}
	}
	records.State = state
	return &records, true, nil
}

// mergeLinkRecords replaces or adds each changed record and restores
// Stash's ascending numeric id order.
func mergeLinkRecords(records, changed []linkRecord) []linkRecord {
	if len(changed) == 0 {
		return records
	}
	index := make(map[string]int, len(records))
	for i, record := range records {
		index[record.ID] = i
	}
	for _, record := range changed {
		if i, ok := index[record.ID]; ok {
			records[i] = record
		} else {
			index[record.ID] = len(records)
			records = append(records, record)
		}
	}
	sort.SliceStable(records, func(i, j int) bool {
		a, errA := strconv.ParseInt(records[i].ID, 10, 64)
		b, errB := strconv.ParseInt(records[j].ID, 10, 64)
		if errA != nil || errB != nil {
			return records[i].ID < records[j].ID
		}
		return a < b
	})
	return records
}

// saveExternalLinks builds the links object and stores it with its records
// in one transaction, so the two rows always describe the same state.
func saveExternalLinks(db dbx, records *linkRecords) (jVal, error) {
	result := buildExternalLinks(records)
	encoded, err := json.Marshal(records)
	if err != nil {
		return jvNull(), err
	}
	cacheValue := jvObj(jvKey("state", jvStr(records.State)), jvKey("links", result))
	err = withTxn(db, func(conn *sql.Conn) error {
		const upsert = `INSERT INTO application_meta(key, value) VALUES (?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`
		if _, err := conn.ExecContext(context.Background(), upsert,
			externalLinksCacheKey, cacheValue.marshalCompact()); err != nil {
			return err
		}
		_, err := conn.ExecContext(context.Background(), upsert, externalLinkRecordsKey, string(encoded))
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	return result, nil
}

// normalizePhash mirrors curator/expand.py's normalize_phash: exactly 16 hex
// digits, casefolded.
func normalizePhash(value jVal) (string, bool) {
	normalized := strings.ToLower(strings.TrimSpace(pythonStrOrEmpty(value)))
	if len(normalized) != 16 {
		return "", false
	}
	if _, err := strconv.ParseUint(normalized, 16, 64); err != nil {
		return "", false
	}
	return normalized, true
}
