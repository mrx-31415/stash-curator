// Command curator-core is the optional compiled accelerator for Stash Curator.
//
// It has two modes. The kernel mode replaces numpy's role in the model build:
// the content-neighbor and performer-similarity kernels mirror the production
// Python implementations in curator/model/builder.py with identical semantics,
// reading feature rows directly from the SQLite feature artifact (see
// content.go, performer.go, multi_hop.go). The backend mode (Slice 0 of the
// full Go backend) implements the raw-plugin interface on stdin/stdout —
// the same contract plugin/backend.py serves — for the ported ops
// (round_trip, health, get_config, get_job_status), with a Python fallback
// spawning backend.py for everything else (backend.go, ops.go, fallback.go).
//
// Kernel protocol: the payload is a single JSON object on stdin; stdout is
// newline-delimited JSON with optional {"progress": fraction} lines followed by
// a final {"result": ...} line. Errors are written to stderr with a non-zero
// exit status.
package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// coreVersion is injected at build time (scripts/build_core.sh) from
// pyproject.toml, which stays the single version source for the plugin.
var coreVersion = "dev"

// coreProtocol is the wire-contract version the Python side requires
// (curator/core.py CORE_PROTOCOL). Bump when the payload/output shapes change.
const coreProtocol = 1

// kernelCommands are the compiled-core stage commands. argv[1] is one of
// these in kernel mode; anything else is the raw-plugin backend mode, where
// argv[1] is the plugin directory (matching backend.py's argv contract) and
// argv[2] is the optional task/hook mode.
var kernelCommands = map[string]bool{
	"version":              true,
	"content-neighbors":    true,
	"performer-similarity": true,
	"multi-hop":            true,
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "curator-core: "+format+"\n", args...)
	os.Exit(1)
}

func writeJSONLine(value any) error {
	buf, err := json.Marshal(value)
	if err != nil {
		return err
	}
	buf = append(buf, '\n')
	_, err = os.Stdout.Write(buf)
	return err
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fail("usage: curator-core {version|content-neighbors|performer-similarity|multi-hop} | {pluginDir} [task-mode]")
	}
	if kernelCommands[args[0]] {
		switch args[0] {
		case "version":
			if err := writeJSONLine(map[string]any{
				"protocol": coreProtocol,
				"version":  coreVersion,
			}); err != nil {
				fail("write version: %v", err)
			}
		case "content-neighbors":
			runContentNeighbors()
		case "performer-similarity":
			runPerformerSimilarity()
		case "multi-hop":
			runMultiHop()
		}
		return
	}
	// Raw-plugin backend mode: argv[1] = plugin dir, argv[2] = task/hook mode.
	pluginDir := args[0]
	mode := ""
	if len(args) > 1 {
		mode = args[1]
	}
	runBackend(pluginDir, mode)
}
