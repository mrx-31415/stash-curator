//go:build unix

package main

import (
	"runtime"
	"syscall"
)

// peakRSSKB returns the process's peak resident set size in KiB (Getrusage
// RUSAGE_SELF Maxrss). Linux reports Maxrss in KiB; Darwin reports bytes, so
// convert so the reported value is always KiB.
func peakRSSKB() int64 {
	var usage syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &usage); err != nil {
		return 0
	}
	if runtime.GOOS == "darwin" {
		return usage.Maxrss / 1024
	}
	return usage.Maxrss
}
