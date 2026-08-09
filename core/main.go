// Command curator-core is the optional compiled accelerator for Stash Curator.
//
// It replaces numpy's role in the model build: the content-neighbor and
// performer-similarity kernels mirror the production Python implementations in
// curator/model/builder.py with identical semantics, reading feature rows
// directly from the SQLite feature artifact. The plugin keeps the raw interface
// and the pure-Python fallback; this binary is optional acceleration exactly
// like numpy today.
//
// Protocol: the payload is a single JSON object on stdin; stdout is
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
		fail("usage: curator-core {version|content-neighbors|performer-similarity}")
	}
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
	default:
		fail("unknown command: %s", args[0])
	}
}
