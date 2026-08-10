// Python fallback dispatch: delegate unported operations, tasks, and the
// entity-sync hook mode to the bundled backend.py.
//
// The binary spawns pluginDir/backend.py with the same argv it received
// ([pluginDir, mode]) and the exact stdin payload, and relays stdout and
// stderr untouched, so the plugin sees byte-identical behavior while the port
// is in flight. fallbackToPython never returns: it mirrors the child's exit
// status (backend.py exits 1 after printing {"error": ...}).
package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func fallbackToPython(pluginDir, mode string, payload []byte) {
	script := filepath.Join(pluginDir, "backend.py")
	if _, err := os.Stat(script); err != nil {
		writeError(fmt.Sprintf("curator-core: backend.py fallback unavailable: %v", err))
	}
	python, err := findPython()
	if err != nil {
		writeError(fmt.Sprintf("curator-core: python interpreter unavailable for fallback: %v", err))
	}
	argv := []string{script, pluginDir}
	if mode != "" {
		argv = append(argv, mode)
	}
	cmd := exec.Command(python, argv...)
	cmd.Stdin = bytes.NewReader(payload)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	runErr := cmd.Run()
	code := 0
	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			code = exitErr.ExitCode()
		} else {
			code = 1
		}
	}
	os.Exit(code)
}

func findPython() (string, error) {
	for _, candidate := range []string{"python3", "python"} {
		if path, err := exec.LookPath(candidate); err == nil {
			return path, nil
		}
	}
	return "", errors.New("neither python3 nor python found in PATH")
}
