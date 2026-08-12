// Pprof summary — parse a captured .pprof file into a browser-viewable
// shape for the Profiling page: the sample type/unit, capture duration, a
// top-function table (flat and cumulative time), and a flame-graph tree
// keyed by call stack. Uses github.com/google/pprof/profile (the parser the
// Go toolchain itself uses); the runtime-written profiles carry their
// symbols, so no separate symbolization is needed.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/google/pprof/profile"
)

// pprofSampleKind names the interesting sample type of a profile: cpu time
// for CPU profiles, live heap space for heap profiles, else the first type.
func pprofSampleKind(p *profile.Profile) (index int, kindName, label string, scale float64) {
	for i, st := range p.SampleType {
		switch {
		case st.Type == "cpu" && st.Unit == "nanoseconds":
			return i, "cpu", "ms", 1.0 / 1e6
		case st.Type == "inuse_space" && st.Unit == "bytes":
			return i, "heap", "MiB", 1.0 / (1 << 20)
		case st.Type == "alloc_space" && st.Unit == "bytes":
			return i, "heap", "MiB", 1.0 / (1 << 20)
		}
	}
	kindName = p.SampleType[0].Type
	switch p.SampleType[0].Unit {
	case "nanoseconds":
		label, scale = "ms", 1.0/1e6
	case "bytes":
		label, scale = "MiB", 1.0/(1<<20)
	default:
		label, scale = p.SampleType[0].Unit, 1.0
	}
	return 0, kindName, label, scale
}

// pprofFrame is one call-stack frame in the aggregation.
type pprofFrame struct {
	name string
	loc  string
}

// pprofFlameNode accumulates sample values across a call path.
type pprofFlameNode struct {
	name     string
	loc      string
	flat     float64 // leaf samples (self time), in display units
	total    float64 // this frame and below, in display units
	children []pprofFlameNode
}

// frameOf maps a profile location to its display frame (outermost line).
func frameOf(loc *profile.Location) pprofFrame {
	if len(loc.Line) == 0 {
		return pprofFrame{"(unknown)", ""}
	}
	line := loc.Line[0]
	fn := line.Function
	name := ""
	if fn != nil {
		name = fn.SystemName
		if name == "" {
			name = fn.Name
		}
		locText := ""
		if fn.Filename != "" {
			locText = fmt.Sprintf("%s:%d", fn.Filename, line.Line)
		}
		return pprofFrame{name, locText}
	}
	return pprofFrame{"(unknown)", ""}
}

// minFlameTotal drops flame nodes too small to be visible (keeps the tree
// JSON bounded for multi-minute profiles).
const minFlameTotalFraction = 0.0001

// pprofSummary parses a profile file and returns the view model as a jVal:
// {kind, unit_label, duration_ms, sample_count, total, top: [...], flame}.
func pprofSummary(data []byte) (jVal, error) {
	p, err := profile.ParseData(data)
	if err != nil {
		return jvNull(), err
	}
	if len(p.SampleType) == 0 {
		return jvNull(), fmt.Errorf("profile has no sample types")
	}
	index, kindName, label, scale := pprofSampleKind(p)
	type node struct {
		frame    pprofFrame
		flat     float64
		total    float64
		children map[string]*node
	}
	root := &node{frame: pprofFrame{name: "total"}, children: map[string]*node{}}
	total := 0.0
	for _, sample := range p.Sample {
		value := float64(sample.Value[index]) * scale
		total += value
		root.total += value
		cur := root
		// Sample locations are leaf-first; build the tree root-first.
		for i := len(sample.Location) - 1; i >= 0; i-- {
			frame := frameOf(sample.Location[i])
			next, ok := cur.children[frame.name]
			if !ok {
				next = &node{frame: frame, children: map[string]*node{}}
				cur.children[frame.name] = next
			}
			next.total += value
			cur = next
		}
		cur.flat += value
	}
	var build func(n *node, min float64) pprofFlameNode
	build = func(n *node, min float64) pprofFlameNode {
		out := pprofFlameNode{name: n.frame.name, loc: n.frame.loc, flat: n.flat, total: n.total}
		for _, child := range n.children {
			if child.total < min {
				continue
			}
			out.children = append(out.children, build(child, min))
		}
		sort.Slice(out.children, func(i, j int) bool { return out.children[i].total > out.children[j].total })
		return out
	}
	flame := build(root, total*minFlameTotalFraction)
	// Top rows: flat time per frame (leaf values), cum from the tree.
	flatByName := map[string]pprofFlameNode{}
	var walk func(n pprofFlameNode)
	walk = func(n pprofFlameNode) {
		existing, ok := flatByName[n.name]
		if !ok {
			existing = pprofFlameNode{name: n.name, loc: n.loc}
		}
		existing.flat += n.flat
		existing.total += n.total
		flatByName[n.name] = existing
		for _, child := range n.children {
			walk(child)
		}
	}
	walk(flame)
	rows := make([]pprofFlameNode, 0, len(flatByName))
	for _, n := range flatByName {
		rows = append(rows, n)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].flat > rows[j].flat })
	const topLimit = 25
	if len(rows) > topLimit {
		rows = rows[:topLimit]
	}
	top := jvArr()
	for _, row := range rows {
		top.arr = append(top.arr, jvObj(
			jvKey("name", jvStr(row.name)),
			jvKey("location", jvStr(row.loc)),
			jvKey("flat", jvFloat(row.flat)),
			jvKey("cum", jvFloat(row.total)),
			jvKey("flat_pct", jvFloat(percent(row.flat, total))),
			jvKey("cum_pct", jvFloat(percent(row.total, total))),
		))
	}
	durationMs := int64(0)
	if p.DurationNanos > 0 {
		durationMs = p.DurationNanos / 1_000_000
	}
	return jvObj(
		jvKey("kind", jvStr(kindName)),
		jvKey("unit_label", jvStr(label)),
		jvKey("duration_ms", jvInt(durationMs)),
		jvKey("sample_count", jvInt(int64(len(p.Sample)))),
		jvKey("total", jvFloat(total)),
		jvKey("top", top),
		jvKey("flame", flameNodeJVal(flame)),
	), nil
}

// percent is the share of part in total, or 0 for a zero total.
func percent(part, total float64) float64 {
	if total <= 0 {
		return 0
	}
	return part / total * 100
}

// flameNodeJVal serializes the flame tree in the order the frontend renders.
func flameNodeJVal(n pprofFlameNode) jVal {
	out := jvObj(
		jvKey("name", jvStr(n.name)),
		jvKey("self", jvFloat(n.flat)),
		jvKey("total", jvFloat(n.total)),
	)
	if n.loc != "" {
		out.set("location", jvStr(n.loc))
	}
	if len(n.children) > 0 {
		children := jvArr()
		for _, child := range n.children {
			children.arr = append(children.arr, flameNodeJVal(child))
		}
		out.set("children", children)
	}
	return out
}

// opGetPprofSummary serves the browser view model for a captured profile.
func opGetPprofSummary(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	name := payload.get("args").get("name").asString()
	if !pprofNameValid(name) {
		return jvNull(), fmt.Errorf("invalid pprof file name")
	}
	dir := pprofProfilesDir(pluginDir, payload, settings)
	data, err := readFileLimit(filepath.Join(dir, name), maxPprofDownloadBytes)
	if err != nil {
		return jvNull(), err
	}
	summary, err := pprofSummary(data)
	if err != nil {
		return jvNull(), fmt.Errorf("parse %s: %v", name, err)
	}
	summary.set("name", jvStr(name))
	return summary, nil
}

// readFileLimit reads a file up to max bytes (the pprof JSON view model and
// raw download share the same bound).
func readFileLimit(path string, max int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() > max {
		return nil, fmt.Errorf("file exceeds the %d MiB limit", max>>20)
	}
	data := make([]byte, info.Size())
	_, err = file.Read(data)
	return data, err
}
