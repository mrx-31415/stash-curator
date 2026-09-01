// External links cache — a port of plugin/backend.py's _external_links read
// path: a state-hashed map of local entities to their StashDB ids, cached
// under application_meta while Stash reports an unchanged library. The cache
// row's JSON must match Python byte-for-byte (sorted state keys, insertion
// ordered links), so the differential harness can pin the cache write.
package main

import (
	"database/sql"
	"strconv"
	"strings"
	"sync"
)

const externalLinksCacheKey = "external_links"

// externalLinksState mirrors backend.py's _external_links_state: a compact
// JSON description of the linked library, with sorted keys exactly like
// json.dumps(sort_keys=True, separators=(",", ":")).
func externalLinksState(payload jVal) (string, error) {
	base, headers := stashConnection(payload)
	data, err := graphqlQuery(base, headers, externalLinksStateQuery, jvNull())
	if err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(`{"performers":`)
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

// linksPage is one externalLinksQuery page: the per-kind id->external maps
// plus each collection's reported count (page 1's counts fix the page set).
type linksPage struct {
	page         int64
	counts       map[string]int64
	scenes       jVal
	sceneIDs     jVal
	scenePhashes jVal
	performers   jVal
	studios      jVal
	err          error
}

// fetchLinksPage executes one externalLinksQuery page, merging each kind's
// stash_id matches and scene phashes exactly like the sequential walk's
// per-page body.
func fetchLinksPage(base string, headers map[string]string, page int64) linksPage {
	data, err := graphqlQuery(base, headers, externalLinksQuery,
		jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(500))))
	if err != nil {
		return linksPage{page: page, err: err}
	}
	result := linksPage{
		page:         page,
		counts:       map[string]int64{},
		scenes:       jvObj(),
		sceneIDs:     jvObj(),
		scenePhashes: jvObj(),
		performers:   jvObj(),
		studios:      jvObj(),
	}
	for _, kind := range []string{"scenes", "performers", "studios"} {
		collection := data.get(kind)
		result.counts[kind] = pythonInt(collection.get("count"))
		rows := collection.get(kind)
		var target *jVal
		switch kind {
		case "scenes":
			target = &result.scenes
		case "performers":
			target = &result.performers
		default:
			target = &result.studios
		}
		for _, row := range rows.arr {
			external := ""
			for _, item := range row.get("stash_ids").arr {
				if strings.EqualFold(strings.TrimRight(item.get("endpoint").asString(), "/"),
					strings.TrimRight(stashdbEndpoint, "/")) {
					external = item.get("stash_id").asString()
					break
				}
			}
			if external != "" {
				id := row.get("id").asString()
				target.set(id, jvStr(external))
				if kind == "scenes" {
					result.sceneIDs.set(external, jvStr(id))
				}
			}
			if kind == "scenes" {
				for _, file := range row.get("files").arr {
					for _, fingerprint := range file.get("fingerprints").arr {
						if !strings.EqualFold(pythonStrOrEmpty(fingerprint.get("type")), "phash") {
							continue
						}
						if value, ok := normalizePhash(fingerprint.get("value")); ok {
							if !result.scenePhashes.has(value) { // setdefault
								result.scenePhashes.set(value, jvStr(row.get("id").asString()))
							}
						}
					}
				}
			}
		}
	}
	return result
}

func externalLinksImpl(payload jVal, db dbx, refresh bool, progress func(processed, total int)) (jVal, error) {
	state := ""
	var err error
	if db != nil {
		state, err = externalLinksState(payload)
		if err != nil {
			return jvNull(), err
		}
		if !refresh {
			// Reuse the last scan while the linked library is unchanged: the
			// saved state is compared against the current one, and a mismatch
			// falls through to the walk so newly-linked entities appear.
			if cached, ok, err := cachedExternalLinks(db, state); err != nil {
				return jvNull(), err
			} else if ok {
				return cached, nil
			}
		}
	}
	base, headers := stashConnection(payload)
	// Page 1 is fetched synchronously: its counts fix the page set (the
	// fetchParallel pattern). The remaining pages run over a bounded worker
	// pool and merge in page order, so the aggregate is identical to the
	// sequential loop (scene_phashes keeps first-seen semantics).
	const pageSize = int64(500)
	first := fetchLinksPage(base, headers, 1)
	if first.err != nil {
		return jvNull(), first.err
	}
	total := int64(0)
	for _, kind := range []string{"scenes", "performers", "studios"} {
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
					pages[p-1] = fetchLinksPage(base, headers, p)
				}
			}()
		}
		for p := int64(2); p <= pagesNeeded; p++ {
			pageCh <- p
		}
		close(pageCh)
		wg.Wait()
	}
	scenes := jvObj()
	sceneIDs := jvObj()
	scenePhashes := jvObj()
	performers := jvObj()
	studios := jvObj()
	for index, page := range pages {
		if page.err != nil {
			return jvNull(), page.err
		}
		// Merge in page order: per-kind maps take the last seen id mapping,
		// scene_phashes keeps the first page that reported the value.
		for _, pair := range page.scenes.obj {
			scenes.set(pair.key, pair.val)
		}
		for _, pair := range page.sceneIDs.obj {
			sceneIDs.set(pair.key, pair.val)
		}
		for _, pair := range page.scenePhashes.obj {
			if !scenePhashes.has(pair.key) {
				scenePhashes.set(pair.key, pair.val)
			}
		}
		for _, pair := range page.performers.obj {
			performers.set(pair.key, pair.val)
		}
		for _, pair := range page.studios.obj {
			studios.set(pair.key, pair.val)
		}
		if progress != nil {
			processed := int64(index+1) * pageSize
			if processed > total {
				processed = total
			}
			progress(int(processed), int(total))
		}
	}
	result := jvObj(
		jvKey("scenes", scenes),
		jvKey("scene_ids", sceneIDs),
		jvKey("scene_phashes", scenePhashes),
		jvKey("performers", performers),
		jvKey("studios", studios),
	)
	if db != nil {
		cacheValue := jvObj(jvKey("state", jvStr(state)), jvKey("links", result))
		if err := execImmediate(db,
			`INSERT INTO application_meta(key, value) VALUES (?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`,
			externalLinksCacheKey, cacheValue.marshalCompact()); err != nil {
			return jvNull(), err
		}
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
