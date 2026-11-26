// Rolling Whisparr search: scenes Curator sends join a rotation that the
// daemon searches a few at a time, retrying on a widening schedule until
// Whisparr has the file. A bulk send therefore never fires one indexer
// search per scene at once (which trips indexer rate limits), and a scene
// that was not released or indexed yet when it was sent is found later.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

// whisparrSearchTask is the daemon job that runs one sweep.
const whisparrSearchTask = "whisparr-search"

// whisparrSearchRetryMs is the wait after a scene's n-th search (1-based);
// later searches repeat the last step.
var whisparrSearchRetryMs = []int64{
	2 * 3_600_000,
	6 * 3_600_000,
	24 * 3_600_000,
	24 * 3_600_000,
	24 * 3_600_000,
	7 * 24 * 3_600_000,
}

// whisparrSweepMaxPauseMs caps a wait on indexer backoff, so an indexer that
// stays broken slows the rotation down instead of stopping it.
const whisparrSweepMaxPauseMs int64 = 6 * 3_600_000

// whisparrSweepErrorPauseMs is the wait after Whisparr could not be reached.
const whisparrSweepErrorPauseMs int64 = 3_600_000

func whisparrSearchRetryAfter(attempts int64) int64 {
	if attempts < 1 {
		attempts = 1
	}
	if attempts > int64(len(whisparrSearchRetryMs)) {
		attempts = int64(len(whisparrSearchRetryMs))
	}
	return whisparrSearchRetryMs[attempts-1]
}

// whisparrSweepConfig is the sweep's slice of the sidecar config.
type whisparrSweepConfig struct {
	enabled    bool
	intervalMs int64
	batchSize  int
	giveUpMs   int64
}

func readWhisparrSweepConfig(config jVal) whisparrSweepConfig {
	batch := int(pythonInt(config.get("whisparr_sweep_batch_size")))
	if batch < 1 {
		batch = 3
	}
	giveUpDays := pythonInt(config.get("whisparr_sweep_give_up_days"))
	if giveUpDays < 1 {
		giveUpDays = 60
	}
	interval := pyRound(pythonFloatOr(config.get("whisparr_sweep_interval_minutes"), 15) * 60_000)
	if interval < 60_000 {
		interval = 15 * 60_000
	}
	return whisparrSweepConfig{
		enabled:    config.get("whisparr_sweep_enabled").truthy(),
		intervalMs: interval,
		batchSize:  batch,
		giveUpMs:   giveUpDays * 24 * 3_600_000,
	}
}

// queueWhisparrSearch puts a scene at the front of the rotation. Sending a
// scene again restarts its schedule, including one that was done or given up.
func queueWhisparrSearch(db dbx, stashdbID string, whisparrID, now int64) error {
	return execImmediate(db, `INSERT INTO whisparr_search
(external_id, whisparr_id, added_at_ms, attempts, last_searched_at_ms, next_due_at_ms, state, updated_at_ms)
VALUES (?, ?, ?, 0, NULL, ?, 'active', ?)
ON CONFLICT(external_id) DO UPDATE SET whisparr_id=excluded.whisparr_id,
added_at_ms=excluded.added_at_ms, attempts=0, last_searched_at_ms=NULL,
next_due_at_ms=excluded.next_due_at_ms, state='active', updated_at_ms=excluded.updated_at_ms`,
		stashdbID, whisparrID, now, now, now)
}

// forgetWhisparrSearch drops scenes from the rotation (they left Whisparr).
func forgetWhisparrSearch(db dbx, stashdbIDs []string) error {
	if len(stashdbIDs) == 0 {
		return nil
	}
	encoded := jvArr()
	for _, id := range stashdbIDs {
		encoded.arr = append(encoded.arr, jvStr(id))
	}
	return execImmediate(db, `DELETE FROM whisparr_search
WHERE external_id IN (SELECT value FROM json_each(?))`, encoded.marshalCompact())
}

// whisparrSweepState reads the sweep's pacing row (zeros before the first run).
func whisparrSweepState(db dbx) (lastRunMs, pausedUntilMs int64, err error) {
	err = db.QueryRow(`SELECT last_run_at_ms, paused_until_ms FROM whisparr_sweep WHERE singleton=1`).
		Scan(&lastRunMs, &pausedUntilMs)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, 0, nil
	}
	return lastRunMs, pausedUntilMs, err
}

func recordWhisparrSweep(db dbx, lastRunMs, pausedUntilMs int64, lastError string) error {
	var errValue any
	if lastError != "" {
		errValue = truncateString(lastError, 2000)
	}
	return execImmediate(db, `INSERT INTO whisparr_sweep(singleton, last_run_at_ms, paused_until_ms, last_error)
VALUES (1, ?, ?, ?)
ON CONFLICT(singleton) DO UPDATE SET last_run_at_ms=excluded.last_run_at_ms,
paused_until_ms=excluded.paused_until_ms, last_error=excluded.last_error`,
		lastRunMs, pausedUntilMs, errValue)
}

// whisparrSearchActive reports whether the rotation has work: the sweep is
// on and at least one scene is still being searched for.
func whisparrSearchActive(db dbx, config jVal) (bool, error) {
	if !readWhisparrSweepConfig(config).enabled {
		return false, nil
	}
	var one int
	err := db.QueryRow(`SELECT 1 FROM whisparr_search WHERE state='active' LIMIT 1`).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// whisparrSweepDue reports whether the daemon should queue a sweep now: the
// interval has passed, Whisparr is not in backoff, and a scene is due.
func whisparrSweepDue(db dbx, config jVal, now int64) (bool, error) {
	cfg := readWhisparrSweepConfig(config)
	if !cfg.enabled {
		return false, nil
	}
	lastRun, pausedUntil, err := whisparrSweepState(db)
	if err != nil {
		return false, err
	}
	if now < pausedUntil || now-lastRun < cfg.intervalMs {
		return false, nil
	}
	var one int
	err = db.QueryRow(`SELECT 1 FROM whisparr_search WHERE state='active' AND next_due_at_ms<=? LIMIT 1`, now).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// whisparrSweepTick queues a sweep when one is due. Unlike the other
// automatic tasks it also runs while a Curator page is open: a sweep is a
// few small Whisparr requests, and bulk sends happen while browsing.
func whisparrSweepTick(db dbx, payload jVal, now int64) (bool, error) {
	cfg, err := sidecarConfig(db)
	if err != nil {
		return false, err
	}
	due, err := whisparrSweepDue(db, cfg.get("config"), now)
	if err != nil || !due {
		return false, err
	}
	return enqueueTask(db, whisparrSearchTask, payload, now, false)
}

// whisparrTime parses Whisparr's ISO dates ("2026-11-26" or RFC 3339).
func whisparrTime(value string) (int64, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0, false
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02"} {
		if parsed, err := time.Parse(layout, value); err == nil {
			return parsed.UnixMilli(), true
		}
	}
	return 0, false
}

// whisparrIndexerBackoffUntil is the latest time any indexer is disabled
// until (0 when none is), as Whisparr reports after rate limits or failures.
func whisparrIndexerBackoffUntil(api whisparrAPI, now int64) (int64, error) {
	statuses, err := api.call("GET", "/indexerstatus", jvNull())
	if err != nil {
		return 0, err
	}
	var until int64
	for _, status := range statuses.arr {
		if at, ok := whisparrTime(pythonStrOrEmpty(status.get("disabledTill"))); ok && at > now && at > until {
			until = at
		}
	}
	return until, nil
}

// whisparrSearchRunning reports whether Whisparr still has a scene search
// queued or running, so sweeps never stack up behind each other.
func whisparrSearchRunning(api whisparrAPI) (bool, error) {
	commands, err := api.call("GET", "/command", jvNull())
	if err != nil {
		return false, err
	}
	for _, command := range commands.arr {
		name := pythonStrOrEmpty(command.get("name"))
		status := strings.ToLower(pythonStrOrEmpty(command.get("status")))
		if name == "MoviesSearch" && (status == "queued" || status == "started") {
			return true, nil
		}
	}
	return false, nil
}

type whisparrSearchRow struct {
	externalID string
	whisparrID int64
	addedAtMs  int64
	attempts   int64
	nextDueMs  int64
}

func activeWhisparrSearches(db dbx) ([]whisparrSearchRow, error) {
	rows, err := db.Query(`SELECT external_id, whisparr_id, added_at_ms, attempts, next_due_at_ms
FROM whisparr_search WHERE state='active' ORDER BY next_due_at_ms, external_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []whisparrSearchRow
	for rows.Next() {
		var row whisparrSearchRow
		if err := rows.Scan(&row.externalID, &row.whisparrID, &row.addedAtMs, &row.attempts, &row.nextDueMs); err != nil {
			return nil, err
		}
		out = append(out, row)
	}
	return out, rows.Err()
}

// localStashdbSceneIDs is the set of StashDB ids already in the library, from
// the local-match cache only (a sweep never triggers a library scan).
func localStashdbSceneIDs(db dbx) (map[string]bool, error) {
	rows, err := db.Query(`SELECT DISTINCT value FROM local_scene_match WHERE kind='stashdb_id'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ids := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids[id] = true
	}
	return ids, rows.Err()
}

// taskWhisparrSearch runs one sweep: settle scenes Whisparr now has, then
// search the best-scored due scenes, at most one batch.
func taskWhisparrSearch(db dbx, settings jVal) (jVal, error) {
	now := nowMs()
	cfgRow, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := readWhisparrSweepConfig(cfgRow.get("config"))
	if !cfg.enabled {
		return jvObj(jvKey("status", jvStr("disabled"))), nil
	}
	summary, err := runWhisparrSweep(db, settings, cfg, now)
	if err != nil {
		// Whisparr down or misconfigured: record it and back off. The job
		// itself succeeds, so a background retry never flags a failed task.
		errorLog("Whisparr search: " + err.Error())
		pausedUntil := now + whisparrSweepErrorPauseMs
		if recErr := recordWhisparrSweep(db, now, pausedUntil, err.Error()); recErr != nil {
			return jvNull(), recErr
		}
		return jvObj(
			jvKey("status", jvStr("error")),
			jvKey("error", jvStr(err.Error())),
			jvKey("paused_until_ms", jvInt(pausedUntil)),
		), nil
	}
	return summary, nil
}

func runWhisparrSweep(db dbx, settings jVal, cfg whisparrSweepConfig, now int64) (jVal, error) {
	api, err := newWhisparrAPI(settings)
	if err != nil {
		return jvNull(), err
	}
	backoff, err := whisparrIndexerBackoffUntil(api, now)
	if err != nil {
		return jvNull(), err
	}
	if backoff > 0 {
		if backoff > now+whisparrSweepMaxPauseMs {
			backoff = now + whisparrSweepMaxPauseMs
		}
		infoLog("Whisparr indexers are in backoff; waiting before the next search")
		if err := recordWhisparrSweep(db, now, backoff, ""); err != nil {
			return jvNull(), err
		}
		return jvObj(jvKey("status", jvStr("indexer_backoff")), jvKey("paused_until_ms", jvInt(backoff))), nil
	}
	busy, err := whisparrSearchRunning(api)
	if err != nil {
		return jvNull(), err
	}
	if busy {
		if err := recordWhisparrSweep(db, now, 0, ""); err != nil {
			return jvNull(), err
		}
		return jvObj(jvKey("status", jvStr("search_running"))), nil
	}
	movies, err := api.call("GET", "/movie", jvNull())
	if err != nil {
		return jvNull(), err
	}
	if movies.kind != jArr {
		return jvNull(), errors.New("Whisparr returned an invalid movie list")
	}
	byID := map[int64]jVal{}
	for _, movie := range movies.arr {
		if id := pythonInt(movie.get("id")); movie.kind == jObj && id > 0 {
			byID[id] = movie
		}
	}
	queue, err := api.queue()
	if err != nil {
		return jvNull(), err
	}
	library, err := localStashdbSceneIDs(db)
	if err != nil {
		return jvNull(), err
	}
	rows, err := activeWhisparrSearches(db)
	if err != nil {
		return jvNull(), err
	}

	var removed, done, gaveUp []string
	var due []whisparrSearchRow
	waits := map[string]int64{} // external id → postponed next_due_at_ms
	for _, row := range rows {
		movie, inWhisparr := byID[row.whisparrID]
		_, downloading := queue[row.whisparrID]
		switch {
		case !inWhisparr:
			removed = append(removed, row.externalID)
		case movie.get("hasFile").truthy() || library[row.externalID]:
			done = append(done, row.externalID)
		case downloading:
			// Whisparr grabbed a release; check back after the next interval.
			waits[row.externalID] = now + cfg.intervalMs
		case now-row.addedAtMs >= cfg.giveUpMs:
			gaveUp = append(gaveUp, row.externalID)
		case row.nextDueMs > now:
		default:
			release, known := whisparrTime(firstNonEmpty(pythonStrOrEmpty(movie.get("releaseDate")), pythonStrOrEmpty(movie.get("digitalRelease"))))
			if known && release > now {
				waits[row.externalID] = release // not released yet: no search can find it
				continue
			}
			due = append(due, row)
		}
	}

	ids := make([]string, len(due))
	for i, row := range due {
		ids[i] = row.externalID
	}
	scores, err := cachedSceneScores(db, ids)
	if err != nil {
		return jvNull(), err
	}
	sort.SliceStable(due, func(i, j int) bool {
		si, iok := scores[due[i].externalID]
		sj, jok := scores[due[j].externalID]
		if iok != jok {
			return iok
		}
		if iok && si != sj {
			return si > sj
		}
		return due[i].nextDueMs < due[j].nextDueMs
	})
	if len(due) > cfg.batchSize {
		due = due[:cfg.batchSize]
	}
	if len(due) > 0 {
		movieIDs := jvArr()
		for _, row := range due {
			movieIDs.arr = append(movieIDs.arr, jvInt(row.whisparrID))
		}
		if _, err := api.call("POST", "/command", jvObj(jvKey("name", jvStr("MoviesSearch")), jvKey("movieIds", movieIDs))); err != nil {
			return jvNull(), err
		}
		infoLog(fmt.Sprintf("Asked Whisparr to search for %d scene(s)", len(due)))
	}

	err = withTxn(db, func(conn *sql.Conn) error {
		exec := func(query string, args ...any) error {
			_, err := conn.ExecContext(context.Background(), query, args...)
			return err
		}
		for _, id := range removed {
			if err := exec(`DELETE FROM whisparr_search WHERE external_id=?`, id); err != nil {
				return err
			}
		}
		for _, id := range done {
			if err := exec(`UPDATE whisparr_search SET state='done', updated_at_ms=? WHERE external_id=?`, now, id); err != nil {
				return err
			}
		}
		for _, id := range gaveUp {
			if err := exec(`UPDATE whisparr_search SET state='gave_up', updated_at_ms=? WHERE external_id=?`, now, id); err != nil {
				return err
			}
		}
		for id, at := range waits {
			if err := exec(`UPDATE whisparr_search SET next_due_at_ms=?, updated_at_ms=? WHERE external_id=?`, at, now, id); err != nil {
				return err
			}
		}
		for _, row := range due {
			attempts := row.attempts + 1
			if err := exec(`UPDATE whisparr_search SET attempts=?, last_searched_at_ms=?, next_due_at_ms=?, updated_at_ms=?
WHERE external_id=?`, attempts, now, now+whisparrSearchRetryAfter(attempts), now, row.externalID); err != nil {
				return err
			}
		}
		_, err := conn.ExecContext(context.Background(), `INSERT INTO whisparr_sweep(singleton, last_run_at_ms, paused_until_ms, last_error)
VALUES (1, ?, 0, NULL)
ON CONFLICT(singleton) DO UPDATE SET last_run_at_ms=excluded.last_run_at_ms, paused_until_ms=0, last_error=NULL`, now)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	active := int64(len(rows) - len(removed) - len(done) - len(gaveUp))
	return jvObj(
		jvKey("status", jvStr("searched")),
		jvKey("searched", jvInt(int64(len(due)))),
		jvKey("done", jvInt(int64(len(done)))),
		jvKey("gave_up", jvInt(int64(len(gaveUp)))),
		jvKey("removed", jvInt(int64(len(removed)))),
		jvKey("active", jvInt(active)),
	), nil
}
