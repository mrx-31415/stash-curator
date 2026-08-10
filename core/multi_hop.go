package main

// Multi-hop stage: personalized PageRank over the walkable performer graph.
//
// Mirrors MultiHopAffinity._pagerank_python / _pagerank_networkx
// (curator/model/multi_hop.py) exactly: the adjacency is already row-stochastic,
// damping alpha, personalization concentrated on the seed, dangling mass
// returned to the seed, converging when sum(|x - xlast|) < N * tolerance.
// Nodes and per-node targets iterate in sorted order, matching the pure-Python
// recurrence bit-for-bit; the result is deterministic regardless of input map
// ordering (keys are sorted before use).

import (
	"encoding/json"
	"os"
	"sort"
)

const (
	defaultDamping       = 0.85
	defaultMaxIterations = 100
	defaultTolerance     = 1e-6
)

type multiHopPayload struct {
	Adjacency     map[string]map[string]float64 `json:"adjacency"`
	Seed          string                        `json:"seed"`
	Damping       float64                       `json:"damping"`
	MaxIterations int                           `json:"max_iterations"`
	Tolerance     float64                       `json:"tolerance"`
	Profile       bool                          `json:"profile,omitempty"`
}

func runMultiHop() {
	var payload multiHopPayload
	if err := json.NewDecoder(os.Stdin).Decode(&payload); err != nil {
		fail("multi-hop: invalid payload: %v", err)
	}
	damping := payload.Damping
	if damping <= 0 {
		damping = defaultDamping
	}
	maxIterations := payload.MaxIterations
	if maxIterations <= 0 {
		maxIterations = defaultMaxIterations
	}
	tolerance := payload.Tolerance
	if tolerance <= 0 {
		tolerance = defaultTolerance
	}
	profile := newProfileRecorder(payload.Profile)
	end := profile.begin("core.pagerank")
	scores := pagerank(payload.Adjacency, payload.Seed, damping, maxIterations, tolerance)
	end()
	profile.emit()
	if err := writeJSONLine(map[string]any{"result": scores}); err != nil {
		fail("multi-hop: write result: %v", err)
	}
}

// pagerank runs the power iteration with networkx/pure-Python semantics.
func pagerank(
	adjacency map[string]map[string]float64,
	seed string,
	damping float64,
	maxIterations int,
	tolerance float64,
) map[string]float64 {
	nodes := make([]string, 0, len(adjacency))
	for node := range adjacency {
		nodes = append(nodes, node)
	}
	sort.Strings(nodes)
	n := len(nodes)
	if n == 0 {
		return map[string]float64{}
	}
	dangling := make([]string, 0)
	for _, node := range nodes {
		if len(adjacency[node]) == 0 {
			dangling = append(dangling, node)
		}
	}
	// Sorted per-node targets for deterministic accumulation order.
	targets := make([][]string, n)
	weights := make([][]float64, n)
	for i, node := range nodes {
		edges := adjacency[node]
		keys := make([]string, 0, len(edges))
		for target := range edges {
			keys = append(keys, target)
		}
		sort.Strings(keys)
		targets[i] = keys
		weights[i] = make([]float64, len(keys))
		for k, target := range keys {
			weights[i][k] = edges[target]
		}
	}
	x := make([]float64, n)
	for i := range x {
		x[i] = 1.0 / float64(n)
	}
	position := make(map[string]int, n)
	for i, node := range nodes {
		position[node] = i
	}
	for iteration := 0; iteration < maxIterations; iteration++ {
		xlast := x
		x = make([]float64, n)
		dangleSum := 0.0
		for _, d := range dangling {
			dangleSum += xlast[position[d]]
		}
		dangleSum *= damping
		for i, node := range nodes {
			value := xlast[i]
			for k, target := range targets[i] {
				x[position[target]] += damping * value * weights[i][k]
			}
			if node == seed {
				// Two separate additions match the pure-Python recurrence
				// bit-for-bit (dangling redistribution, then teleport).
				x[i] += dangleSum
				x[i] += 1 - damping
			}
		}
		error := 0.0
		for i := range nodes {
			error += absFloat(x[i] - xlast[i])
		}
		if error < float64(n)*tolerance {
			break
		}
	}
	result := make(map[string]float64, n)
	for i, node := range nodes {
		result[node] = x[i]
	}
	return result
}

func absFloat(value float64) float64 {
	if value < 0 {
		return -value
	}
	return value
}
