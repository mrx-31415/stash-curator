// Pausing Curator's learning from viewing, and forgetting viewing after the
// fact. A pause period covers player sessions (submit_events) and the plays
// Curator rebuilds from Stash's play history; deliberate feedback such as
// thumbs, tag answers and dismissals is not affected.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

// pauseWindow is [startedAtMs, endedAtMs); endedAtMs < 0 means still open.
type pauseWindow struct {
	startedAtMs int64
	endedAtMs   int64
}

func (w pauseWindow) covers(atMs int64) bool {
	return atMs >= w.startedAtMs && (w.endedAtMs < 0 || atMs < w.endedAtMs)
}

// syncLearningPause opens a pause period when the pauseLearning setting is
// on and none is open, and closes the open one when it is off. Runs on every
// sidecar open that carries the plugin settings.
func syncLearningPause(db dbx, settings jVal, nowMs int64) error {
	if settings.kind != jObj {
		return nil // a task or hook without settings: leave the state alone
	}
	paused := settings.get("pauseLearning").truthy()
	var openID int64
	err := db.QueryRow(`SELECT pause_id FROM learning_pause
WHERE reason='paused' AND ended_at_ms IS NULL ORDER BY started_at_ms DESC LIMIT 1`).Scan(&openID)
	switch {
	case err != nil && !errors.Is(err, sql.ErrNoRows):
		return err
	case paused && errors.Is(err, sql.ErrNoRows):
		_, err = db.Exec(`INSERT INTO learning_pause(started_at_ms, ended_at_ms, reason) VALUES (?, NULL, 'paused')`, nowMs)
		return err
	case !paused && err == nil:
		_, err = db.Exec(`UPDATE learning_pause SET ended_at_ms=? WHERE pause_id=?`, nowMs, openID)
		return err
	}
	return nil
}

func loadPauseWindows(db interface {
	Query(query string, args ...any) (*sql.Rows, error)
}) ([]pauseWindow, error) {
	rows, err := db.Query(`SELECT started_at_ms, COALESCE(ended_at_ms, -1) FROM learning_pause`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var windows []pauseWindow
	for rows.Next() {
		var w pauseWindow
		if err := rows.Scan(&w.startedAtMs, &w.endedAtMs); err != nil {
			return nil, err
		}
		windows = append(windows, w)
	}
	return windows, rows.Err()
}

func pausedAt(windows []pauseWindow, atMs int64) bool {
	for _, w := range windows {
		if w.covers(atMs) {
			return true
		}
	}
	return false
}

func connPauseWindows(conn *sql.Conn) ([]pauseWindow, error) {
	rows, err := conn.QueryContext(context.Background(),
		`SELECT started_at_ms, COALESCE(ended_at_ms, -1) FROM learning_pause`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var windows []pauseWindow
	for rows.Next() {
		var w pauseWindow
		if err := rows.Scan(&w.startedAtMs, &w.endedAtMs); err != nil {
			return nil, err
		}
		windows = append(windows, w)
	}
	return windows, rows.Err()
}

// forgetViewing records [sinceMs, untilMs) as forgotten, removes the player
// sessions and the signals derived from them in that period, and rebuilds
// the sessions Curator derives from Stash's play history so plays in the
// period drop out. The next model update then no longer sees them.
func forgetViewing(db dbx, sinceMs, untilMs int64) (jVal, error) {
	if sinceMs < 0 || untilMs <= sinceMs {
		return jvNull(), fmt.Errorf("the period to forget must end after it starts")
	}
	var sessions, events int64
	err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `INSERT INTO learning_pause(started_at_ms, ended_at_ms, reason)
VALUES (?, ?, 'forgotten')`, sinceMs, untilMs); err != nil {
			return err
		}
		res, err := conn.ExecContext(ctx, `DELETE FROM behavior_event
WHERE provenance='direct_player' AND (
    (occurred_at_ms >= ? AND occurred_at_ms < ?)
    OR session_id IN (SELECT session_id FROM play_session
        WHERE provenance='direct_player' AND started_at_ms >= ? AND started_at_ms < ?))`,
			sinceMs, untilMs, sinceMs, untilMs)
		if err != nil {
			return err
		}
		if events, err = res.RowsAffected(); err != nil {
			return err
		}
		res, err = conn.ExecContext(ctx, `DELETE FROM play_session
WHERE provenance='direct_player' AND started_at_ms >= ? AND started_at_ms < ?`, sinceMs, untilMs)
		if err != nil {
			return err
		}
		sessions, err = res.RowsAffected()
		return err
	})
	if err != nil {
		return jvNull(), err
	}
	historical, err := historicalRebuild(db, nil, nil)
	if err != nil {
		return jvNull(), err
	}
	return jvObj(
		jvKey("forgotten_sessions", jvInt(sessions)),
		jvKey("forgotten_signals", jvInt(events)),
		jvKey("history_sessions", jvInt(historical.sessionCount)),
	), nil
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
