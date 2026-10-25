package main

// Incremental Expand refresh state. StashDB has no updated_at scene filter,
// but it sorts by UPDATED_AT, so an incremental refresh walks each seed probe
// newest-update-first and stops at the previous refresh. Seeds that were not
// part of the last refresh still get the full DATE + POPULARITY sample, and a
// weekly full fetch renews the popularity sample a watermark cannot see.
// Favourite look-alikes barely move between nights, so the chase result is
// reused for a week while its inputs stay the same.

import (
	"context"
	"database/sql"
	"encoding/json"
	"strings"
)

const (
	expandSeedStateKey = "expand_seed_state"
	expandLookalikeKey = "expand_lookalike_cache"
	// expandFullFetchIntervalMs bounds how long incremental refreshes run
	// before a full fetch resamples every seed source by popularity.
	expandFullFetchIntervalMs = 7 * 24 * 3_600_000
	// expandWatermarkSlackMs re-reads an hour before the previous refresh so
	// clock skew between StashDB and this host cannot drop an update.
	expandWatermarkSlackMs = 3_600_000
	expandLookalikeTTLMs   = 7 * 24 * 3_600_000
)

// expandSeedState is the seed set the cached pool was fetched for and when
// the last full fetch ran.
type expandSeedState struct {
	FullFetchAtMs int64    `json:"full_fetch_at_ms"`
	Performers    []string `json:"performers"`
	Studios       []string `json:"studios"`
	Tags          []string `json:"tags"`
}

func (s expandSeedState) values(source string) []string {
	switch source {
	case "performers":
		return s.Performers
	case "studios":
		return s.Studios
	}
	return s.Tags
}

// lookalikeEntry is one cached look-alike chase: the additions it found for
// the chase inputs in key.
type lookalikeEntry struct {
	Key         string   `json:"key"`
	FetchedAtMs int64    `json:"fetched_at_ms"`
	Additions   []string `json:"additions"`
}

// readExpandMeta decodes one JSON application_meta value; a missing or
// unreadable row reports ok=false so the refresh falls back to a full fetch.
func readExpandMeta(db dbx, key string, target any) (bool, error) {
	var raw string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key=?`, key).Scan(&raw)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return json.Unmarshal([]byte(raw), target) == nil, nil
}

func writeExpandMeta(ctx context.Context, conn *sql.Conn, key string, value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	_, err = conn.ExecContext(ctx, `INSERT INTO application_meta(key,value) VALUES (?,?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value`, key, string(raw))
	return err
}

// splitKnownSeeds splits a seed source's values into those the cached pool
// already covers and those it has never fetched, keeping the seed order.
func splitKnownSeeds(values, previous []string) (known, fresh []string) {
	seen := make(map[string]bool, len(previous))
	for _, value := range previous {
		seen[value] = true
	}
	for _, value := range values {
		if seen[value] {
			known = append(known, value)
		} else {
			fresh = append(fresh, value)
		}
	}
	return known, fresh
}

// lookalikeCacheKey identifies the chase inputs: endpoint, filters, limits
// and the ranked favourites chased.
func lookalikeCacheKey(gender, ethnicity string, topK, perFavorite int, targets []string) string {
	raw, _ := json.Marshal([]any{
		strings.ToLower(strings.TrimRight(stashdbEndpoint, "/")), gender, ethnicity, topK, perFavorite, targets,
	})
	return string(raw)
}
