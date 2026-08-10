// Python round() semantics for the ported backend ops.
//
// round(x, ndigits) with ndigits >= 0 in CPython rounds the exact binary
// value to ndigits decimal places, ties to even, via the correctly-rounded
// decimal conversion in PyOS_double_to_string('f', ndigits), then converts
// the rounded decimal back to the nearest double. That is not the same as
// rounding the shortest representation or a naive scale-multiply: the exact
// decimal expansion must be rounded, and ties round to even. This file
// implements that exactly: the double is decomposed into integer digits
// times a power of ten, the digits are rounded half-even at the target
// decimal position, and the resulting decimal is converted back to float64
// with correct rounding (round-half-even on the binary tie), matching
// CPython's parse-back.
package main

import (
	"math"
	"math/big"
	"strconv"
	"strings"
)

// pyRoundTo mirrors Python's round(x, ndigits) for ndigits >= 0.
func pyRoundTo(x float64, ndigits int) float64 {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return x
	}
	if ndigits < 0 {
		// Not used by the ported ops; Python's negative-ndigits path uses
		// the same decimal machinery, but callers here never reach it.
		ndigits = 0
	}
	neg := x < 0 || (x == 0 && math.Signbit(x))
	abs := math.Abs(x)
	if abs == 0 {
		if neg {
			return -0.0
		}
		return 0.0
	}
	digits, exp := exactDecimal(abs)
	// Round `digits` to the nearest multiple of 10^shift where the result
	// has ndigits digits after the decimal point: digits*10^exp -> q*10^-ndigits.
	if exp >= -ndigits {
		// Already at or finer than the target granularity: the value is
		// exactly representable as q*10^-ndigits, so it rounds to itself.
		result := abs
		if neg {
			return -result
		}
		return result
	}
	shift := -exp - ndigits // > 0
	q, rem := quotientRemainder(digits, pow10Big(shift))
	half := new(big.Int).Mul(pow10Big(shift-1), big.NewInt(5)) // 10^shift / 2
	// Compare rem to half: ties round to even q.
	cmp := rem.Cmp(half)
	if cmp > 0 {
		q.Add(q, big.NewInt(1))
	} else if cmp == 0 {
		if q.Bit(0) == 1 {
			q.Add(q, big.NewInt(1))
		}
	}
	// Result is q * 10^-ndigits, converted back to the nearest double.
	rounded := bigDecimalToFloat(q, -ndigits)
	if neg {
		return -rounded
	}
	return rounded
}

// exactDecimal returns the exact decimal representation of a finite positive
// double: value = digits * 10^exp with digits an integer.
func exactDecimal(x float64) (*big.Int, int) {
	bits := math.Float64bits(x)
	exp := int((bits>>52)&0x7ff) - 1023 // unbiased
	mant := bits & 0xfffffffffffff
	if exp == -1023 { // subnormal; mantissa has no implicit bit
		return new(big.Int).SetUint64(mant), -1074
	}
	mant |= 1 << 52
	p := exp - 52
	if p >= 0 {
		digits := new(big.Int).Lsh(new(big.Int).SetUint64(mant), uint(p))
		return digits, 0
	}
	// digits = mant * 5^(-p); decimal exponent = p.
	five := big.NewInt(5)
	digits := new(big.Int).Exp(five, big.NewInt(int64(-p)), nil)
	digits.Mul(digits, new(big.Int).SetUint64(mant))
	return digits, p
}

var pow10Cache = map[int]*big.Int{0: big.NewInt(1)}

func pow10Big(n int) *big.Int {
	if n < 0 {
		return big.NewInt(0)
	}
	if cached, ok := pow10Cache[n]; ok {
		return new(big.Int).Set(cached)
	}
	value := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n)), nil)
	pow10Cache[n] = new(big.Int).Set(value)
	return value
}

func quotientRemainder(digits, divisor *big.Int) (*big.Int, *big.Int) {
	q := new(big.Int)
	r := new(big.Int)
	q.QuoRem(digits, divisor, r)
	return q, r
}

// bigDecimalToFloat converts digits*10^exp (digits >= 0) to the nearest
// float64, matching strtod's correctly-rounded conversion (ties to even on
// the binary result).
func bigDecimalToFloat(digits *big.Int, exp int) float64 {
	if digits.Sign() == 0 {
		return 0.0
	}
	s := digits.String()
	if exp > 0 {
		s += strings.Repeat("0", exp)
		exp = 0
	}
	if exp < 0 {
		cut := len(s) + exp
		if cut <= 0 {
			s = "0." + strings.Repeat("0", -cut) + s
		} else {
			s = s[:cut] + "." + s[cut:]
		}
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		// Overflow to infinity (cannot happen for the inputs round() sees);
		// fall back to big.Float conversion for correctness.
		bf := new(big.Float).SetPrec(53).SetInt(digits)
		if exp > 0 {
			bf.Mul(bf, new(big.Float).SetPrec(64).SetInt(pow10Big(exp)))
		} else if exp < 0 {
			bf.Quo(bf, new(big.Float).SetPrec(64).SetInt(pow10Big(-exp)))
		}
		value, _ := bf.Float64()
		return value
	}
	return f
}
