package main

// Self-verification for the shared fixed-chunking helper: the aggregate
// output must be item-ordered and identical across goroutine counts (the
// property the kernels and the parallelized build stages rely on).

import (
	"fmt"
	"reflect"
	"testing"
)

func TestParallelChunksOrderAndDeterminism(t *testing.T) {
	n := 1000
	// fn returns one output per item so the concatenation must be exactly
	// the serial sequence.
	serial := make([]string, 0, n)
	for i := 0; i < n; i++ {
		serial = append(serial, fmt.Sprintf("item-%04d", i))
	}
	for _, threads := range []int{1, 2, 3, 7, 8, 64, 1000, 2000} {
		got := parallelChunks(n, threads, func(start, end int) []string {
			out := make([]string, 0, end-start)
			for i := start; i < end; i++ {
				out = append(out, fmt.Sprintf("item-%04d", i))
			}
			return out
		})
		if !reflect.DeepEqual(got, serial) {
			t.Fatalf("threads=%d: output differs from serial order", threads)
		}
	}
}

func TestParallelChunksEdgeCases(t *testing.T) {
	if got := parallelChunks(0, 4, func(start, end int) []int { return []int{1} }); got != nil {
		t.Fatalf("n=0 must return nil, got %v", got)
	}
	got := parallelChunks(5, 1, func(start, end int) []int {
		out := make([]int, 0, end-start)
		for i := start; i < end; i++ {
			out = append(out, i)
		}
		return out
	})
	if !reflect.DeepEqual(got, []int{0, 1, 2, 3, 4}) {
		t.Fatalf("single thread must reproduce the serial sequence, got %v", got)
	}
	// chunks must partition the range without overlap or gaps
	covered := 0
	for _, threads := range []int{2, 3, 5} {
		out := parallelChunks(7, threads, func(start, end int) []int {
			return []int{end - start}
		})
		for _, size := range out {
			covered += size
		}
	}
	if covered != 21 {
		t.Fatalf("chunks covered %d items, want 21", covered)
	}
}

func TestOrderedProgressEmitsPointsInOrder(t *testing.T) {
	progress := newOrderedProgress()
	emitted := []int{}
	done := make(chan struct{})
	go func() {
		defer close(done)
		progress.wait([]int{250, 500, 750}, func(completed int) {
			emitted = append(emitted, completed)
		})
	}()
	// Complete out of order: 300 items finish before 250's reporter window
	// is observable, but the emitted sequence must stay strictly increasing.
	for i := 0; i < 300; i++ {
		progress.done()
	}
	for i := 0; i < 200; i++ {
		progress.done()
	}
	progress.done() // 501
	for i := 0; i < 249; i++ {
		progress.done()
	}
	<-done
	if !reflect.DeepEqual(emitted, []int{250, 500, 750}) {
		t.Fatalf("emitted points %v, want [250 500 750]", emitted)
	}
}
