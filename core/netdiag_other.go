//go:build !windows

package main

// socketSummary is reported only on Windows, where ephemeral port exhaustion
// has been seen in practice.
func socketSummary(string) jVal { return jvNull() }
