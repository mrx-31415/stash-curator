"""Fit the watch-time response curve per instance.

`viewing_outcome`'s shipped curve rises monotonically in watch time. Measured
against an outcome it cannot influence -- whether the user returned to the
scene on a later day -- the real relationship is an inverted U peaking near a
minute, so the shipped curve assigns its maximum where measured outcomes are
near-worst.

This fits `logit(p) = b0 + b1*ln t + b2*(ln t)^2` on first plays and returns
coefficients only when they earn adoption. Everything here is deliberately
plain float arithmetic in a fixed operation order, with no RNG and no linear
algebra library: the Go model builder mirrors it bit-for-bit, the same way the
multi-hop PageRank kernel is mirrored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Shipped prior. These are the coefficients measured on a real library, and
# they are what a fitted curve is shrunk toward, so a small instance moves
# smoothly from shipped to personal behaviour instead of jumping between
# builds.
DEFAULT_VIEW_CURVE = (-3.332, 0.734, -0.092)

# Guards. A cold install must never be worse off than the shipped curve.
MIN_FIRST_PLAYS = 200
MIN_POSITIVES = 30
SHRINK_PRIOR_STRENGTH = 400.0
PAYLOAD_DIGITS = 6
CV_FOLDS = 5
IRLS_ITERATIONS = 40
IRLS_RIDGE = 1e-8


@dataclass(frozen=True)
class ViewCurveFit:
    """The outcome of a fit attempt, including why it was refused."""

    coefficients: tuple[float, float, float]
    # logit of the instance's overall return rate. The curve is read relative
    # to this: a duration that predicts returning better than the library
    # average is positive evidence, one that predicts worse is negative.
    base_logit: float
    adopted: bool
    reason: str
    sample_size: int
    positives: int
    heldout_quadratic: float
    heldout_monotone: float
    heldout_constant: float

    @property
    def curve(self) -> tuple[float, float, float, float]:
        """The four numbers `viewing_outcome` needs: the fit plus its centre."""
        return (*self.coefficients, self.base_logit)

    def as_payload(self) -> dict[str, object]:
        """Recorded in the artifact so a model says which curve produced it.

        Held-out scores are null rather than infinite when a guard refused
        before scoring: `json.dumps` would emit `Infinity`, which is not JSON
        and which the Go mirror could not reproduce.

        Values are rounded because Go's math.Exp/math.Log and CPython's libm
        differ in the last bit, and this payload is compared as a JSON string
        between the two implementations. Six digits is far more than the field
        needs -- it is provenance, not an input to anything -- and far coarser
        than the disagreement, so the two always serialize identically.
        """

        def score(value: float) -> float | None:
            return round(value, PAYLOAD_DIGITS) if math.isfinite(value) else None

        return {
            "coefficients": [round(value, PAYLOAD_DIGITS) for value in self.coefficients],
            "base_logit": round(self.base_logit, PAYLOAD_DIGITS),
            "adopted": self.adopted,
            "reason": self.reason,
            "sample_size": self.sample_size,
            "positives": self.positives,
            "heldout_quadratic": score(self.heldout_quadratic),
            "heldout_monotone": score(self.heldout_monotone),
            "heldout_constant": score(self.heldout_constant),
        }


def _design(log_t: float, terms: int) -> tuple[float, ...]:
    if terms == 1:
        return (1.0,)
    if terms == 2:
        return (1.0, log_t)
    return (1.0, log_t, log_t * log_t)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting on a small dense system.

    Written out rather than delegated so the Go mirror can reproduce the same
    operation order exactly.
    """
    size = len(vector)
    augmented = [[*matrix[row], vector[row]] for row in range(size)]
    for column in range(size):
        pivot_row = column
        largest = abs(augmented[column][column])
        for row in range(column + 1, size):
            candidate = abs(augmented[row][column])
            if candidate > largest:
                largest = candidate
                pivot_row = row
        if largest < 1e-12:
            return None
        if pivot_row != column:
            augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]
        pivot = augmented[column][column]
        for row in range(column + 1, size):
            factor = augmented[row][column] / pivot
            if factor == 0.0:
                continue
            for col in range(column, size + 1):
                augmented[row][col] -= factor * augmented[column][col]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        total = augmented[row][size]
        for col in range(row + 1, size):
            total -= augmented[row][col] * solution[col]
        solution[row] = total / augmented[row][row]
    return solution


def _fit_logistic(samples: list[tuple[float, float]], terms: int) -> list[float] | None:
    """Newton/IRLS on the logistic likelihood. Fixed iteration count so two
    implementations cannot diverge on a convergence test."""
    beta = [0.0] * terms
    for _ in range(IRLS_ITERATIONS):
        hessian = [[IRLS_RIDGE if r == c else 0.0 for c in range(terms)] for r in range(terms)]
        gradient = [0.0] * terms
        for log_t, label in samples:
            row = _design(log_t, terms)
            z = 0.0
            for index in range(terms):
                z += beta[index] * row[index]
            p = 1.0 / (1.0 + math.exp(-z)) if z > -700.0 else 0.0
            weight = p * (1.0 - p)
            if weight < 1e-9:
                weight = 1e-9
            residual = label - p
            for r in range(terms):
                gradient[r] += row[r] * residual
                for c in range(terms):
                    hessian[r][c] += row[r] * row[c] * weight
        step = _solve(hessian, gradient)
        if step is None:
            return None
        for index in range(terms):
            beta[index] += step[index]
        if not all(math.isfinite(value) for value in beta):
            return None
    return beta


def _log_likelihood(samples: list[tuple[float, float]], beta: list[float]) -> float:
    terms = len(beta)
    total = 0.0
    for log_t, label in samples:
        row = _design(log_t, terms)
        z = 0.0
        for index in range(terms):
            z += beta[index] * row[index]
        # log(1 + e^z) without overflow.
        total += label * z - (z + math.log1p(math.exp(-z)) if z > 0.0 else math.log1p(math.exp(z)))
    return total


def _heldout(samples: list[tuple[float, float]], terms: int) -> float:
    """Negative held-out log-likelihood over deterministic folds.

    Folds are assigned by position in the caller's stable ordering, so no
    random seed has to agree across two languages.
    """
    total = 0.0
    for fold in range(CV_FOLDS):
        train = [row for index, row in enumerate(samples) if index % CV_FOLDS != fold]
        test = [row for index, row in enumerate(samples) if index % CV_FOLDS == fold]
        if not train or not test:
            continue
        beta = _fit_logistic(train, terms)
        if beta is None:
            return math.inf
        total -= _log_likelihood(test, beta)
    return total


def fit_view_curve(first_plays: list[tuple[float, bool]]) -> ViewCurveFit:
    """Fit and adjudicate the curve. `first_plays` must be in a stable order."""
    samples = [
        (math.log(seconds), 1.0 if returned else 0.0)
        for seconds, returned in first_plays
        if seconds > 0.0 and math.isfinite(seconds)
    ]
    positives = sum(1 for _, label in samples if label > 0.0)
    base_logit = 0.0
    if 0 < positives < len(samples):
        base_rate = positives / len(samples)
        base_logit = math.log(base_rate / (1.0 - base_rate))

    def refuse(
        reason: str, quad: float = math.inf, mono: float = math.inf, const: float = math.inf
    ) -> ViewCurveFit:
        return ViewCurveFit(
            DEFAULT_VIEW_CURVE,
            base_logit,
            False,
            reason,
            len(samples),
            positives,
            quad,
            mono,
            const,
        )

    if len(samples) < MIN_FIRST_PLAYS:
        return refuse("insufficient_sample")
    if positives < MIN_POSITIVES:
        return refuse("insufficient_positives")
    if positives == len(samples):
        # Every first play returned: there is no base rate to read the curve
        # against, so there is nothing for it to be evidence relative to.
        return refuse("no_negative_class")

    quadratic = _heldout(samples, 3)
    monotone = _heldout(samples, 2)
    constant = _heldout(samples, 1)
    if not math.isfinite(quadratic):
        return refuse("fit_failed", quadratic, monotone, constant)
    # "It won", not "it converged": the shape has to beat both simpler
    # alternatives on data it did not see.
    if quadratic >= monotone or quadratic >= constant:
        return refuse("not_better_than_baseline", quadratic, monotone, constant)

    beta = _fit_logistic(samples, 3)
    if beta is None:
        return refuse("fit_failed", quadratic, monotone, constant)
    if beta[2] >= 0.0:
        # Positive curvature is a U, not an inverted U -- the shipped curve is
        # a better description than that.
        return refuse("curvature_not_negative", quadratic, monotone, constant)

    weight = len(samples) / (len(samples) + SHRINK_PRIOR_STRENGTH)
    shrunk = tuple(
        weight * beta[index] + (1.0 - weight) * DEFAULT_VIEW_CURVE[index] for index in range(3)
    )
    if shrunk[2] >= 0.0:
        return refuse("curvature_not_negative", quadratic, monotone, constant)
    return ViewCurveFit(
        (shrunk[0], shrunk[1], shrunk[2]),
        base_logit,
        True,
        "adopted",
        len(samples),
        positives,
        quadratic,
        monotone,
        constant,
    )
