package main

import (
	"encoding/json"
	"errors"
	"testing"
	"time"
)

func TestStageRecorderFillsTimingsAndSpans(t *testing.T) {
	rec := newStageRecorder()
	if err := rec.stage("feature_lookup", "", func() error {
		time.Sleep(2 * time.Millisecond)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	timings := rec.timingsMap()
	if got := timings["feature_lookup"]; got < 1 {
		t.Errorf("feature_lookup timing = %d ms, want >= 1", got)
	}
	memory := rec.stageMemory()
	snapshot, ok := memory["feature_lookup"]
	if !ok {
		t.Fatal("stage_memory missing feature_lookup key")
	}
	if snapshot.get("peak_rss_kb").kind != jNum {
		t.Errorf("stage_memory peak_rss_kb = %s", snapshot.marshalCompact())
	}
	// A stage error propagates; the timing is still recorded (Python's
	// span() records in its finally block, and a failed build discards the
	// drain result anyway).
	boom := errors.New("boom")
	if err := rec.stage("scoring", "", func() error { return boom }); err != boom {
		t.Errorf("stage error = %v, want boom", err)
	}
	if _, ok := rec.timingsMap()["scoring"]; !ok {
		t.Error("failed stage recorded no timing")
	}
}

func TestStageRecorderEmptyKeys(t *testing.T) {
	rec := newStageRecorder()
	// An empty timingKey records no stage key (spans-only stages like
	// feature.tfidf); an empty spanName records no span (Python had timings
	// without spans for those stages).
	trace := beginTrace("model-build", "task")
	defer endTrace(trace)
	if err := rec.stage("", "feature.tfidf", func() error {
		time.Sleep(time.Millisecond)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if len(rec.timingsMap()) != 0 {
		t.Errorf("empty timingKey wrote a stage key: %v", rec.timingsMap())
	}
	found := false
	for _, event := range trace.events {
		if event.name == "feature.tfidf" && event.category == "python" {
			found = true
			if event.details.get("peak_rss_kb").kind != jNum {
				t.Errorf("span details lack memory: %s", event.details.marshalCompact())
			}
		}
	}
	if !found {
		t.Error("no python feature.tfidf span recorded in the active trace")
	}
}

func TestStageRecorderSetRecordsTimingAndMemory(t *testing.T) {
	rec := newStageRecorder()
	rec.set("score_first_ordering", 0)
	rec.set("total", 42)
	timings := rec.timingsMap()
	if timings["score_first_ordering"] != 0 || timings["total"] != 42 {
		t.Errorf("set timings = %v", timings)
	}
	if _, ok := rec.stageMemory()["total"]; !ok {
		t.Error("set did not record a memory snapshot")
	}
}

func TestJvPlainRoundTrip(t *testing.T) {
	value := jvObj(
		jvKey("peak_rss_kb", jvInt(1234)),
		jvKey("heap_alloc_kb", jvInt(567)),
		jvKey("label", jvStr("x")),
		jvKey("flag", jvBool(true)),
		jvKey("nothing", jvNull()),
	)
	plain := jvPlain(value)
	encoded, err := json.Marshal(plain)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := parseJSON(encoded)
	if err != nil {
		t.Fatalf("jvPlain output is not valid JSON: %v", err)
	}
	if parsed.get("peak_rss_kb").asString() != "1234" {
		t.Errorf("peak_rss_kb = %s", parsed.get("peak_rss_kb").asString())
	}
	if parsed.get("nothing").kind != jNull {
		t.Errorf("nothing = %s", parsed.marshalCompact())
	}
}
