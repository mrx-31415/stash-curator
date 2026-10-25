package main

import (
	"os"
	"strconv"
	"strings"
)

// workerGCPercent is the daemon's GOGC default (see runDaemon); GOGC
// in the environment overrides it.
const workerGCPercent = 50

// Leave half the container's memory for Stash, kernel subprocesses and SQLite.
// shortcut: Go's limit is soft, reduce live build data if collections cannot fit.
func workerMemoryBudget(paths ...string) int64 {
	var budget int64
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		limit, err := strconv.ParseInt(strings.TrimSpace(string(data)), 10, 64)
		if err == nil && limit > 1 && (budget == 0 || limit/2 < budget) {
			budget = limit / 2
		}
	}
	return budget
}
