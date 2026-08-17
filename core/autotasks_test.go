// Auto-scheduler tests (docs/decisions/004, Phase 2a): the daemon's
// event-driven update-model / sync-plays triggers and the stay-alive rule,
// against a temp migrated sidecar.
package main

import (
	"testing"
)

// enableAutoTasks flips the stored config so sidecarConfig merges
// auto_tasks_enabled=true.
func enableAutoTasks(t *testing.T, db dbx) {
	t.Helper()
	if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
		`{"auto_tasks_enabled": true}`, nowMs()); err != nil {
		t.Fatal(err)
	}
}

func seedModelUpdate(t *testing.T, db dbx, requested int64, published int64, requestedAtMs int64) {
	t.Helper()
	if _, err := db.Exec(`UPDATE model_update_state SET requested_generation=?, published_generation=?, requested_at_ms=? WHERE singleton=1`,
		requested, published, requestedAtMs); err != nil {
		t.Fatal(err)
	}
}

func seedPlay(t *testing.T, db dbx, sessionID string, endedAtMs int64) {
	t.Helper()
	if _, err := db.Exec(`INSERT OR IGNORE INTO source_scene(scene_id, source_hash)
VALUES ('s1', 'h-s1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO play_session(session_id, scene_id, started_at_ms, ended_at_ms, active_seconds, provenance, confidence)
VALUES (?, 's1', ?, ?, 1, 'direct_player', 1)`, sessionID, endedAtMs-1000, endedAtMs); err != nil {
		t.Fatal(err)
	}
}

func seedSyncPlaysDone(t *testing.T, db dbx, finishedAtMs int64) {
	t.Helper()
	if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms, finished_at_ms, summary_json)
VALUES (?, 'sync-plays', 'complete', ?, ?, '{}')`, uuid4(), finishedAtMs-1000, finishedAtMs); err != nil {
		t.Fatal(err)
	}
}

func queuedModes(t *testing.T, db dbx) map[string]bool {
	t.Helper()
	rows, err := db.Query(`SELECT job_type FROM curator_job WHERE state='queued'`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	modes := map[string]bool{}
	for rows.Next() {
		var mode string
		if err := rows.Scan(&mode); err != nil {
			t.Fatal(err)
		}
		modes[mode] = true
	}
	return modes
}

func TestSchedulerDisabledByDefault(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		seedModelUpdate(t, db, 5, 0, now-1_000)
		seedPlay(t, db, "p1", now-120_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 || len(queuedModes(t, db)) != 0 {
			t.Fatalf("auto tasks must be off by default: %v", enqueued)
		}
	})
}

func TestSchedulerModelUpdateReady(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// Threshold met (5 pending events) → enqueue update-model.
		seedModelUpdate(t, db, 5, 0, now-1_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 1 || enqueued[0] != "update-model" {
			t.Fatalf("expected update-model enqueue, got %v", enqueued)
		}
		if !queuedModes(t, db)["update-model"] {
			t.Fatal("no queued update-model row")
		}
	})
}

func TestSchedulerModelUpdateNotReadyYet(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// One event, far below threshold and inside the max-wait window.
		seedModelUpdate(t, db, 1, 0, now-1_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("not ready, must not enqueue: %v", enqueued)
		}
	})
}

func TestSchedulerSkipsWhileRebuilding(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('b1', 'build', 'running', ?)`, now-10_000); err != nil {
			t.Fatal(err)
		}
		seedModelUpdate(t, db, 5, 0, now-1_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("must not enqueue while rebuilding: %v", enqueued)
		}
	})
}

func TestSchedulerCoalescesActiveSameType(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('u1', 'update-model', 'queued', ?)`, now-10_000); err != nil {
			t.Fatal(err)
		}
		seedModelUpdate(t, db, 5, 0, now-1_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("coalescing must skip: %v", enqueued)
		}
		if len(queuedModes(t, db)) != 1 {
			t.Fatalf("coalescing added a row: %v", queuedModes(t, db))
		}
	})
}

func TestSchedulerPlaySyncQuietWindow(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// Play ended 10s ago — still in the quiet window → no sync yet.
		seedPlay(t, db, "p1", now-10_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("must wait for the quiet window: %v", enqueued)
		}
	})
}

func TestSchedulerPlaySyncFiresWhenQuiet(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// Play ended 120s ago, no sync-plays ever ran → enqueue.
		seedPlay(t, db, "p1", now-120_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 1 || enqueued[0] != "sync-plays" {
			t.Fatalf("expected sync-plays enqueue, got %v", enqueued)
		}
	})
}

func TestSchedulerPlaySyncAlreadySynced(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	enableAutoTasks(t, db)
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// A sync-plays completed after the newest play → nothing to sync.
		seedPlay(t, db, "p1", now-300_000)
		seedSyncPlaysDone(t, db, now-200_000)
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("plays already synced: %v", enqueued)
		}
	})
}

func TestSchedulerScheduleSeedsNotDue(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			`{"schedule_expand_refresh_enabled": true}`, now); err != nil {
			t.Fatal(err)
		}

		// Default config: expand-refresh enabled. First tick seeds the row
		// one interval out — never fires immediately.
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 || len(queuedModes(t, db)) != 0 {
			t.Fatalf("first tick must only seed: %v", enqueued)
		}
		var next int64
		if err := db.QueryRow(`SELECT next_run_at_ms FROM scheduled_task WHERE task_type='expand-refresh'`).Scan(&next); err != nil {
			t.Fatal(err)
		}
		if next != now+24*3_600_000 {
			t.Fatalf("next_run must be one 24h interval out: %d", next)
		}
	})
}

func TestSchedulerScheduleDueEnqueues(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			`{"schedule_expand_refresh_enabled": true}`, now); err != nil {
			t.Fatal(err)
		}

		if _, err := db.Exec(`INSERT INTO scheduled_task(task_type, next_run_at_ms) VALUES ('expand-refresh', ?)`, now-1_000); err != nil {
			t.Fatal(err)
		}
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 1 || enqueued[0] != "expand-refresh" {
			t.Fatalf("expected expand-refresh enqueue, got %v", enqueued)
		}
		var next, last int64
		if err := db.QueryRow(`SELECT next_run_at_ms, last_run_at_ms FROM scheduled_task WHERE task_type='expand-refresh'`).Scan(&next, &last); err != nil {
			t.Fatal(err)
		}
		if next != now+24*3_600_000 || last != now {
			t.Fatalf("schedule not advanced: next=%d last=%d", next, last)
		}
	})
}

func TestSchedulerScheduleDisabled(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		off := `{"schedule_expand_refresh_enabled": false, "schedule_sync_build_enabled": false,
			"schedule_backup_enabled": false}`
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`, off, now); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec(`INSERT INTO scheduled_task(task_type, next_run_at_ms) VALUES ('expand-refresh', ?)`, now-1_000); err != nil {
			t.Fatal(err)
		}
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("disabled schedule must not enqueue: %v", enqueued)
		}
	})
}

func TestSchedulerScheduleOrderBackupFirst(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		cfg := `{"schedule_expand_refresh_enabled": false, "schedule_sync_build_enabled": true,
			"schedule_backup_enabled": true}`
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`, cfg, now); err != nil {
			t.Fatal(err)
		}
		for _, mode := range []string{"sync-build", "backup"} {
			if _, err := db.Exec(`INSERT INTO scheduled_task(task_type, next_run_at_ms) VALUES (?, ?)`, mode, now-1_000); err != nil {
				t.Fatal(err)
			}
		}
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 2 || enqueued[0] != "backup" || enqueued[1] != "sync-build" {
			t.Fatalf("backup must run before sync-build: %v", enqueued)
		}
	})
}

func TestSchedulerScheduleCoalescesActiveJob(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			`{"schedule_expand_refresh_enabled": true}`, now); err != nil {
			t.Fatal(err)
		}

		if _, err := db.Exec(`INSERT INTO scheduled_task(task_type, next_run_at_ms) VALUES ('expand-refresh', ?)`, now-1_000); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec(`INSERT INTO curator_job(job_id, job_type, state, started_at_ms)
VALUES ('e1', 'expand-refresh', 'queued', ?)`, now-10_000); err != nil {
			t.Fatal(err)
		}
		enqueued, err := schedulerTick(db, jvObj(), now)
		if err != nil {
			t.Fatal(err)
		}
		if len(enqueued) != 0 {
			t.Fatalf("coalescing must skip the duplicate: %v", enqueued)
		}
		// The schedule still advances (the active job satisfies this slot).
		var next int64
		if err := db.QueryRow(`SELECT next_run_at_ms FROM scheduled_task WHERE task_type='expand-refresh'`).Scan(&next); err != nil {
			t.Fatal(err)
		}
		if next != now+24*3_600_000 {
			t.Fatalf("schedule must advance past a coalesced slot: %d", next)
		}
	})
}

func TestSchedulerStayAlive(t *testing.T) {
	db, _ := openTempDB(t)
	if err := migrate(db, 1_700_000_000_000); err != nil {
		t.Fatal(err)
	}
	now := int64(1_000_000_000_000)
	pinTime(t, now, func() {
		// Schedules + auto both off → nothing keeps the daemon alive.
		off := `{"auto_tasks_enabled": false, "schedule_expand_refresh_enabled": false,
			"schedule_sync_build_enabled": false, "schedule_backup_enabled": false}`
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`, off, now); err != nil {
			t.Fatal(err)
		}
		seedModelUpdate(t, db, 5, 0, now-1_000)
		if stay, err := schedulerStayAlive(db, now); err != nil || stay {
			t.Fatalf("auto+schedules off must not stay alive: %v %v", stay, err)
		}
		// Auto on (schedules still off) → pending model keeps it alive.
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			`{"auto_tasks_enabled": true, "schedule_expand_refresh_enabled": false,
			"schedule_sync_build_enabled": false, "schedule_backup_enabled": false}`, now); err != nil {
			t.Fatal(err)
		}
		if stay, err := schedulerStayAlive(db, now); err != nil || !stay {
			t.Fatalf("pending model must stay alive: %v %v", stay, err)
		}
		// Published → nothing pending → exits.
		seedModelUpdate(t, db, 5, 5, now-1_000)
		if stay, err := schedulerStayAlive(db, now); err != nil || stay {
			t.Fatalf("clean state must not stay alive: %v %v", stay, err)
		}
		// Unsynced plays → stays.
		seedPlay(t, db, "p1", now-120_000)
		if stay, err := schedulerStayAlive(db, now); err != nil || !stay {
			t.Fatalf("unsynced plays must stay alive: %v %v", stay, err)
		}
		// Any enabled schedule (default: expand-refresh) → resident.
		if _, err := db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
			`{"auto_tasks_enabled": false, "schedule_sync_build_enabled": true,
			"schedule_backup_enabled": false}`, now); err != nil {
			t.Fatal(err)
		}
		if stay, err := schedulerStayAlive(db, now); err != nil || !stay {
			t.Fatalf("an enabled schedule must stay alive: %v %v", stay, err)
		}
	})
}
