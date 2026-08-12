//go:build windows

package main

import "runtime"

// peakRSSKB reports the heap-sys proxy on windows (no Getrusage); the plan
// accepts this approximation — linux/darwin get true RSS.
func peakRSSKB() int64 {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return int64(stats.HeapSys) / 1024
}
