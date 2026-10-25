package main

import (
	"bytes"
	"encoding/base64"
	"math/rand"
	"os"
	"path/filepath"
	"testing"
)

func TestDownloadBackupReassemblesChunks(t *testing.T) {
	dir := t.TempDir()
	want := make([]byte, 2*backupChunkBytes+123)
	rand.New(rand.NewSource(1)).Read(want)
	id := "curator-1700000000000.sqlite3.backup"
	if err := os.WriteFile(filepath.Join(dir, id), want, 0o644); err != nil {
		t.Fatal(err)
	}
	request := func(backupID string, offset int64) (jVal, error) {
		payload := jvObj(
			jvKey("server_connection", jvObj(jvKey("Host", jvStr("127.0.0.1")), jvKey("Port", jvInt(1)))),
			jvKey("args", jvObj(
				jvKey("operation", jvStr("download_backup")),
				jvKey("database_path", jvStr(filepath.Join(dir, "curator.sqlite3"))),
				jvKey("backup_id", jvStr(backupID)),
				jvKey("offset", jvInt(offset)),
			)),
		)
		return opBackupControl(t.TempDir(), payload)
	}
	var got []byte
	chunks := 0
	for {
		chunk, err := request(id, int64(len(got)))
		if err != nil {
			t.Fatal(err)
		}
		data, err := base64.StdEncoding.DecodeString(chunk.get("content_base64").asString())
		if err != nil {
			t.Fatal(err)
		}
		if len(data) > backupChunkBytes {
			t.Fatalf("chunk of %d bytes exceeds the limit", len(data))
		}
		got = append(got, data...)
		chunks++
		if chunk.get("done").truthy() {
			break
		}
		if chunks > 3 {
			t.Fatal("download did not finish")
		}
	}
	if chunks != 3 || !bytes.Equal(got, want) {
		t.Fatalf("got %d chunks / %d bytes, want 3 chunks / %d identical bytes", chunks, len(got), len(want))
	}
	for _, bad := range []string{"../" + id, "curator.sqlite3", "curator-1.sqlite3.backup"} {
		if _, err := request(bad, 0); err == nil {
			t.Errorf("download of %q was not rejected", bad)
		}
	}
	if _, err := request(id, int64(len(want))+1); err == nil {
		t.Error("offset past the end was not rejected")
	}
}
