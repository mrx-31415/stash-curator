// Which viewing Curator learns from. Curator keeps every play (player
// sessions, Stash's play history and the signals derived from them) and
// viewing_rule rows decide which of them count (migration 0054). Deciding
// rule for a play: the most specific rule covering it (one scene before all
// scenes), then the newest; with none the play counts. Readers that learn
// from viewing read the counted_* views, which apply the same order in SQL.
// Deliberate feedback such as thumbs, tag answers and dismissals is never
// affected.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sort"
)

const (
	choiceInclude = "include"
	choiceExclude = "exclude"
	reasonPaused  = "paused"
	reasonChosen  = "chosen"
)

// viewingRule is [startedAtMs, endedAtMs) for sceneID ("" = every scene);
// endedAtMs < 0 means still open.
type viewingRule struct {
	ruleID      int64
	sceneID     string
	startedAtMs int64
	endedAtMs   int64
	choice      string
	reason      string
	createdAtMs int64
}

func (r viewingRule) covers(sceneID string, atMs int64) bool {
	return (r.sceneID == "" || r.sceneID == sceneID) &&
		atMs >= r.startedAtMs && (r.endedAtMs < 0 || atMs < r.endedAtMs)
}

type rowQuerier interface {
	Query(query string, args ...any) (*sql.Rows, error)
}

type connQuerier struct{ conn *sql.Conn }

func (c connQuerier) Query(query string, args ...any) (*sql.Rows, error) {
	return c.conn.QueryContext(context.Background(), query, args...)
}

func loadViewingRules(db rowQuerier) ([]viewingRule, error) {
	rows, err := db.Query(`SELECT rule_id, COALESCE(scene_id, ''), started_at_ms,
COALESCE(ended_at_ms, -1), choice, reason, created_at_ms FROM viewing_rule ORDER BY rule_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var rules []viewingRule
	for rows.Next() {
		var r viewingRule
		if err := rows.Scan(&r.ruleID, &r.sceneID, &r.startedAtMs, &r.endedAtMs,
			&r.choice, &r.reason, &r.createdAtMs); err != nil {
			return nil, err
		}
		rules = append(rules, r)
	}
	return rules, rows.Err()
}

// decideViewing is the counted_* views' rule order in Go: nil when no rule
// covers the play.
func decideViewing(rules []viewingRule, sceneID string, atMs int64) *viewingRule {
	var best *viewingRule
	for i := range rules {
		r := &rules[i]
		if !r.covers(sceneID, atMs) {
			continue
		}
		if best == nil {
			best = r
			continue
		}
		specific, bestSpecific := r.sceneID != "", best.sceneID != ""
		if specific && !bestSpecific || specific == bestSpecific && r.ruleID > best.ruleID {
			best = r
		}
	}
	return best
}

func countedAt(rules []viewingRule, sceneID string, atMs int64) bool {
	rule := decideViewing(rules, sceneID, atMs)
	return rule == nil || rule.choice == choiceInclude
}

// syncLearningPause opens an exclude rule for every scene when the
// pauseLearning setting is on and none is open, and ends the open one when
// it is off. Runs on every sidecar open that carries the plugin settings.
func syncLearningPause(db dbx, settings jVal, nowMs int64) error {
	if settings.kind != jObj {
		return nil // a task or hook without settings: leave the state alone
	}
	paused := settings.get("pauseLearning").truthy()
	var openID, startedAt int64
	err := db.QueryRow(`SELECT rule_id, started_at_ms FROM viewing_rule
WHERE reason='paused' AND ended_at_ms IS NULL ORDER BY rule_id DESC LIMIT 1`).Scan(&openID, &startedAt)
	switch {
	case err != nil && !errors.Is(err, sql.ErrNoRows):
		return err
	case paused && errors.Is(err, sql.ErrNoRows):
		_, err = db.Exec(`INSERT INTO viewing_rule(scene_id, started_at_ms, ended_at_ms, choice, reason, created_at_ms)
VALUES (NULL, ?, NULL, 'exclude', 'paused', ?)`, nowMs, nowMs)
		return err
	case !paused && err == nil:
		_, err = db.Exec(`UPDATE viewing_rule SET ended_at_ms=? WHERE rule_id=?`, max(nowMs, startedAt+1), openID)
		return err
	}
	return nil
}

// viewingSpan is one watch, or a whole period when sceneID is "".
type viewingSpan struct {
	sceneID     string
	startedAtMs int64
	endedAtMs   int64 // exclusive
}

func ruleJSON(r viewingRule) jVal {
	scene, ended := jvNull(), jvNull()
	if r.sceneID != "" {
		scene = jvStr(r.sceneID)
	}
	if r.endedAtMs >= 0 {
		ended = jvInt(r.endedAtMs)
	}
	return jvObj(
		jvKey("rule_id", jvInt(r.ruleID)), jvKey("scene_id", scene),
		jvKey("started_at_ms", jvInt(r.startedAtMs)), jvKey("ended_at_ms", ended),
		jvKey("choice", jvStr(r.choice)), jvKey("reason", jvStr(r.reason)),
		jvKey("created_at_ms", jvInt(r.createdAtMs)),
	)
}

func ruleFromJSON(v jVal) (viewingRule, error) {
	r := viewingRule{
		ruleID:      pythonIntErrOr(v.get("rule_id"), -1),
		sceneID:     pythonStrOrEmpty(v.get("scene_id")),
		startedAtMs: pythonIntErrOr(v.get("started_at_ms"), -1),
		endedAtMs:   pythonIntErrOr(v.get("ended_at_ms"), -1),
		choice:      v.get("choice").asString(),
		reason:      v.get("reason").asString(),
		createdAtMs: pythonIntErrOr(v.get("created_at_ms"), -1),
	}
	if r.ruleID < 1 || r.startedAtMs < 0 || r.createdAtMs < 0 ||
		(r.choice != choiceInclude && r.choice != choiceExclude) ||
		(r.reason != reasonPaused && r.reason != reasonChosen) ||
		(r.endedAtMs >= 0 && r.endedAtMs <= r.startedAtMs) {
		return viewingRule{}, fmt.Errorf("invalid viewing rule")
	}
	return r, nil
}

// insertRule inserts r, keeping r.ruleID when it is set (undo restores a
// rule in its original place in the newest-wins order).
func insertRule(conn *sql.Conn, r viewingRule) (int64, error) {
	var ruleID, scene, ended any
	if r.ruleID > 0 {
		ruleID = r.ruleID
	}
	if r.sceneID != "" {
		scene = r.sceneID
	}
	if r.endedAtMs >= 0 {
		ended = r.endedAtMs
	}
	res, err := conn.ExecContext(context.Background(), `INSERT INTO viewing_rule(
    rule_id, scene_id, started_at_ms, ended_at_ms, choice, reason, created_at_ms
) VALUES (?, ?, ?, ?, ?, ?, ?)`, ruleID, scene, r.startedAtMs, ended, r.choice, r.reason, r.createdAtMs)
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

// viewingChange records what one choice did, so it can be undone exactly.
type viewingChange struct {
	added   []int64
	removed []viewingRule
	scenes  []string // the scenes touched; nil when a rule covers every scene
}

func (c viewingChange) undoJSON() jVal {
	added := jvArr()
	for _, id := range c.added {
		added.arr = append(added.arr, jvInt(id))
	}
	removed := jvArr()
	for _, r := range c.removed {
		removed.arr = append(removed.arr, ruleJSON(r))
	}
	return jvObj(jvKey("added_rule_ids", added), jvKey("removed_rules", removed))
}

type sceneCollector struct {
	scenes map[string]bool
	every  bool
}

func (s *sceneCollector) add(sceneID string) {
	if sceneID == "" {
		s.every = true
		return
	}
	if s.scenes == nil {
		s.scenes = map[string]bool{}
	}
	s.scenes[sceneID] = true
}

func (s *sceneCollector) list() []string {
	if s.every {
		return nil
	}
	out := []string{}
	for scene := range s.scenes {
		out = append(out, scene)
	}
	sort.Strings(out)
	return out
}

// setViewingChoice makes each watch (or period) count or not. A watch's own
// choice replaces any earlier choice for that watch and stands until the
// watch is changed again: pauses and period choices do not override it. A
// period choice covers every other play in it.
func setViewingChoice(conn *sql.Conn, choice string, spans []viewingSpan, nowMs int64) (viewingChange, error) {
	if choice != choiceInclude && choice != choiceExclude {
		return viewingChange{}, fmt.Errorf("choice must be include or exclude")
	}
	change := viewingChange{}
	touched := sceneCollector{}
	for _, span := range spans {
		if span.startedAtMs < 0 || span.endedAtMs <= span.startedAtMs {
			return viewingChange{}, fmt.Errorf("a viewing period must end after it starts")
		}
		touched.add(span.sceneID)
		rules, err := loadViewingRules(connQuerier{conn})
		if err != nil {
			return viewingChange{}, err
		}
		for _, r := range rules {
			// A watch's earlier choice it overlaps, or an earlier period
			// choice it covers whole (which could no longer decide anything:
			// the newer rule wins). Every-scene lookups stay short that way.
			replaced := span.sceneID != "" && r.sceneID == span.sceneID &&
				r.startedAtMs < span.endedAtMs && (r.endedAtMs < 0 || r.endedAtMs > span.startedAtMs)
			covered := span.sceneID == "" && r.sceneID == "" && r.reason == reasonChosen &&
				r.startedAtMs >= span.startedAtMs && r.endedAtMs >= 0 && r.endedAtMs <= span.endedAtMs
			if !replaced && !covered {
				continue
			}
			if _, err := conn.ExecContext(context.Background(), `DELETE FROM viewing_rule WHERE rule_id=?`, r.ruleID); err != nil {
				return viewingChange{}, err
			}
			change.removed = append(change.removed, r)
		}
		id, err := insertRule(conn, viewingRule{sceneID: span.sceneID, startedAtMs: span.startedAtMs,
			endedAtMs: span.endedAtMs, choice: choice, reason: reasonChosen, createdAtMs: nowMs})
		if err != nil {
			return viewingChange{}, err
		}
		change.added = append(change.added, id)
	}
	change.scenes = touched.list()
	return change, nil
}

// undoViewingChoice reverses one setViewingChoice from its undoJSON. Only
// chosen rules are removed; a pause is never undone this way.
func undoViewingChoice(conn *sql.Conn, undo jVal) (viewingChange, error) {
	added, removed := undo.get("added_rule_ids"), undo.get("removed_rules")
	if !isList(added) || !isList(removed) {
		return viewingChange{}, fmt.Errorf("undo must list added_rule_ids and removed_rules")
	}
	ctx := context.Background()
	touched := sceneCollector{}
	for _, v := range added.arr {
		id := pythonIntErrOr(v, -1)
		var scene sql.NullString
		err := conn.QueryRowContext(ctx, `SELECT scene_id FROM viewing_rule WHERE rule_id=? AND reason='chosen'`, id).Scan(&scene)
		if errors.Is(err, sql.ErrNoRows) {
			continue // already gone
		}
		if err != nil {
			return viewingChange{}, err
		}
		if _, err := conn.ExecContext(ctx, `DELETE FROM viewing_rule WHERE rule_id=?`, id); err != nil {
			return viewingChange{}, err
		}
		touched.add(scene.String)
	}
	for _, v := range removed.arr {
		r, err := ruleFromJSON(v)
		if err != nil {
			return viewingChange{}, err
		}
		if _, err := insertRule(conn, r); err != nil {
			return viewingChange{}, err
		}
		touched.add(r.sceneID)
	}
	return viewingChange{scenes: touched.list()}, nil
}

// applyViewingChange runs a rule change, rebuilds the sessions Curator
// derives from Stash's play history for the scenes it touched (they leave
// out plays that do not count) and asks for a model update.
func applyViewingChange(db dbx, fn func(conn *sql.Conn) (viewingChange, error)) (viewingChange, error) {
	var change viewingChange
	if err := withTxn(db, func(conn *sql.Conn) error {
		var err error
		change, err = fn(conn)
		return err
	}); err != nil {
		return viewingChange{}, err
	}
	if change.scenes == nil || len(change.scenes) > 0 {
		if _, err := historicalRebuild(db, change.scenes, nil); err != nil {
			return viewingChange{}, err
		}
	}
	err := withTxn(db, func(conn *sql.Conn) error { return coordinatorRequest(conn, "viewing_choice", nowMs()) })
	return change, err
}

// forgetViewing stops counting every play in [sinceMs, untilMs). Nothing is
// deleted: the period can be counted again from the viewing history.
func forgetViewing(db dbx, sinceMs, untilMs int64) (jVal, error) {
	if sinceMs < 0 || untilMs <= sinceMs {
		return jvNull(), fmt.Errorf("the period to forget must end after it starts")
	}
	change, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
		return setViewingChoice(conn, choiceExclude, []viewingSpan{{"", sinceMs, untilMs}}, nowMs())
	})
	if err != nil {
		return jvNull(), err
	}
	return jvObj(jvKey("undo", change.undoJSON())), nil
}

func opForgetViewing(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "forget_viewing", func(settings jVal) (jVal, error) {
		args := payload.get("args")
		untilMs := pythonIntErrOr(args.get("until_ms"), nowMs())
		hours := pythonIntErrOr(args.get("hours"), 0)
		sinceMs := pythonIntErrOr(args.get("since_ms"), untilMs-hours*3_600_000)
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		return forgetViewing(db, sinceMs, untilMs)
	})
}

// opSetViewingChoice: args.choice ("include" | "exclude") and one of
// args.watches ([{scene_id, started_at_ms, ended_at_ms}] as
// get_viewing_history returns them), args.periods ([{since_ms, until_ms}])
// or args.since_ms/until_ms, the last two for every scene. A period ends no
// later than now.
func opSetViewingChoice(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "set_viewing_choice", func(settings jVal) (jVal, error) {
		args := payload.get("args")
		choice := args.get("choice").asString()
		var spans []viewingSpan
		if watches := args.get("watches"); isList(watches) {
			for _, w := range watches.arr {
				scene := pythonStrOrEmpty(w.get("scene_id"))
				if scene == "" {
					return jvNull(), fmt.Errorf("each watch needs a scene_id")
				}
				spans = append(spans, viewingSpan{scene,
					pythonIntErrOr(w.get("started_at_ms"), -1), pythonIntErrOr(w.get("ended_at_ms"), -1)})
			}
		} else {
			periods := args.get("periods")
			if !isList(periods) {
				periods = jvArr(args)
			}
			now := nowMs()
			for _, p := range periods.arr {
				spans = append(spans, viewingSpan{"",
					pythonIntErrOr(p.get("since_ms"), -1), min(pythonIntErrOr(p.get("until_ms"), now), now)})
			}
		}
		if len(spans) == 0 {
			return jvNull(), fmt.Errorf("nothing to change")
		}
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		change, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
			return setViewingChoice(conn, choice, spans, nowMs())
		})
		if err != nil {
			return jvNull(), err
		}
		return jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)), jvKey("undo", change.undoJSON())), nil
	})
}

func opUndoViewingChoice(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "undo_viewing_choice", func(settings jVal) (jVal, error) {
		undo := payload.get("args").get("undo")
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		if _, err := applyViewingChange(db, func(conn *sql.Conn) (viewingChange, error) {
			return undoViewingChoice(conn, undo)
		}); err != nil {
			return jvNull(), err
		}
		return jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)), jvKey("undone", jvBool(true))), nil
	})
}
