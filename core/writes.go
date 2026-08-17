// Slice-3 interactive write ops — ports of backend.py's _api write branches
// and the service layers behind them: ExpandService.shortlist
// (update_shortlist), InteractionStore (submit_feedback, correct_feedback,
// submit_tag_preferences, submit_events), and CuratorAPI.update_config.
// Every write runs inside BEGIN IMMEDIATE transactions with Python's exact
// SQL, error messages, and ModelUpdateCoordinator.request signaling.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"
)

// feedbackTypes mirrors interactions.py FEEDBACK_TYPES.
var feedbackTypes = map[string]bool{
	"thumb_up":       true,
	"thumb_down":     true,
	"not_now":        true,
	"never_show":     true,
	"prune":          true,
	"metadata_wrong": true,
}

// tagSentimentValues mirrors interactions.py TAG_SENTIMENT_VALUES.
var tagSentimentValues = map[float64]bool{-1.0: true, -0.5: true, 0.0: true, 0.5: true, 1.0: true}

const blockedTagValue = -1.0

// coordinatorRequest mirrors ModelUpdateCoordinator.request's write: bump the
// generation counter inside the caller's transaction, stamping requested_at_ms
// only when the model was previously clean.
func coordinatorRequest(conn *sql.Conn, cause string, nowMs int64) error {
	if cause == "" {
		return fmt.Errorf("update cause must not be empty")
	}
	_, err := conn.ExecContext(context.Background(), `
UPDATE model_update_state SET
    requested_generation=requested_generation+1,
    requested_at_ms=CASE
        WHEN requested_generation=published_generation THEN ?
        ELSE requested_at_ms
    END,
    last_cause=?
WHERE singleton=1`, nowMs, cause)
	return err
}

// ── update_shortlist ────────────────────────────────────────────────────────

func opUpdateShortlist(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "update_shortlist",
		func(settings jVal) (jVal, error) { return updateShortlistBody(pluginDir, payload, settings) })
}

func updateShortlistBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	entityType := pythonStrOrEmpty(args.get("entity_type"))
	externalID := pythonStrOrEmpty(args.get("external_id"))
	selected := args.get("selected").truthy()
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	if entityType != "scene" && entityType != "performer" {
		return jvNull(), fmt.Errorf("invalid shortlist entity type")
	}
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if !selected {
			_, err := conn.ExecContext(ctx,
				`DELETE FROM external_shortlist WHERE entity_type=? AND external_id=?`,
				entityType, externalID)
			return err
		}
		var payloadJSON, score, sourcesJSON string
		err := conn.QueryRowContext(ctx,
			`SELECT payload_json, score, sources_json FROM external_entity WHERE entity_type=? AND external_id=?`,
			entityType, externalID).Scan(&payloadJSON, &score, &sourcesJSON)
		if err == sql.ErrNoRows {
			return fmt.Errorf("external entity is not in the current Expand cache")
		}
		if err != nil {
			return err
		}
		_, err = conn.ExecContext(ctx, `
INSERT INTO external_shortlist(
  entity_type, external_id, payload_json, score, sources_json, added_at_ms
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(entity_type, external_id) DO UPDATE SET
  payload_json=excluded.payload_json, score=excluded.score,
  sources_json=excluded.sources_json`,
			entityType, externalID, payloadJSON, score, sourcesJSON, nowMs())
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("entity_type", jvStr(entityType)),
		jvKey("external_id", jvStr(externalID)),
		jvKey("selected", jvBool(selected)),
	), nil
}

// ── feedback ────────────────────────────────────────────────────────────────

type feedbackEntry struct {
	feedbackID    string
	sceneID       string
	feedbackType  string
	value         string
	hasValue      bool
	occurredAtMs  int64
	impressionID  string
	hasImpression bool
	payload       jVal
}

// normalizeFeedbackEntry mirrors InteractionStore._feedback_entry.
func normalizeFeedbackEntry(entry jVal) (feedbackEntry, error) {
	feedbackType := pythonStrOrEmpty(entry.get("feedback_type"))
	if !feedbackTypes[feedbackType] {
		return feedbackEntry{}, fmt.Errorf("unknown feedback type: %s", feedbackType)
	}
	feedbackID := pythonStrOrEmpty(entry.get("feedback_id"))
	sceneID := pythonStrOrEmpty(entry.get("scene_id"))
	occurredAtMs := pythonIntErrOr(entry.get("occurred_at_ms"), -1)
	if feedbackID == "" || sceneID == "" || occurredAtMs < 0 {
		return feedbackEntry{}, fmt.Errorf("feedback_id, scene_id, and occurred_at_ms are required")
	}
	out := feedbackEntry{
		feedbackID:   feedbackID,
		sceneID:      sceneID,
		feedbackType: feedbackType,
		occurredAtMs: occurredAtMs,
		payload:      jvObj(),
	}
	if v := entry.get("value"); v.kind != jNull {
		out.value = v.asString()
		out.hasValue = true
	}
	if v := entry.get("impression_id"); v.truthy() {
		out.impressionID = v.asString()
		out.hasImpression = true
	}
	if v := entry.get("payload"); v.kind == jObj {
		out.payload = v
	}
	return out, nil
}

// applyFeedback mirrors InteractionStore._apply_feedback.
func applyFeedback(conn *sql.Conn, entry feedbackEntry) error {
	ctx := context.Background()
	switch entry.feedbackType {
	case "never_show":
		if _, err := conn.ExecContext(ctx, `
INSERT INTO exclusion(
    exclusion_id, entity_type, entity_id, exclusion_type, created_at_ms
) VALUES (?, 'scene', ?, 'never_show', ?)
ON CONFLICT(entity_type, entity_id, exclusion_type) DO UPDATE SET
    created_at_ms=excluded.created_at_ms, reversed_at_ms=NULL, expires_at_ms=NULL`,
			"exclusion:"+entry.sceneID, entry.sceneID, entry.occurredAtMs); err != nil {
			return err
		}
		return reopenPruning(conn, entry, "Never show")
	case "thumb_down":
		return reopenPruning(conn, entry, "Thumbs down")
	case "prune":
		_, err := conn.ExecContext(ctx, `
INSERT INTO pruning_candidate(
    scene_id, state, created_at_ms, updated_at_ms, reason
) VALUES (?, 'review', ?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET state='review',
    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason`,
			entry.sceneID, entry.occurredAtMs, entry.occurredAtMs, entry.value)
		return err
	}
	return nil
}

// reopenPruning mirrors InteractionStore._reopen_pruning.
func reopenPruning(conn *sql.Conn, entry feedbackEntry, reason string) error {
	_, err := conn.ExecContext(context.Background(), `
INSERT INTO pruning_candidate(scene_id, state, created_at_ms, updated_at_ms, reason)
VALUES (?, 'review', ?, ?, ?)
ON CONFLICT(scene_id) DO UPDATE SET state='review',
    updated_at_ms=excluded.updated_at_ms, reason=excluded.reason`,
		entry.sceneID, entry.occurredAtMs, entry.occurredAtMs, reason)
	return err
}

func opSubmitFeedback(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_feedback",
		func(settings jVal) (jVal, error) { return submitFeedbackBody(pluginDir, payload, settings) })
}

func submitFeedbackBody(pluginDir string, payload, settings jVal) (jVal, error) {
	entries := payload.get("args").get("entries")
	if !isList(entries) {
		return jvNull(), fmt.Errorf("entries must be a list")
	}
	normalized := make([]feedbackEntry, len(entries.arr))
	for i, entry := range entries.arr {
		item, err := normalizeFeedbackEntry(entry)
		if err != nil {
			return jvNull(), err
		}
		normalized[i] = item
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	inserted := int64(0)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, entry := range normalized {
			res, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    impression_id, payload_json
) VALUES (?, ?, ?, ?, ?, ?, ?)`,
				entry.feedbackID, entry.sceneID, entry.feedbackType, sqlNullable(entry.value, entry.hasValue),
				entry.occurredAtMs, sqlNullable(entry.impressionID, entry.hasImpression),
				entry.payload.marshalSortedKeys())
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
			if err := applyFeedback(conn, entry); err != nil {
				return err
			}
		}
		if inserted > 0 {
			return coordinatorRequest(conn, "direct_feedback", nowMs())
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

// sqlNullable maps (value, has) to a SQL arg: NULL when unset.
func sqlNullable(value string, has bool) any {
	if !has {
		return nil
	}
	return value
}

func opCorrectFeedback(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "correct_feedback",
		func(settings jVal) (jVal, error) { return correctFeedbackBody(pluginDir, payload, settings) })
}

func correctFeedbackBody(pluginDir string, payload, settings jVal) (jVal, error) {
	args := payload.get("args")
	feedbackID := pythonStrOrEmpty(args.get("feedback_id"))
	correctionID := pythonStrOrEmpty(args.get("correction_id"))
	feedbackType := jvNull()
	if args.get("feedback_type").truthy() {
		feedbackType = jvStr(args.get("feedback_type").asString())
	}
	now := nowMs()
	if feedbackType.kind == jStr && !feedbackTypes[feedbackType.s] {
		return jvNull(), fmt.Errorf("unknown feedback type: %s", feedbackType.s)
	}
	if feedbackID == "" || correctionID == "" || now < 0 {
		return jvNull(), fmt.Errorf("feedback_id, correction_id, and occurred_at_ms are required")
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		var sceneID, originalType string
		var originalAtMs int64
		var reversedBy sql.NullString
		err := conn.QueryRowContext(ctx, `
SELECT scene_id, feedback_type, occurred_at_ms, reversed_by_id
FROM feedback WHERE feedback_id=?`, feedbackID).
			Scan(&sceneID, &originalType, &originalAtMs, &reversedBy)
		if err == sql.ErrNoRows {
			return fmt.Errorf("unknown feedback")
		}
		if err != nil {
			return err
		}
		if reversedBy.Valid {
			return fmt.Errorf("feedback was already corrected")
		}
		if now < originalAtMs {
			return fmt.Errorf("correction cannot predate feedback")
		}
		correctionType := "reversal"
		if feedbackType.kind == jStr {
			correctionType = feedbackType.s
		}
		correction := feedbackEntry{
			feedbackID:   correctionID,
			sceneID:      sceneID,
			feedbackType: correctionType,
			occurredAtMs: now,
			payload:      jvObj(jvKey("replaces_feedback_id", jvStr(feedbackID))),
		}
		payloadJSON := correction.payload.marshalCompact()
		if _, err := conn.ExecContext(ctx, `
INSERT INTO feedback(
    feedback_id, scene_id, feedback_type, value, occurred_at_ms,
    impression_id, payload_json
) VALUES (?, ?, ?, ?, ?, ?, ?)`,
			correctionID, sceneID, correctionType, nil, now, nil, payloadJSON); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx,
			`UPDATE feedback SET reversed_by_id=? WHERE feedback_id=?`,
			correctionID, feedbackID); err != nil {
			return err
		}
		if feedbackType.kind == jStr {
			if err := applyFeedback(conn, correction); err != nil {
				return err
			}
		}
		var activeNeverShow int
		err = conn.QueryRowContext(ctx, `
SELECT 1 FROM feedback
WHERE scene_id=? AND feedback_type='never_show' AND reversed_by_id IS NULL
LIMIT 1`, sceneID).Scan(&activeNeverShow)
		if err == sql.ErrNoRows {
			if _, err := conn.ExecContext(ctx, `
UPDATE exclusion SET reversed_at_ms=?
WHERE entity_type='scene' AND entity_id=? AND exclusion_type='never_show'
AND reversed_at_ms IS NULL`, now, sceneID); err != nil {
				return err
			}
		} else if err != nil {
			return err
		}
		if originalType == "thumb_down" || originalType == "never_show" || originalType == "prune" {
			var activeNegative int
			err = conn.QueryRowContext(ctx, `
SELECT 1 FROM feedback
WHERE scene_id=? AND feedback_type IN ('thumb_down', 'never_show', 'prune')
AND reversed_by_id IS NULL
LIMIT 1`, sceneID).Scan(&activeNegative)
			if err == sql.ErrNoRows {
				if _, err := conn.ExecContext(ctx,
					`DELETE FROM pruning_candidate WHERE scene_id=? AND state='review'`,
					sceneID); err != nil {
					return err
				}
			} else if err != nil {
				return err
			}
		}
		return coordinatorRequest(conn, "feedback_correction", now)
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("feedback_id", jvStr(feedbackID)),
		jvKey("correction_id", jvStr(correctionID)),
		jvKey("feedback_type", feedbackType),
	), nil
}

// ── tag preferences ─────────────────────────────────────────────────────────

type tagPreferenceEntry struct {
	preferenceID string
	tagID        string
	value        jVal // jvNull = None
	blocked      bool
	occurredAtMs int64
}

// normalizeTagPreferenceEntry mirrors InteractionStore._tag_preference_entry.
func normalizeTagPreferenceEntry(db dbx, entry jVal) (tagPreferenceEntry, error) {
	preferenceID := pythonStrOrEmpty(entry.get("preference_id"))
	tagID := pythonStrOrEmpty(entry.get("tag_id"))
	occurredAtMs := pythonIntErrOr(entry.get("occurred_at_ms"), -1)
	blocked := entry.get("blocked").truthy()
	value := entry.get("value")
	if value.kind != jNull {
		if value.kind == jBool || !isJSONNumber(value) {
			return tagPreferenceEntry{}, fmt.Errorf("tag sentiment must be numeric or null")
		}
		f, err := pythonFloat(value)
		if err != nil || !tagSentimentValues[f] {
			return tagPreferenceEntry{}, fmt.Errorf("tag sentiment must use the fixed five-point scale")
		}
		value = jvFloat(f)
	}
	if blocked {
		value = jvFloat(blockedTagValue)
	}
	if preferenceID == "" || tagID == "" || occurredAtMs < 0 {
		return tagPreferenceEntry{}, fmt.Errorf("preference_id, tag_id, and occurred_at_ms are required")
	}
	configVersion := "cfg-" + featureFingerprint()[:20]
	var one int
	err := db.QueryRow(`SELECT 1 FROM tag_role WHERE config_version=? AND tag_id=?`,
		configVersion, tagID).Scan(&one)
	if err == sql.ErrNoRows {
		return tagPreferenceEntry{}, fmt.Errorf("unknown or unsupported tag: %s", tagID)
	}
	if err != nil {
		return tagPreferenceEntry{}, err
	}
	return tagPreferenceEntry{
		preferenceID: preferenceID,
		tagID:        tagID,
		value:        value,
		blocked:      blocked,
		occurredAtMs: occurredAtMs,
	}, nil
}

func opSubmitTagPreferences(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_tag_preferences",
		func(settings jVal) (jVal, error) { return submitTagPreferencesBody(pluginDir, payload, settings) })
}

func submitTagPreferencesBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	normalized := make([]tagPreferenceEntry, len(entries.arr))
	for i, entry := range entries.arr {
		item, err := normalizeTagPreferenceEntry(db, entry)
		if err != nil {
			return jvNull(), err
		}
		normalized[i] = item
	}
	inserted := int64(0)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, entry := range normalized {
			var currentID string
			var currentAtMs int64
			currentErr := conn.QueryRowContext(ctx,
				`SELECT preference_id, occurred_at_ms FROM direct_tag_preference WHERE tag_id=?`,
				entry.tagID).Scan(&currentID, &currentAtMs)
			hasCurrent := currentErr == nil
			if currentErr != nil && currentErr != sql.ErrNoRows {
				return currentErr
			}
			valueArg := any(nil)
			if entry.value.kind != jNull {
				valueArg = pythonFloatOr(entry.value, 0)
			}
			res, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO direct_tag_preference_history(
    preference_id, tag_id, value, blocked, occurred_at_ms
) VALUES (?, ?, ?, ?, ?)`,
				entry.preferenceID, entry.tagID, valueArg, boolToInt(entry.blocked), entry.occurredAtMs)
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
			if hasCurrent && (currentAtMs > entry.occurredAtMs ||
				(currentAtMs == entry.occurredAtMs && currentID >= entry.preferenceID)) {
				if _, err := conn.ExecContext(ctx,
					`UPDATE direct_tag_preference_history SET replaced_by_id=? WHERE preference_id=?`,
					currentID, entry.preferenceID); err != nil {
					return err
				}
				continue
			}
			if hasCurrent {
				if _, err := conn.ExecContext(ctx,
					`UPDATE direct_tag_preference_history SET replaced_by_id=? WHERE preference_id=?`,
					entry.preferenceID, currentID); err != nil {
					return err
				}
			}
			if entry.value.kind == jNull {
				if _, err := conn.ExecContext(ctx,
					`DELETE FROM direct_tag_preference WHERE tag_id=?`, entry.tagID); err != nil {
					return err
				}
				continue
			}
			if _, err := conn.ExecContext(ctx, `
INSERT INTO direct_tag_preference(
    tag_id, preference_id, value, blocked, occurred_at_ms
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(tag_id) DO UPDATE SET
    preference_id=excluded.preference_id,
    value=excluded.value,
    blocked=excluded.blocked,
    occurred_at_ms=excluded.occurred_at_ms`,
				entry.tagID, entry.preferenceID, valueArg, boolToInt(entry.blocked), entry.occurredAtMs); err != nil {
				return err
			}
		}
		if inserted > 0 {
			return coordinatorRequest(conn, "direct_tag_preference", nowMs())
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

// ── submit_term_preferences ─────────────────────────────────────────────────

// termPreferenceEntry mirrors InteractionStore._term_preference_entry's output.
type termPreferenceEntry struct {
	preferenceID string
	term         string
	value        jVal // jvNull = None
	blocked      bool
	occurredAtMs int64
}

var termTokenRE = regexp.MustCompile(`^[a-zA-Z]{3,}$`)

// normalizeTermPreferenceEntry mirrors InteractionStore._term_preference_entry:
// the five-point scale and blocked semantics of tags, keyed by a lowercase
// description token (the tokenizer's [a-zA-Z]{3,} shape). Terms have no source
// table, so unlike tags there is no membership check — a preference for a term
// the current model has not qualified simply has no feature to blend into.
func normalizeTermPreferenceEntry(entry jVal) (termPreferenceEntry, error) {
	preferenceID := pythonStrOrEmpty(entry.get("preference_id"))
	term := strings.ToLower(strings.TrimSpace(pythonStrOrEmpty(entry.get("term"))))
	occurredAtMs := pythonIntErrOr(entry.get("occurred_at_ms"), -1)
	blocked := entry.get("blocked").truthy()
	value := entry.get("value")
	if value.kind != jNull {
		if value.kind == jBool || !isJSONNumber(value) {
			return termPreferenceEntry{}, fmt.Errorf("term sentiment must be numeric or null")
		}
		f, err := pythonFloat(value)
		if err != nil || !tagSentimentValues[f] {
			return termPreferenceEntry{}, fmt.Errorf("term sentiment must use the fixed five-point scale")
		}
		value = jvFloat(f)
	}
	if blocked {
		value = jvFloat(blockedTagValue)
	}
	if preferenceID == "" || term == "" || occurredAtMs < 0 {
		return termPreferenceEntry{}, fmt.Errorf("preference_id, term, and occurred_at_ms are required")
	}
	if !termTokenRE.MatchString(term) {
		return termPreferenceEntry{}, fmt.Errorf("term must be a description token ([a-zA-Z]{3,})")
	}
	return termPreferenceEntry{
		preferenceID: preferenceID,
		term:         term,
		value:        value,
		blocked:      blocked,
		occurredAtMs: occurredAtMs,
	}, nil
}

func opSubmitTermPreferences(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_term_preferences",
		func(settings jVal) (jVal, error) { return submitTermPreferencesBody(pluginDir, payload, settings) })
}

func submitTermPreferencesBody(pluginDir string, payload, settings jVal) (jVal, error) {
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
	normalized := make([]termPreferenceEntry, len(entries.arr))
	for i, entry := range entries.arr {
		item, err := normalizeTermPreferenceEntry(entry)
		if err != nil {
			return jvNull(), err
		}
		normalized[i] = item
	}
	inserted := int64(0)
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, entry := range normalized {
			var currentID string
			var currentAtMs int64
			currentErr := conn.QueryRowContext(ctx,
				`SELECT preference_id, occurred_at_ms FROM direct_term_preference WHERE term=?`,
				entry.term).Scan(&currentID, &currentAtMs)
			hasCurrent := currentErr == nil
			if currentErr != nil && currentErr != sql.ErrNoRows {
				return currentErr
			}
			valueArg := any(nil)
			if entry.value.kind != jNull {
				valueArg = pythonFloatOr(entry.value, 0)
			}
			res, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO direct_term_preference_history(
    preference_id, term, value, blocked, occurred_at_ms
) VALUES (?, ?, ?, ?, ?)`,
				entry.preferenceID, entry.term, valueArg, boolToInt(entry.blocked), entry.occurredAtMs)
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
			if hasCurrent && (currentAtMs > entry.occurredAtMs ||
				(currentAtMs == entry.occurredAtMs && currentID >= entry.preferenceID)) {
				if _, err := conn.ExecContext(ctx,
					`UPDATE direct_term_preference_history SET replaced_by_id=? WHERE preference_id=?`,
					currentID, entry.preferenceID); err != nil {
					return err
				}
				continue
			}
			if hasCurrent {
				if _, err := conn.ExecContext(ctx,
					`UPDATE direct_term_preference_history SET replaced_by_id=? WHERE preference_id=?`,
					entry.preferenceID, currentID); err != nil {
					return err
				}
			}
			if entry.value.kind == jNull {
				if _, err := conn.ExecContext(ctx,
					`DELETE FROM direct_term_preference WHERE term=?`, entry.term); err != nil {
					return err
				}
				continue
			}
			if _, err := conn.ExecContext(ctx, `
INSERT INTO direct_term_preference(
    term, preference_id, value, blocked, occurred_at_ms
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(term) DO UPDATE SET
    preference_id=excluded.preference_id,
    value=excluded.value,
    blocked=excluded.blocked,
    occurred_at_ms=excluded.occurred_at_ms`,
				entry.term, entry.preferenceID, valueArg, boolToInt(entry.blocked), entry.occurredAtMs); err != nil {
				return err
			}
		}
		if inserted > 0 {
			return coordinatorRequest(conn, "direct_term_preference", nowMs())
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

// ── events (qualified impressions + play sessions) ──────────────────────────

// pythonIntErrOr mirrors Python's int(entry.get(key, default)).
func pythonIntErrOr(v jVal, def int64) int64 {
	if v.kind == jNull {
		return def
	}
	n, err := pythonIntErr(v)
	if err != nil {
		return def
	}
	return n
}

// finite64 mirrors Python's math.isfinite.
func finite64(f float64) bool {
	return !math.IsInf(f, 0) && !math.IsNaN(f)
}

func opSubmitEvents(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "submit_events",
		func(settings jVal) (jVal, error) { return submitEventsBody(pluginDir, payload, settings) })
}

func submitEventsBody(pluginDir string, payload, settings jVal) (jVal, error) {
	entries := payload.get("args").get("entries")
	if !isList(entries) {
		return jvNull(), fmt.Errorf("entries must be a list")
	}
	var impressions, sessions []jVal
	for _, entry := range entries.arr {
		if entry.kind != jObj {
			return jvNull(), fmt.Errorf("'%s' object has no attribute 'get'", entry.kindName())
		}
		if entry.get("event_type").asString() == "qualified_impression" {
			impressions = append(impressions, entry)
		} else {
			sessions = append(sessions, entry)
		}
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	ensureAutoWorker(pluginDir, payload, settings, db)
	qualified, err := qualifyImpressions(db, impressions)
	if err != nil {
		return jvNull(), err
	}
	sessionCount, err := submitSessions(db, sessions)
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("accepted", jvInt(qualified+sessionCount)),
	), nil
}

// qualifyImpressions mirrors InteractionStore.qualify_impressions.
func qualifyImpressions(db dbx, entries []jVal) (int64, error) {
	type impressionEntry struct {
		impressionID string
		sceneID      string
		occurredAtMs int64
	}
	normalized := make([]impressionEntry, len(entries))
	for i, entry := range entries {
		impressionID := pythonStrOrEmpty(entry.get("impression_id"))
		sceneID := pythonStrOrEmpty(entry.get("scene_id"))
		occurredAtMs := pythonIntErrOr(entry.get("occurred_at_ms"), -1)
		if impressionID == "" || sceneID == "" || occurredAtMs < 0 {
			return 0, fmt.Errorf("impression_id, scene_id, and occurred_at_ms are required")
		}
		normalized[i] = impressionEntry{impressionID, sceneID, occurredAtMs}
	}
	inserted := int64(0)
	err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, entry := range normalized {
			res, err := conn.ExecContext(ctx, `
UPDATE impression_item SET qualified_at_ms=?
WHERE impression_id=? AND scene_id=? AND qualified_at_ms IS NULL`,
				entry.occurredAtMs, entry.impressionID, entry.sceneID)
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
			var lane string
			err = conn.QueryRowContext(ctx,
				`SELECT lane FROM impression WHERE impression_id=?`, entry.impressionID).Scan(&lane)
			if err == sql.ErrNoRows {
				return fmt.Errorf("") // Python's assert impression is not None
			}
			if err != nil {
				return err
			}
			if _, err := conn.ExecContext(ctx, `
INSERT INTO recommendation_history(
    history_id, scene_id, impression_id, lane, shown_at_ms
) VALUES (?, ?, ?, ?, ?)`,
				entry.impressionID+":"+entry.sceneID, entry.sceneID, entry.impressionID,
				lane, entry.occurredAtMs); err != nil {
				return err
			}
			inserted++
		}
		return nil
	})
	return inserted, err
}

type playedRange struct {
	start float64
	end   float64
}

type sessionInput struct {
	sessionID              string
	sceneID                string
	startedAtMs            int64
	endedAtMs              int64
	activeSeconds          float64
	origin                 string
	sourceRoute            string
	startPositionSeconds   float64
	maximumPositionSeconds float64
	finalPositionSeconds   float64
	playedRanges           []playedRange
	seekDestinations       []float64
	nearbyMarkerIDs        []string
	naturalCompletion      bool
	impressionID           string
	hasImpression          bool
	lane                   string
	hasLane                bool
	impressionPosition     int64
	hasImpressionPosition  bool
	modelID                string
	hasModelID             bool
}

// normalizeSession mirrors InteractionStore._session plus DirectSessionInput
// __post_init__ validation.
func normalizeSession(entry jVal) (sessionInput, error) {
	out := sessionInput{
		sessionID:              pythonStrOrEmpty(entry.get("session_id")),
		sceneID:                pythonStrOrEmpty(entry.get("scene_id")),
		startedAtMs:            pythonIntErrOr(entry.get("started_at_ms"), -1),
		endedAtMs:              pythonIntErrOr(entry.get("ended_at_ms"), -1),
		activeSeconds:          pythonFloatOr(entry.get("active_seconds"), 0),
		origin:                 pythonStrOrEmpty(entry.get("origin")),
		sourceRoute:            pythonStrOrEmpty(entry.get("source_route")),
		startPositionSeconds:   pythonFloatOr(entry.get("start_position_seconds"), 0),
		maximumPositionSeconds: pythonFloatOr(entry.get("maximum_position_seconds"), 0),
		finalPositionSeconds:   pythonFloatOr(entry.get("final_position_seconds"), 0),
		naturalCompletion:      entry.get("natural_completion").truthy(),
	}
	if out.origin == "" {
		out.origin = "stash"
	}
	if out.origin != "curator" && out.origin != "stash" {
		return sessionInput{}, fmt.Errorf("'%s' is not a valid SessionOrigin", out.origin)
	}
	for _, item := range entry.get("played_ranges").arr {
		startV := item.get("start_seconds")
		endV := item.get("end_seconds")
		if startV.kind == jNull {
			return sessionInput{}, fmt.Errorf("'start_seconds'")
		}
		if endV.kind == jNull {
			return sessionInput{}, fmt.Errorf("'end_seconds'")
		}
		start, err := pythonFloat(startV)
		if err != nil {
			return sessionInput{}, err
		}
		end, err := pythonFloat(endV)
		if err != nil {
			return sessionInput{}, err
		}
		if !finite64(start) || !finite64(end) || start < 0 || end < start {
			return sessionInput{}, fmt.Errorf("played range must be non-negative and ordered")
		}
		out.playedRanges = append(out.playedRanges, playedRange{start, end})
	}
	for _, v := range entry.get("seek_destinations_seconds").arr {
		f, err := pythonFloat(v)
		if err != nil {
			return sessionInput{}, err
		}
		out.seekDestinations = append(out.seekDestinations, f)
	}
	for _, v := range entry.get("nearby_marker_ids").arr {
		out.nearbyMarkerIDs = append(out.nearbyMarkerIDs, v.asString())
	}
	if v := entry.get("impression_id"); v.truthy() {
		out.impressionID = v.asString()
		out.hasImpression = true
	}
	if v := entry.get("lane"); v.truthy() {
		out.lane = v.asString()
		out.hasLane = true
	}
	if v := entry.get("impression_position"); v.kind != jNull {
		out.impressionPosition = pythonInt(v)
		out.hasImpressionPosition = true
	}
	if v := entry.get("model_id"); v.truthy() {
		out.modelID = v.asString()
		out.hasModelID = true
	}
	// DirectSessionInput.__post_init__
	if out.sessionID == "" || out.sceneID == "" {
		return sessionInput{}, fmt.Errorf("session_id and scene_id are required")
	}
	if out.startedAtMs < 0 || out.endedAtMs < out.startedAtMs {
		return sessionInput{}, fmt.Errorf("session timestamps must be non-negative and ordered")
	}
	positions := []float64{out.activeSeconds, out.startPositionSeconds,
		out.maximumPositionSeconds, out.finalPositionSeconds}
	positions = append(positions, out.seekDestinations...)
	for _, p := range positions {
		if !finite64(p) || p < 0 {
			return sessionInput{}, fmt.Errorf("session durations and positions must be non-negative")
		}
	}
	if out.hasImpressionPosition && out.impressionPosition < 0 {
		return sessionInput{}, fmt.Errorf("impression_position must be non-negative")
	}
	if out.origin == "curator" && !out.hasImpression {
		return sessionInput{}, fmt.Errorf("Curator-originated sessions require an impression_id")
	}
	return out, nil
}

// observedPlayback mirrors DirectSessionInput.observed_playback.
func (s *sessionInput) observedPlayback() bool {
	return s.activeSeconds > 0 || len(s.playedRanges) > 0 ||
		s.maximumPositionSeconds > s.startPositionSeconds
}

type outcomeSignal struct {
	signalType   string
	value        float64
	confidence   float64
	observedAtMs int64
	provenance   string
}

// viewingOutcome mirrors events.curves.viewing_outcome with the default
// calibration; the exp uses the glibc-faithful pyExp so the stored REAL
// outcome matches Python's math.exp bit for bit.
func viewingOutcome(activeSeconds float64, observedAtMs int64) (outcomeSignal, bool) {
	const threshold = 30.0
	var value float64
	if activeSeconds < threshold {
		value = -0.10 * (1 - activeSeconds/threshold)
	} else {
		value = 0.35 * (1 - math.Exp(-(activeSeconds-threshold)/90.0))
	}
	if mathAbs(value) < 1e-12 {
		return outcomeSignal{}, false
	}
	return outcomeSignal{"view", value, 0.80, observedAtMs, "direct_player"}, true
}

// quickReplacementOutcome mirrors events.replacements.quick_replacement_outcome
// with the default calibration and no resumed playback.
func quickReplacementOutcome(original, replacement sessionInput, positive bool) (outcomeSignal, bool) {
	elapsedSeconds := float64(replacement.startedAtMs-original.endedAtMs) / 1000
	disqualified := original.origin != "curator" ||
		original.activeSeconds >= 30.0 ||
		replacement.sceneID == original.sceneID ||
		elapsedSeconds < 0 ||
		elapsedSeconds > 300.0 ||
		positive
	if disqualified {
		return outcomeSignal{}, false
	}
	return outcomeSignal{"quick_replacement", -0.25, 0.90, replacement.startedAtMs, "direct_player"}, true
}

// insertSignal mirrors InteractionStore._insert_signal.
func insertSignal(conn *sql.Conn, eventID, sceneID string, sessionID any, signal outcomeSignal) (bool, error) {
	payload := jvObj(jvKey("primary_signal", jvStr(signal.signalType)))
	res, err := conn.ExecContext(context.Background(), `
INSERT OR IGNORE INTO behavior_event(
    event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
    provenance, session_id, payload_json
) VALUES (?, 'occasion_outcome', ?, ?, ?, ?, ?, ?, ?)`,
		eventID, sceneID, signal.observedAtMs, signal.value, signal.confidence,
		signal.provenance, sessionID, payload.marshalCompact())
	if err != nil {
		return false, err
	}
	rows, err := res.RowsAffected()
	return rows > 0, err
}

// insertReplacement mirrors InteractionStore._insert_replacement.
func insertReplacement(conn *sql.Conn, replacement sessionInput) (bool, error) {
	var summaryJSON string
	err := conn.QueryRowContext(context.Background(), `
SELECT summary_json FROM play_session
WHERE provenance='direct_player' AND session_id<>? AND ended_at_ms<=?
AND `+observedPlaybackSQL+`
ORDER BY ended_at_ms DESC LIMIT 1`,
		replacement.sessionID, replacement.startedAtMs).Scan(&summaryJSON)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	parsed, err := parseJSON([]byte(summaryJSON))
	if err != nil {
		return false, err
	}
	original, err := normalizeSession(parsed)
	if err != nil {
		return false, err
	}
	var one int
	err = conn.QueryRowContext(context.Background(), `
SELECT 1 FROM feedback WHERE scene_id=? AND feedback_type='thumb_up'
AND reversed_by_id IS NULL AND occurred_at_ms BETWEEN ? AND ? LIMIT 1`,
		original.sceneID, original.endedAtMs, replacement.startedAtMs).Scan(&one)
	positive := err == nil
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	signal, ok := quickReplacementOutcome(original, replacement, positive)
	if !ok {
		return false, nil
	}
	return insertSignal(conn, replacement.sessionID+":replacement",
		original.sceneID, original.sessionID, signal)
}

// submitSessions mirrors InteractionStore.submit_sessions.
func submitSessions(db dbx, entries []jVal) (int64, error) {
	sessions := make([]sessionInput, len(entries))
	for i, entry := range entries {
		session, err := normalizeSession(entry)
		if err != nil {
			return 0, err
		}
		sessions[i] = session
	}
	inserted := int64(0)
	signaled := false
	err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		for _, session := range sessions {
			summary := sessionSummaryJSON(session)
			res, err := conn.ExecContext(ctx, `
INSERT OR IGNORE INTO play_session(
    session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
    provenance, confidence, impression_id, summary_json
) VALUES (?, ?, ?, ?, ?, 'direct_player', 1, ?, ?)`,
				session.sessionID, session.sceneID, session.startedAtMs, session.endedAtMs,
				session.activeSeconds, session.impressionArg(), summary)
			if err != nil {
				// OR IGNORE does not cover foreign-key violations; a scene added
				// after the last sync is dropped like Python's IntegrityError path.
				continue
			}
			rows, err := res.RowsAffected()
			if err != nil {
				return err
			}
			if rows == 0 {
				continue
			}
			inserted++
			if session.observedPlayback() {
				if outcome, ok := viewingOutcome(session.activeSeconds, session.endedAtMs); ok {
					sig, err := insertSignal(conn, session.sessionID+":view",
						session.sceneID, session.sessionID, outcome)
					if err != nil {
						return err
					}
					signaled = signaled || sig
				}
			}
			sig, err := insertReplacement(conn, session)
			if err != nil {
				return err
			}
			signaled = signaled || sig
		}
		if signaled {
			return coordinatorRequest(conn, "session_outcome", nowMs())
		}
		return nil
	})
	return inserted, err
}

func (s *sessionInput) impressionArg() any {
	if s.hasImpression {
		return s.impressionID
	}
	return nil
}

func (s *sessionInput) impressionPositionPtr() *int64 {
	if !s.hasImpressionPosition {
		return nil
	}
	return &s.impressionPosition
}

// sessionSummaryJSON mirrors json.dumps(asdict(session), sort_keys=True,
// separators=(",", ":")): the DirectSessionInput fields serialized with
// sorted keys.
func sessionSummaryJSON(s sessionInput) string {
	ranges := jvArr()
	for _, r := range s.playedRanges {
		ranges.arr = append(ranges.arr, jvObj(
			jvKey("start_seconds", jvFloat(r.start)),
			jvKey("end_seconds", jvFloat(r.end)),
		))
	}
	seeks := jvArr()
	for _, v := range s.seekDestinations {
		seeks.arr = append(seeks.arr, jvFloat(v))
	}
	markers := jvArr()
	for _, id := range s.nearbyMarkerIDs {
		markers.arr = append(markers.arr, jvStr(id))
	}
	summary := jvObj(
		jvKey("active_seconds", jvFloat(s.activeSeconds)),
		jvKey("ended_at_ms", jvInt(s.endedAtMs)),
		jvKey("final_position_seconds", jvFloat(s.finalPositionSeconds)),
		jvKey("impression_id", optStrValue(s.impressionID, s.hasImpression)),
		jvKey("impression_position", jvOptionalInt(s.impressionPositionPtr())),
		jvKey("lane", optStrValue(s.lane, s.hasLane)),
		jvKey("maximum_position_seconds", jvFloat(s.maximumPositionSeconds)),
		jvKey("model_id", optStrValue(s.modelID, s.hasModelID)),
		jvKey("natural_completion", jvBool(s.naturalCompletion)),
		jvKey("nearby_marker_ids", markers),
		jvKey("origin", jvStr(s.origin)),
		jvKey("played_ranges", ranges),
		jvKey("scene_id", jvStr(s.sceneID)),
		jvKey("seek_destinations_seconds", seeks),
		jvKey("session_id", jvStr(s.sessionID)),
		jvKey("source_route", jvStr(s.sourceRoute)),
		jvKey("start_position_seconds", jvFloat(s.startPositionSeconds)),
		jvKey("started_at_ms", jvInt(s.startedAtMs)),
	)
	return summary.marshalSortedKeys()
}

func optStrValue(value string, has bool) jVal {
	if !has {
		return jvNull()
	}
	return jvStr(value)
}

// ── update_config ───────────────────────────────────────────────────────────

// allowedConfigKeys mirrors api.py's update_config allowed set.
var allowedConfigKeys = map[string]bool{
	"page_size":                              true,
	"diversity_enabled":                      true,
	"sync_page_size":                         true,
	"debounce_ms":                            true,
	"model_update_event_threshold":           true,
	"model_update_max_wait_minutes":          true,
	"model_update_min_interval_minutes":      true,
	"prune_tag_name":                         true,
	"expand_horizon_days":                    true,
	"expand_gender":                          true,
	"expand_wildcard":                        true,
	"auto_tasks_enabled":                     true,
	"schedule_expand_refresh_enabled":        true,
	"schedule_expand_refresh_interval_hours": true,
	"schedule_sync_build_enabled":            true,
	"schedule_sync_build_interval_hours":     true,
	"schedule_backup_enabled":                true,
	"schedule_backup_interval_hours":         true,
}

// pythonListRepr renders a []string like Python's repr of a list of strings.
func pythonListRepr(items []string) string {
	quoted := make([]string, len(items))
	for i, item := range items {
		quoted[i] = "'" + item + "'"
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

func opUpdateConfig(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "update_config",
		func(settings jVal) (jVal, error) { return updateConfigBody(pluginDir, payload, settings) })
}

func updateConfigBody(pluginDir string, payload, settings jVal) (jVal, error) {
	values := payload.get("args").get("values")
	if values.kind != jObj {
		return jvNull(), fmt.Errorf("values must be an object")
	}
	var unknown []string
	for _, pair := range values.obj {
		if !allowedConfigKeys[pair.key] {
			unknown = append(unknown, pair.key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return jvNull(), fmt.Errorf("unknown configuration keys: %s", pythonListRepr(unknown))
	}
	db, err := openAPISidecar(pluginDir, payload, settings)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	current, err := sidecarConfig(db)
	if err != nil {
		return jvNull(), err
	}
	cfg := current.get("config")
	merged := mergeObjects(cfg, values)
	if err := validateConfig(merged); err != nil {
		return jvNull(), err
	}
	if err := withTxn(db, func(conn *sql.Conn) error {
		_, err := conn.ExecContext(context.Background(),
			`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			merged.marshalSortedKeys(), nowMs())
		return err
	}); err != nil {
		return jvNull(), err
	}
	// A settings change may enable schedules or auto tasks — the worker must
	// exist to act on them; it reads the just-written config on its next tick.
	ensureAutoWorker(pluginDir, payload, settings, db)
	return sidecarConfig(db)
}
