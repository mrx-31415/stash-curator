// Build-stage instrumentation — the shared stage recorder behind the model
// and feature build timings (issue #124). It measures named stages in whole
// milliseconds (Python's round() semantics via elapsedMs), keeps a per-stage
// memory snapshot, and, when a trace is active, records each stage as a
// "python"-category span with the Python-era span name and the memory
// snapshot as details. The recorder is passed down from the kernel command
// (runModelBuild / runFeatureBuild) or the task-mode build (coordinatorDrain
// -> modelBuild), so the drained result carries every stage's timing and
// memory for the trace and the kernel result surface.
package main

import (
	"sync"
	"time"
)

// stageRecorder accumulates build-stage timings and memory snapshots. Stages
// run sequentially within a build; the mutex guards the maps for the kernel
// result readers and keeps the recorder safe to share.
type stageRecorder struct {
	mu      sync.Mutex
	timings map[string]int64 // timing key -> elapsed whole ms
	memory  map[string]jVal  // timing key -> memSnapshot() at stage end
}

func newStageRecorder() *stageRecorder {
	return &stageRecorder{
		timings: map[string]int64{},
		memory:  map[string]jVal{},
	}
}

// stage runs fn under timingKey, recording the elapsed whole milliseconds,
// and returns fn's error. When spanName is non-empty it also records a
// "python"-category span (Python-era stage name) with a memory snapshot as
// details. An empty timingKey records no timing/memory entry (used for
// spans-only stages like feature.tfidf); an empty spanName records no span
// (the Python side had timings without spans for those stages).
func (r *stageRecorder) stage(timingKey, spanName string, fn func() error) error {
	started := time.Now()
	err := fn()
	if timingKey != "" {
		r.set(timingKey, elapsedMs(started))
	}
	if spanName != "" {
		recordStageSpan(spanName, started)
	}
	return err
}

// set stores a precomputed or fixed timing value (the reuse-check lookup,
// the zeroed score_first_ordering / reason_generation keys) together with a
// memory snapshot at that point.
func (r *stageRecorder) set(key string, ms int64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.timings[key] = ms
	r.memory[key] = memSnapshot()
}

// timingsMap returns a copy of the recorded timings.
func (r *stageRecorder) timingsMap() map[string]int64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]int64, len(r.timings))
	for key, value := range r.timings {
		out[key] = value
	}
	return out
}

// stageMemory returns a copy of the per-stage memory snapshots.
func (r *stageRecorder) stageMemory() map[string]jVal {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]jVal, len(r.memory))
	for key, value := range r.memory {
		out[key] = value
	}
	return out
}

// recordStageSpan records a "python"-category stage span ending now with a
// memory snapshot as details, mirroring curator.profiling.span() with the
// build's memory fields attached.
func recordStageSpan(name string, started time.Time) {
	if t := currentTrace(); t != nil {
		t.record("python", name, started.UnixNano(), time.Since(started).Nanoseconds(), memSnapshot())
	}
}

// jvPlain converts a jVal into plain Go values so encoding/json can marshal
// it (kernel NDJSON results go through the stdlib encoder; jVal itself has
// no MarshalJSON method).
func jvPlain(v jVal) any {
	switch v.kind {
	case jNull:
		return nil
	case jBool:
		return v.b
	case jNum:
		f, err := pythonFloat(v)
		if err != nil {
			return v.num
		}
		return f
	case jStr:
		return v.s
	case jArr:
		out := make([]any, 0, len(v.arr))
		for _, item := range v.arr {
			out = append(out, jvPlain(item))
		}
		return out
	case jObj:
		out := make(map[string]any, len(v.obj))
		for _, pair := range v.obj {
			out[pair.key] = jvPlain(pair.val)
		}
		return out
	}
	return nil
}

// stageMemoryPlain converts a per-stage memory map into plain Go values for
// the kernel NDJSON result.
func stageMemoryPlain(raw map[string]jVal) map[string]any {
	out := make(map[string]any, len(raw))
	for key, value := range raw {
		out[key] = jvPlain(value)
	}
	return out
}

// stageMemoryPlain converts the recorder's per-stage memory snapshots into
// plain Go values for the kernel NDJSON result.
func (r *stageRecorder) stageMemoryPlain() map[string]any {
	return stageMemoryPlain(r.stageMemory())
}
