//go:build windows

package main

import "syscall"

// BELOW_NORMAL_PRIORITY_CLASS. PROCESS_MODE_BACKGROUND_BEGIN would also lower
// I/O priority, but it is only valid for the calling process on Vista+ and
// silently fails when the process is already in background mode, so the plain
// class change is the predictable choice.
const belowNormalPriorityClass = 0x00004000

// lowerWorkerPriority mirrors the unix implementation. Failures are ignored:
// lower priority is an optimization, not a precondition for running.
func lowerWorkerPriority() {
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	setPriorityClass := kernel32.NewProc("SetPriorityClass")
	handle, err := syscall.GetCurrentProcess()
	if err != nil {
		return
	}
	_, _, _ = setPriorityClass.Call(uintptr(handle), belowNormalPriorityClass)
}
