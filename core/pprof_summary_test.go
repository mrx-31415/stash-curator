package main

import (
	"bytes"
	"runtime/pprof"
	"strings"
	"testing"
)

// pprofBusyWork is the known-hot function the CPU-profile tests look for.
// Not inlined so the stack trace carries its frame.
//
//go:noinline
func pprofBusyWork() float64 {
	total := 0.0
	for i := 0; i < 30_000_000; i++ {
		total += float64(i) * 0.5
	}
	return total
}

func TestPprofSummaryParsesCPUProfile(t *testing.T) {
	var buf bytes.Buffer
	if err := pprof.StartCPUProfile(&buf); err != nil {
		t.Fatal(err)
	}
	_ = pprofBusyWork()
	pprof.StopCPUProfile()

	summary, err := pprofSummary(buf.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	if summary.get("kind").asString() != "cpu" {
		t.Errorf("kind = %s", summary.get("kind").asString())
	}
	if summary.get("unit_label").asString() != "ms" {
		t.Errorf("unit_label = %s", summary.get("unit_label").asString())
	}
	if numberValue(summary.get("total")) <= 0 {
		t.Error("total not positive")
	}
	if numberValue(summary.get("sample_count")) <= 0 {
		t.Error("sample_count not positive")
	}
	top := summary.get("top")
	if top.kind != jArr || len(top.arr) == 0 {
		t.Fatalf("top = %s", summary.marshalCompact())
	}
	found := false
	for _, row := range top.arr {
		name := row.get("name").asString()
		if strings.Contains(name, "pprofBusyWork") {
			found = true
			if numberValue(row.get("flat_pct")) <= 0 || numberValue(row.get("cum_pct")) <= 0 {
				t.Errorf("row %s missing percentages: %s", name, row.marshalCompact())
			}
		}
	}
	if !found {
		t.Error("pprofBusyWork missing from the top table")
	}
	// The flame tree must contain the busy function somewhere under root.
	if !flameContains(summary.get("flame"), "pprofBusyWork") {
		t.Error("pprofBusyWork missing from the flame tree")
	}
}

func TestPprofSummaryParsesHeapProfile(t *testing.T) {
	var buf bytes.Buffer
	if err := pprof.WriteHeapProfile(&buf); err != nil {
		t.Fatal(err)
	}
	summary, err := pprofSummary(buf.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	if summary.get("kind").asString() != "heap" {
		t.Errorf("kind = %s", summary.get("kind").asString())
	}
	if summary.get("unit_label").asString() != "MiB" {
		t.Errorf("unit_label = %s", summary.get("unit_label").asString())
	}
}

func flameContains(node jVal, needle string) bool {
	if strings.Contains(node.get("name").asString(), needle) {
		return true
	}
	for _, child := range node.get("children").arr {
		if flameContains(child, needle) {
			return true
		}
	}
	return false
}
