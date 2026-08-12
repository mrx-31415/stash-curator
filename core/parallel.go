package main

// Deterministic fixed-chunking helpers shared by the parallelized build
// stages. The content and performer kernels process rows in fixed chunks
// with one goroutine per chunk and assemble results in chunk order, making
// the output identical across goroutine counts (verified by the differential
// gates); these helpers extend the same pattern to the serial per-scene
// loops (lane classification, model scoring, feature construction).

import "sync"

// parallelChunks runs fn over fixed chunks of [0, n) with one goroutine per
// chunk and returns the outputs concatenated in chunk order. fn returns the
// outputs for its [start, end) items in order; chunks partition the item
// sequence without overlap, so the aggregate is identical across goroutine
// counts. n <= 0 returns nil.
func parallelChunks[T any](n, threads int, fn func(start, end int) []T) []T {
	if n <= 0 {
		return nil
	}
	if threads > n {
		threads = n
	}
	chunk := (n + threads - 1) / threads
	nchunks := (n + chunk - 1) / chunk
	results := make([][]T, nchunks)
	var wg sync.WaitGroup
	for w := 0; w < nchunks; w++ {
		start := w * chunk
		end := min(start+chunk, n)
		wg.Add(1)
		go func(w, start, end int) {
			defer wg.Done()
			results[w] = fn(start, end)
		}(w, start, end)
	}
	wg.Wait()
	var out []T
	for _, part := range results {
		out = append(out, part...)
	}
	return out
}

// orderedProgress emits progress ticks at the given points in point order
// regardless of worker interleaving, mirroring the contentKernel reporter
// (progress lines stay in strict item order). done must be called once per
// completed item; wait reports each point once completed reaches it and
// returns after the last point.
type orderedProgress struct {
	mu        sync.Mutex
	completed int
	cond      *sync.Cond
}

func newOrderedProgress() *orderedProgress {
	p := &orderedProgress{}
	p.cond = sync.NewCond(&p.mu)
	return p
}

func (p *orderedProgress) done() {
	p.mu.Lock()
	p.completed++
	p.cond.Signal()
	p.mu.Unlock()
}

func (p *orderedProgress) wait(points []int, emit func(completed int)) {
	for _, point := range points {
		p.mu.Lock()
		for p.completed < point {
			p.cond.Wait()
		}
		p.mu.Unlock()
		emit(point)
	}
}
