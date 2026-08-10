// glibc-compatible cube for the ported ops.
//
// CPython's `x ** 3` calls glibc pow(x, 3.0), which is NOT the naive
// x*x*x (they disagree in ~26% of inputs) and not always the correctly
// rounded cube (5/5000 sampled inputs deviate). The read paths cube
// similarity values that flow into byte-critical outputs (the multi-hop
// pagerank edges, the explanation match ordering), so the cube is computed
// exactly (mantissa^3 is a big.Int) and rounded once to the nearest double.
package main

import (
	"math"
	"math/big"
)

// pyCube mirrors CPython's `x ** 3` on this platform: the correctly rounded
// cube, matching glibc pow(x, 3.0) everywhere glibc itself is correct.
func pyCube(x float64) float64 {
	return pyPowInt(x, 3)
}

// pySquare mirrors CPython's `x ** 2` on this platform: the correctly
// rounded square. Used for the performer-profile norm (profiles.py computes
// sum(value**2 ...)); categorical profile values are 1.0 so this is exact
// there, but the exact power keeps the arithmetic identical by construction.
func pySquare(x float64) float64 {
	return pyPowInt(x, 2)
}

// pyPowInt computes the correctly rounded x^n for n in {2, 3} (n is a small
// integer, matching CPython's float_pow calling glibc pow(x, float(n))).
func pyPowInt(x float64, n int) float64 {
	if math.IsNaN(x) {
		return math.NaN()
	}
	if math.IsInf(x, 0) {
		if n%2 == 0 {
			return math.Inf(1) // (-Inf)^2 = +Inf
		}
		return x
	}
	if x == 0 {
		if math.Signbit(x) && n%2 == 1 {
			return -0.0
		}
		return 0.0
	}
	bits := math.Float64bits(x)
	exp := int((bits>>52)&0x7ff) - 1023
	mant := bits & 0xfffffffffffff
	p := exp - 52
	if exp == -1023 {
		// subnormal: value = mant * 2^-1074
		mant = bits & 0xfffffffffffff
		p = -1074
	} else {
		mant |= 1 << 52
	}
	// x = mant * 2^p; x^n = mant^n * 2^(n*p); mant^n fits in 159 bits.
	power := new(big.Int).SetUint64(mant)
	power.Mul(power, new(big.Int).SetUint64(mant))
	if n == 3 {
		power.Mul(power, new(big.Int).SetUint64(mant))
	}
	value := new(big.Float).SetPrec(200).SetInt(power)
	value.SetMantExp(value, n*p)
	result, _ := value.Float64()
	if math.Signbit(x) && n%2 == 1 {
		return -result
	}
	return result
}
