//go:build linux

package main

import (
	"syscall"
	"testing"
)

const sysIoprioGet = syscall.SYS_IOPRIO_SET + 1 // ioprio_get follows ioprio_set

func TestLowerIOPriorityMovesToLowestBestEffort(t *testing.T) {
	lowerIOPriority()
	value, _, errno := syscall.Syscall(sysIoprioGet, ioprioWhoProcess, 0, 0)
	if errno != 0 {
		t.Skipf("ioprio_get unavailable: %v", errno)
	}
	if class := int(value) >> ioprioClassShift; class != ioprioClassBE {
		t.Errorf("io class = %d, want %d (best-effort)", class, ioprioClassBE)
	}
	if level := int(value) & 7; level != ioprioBELowest {
		t.Errorf("io level = %d, want %d (lowest)", level, ioprioBELowest)
	}
}
