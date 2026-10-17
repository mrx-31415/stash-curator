package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

func isThePornDB(endpoint string) bool {
	u, err := url.Parse(endpoint)
	return err == nil && strings.EqualFold(u.Hostname(), "theporndb.net")
}

// One client per plugin operation shares identity lookups across discovery probes.
var tpdbSession struct {
	sync.Mutex
	client        *tpdbClient
	endpoint, key string
}

var tpdbCachePath string

type tpdbClient struct {
	base, key       string
	http            *http.Client
	requests        chan struct{}
	mu              sync.Mutex
	details         map[string]*tpdbDetail
	tags            []jVal
	tagsReady       bool
	rateMu          sync.Mutex
	retryAfter      time.Time
	nextRequest     time.Time
	requestInterval time.Duration
	cachePath       string
	tagsCheckedAt   int64
}

type tpdbDetail struct {
	ready     chan struct{}
	value     jVal
	err       error
	checkedAt int64
}

func newTPDBClient(endpoint, key string) *tpdbClient {
	base := strings.TrimSuffix(strings.TrimRight(endpoint, "/"), "/graphql")
	if isThePornDB(endpoint) {
		base = "https://api.theporndb.net"
	}
	client := &tpdbClient{base: base, key: key, http: &http.Client{Timeout: 30 * time.Second},
		requests: make(chan struct{}, 4), details: map[string]*tpdbDetail{}}
	if isThePornDB(endpoint) {
		client.cachePath, client.requestInterval = tpdbCachePath, time.Second
		client.loadCache()
	}
	return client
}

func (c *tpdbClient) loadCache() {
	if c.cachePath == "" {
		return
	}
	raw, err := os.ReadFile(c.cachePath)
	if err != nil {
		return
	}
	cache, err := parseJSON(raw)
	if err != nil || pythonInt(cache.get("version")) != 1 {
		return
	}
	now := time.Now().UnixMilli()
	for _, pair := range cache.get("identities").obj {
		checked := pythonInt(pair.val.get("checked_at_ms"))
		if checked > 0 && checked <= now && now-checked < 7*86_400_000 && pair.val.get("value").kind == jObj {
			entry := &tpdbDetail{ready: make(chan struct{}), value: pair.val.get("value"), checkedAt: checked}
			close(entry.ready)
			c.details[pair.key] = entry
		}
	}
	checked := pythonInt(cache.get("tags_checked_at_ms"))
	if checked > 0 && checked <= now && now-checked < 30*86_400_000 && cache.get("tags").kind == jArr {
		c.tags, c.tagsReady, c.tagsCheckedAt = cache.get("tags").arr, true, checked
	}
}

func tpdbIdentity(raw jVal) jVal {
	value := jvObj()
	for _, field := range []string{"id", "_id", "uuid", "name"} {
		if raw.has(field) {
			value.set(field, raw.get(field))
		}
	}
	if raw.get("parent").kind == jObj {
		value.set("parent", tpdbIdentity(raw.get("parent")))
	}
	return value
}

func (c *tpdbClient) rememberIdentity(resource string, row jVal) {
	id, numeric := row.get("id"), row.get("_id")
	if resource == "sites" {
		id, numeric = row.get("uuid"), row.get("id")
	}
	if !id.truthy() || !numeric.truthy() {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	key := resource + "/" + id.asString()
	if previous, exists := c.details[key]; exists {
		select {
		case <-previous.ready:
		default:
			return
		}
	}
	entry := &tpdbDetail{ready: make(chan struct{}), value: tpdbIdentity(row), checkedAt: time.Now().UnixMilli()}
	close(entry.ready)
	c.details[key] = entry
}

func (c *tpdbClient) saveCache() {
	if c.cachePath == "" {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	keys := make([]string, 0, len(c.details))
	for key, entry := range c.details {
		select {
		case <-entry.ready:
			if entry.err == nil && entry.value.kind == jObj {
				keys = append(keys, key)
			}
		default:
		}
	}
	sort.Slice(keys, func(i, j int) bool { return c.details[keys[i]].checkedAt > c.details[keys[j]].checkedAt })
	identities := jvObj()
	for _, key := range keys[:min(1000, len(keys))] {
		entry := c.details[key]
		identities.set(key, jvObj(jvKey("checked_at_ms", jvInt(entry.checkedAt)), jvKey("value", tpdbIdentity(entry.value))))
	}
	cache := jvObj(jvKey("version", jvInt(1)), jvKey("identities", identities),
		jvKey("tags_checked_at_ms", jvInt(c.tagsCheckedAt)), jvKey("tags", jvArr(c.tags...)))
	if err := os.MkdirAll(filepath.Dir(c.cachePath), 0o700); err != nil {
		return
	}
	file, err := os.CreateTemp(filepath.Dir(c.cachePath), ".theporndb-*.tmp")
	if err != nil {
		return
	}
	defer os.Remove(file.Name())
	_, err = file.WriteString(cache.marshalCompact())
	closeErr := file.Close()
	if err == nil && closeErr == nil {
		if err := os.Rename(file.Name(), c.cachePath); err != nil {
			infoLog("ThePornDB identity cache could not be saved")
		}
	}
}

func thePornDBQuery(endpoint, key, document string, variables jVal) (jVal, error) {
	tpdbSession.Lock()
	if tpdbSession.client == nil || tpdbSession.endpoint != endpoint || tpdbSession.key != key {
		tpdbSession.client = newTPDBClient(endpoint, key)
		tpdbSession.endpoint, tpdbSession.key = endpoint, key
	}
	client := tpdbSession.client
	tpdbSession.Unlock()
	defer client.saveCache()
	started := time.Now().UnixNano()
	defer func() {
		if trace := currentTrace(); trace != nil {
			trace.record("stashdb", graphqlOperationName(document), started, time.Now().UnixNano()-started, jvNull())
		}
	}()
	return client.query(graphqlOperationName(document), variables)
}

func (c *tpdbClient) get(path string, params url.Values, missingOK bool) (jVal, error) {
	c.requests <- struct{}{}
	defer func() { <-c.requests }()
	address := c.base + path
	if len(params) > 0 {
		address += "?" + params.Encode()
	}
	req, err := http.NewRequest(http.MethodGet, address, nil)
	if err != nil {
		return jvNull(), err
	}
	req.Header.Set("Authorization", "Bearer "+c.key)
	req.Header.Set("Accept", "application/json")
	for attempt := 0; ; attempt++ {
		c.rateMu.Lock()
		start := time.Now()
		if c.retryAfter.After(start) {
			start = c.retryAfter
		}
		if c.nextRequest.After(start) {
			start = c.nextRequest
		}
		c.nextRequest = start.Add(c.requestInterval)
		delay := time.Until(start)
		c.rateMu.Unlock()
		if delay > 0 {
			time.Sleep(delay)
		}
		response, err := c.http.Do(req)
		if err != nil {
			return jvNull(), fmt.Errorf("ThePornDB request failed: %w", err)
		}
		if response.StatusCode == http.StatusTooManyRequests && attempt < 3 {
			seconds, err := strconv.Atoi(response.Header.Get("Retry-After"))
			if err != nil || seconds < 0 {
				seconds = 60
			}
			response.Body.Close()
			c.rateMu.Lock()
			c.retryAfter = time.Now().Add(time.Duration(seconds) * time.Second)
			c.rateMu.Unlock()
			continue
		}
		defer response.Body.Close()
		if missingOK && response.StatusCode == http.StatusNotFound {
			return jvNull(), nil
		}
		if response.StatusCode != http.StatusOK {
			return jvNull(), fmt.Errorf("ThePornDB request failed (HTTP %d)", response.StatusCode)
		}
		raw, err := io.ReadAll(response.Body)
		if err != nil {
			return jvNull(), fmt.Errorf("ThePornDB response failed: %w", err)
		}
		result, err := parseJSON(raw)
		if err != nil || result.kind != jObj || !result.has("data") {
			return jvNull(), fmt.Errorf("ThePornDB returned an invalid response")
		}
		return result, nil
	}
}

// Virtual pages preserve the caller's page size across the REST API's 100-row cap.
func (c *tpdbClient) list(path string, params url.Values, page, size int64) (int64, []jVal, error) {
	if page < 1 || size < 1 || size > 500 {
		return 0, nil, fmt.Errorf("invalid ThePornDB page")
	}
	if params == nil {
		params = url.Values{}
	}
	offset := (page - 1) * size
	restSize := minInt64(size, 100)
	restPage, skip := offset/restSize+1, offset%restSize
	var rows []jVal
	var total int64
	for int64(len(rows)) < size {
		params.Set("page", strconv.FormatInt(restPage, 10))
		params.Set("per_page", strconv.FormatInt(restSize, 10))
		result, err := c.get(path, params, false)
		if err != nil {
			return 0, nil, err
		}
		data := result.get("data")
		if data.kind != jArr {
			return 0, nil, fmt.Errorf("ThePornDB returned an invalid list")
		}
		for _, row := range data.arr {
			if row.kind != jObj || !row.get("id").truthy() {
				return 0, nil, fmt.Errorf("ThePornDB returned an invalid list identity")
			}
			if strings.HasPrefix(path, "/performers") {
				c.rememberIdentity("performers", row)
			} else if path == "/scenes" {
				c.rememberIdentity("sites", row.get("site"))
				for _, person := range row.get("performers").arr {
					c.rememberIdentity("performer-sites", person)
					c.rememberIdentity("performers", person.get("parent"))
				}
			}
		}
		if result.get("meta").kind != jObj {
			// Similar-performer responses are unpaginated.
			total = int64(len(data.arr))
			start := minInt64(offset, total)
			return total, data.arr[start:minInt64(start+size, total)], nil
		}
		meta := result.get("meta")
		if meta.get("total").kind != jNum || (meta.has("current_page") && pythonInt(meta.get("current_page")) != restPage) {
			return 0, nil, fmt.Errorf("ThePornDB returned invalid pagination")
		}
		total = pythonInt(meta.get("total"))
		start := minInt64(skip, int64(len(data.arr)))
		end := minInt64(int64(len(data.arr)), start+size-int64(len(rows)))
		rows = append(rows, data.arr[start:end]...)
		if len(data.arr) == 0 || restPage*restSize >= total {
			break
		}
		restPage++
		skip = 0
	}
	return total, rows, nil
}

func (c *tpdbClient) detail(resource, id string) (jVal, error) {
	c.mu.Lock()
	cacheKey := resource + "/" + id
	if entry, ok := c.details[cacheKey]; ok {
		c.mu.Unlock()
		<-entry.ready
		return entry.value, entry.err
	}
	entry := &tpdbDetail{ready: make(chan struct{})}
	c.details[cacheKey] = entry
	c.mu.Unlock()
	result, err := c.get("/"+resource+"/"+url.PathEscape(id), nil, true)
	value := result.get("data")
	if err == nil && value.kind != jObj && value.kind != jNull {
		err = fmt.Errorf("ThePornDB returned an invalid identity")
	}
	entry.value, entry.err, entry.checkedAt = value, err, time.Now().UnixMilli()
	close(entry.ready)
	return value, err
}

func (c *tpdbClient) tagCatalog() ([]jVal, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.tagsReady {
		return c.tags, nil
	}
	var tags []jVal
	for page := int64(1); ; page++ {
		total, rows, err := c.list("/tags", nil, page, 100)
		if err != nil {
			return nil, err
		}
		tags = append(tags, rows...)
		if len(rows) == 0 || int64(len(tags)) >= total {
			break
		}
	}
	c.tags, c.tagsReady = tags, true
	c.tagsCheckedAt = time.Now().UnixMilli()
	return tags, nil
}

func (c *tpdbClient) parentPerformer(id string) (jVal, error) {
	c.mu.Lock()
	site, knownSite := c.details["performer-sites/"+id]
	c.mu.Unlock()
	if knownSite {
		<-site.ready
		return site.value.get("parent"), site.err
	}
	performer, err := c.detail("performers", id)
	if err != nil || performer.kind == jObj {
		return performer, err
	}
	profile, err := c.detail("performer-sites", id)
	return profile.get("parent"), err
}

func (c *tpdbClient) sceneFilter(params url.Values, source string, criterion jVal) (bool, error) {
	modifier := criterion.get("modifier").asString()
	if modifier != "INCLUDES" && modifier != "INCLUDES_ALL" {
		return false, fmt.Errorf("unsupported ThePornDB %s filter modifier", source)
	}
	field, numeric := source, "_id"
	if source == "studios" {
		field, numeric = "sites", "id"
	} else if source == "tags" {
		numeric = "id"
	}
	ids := criterion.get("value").arr
	rows, errors := make([]jVal, len(ids)), make([]error, len(ids))
	work := make(chan int)
	stop := make(chan struct{})
	var stopOnce sync.Once
	var wg sync.WaitGroup
	for range min(4, len(ids)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range work {
				select {
				case <-stop:
					continue
				default:
				}
				id := ids[index].asString()
				switch source {
				case "performers":
					rows[index], errors[index] = c.parentPerformer(id)
				case "studios":
					rows[index], errors[index] = c.detail("sites", id)
				case "tags":
					var tags []jVal
					tags, errors[index] = c.tagCatalog()
					for _, tag := range tags {
						if tag.get("uuid").asString() == id {
							rows[index] = tag
							break
						}
					}
				}
				if errors[index] != nil {
					stopOnce.Do(func() { close(stop) })
				}
			}
		}()
	}
queue:
	for index := range ids {
		select {
		case work <- index:
		case <-stop:
			break queue
		}
	}
	close(work)
	wg.Wait()
	for _, err := range errors {
		if err != nil {
			return false, err
		}
	}
	count := 0
	for _, row := range rows {
		if row.kind != jObj || !row.get(numeric).truthy() {
			if modifier == "INCLUDES_ALL" {
				return false, nil
			}
			continue
		}
		params.Set(field+"["+row.get(numeric).asString()+"]", pythonStrOrEmpty(row.get("name")))
		count++
	}
	if source == "performers" || source == "tags" {
		key := "performer_and"
		if source == "tags" {
			key = "tag_and"
		}
		params.Set(key, strconv.FormatBool(modifier == "INCLUDES_ALL"))
	}
	return count > 0, nil
}

func (c *tpdbClient) query(operation string, variables jVal) (jVal, error) {
	input := variables.get("input")
	page, size := int64(1), int64(25)
	if input.has("page") {
		page = pythonInt(input.get("page"))
	}
	if input.has("per_page") {
		size = pythonInt(input.get("per_page"))
	}
	switch operation {
	case "CuratorSceneFilterSchema":
		return jvObj(jvKey("__type", jvObj(jvKey("inputFields", jvArr())))), nil
	case "CuratorTagCategories":
		return jvObj(jvKey("queryTagCategories", jvObj(jvKey("count", jvInt(0)), jvKey("tag_categories", jvArr())))), nil
	case "CuratorTaxonomyTags":
		tags, err := c.tagCatalog()
		if err != nil {
			return jvNull(), err
		}
		page, size = pythonInt(variables.get("page")), pythonInt(variables.get("perPage"))
		if page < 1 || size < 1 {
			return jvNull(), fmt.Errorf("invalid ThePornDB tag page")
		}
		start := minInt64((page-1)*size, int64(len(tags)))
		rows := jvArr()
		for _, tag := range tags[start:minInt64(start+size, int64(len(tags)))] {
			rows.arr = append(rows.arr, jvObj(jvKey("id", tag.get("uuid")), jvKey("name", tag.get("name")), jvKey("aliases", jvArr()), jvKey("category", jvNull())))
		}
		return jvObj(jvKey("queryTags", jvObj(jvKey("count", jvInt(int64(len(tags)))), jvKey("tags", rows)))), nil
	case "CuratorExpandScenes":
		if input.has("updated_at") {
			return jvNull(), fmt.Errorf("ThePornDB requires a full discovery refresh")
		}
		params := url.Values{"orderBy": {"recently_released"}}
		if input.get("direction").asString() == "ASC" {
			params.Set("orderBy", "former_released")
		}
		if sort := input.get("sort").asString(); sort == "POPULARITY" || sort == "TRENDING" {
			params.Set("orderBy", "most_relevant")
		}
		for _, source := range []string{"performers", "studios", "tags"} {
			if input.has(source) {
				ok, err := c.sceneFilter(params, source, input.get(source))
				if err != nil {
					return jvNull(), err
				}
				if !ok {
					return jvObj(jvKey("queryScenes", jvObj(jvKey("count", jvInt(0)), jvKey("scenes", jvArr())))), nil
				}
			}
		}
		total, raw, err := c.list("/scenes", params, page, size)
		if err != nil {
			return jvNull(), err
		}
		rows := jvArr()
		for _, row := range raw {
			rows.arr = append(rows.arr, tpdbScene(row))
		}
		return jvObj(jvKey("queryScenes", jvObj(jvKey("count", jvInt(total)), jvKey("scenes", rows)))), nil
	case "CuratorSimilarPerformers", "CuratorPerformerSearch":
		params := url.Values{"orderBy": {"most_relevant"}}
		if input.get("sort").asString() == "NAME" {
			params.Set("orderBy", "asc_name")
		}
		if input.get("names").truthy() {
			params.Set("q", input.get("names").asString())
		}
		for _, name := range []string{"gender", "ethnicity"} {
			if input.get(name).truthy() {
				words := strings.Fields(strings.ToLower(strings.ReplaceAll(input.get(name).asString(), "_", " ")))
				for i, word := range words {
					words[i] = strings.ToUpper(word[:1]) + word[1:]
				}
				params.Set(name, strings.Join(words, " "))
			}
		}
		if input.has("age") {
			if input.get("age").get("modifier").asString() != "GREATER_THAN" {
				return jvNull(), fmt.Errorf("unsupported ThePornDB age filter")
			}
			params.Set("age", input.get("age").get("value").asString())
			params.Set("age_operation", ">")
		}
		path := "/performers"
		if input.get("performed_with").truthy() {
			parent, err := c.parentPerformer(input.get("performed_with").asString())
			if err != nil {
				return jvNull(), err
			}
			if parent.kind != jObj {
				return jvObj(jvKey("queryPerformers", jvObj(jvKey("performers", jvArr())))), nil
			}
			// The REST API offers profile similarity, rather than a co-star query.
			path = "/performers/" + url.PathEscape(parent.get("id").asString()) + "/similar"
		}
		total, raw, err := c.list(path, params, page, size)
		if err != nil {
			return jvNull(), err
		}
		rows := jvArr()
		for _, row := range raw {
			performer := tpdbPerformer(row)
			if input.get("gender").truthy() && !strings.EqualFold(performer.get("gender").asString(), input.get("gender").asString()) {
				continue
			}
			if input.get("ethnicity").truthy() && !strings.EqualFold(performer.get("ethnicity").asString(), input.get("ethnicity").asString()) {
				continue
			}
			rows.arr = append(rows.arr, performer)
		}
		return jvObj(jvKey("queryPerformers", jvObj(jvKey("count", jvInt(total)), jvKey("performers", rows)))), nil
	}
	return jvNull(), fmt.Errorf("unsupported ThePornDB discovery operation: %s", operation)
}

func tpdbImages(raw jVal) jVal {
	rows := jvArr()
	for _, key := range []string{"image", "poster", "thumbnail", "face"} {
		if raw.get(key).truthy() {
			rows.arr = append(rows.arr, jvObj(jvKey("url", raw.get(key)), jvKey("width", jvNull()), jvKey("height", jvNull())))
		}
	}
	return rows
}

var tpdbNumber = regexp.MustCompile(`^\s*(\d+(?:\.\d+)?)\s*(cm|m|in|inches|")?\s*$`)
var tpdbCup = regexp.MustCompile(`^(\d{2,3})?([A-Za-z]{1,3})$`)

func tpdbMeasurement(raw jVal, height bool) jVal {
	match := tpdbNumber.FindStringSubmatch(pythonStrOrEmpty(raw))
	if match == nil {
		return jvNull()
	}
	value, _ := strconv.ParseFloat(match[1], 64)
	if height {
		if match[2] == "m" {
			value *= 100
		}
		if match[2] == "in" || match[2] == "inches" || match[2] == `"` {
			value *= 2.54
		}
		if value < 100 || value > 230 {
			return jvNull()
		}
	} else {
		if match[2] == "cm" {
			value /= 2.54
		}
		if match[2] == "m" || value < 15 || value > 80 {
			return jvNull()
		}
	}
	return jvFloat(value)
}

func tpdbPerformer(raw jVal) jVal {
	isSite := raw.get("extra").kind == jObj && raw.get("parent").kind != jObj
	if raw.get("parent").kind == jObj {
		raw = raw.get("parent")
	}
	extra := raw.get("extras")
	if extra.kind != jObj {
		extra = raw.get("extra")
	}
	result := jvObj(jvKey("id", raw.get("id")), jvKey("name", raw.get("name")), jvKey("aliases", jvArr()),
		jvKey("curator_site_performer", jvBool(isSite)),
		jvKey("disambiguation", raw.get("disambiguation")), jvKey("scene_count", jvNull()), jvKey("images", tpdbImages(raw)),
		jvKey("birth_date", extra.get("birthday")), jvKey("height", tpdbMeasurement(extra.get("height"), true)),
		jvKey("cup_size", jvNull()), jvKey("band_size", jvNull()), jvKey("waist_size", tpdbMeasurement(extra.get("waist"), false)),
		jvKey("hip_size", tpdbMeasurement(extra.get("hips"), false)), jvKey("breast_type", jvNull()))
	if raw.get("aliases").kind == jArr {
		result.set("aliases", raw.get("aliases"))
	}
	for _, pair := range [][2]string{{"gender", "gender"}, {"ethnicity", "ethnicity"}, {"eye_color", "eye_colour"}, {"hair_color", "hair_colour"}} {
		value := extra.get(pair[1])
		if pair[0] == "hair_color" && !value.truthy() {
			value = extra.get("haircolor")
		}
		if value.truthy() {
			text := strings.ToUpper(strings.ReplaceAll(strings.TrimSpace(value.asString()), " ", "_"))
			if text == "BROWN" && pair[0] == "hair_color" {
				text = "BRUNETTE"
			}
			result.set(pair[0], jvStr(text))
		} else {
			result.set(pair[0], jvNull())
		}
	}
	if measurements := parseMeasurements(pythonStrOrEmpty(extra.get("measurements"))); measurements != nil {
		result.set("band_size", jvFloat(measurements.bandInches))
		result.set("waist_size", jvFloat(measurements.waistInches))
		result.set("hip_size", jvFloat(measurements.hipInches))
		match := measurementPattern.FindStringSubmatch(extra.get("measurements").asString())
		if measurements.hasCup {
			result.set("cup_size", jvStr(strings.ToUpper(match[2])))
		}
	}
	if cup := tpdbCup.FindStringSubmatch(strings.TrimSpace(pythonStrOrEmpty(extra.get("cupsize")))); cup != nil {
		if _, ok := cupAliases[strings.ToUpper(cup[2])]; ok {
			result.set("cup_size", jvStr(strings.ToUpper(cup[2])))
		}
		if cup[1] != "" {
			result.set("band_size", tpdbMeasurement(jvStr(cup[1]), false))
		}
	}
	fake := extra.get("fake_boobs")
	if fake.kind == jNull {
		fake = extra.get("fakeboobs")
	}
	if fake.kind == jBool {
		value := "NATURAL"
		if fake.b {
			value = "FAKE"
		}
		result.set("breast_type", jvStr(value))
	}
	for _, name := range []string{"tattoos", "piercings"} {
		rows := jvArr()
		text := strings.TrimSpace(pythonStrOrEmpty(extra.get(name)))
		if text != "" && presenceCategory(text) != "absent" {
			rows.arr = append(rows.arr, jvObj(jvKey("location", jvStr(text))))
		}
		result.set(name, rows)
	}
	return result
}

func tpdbScene(raw jVal) jVal {
	cast, tags, fingerprints := jvArr(), jvArr(), jvArr()
	seen := map[string]bool{}
	for _, person := range raw.get("performers").arr {
		person = tpdbPerformer(person)
		id := person.get("id").asString()
		if !seen[id] {
			cast.arr = append(cast.arr, jvObj(jvKey("performer", person)))
			seen[id] = true
		}
	}
	for _, tag := range raw.get("tags").arr {
		tags.arr = append(tags.arr, jvObj(jvKey("id", tag.get("uuid")), jvKey("name", tag.get("name"))))
	}
	for _, hash := range raw.get("hashes").arr {
		algorithm := strings.ToUpper(pythonStrOrEmpty(hash.get("type")))
		if (algorithm == "PHASH" || algorithm == "OSHASH" || algorithm == "MD5") && hash.get("hash").truthy() {
			fingerprints.arr = append(fingerprints.arr, jvObj(jvKey("hash", hash.get("hash")), jvKey("algorithm", jvStr(algorithm)), jvKey("duration", hash.get("duration"))))
		}
	}
	studio := jvNull()
	if site := raw.get("site"); site.kind == jObj {
		studio = jvObj(jvKey("id", site.get("uuid")), jvKey("name", site.get("name")))
	}
	return jvObj(jvKey("id", raw.get("id")), jvKey("title", raw.get("title")), jvKey("release_date", raw.get("date")),
		jvKey("production_date", jvNull()), jvKey("duration", raw.get("duration")), jvKey("details", raw.get("description")),
		jvKey("studio", studio), jvKey("tags", tags), jvKey("performers", cast), jvKey("images", tpdbImages(raw)), jvKey("fingerprints", fingerprints))
}
