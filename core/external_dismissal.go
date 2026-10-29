// update_external_dismissal / get_external_dismissals: hiding StashDB scenes
// from Find (ExpandService.dismiss, dismissal_results, dismissed_scene_ids).
package main

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
)

// dismissedScenes mirrors ExpandService.dismissed_scenes: kind by external id
// for Not interested, or a Not now that has not expired.
func dismissedScenes(db dbx) (map[string]string, error) {
	rows, err := db.Query(`SELECT external_id, kind FROM external_dismissal WHERE endpoint=lower(?)
AND (expires_at_ms IS NULL OR expires_at_ms>?)`, stashdbEndpoint, nowMs())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	dismissed := map[string]string{}
	for rows.Next() {
		var externalID, kind string
		if err := rows.Scan(&externalID, &kind); err != nil {
			return nil, err
		}
		dismissed[externalID] = kind
	}
	return dismissed, rows.Err()
}

// dismissedValue is an item's "dismissed" field: its kind, or null.
func dismissedValue(dismissed map[string]string, externalID string) jVal {
	if kind, ok := dismissed[externalID]; ok {
		return jvStr(kind)
	}
	return jvNull()
}

func opUpdateExternalDismissal(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "update_external_dismissal",
		func(settings jVal) (jVal, error) { return updateExternalDismissalBody(pluginDir, payload, settings) })
}

func updateExternalDismissalBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	externalID := pythonStrOrEmpty(args.get("external_id"))
	kind := ""
	if args.get("kind").truthy() {
		kind = pythonStrOrEmpty(args.get("kind"))
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	if kind != "" && kind != "not_interested" && kind != "not_now" {
		return jvNull(), fmt.Errorf("invalid dismissal kind")
	}
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if kind == "" {
			_, err := conn.ExecContext(ctx,
				`DELETE FROM external_dismissal WHERE endpoint=lower(?) AND external_id=?`,
				stashdbEndpoint, externalID)
			return err
		}
		var payloadJSON string
		err := conn.QueryRowContext(ctx,
			`SELECT payload_json FROM external_entity WHERE entity_type='scene' AND external_id=?`,
			externalID).Scan(&payloadJSON)
		if err == sql.ErrNoRows {
			return fmt.Errorf("external entity is not in the current Expand cache")
		}
		if err != nil {
			return err
		}
		stored, err := parseJSON([]byte(payloadJSON))
		if err != nil {
			return err
		}
		source := pythonStrOrEmpty(stored.get("curator_endpoint"))
		if source == "" {
			source = "https://stashdb.org/graphql"
		}
		if !strings.EqualFold(strings.TrimRight(source, "/"), stashdbEndpoint) {
			return fmt.Errorf("external entity is not in the selected endpoint's cache")
		}
		now := nowMs()
		var expiresAtMs any
		if kind == "not_now" {
			expiresAtMs = now + int64(notNowDays*86_400_000)
		}
		_, err = conn.ExecContext(ctx, `
INSERT INTO external_dismissal(
  endpoint, external_id, kind, created_at_ms, expires_at_ms, payload_json
) VALUES (lower(?), ?, ?, ?, ?, ?)
ON CONFLICT(endpoint, external_id) DO UPDATE SET
  kind=excluded.kind, created_at_ms=excluded.created_at_ms,
  expires_at_ms=excluded.expires_at_ms, payload_json=excluded.payload_json`,
			stashdbEndpoint, externalID, kind, now, expiresAtMs, payloadJSON)
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	kindVal := jvNull()
	if kind != "" {
		kindVal = jvStr(kind)
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("external_id", jvStr(externalID)),
		jvKey("kind", kindVal),
	), nil
}

func opGetExternalDismissals(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_external_dismissals",
		func(settings jVal) (jVal, error) { return getExternalDismissalsBody(pluginDir, payload, settings) })
}

func getExternalDismissalsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	page := argsInt(args, "page", 1)
	count := argsInt(args, "page_size", 20)
	if page < 1 || count < 1 || count > 100 {
		return jvNull(), fmt.Errorf("invalid dismissal page")
	}
	const active = `d.endpoint=lower(?) AND (d.expires_at_ms IS NULL OR d.expires_at_ms>?)`
	now := nowMs()
	var total int64
	if err := db.QueryRow(`SELECT count(*) FROM external_dismissal d WHERE `+active, stashdbEndpoint, now).Scan(&total); err != nil {
		return jvNull(), err
	}
	// Card-shaped like Expand items; the score and sources come from the
	// candidate cache while the scene is still in it.
	rows, err := db.Query(`SELECT d.external_id, d.kind, d.created_at_ms, d.expires_at_ms, d.payload_json,
e.score, e.sources_json FROM external_dismissal d
LEFT JOIN external_entity e ON e.entity_type='scene' AND e.external_id=d.external_id WHERE `+active+`
ORDER BY d.created_at_ms DESC, d.external_id DESC LIMIT ? OFFSET ?`, stashdbEndpoint, now, count, (page-1)*count)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var externalID, kind, payloadJSON string
		var createdAtMs int64
		var expiresAtMs sql.NullInt64
		var score sql.NullFloat64
		var sourcesJSON sql.NullString
		if err := rows.Scan(&externalID, &kind, &createdAtMs, &expiresAtMs, &payloadJSON, &score, &sourcesJSON); err != nil {
			return jvNull(), err
		}
		sources := jvArr()
		if sourcesJSON.Valid && sourcesJSON.String != "" {
			if sources, err = parseJSON([]byte(sourcesJSON.String)); err != nil {
				return jvNull(), err
			}
		}
		stored, err := parseJSON([]byte(payloadJSON))
		if err != nil {
			return jvNull(), err
		}
		expires := jvNull()
		if expiresAtMs.Valid {
			expires = jvInt(expiresAtMs.Int64)
		}
		items.arr = append(items.arr, jvObj(
			jvKey("id", jvStr(externalID)),
			jvKey("score", jvFloat(score.Float64)),
			jvKey("sources", sources),
			jvKey("payload", stored),
			jvKey("kind", jvStr(kind)),
			jvKey("created_at_ms", jvInt(createdAtMs)),
			jvKey("expires_at_ms", expires),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("ready", jvBool(true)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(total)),
		jvKey("has_more", jvBool(page*count < total)),
		jvKey("items", items),
	), nil
}

// ── submit_external_scene_reasons ───────────────────────────────────────────

var externalSceneReasonSubjects = map[string]bool{"performer": true, "tag": true, "studio": true}

// normalizeExternalSceneReasonEntry mirrors
// InteractionStore._external_scene_reason_entry.
func normalizeExternalSceneReasonEntry(entry jVal) (sceneReasonEntry, error) {
	answerID := pythonStrOrEmpty(entry.get("answer_id"))
	externalID := pythonStrOrEmpty(entry.get("external_id"))
	occurredAtMs := pythonIntErrOr(entry.get("occurred_at_ms"), -1)
	if answerID == "" || externalID == "" || occurredAtMs < 0 {
		return sceneReasonEntry{}, fmt.Errorf("answer_id, external_id, and occurred_at_ms are required")
	}
	polarity := entry.get("polarity")
	if !isJSONInt(polarity) || (polarity.num != "1" && polarity.num != "-1") {
		return sceneReasonEntry{}, fmt.Errorf("polarity must be 1 or -1")
	}
	reasons := entry.get("reasons")
	if !isList(reasons) || len(reasons.arr) == 0 || len(reasons.arr) > sceneReasonLimit {
		return sceneReasonEntry{}, fmt.Errorf("reasons must be a list of 1 to 20 items")
	}
	subjects := make([]sceneReasonSubject, 0, len(reasons.arr))
	for _, reason := range reasons.arr {
		if reason.kind != jObj {
			return sceneReasonEntry{}, fmt.Errorf("each reason must be an object")
		}
		kind := pythonStrOrEmpty(reason.get("subject_type"))
		if !externalSceneReasonSubjects[kind] {
			return sceneReasonEntry{}, fmt.Errorf("unsupported reason subject: %s", kind)
		}
		subject := pythonStrOrEmpty(reason.get("subject_id"))
		if subject == "" {
			return sceneReasonEntry{}, fmt.Errorf("reason subject_id is required")
		}
		subjects = append(subjects, sceneReasonSubject{kind: kind, id: subject})
	}
	value := int64(1)
	if polarity.num == "-1" {
		value = -1
	}
	// sceneID carries the external id; there is no library scene.
	return sceneReasonEntry{answerID: answerID, sceneID: externalID, polarity: value,
		reasons: subjects, occurredAtMs: occurredAtMs}, nil
}

func opSubmitExternalSceneReasons(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_external_scene_reasons",
		func(settings jVal) (jVal, error) { return submitExternalSceneReasonsBody(pluginDir, payload, settings) })
}

func submitExternalSceneReasonsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	entries := payload.get("args").get("entries")
	if !isList(entries) {
		return jvNull(), fmt.Errorf("entries must be a list")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	normalized := make([]sceneReasonEntry, len(entries.arr))
	for i, entry := range entries.arr {
		item, err := normalizeExternalSceneReasonEntry(entry)
		if err != nil {
			return jvNull(), err
		}
		normalized[i] = item
	}
	inserted := int64(0)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, entry := range normalized {
			res, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO external_scene_reason_answer(
    answer_id, endpoint, external_id, polarity, occurred_at_ms
) VALUES (?, lower(?), ?, ?, ?)`,
				entry.answerID, stashdbEndpoint, entry.sceneID, entry.polarity, entry.occurredAtMs)
			if err != nil {
				return err
			}
			rows, err := res.RowsAffected()
			if err != nil {
				return err
			}
			if rows == 0 {
				continue
			}
			inserted++
			for _, reason := range entry.reasons {
				if _, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO external_scene_reason(answer_id, subject_type, subject_id) VALUES (?, ?, ?)`,
					entry.answerID, reason.kind, reason.id); err != nil {
					return err
				}
			}
		}
		if inserted > 0 {
			return coordinatorRequest(conn, "scene_reason", nowMs())
		}
		return nil
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("accepted", jvInt(inserted)),
	), nil
}

// ── disliked StashDB performers ─────────────────────────────────────────────

// dislikedPerformerStrength mirrors DISLIKED_PERFORMER_STRENGTH.
const dislikedPerformerStrength = 0.5

// linkedPerformers mirrors builder.LINKED_PERFORMERS.
const linkedPerformers = `
SELECT link.key AS performer_id, link.value AS stash_id
FROM application_meta m, json_each(json_extract(m.value, '$.links.performers')) link
WHERE m.key='external_links'`

// dislikedPerformers mirrors ExpandService.disliked_performers: name by
// StashDB id.
func dislikedPerformers(db dbx) (map[string]string, error) {
	rows, err := db.Query(`SELECT performer_id, name FROM external_performer_dislike WHERE endpoint=lower(?)`, stashdbEndpoint)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	disliked := map[string]string{}
	for rows.Next() {
		var performerID, name string
		if err := rows.Scan(&performerID, &name); err != nil {
			return nil, err
		}
		disliked[performerID] = name
	}
	return disliked, rows.Err()
}

// withPerformerDislike mirrors ExpandService._with_performer_dislike: lower
// a scene's score for a cast member without a local profile the user is not
// into, naming them in the payload. The payload is changed in place.
func withPerformerDislike(payload jVal, score float64, disliked map[string]string) (jVal, float64) {
	if len(disliked) == 0 {
		return payload, score
	}
	cast := payload.get("performers").arr
	names := jvArr()
	for _, item := range cast {
		performer := item.get("performer")
		name, ok := disliked[pythonStrOrEmpty(performer.get("id"))]
		if !ok || performer.get("curator_local").truthy() {
			continue
		}
		if value := pythonStrOrEmpty(performer.get("name")); value != "" {
			name = value
		}
		names.arr = append(names.arr, jvStr(name))
	}
	if len(names.arr) == 0 {
		return payload, score
	}
	penalty := 0.25 * dislikedPerformerStrength * expandCastWeight(len(cast)) / 0.90
	payload.set("curator_performer_dislike", jvObj(jvKey("names", names), jvKey("penalty", jvFloat(penalty))))
	return payload, score - penalty
}

func opUpdateExternalPerformerDislike(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "update_external_performer_dislike",
		func(settings jVal) (jVal, error) { return updateExternalPerformerDislikeBody(pluginDir, payload, settings) })
}

func updateExternalPerformerDislikeBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	performerID := pythonStrOrEmpty(args.get("performer_id"))
	name := pythonStrOrEmpty(args.get("name"))
	disliked := args.get("disliked").truthy()
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	if performerID == "" {
		return jvNull(), fmt.Errorf("performer_id is required")
	}
	if name == "" {
		name = performerID
	}
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		var res sql.Result
		var err error
		if disliked {
			res, err = conn.ExecContext(ctx, `
INSERT INTO external_performer_dislike(endpoint, performer_id, name, created_at_ms)
VALUES (lower(?), ?, ?, ?)
ON CONFLICT(endpoint, performer_id) DO UPDATE SET name=excluded.name`,
				stashdbEndpoint, performerID, name, nowMs())
		} else {
			res, err = conn.ExecContext(ctx,
				`DELETE FROM external_performer_dislike WHERE endpoint=lower(?) AND performer_id=?`,
				stashdbEndpoint, performerID)
		}
		if err != nil {
			return err
		}
		changed, err := res.RowsAffected()
		if err != nil || changed == 0 {
			return err
		}
		// A performer already linked to the library is model evidence.
		var one int
		err = conn.QueryRowContext(ctx, `SELECT 1 FROM (`+linkedPerformers+`) WHERE stash_id=?`, performerID).Scan(&one)
		if err == sql.ErrNoRows {
			return nil
		}
		if err != nil {
			return err
		}
		return coordinatorRequest(conn, "scene_reason", nowMs())
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("performer_id", jvStr(performerID)),
		jvKey("disliked", jvBool(disliked)),
	), nil
}

func opGetExternalPerformerDislikes(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_external_performer_dislikes",
		func(settings jVal) (jVal, error) { return getExternalPerformerDislikesBody(pluginDir, payload, settings) })
}

func getExternalPerformerDislikesBody(pluginDir string, payload, settings jVal) (jVal, error) {
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	args := payload.get("args")
	page := argsInt(args, "page", 1)
	count := argsInt(args, "page_size", 20)
	if page < 1 || count < 1 || count > 100 {
		return jvNull(), fmt.Errorf("invalid performer dislike page")
	}
	var total int64
	if err := db.QueryRow(`SELECT count(*) FROM external_performer_dislike WHERE endpoint=lower(?)`, stashdbEndpoint).Scan(&total); err != nil {
		return jvNull(), err
	}
	rows, err := db.Query(`SELECT performer_id, name, created_at_ms FROM external_performer_dislike
WHERE endpoint=lower(?) ORDER BY created_at_ms DESC, performer_id DESC LIMIT ? OFFSET ?`,
		stashdbEndpoint, count, (page-1)*count)
	if err != nil {
		return jvNull(), err
	}
	defer rows.Close()
	items := jvArr()
	for rows.Next() {
		var performerID, name string
		var createdAtMs int64
		if err := rows.Scan(&performerID, &name, &createdAtMs); err != nil {
			return jvNull(), err
		}
		items.arr = append(items.arr, jvObj(
			jvKey("performer_id", jvStr(performerID)),
			jvKey("name", jvStr(name)),
			jvKey("created_at_ms", jvInt(createdAtMs)),
		))
	}
	if err := rows.Err(); err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("page", jvInt(page)),
		jvKey("page_size", jvInt(count)),
		jvKey("total", jvInt(total)),
		jvKey("has_more", jvBool(page*count < total)),
		jvKey("items", items),
	), nil
}
