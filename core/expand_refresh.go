// Expand refresh — a port of backend.py's expand-refresh task mode and
// curator/expand.py's ExpandService.refresh, including the taxonomy
// refresh/publish side (curator/taxonomy/store.py + stashdb.py) it depends
// on. The candidate fetch reuses the network-layer fetch machinery
// (fetchScenes) and scoring (expandService.score).
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed stashdb_category_roles.json
var categoryRolesJSON []byte

// categoryRoles is the parsed stashdb_category_roles.json resource: the
// default role plus the category-id → role map (taxonomy.store's
// STASHDB_CATEGORY_ROLES / DEFAULT_CATEGORY_ROLE).
var categoryRoles = struct {
	defaultRole string
	roles       map[string]string
}{}

func init() {
	parsed, err := parseJSON(categoryRolesJSON)
	if err != nil {
		panic("core: invalid embedded stashdb_category_roles.json: " + err.Error())
	}
	categoryRoles.defaultRole = parsed.get("default_role").asString()
	categoryRoles.roles = map[string]string{}
	for _, item := range parsed.get("categories").arr {
		categoryRoles.roles[item.get("id").asString()] = item.get("role").asString()
	}
}

// categoryRoleFingerprint mirrors taxonomy.store.CATEGORY_ROLE_FINGERPRINT:
// sha256 of the resource bytes.
func categoryRoleFingerprint() string {
	digest := sha256.Sum256(categoryRolesJSON)
	return hex.EncodeToString(digest[:])
}

// Taxonomy query documents, byte-identical to curator/taxonomy/stashdb.py.
const taxonomyCategoriesQuery = `
query CuratorTagCategories {
  queryTagCategories {
    count
    tag_categories { id name group description }
  }
}
`
const taxonomyTagsQuery = `
query CuratorTaxonomyTags($page: Int!, $perPage: Int!) {
  queryTags(input: {page: $page, per_page: $perPage, sort: NAME, direction: ASC}) {
    count
    tags { id name aliases category { id } }
  }
}
`

type taxonomyCategory struct {
	categoryID  string
	name        string
	group       string
	description string // "" = None
}

type taxonomyTag struct {
	tagID      string
	name       string
	aliases    []string
	categoryID string // "" = None
}

// taxonomyFetch mirrors StashDBTaxonomyClient.fetch: categories then
// paginated tags, sorted deterministically.
func taxonomyFetch(clientURL, apiKey string) ([]taxonomyCategory, []taxonomyTag, error) {
	data, err := stashdbQuery(clientURL, apiKey, taxonomyCategoriesQuery, jvNull())
	if err != nil {
		return nil, nil, err
	}
	categoryRows := data.get("queryTagCategories").get("tag_categories")
	var categories []taxonomyCategory
	for _, row := range categoryRows.arr {
		description := ""
		if row.get("description").truthy() {
			description = row.get("description").asString()
		}
		categories = append(categories, taxonomyCategory{
			categoryID:  row.get("id").asString(),
			name:        row.get("name").asString(),
			group:       row.get("group").asString(),
			description: description,
		})
	}
	sort.SliceStable(categories, func(i, j int) bool {
		return categories[i].categoryID < categories[j].categoryID
	})
	var tags []taxonomyTag
	page := int64(1)
	total := int64(0)
	for {
		data, err := stashdbQuery(clientURL, apiKey, taxonomyTagsQuery,
			jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(500))))
		if err != nil {
			return nil, nil, err
		}
		tagsData := data.get("queryTags")
		rawTags := tagsData.get("tags")
		total = pythonInt(tagsData.get("count"))
		for _, raw := range rawTags.arr {
			categoryID := ""
			if raw.get("category").kind == jObj {
				categoryID = raw.get("category").get("id").asString()
			}
			aliasSet := map[string]bool{}
			for _, alias := range raw.get("aliases").arr {
				trimmed := strings.TrimSpace(alias.asString())
				if trimmed != "" {
					aliasSet[trimmed] = true
				}
			}
			aliases := make([]string, 0, len(aliasSet))
			for alias := range aliasSet {
				aliases = append(aliases, alias)
			}
			sort.SliceStable(aliases, func(i, j int) bool {
				return strings.ToLower(aliases[i]) < strings.ToLower(aliases[j])
			})
			tags = append(tags, taxonomyTag{
				tagID:      raw.get("id").asString(),
				name:       raw.get("name").asString(),
				aliases:    aliases,
				categoryID: categoryID,
			})
		}
		if len(rawTags.arr) == 0 || int64(len(tags)) >= total {
			break
		}
		page++
	}
	sort.SliceStable(tags, func(i, j int) bool { return tags[i].tagID < tags[j].tagID })
	return categories, tags, nil
}

// taxonomyStorePublish mirrors TaxonomyStore.publish: the snapshot rows and
// the active snapshot id in application_meta.
func taxonomyStorePublish(db dbx, endpoint string, categories []taxonomyCategory, tags []taxonomyTag, fetchedAtMs int64) (snapshotID string, reused bool, err error) {
	canonical := taxonomyDataCanonical(endpoint, categories, tags)
	digest := sha256.Sum256([]byte(canonical))
	snapshotID = fmt.Sprintf("tax-%s", hex.EncodeToString(digest[:])[:20])
	var one int
	err = db.QueryRow(`SELECT 1 FROM taxonomy_snapshot WHERE snapshot_id=?`, snapshotID).Scan(&one)
	reused = err == nil
	if err != nil && err != sql.ErrNoRows {
		return "", false, err
	}
	txnErr := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO taxonomy_snapshot(
    snapshot_id, endpoint, fetched_at_ms, category_count, tag_count
) VALUES (?, ?, ?, ?, ?)`,
			snapshotID, endpoint, fetchedAtMs, len(categories), len(tags)); err != nil {
			return err
		}
		if !reused {
			for _, item := range categories {
				description := any(nil)
				if item.description != "" {
					description = item.description
				}
				if _, err := conn.ExecContext(ctx, `
INSERT INTO taxonomy_category(
    snapshot_id, category_id, name, group_name, description
) VALUES (?, ?, ?, ?, ?)`,
					snapshotID, item.categoryID, item.name, item.group, description); err != nil {
					return err
				}
			}
			for _, item := range tags {
				categoryID := any(nil)
				if item.categoryID != "" {
					categoryID = item.categoryID
				}
				if _, err := conn.ExecContext(ctx, `
INSERT INTO taxonomy_tag(snapshot_id, tag_id, name, category_id)
VALUES (?, ?, ?, ?)`, snapshotID, item.tagID, item.name, categoryID); err != nil {
					return err
				}
				for _, alias := range item.aliases {
					if _, err := conn.ExecContext(ctx, `
INSERT INTO taxonomy_tag_alias(snapshot_id, tag_id, alias)
VALUES (?, ?, ?)`, snapshotID, item.tagID, alias); err != nil {
						return err
					}
				}
			}
		}
		_, err := conn.ExecContext(ctx, `
INSERT INTO application_meta(key, value) VALUES ('taxonomy_snapshot_id', ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, snapshotID)
		return err
	})
	if txnErr != nil {
		return "", false, txnErr
	}
	return snapshotID, reused, nil
}

// taxonomyDataCanonical mirrors json.dumps(asdict(TaxonomyData),
// sort_keys=True, separators=(",", ":")).
func taxonomyDataCanonical(endpoint string, categories []taxonomyCategory, tags []taxonomyTag) string {
	cats := jvArr()
	for _, item := range categories {
		description := jvNull()
		if item.description != "" {
			description = jvStr(item.description)
		}
		cats.arr = append(cats.arr, jvObj(
			jvKey("category_id", jvStr(item.categoryID)),
			jvKey("description", description),
			jvKey("group", jvStr(item.group)),
			jvKey("name", jvStr(item.name)),
		))
	}
	tagRows := jvArr()
	for _, item := range tags {
		aliases := jvArr()
		for _, alias := range item.aliases {
			aliases.arr = append(aliases.arr, jvStr(alias))
		}
		categoryID := jvNull()
		if item.categoryID != "" {
			categoryID = jvStr(item.categoryID)
		}
		tagRows.arr = append(tagRows.arr, jvObj(
			jvKey("aliases", aliases),
			jvKey("category_id", categoryID),
			jvKey("name", jvStr(item.name)),
			jvKey("tag_id", jvStr(item.tagID)),
		))
	}
	doc := jvObj(
		jvKey("categories", cats),
		jvKey("endpoint", jvStr(endpoint)),
		jvKey("tags", tagRows),
	)
	return doc.marshalSortedKeys()
}

// taxonomyStorePublish mirrors TaxonomyStore.publish: the snapshot rows and
// the active snapshot id in application_meta.
// refreshTaxonomy mirrors ExpandService._refresh_taxonomy.
func refreshTaxonomy(db dbx, clientURL, apiKey string, nowMs int64) (bool, error) {
	var checked sql.NullString
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='taxonomy_checked_at_ms'`).Scan(&checked)
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	lastChecked := int64(0)
	if checked.Valid {
		lastChecked, _ = parseInt64(checked.String)
	}
	if lastChecked == 0 {
		var fetched sql.NullInt64
		err := db.QueryRow(`
SELECT s.fetched_at_ms FROM application_meta m
JOIN taxonomy_snapshot s ON s.snapshot_id=m.value
WHERE m.key='taxonomy_snapshot_id'`).Scan(&fetched)
		if err == nil && fetched.Valid {
			lastChecked = fetched.Int64
		}
	}
	if nowMs-lastChecked < 30*86_400_000 {
		return false, nil
	}
	categories, tags, err := taxonomyFetch(clientURL, apiKey)
	if err != nil {
		return false, nil
	}
	endpoint := clientURL
	snapshotID, reused, err := taxonomyStorePublish(db, endpoint, categories, tags, nowMs)
	if err != nil {
		return false, err
	}
	_ = snapshotID
	if err := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(), `
INSERT INTO application_meta(key, value) VALUES ('taxonomy_checked_at_ms', ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, fmt.Sprintf("%d", nowMs))
		return err
	}); err != nil {
		return false, err
	}
	if !reused {
		if err := withTxn(db, func(conn *sql.Conn) error {
			return coordinatorRequest(conn, "taxonomy_sync", nowMs)
		}); err != nil {
			return false, err
		}
	}
	return !reused, nil
}

// supportsIncrementalFetch mirrors ExpandService._supports_incremental_fetch.
func supportsIncrementalFetch(clientURL, apiKey string) bool {
	probe := jvObj(
		jvKey("page", jvInt(1)),
		jvKey("per_page", jvInt(1)),
		jvKey("sort", jvStr("UPDATED_AT")),
		jvKey("direction", jvStr("DESC")),
		jvKey("updated_at", jvObj(
			jvKey("value", jvStr("1970-01-01T00:00:00Z")),
			jvKey("modifier", jvStr("GREATER_THAN")),
		)),
	)
	_, err := stashdbQuery(clientURL, apiKey, stashdbScenesQuery, jvObj(jvKey("input", probe)))
	return err == nil
}

// recentScene mirrors ExpandService._recent: release_date or production_date
// missing/invalid is recent; else >= cutoff.
func recentScene(scene jVal, cutoff string) bool {
	raw := scene.get("release_date")
	if raw.kind == jNull || raw.asString() == "" {
		raw = scene.get("production_date")
	}
	if raw.kind == jNull || raw.asString() == "" {
		return true
	}
	value := raw.asString()
	t, err := time.Parse("2006-01-02", value)
	if err != nil {
		return true
	}
	cutoffDate, err := time.Parse("2006-01-02", cutoff)
	if err != nil {
		return true
	}
	return !t.Before(cutoffDate)
}

// refreshSeeds mirrors ExpandService._seeds.
func refreshSeeds(s *expandService, clientURL, apiKey, modelID, featureVersion string, links jVal,
	similarTopK, similarPerFavorite int, gender, ethnicity string, timings map[string]int64) (jVal, error) {
	topRows, err := s.db.Query(`
SELECT scene_id FROM model_scene_score WHERE model_id=?
ORDER BY appeal * confidence DESC LIMIT 500`, modelID)
	if err != nil {
		return jvNull(), err
	}
	var top []string
	for topRows.Next() {
		var sceneID string
		if err := topRows.Scan(&sceneID); err != nil {
			topRows.Close()
			return jvNull(), err
		}
		top = append(top, sceneID)
	}
	topRows.Close()
	if err := topRows.Err(); err != nil {
		return jvNull(), err
	}
	evidence, _, err := s.performerEvidence(modelID, links)
	if err != nil {
		return jvNull(), err
	}
	externalIDs := make([]string, 0, len(evidence))
	for externalID := range evidence {
		externalIDs = append(externalIDs, externalID)
	}
	sort.SliceStable(externalIDs, func(i, j int) bool {
		a, b := evidence[externalIDs[i]], evidence[externalIDs[j]]
		if a.strength != b.strength {
			return a.strength > b.strength
		}
		return externalIDs[i] < externalIDs[j]
	})
	basePerformers := make([]string, 0, len(externalIDs))
	for _, externalID := range externalIDs {
		if evidence[externalID].strength > 0 {
			basePerformers = append(basePerformers, externalID)
		}
	}
	expandedPerformers := expandSimilarPerformers(s, clientURL, apiKey, basePerformers, evidence,
		featureVersion, similarTopK, similarPerFavorite, gender, ethnicity, timings)
	performers := jvArr()
	for _, externalID := range expandedPerformers {
		performers.arr = append(performers.arr, jvStr(externalID))
	}
	playedRows, err := s.db.Query(`
SELECT scene_id FROM source_scene ORDER BY play_count DESC, updated_at DESC LIMIT 200`)
	if err != nil {
		return jvNull(), err
	}
	var played []string
	for playedRows.Next() {
		var sceneID string
		if err := playedRows.Scan(&sceneID); err != nil {
			playedRows.Close()
			return jvNull(), err
		}
		played = append(played, sceneID)
	}
	playedRows.Close()
	if err := playedRows.Err(); err != nil {
		return jvNull(), err
	}
	studioScope := dedupe(append(append([]string(nil), top...), played...))
	studioSet := map[string]bool{}
	if len(studioScope) > 0 {
		placeholders := strings.TrimSuffix(strings.Repeat("?,", len(studioScope)), ",")
		args := make([]any, len(studioScope))
		for i, id := range studioScope {
			args[i] = id
		}
		rows, err := s.db.Query(fmt.Sprintf(
			`SELECT DISTINCT studio_id FROM source_scene WHERE scene_id IN (%s) AND studio_id IS NOT NULL`,
			placeholders), args...)
		if err != nil {
			return jvNull(), err
		}
		studios := links.get("studios")
		localStudioByExternal := make(map[string]string, len(studios.obj))
		for _, pair := range studios.obj {
			localStudioByExternal[pair.key] = pair.val.asString()
		}
		for rows.Next() {
			var studioID string
			if err := rows.Scan(&studioID); err != nil {
				rows.Close()
				return jvNull(), err
			}
			if externalID, ok := localStudioByExternal[studioID]; ok {
				studioSet[externalID] = true
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return jvNull(), err
		}
	}
	sortedStudios := make([]string, 0, len(studioSet))
	for id := range studioSet {
		sortedStudios = append(sortedStudios, id)
	}
	sort.Strings(sortedStudios)
	if len(sortedStudios) > 60 {
		sortedStudios = sortedStudios[:60]
	}
	studiosArr := jvArr()
	for _, id := range sortedStudios {
		studiosArr.arr = append(studiosArr.arr, jvStr(id))
	}
	localTagsRows, err := s.db.Query(`
SELECT d.name FROM feature_affinity a
JOIN feature_definition d USING(feature_id)
WHERE a.model_id=? AND d.feature_version=? AND d.family='content'
  AND a.affinity > 0
ORDER BY a.affinity * a.confidence DESC LIMIT 50`, modelID, featureVersion)
	if err != nil {
		return jvNull(), err
	}
	var localTags []string
	for localTagsRows.Next() {
		var name string
		if err := localTagsRows.Scan(&name); err != nil {
			localTagsRows.Close()
			return jvNull(), err
		}
		localTags = append(localTags, strings.TrimPrefix(name, "tag:"))
	}
	localTagsRows.Close()
	if err := localTagsRows.Err(); err != nil {
		return jvNull(), err
	}
	directRows, err := s.db.Query(`SELECT tag_id FROM direct_tag_preference WHERE value > 0 ORDER BY value DESC, tag_id`)
	if err != nil {
		return jvNull(), err
	}
	var directTags []string
	for directRows.Next() {
		var tagID string
		if err := directRows.Scan(&tagID); err != nil {
			directRows.Close()
			return jvNull(), err
		}
		directTags = append(directTags, tagID)
	}
	directRows.Close()
	if err := directRows.Err(); err != nil {
		return jvNull(), err
	}
	merged := make([]string, 0, len(directTags)+len(localTags))
	seen := map[string]bool{}
	for _, id := range append(append([]string(nil), directTags...), localTags...) {
		if !seen[id] {
			seen[id] = true
			merged = append(merged, id)
		}
	}
	localSet := map[string]bool{}
	for _, id := range merged {
		localSet[id] = true
	}
	resolved, err := s.externalTagIDs(localSet)
	if err != nil {
		return jvNull(), err
	}
	tagsArr := jvArr()
	for _, id := range merged {
		if externalID, ok := resolved[id]; ok {
			tagsArr.arr = append(tagsArr.arr, jvStr(externalID))
			if len(tagsArr.arr) >= 50 {
				break
			}
		}
	}
	return jvObj(
		jvKey("performers", performers),
		jvKey("studios", studiosArr),
		jvKey("tags", tagsArr),
	), nil
}

// expandSimilarPerformers mirrors ExpandService._expand_similar_performers:
// chase the strongest favourites into StashDB and pull their closest look-alikes so
// the seed set reaches performers the model has affinity for but has not seen.
// Best-effort: any failure degrades to the base seed set.
func expandSimilarPerformers(s *expandService, clientURL, apiKey string, base []string,
	evidence map[string]*performerEvidence, featureVersion string, topK, perFavorite int,
	gender, ethnicity string, timings map[string]int64) []string {
	if topK <= 0 || perFavorite <= 0 || len(base) == 0 {
		return base
	}
	weights := performerBlockWeightsMap()
	recorded := time.Now().Format("2006-01-02")
	ids := make([]string, 0, len(evidence))
	for id := range evidence {
		ids = append(ids, id)
	}
	sort.SliceStable(ids, func(i, j int) bool {
		a, b := evidence[ids[i]], evidence[ids[j]]
		if a.strength != b.strength {
			return a.strength > b.strength
		}
		return ids[i] < ids[j]
	})
	// Only the top_k favourites are used as chase targets, so load just their
	// profiles (performerProfilesForIDs) instead of every performer profile in
	// the model — the all-profiles load is the serial bottleneck of the seeds
	// phase on large libraries.
	limit := topK
	if limit > len(ids) {
		limit = len(ids)
	}
	favouriteIDs := make(map[string]bool, limit)
	for i := range limit {
		favouriteIDs[evidence[ids[i]].localID] = true
	}
	t0 := time.Now()
	profiles, err := performerProfilesForIDs(s.db, featureVersion, favouriteIDs)
	if err != nil || len(profiles) == 0 {
		return base
	}
	timings["seeds_profiles"] = time.Since(t0).Milliseconds()
	type scoredPerformer struct {
		sim float64
		id  string
	}
	type chaseResult struct {
		scored []scoredPerformer
	}
	results := make([]chaseResult, limit)
	var networkMs, matchMs, calls int64
	// Fetch the shared popularity recall floor once (it is identical across all
	// favorites), then union each favorite's co-star/age pools against it. This
	// removes the redundant per-favorite base fetch, the largest query of the
	// chase. The base pool is the same list every favorite would have fetched,
	// so the per-target union (and thus the seed set) is unchanged.
	tBase := time.Now()
	sharedBase := fetchBasePerformerPool(clientURL, apiKey, gender, ethnicity)
	timings["seeds_chase_base"] = time.Since(tBase).Milliseconds()
	// Fetch each favorite's StashDB pool and score it in parallel (bounded by
	// the same worker count the scene probes use), then merge in the same seed
	// order as the sequential path so the additions (and thus scene_count /
	// performer_count) stay byte-identical to the Python oracle. Only the
	// independent per-favorite work runs concurrently — the dedup merge below
	// is sequential, so cross-favorite ordering is deterministic.
	workers := min(8, limit)
	if workers < 1 {
		workers = 1
	}
	workCh := make(chan int)
	var wg sync.WaitGroup
	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for idx := range workCh {
				externalID := ids[idx]
				target := profiles[evidence[externalID].localID]
				if target == nil {
					continue
				}
				tNet := time.Now()
				pool, err := fetchPerformerPool(clientURL, apiKey, target, gender, ethnicity, externalID, sharedBase)
				atomic.AddInt64(&networkMs, time.Since(tNet).Milliseconds())
				atomic.AddInt64(&calls, 1)
				if err != nil {
					continue
				}
				var scored []scoredPerformer
				tMatch := time.Now()
				for _, performer := range pool {
					profile := expandProfile(performer, jvStr(recorded))
					if len(profileConflicts(profile, target)) > 0 {
						continue
					}
					sim, _ := profileMatch(profile, target, weights)
					scored = append(scored, scoredPerformer{sim: sim, id: performer.get("id").asString()})
				}
				atomic.AddInt64(&matchMs, time.Since(tMatch).Milliseconds())
				results[idx].scored = scored
			}
		}()
	}
	for idx := range limit {
		workCh <- idx
	}
	close(workCh)
	wg.Wait()
	added := map[string]bool{}
	var additions []string
	for idx := range limit {
		scored := results[idx].scored
		if len(scored) == 0 {
			continue
		}
		sort.SliceStable(scored, func(i, j int) bool { return scored[i].sim > scored[j].sim })
		for i := range min(perFavorite, len(scored)) {
			eid := scored[i].id
			if _, known := evidence[eid]; known || added[eid] {
				continue
			}
			added[eid] = true
			additions = append(additions, eid)
		}
	}
	timings["seeds_chase_network"] = networkMs
	timings["seeds_chase_match"] = matchMs
	timings["seeds_chase_calls"] = int64(calls)
	if len(additions) == 0 {
		return base
	}
	return append(append([]string(nil), base...), additions...)
}

// expandRefresh mirrors ExpandService.refresh and returns the summary dict.
func expandRefresh(db dbx, clientURL, apiKey string, links jVal, horizonDays int,
	gender, ethnicity string, wildcard bool, candidateLimit int, similarTopK, similarPerFavorite int,
	forceFull bool, nowMs int64, progress func(processed, total int)) (jVal, error) {
	fetchedAtMs := nowMs
	started := time.Now()
	timings := map[string]int64{}
	// The taxonomy check and seed load used to be markerless: on a large
	// library the bar sat at 5% for the whole stretch. The 50/150 ticks
	// bracket both phases (issue #110).
	if progress != nil {
		progress(50, 1000)
	}
	t0 := time.Now()
	taxonomyRefreshed, err := refreshTaxonomy(db, clientURL, apiKey, fetchedAtMs)
	if err != nil {
		return jvNull(), err
	}
	timings["taxonomy"] = time.Since(t0).Milliseconds()
	if progress != nil {
		progress(100, 1000)
	}
	modelID, err := currentModelID(db)
	if err != nil {
		return jvNull(), err
	}
	if modelID == "" {
		return jvNull(), fmt.Errorf("no published model")
	}
	var featureVersion string
	if err := db.QueryRow(`SELECT feature_version FROM model_version WHERE model_id=?`, modelID).Scan(&featureVersion); err != nil {
		return jvNull(), err
	}
	s := newExpandService(db)
	if progress != nil {
		progress(150, 1000)
	}
	t0 = time.Now()
	seeds, err := refreshSeeds(s, clientURL, apiKey, modelID, featureVersion, links,
		similarTopK, similarPerFavorite, gender, ethnicity, timings)
	if err != nil {
		return jvNull(), err
	}
	timings["seeds"] = time.Since(t0).Milliseconds()
	if progress != nil {
		progress(200, 1000)
	}
	since := ""
	cachedModelID := ""
	var cacheModelID sql.NullString
	var cachedFetchedAt sql.NullInt64
	err = db.QueryRow(`SELECT model_id, fetched_at_ms FROM expand_cache WHERE singleton=1`).
		Scan(&cacheModelID, &cachedFetchedAt)
	if err == nil && cacheModelID.Valid && cachedFetchedAt.Valid {
		cachedModelID = cacheModelID.String
		since = epochMsToISO(cachedFetchedAt.Int64)
	} else if err != nil && err != sql.ErrNoRows {
		return jvNull(), err
	}
	if forceFull {
		// A force rebuild is the dev escape hatch for scenes a watermark could never
		// surface: it ignores the incremental cursor and re-fetches the whole window.
		since = ""
	} else if since != "" && !supportsIncrementalFetch(clientURL, apiKey) {
		// The live stashdb instance predates the updated_at SceneQueryInput field, so
		// the watermark queries would fail validation; fall back to a full fetch there
		// while newer instances keep the incremental behavior.
		since = ""
	}
	rows := &sceneRows{m: map[string]jVal{}}
	sources := map[string]map[string]bool{}
	filters := []struct {
		source string
		values jVal
	}{
		{"performers", seeds.get("performers")},
		{"studios", seeds.get("studios")},
		{"tags", seeds.get("tags")},
	}
	active := 0
	for _, filter := range filters {
		if len(filter.values.arr) > 0 {
			active++
		}
	}
	if wildcard {
		active++
	}
	perSource := maxInt(1, int(math.Ceil(float64(candidateLimit)/float64(maxInt(1, active)))))
	type querySpec struct {
		source string
		values []string
		limit  int64
		sort   string
	}
	var queries []querySpec
	for _, filter := range filters {
		if len(filter.values.arr) > 0 {
			values := make([]string, 0, len(filter.values.arr))
			for _, v := range filter.values.arr {
				values = append(values, v.asString())
			}
			// A full refresh samples each seed source by recency AND by popularity so
			// interesting scenes older than the newest N are not truncated out (a date-only
			// pool is recency-biased). An incremental refresh walks the watermark, where the
			// UPDATED_AT sort makes both probes identical, so it keeps one probe per source.
			if since != "" {
				queries = append(queries, querySpec{filter.source, values, int64(perSource), "DATE"})
			} else {
				half := int64(perSource) / 2
				if half < 1 {
					half = 1
				}
				queries = append(queries, querySpec{filter.source, values, half, "DATE"})
				queries = append(queries, querySpec{filter.source, values, half, "POPULARITY"})
			}
		}
	}
	if wildcard {
		queries = append(queries, querySpec{"wildcard", nil, minInt64(100, int64(perSource)), "TRENDING"})
	}
	specs := make([]fetchPageSpec, 0, len(queries))
	for _, query := range queries {
		specs = append(specs, fetchPageSpec{
			source:   query.source,
			values:   query.values,
			limit:    query.limit,
			modifier: "INCLUDES",
			sort:     query.sort,
			since:    since,
		})
	}
	// Fetch every probe concurrently (pages within each probe in parallel),
	// merging in probe order — the same merge semantics as the sequential
	// loop, so the fetched rows are identical while the fetch phase takes
	// max(probe) instead of the sum. The per-probe progress ticks keep their
	// sequential values and fire once all probes have returned.
	t0 = time.Now()
	fetched, fetchedSources, err := fetchProbes(clientURL, apiKey, specs)
	if err != nil {
		return jvNull(), err
	}
	timings["fetch"] = time.Since(t0).Milliseconds()
	rows = fetched
	sources = fetchedSources
	if progress != nil {
		for position := range specs {
			progress(200+int(pyRound(450*float64(position+1)/float64(maxInt(1, len(specs))))), 1000)
		}
		if len(specs) == 0 {
			progress(650, 1000)
		}
	}
	today := time.Now()
	cutoff := today.AddDate(0, 0, -horizonDays).Format("2006-01-02")
	byExternalID, byPhash := sceneLinkMaps(links)
	var candidates []jVal
	for _, row := range rows.list() {
		candidate := annotateLocalMatch(row, byExternalID, byPhash)
		match := candidate.get("curator_local_match")
		if match.get("type").asString() != "stashdb_id" &&
			recentScene(candidate, cutoff) &&
			matchesGender(candidate, gender) {
			candidates = append(candidates, candidate)
		}
	}
	if progress != nil {
		progress(750, 1000)
	}
	t0 = time.Now()
	scenes, performers, err := s.score(candidates, sources, modelID, featureVersion, links, jvNull())
	if err != nil {
		return jvNull(), err
	}
	timings["score"] = time.Since(t0).Milliseconds()
	if progress != nil {
		progress(900, 1000)
	}
	t0 = time.Now()
	writeErr := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		upsert := func(entityType string, items []scoredScene) error {
			for _, item := range items {
				srcs := jvArr()
				sources := append([]string(nil), item.sources...)
				sort.Strings(sources)
				for _, source := range sources {
					srcs.arr = append(srcs.arr, jvStr(source))
				}
				if _, err := conn.ExecContext(ctx, `
INSERT INTO external_entity(
  entity_type, external_id, payload_json, score, sources_json, fetched_at_ms, pool
) VALUES (?, ?, ?, ?, ?, ?, 'candidate')
ON CONFLICT(entity_type, external_id) DO UPDATE SET
  payload_json=excluded.payload_json, score=excluded.score,
  sources_json=excluded.sources_json, fetched_at_ms=excluded.fetched_at_ms,
  pool=CASE WHEN external_entity.pool='candidate'
    THEN 'candidate' ELSE excluded.pool END`,
					entityType, item.id, item.payload.marshalCompact(), item.score,
					srcs.marshalCompact(), fetchedAtMs); err != nil {
					return err
				}
			}
			return nil
		}
		if err := upsert("scene", scenes); err != nil {
			return err
		}
		if err := upsert("performer", performers); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx, `
DELETE FROM external_entity
WHERE entity_type='scene' AND pool IN ('candidate', 'explore') AND (
    (json_extract(payload_json, '$.release_date') IS NOT NULL
     AND json_extract(payload_json, '$.release_date') < ?)
    OR (json_extract(payload_json, '$.release_date') IS NULL
        AND json_extract(payload_json, '$.production_date') IS NOT NULL
        AND json_extract(payload_json, '$.production_date') < ?)
) AND external_id NOT IN (
    SELECT external_id FROM external_shortlist WHERE entity_type='scene'
)`, cutoff, cutoff); err != nil {
			return err
		}
		poolRows, err := conn.QueryContext(ctx,
			`SELECT entity_type, count(*) AS count FROM external_entity WHERE pool='candidate' GROUP BY entity_type`)
		if err != nil {
			return err
		}
		poolCounts := map[string]int64{}
		for poolRows.Next() {
			var entityType string
			var count int64
			if err := poolRows.Scan(&entityType, &count); err != nil {
				poolRows.Close()
				return err
			}
			poolCounts[entityType] = count
		}
		poolRows.Close()
		if err := poolRows.Err(); err != nil {
			return err
		}
		_, err = conn.ExecContext(ctx, `
INSERT INTO expand_cache(
  singleton, model_id, fetched_at_ms, expires_at_ms, scene_count, performer_count
) VALUES (1, ?, ?, ?, ?, ?)
ON CONFLICT(singleton) DO UPDATE SET model_id=excluded.model_id,
  fetched_at_ms=excluded.fetched_at_ms, expires_at_ms=excluded.expires_at_ms,
  scene_count=excluded.scene_count, performer_count=excluded.performer_count`,
			modelID, fetchedAtMs, fetchedAtMs+12*3_600_000, poolCounts["scene"], poolCounts["performer"])
		return err
	})
	timings["database_writing"] = time.Since(t0).Milliseconds()
	if writeErr != nil {
		return jvNull(), writeErr
	}
	if cachedModelID != "" && cachedModelID != modelID {
		if err := rescoreCandidates(s, modelID, featureVersion, links); err != nil {
			return jvNull(), err
		}
	}
	timings["total"] = time.Since(started).Milliseconds()
	if progress != nil {
		progress(1000, 1000)
	}
	return jvObj(
		jvKey("scene_count", jvInt(int64(len(scenes)))),
		jvKey("performer_count", jvInt(int64(len(performers)))),
		jvKey("taxonomy_refreshed", jvBool(taxonomyRefreshed)),
		jvKey("incremental", jvBool(since != "")),
		jvKey("stage_timings_ms", stageTimingsJValForExpand(timings)),
	), nil
}

// rescoreCandidates mirrors ExpandService._rescore_candidates.
func rescoreCandidates(s *expandService, modelID, featureVersion string, links jVal) error {
	rows, err := s.db.Query(
		`SELECT external_id, payload_json, sources_json FROM external_entity WHERE entity_type='scene' AND pool='candidate'`)
	if err != nil {
		return err
	}
	type candidateRow struct {
		externalID string
		payload    jVal
		sources    []string
	}
	var candidates []candidateRow
	for rows.Next() {
		var externalID, payloadJSON, sourcesJSON string
		if err := rows.Scan(&externalID, &payloadJSON, &sourcesJSON); err != nil {
			rows.Close()
			return err
		}
		payload, err := parseJSON([]byte(payloadJSON))
		if err != nil {
			rows.Close()
			return err
		}
		srcs, err := parseJSON([]byte(sourcesJSON))
		if err != nil {
			rows.Close()
			return err
		}
		var sourceList []string
		for _, item := range srcs.arr {
			sourceList = append(sourceList, item.asString())
		}
		candidates = append(candidates, candidateRow{externalID, payload, sourceList})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if len(candidates) == 0 {
		return nil
	}
	scenes := make([]jVal, 0, len(candidates))
	sources := map[string]map[string]bool{}
	for _, row := range candidates {
		scenes = append(scenes, row.payload)
		set := map[string]bool{}
		for _, source := range row.sources {
			set[source] = true
		}
		sources[row.externalID] = set
	}
	rescored, performers, err := s.score(scenes, sources, modelID, featureVersion, links, jvNull())
	if err != nil {
		return err
	}
	sceneScores := map[string]float64{}
	for _, item := range rescored {
		sceneScores[item.id] = item.score
	}
	return withTxn(s.db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, row := range candidates {
			if score, ok := sceneScores[row.externalID]; ok {
				if _, err := conn.ExecContext(ctx,
					`UPDATE external_entity SET score=? WHERE entity_type='scene' AND external_id=?`,
					score, row.externalID); err != nil {
					return err
				}
			}
		}
		for _, item := range performers {
			if _, err := conn.ExecContext(ctx,
				`UPDATE external_entity SET score=? WHERE entity_type='performer' AND external_id=?`,
				item.score, item.id); err != nil {
				return err
			}
		}
		return nil
	})
}

// sortedSourceKeys returns a sorted copy of a sources set (Python's
// sorted(sources[id])).
