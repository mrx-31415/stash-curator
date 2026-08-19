//go:build linux

package main

import "syscall"

// I/O priority is the half that matters most here: the build's disk writes are
// what make a co-hosted Stash unresponsive, and CPU niceness does nothing
// about them.
const (
	ioprioWhoProcess = 1 // IOPRIO_WHO_PROCESS
	ioprioClassBE    = 2 // IOPRIO_CLASS_BE
	ioprioClassShift = 13
	ioprioBELowest   = 7 // best-effort levels run 0 (highest) to 7 (lowest)
)

// lowerIOPriority puts the worker in the lowest best-effort I/O band.
//
// Deliberately not IOPRIO_CLASS_IDLE: idle only gets serviced when the disk is
// otherwise quiet, which on a busy host can stall a build indefinitely rather
// than merely slowing it. Lowest best-effort still yields to everything else
// while guaranteeing forward progress.
func lowerIOPriority() {
	_, _, _ = syscall.Syscall(
		syscall.SYS_IOPRIO_SET,
		ioprioWhoProcess,
		0, // the calling process
		uintptr(ioprioClassBE<<ioprioClassShift|ioprioBELowest),
	)
}
