from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar

from .metrics import (
    DEFAULT_CALIBRATION_BINS,
    PA_CLASS_ORDER,
    PROBABILITY_EPSILON,
    evaluate_multiclass,
    require_frozen_class_order,
    validate_evaluation_inputs,
    validate_probability_matrix,
)


CALIBRATION_SCHEMA_VERSION = "MLB_PA_TEMPERATURE_CALIBRATION_V1"
CALIBRATION_SOURCE_SEASON = 2024
DEFAULT_TEMPERATURE_BOUNDS = (0.05, 20.0)
# Metric differences at or below this absolute tolerance are treated as numerical ties.
CALIBRATION_RETENTION_TOLERANCE = 1e-10


@dataclass(frozen=True)
class TemperatureScalingResult:
    source_season: int
    fitted_temperature: float
    retained_temperature: float
    retained: bool
    retention_tolerance: float
    raw_probabilities: np.ndarray
    scaled_probabilities: np.ndarray
    final_probabilities: np.ndarray
    raw_evidence: dict[str, Any]
    scaled_evidence: dict[str, Any]
    optimizer_success: bool
    optimizer_message: str
    rejection_reason: str | None
    temperature_bounds: tuple[float, float]

    def evidence(self) -> dict[str, Any]:
        """Return JSON-ready calibration evidence without duplicating row probabilities."""

        return {
            "schemaVersion": CALIBRATION_SCHEMA_VERSION,
            "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
            "zeroProbabilityHandling": "CLIP_TO_FLOAT64_EPSILON_BEFORE_LOG",
            "sourceSeason": self.source_season,
            "fittedTemperature": self.fitted_temperature,
            "retainedTemperature": self.retained_temperature,
            "retained": self.retained,
            "retentionRule": "LOG_LOSS_AND_SUMMED_MULTICLASS_BRIER_MUST_NOT_WORSEN",
            "retentionTolerance": self.retention_tolerance,
            "temperatureBounds": list(self.temperature_bounds),
            "optimizerSuccess": self.optimizer_success,
            "optimizerMessage": self.optimizer_message,
            "rejectionReason": self.rejection_reason,
            "raw": self.raw_evidence,
            "scaledCandidate": self.scaled_evidence,
            "finalSelection": "SCALED" if self.retained else "RAW",
        }


def _validate_temperature(temperature: float) -> float:
    if not isinstance(temperature, (int, float, np.integer, np.floating)) or isinstance(
        temperature, (bool, np.bool_)
    ):
        raise TypeError("temperature must be a finite positive number")
    value = float(temperature)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("temperature must be a finite positive number")
    return value


def _temperature_scale_validated(matrix: np.ndarray, temperature: float) -> np.ndarray:
    log_probabilities = np.log(np.clip(matrix, PROBABILITY_EPSILON, 1.0))
    # Center before division so even extremely small positive temperatures cannot
    # overflow equal negative log probabilities to ``-inf - -inf``.
    centered_log_probabilities = log_probabilities - log_probabilities.max(
        axis=1, keepdims=True
    )
    scaled_logits = centered_log_probabilities / temperature
    exponentiated = np.exp(scaled_logits)
    return exponentiated / exponentiated.sum(axis=1, keepdims=True)


def temperature_scale(
    probabilities: Any,
    temperature: float,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> np.ndarray:
    """Apply scalar temperature scaling using log-probability logits and softmax."""

    order = require_frozen_class_order(class_order)
    matrix = validate_probability_matrix(probabilities, class_order=order)
    value = _validate_temperature(temperature)
    return _temperature_scale_validated(matrix, value)


def _validate_source_seasons(source_seasons: Any, row_count: int) -> np.ndarray:
    raw = np.asarray(source_seasons)
    if raw.ndim != 1 or raw.shape[0] != row_count:
        raise ValueError("source_seasons must be one-dimensional and row-aligned")
    items = raw.tolist()
    if not all(
        isinstance(value, (int, np.integer))
        and not isinstance(value, (bool, np.bool_))
        for value in items
    ):
        raise TypeError("source_seasons must contain non-boolean integer years")
    values = np.asarray(items, dtype=np.int64)
    if not np.all(values == CALIBRATION_SOURCE_SEASON):
        observed = sorted({int(value) for value in values})
        raise ValueError(
            "temperature fitting is restricted to frozen 2024 calibration rows; "
            f"observed seasons={observed}"
        )
    return values


def _validate_bounds(bounds: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(bounds, tuple) or len(bounds) != 2:
        raise TypeError("temperature_bounds must be a (lower, upper) tuple")
    lower = _validate_temperature(bounds[0])
    upper = _validate_temperature(bounds[1])
    if lower >= upper:
        raise ValueError("temperature_bounds lower value must be below upper value")
    return lower, upper


def fit_temperature_scaling(
    labels: Any,
    probabilities: Any,
    *,
    source_seasons: Any,
    class_order: Sequence[str] = PA_CLASS_ORDER,
    n_bins: int = DEFAULT_CALIBRATION_BINS,
    temperature_bounds: tuple[float, float] = DEFAULT_TEMPERATURE_BOUNDS,
    retention_tolerance: float = CALIBRATION_RETENTION_TOLERANCE,
) -> TemperatureScalingResult:
    """
    Fit one temperature on 2024 rows and retain it only if both governing metrics
    do not worsen beyond the documented absolute numerical tolerance.
    """

    order = require_frozen_class_order(class_order)
    encoded, matrix = validate_evaluation_inputs(
        labels, probabilities, class_order=order
    )
    _validate_source_seasons(source_seasons, encoded.size)
    bounds = _validate_bounds(temperature_bounds)
    if not isinstance(retention_tolerance, (int, float)) or isinstance(
        retention_tolerance, bool
    ):
        raise TypeError("retention_tolerance must be a finite non-negative number")
    tolerance = float(retention_tolerance)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("retention_tolerance must be a finite non-negative number")

    row_indices = np.arange(encoded.size)

    def objective(temperature: float) -> float:
        scaled = _temperature_scale_validated(matrix, float(temperature))
        realized = scaled[row_indices, encoded]
        return float(-np.log(np.clip(realized, PROBABILITY_EPSILON, 1.0)).mean())

    optimization = minimize_scalar(
        objective,
        method="bounded",
        bounds=bounds,
        options={"xatol": 1e-8, "maxiter": 500},
    )
    optimizer_success = bool(optimization.success) and math.isfinite(
        float(optimization.x)
    )
    fitted_temperature = (
        float(optimization.x) if optimizer_success else 1.0
    )
    scaled = _temperature_scale_validated(matrix, fitted_temperature)
    raw_evidence = evaluate_multiclass(
        encoded, matrix, class_order=order, n_bins=n_bins
    )
    scaled_evidence = evaluate_multiclass(
        encoded, scaled, class_order=order, n_bins=n_bins
    )

    governing_metrics_not_worse = (
        scaled_evidence["logLoss"] <= raw_evidence["logLoss"] + tolerance
        and scaled_evidence["brierScore"] <= raw_evidence["brierScore"] + tolerance
    )
    retained = optimizer_success and governing_metrics_not_worse
    if not optimizer_success:
        rejection_reason = "OPTIMIZATION_FAILED"
    elif not governing_metrics_not_worse:
        rejection_reason = "GOVERNING_METRIC_WORSENED"
    else:
        rejection_reason = None

    raw_copy = np.array(matrix, copy=True)
    scaled_copy = np.array(scaled, copy=True)
    final_copy = np.array(scaled if retained else matrix, copy=True)
    return TemperatureScalingResult(
        source_season=CALIBRATION_SOURCE_SEASON,
        fitted_temperature=fitted_temperature,
        retained_temperature=fitted_temperature if retained else 1.0,
        retained=retained,
        retention_tolerance=tolerance,
        raw_probabilities=raw_copy,
        scaled_probabilities=scaled_copy,
        final_probabilities=final_copy,
        raw_evidence=raw_evidence,
        scaled_evidence=scaled_evidence,
        optimizer_success=optimizer_success,
        optimizer_message=str(optimization.message),
        rejection_reason=rejection_reason,
        temperature_bounds=bounds,
    )


__all__ = [
    "CALIBRATION_RETENTION_TOLERANCE",
    "CALIBRATION_SCHEMA_VERSION",
    "CALIBRATION_SOURCE_SEASON",
    "DEFAULT_TEMPERATURE_BOUNDS",
    "TemperatureScalingResult",
    "fit_temperature_scaling",
    "temperature_scale",
]
