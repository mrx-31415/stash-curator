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

// TestViewValueMatchesPython pins the curve itself, not only the fit.
func TestViewValueMatchesPython(t *testing.T) {
	curve := fitViewCurve(parityCorpus(600)).curve()

	if got, ok := viewValue(45.0, &curve); !ok || !closeEnough(got, 0.3353060834105465) {
		t.Errorf("viewValue(45) = %v ok=%v", got, ok)
	}
	// A brief play is negative evidence, floored at direct_short_exit_min.
	if got, ok := viewValue(2.0, &curve); !ok || !closeEnough(got, -0.1) {
		t.Errorf("viewValue(2) = %v ok=%v", got, ok)
	}
	// Past the peak the curve abstains rather than voting against.
	if _, ok := viewValue(36000.0, &curve); ok {
		t.Errorf("viewValue(36000) reported evidence, want abstain")
	}
}

// TestViewValueHasNoStepAtTheThreshold is the property the base-rate centring
// exists for: refitting only the rise made 29.9s and 30.1s differ by most of
// the signal's range.
func TestViewValueHasNoStepAtTheThreshold(t *testing.T) {
	curve := fitViewCurve(parityCorpus(600)).curve()

	below, belowOK := viewValue(29.9, &curve)
	above, aboveOK := viewValue(30.1, &curve)
	if !belowOK || !aboveOK {
		t.Fatalf("expected evidence on both sides of the threshold")
	}
	if math.Abs(above-below) >= 0.01 {
		t.Errorf("step at the threshold: %v -> %v", below, above)
	}
}

// TestViewValueFallsBackToShipped covers the guards: without a fitted curve,
// or with one that is not an inverted U, the shipped two-piece shape stands.
func TestViewValueFallsBackToShipped(t *testing.T) {
	shipped := viewPositiveMax * (1 - math.Exp(-(300.0-shortExitSeconds)/viewRiseSeconds))
	if got, ok := viewValue(300.0, nil); !ok || got != shipped {
		t.Errorf("unfitted viewValue(300) = %v, want %v", got, shipped)
	}
	positiveCurvature := [4]float64{-4.0, 1.6, 0.2, -2.0}
	if got, ok := viewValue(300.0, &positiveCurvature); !ok || got != shipped {
		t.Errorf("positive-curvature viewValue(300) = %v, want %v", got, shipped)
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
