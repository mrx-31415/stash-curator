package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
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

type tpdbClient struct {
	base, key string
	http      *http.Client
	requests  chan struct{}
	mu        sync.Mutex
	details   map[string]jVal
	tags      []jVal
	tagsReady bool
}

func newTPDBClient(endpoint, key string) *tpdbClient {
	base := strings.TrimSuffix(strings.TrimRight(endpoint, "/"), "/graphql")
	if isThePornDB(endpoint) {
		base = "https://api.theporndb.net"
	}
	return &tpdbClient{base: base, key: key, http: &http.Client{Timeout: 30 * time.Second},
		requests: make(chan struct{}, 4), details: map[string]jVal{}}
}

func thePornDBQuery(endpoint, key, document string, variables jVal) (jVal, error) {
	tpdbSession.Lock()
	if tpdbSession.client == nil || tpdbSession.endpoint != endpoint || tpdbSession.key != key {
		tpdbSession.client = newTPDBClient(endpoint, key)
		tpdbSession.endpoint, tpdbSession.key = endpoint, key
	}
	client := tpdbSession.client
	tpdbSession.Unlock()
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
	response, err := c.http.Do(req)
	if err != nil {
		return jvNull(), fmt.Errorf("ThePornDB request failed: %w", err)
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
	defer c.mu.Unlock()
	cacheKey := resource + "/" + id
	if value, ok := c.details[cacheKey]; ok {
		return value, nil
	}
	result, err := c.get("/"+resource+"/"+url.PathEscape(id), nil, true)
	if err != nil {
		return jvNull(), err
	}
	value := result.get("data")
	if value.kind != jObj && value.kind != jNull {
		return jvNull(), fmt.Errorf("ThePornDB returned an invalid identity")
	}
	c.details[cacheKey] = value
	return value, nil
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
	return tags, nil
}

func (c *tpdbClient) parentPerformer(id string) (jVal, error) {
	performer, err := c.detail("performers", id)
	if err != nil || performer.kind == jObj {
		return performer, err
	}
	site, err := c.detail("performer-sites", id)
	return site.get("parent"), err
}

func (c *tpdbClient) sceneFilter(params url.Values, source string, criterion jVal) (bool, error) {
	modifier := criterion.get("modifier").asString()
	if modifier != "INCLUDES" && modifier != "INCLUDES_ALL" {
		return false, fmt.Errorf("unsupported ThePornDB %s filter modifier", source)
	}
	count := 0
	for _, id := range criterion.get("value").arr {
		var row jVal
		var err error
		field, numeric := source, "_id"
		switch source {
		case "performers":
			row, err = c.parentPerformer(id.asString())
		case "studios":
			row, err = c.detail("sites", id.asString())
			field, numeric = "sites", "id"
		case "tags":
			var tags []jVal
			tags, err = c.tagCatalog()
			for _, tag := range tags {
				if tag.get("uuid").asString() == id.asString() {
					row = tag
					break
				}
			}
			numeric = "id"
		}
		if err != nil {
			return false, err
		}
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
