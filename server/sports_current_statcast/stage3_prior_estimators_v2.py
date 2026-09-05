"""Deterministic empirical-Bayes estimators for MLB player-state priors.

The functions in this module are intentionally data-source agnostic.  They
accept already authenticated, training-only sufficient statistics and return
plain JSON-compatible parameter dictionaries.  No target, model, validation
metric, clock, filesystem path, or final-OOT value enters scientific identity.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np


INTEGER_TOLERANCE = 1e-6
PROBABILITY_EPSILON = 1e-9
FLOAT64_CSS_TOLERANCE_MULTIPLIER = 64.0


class PriorEstimatorV2Error(RuntimeError):
    """A sufficient-statistic domain or estimator invariant failed closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _float_vector(values: Sequence[float] | np.ndarray, *, name: str) -> np.ndarray:
    output = np.asarray(values, dtype=np.float64)
    if output.ndim != 1:
        raise PriorEstimatorV2Error("ESTIMATOR_VECTOR_REQUIRED", f"{name} must be one-dimensional.")
    if not bool(np.isfinite(output).all()):
        raise PriorEstimatorV2Error("ESTIMATOR_NONFINITE_INPUT", f"{name} contains a non-finite value.")
    return output


def _integer_vector(values: Sequence[float] | np.ndarray, *, name: str) -> np.ndarray:
    output = _float_vector(values, name=name)
    rounded = np.rint(output)
    if bool(((output < -INTEGER_TOLERANCE) | (np.abs(output - rounded) > INTEGER_TOLERANCE)).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COUNT_DOMAIN_INVALID",
            f"{name} must contain exact nonnegative integer counts.",
        )
    return rounded.astype(np.float64, copy=False)


def _fixed_sum(values: np.ndarray) -> float:
    return float(math.fsum(float(value) for value in values.tolist()))


def _fixed_mean(values: np.ndarray) -> float:
    return _fixed_sum(values) / float(len(values))


def _fixed_sample_variance(values: np.ndarray) -> float:
    if len(values) <= 1:
        return 0.0
    mean = _fixed_mean(values)
    return float(
        math.fsum((float(value) - mean) ** 2 for value in values.tolist())
        / float(len(values) - 1)
    )


def _deterministic_median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise PriorEstimatorV2Error("ESTIMATOR_MEDIAN_EMPTY", "A deterministic median requires values.")
    middle = len(ordered) // 2
    return (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )


def _linear_quantile(values: np.ndarray, probability: float) -> float:
    ordered = np.sort(values.astype(np.float64, copy=False), kind="mergesort")
    if not len(ordered):
        raise PriorEstimatorV2Error("ESTIMATOR_QUANTILE_EMPTY", "A quantile requires values.")
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * float(probability)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    weight = position - lower
    return float((1.0 - weight) * ordered[lower] + weight * ordered[upper])


def validate_composition(
    counts: Sequence[Sequence[float]] | np.ndarray,
    totals: Sequence[float] | np.ndarray,
    *,
    family_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.asarray(counts, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COMPOSITION_SHAPE_INVALID",
            f"{family_id} requires a two-dimensional composition with at least two cells.",
        )
    exposure = _integer_vector(totals, name=f"{family_id} totals")
    if len(exposure) != len(matrix):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COMPOSITION_LENGTH_MISMATCH",
            f"{family_id} count rows and totals differ.",
        )
    if not bool(np.isfinite(matrix).all()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_NONFINITE_INPUT", f"{family_id} contains a non-finite component."
        )
    rounded = np.rint(matrix)
    if bool(((matrix < -INTEGER_TOLERANCE) | (np.abs(matrix - rounded) > INTEGER_TOLERANCE)).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COUNT_DOMAIN_INVALID",
            f"{family_id} components must be exact nonnegative integer counts.",
        )
    matrix = rounded.astype(np.float64, copy=False)
    reconciliation = matrix.sum(axis=1, dtype=np.float64)
    if bool((np.abs(reconciliation - exposure) > INTEGER_TOLERANCE).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COMPOSITION_RECONCILIATION_FAILED",
            f"{family_id} components do not sum exactly to their registered denominator.",
        )
    if bool((matrix > exposure[:, None] + INTEGER_TOLERANCE).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COMPONENT_EXCEEDS_TOTAL",
            f"{family_id} has a component greater than its denominator.",
        )
    return matrix, exposure


def fit_dirichlet_multinomial(
    counts: Sequence[Sequence[float]] | np.ndarray,
    totals: Sequence[float] | np.ndarray,
    *,
    family_id: str,
    cell_names: Sequence[str],
) -> dict[str, Any]:
    """Fit one shared Dirichlet prior by deterministic method of moments."""

    matrix, exposure = validate_composition(counts, totals, family_id=family_id)
    if matrix.shape[1] != len(cell_names) or len(set(cell_names)) != len(cell_names):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_CELL_CONTRACT_INVALID",
            f"{family_id} cell names do not match the composition width.",
        )
    positive = exposure > 0.0
    if not bool(positive.any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_TRAINING_EVIDENCE_EMPTY",
            f"{family_id} has no positive-exposure training player state.",
        )
    matrix = matrix[positive]
    exposure = exposure[positive]
    k = matrix.shape[1]
    total_exposure = _fixed_sum(exposure)
    cell_totals = np.asarray([_fixed_sum(matrix[:, index]) for index in range(k)])
    probabilities = (cell_totals + 0.5) / (total_exposure + float(k) / 2.0)
    probabilities = probabilities / _fixed_sum(probabilities)
    shares = matrix / exposure[:, None]
    sample_variances: list[float] = []
    sampling_variances: list[float] = []
    corrected_variances: list[float] = []
    candidates: list[float] = []
    for index in range(k):
        probability = float(probabilities[index])
        sample = _fixed_sample_variance(shares[:, index])
        sampling = _fixed_mean(probability * (1.0 - probability) / exposure)
        corrected = max(0.0, sample - sampling)
        sample_variances.append(sample)
        sampling_variances.append(sampling)
        corrected_variances.append(corrected)
        if corrected > PROBABILITY_EPSILON:
            candidate = probability * (1.0 - probability) / corrected - 1.0
            if math.isfinite(candidate) and candidate > 0.0:
                candidates.append(float(candidate))
    median_exposure = _deterministic_median(exposure.tolist())
    exposure_p95 = _linear_quantile(exposure, 0.95)
    fallback_used = not candidates
    raw_concentration = (
        _deterministic_median(candidates) if candidates else median_exposure
    )
    concentration = float(
        np.clip(
            raw_concentration,
            PROBABILITY_EPSILON,
            max(exposure_p95, PROBABILITY_EPSILON),
        )
    )
    alphas = probabilities * concentration
    return {
        "method": "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES_METHOD_OF_MOMENTS",
        "familyId": family_id,
        "cellNames": list(cell_names),
        "priorAlpha": [float(value) for value in alphas],
        "priorComposition": [float(value) for value in probabilities],
        "priorConcentration": concentration,
        "playerStateCount": int(len(exposure)),
        "totalObservedExposure": total_exposure,
        "totalObservedCellCounts": [float(value) for value in cell_totals],
        "sampleShareVariance": sample_variances,
        "meanMultinomialSamplingVariance": sampling_variances,
        "correctedBetweenPlayerVariance": corrected_variances,
        "identifiedConcentrationCandidates": sorted(candidates),
        "rawMethodOfMomentsConcentration": raw_concentration,
        "underidentifiedFallbackUsed": fallback_used,
        "trainingMedianExposure": median_exposure,
        "trainingExposureP95": exposure_p95,
    }


def fit_beta_binomial(
    successes: Sequence[float] | np.ndarray,
    trials: Sequence[float] | np.ndarray,
    *,
    family_id: str,
    success_cell: str,
    failure_cell: str,
) -> dict[str, Any]:
    """Canonical K=2 Dirichlet adapter, exactly equivalent to Beta-Binomial."""

    success = _integer_vector(successes, name=f"{family_id} successes")
    exposure = _integer_vector(trials, name=f"{family_id} trials")
    if len(success) != len(exposure) or bool((success > exposure).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_BINOMIAL_RECONCILIATION_FAILED",
            f"{family_id} successes must be no greater than trials.",
        )
    fitted = fit_dirichlet_multinomial(
        np.column_stack((success, exposure - success)),
        exposure,
        family_id=family_id,
        cell_names=(success_cell, failure_cell),
    )
    alpha, beta = fitted["priorAlpha"]
    return {
        **fitted,
        "method": "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "alpha": alpha,
        "beta": beta,
        "priorMean": fitted["priorComposition"][0],
        "priorStrength": fitted["priorConcentration"],
        "totalObservedTrials": fitted["totalObservedExposure"],
        "totalObservedSuccesses": fitted["totalObservedCellCounts"][0],
        "sampleRateVariance": fitted["sampleShareVariance"][0],
        "meanBinomialSamplingVariance": fitted[
            "meanMultinomialSamplingVariance"
        ][0],
        "correctedBetweenPlayerVariance": fitted[
            "correctedBetweenPlayerVariance"
        ][0],
    }


def dirichlet_posterior(
    counts: Sequence[Sequence[float]] | np.ndarray,
    totals: Sequence[float] | np.ndarray,
    fitted: dict[str, Any],
) -> dict[str, np.ndarray]:
    matrix, exposure = validate_composition(
        counts, totals, family_id=str(fitted.get("familyId") or "DIRICHLET")
    )
    alpha = _float_vector(fitted["priorAlpha"], name="prior alpha")
    if matrix.shape[1] != len(alpha) or bool((alpha <= 0.0).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_FITTED_PARAMETER_INVALID", "Dirichlet prior alphas are invalid."
        )
    posterior_alpha = matrix + alpha[None, :]
    posterior_strength = posterior_alpha.sum(axis=1, dtype=np.float64)
    means = posterior_alpha / posterior_strength[:, None]
    denominator = posterior_strength**2 * (posterior_strength + 1.0)
    variances = (
        posterior_alpha
        * (posterior_strength[:, None] - posterior_alpha)
        / denominator[:, None]
    )
    covariance = np.empty((len(matrix), len(alpha), len(alpha)), dtype=np.float64)
    for left in range(len(alpha)):
        for right in range(len(alpha)):
            covariance[:, left, right] = (
                variances[:, left]
                if left == right
                else -posterior_alpha[:, left]
                * posterior_alpha[:, right]
                / denominator
            )
    return {
        "posteriorAlpha": posterior_alpha,
        "posteriorMean": means,
        "posteriorVariance": variances,
        "posteriorCovariance": covariance,
        "posteriorStrength": posterior_strength,
        "effectiveN": exposure,
        "reliability": exposure / (float(alpha.sum()) + exposure),
    }


def fit_gamma_poisson_components(
    component_counts: Sequence[Sequence[float]] | np.ndarray,
    exposure_values: Sequence[float] | np.ndarray,
    *,
    family_id: str,
    component_names: Sequence[str],
) -> dict[str, Any]:
    counts = np.asarray(component_counts, dtype=np.float64)
    exposure = _integer_vector(exposure_values, name=f"{family_id} exposure")
    if counts.ndim != 2 or counts.shape[1] != len(component_names) or len(counts) != len(exposure):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COMPONENT_SHAPE_INVALID",
            f"{family_id} component counts do not match their contract.",
        )
    if not bool(np.isfinite(counts).all()):
        raise PriorEstimatorV2Error("ESTIMATOR_NONFINITE_INPUT", f"{family_id} contains non-finite counts.")
    rounded = np.rint(counts)
    if bool(((counts < -INTEGER_TOLERANCE) | (np.abs(counts - rounded) > INTEGER_TOLERANCE)).any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_COUNT_DOMAIN_INVALID",
            f"{family_id} component counts must be nonnegative integers.",
        )
    positive = exposure > 0.0
    if not bool(positive.any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_TRAINING_EVIDENCE_EMPTY", f"{family_id} has no positive exposure."
        )
    counts = rounded[positive]
    exposure = exposure[positive]
    rates = counts / exposure[:, None]
    total_exposure = _fixed_sum(exposure)
    means: list[float] = []
    sample_variances: list[float] = []
    sampling_variances: list[float] = []
    corrected_variances: list[float] = []
    candidates: list[float] = []
    totals: list[float] = []
    for index in range(counts.shape[1]):
        total_count = _fixed_sum(counts[:, index])
        mean = float((total_count + 0.5) / (total_exposure + 1.0))
        sample = _fixed_sample_variance(rates[:, index])
        sampling = _fixed_mean(mean / exposure)
        corrected = max(0.0, sample - sampling)
        candidate = mean / corrected if corrected > PROBABILITY_EPSILON else math.nan
        if math.isfinite(candidate) and candidate > 0.0:
            candidates.append(float(candidate))
        totals.append(total_count)
        means.append(mean)
        sample_variances.append(sample)
        sampling_variances.append(sampling)
        corrected_variances.append(corrected)
    median_exposure = _deterministic_median(exposure.tolist())
    exposure_p95 = _linear_quantile(exposure, 0.95)
    fallback_used = not candidates
    raw_equivalent_exposure = (
        _deterministic_median(candidates) if candidates else median_exposure
    )
    equivalent_exposure = float(
        np.clip(
            raw_equivalent_exposure,
            PROBABILITY_EPSILON,
            max(exposure_p95, PROBABILITY_EPSILON),
        )
    )
    shapes = [float(mean * equivalent_exposure) for mean in means]
    return {
        "method": "GAMMA_POISSON_COMPONENT_SHRINKAGE",
        "familyId": family_id,
        "componentNames": list(component_names),
        "priorShape": shapes,
        "priorRate": equivalent_exposure,
        "priorComponentMean": means,
        "priorEquivalentExposure": equivalent_exposure,
        "playerStateCount": int(len(exposure)),
        "totalObservedExposure": total_exposure,
        "totalObservedComponentCounts": totals,
        "sampleRateVariance": sample_variances,
        "meanPoissonSamplingVariance": sampling_variances,
        "correctedBetweenPlayerRateVariance": corrected_variances,
        "identifiedEquivalentExposureCandidates": sorted(candidates),
        "rawEquivalentExposure": raw_equivalent_exposure,
        "underidentifiedFallbackUsed": fallback_used,
        "trainingMedianExposure": median_exposure,
        "trainingExposureP95": exposure_p95,
    }


def gamma_poisson_posterior(
    component_counts: Sequence[Sequence[float]] | np.ndarray,
    exposure_values: Sequence[float] | np.ndarray,
    fitted: dict[str, Any],
) -> dict[str, np.ndarray]:
    counts = np.asarray(component_counts, dtype=np.float64)
    exposure = _integer_vector(exposure_values, name="Gamma-Poisson exposure")
    rounded = np.rint(counts)
    if (
        counts.ndim != 2
        or len(counts) != len(exposure)
        or counts.shape[1] != len(fitted["priorShape"])
        or not bool(np.isfinite(counts).all())
        or bool(((counts < -INTEGER_TOLERANCE) | (np.abs(counts - rounded) > INTEGER_TOLERANCE)).any())
        or bool(((exposure == 0.0) & (rounded.sum(axis=1) > 0.0)).any())
    ):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_GAMMA_POISSON_INPUT_INVALID",
            "Gamma-Poisson counts/exposure violate the registered component domain.",
        )
    shape = _float_vector(fitted["priorShape"], name="Gamma prior shape")
    rate = float(fitted["priorRate"])
    if rate <= 0.0 or bool((shape <= 0.0).any()):
        raise PriorEstimatorV2Error("ESTIMATOR_FITTED_PARAMETER_INVALID", "Gamma prior parameters are invalid.")
    posterior_shape = rounded + shape[None, :]
    posterior_rate = rate + exposure
    means = posterior_shape / posterior_rate[:, None]
    variances = posterior_shape / posterior_rate[:, None] ** 2
    return {
        "posteriorShape": posterior_shape,
        "posteriorRate": posterior_rate,
        "posteriorMean": means,
        "posteriorVariance": variances,
        "effectiveN": exposure,
        "reliability": exposure / posterior_rate,
    }


def normal_sufficient_statistics(
    counts: Sequence[float] | np.ndarray,
    sums: Sequence[float] | np.ndarray,
    sums_of_squares: Sequence[float] | np.ndarray,
) -> dict[str, np.ndarray]:
    n = _integer_vector(counts, name="Normal observation count")
    total = _float_vector(sums, name="Normal observation sum")
    square_total = _float_vector(sums_of_squares, name="Normal observation sumsq")
    if not (len(n) == len(total) == len(square_total)):
        raise PriorEstimatorV2Error("ESTIMATOR_NORMAL_LENGTH_MISMATCH", "Normal sufficient-statistic lengths differ.")
    zero_invalid = (n == 0.0) & ((np.abs(total) > INTEGER_TOLERANCE) | (np.abs(square_total) > INTEGER_TOLERANCE))
    if bool(zero_invalid.any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_NORMAL_ZERO_COUNT_INVALID",
            "Zero-count Normal state carries a nonzero sum or sum of squares.",
        )
    mean = np.full(len(n), np.nan, dtype=np.float64)
    css = np.full(len(n), np.nan, dtype=np.float64)
    variance = np.full(len(n), np.nan, dtype=np.float64)
    positive = n > 0.0
    mean[positive] = total[positive] / n[positive]
    css[positive] = square_total[positive] - total[positive] ** 2 / n[positive]
    tolerance = FLOAT64_CSS_TOLERANCE_MULTIPLIER * np.finfo(np.float64).eps * np.maximum.reduce(
        (
            np.abs(square_total),
            np.where(positive, np.abs(total**2 / np.where(positive, n, 1.0)), 0.0),
            np.ones(len(n), dtype=np.float64),
        )
    )
    material_negative = positive & (css < -tolerance)
    if bool(material_negative.any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_NORMAL_NEGATIVE_VARIANCE",
            "Normal sum/sumsq/count imply a materially negative centered sum of squares.",
        )
    singleton_invalid = (n == 1.0) & (np.abs(css) > tolerance)
    if bool(singleton_invalid.any()):
        raise PriorEstimatorV2Error(
            "ESTIMATOR_NORMAL_SINGLETON_RECONCILIATION_FAILED",
            "A one-observation Normal state must satisfy sumsq = sum^2 within the registered float64 tolerance.",
        )
    tiny_negative = positive & (css < 0.0)
    css[tiny_negative] = 0.0
    singleton_clamped = n == 1.0
    css[singleton_clamped] = 0.0
    multiple = n > 1.0
    variance[multiple] = css[multiple] / (n[multiple] - 1.0)
    return {
        "count": n,
        "sum": total,
        "sumsq": square_total,
        "sampleMean": mean,
        "centeredSumSquares": css,
        "sampleVariance": variance,
        "cssTolerance": tolerance,
        "tinyNegativeCssClamped": tiny_negative,
        "singletonCssClamped": singleton_clamped,
    }


def fit_normal_normal(
    counts: Sequence[float] | np.ndarray,
    sums: Sequence[float] | np.ndarray,
    sums_of_squares: Sequence[float] | np.ndarray,
    *,
    family_id: str,
) -> dict[str, Any]:
    stats = normal_sufficient_statistics(counts, sums, sums_of_squares)
    n = stats["count"]
    positive = n > 0.0
    if not bool(positive.any()):
        raise PriorEstimatorV2Error("ESTIMATOR_TRAINING_EVIDENCE_EMPTY", f"{family_id} has no observed velocity.")
    observed_n = n[positive]
    observed_sum = stats["sum"][positive]
    means = stats["sampleMean"][positive]
    pooled_mask = observed_n > 1.0
    if bool(pooled_mask.any()):
        pooled_numerator = _fixed_sum(stats["centeredSumSquares"][positive][pooled_mask])
        pooled_denominator = _fixed_sum(observed_n[pooled_mask] - 1.0)
        pooled_within = pooled_numerator / pooled_denominator
    else:
        pooled_within = 0.0
    if not math.isfinite(pooled_within) or pooled_within <= PROBABILITY_EPSILON:
        pooled_within = PROBABILITY_EPSILON
        within_fallback = True
    else:
        within_fallback = False
    population_mean = _fixed_sum(observed_sum) / _fixed_sum(observed_n)
    sample_mean_variance = _fixed_sample_variance(means)
    mean_sampling_variance = _fixed_mean(pooled_within / observed_n)
    corrected_between = max(0.0, sample_mean_variance - mean_sampling_variance)
    raw_equivalent = (
        pooled_within / corrected_between
        if corrected_between > PROBABILITY_EPSILON
        else math.nan
    )
    median_n = _deterministic_median(observed_n.tolist())
    n_p95 = _linear_quantile(observed_n, 0.95)
    between_fallback = not math.isfinite(raw_equivalent) or raw_equivalent <= 0.0
    equivalent_n = median_n if between_fallback else raw_equivalent
    equivalent_n = float(np.clip(equivalent_n, PROBABILITY_EPSILON, max(n_p95, PROBABILITY_EPSILON)))
    governed_between = pooled_within / equivalent_n
    return {
        "method": "NORMAL_NORMAL_EMPIRICAL_BAYES",
        "familyId": family_id,
        "populationMean": float(population_mean),
        "pooledWithinPlayerVariance": float(pooled_within),
        "correctedBetweenPlayerVariance": float(corrected_between),
        "governedBetweenPlayerVariance": float(governed_between),
        "priorEquivalentObservationCount": equivalent_n,
        "playerStateCount": int(len(observed_n)),
        "totalObservedCount": _fixed_sum(observed_n),
        "samplePlayerMeanVariance": sample_mean_variance,
        "meanPlayerSamplingVariance": mean_sampling_variance,
        "rawEquivalentObservationCount": raw_equivalent if math.isfinite(raw_equivalent) else None,
        "underidentifiedBetweenVarianceFallbackUsed": between_fallback,
        "pooledWithinVarianceFallbackUsed": within_fallback,
        "trainingMedianObservationCount": median_n,
        "trainingObservationCountP95": n_p95,
        "tinyNegativeCssClampCount": int(stats["tinyNegativeCssClamped"][positive].sum()),
        "cssToleranceFormula": "64 * float64_epsilon * max(abs(sumsq), abs(sum^2/n), 1)",
    }


def normal_normal_posterior(
    counts: Sequence[float] | np.ndarray,
    sums: Sequence[float] | np.ndarray,
    sums_of_squares: Sequence[float] | np.ndarray,
    fitted: dict[str, Any],
) -> dict[str, np.ndarray]:
    stats = normal_sufficient_statistics(counts, sums, sums_of_squares)
    n = stats["count"]
    population_mean = float(fitted["populationMean"])
    within = float(fitted["pooledWithinPlayerVariance"])
    between = float(fitted["governedBetweenPlayerVariance"])
    if not all(math.isfinite(value) and value > 0.0 for value in (within, between)) or not math.isfinite(population_mean):
        raise PriorEstimatorV2Error("ESTIMATOR_FITTED_PARAMETER_INVALID", "Normal-Normal fitted parameters are invalid.")
    reliability = n * between / (n * between + within)
    observed_mean = stats["sampleMean"]
    posterior_mean = np.full(len(n), population_mean, dtype=np.float64)
    positive = n > 0.0
    posterior_mean[positive] = (
        reliability[positive] * observed_mean[positive]
        + (1.0 - reliability[positive]) * population_mean
    )
    posterior_variance = 1.0 / (1.0 / between + n / within)
    return {
        **stats,
        "posteriorMean": posterior_mean,
        "posteriorVariance": posterior_variance,
        "posteriorStd": np.sqrt(posterior_variance),
        "effectiveN": n,
        "reliability": reliability,
    }


__all__ = [
    "FLOAT64_CSS_TOLERANCE_MULTIPLIER",
    "INTEGER_TOLERANCE",
    "PriorEstimatorV2Error",
    "dirichlet_posterior",
    "fit_beta_binomial",
    "fit_dirichlet_multinomial",
    "fit_gamma_poisson_components",
    "fit_normal_normal",
    "gamma_poisson_posterior",
    "normal_normal_posterior",
    "normal_sufficient_statistics",
    "validate_composition",
]
