//go:build unix

package main

import "testing"

func TestProcZombie(t *testing.T) {
	if !procZombie([]byte("42 (curator core) Z 1 2 3")) {
		t.Fatal("zombie process not detected")
	}
	if procZombie([]byte("42 (curator core) S 1 2 3")) {
		t.Fatal("live process reported as zombie")
	}
}
