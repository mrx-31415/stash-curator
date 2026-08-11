// Python 3.12+ sum() semantics for the ported ops.
//
// CPython 3.12 changed builtins.sum() to use Neumaier compensated summation
// for floats (bpo-100425): the first float initializes the accumulator, each
// following value applies the Neumaier correction, and the result is
// s + c. Naive accumulation differs in the last ulp, so every Python
// `sum(...)` in the ported paths must be mirrored with neumaierSum.
package main

// neumaierSum mirrors CPython 3.12+ sum() over float values in the given
// order: the first value seeds the accumulator directly, then each value
// applies the Neumaier step, and the final result is s + c.
//go:noinline
func neumaierSum(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	s := values[0]
	c := 0.0
	for _, v := range values[1:] {
		t := s + v
		if absFloat(s) >= absFloat(v) {
			c += (s - t) + v
		} else {
			c += (v - t) + s
		}
		s = t
	}
	return s + c
}
