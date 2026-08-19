//go:build unix

package main

import "syscall"

// workerNiceness is how far the background worker is pushed below everything
// else on the box. A model build peaks around 5 GiB RSS and writes a
// multi-hundred-megabyte artifact, so on a machine that is also serving Stash
// it competes directly with the thing the user is looking at. +10 is a large
// step down without being so extreme that the build never finishes on a busy
// host.
const workerNiceness = 10

// lowerWorkerPriority de-prioritizes the calling process for CPU and, where
// the platform supports it, disk. Only the daemon calls this: foreground
// plugin invocations are answering a user action and must stay at normal
// priority. Children inherit both settings, so the build kernels the daemon
// spawns are covered without touching their spawn sites.
//
// Failures are ignored by design. Lower priority is an optimization, and a
// sandbox that forbids setpriority is not a reason to refuse to run.
func lowerWorkerPriority() {
	_ = syscall.Setpriority(syscall.PRIO_PROCESS, 0, workerNiceness)
	lowerIOPriority()
}
