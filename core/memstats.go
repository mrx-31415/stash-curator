// Build-stage memory capture. memSnapshot returns a jVal with the process
// peak RSS and the runtime heap counters; build stages attach it to their
// trace spans and the kernel results expose it as stage_memory / peak_rss_kb.
package main

import "runtime"

// memSnapshot returns a jVal with: peak_rss_kb (Getrusage RUSAGE_SELF
// Maxrss on unix; HeapSys/1024 proxy on windows — see memstats_unix.go /
// memstats_windows.go), heap_alloc_kb, heap_sys_kb, total_alloc_kb, num_gc
// (runtime.ReadMemStats).
func memSnapshot() jVal {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return jvObj(
		jvKey("peak_rss_kb", jvInt(peakRSSKB())),
		jvKey("heap_alloc_kb", jvInt(int64(stats.HeapAlloc)/1024)),
		jvKey("heap_sys_kb", jvInt(int64(stats.HeapSys)/1024)),
		jvKey("total_alloc_kb", jvInt(int64(stats.TotalAlloc)/1024)),
		jvKey("num_gc", jvInt(int64(stats.NumGC))),
	)
}
