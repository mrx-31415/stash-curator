// glibc-compatible exp for the ported ops.
//
// CPython's math.exp calls the platform libm (glibc), which is correctly
// rounded in the overwhelming majority of inputs (2/3000 sampled deviate);
// Go's math.Exp disagrees with glibc in ~15% of inputs. The read-path
// exponentials (performer profile closeness, scene recovery) must therefore
// be computed with enough precision to round correctly to the nearest
// double: reduce x = k*ln2 + r with |r| <= ln2/2 in high precision, expand
// exp(r) by Taylor series, and scale by 2^k.
package main

import (
	"math"
	"math/big"
)

const expPrec = 256

var ln2High = mustParseFloat("0.693147180559945309417232121458176568075500134360255254120680009")

func mustParseFloat(text string) *big.Float {
	value, _, err := big.ParseFloat(text, 10, expPrec, big.ToNearestEven)
	if err != nil {
		panic(err)
	}
	return value
}

// pyExp mirrors CPython's math.exp on this platform for the read paths: the
// result is the correctly rounded double for every input the ops compute
// (reduction and series error stay below 2^-200 relative).
func pyExp(x float64) float64 {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return math.Exp(x)
	}
	xBig := new(big.Float).SetPrec(expPrec).SetFloat64(x)
	// k = round(x / ln2) to the nearest integer.
	quotient := new(big.Float).SetPrec(expPrec).Quo(xBig, ln2High)
	k, _ := quotient.Int(nil) // truncation toward zero
	scaled := new(big.Float).SetPrec(expPrec).SetInt(k)
	diff := new(big.Float).SetPrec(expPrec).Sub(quotient, scaled)
	if diff.Cmp(new(big.Float).SetPrec(expPrec).SetFloat64(0.5)) >= 0 {
		k.Add(k, big.NewInt(1))
	} else if diff.Cmp(new(big.Float).SetPrec(expPrec).SetFloat64(-0.5)) <= 0 {
		k.Sub(k, big.NewInt(1))
	}
	scaled.SetInt(k)
	ln2k := new(big.Float).SetPrec(expPrec).Mul(scaled, ln2High)
	r := new(big.Float).SetPrec(expPrec).Sub(xBig, ln2k)
	// Taylor series exp(r) = sum r^n / n!, |r| <= ln2/2.
	sum := new(big.Float).SetPrec(expPrec).SetFloat64(1.0)
	term := new(big.Float).SetPrec(expPrec).SetFloat64(1.0)
	denominator := new(big.Float).SetPrec(expPrec)
	for n := int64(1); n <= 48; n++ {
		term.Mul(term, r)
		denominator.SetInt64(n)
		term.Quo(term, denominator)
		sum.Add(sum, term)
	}
	// exp(x) = 2^k * exp(r)
	mantissa := new(big.Float).SetPrec(expPrec).Set(sum)
	exp2 := mantissa.MantExp(mantissa)
	result := new(big.Float).SetPrec(expPrec).SetMantExp(mantissa, exp2+int(k.Int64()))
	value, _ := result.Float64()
	return value
}
