package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWorkerMemoryBudget(t *testing.T) {
	for _, value := range []string{"4294967296\n", "max\n", "0", "-1", "invalid"} {
		t.Run(value, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "memory.max")
			if err := os.WriteFile(path, []byte(value), 0600); err != nil {
				t.Fatal(err)
			}
			want := int64(0)
			if value == "4294967296\n" {
				want = 2 << 30
			}
			if got := workerMemoryBudget(path+".missing", path); got != want {
				t.Fatalf("budget = %d, want %d", got, want)
			}
		})
	}
}
