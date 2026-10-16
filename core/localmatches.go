package main

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"strings"
	"time"
)

const localMatchFields = `id stash_ids { endpoint stash_id } files { fingerprints { type value } }`

const localMatchTask = "local-matches"

func ensureLocalSceneMatches(pluginDir string, payload, settings jVal, db dbx) (bool, error) {
	var ready string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='local_scene_matches_ready'`).Scan(&ready)
	if err == nil {
		return true, nil
	}
	if err != sql.ErrNoRows {
		return false, err
	}
	var state, failure string
	var started int64
	err = db.QueryRow(`SELECT state, COALESCE(error, ''), started_at_ms FROM curator_job WHERE job_type=?
ORDER BY started_at_ms DESC, rowid DESC LIMIT 1`, localMatchTask).Scan(&state, &failure, &started)
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	if state == "failed" || state == "cancelled" {
		return false, fmt.Errorf("Checking your library failed: %s. Retry the Prepare local scene matches task", failure)
	}
	// Polling must remain read-only while the worker holds the index write lock.
	if (state == "queued" || state == "running") && started > nowMs()-6*3_600_000 {
		return false, nil
	}
	_, err = runTaskBody(pluginDir, payload, localMatchTask, settings)
	return false, err
}

const localMatchPageQuery = `query CuratorLocalSceneMatches($page: Int!, $perPage: Int!) {
 findScenes(filter: {page: $page, per_page: $perPage, sort: "id", direction: ASC}) {
  count scenes {` + localMatchFields + `}
 }
}`

const localMatchIDsQuery = `query CuratorLocalSceneMatchesByIds($ids: [ID!]) {
 findScenes(ids: $ids, filter: {per_page: -1}) { scenes {` + localMatchFields + `} }
}`

// Keep matching facts separate from model source hashes: fingerprint changes
// and metadata edits must not force each other's caches to rebuild.
func writeLocalSceneMatch(conn *sql.Conn, scene jVal) error {
	id := pythonStrOrEmpty(scene.get("id"))
	if id == "" {
		return fmt.Errorf("local scene match is missing an id")
	}
	values := map[string]map[string]bool{"stashdb_id": {}, "phash": {}}
	for _, stashID := range scene.get("stash_ids").arr {
		if strings.EqualFold(strings.TrimRight(stashID.get("endpoint").asString(), "/"), "https://stashdb.org/graphql") {
			if value := pythonStrOrEmpty(stashID.get("stash_id")); value != "" {
				values["stashdb_id"][value] = true
			}
		}
	}
	for _, file := range scene.get("files").arr {
		for _, fingerprint := range file.get("fingerprints").arr {
			if strings.EqualFold(fingerprint.get("type").asString(), "phash") {
				if value, ok := normalizePhash(fingerprint.get("value")); ok {
					values["phash"][value] = true
				}
			}
		}
	}
	ctx := context.Background()
	for _, kind := range []string{"stashdb_id", "phash"} {
		ordered := make([]string, 0, len(values[kind]))
		for value := range values[kind] {
			ordered = append(ordered, value)
		}
		sort.Strings(ordered)
		wanted := jvArr()
		for _, value := range ordered {
			wanted.arr = append(wanted.arr, jvStr(value))
		}
		if _, err := conn.ExecContext(ctx, `DELETE FROM local_scene_match
WHERE scene_id=? AND kind=? AND value NOT IN (SELECT value FROM json_each(?))`, id, kind, wanted.marshalCompact()); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx, `INSERT OR IGNORE INTO local_scene_match(scene_id, kind, value)
SELECT ?, ?, value FROM json_each(?)`, id, kind, wanted.marshalCompact()); err != nil {
			return err
		}
	}
	return nil
}

func queueLocalSceneMatch(conn *sql.Conn, id string) error {
	_, err := conn.ExecContext(context.Background(), `INSERT INTO local_scene_match_pending(scene_id, revision)
VALUES (?, ?) ON CONFLICT(scene_id) DO UPDATE SET revision=excluded.revision`, id, uuid4())
	return err
}

func backfillLocalSceneMatches(db dbx, base string, headers map[string]string, progress func(processed, total int)) error {
	var ready string
	err := db.QueryRow(`SELECT value FROM application_meta WHERE key='local_scene_matches_ready'`).Scan(&ready)
	if err == nil {
		return nil
	}
	if err != sql.ErrNoRows {
		return err
	}
	var scenes []jVal
	err = pythonSpan("local_matches.fetch", func() error {
		for page := int64(1); ; page++ {
			data, err := graphqlQuery(base, headers, localMatchPageQuery,
				jvObj(jvKey("page", jvInt(page)), jvKey("perPage", jvInt(1000))))
			if err != nil {
				return err
			}
			root := data.get("findScenes")
			if root.get("scenes").kind != jArr || root.get("count").kind != jNum {
				return fmt.Errorf("Stash did not return local scene matches")
			}
			items := root.get("scenes").arr
			if len(items) == 0 && int64(len(scenes)) < pythonInt(root.get("count")) {
				return fmt.Errorf("Stash returned an incomplete local scene match page")
			}
			scenes = append(scenes, items...)
			if progress != nil {
				progress(len(scenes), int(pythonInt(root.get("count"))))
			}
			if page*1000 >= pythonInt(root.get("count")) {
				if int64(len(scenes)) < pythonInt(root.get("count")) {
					return fmt.Errorf("Stash returned an incomplete local scene match page")
				}
				break
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	return pythonSpan("local_matches.index", func() error {
		return withTxn(db, func(conn *sql.Conn) error {
			var existing string
			err := conn.QueryRowContext(context.Background(), `SELECT value FROM application_meta WHERE key='local_scene_matches_ready'`).Scan(&existing)
			if err == nil {
				return nil
			}
			if err != sql.ErrNoRows {
				return err
			}
			if _, err := conn.ExecContext(context.Background(), `DELETE FROM local_scene_match`); err != nil {
				return err
			}
			for _, scene := range scenes {
				if err := writeLocalSceneMatch(conn, scene); err != nil {
					return err
				}
			}
			_, err = conn.ExecContext(context.Background(), `INSERT OR IGNORE INTO application_meta(key,value)
VALUES ('local_scene_matches_ready','1')`)
			return err
		})
	})
}

func refreshPendingLocalSceneMatches(db dbx, base string, headers map[string]string) error {
	rows, err := db.Query(`SELECT scene_id, revision FROM local_scene_match_pending ORDER BY scene_id`)
	if err != nil {
		return err
	}
	type pendingMatch struct {
		id       string
		revision string
	}
	var pending []pendingMatch
	for rows.Next() {
		var item pendingMatch
		if err := rows.Scan(&item.id, &item.revision); err != nil {
			rows.Close()
			return err
		}
		pending = append(pending, item)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for start := 0; start < len(pending); start += 200 {
		batch := pending[start:minInt(start+200, len(pending))]
		ids := jvArr()
		for _, item := range batch {
			ids.arr = append(ids.arr, jvStr(item.id))
		}
		data, err := graphqlQuery(base, headers, localMatchIDsQuery, jvObj(jvKey("ids", ids)))
		byID := map[string]jVal{}
		if err != nil {
			if !strings.Contains(err.Error(), "scene with id ") || !strings.Contains(err.Error(), " not found") {
				return err
			}
			// Stash rejects the whole ID batch if a queued scene was deleted; singular lookups return null.
			declarations, fields := make([]string, len(batch)), make([]string, len(batch))
			variables := jvObj()
			for index, item := range batch {
				key := fmt.Sprintf("s%d", index)
				declarations[index] = "$" + key + ": ID!"
				fields[index] = fmt.Sprintf("%s: findScene(id: $%s) {%s}", key, key, localMatchFields)
				variables.set(key, jvStr(item.id))
			}
			query := "query CuratorLocalSceneMatchesByIds(" + strings.Join(declarations, ", ") + ") { " + strings.Join(fields, " ") + " }"
			data, err = graphqlQuery(base, headers, query, variables)
			if err != nil {
				return err
			}
			for index, item := range batch {
				key := fmt.Sprintf("s%d", index)
				if !data.has(key) {
					return fmt.Errorf("Stash did not return changed local scene matches")
				}
				if scene := data.get(key); scene.kind != jNull {
					byID[item.id] = scene
				}
			}
		} else {
			items := data.get("findScenes").get("scenes")
			if items.kind != jArr {
				return fmt.Errorf("Stash did not return changed local scene matches")
			}
			for _, scene := range items.arr {
				id := pythonStrOrEmpty(scene.get("id"))
				if id == "" {
					return fmt.Errorf("local scene match is missing an id")
				}
				byID[id] = scene
			}
		}
		if err := withTxn(db, func(conn *sql.Conn) error {
			for _, item := range batch {
				var revision string
				err := conn.QueryRowContext(context.Background(), `SELECT revision FROM local_scene_match_pending WHERE scene_id=?`, item.id).Scan(&revision)
				if err == sql.ErrNoRows {
					continue
				}
				if err != nil {
					return err
				}
				// A newer hook must survive a fetch that started before its mutation.
				if revision != item.revision {
					continue
				}
				if scene, exists := byID[item.id]; exists {
					if err := writeLocalSceneMatch(conn, scene); err != nil {
						return err
					}
				} else if _, err := conn.ExecContext(context.Background(), `DELETE FROM local_scene_match WHERE scene_id=?`, item.id); err != nil {
					return err
				}
				if _, err := conn.ExecContext(context.Background(), `DELETE FROM local_scene_match_pending WHERE scene_id=? AND revision=?`, item.id, item.revision); err != nil {
					return err
				}
			}
			return nil
		}); err != nil {
			return err
		}
	}
	return nil
}

func localSceneLinks(payload jVal, db dbx) (jVal, error) {
	defer recordStageSpan("local_matches.load", time.Now())
	base, headers := stashConnection(payload)
	if err := backfillLocalSceneMatches(db, base, headers, nil); err != nil {
		return jvNull(), err
	}
	if err := pythonSpan("local_matches.pending", func() error { return refreshPendingLocalSceneMatches(db, base, headers) }); err != nil {
		return jvNull(), err
	}
	rows, err := db.Query(`SELECT scene_id, kind, value FROM local_scene_match ORDER BY CAST(scene_id AS INTEGER), scene_id, kind, value`)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	ids, phashes := jvObj(), jvObj()
	seenIDs, seenHashes := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var id, kind, value string
		if err := rows.Scan(&id, &kind, &value); err != nil {
			return jvNull(), err
		}
		if kind == "stashdb_id" && !seenIDs[value] {
			ids.obj = append(ids.obj, jvKey(value, jvStr(id)))
			seenIDs[value] = true
		} else if kind == "phash" && !seenHashes[value] {
			phashes.obj = append(phashes.obj, jvKey(value, jvStr(id)))
			seenHashes[value] = true
		}
	}
	return jvObj(jvKey("scene_ids", ids), jvKey("scene_phashes", phashes)), rows.Err()
}
