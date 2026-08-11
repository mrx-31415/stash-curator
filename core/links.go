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
	if payload.get("state").asString() != state {
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
	state := ""
	var err error
	if db != nil {
		state, err = externalLinksState(payload)
		if err != nil {
			return jvNull(), err
		}
		if cached, ok, err := cachedExternalLinks(db, state); err != nil {
			return jvNull(), err
		} else if ok {
			return cached, nil
		}
	}
	scenes := jvObj()
	sceneIDs := jvObj()
	scenePhashes := jvObj()
	performers := jvObj()
	studios := jvObj()
	base, headers := stashConnection(payload)
	page := int64(1)
	for {
		data, err := graphqlQuery(base, headers, externalLinksQuery,
			jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(500))))
		if err != nil {
			return jvNull(), err
		}
		more := false
		for _, kind := range []string{"scenes", "performers", "studios"} {
			collection := data.get(kind)
			rows := collection.get(kind)
			var target *jVal
			switch kind {
			case "scenes":
				target = &scenes
			case "performers":
				target = &performers
			default:
				target = &studios
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
						sceneIDs.set(external, jvStr(id))
					}
				}
				if kind == "scenes" {
					for _, file := range row.get("files").arr {
						for _, fingerprint := range file.get("fingerprints").arr {
							if !strings.EqualFold(pythonStrOrEmpty(fingerprint.get("type")), "phash") {
								continue
							}
							if value, ok := normalizePhash(fingerprint.get("value")); ok {
								if !scenePhashes.has(value) { // setdefault
									scenePhashes.set(value, jvStr(row.get("id").asString()))
								}
							}
						}
					}
				}
			}
			if page*500 < pythonInt(collection.get("count")) {
				more = true
			}
		}
		if !more {
			break
		}
		page++
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
