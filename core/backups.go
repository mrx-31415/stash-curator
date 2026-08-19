// Backup control ops — list_backups / create_backup / delete_backup /
// restore_backup: a port of backend.py's _backup_control together with
// curator/storage/database.py's backup_database and _validate_backup. The
// backup itself uses the SQLite online-backup API (like Python's
// Connection.backup), so the destination is a consistent snapshot with the
// same page count as the source (byte-identical backups from identical
// sources, same size at minimum).
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	sqlite "github.com/mattn/go-sqlite3"
)

// backupName mirrors backend.py's BACKUP_NAME.
var backupName = regexp.MustCompile(`^curator-(?:before-restore-)?(\d+)\.sqlite3\.backup$`)

// backupDirectory mirrors backend.py's _backup_directory: settings.backupPath
// expanded and resolved, else the database path's parent directory.
func backupDirectory(pluginDir string, payload, settings jVal) string {
	configured := strings.TrimSpace(pythonStrOrEmpty(settings.get("backupPath")))
	if configured != "" {
		return realpath(expandUser(configured))
	}
	return filepath.Dir(realpath(databasePath(pluginDir, payload, settings)))
}

// listBackups mirrors backend.py's _list_backups: every non-symlink regular
// file whose name matches BACKUP_NAME, sorted by created_at_ms descending.
func listBackups(directory string) (jVal, error) {
	items := jvArr()
	entries, err := os.ReadDir(directory)
	if err != nil {
		if os.IsNotExist(err) {
			return items, nil
		}
		return jvNull(), err
	}
	for _, entry := range entries {
		name := entry.Name()
		match := backupName.FindStringSubmatch(name)
		if match == nil {
			continue
		}
		info, err := entry.Info() // lstat semantics: symlinks report ModeSymlink
		if err != nil || !info.Mode().IsRegular() {
			continue
		}
		createdMs, _ := strconv.ParseInt(match[1], 10, 64)
		items.arr = append(items.arr, jvObj(
			jvKey("id", jvStr(name)),
			jvKey("created_at_ms", jvInt(createdMs)),
			jvKey("size_bytes", jvInt(info.Size())),
			jvKey("path", jvStr(realpath(filepath.Join(directory, name)))),
		))
	}
	sort.SliceStable(items.arr, func(i, j int) bool {
		a, _ := strconv.ParseInt(items.arr[i].get("created_at_ms").num, 10, 64)
		b, _ := strconv.ParseInt(items.arr[j].get("created_at_ms").num, 10, 64)
		return a > b
	})
	return items, nil
}

// validateBackup mirrors backend.py's backup validation: a full SQLite
// integrity check, schema presence, and migration checksum validation.
func validateBackup(path string) error {
	inner := func() error {
		db, err := openDatabase(path, true, nil)
		if err != nil {
			return err
		}
		defer db.Close()
		var check string
		if err := db.QueryRow("PRAGMA integrity_check").Scan(&check); err != nil {
			return err
		}
		if check != "ok" {
			return errors.New("backup failed SQLite integrity validation")
		}
		var one int
		err = db.QueryRow(
			`SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'`,
		).Scan(&one)
		if err == sql.ErrNoRows {
			return errors.New("backup is not a Curator database")
		}
		if err != nil {
			return err
		}
		_, err = queryMigrationStatus(db)
		return err
	}
	if err := inner(); err != nil {
		return fmt.Errorf("incompatible Curator backup: %v", err)
	}
	return nil
}

var validateBackupFn = validateBackup

func removeBackupSidecars(path string) {
	for _, suffix := range []string{"-wal", "-shm"} {
		if err := os.Remove(path + suffix); err != nil && !os.IsNotExist(err) {
			warnLog("could not remove backup sidecar: " + err.Error())
		}
	}
}

func backupDatabaseValidated(db dbx, dst string, overwrite bool, progress func(done, total int)) (string, error) {
	backup, err := backupDatabase(db, dst, overwrite, progress)
	if err != nil {
		return "", err
	}
	if err := validateBackupFn(backup); err != nil {
		removeBackupSidecars(backup)
		_ = os.Remove(backup)
		return "", err
	}
	removeBackupSidecars(backup)
	return backup, nil
}

// backupDatabase mirrors curator.storage.database.backup_database: an
// online backup of the source's main database into a temp file (256 pages
// per step, like Python's pages=256), then an atomic rename to the
// destination. progress(done, total) fires per step; the temp is removed on
// any failure.
func backupDatabase(db dbx, dst string, overwrite bool, progress func(done, total int)) (string, error) {
	dst = realpath(expandUser(dst))
	if _, err := os.Stat(dst); err == nil && !overwrite {
		return "", fmt.Errorf("backup destination already exists: %s", dst)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return "", err
	}
	temporary := filepath.Join(
		filepath.Dir(dst),
		fmt.Sprintf(".%s.%s.tmp", filepath.Base(dst), strings.ReplaceAll(uuid4(), "-", "")),
	)
	cleanup := func() {
		if err := os.Remove(temporary); err != nil && !os.IsNotExist(err) {
			warnLog("could not remove backup temp: " + err.Error())
		}
	}
	conn, err := db.Conn(context.Background())
	if err != nil {
		return "", err
	}
	defer conn.Close()
	backupErr := conn.Raw(func(driverConn any) error {
		src, ok := driverConn.(*sqlite.SQLiteConn)
		if !ok {
			return errors.New("sqlite driver does not expose the backup API")
		}
		// The mattn backup API backs up into a *connection* opened on the
		// destination; open the temp destination and back the source's main
		// database into it (the same sqlite3_backup_init Python uses).
		destDB, err := sql.Open("sqlite3", "file:"+temporary+"?mode=rwc")
		if err != nil {
			return err
		}
		defer destDB.Close()
		destConn, err := destDB.Conn(context.Background())
		if err != nil {
			return err
		}
		defer destConn.Close()
		var backup *sqlite.SQLiteBackup
		destErr := destConn.Raw(func(destConn any) error {
			dest, ok := destConn.(*sqlite.SQLiteConn)
			if !ok {
				return errors.New("sqlite driver does not expose the backup API")
			}
			var err error
			backup, err = dest.Backup("main", src, "main")
			return err
		})
		if destErr != nil {
			return destErr
		}
		for {
			// mattn's Step returns (done, err): true once sqlite3_backup_step
			// reports SQLITE_DONE (modernc's returns more-remaining; the loop
			// breaks on the done signal).
			done, err := backup.Step(256)
			if progress != nil {
				progress(backup.PageCount()-backup.Remaining(), backup.PageCount())
			}
			if err != nil {
				backup.Finish()
				return err
			}
			if done {
				break
			}
		}
		return backup.Finish()
	})
	if backupErr != nil {
		cleanup()
		return "", backupErr
	}
	if err := os.Rename(temporary, dst); err != nil {
		cleanup()
		return "", err
	}
	return dst, nil
}

// mirrorDerivedArtifacts copies every immutable final artifact in the live
// derived cache (<stem>-derived beside the core database) into
// <backup-dir>/derived/, so a backup directory carries both the database
// snapshot and the artifact generations its published rows reference. The
// sidecar itself is never copied here: the WAL database is only ever
// snapshotted through the SQLite backup API (backupDatabase), and only the
// immutable final artifact files are file-copied. Artifact basenames embed
// the generation version, so the mirror is idempotent and additive: a
// re-run never rewrites an unchanged artifact (target exists with the same
// size) and never deletes older copies, keeping every historical backup
// restorable against the artifacts its snapshot references. Symlinked or
// non-regular entries in the cache are skipped; a symlinked cache directory
// is rejected outright (the same guard artifactPath applies).
func mirrorDerivedArtifacts(db dbx, directory string) error {
	corePath, err := coreDatabasePath(db)
	if err != nil {
		return err
	}
	cache := cacheDirectory(corePath)
	info, err := os.Lstat(cache)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // no derived cache yet — nothing to mirror
		}
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return fmt.Errorf("unsafe derived-cache directory: %s", cache)
	}
	entries, err := os.ReadDir(cache)
	if err != nil {
		return err
	}
	targetDir := filepath.Join(directory, "derived")
	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		return err
	}
	for _, entry := range entries {
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			continue
		}
		if !finalArtifactName.MatchString(entry.Name()) {
			continue
		}
		source := filepath.Join(cache, entry.Name())
		target := filepath.Join(targetDir, entry.Name())
		if err := mirrorArtifactFile(source, target); err != nil {
			return err
		}
	}
	return nil
}

// mirrorArtifactFile copies source to target unless a regular target of the
// same size already exists — artifact filenames embed the generation
// version, so an existing same-size target is already the mirrored artifact
// and copying again would be pure waste (no hashing of the large files). A
// size mismatch means the target is stale or truncated; it is replaced. The
// copy lands in a temp file in the target directory and is renamed into
// place, so a partially written mirror is never visible; the temp is removed
// on any failure.
func mirrorArtifactFile(source, target string) error {
	srcInfo, err := os.Stat(source)
	if err != nil {
		return err
	}
	if info, err := os.Stat(target); err == nil {
		if info.Size() == srcInfo.Size() {
			return nil // already mirrored
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("refusing to replace non-regular mirror target: %s", target)
		}
		// Stale/truncated target: drop it so the rename below is a clean
		// replace (also required on Windows, where os.Rename cannot replace
		// an existing file).
		if err := os.Remove(target); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	temporary := filepath.Join(
		filepath.Dir(target),
		fmt.Sprintf(".%s.%s.tmp", filepath.Base(target), strings.ReplaceAll(uuid4(), "-", "")),
	)
	cleanup := func() {
		if err := os.Remove(temporary); err != nil && !os.IsNotExist(err) {
			warnLog("could not remove derived mirror temp: " + err.Error())
		}
	}
	src, err := os.Open(source)
	if err != nil {
		return err
	}
	dst, err := os.OpenFile(temporary, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		src.Close()
		return err
	}
	_, copyErr := io.Copy(dst, src)
	src.Close()
	if err := dst.Close(); err != nil && copyErr == nil {
		copyErr = err
	}
	if copyErr != nil {
		cleanup()
		return copyErr
	}
	if err := os.Rename(temporary, target); err != nil {
		cleanup()
		return err
	}
	return nil
}

// opBackupControl mirrors backend.py's _backup_control dispatch. It is not
// _profiled (matching the Python dispatch).
func opBackupControl(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	args := payload.get("args")
	operation := args.get("operation").asString()
	database := realpath(databasePath(pluginDir, payload, settings))
	directory := backupDirectory(pluginDir, payload, settings)
	if operation == "list_backups" {
		items, err := listBackups(directory)
		if err != nil {
			return jvNull(), err
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("backup_directory", jvStr(directory)),
			jvKey("items", items),
		), nil
	}
	db, err := openSidecar(pluginDir, payload, settings, true)
	if err != nil {
		return jvNull(), err
	}
	defer db.Close()
	var running int
	err = db.QueryRow(`SELECT 1 FROM curator_job WHERE state='running' LIMIT 1`).Scan(&running)
	if err == nil {
		return jvNull(), errors.New("cannot change backups while a Curator job is running")
	}
	if err != sql.ErrNoRows {
		return jvNull(), err
	}
	now := nowMs()
	if operation == "create_backup" {
		backup, err := backupDatabaseValidated(
			db,
			filepath.Join(directory, fmt.Sprintf("curator-%d.sqlite3.backup", now)),
			false,
			nil,
		)
		if err != nil {
			return jvNull(), err
		}
		if err := mirrorDerivedArtifacts(db, directory); err != nil {
			// The database backup is the contract; the artifact mirror is
			// best-effort additive recovery data, so a mirror failure warns
			// (plugin logs) instead of failing the backup.
			warnLog("derived artifact mirror failed: " + err.Error())
		}
		items, err := listBackups(directory)
		if err != nil {
			return jvNull(), err
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("backup_path", jvStr(backup)),
			jvKey("items", items),
		), nil
	}
	backupID := pythonStrOrEmpty(args.get("backup_id"))
	match := backupName.FindStringSubmatch(backupID)
	backup := filepath.Join(directory, backupID)
	if match == nil || realpath(filepath.Dir(backup)) != directory ||
		!isRegularFile(backup) || isSymlink(backup) {
		return jvNull(), errors.New("select a recognized Curator backup")
	}
	if operation == "delete_backup" {
		if pythonStrOrEmpty(args.get("confirmation")) != "DELETE "+backupID {
			return jvNull(), errors.New("deletion requires explicit confirmation")
		}
		if err := validateBackup(backup); err != nil {
			return jvNull(), err
		}
		if err := os.Remove(backup); err != nil {
			return jvNull(), err
		}
		items, err := listBackups(directory)
		if err != nil {
			return jvNull(), err
		}
		return jvObj(
			jvKey("schema_version", jvInt(apiSchemaVersion)),
			jvKey("deleted", jvStr(backupID)),
			jvKey("items", items),
		), nil
	}
	if pythonStrOrEmpty(args.get("confirmation")) != "RESTORE "+backupID {
		return jvNull(), errors.New("restore requires explicit confirmation")
	}
	if err := validateBackup(backup); err != nil {
		return jvNull(), err
	}
	safety, err := backupDatabase(
		db,
		filepath.Join(directory, fmt.Sprintf("curator-before-restore-%d.sqlite3.backup", now)),
		false,
		nil,
	)
	if err != nil {
		return jvNull(), err
	}
	// The sidecar connection must be fully closed before the file swap:
	// drop -wal/-shm like Python does, then copy the backup over the core.
	if err := db.Close(); err != nil {
		return jvNull(), err
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		if err := os.Remove(database + suffix); err != nil && !os.IsNotExist(err) {
			return jvNull(), err
		}
	}
	source, err := openDatabase(backup, true, nil)
	if err != nil {
		return jvNull(), err
	}
	if _, err := backupDatabase(source, database, true, nil); err != nil {
		source.Close()
		return jvNull(), err
	}
	source.Close()
	restored, err := openDatabase(database, false, nil)
	if err != nil {
		return jvNull(), err
	}
	restoreErr := func() error {
		if err := migrate(restored, now); err != nil {
			return err
		}
		return withTxn(restored, func(conn *sql.Conn) error {
			if _, err := conn.ExecContext(context.Background(),
				`UPDATE model_version SET status='superseded', validation_status='restore_invalidated'
WHERE status='published'`); err != nil {
				return err
			}
			if _, err := conn.ExecContext(context.Background(),
				`UPDATE feature_build SET status='superseded', validation_status='restore_invalidated'
WHERE status='published'`); err != nil {
				return err
			}
			_, err := conn.ExecContext(context.Background(),
				`DELETE FROM application_meta WHERE key='current_model_id'`)
			return err
		})
	}()
	restored.Close()
	if restoreErr != nil {
		return jvNull(), restoreErr
	}
	return jvObj(
		jvKey("schema_version", jvInt(apiSchemaVersion)),
		jvKey("restored_from", jvStr(realpath(backup))),
		jvKey("safety_backup", jvStr(safety)),
		jvKey("recommendations_need_rebuilding", jvBool(true)),
	), nil
}

// withTxn runs fn inside one BEGIN IMMEDIATE transaction on the pool's
// single connection, committing on success and rolling back on error —
// mirroring curator.storage.transaction (no nested transactions). Busy
// failures before COMMIT are retried with backoff (the #109 mitigation for
// extended SQLITE_BUSY codes the busy_timeout handler does not cover); a
// COMMIT failure is never retried — its outcome is ambiguous and re-running
// fn could double-apply writes.
func withTxn(db dbx, fn func(conn *sql.Conn) error) error {
	var lastErr error
	for attempt := range busyRetryAttempts {
		conn, err := db.Conn(context.Background())
		if err != nil {
			return err
		}
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
			conn.Close()
			if isBusyError(err) && attempt < busyRetryAttempts-1 {
				lastErr = err
				time.Sleep(busyRetryBackoff(attempt))
				continue
			}
			return err
		}
		if err := fn(conn); err != nil {
			conn.ExecContext(ctx, "ROLLBACK")
			conn.Close()
			if isBusyError(err) && attempt < busyRetryAttempts-1 {
				lastErr = err
				time.Sleep(busyRetryBackoff(attempt))
				continue
			}
			return err
		}
		if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
			conn.Close()
			return err
		}
		conn.Close()
		return nil
	}
	return lastErr
}

// isRegularFile reports whether path names a regular, non-symlink file
// (Python's path.is_file() with an explicit is_symlink() guard).
func isRegularFile(path string) bool {
	info, err := os.Lstat(path)
	return err == nil && info.Mode().IsRegular()
}

// isSymlink mirrors Python's Path.is_symlink().
func isSymlink(path string) bool {
	info, err := os.Lstat(path)
	return err == nil && info.Mode()&os.ModeSymlink != 0
}
