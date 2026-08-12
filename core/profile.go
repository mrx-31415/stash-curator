package main

// Lightweight span profiling for the compiled core. When the payload requests
// it (`profile: true`), stages record (name, offset from process start,
// duration) and emit them as NDJSON `{"span": ...}` lines before the result;
// the Python side (curator/core.py run_core) folds them into the plugin's
// profile_trace with category "core". Chrome-trace microsecond units, same as
// the Python Trace.record payloads.

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/pprof"
	"sync"
	"time"
)

var processStarted = time.Now()

type spanRecord struct {
	name     string
	offsetUs int64
	durUs    int64
}

type profileRecorder struct {
	mu      sync.Mutex
	started time.Time
	enabled bool
	spans   []spanRecord
}

func newProfileRecorder(enabled bool) *profileRecorder {
	return &profileRecorder{started: processStarted, enabled: enabled}
}

// begin opens a span; call the returned function to close it.
func (p *profileRecorder) begin(name string) func() {
	if p == nil || !p.enabled {
		return func() {}
	}
	started := time.Now()
	return func() {
		ended := time.Now()
		p.mu.Lock()
		p.spans = append(p.spans, spanRecord{
			name:     name,
			offsetUs: started.Sub(p.started).Microseconds(),
			durUs:    ended.Sub(started).Microseconds(),
		})
		p.mu.Unlock()
	}
}

// emit writes the recorded spans as NDJSON lines before the final result.
func (p *profileRecorder) emit() {
	if p == nil || !p.enabled {
		return
	}
	p.mu.Lock()
	spans := make([]spanRecord, len(p.spans))
	copy(spans, p.spans)
	p.mu.Unlock()
	for _, s := range spans {
		_ = writeJSONLine(map[string]any{
			"span": map[string]any{
				"name":      s.name,
				"cat":       "core",
				"offset_us": s.offsetUs,
				"dur_us":    s.durUs,
			},
		})
	}
}

// startProfiling enables on-demand Go runtime profiling for this process,
// switched on by environment variables so no rebuild is needed:
//
//	CURATOR_CORE_CPU_PROFILE_DIR=<dir>   CPU profile per process on exit
//	CURATOR_CORE_MEM_PROFILE_DIR=<dir>   heap profile per process on exit
//
// Each process writes its own file (<kind>-<mode>-<pid>.pprof) into the
// directory (created if missing). A model-build run re-executes the
// content-neighbors and performer-similarity kernels as subprocesses, and
// they inherit the env, so the run yields one profile per process — analyze
// with `go tool pprof`. Start/stop errors are reported on stderr and the
// process continues unprofiled.
func startProfiling(mode string) (stopCPU func(), dumpMem func()) {
	stopCPU = func() {}
	dumpMem = func() {}
	if dir := os.Getenv("CURATOR_CORE_CPU_PROFILE_DIR"); dir != "" {
		path := profilePath(dir, "cpu", mode)
		file, err := os.Create(path)
		if err != nil {
			fmt.Fprintf(os.Stderr, "curator-core: cpu profile: %v\n", err)
		} else if err := pprof.StartCPUProfile(file); err != nil {
			fmt.Fprintf(os.Stderr, "curator-core: cpu profile: %v\n", err)
			file.Close()
		} else {
			stopCPU = func() {
				pprof.StopCPUProfile()
				file.Close()
			}
		}
	}
	if dir := os.Getenv("CURATOR_CORE_MEM_PROFILE_DIR"); dir != "" {
		dumpMem = func() {
			path := profilePath(dir, "mem", mode)
			file, err := os.Create(path)
			if err != nil {
				fmt.Fprintf(os.Stderr, "curator-core: mem profile: %v\n", err)
				return
			}
			defer file.Close()
			runtime.GC() // settle the live heap so the inuse view is meaningful
			if err := pprof.WriteHeapProfile(file); err != nil {
				fmt.Fprintf(os.Stderr, "curator-core: mem profile: %v\n", err)
			}
		}
	}
	return stopCPU, dumpMem
}

// profilePath returns the per-process profile file path inside dir, creating
// dir when missing.
func profilePath(dir, kind, mode string) string {
	_ = os.MkdirAll(dir, 0o755)
	return filepath.Join(dir, fmt.Sprintf("%s-%s-%d.pprof", kind, mode, os.Getpid()))
}
