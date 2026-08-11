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
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	sqlite "modernc.org/sqlite"
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

// validateBackup mirrors backend.py's _validate_backup: SQLite integrity
// check, a schema_migration table, and a migration-status (checksum) pass;
// every failure is wrapped as "incompatible Curator backup: ...".
func validateBackup(path string) error {
	inner := func() error {
		db, err := openDatabase(path, true, nil)
		if err != nil {
			return err
		}
		defer db.Close()
		var check string
		if err := db.QueryRow("PRAGMA quick_check").Scan(&check); err != nil {
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

// backupConn is the driver-level surface the modernc sqlite driver exposes
// for the online-backup API (method on its unexported *conn type).
type backupConn interface {
	NewBackup(dstURI string) (*sqlite.Backup, error)
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
		api, ok := driverConn.(backupConn)
		if !ok {
			return errors.New("sqlite driver does not expose the backup API")
		}
		backup, err := api.NewBackup(temporary)
		if err != nil {
			return err
		}
		for {
			more, err := backup.Step(256)
			if progress != nil {
				progress(backup.PageCount()-backup.Remaining(), backup.PageCount())
			}
			if err != nil {
				backup.Finish()
				return err
			}
			if !more {
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
		backup, err := backupDatabase(
			db,
			filepath.Join(directory, fmt.Sprintf("curator-%d.sqlite3.backup", now)),
			false,
			nil,
		)
		if err != nil {
			return jvNull(), err
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
// mirroring curator.storage.transaction (no nested transactions).
func withTxn(db dbx, fn func(conn *sql.Conn) error) error {
	conn, err := db.Conn(context.Background())
	if err != nil {
		return err
	}
	defer conn.Close()
	ctx := context.Background()
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	if err := fn(conn); err != nil {
		conn.ExecContext(ctx, "ROLLBACK")
		return err
	}
	_, err = conn.ExecContext(ctx, "COMMIT")
	return err
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
