package main

import "math"

// pyTanh mirrors glibc's dbl-64 __tanh (sysdeps/ieee754/dbl-64/s_tanh.c):
// the fdlibm expm1-based algorithm with the same constants and arithmetic
// order. Go's math.Tanh is a different algorithm that disagrees with glibc
// by 1 ulp on ~16% of inputs, so the port must reproduce glibc exactly.

const (
	tanhOne         = 1.0
	tanhTwo         = 2.0
	tanhTiny        = 1.0e-300
	expm1Huge       = 1.0e+300
	expm1Tiny       = 1.0e-300
	expm1OThreshold = 7.09782712893383973096e+02
	expm1Ln2Hi      = 6.93147180369123816490e-01
	expm1Ln2Lo      = 1.90821492927058770002e-10
	expm1InvLn2     = 1.44269504088896338700e+00
	expm1Ln2HiHalf  = 0x3fd62e42 // |x| > 0.5 ln2
	expm1Ln2Hi15    = 0x3FF0A2B2 // |x| < 1.5 ln2
	expm1Small      = 0x3c900000 // |x| < 2^-54
	expm1Big        = 0x4043687A // |x| >= 56*ln2
	expm1Overflow   = 0x40862E42 // |x| >= 709.78...
)

// expm1Q mirrors the scaled coefficients of fdlibm expm1.
var expm1Q = [...]float64{
	1.0,
	-3.33333333333331316428e-02, /* BFA11111 111110F4 */
	1.58730158725481460165e-03,  /* 3F5A01A0 19FE5585 */
	-7.93650757867487942473e-05, /* BF14CE19 9EAADBB7 */
	4.00821782732936239552e-06,  /* 3ED0CFCA 86E65239 */
	-2.01099218183624371326e-07, /* BE8AFDB7 6E09C32D */
}

func highWord32(bits uint64) int32 { return int32(bits >> 32) }
func lowWord32(bits uint64) int32  { return int32(bits & 0xffffffff) }
func setHighWord(bits uint64, high int32) uint64 {
	return (uint64(uint32(high)) << 32) | (bits & 0xffffffff)
}

// addKToExponent adds k*2^52 to the double, matching C's
// GET_HIGH_WORD(high, y); SET_HIGH_WORD(y, high + (k << 20)).
func addKToExponent(y float64, k int) float64 {
	bits := math.Float64bits(y)
	return math.Float64frombits(bits + (uint64(int64(k)) << 52))
}

// pyExpm1 mirrors glibc's __expm1 (s_expm1.c), the fdlibm implementation.
func pyExpm1(x float64) float64 {
	var y, hi, lo, c, t, e, hxs, hfx, r1, h2, h4, R1, R2, R3 float64
	bits := math.Float64bits(x)
	hx := highWord32(bits)
	xsb := hx & -0x80000000
	if xsb == 0 {
		y = x
	} else {
		y = -x
	}
	hx &= 0x7fffffff

	// filter out huge and non-finite argument
	if hx >= expm1Big { // |x| >= 56*ln2
		if hx >= expm1Overflow { // |x| >= 709.78...
			if hx >= 0x7ff00000 {
				low := lowWord32(bits)
				if (hx&0xfffff)|low != 0 {
					return x + x // NaN
				}
				if xsb == 0 {
					return x // exp(+inf) = inf
				}
				return -1.0 // exp(-inf) = -1
			}
			if x > expm1OThreshold {
				return math.Inf(1) // overflow (huge*huge)
			}
		}
		if xsb != 0 { // x < -56*ln2, return -1.0
			return expm1Tiny - expm1Q[0]
		}
	}

	// argument reduction
	var k int32
	if hx > expm1Ln2HiHalf { // |x| > 0.5 ln2
		if hx < expm1Ln2Hi15 { // |x| < 1.5 ln2
			if xsb == 0 {
				hi = x - expm1Ln2Hi
				lo = expm1Ln2Lo
				k = 1
			} else {
				hi = x + expm1Ln2Hi
				lo = -expm1Ln2Lo
				k = -1
			}
		} else {
			var kd float64
			if xsb == 0 {
				kd = expm1InvLn2*x + 0.5
			} else {
				kd = expm1InvLn2*x - 0.5
			}
			k = int32(kd) // C: double -> int truncation toward zero
			t = float64(k)
			hi = x - t*expm1Ln2Hi // t*ln2_hi is exact here
			lo = t * expm1Ln2Lo
		}
		x = hi - lo
		c = (hi - x) - lo
	} else if hx < expm1Small { // |x| < 2^-54, return x
		t = expm1Huge + x // return x with inexact flags when x != 0
		return x - (t - (expm1Huge + x))
	}

	// x is now in primary range
	hfx = 0.5 * x
	hxs = x * hfx
	R1 = expm1Q[0] + hxs*expm1Q[1]
	h2 = hxs * hxs
	R2 = expm1Q[2] + hxs*expm1Q[3]
	h4 = h2 * h2
	R3 = expm1Q[4] + hxs*expm1Q[5]
	r1 = R1 + h2*R2 + h4*R3
	t = 3.0 - r1*hfx
	e = hxs * ((r1 - t) / (6.0 - x*t))
	if k == 0 {
		return x - (x*e - hxs) // c is 0
	}
	e = (x*(e-c) - c)
	e -= hxs
	if k == -1 {
		return 0.5*(x-e) - 0.5
	}
	if k == 1 {
		if x < -0.25 {
			return -2.0 * (e - (x + 0.5))
		}
		return expm1Q[0] + 2.0*(x-e)
	}
	if k <= -2 || k > 56 { // suffice to return exp(x)-1
		y = expm1Q[0] - (e - x)
		return addKToExponent(y, int(k)) - expm1Q[0]
	}
	tt := 1.0
	if k < 20 {
		bits = math.Float64bits(tt)
		bits = setHighWord(bits, 0x3ff00000-(0x200000>>uint(k))) // t = 1 - 2^-k
		tt = math.Float64frombits(bits)
		y = tt - (e - x)
		return addKToExponent(y, int(k))
	}
	bits = math.Float64bits(tt)
	bits = setHighWord(bits, (0x3ff-k)<<20) // 2^-k
	tt = math.Float64frombits(bits)
	y = x - (e + tt)
	y += expm1Q[0]
	return addKToExponent(y, int(k))
}

// pyTanh mirrors glibc's __tanh (s_tanh.c): expm1-based, exact sign handling.
func pyTanh(x float64) float64 {
	var t, z float64
	bits := math.Float64bits(x)
	jx := highWord32(bits)
	lx := lowWord32(bits)
	ix := jx & 0x7fffffff

	// x is INF or NaN
	if ix >= 0x7ff00000 {
		if jx >= 0 {
			return tanhOne/x + tanhOne // tanh(+-inf) = +-1
		}
		return tanhOne/x - tanhOne // tanh(NaN) = NaN
	}
	// |x| < 22
	if ix < 0x40360000 {
		if (ix | lx) == 0 {
			return x // x == +-0
		}
		if ix < 0x3c800000 { // |x| < 2^-55
			return x * (tanhOne + x)
		}
		if ix >= 0x3ff00000 { // |x| >= 1
			t = pyExpm1(tanhTwo * math.Abs(x))
			z = tanhOne - tanhTwo/(t+tanhTwo)
		} else {
			t = pyExpm1(-tanhTwo * math.Abs(x))
			z = -t / (t + tanhTwo)
		}
	} else {
		z = tanhOne - tanhTiny // raised inexact flag
	}
	if jx >= 0 {
		return z
	}
	return -z
}
