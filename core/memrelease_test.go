package main

import (
	"runtime"
	"testing"
)

// The daemon calls releaseMemoryToOS after every job so it does not idle at a
// build's high-water mark. Assert the pages actually come back rather than
// just that the call returns: a plain runtime.GC() collects the garbage but
// leaves it mapped, which is the exact behaviour this guards against.
func TestReleaseMemoryToOSReturnsPagesToTheOS(t *testing.T) {
	// Allocate enough that the runtime takes fresh spans from the OS rather
	// than serving the request from what it already holds.
	const chunks, chunkBytes = 64, 4 << 20 // 256 MiB total
	ballast := make([][]byte, 0, chunks)
	for i := 0; i < chunks; i++ {
		block := make([]byte, chunkBytes)
		// Touch each page so it is resident, not just reserved.
		for offset := 0; offset < len(block); offset += 4096 {
			block[offset] = byte(i)
		}
		ballast = append(ballast, block)
	}
	runtime.KeepAlive(ballast)
	ballast = nil

	// A collection alone frees the objects but keeps the pages mapped.
	runtime.GC()
	var afterGC runtime.MemStats
	runtime.ReadMemStats(&afterGC)

	releaseMemoryToOS()
	var afterRelease runtime.MemStats
	runtime.ReadMemStats(&afterRelease)

	if afterRelease.HeapReleased <= afterGC.HeapReleased {
		t.Errorf(
			"HeapReleased did not grow: after GC %d KiB, after release %d KiB",
			afterGC.HeapReleased/1024, afterRelease.HeapReleased/1024,
		)
	}
	if afterRelease.HeapIdle < afterRelease.HeapReleased {
		t.Errorf(
			"released %d KiB exceeds idle %d KiB",
			afterRelease.HeapReleased/1024, afterRelease.HeapIdle/1024,
		)
	}
}
