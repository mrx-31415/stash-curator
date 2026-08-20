// Fit the watch-time response curve per instance.
//
// Mirrors curator/model/watchfit.py exactly: the same fixed IRLS iteration
// count, the same ridge, the same Gaussian elimination with partial pivoting,
// and the same deterministic fold assignment by position. No RNG and no linear
// algebra library on either side, so the two implementations agree bit-for-bit
// the way the multi-hop PageRank kernel does.

package main

import "math"

var defaultViewCurve = [3]float64{-3.332, 0.734, -0.092}

const (
	minFirstPlays       = 200
	minPositives        = 30
	shrinkPriorStrength = 400.0
	payloadDigits       = 6
	cvFolds             = 5
	irlsIterations      = 40
	irlsRidge           = 1e-8
)

type viewCurveFit struct {
	coefficients [3]float64
	// logit of the instance's overall return rate; the curve is read against it.
	baseLogit        float64
	adopted          bool
	reason           string
	sampleSize       int
	positives        int
	heldoutQuadratic float64
	heldoutMonotone  float64
	heldoutConstant  float64
}

type watchSample struct {
	logT  float64
	label float64
}

func watchDesign(logT float64, terms int) [3]float64 {
	switch terms {
	case 1:
		return [3]float64{1, 0, 0}
	case 2:
		return [3]float64{1, logT, 0}
	default:
		return [3]float64{1, logT, logT * logT}
	}
}

// watchSolve mirrors watchfit._solve.
func watchSolve(matrix [][]float64, vector []float64) ([]float64, bool) {
	size := len(vector)
	augmented := make([][]float64, size)
	for row := 0; row < size; row++ {
		augmented[row] = make([]float64, size+1)
		copy(augmented[row], matrix[row])
		augmented[row][size] = vector[row]
	}
	for column := 0; column < size; column++ {
		pivotRow := column
		largest := math.Abs(augmented[column][column])
		for row := column + 1; row < size; row++ {
			candidate := math.Abs(augmented[row][column])
			if candidate > largest {
				largest = candidate
				pivotRow = row
			}
		}
		if largest < 1e-12 {
			return nil, false
		}
		if pivotRow != column {
			augmented[column], augmented[pivotRow] = augmented[pivotRow], augmented[column]
		}
		pivot := augmented[column][column]
		for row := column + 1; row < size; row++ {
			factor := augmented[row][column] / pivot
			if factor == 0 {
				continue
			}
			for col := column; col <= size; col++ {
				augmented[row][col] -= float64(factor * augmented[column][col])
			}
		}
	}
	solution := make([]float64, size)
	for row := size - 1; row >= 0; row-- {
		total := augmented[row][size]
		for col := row + 1; col < size; col++ {
			total -= float64(augmented[row][col] * solution[col])
		}
		solution[row] = total / augmented[row][row]
	}
	return solution, true
}

// watchFitLogistic mirrors watchfit._fit_logistic.
func watchFitLogistic(samples []watchSample, terms int) ([]float64, bool) {
	beta := make([]float64, terms)
	for iteration := 0; iteration < irlsIterations; iteration++ {
		hessian := make([][]float64, terms)
		for r := 0; r < terms; r++ {
			hessian[r] = make([]float64, terms)
			hessian[r][r] = irlsRidge
		}
		gradient := make([]float64, terms)
		for _, sample := range samples {
			row := watchDesign(sample.logT, terms)
			z := 0.0
			for index := 0; index < terms; index++ {
				z += float64(beta[index] * row[index])
			}
			p := 0.0
			if z > -700.0 {
				p = 1.0 / (1.0 + math.Exp(-z))
			}
			weight := p * (1.0 - p)
			if weight < 1e-9 {
				weight = 1e-9
			}
			residual := sample.label - p
			for r := 0; r < terms; r++ {
				gradient[r] += float64(row[r] * residual)
				for c := 0; c < terms; c++ {
					hessian[r][c] += float64(float64(row[r]*row[c]) * weight)
				}
			}
		}
		step, ok := watchSolve(hessian, gradient)
		if !ok {
			return nil, false
		}
		for index := 0; index < terms; index++ {
			beta[index] += step[index]
		}
		for index := 0; index < terms; index++ {
			if math.IsNaN(beta[index]) || math.IsInf(beta[index], 0) {
				return nil, false
			}
		}
	}
	return beta, true
}

// watchLogLikelihood mirrors watchfit._log_likelihood.
func watchLogLikelihood(samples []watchSample, beta []float64) float64 {
	terms := len(beta)
	total := 0.0
	for _, sample := range samples {
		row := watchDesign(sample.logT, terms)
		z := 0.0
		for index := 0; index < terms; index++ {
			z += float64(beta[index] * row[index])
		}
		if z > 0.0 {
			total += float64(sample.label*z) - (z + math.Log1p(math.Exp(-z)))
		} else {
			total += float64(sample.label*z) - math.Log1p(math.Exp(z))
		}
	}
	return total
}

// watchHeldout mirrors watchfit._heldout.
func watchHeldout(samples []watchSample, terms int) float64 {
	total := 0.0
	for fold := 0; fold < cvFolds; fold++ {
		train := make([]watchSample, 0, len(samples))
		test := make([]watchSample, 0, len(samples))
		for index, sample := range samples {
			if index%cvFolds != fold {
				train = append(train, sample)
			} else {
				test = append(test, sample)
			}
		}
		if len(train) == 0 || len(test) == 0 {
			continue
		}
		beta, ok := watchFitLogistic(train, terms)
		if !ok {
			return math.Inf(1)
		}
		total -= watchLogLikelihood(test, beta)
	}
	return total
}

// fitViewCurve mirrors watchfit.fit_view_curve. firstPlays must arrive in the
// same stable order the Python side uses (ordered by scene_id).
func fitViewCurve(firstPlays []struct {
	Seconds  float64
	Returned bool
}) viewCurveFit {
	samples := make([]watchSample, 0, len(firstPlays))
	positives := 0
	for _, play := range firstPlays {
		if play.Seconds <= 0 || math.IsNaN(play.Seconds) || math.IsInf(play.Seconds, 0) {
			continue
		}
		label := 0.0
		if play.Returned {
			label = 1.0
			positives++
		}
		samples = append(samples, watchSample{math.Log(play.Seconds), label})
	}
	inf := math.Inf(1)
	baseLogit := 0.0
	if positives > 0 && positives < len(samples) {
		baseRate := float64(positives) / float64(len(samples))
		baseLogit = math.Log(baseRate / (1.0 - baseRate))
	}
	refuse := func(reason string, quad, mono, konst float64) viewCurveFit {
		return viewCurveFit{
			defaultViewCurve, baseLogit, false, reason, len(samples), positives, quad, mono, konst,
		}
	}
	if len(samples) < minFirstPlays {
		return refuse("insufficient_sample", inf, inf, inf)
	}
	if positives < minPositives {
		return refuse("insufficient_positives", inf, inf, inf)
	}
	if positives == len(samples) {
		return refuse("no_negative_class", inf, inf, inf)
	}
	quadratic := watchHeldout(samples, 3)
	monotone := watchHeldout(samples, 2)
	constant := watchHeldout(samples, 1)
	if math.IsInf(quadratic, 0) || math.IsNaN(quadratic) {
		return refuse("fit_failed", quadratic, monotone, constant)
	}
	if quadratic >= monotone || quadratic >= constant {
		return refuse("not_better_than_baseline", quadratic, monotone, constant)
	}
	beta, ok := watchFitLogistic(samples, 3)
	if !ok {
		return refuse("fit_failed", quadratic, monotone, constant)
	}
	if beta[2] >= 0.0 {
		return refuse("curvature_not_negative", quadratic, monotone, constant)
	}
	weight := float64(len(samples)) / (float64(len(samples)) + shrinkPriorStrength)
	var shrunk [3]float64
	for index := 0; index < 3; index++ {
		shrunk[index] = float64(weight*beta[index]) + float64((1.0-weight)*defaultViewCurve[index])
	}
	if shrunk[2] >= 0.0 {
		return refuse("curvature_not_negative", quadratic, monotone, constant)
	}
	return viewCurveFit{
		shrunk, baseLogit, true, "adopted", len(samples), positives, quadratic, monotone, constant,
	}
}

// unfittedViewCurve is what the paths that do not fit use: the shipped curve,
// matching Python, where curation.py constructs a fresh PreferenceModelBuilder
// and calls _scene_labels() without a build having fitted anything.
func unfittedViewCurve() viewCurveFit {
	inf := math.Inf(1)
	return viewCurveFit{defaultViewCurve, 0, false, "not_fitted", 0, 0, inf, inf, inf}
}

// curve is the four numbers viewingOutcomeCurve needs: the fit plus its centre.
func (fit viewCurveFit) curve() [4]float64 {
	return [4]float64{fit.coefficients[0], fit.coefficients[1], fit.coefficients[2], fit.baseLogit}
}

// payload mirrors ViewCurveFit.as_payload, including the null-for-infinite
// rule: json.dumps would emit Infinity, which is not JSON.
func (fit viewCurveFit) payload() jVal {
	scale := math.Pow(10, payloadDigits)
	round := func(value float64) float64 {
		return math.Round(value*scale) / scale
	}
	score := func(value float64) jVal {
		if math.IsInf(value, 0) || math.IsNaN(value) {
			return jvNull()
		}
		return jvFloat(round(value))
	}
	coefficients := jvArr(
		jvFloat(round(fit.coefficients[0])),
		jvFloat(round(fit.coefficients[1])),
		jvFloat(round(fit.coefficients[2])),
	)
	return jvObj(
		jvKey("coefficients", coefficients),
		jvKey("base_logit", jvFloat(round(fit.baseLogit))),
		jvKey("adopted", jvBool(fit.adopted)),
		jvKey("reason", jvStr(fit.reason)),
		jvKey("sample_size", jvInt(int64(fit.sampleSize))),
		jvKey("positives", jvInt(int64(fit.positives))),
		jvKey("heldout_quadratic", score(fit.heldoutQuadratic)),
		jvKey("heldout_monotone", score(fit.heldoutMonotone)),
		jvKey("heldout_constant", score(fit.heldoutConstant)),
	)
}
