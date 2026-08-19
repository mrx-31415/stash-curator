//go:build unix

package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"testing"
)

// Raising niceness is irreversible without privileges, so the assertion runs
// in a re-exec of the test binary: doing it in-process would leave every
// later test in the package running at +10.
const lowerPriorityChildEnv = "CURATOR_TEST_LOWER_PRIORITY_CHILD"

func TestLowerWorkerPriorityLowersCPUPriority(t *testing.T) {
	if os.Getenv(lowerPriorityChildEnv) == "1" {
		before, err := syscall.Getpriority(syscall.PRIO_PROCESS, 0)
		if err != nil {
			fmt.Printf("ERR before %v\n", err)
			return
		}
		lowerWorkerPriority()
		after, err := syscall.Getpriority(syscall.PRIO_PROCESS, 0)
		if err != nil {
			fmt.Printf("ERR after %v\n", err)
			return
		}
		fmt.Printf("RESULT %d %d\n", before, after)
		return
	}

	cmd := exec.Command(os.Args[0], "-test.run=TestLowerWorkerPriorityLowersCPUPriority", "-test.v")
	cmd.Env = append(os.Environ(), lowerPriorityChildEnv+"=1")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("child failed: %v\n%s", err, out)
	}
	var before, after int
	var found bool
	for _, line := range strings.Split(string(out), "\n") {
		if strings.HasPrefix(line, "RESULT ") {
			if _, err := fmt.Sscanf(line, "RESULT %d %d", &before, &after); err != nil {
				t.Fatalf("unparsable result %q: %v", line, err)
			}
			found = true
		}
	}
	if !found {
		t.Fatalf("child produced no result:\n%s", out)
	}
	// getpriority reports 20-nice, not the nice value, so a *lower* number is
	// a *lower* priority. Asserting after > before would be backwards.
	if after >= before {
		t.Fatalf("priority not lowered: getpriority before=%d after=%d (lower is nicer)", before, after)
	}
}
