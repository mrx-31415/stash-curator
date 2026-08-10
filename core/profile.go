package main

// Lightweight span profiling for the compiled core. When the payload requests
// it (`profile: true`), stages record (name, offset from process start,
// duration) and emit them as NDJSON `{"span": ...}` lines before the result;
// the Python side (curator/core.py run_core) folds them into the plugin's
// profile_trace with category "core". Chrome-trace microsecond units, same as
// the Python Trace.record payloads.

import (
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
