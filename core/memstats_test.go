package main

import (
	"runtime"
	"testing"
)

func TestMemSnapshotKeysPresent(t *testing.T) {
	snapshot := memSnapshot()
	for _, key := range []string{"peak_rss_kb", "heap_alloc_kb", "heap_sys_kb", "total_alloc_kb", "num_gc"} {
		if snapshot.get(key).kind != jNum {
			t.Errorf("memSnapshot missing %s: %s", key, snapshot.marshalCompact())
		}
	}
	// Runtime guarantees: some heap is allocated by the test process and at
	// least one GC cycle has run before this test.
	if snapshot.get("total_alloc_kb").asString() == "0" {
		t.Error("total_alloc_kb = 0")
	}
	if snapshot.get("num_gc").asString() == "0" {
		t.Error("num_gc = 0")
	}
}

func TestPeakRSSKBOnLinux(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Getrusage peak semantics are linux-specific in this test")
	}
	peak := peakRSSKB()
	if peak <= 0 {
		t.Errorf("peakRSSKB = %d, want > 0", peak)
	}
	// A resident test process is a few MiB at minimum; the peak must be
	// plausible for a process that has loaded the Go runtime.
	if peak < 1024 {
		t.Errorf("peakRSSKB = %d kB, implausibly small", peak)
	}
}
