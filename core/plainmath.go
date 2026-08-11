package main

// Plain float helpers replacing the bit-exact CPython ports: stored outputs
// are compared with tolerance now, so stdlib math suffices.

// sumFloats is a plain left-to-right accumulation.
func sumFloats(values []float64) float64 {
	total := 0.0
	for _, value := range values {
		total += value
	}
	return total
}
