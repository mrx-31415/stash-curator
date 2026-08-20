package main

import (
	"math"
	"testing"
)

// parityCorpus builds the identical sample set tests/model/test_watchfit.py
// generates, using integer arithmetic so neither side needs a shared fixture
// file or a random seed.
func parityCorpus(count int) []struct {
	Seconds  float64
	Returned bool
} {
	trueCurve := [3]float64{-4.0, 1.6, -0.2}
	out := make([]struct {
		Seconds  float64
		Returned bool
	}, 0, count)
	state := int64(12345)
	for index := 0; index < count; index++ {
		seconds := math.Exp(1.5 + 6.5*(float64(index%64)/64.0))
		logT := math.Log(seconds)
		z := trueCurve[0] + trueCurve[1]*logT + trueCurve[2]*logT*logT
		probability := 1.0 / (1.0 + math.Exp(-z))
		state = (state*1103515245 + 12345) % 2147483648
		out = append(out, struct {
			Seconds  float64
			Returned bool
		}{seconds, (float64(state) / 2147483648.0) < probability})
	}
	return out
}

// closeEnough is the project's tolerance convention for mirrored float
// outputs. Go's math.Exp/math.Log and CPython's libm differ in the last bit or
// two, so the two implementations agree to well within any consequence rather
// than bit-for-bit -- see the note at the top of plainmath.go, which records
// that the bit-exact CPython ports were deliberately dropped.
func closeEnough(got, want float64) bool {
	scale := math.Max(1.0, math.Abs(want))
	return math.Abs(got-want) <= 1e-12*scale
}

// TestFitViewCurveMatchesPython pins the Go fit to the values
// curator/model/watchfit.py produces on the same corpus. The two run the same
// IRLS with the same fixed iteration count and the same fold assignment, so
// only libm's last bit should separate them.
func TestFitViewCurveMatchesPython(t *testing.T) {
	fit := fitViewCurve(parityCorpus(600))

	if !fit.adopted || fit.reason != "adopted" {
		t.Fatalf("expected the fit to be adopted, got %q", fit.reason)
	}
	if fit.sampleSize != 600 || fit.positives != 116 {
		t.Fatalf("corpus differs from Python: n=%d positives=%d", fit.sampleSize, fit.positives)
	}
	for index, want := range [3]float64{
		-3.8799890217749162,
		1.315676077240522,
		-0.1630173563979539,
	} {
		if !closeEnough(fit.coefficients[index], want) {
			t.Errorf("coefficient %d = %v, Python produces %v", index, fit.coefficients[index], want)
		}
	}
	if !closeEnough(fit.heldoutQuadratic, 280.55439609565457) {
		t.Errorf("held-out quadratic = %v", fit.heldoutQuadratic)
	}
	if !closeEnough(fit.heldoutMonotone, 293.4078526608149) {
		t.Errorf("held-out monotone = %v", fit.heldoutMonotone)
	}
	if !closeEnough(fit.heldoutConstant, 297.29725581442415) {
		t.Errorf("held-out constant = %v", fit.heldoutConstant)
	}
}

// TestViewRiseMatchesPython pins the curve itself, not only the fit.
func TestViewRiseMatchesPython(t *testing.T) {
	curve := fitViewCurve(parityCorpus(600)).coefficients

	if got := viewRise(45.0, &curve); !closeEnough(got, 0.34769805377892304) {
		t.Errorf("viewRise(45) = %v", got)
	}
	if got := viewRise(300.0, &curve); !closeEnough(got, 0.24240197521844445) {
		t.Errorf("viewRise(300) = %v", got)
	}
}

// TestViewCurvePayloadRounds guards the artifact field: the coefficients are
// rounded before they reach config_json precisely so a last-bit difference
// between the two implementations cannot make the stored JSON differ.
func TestViewCurvePayloadRounds(t *testing.T) {
	payload := fitViewCurve(parityCorpus(600)).payload()
	coefficients := payload.get("coefficients")
	if coefficients.kind != jArr || len(coefficients.arr) != 3 {
		t.Fatalf("coefficients are not a 3-element array")
	}
	for index, want := range []string{"-3.879989", "1.315676", "-0.163017"} {
		if coefficients.arr[index].num != want {
			t.Errorf("coefficient %d serialized as %q, want %q",
				index, coefficients.arr[index].num, want)
		}
	}
}

// TestViewRiseFallsBackToShipped covers the guards: without a fitted curve, or
// with one that is not an inverted U, the shipped exponential rise stands.
func TestViewRiseFallsBackToShipped(t *testing.T) {
	shipped := viewPositiveMax * (1 - math.Exp(-(300.0-shortExitSeconds)/viewRiseSeconds))
	if got := viewRise(300.0, nil); got != shipped {
		t.Errorf("unfitted viewRise(300) = %v, want %v", got, shipped)
	}
	positiveCurvature := [3]float64{-4.0, 1.6, 0.2}
	if got := viewRise(300.0, &positiveCurvature); got != shipped {
		t.Errorf("positive-curvature viewRise(300) = %v, want %v", got, shipped)
	}
}

// TestFitViewCurveGuards mirrors the Python guard tests.
func TestFitViewCurveGuards(t *testing.T) {
	small := fitViewCurve(parityCorpus(minFirstPlays - 1))
	if small.adopted || small.reason != "insufficient_sample" {
		t.Errorf("small sample: adopted=%v reason=%q", small.adopted, small.reason)
	}
	if small.coefficients != defaultViewCurve {
		t.Errorf("small sample did not fall back to the shipped curve")
	}

	negative := parityCorpus(600)
	for index := range negative {
		negative[index].Returned = false
	}
	none := fitViewCurve(negative)
	if none.adopted || none.reason != "insufficient_positives" {
		t.Errorf("no positives: adopted=%v reason=%q", none.adopted, none.reason)
	}
}
