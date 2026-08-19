//go:build unix && !linux

package main

// lowerIOPriority is a no-op away from Linux: darwin has no ioprio_set, and
// its setiopolicy_np equivalent is not reachable from the standard library.
// CPU niceness still applies there.
func lowerIOPriority() {}
