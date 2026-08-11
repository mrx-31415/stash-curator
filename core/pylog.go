package main

import "math"

// pyLog mirrors glibc's dbl-64 __log (sysdeps/ieee754/dbl-64/e_log.c): the
// table-driven algorithm with the same constants and arithmetic order. The
// FMA path (__FP_FAST_FMA) is selected when the build target has FMA; glibc
// builds without it use the tab2 (chi/clo) path.
func pyLog(x float64) float64 {
	ix := math.Float64bits(x)
	top := uint32(ix >> 48)
	loBound := math.Float64bits(1.0 - 0x1p-4)
	hiBound := math.Float64bits(1.0 + 0x1.09p-4)
	if ix-loBound < hiBound-loBound {
		if ix == math.Float64bits(1.0) {
			return 0
		}
		r := x - 1.0
		r2 := r * r
		r3 := r * r2
		y := r3 * (logPoly1[1] + r*logPoly1[2] + r2*logPoly1[3] +
			r3*(logPoly1[4]+r*logPoly1[5]+r2*logPoly1[6]+
				r3*(logPoly1[7]+r*logPoly1[8]+r2*logPoly1[9]+r3*logPoly1[10])))
		w := r * 0x1p27
		rhi := r + w - w
		rlo := r - rhi
		w = rhi * rhi * logPoly1[0]
		hi := r + w
		lo := r - hi + w
		lo += logPoly1[0] * rlo * (rhi + r)
		y += lo
		y += hi
		return y
	}
	if top-0x0010 >= 0x7ff0-0x0010 {
		// x < 0x1p-1022 or inf or nan
		if ix*2 == 0 {
			return math.Inf(-1) // __math_divzero(1)
		}
		if ix == math.Float64bits(math.Inf(1)) {
			return x
		}
		if top&0x8000 != 0 || top&0x7ff0 == 0x7ff0 {
			return math.NaN()
		}
		ix = math.Float64bits(x * 0x1p52)
		ix -= 52 << 52
	}
	tmp := ix - 0x3fe6000000000000
	i := int((tmp >> 45) % 128)
	k := int(int64(tmp) >> 52)
	iz := ix - (tmp & (0xfff << 52))
	invc := logTab[i].invc
	logc := logTab[i].logc
	z := math.Float64frombits(iz)
	// non-FMA path (glibc without __FP_FAST_FMA)
	r := (z - logTab2[i].chi - logTab2[i].clo) * invc
	kd := float64(k)
	w := kd*logLn2hi + logc
	hi := w + r
	lo := w - hi + r + kd*logLn2lo
	r2 := r * r
	return lo + r2*logPoly[0] + r*r2*(logPoly[1]+r*logPoly[2]+r2*(logPoly[3]+r*logPoly[4])) + hi
}
