package main

import "runtime/debug"

// releaseMemoryToOS forces a collection and hands the freed pages back to the
// operating system.
//
// A model build allocates on the order of a gigabyte, nearly all of which is
// garbage the moment the job ends: lane classification alone materializes
// every scene's classifications twice before writing. Go's runtime is content
// to keep those pages mapped for reuse, so without this the daemon's RSS stays
// at the build's high-water mark.
//
// That matters because the daemon does not always exit when it goes idle:
// schedulerStayAlive keeps it resident whenever a dirty model or unsynced
// plays mean work is coming, so it would otherwise sit on a build's footprint
// while doing nothing, on a machine that is usually also serving Stash.
//
// The cost is one forced GC, which is milliseconds against jobs measured in
// seconds to minutes.
func releaseMemoryToOS() {
	debug.FreeOSMemory()
}
