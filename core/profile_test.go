package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"testing"
)

func TestStartProfilingWritesProfiles(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("CURATOR_CORE_CPU_PROFILE_DIR", dir)
	t.Setenv("CURATOR_CORE_MEM_PROFILE_DIR", dir)
	stopCPU, dumpMem := startProfiling("model-build")
	// A little allocation work so the heap profile has content.
	work := make([]byte, 1<<20)
	for i := range work {
		work[i] = byte(i)
	}
	runtime.KeepAlive(work)
	stopCPU()
	dumpMem()
	for _, kind := range []string{"cpu", "mem"} {
		path := filepath.Join(dir, kind+"-model-build-"+strconv.Itoa(os.Getpid())+".pprof")
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("%s profile: %v", kind, err)
		}
		if len(data) < 64 {
			t.Errorf("%s profile too small: %d bytes", kind, len(data))
		}
	}
}

func TestStartProfilingNoopWithoutEnv(t *testing.T) {
	t.Setenv("CURATOR_CORE_CPU_PROFILE_DIR", "")
	t.Setenv("CURATOR_CORE_MEM_PROFILE_DIR", "")
	stopCPU, dumpMem := startProfiling("model-build")
	stopCPU()
	dumpMem()
	dir := t.TempDir()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Errorf("unexpected files written without env: %v", entries)
	}
}
