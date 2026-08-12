package main

import (
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"
)

func TestStartProfilingForExplicitDir(t *testing.T) {
	settings := jvObj(jvKey("pprofEnabled", jvBool(true)))
	pluginDir := t.TempDir()
	payload := jvObj(jvKey("args", jvObj(jvKey("database_path", jvStr(filepath.Join(pluginDir, "data", "curator.sqlite3"))))))
	stopCPU, dumpMem := startProfilingFor(pluginDir, payload, settings, "get_similar")
	work := make([]byte, 1<<20)
	runtime.KeepAlive(work)
	stopCPU()
	dumpMem()
	dir := filepath.Join(pluginDir, "data", "profiles")
	for _, kind := range []string{"cpu", "mem"} {
		matches, err := filepath.Glob(filepath.Join(dir, kind+"-get_similar-*.pprof"))
		if err != nil {
			t.Fatal(err)
		}
		if len(matches) != 1 {
			t.Errorf("%s profile missing in %s: %v", kind, dir, matches)
		}
		data, err := os.ReadFile(matches[0])
		if err != nil {
			t.Fatal(err)
		}
		if len(data) < 64 {
			t.Errorf("%s profile too small: %d bytes", kind, len(data))
		}
	}
}

func TestStartProfilingForDisabled(t *testing.T) {
	pluginDir := t.TempDir()
	payload := jvObj(jvKey("args", jvObj()))
	stopCPU, dumpMem := startProfilingFor(pluginDir, payload, jvObj(jvKey("pprofEnabled", jvBool(false))), "get_similar")
	stopCPU()
	dumpMem()
	if _, err := os.Stat(filepath.Join(pluginDir, "data", "profiles")); !os.IsNotExist(err) {
		t.Error("profiles dir created while disabled")
	}
}

func TestPrunePprofFilesKeepsNewest(t *testing.T) {
	dir := t.TempDir()
	for i := 0; i < 5; i++ {
		name := "cpu-op-" + string(rune('a'+i)) + ".pprof"
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
		stamp := time.Unix(1_000_000+int64(i), 0)
		if err := os.Chtimes(filepath.Join(dir, name), stamp, stamp); err != nil {
			t.Fatal(err)
		}
	}
	prunePprofFiles(dir, 2)
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	sort.Strings(names)
	want := []string{"cpu-op-d.pprof", "cpu-op-e.pprof"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Errorf("kept %v, want %v", names, want)
	}
}

func TestPprofNameValid(t *testing.T) {
	for _, name := range []string{"cpu-get_similar-123.pprof", "mem-build-7.pprof"} {
		if !pprofNameValid(name) {
			t.Errorf("rejected valid name %q", name)
		}
	}
	for _, name := range []string{"", "cpu-x.pprof/..", "../cpu-x.pprof", "a/b.pprof", "cpu-x.pprof\\..", "notes.txt", "cpu-x.pprof.."} {
		if pprofNameValid(name) {
			t.Errorf("accepted invalid name %q", name)
		}
	}
}

func TestListPprofFilesNewestFirst(t *testing.T) {
	dir := t.TempDir()
	for i := 0; i < 3; i++ {
		name := "cpu-op-" + string(rune('a'+i)) + ".pprof"
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
		stamp := time.Unix(1_000_000+int64(i), 0)
		if err := os.Chtimes(filepath.Join(dir, name), stamp, stamp); err != nil {
			t.Fatal(err)
		}
	}
	files, err := listPprofFiles(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 3 {
		t.Fatalf("listed %d files", len(files))
	}
	if files[0].name != "cpu-op-c.pprof" || files[2].name != "cpu-op-a.pprof" {
		t.Errorf("order = %s, %s, %s", files[0].name, files[1].name, files[2].name)
	}
	// Missing directory -> empty list, not an error.
	empty, err := listPprofFiles(filepath.Join(dir, "nope"))
	if err != nil || len(empty) != 0 {
		t.Errorf("missing dir: %v %v", empty, err)
	}
}

func TestPprofProfilesDirResolution(t *testing.T) {
	pluginDir := t.TempDir()
	payload := jvObj(jvKey("args", jvObj(jvKey("database_path", jvStr("/srv/data/curator.sqlite3")))))
	got := pprofProfilesDir(pluginDir, payload, jvObj())
	if got != "/srv/data/profiles" {
		t.Errorf("dir = %q", got)
	}
	// Default location: beside the plugin data dir.
	got = pprofProfilesDir(pluginDir, jvObj(jvKey("args", jvObj())), jvObj())
	if got != filepath.Join(pluginDir, "data", "profiles") {
		t.Errorf("default dir = %q", got)
	}
}
