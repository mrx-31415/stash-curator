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
	"sort"
	"strings"
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

// startProfiling enables on-demand Go runtime profiling for this process.
// cpuDir/memDir select the output directories; an empty value falls back to
// the CURATOR_CORE_CPU_PROFILE_DIR / CURATOR_CORE_MEM_PROFILE_DIR env vars.
//
// Each process writes its own file (<kind>-<mode>-<pid>.pprof) into the
// directory (created if missing). A model-build run re-executes the
// content-neighbors and performer-similarity kernels as subprocesses, and
// they inherit the env, so the run yields one profile per process — analyze
// with `go tool pprof`. Start/stop errors are reported on stderr and the
// process continues unprofiled.
func startProfiling(mode, cpuDir, memDir string) (stopCPU func(), dumpMem func()) {
	stopCPU = func() {}
	dumpMem = func() {}
	if cpuDir == "" {
		cpuDir = os.Getenv("CURATOR_CORE_CPU_PROFILE_DIR")
	}
	if memDir == "" {
		memDir = os.Getenv("CURATOR_CORE_MEM_PROFILE_DIR")
	}
	if cpuDir != "" {
		path := profilePath(cpuDir, "cpu", mode)
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
	if memDir != "" {
		dumpMem = func() {
			path := profilePath(memDir, "mem", mode)
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

// maxPprofFiles bounds the per-session profile files kept in the sidecar
// profiles directory (oldest pruned at capture time).
const maxPprofFiles = 20

// startProfilingFor turns on pprof capture for one plugin operation when the
// pprofEnabled setting is on: profiles land in <sidecar dir>/profiles (the
// same directory as the sidecar database), and the env vars are set so the
// model-build kernel subprocesses inherit the capture. Returns no-op
// closers when the setting is off.
func startProfilingFor(pluginDir string, payload, settings jVal, mode string) (stopCPU func(), dumpMem func()) {
	stopCPU = func() {}
	dumpMem = func() {}
	if !settings.get("pprofEnabled").truthy() {
		return stopCPU, dumpMem
	}
	dir := pprofProfilesDir(pluginDir, payload, settings)
	prunePprofFiles(dir, maxPprofFiles)
	os.Setenv("CURATOR_CORE_CPU_PROFILE_DIR", dir)
	os.Setenv("CURATOR_CORE_MEM_PROFILE_DIR", dir)
	return startProfiling(mode, dir, dir)
}

// prunePprofFiles keeps the newest max profile files in dir (by mtime),
// deleting the oldest beyond the cap.
func prunePprofFiles(dir string, max int) {
	type entry struct {
		name string
		mod  int64
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	var files []entry
	for _, item := range entries {
		if item.IsDir() || !strings.HasSuffix(item.Name(), ".pprof") {
			continue
		}
		info, err := item.Info()
		if err != nil {
			continue
		}
		files = append(files, entry{item.Name(), info.ModTime().UnixMilli()})
	}
	if len(files) <= max {
		return
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mod < files[j].mod })
	for _, item := range files[:len(files)-max] {
		_ = os.Remove(filepath.Join(dir, item.name))
	}
}

// profilePath returns the per-process profile file path inside dir, creating
// dir when missing.
func profilePath(dir, kind, mode string) string {
	_ = os.MkdirAll(dir, 0o755)
	return filepath.Join(dir, fmt.Sprintf("%s-%s-%d.pprof", kind, mode, os.Getpid()))
}
