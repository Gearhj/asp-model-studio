"""Leakage-resistant convex blending and cross-fitting helpers for NFL M1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize


class EnsembleError(ValueError):
    """Raised when ensemble inputs or fold lineage are invalid."""


def _matrix(values: Sequence[Sequence[float]] | np.ndarray, *, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise EnsembleError(f"{label} must be a non-empty two-dimensional matrix")
    if not np.isfinite(array).all():
        raise EnsembleError(f"{label} contains a non-finite value")
    return array


def _target(values: Sequence[float] | np.ndarray, rows: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size != rows or not np.isfinite(array).all():
        raise EnsembleError("target must be a finite vector aligned with predictions")
    return array


@dataclass(frozen=True)
class ConvexBlend:
    weights: tuple[float, ...]
    objective: str
    training_rows: int
    objective_value: float

    def predict(self, base_predictions: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        matrix = _matrix(base_predictions, label="base_predictions")
        weights = np.asarray(self.weights, dtype=np.float64)
        if matrix.shape[1] != weights.size:
            raise EnsembleError("base model count differs from fitted blend")
        return matrix @ weights


def fit_convex_blend(
    base_predictions: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[float] | np.ndarray,
    *,
    objective: str = "mse",
) -> ConvexBlend:
    """Fit nonnegative weights summing exactly to one on authorized rows."""

    matrix = _matrix(base_predictions, label="base_predictions")
    truth = _target(target, matrix.shape[0])
    if objective not in {"mse", "binary_log_loss"}:
        raise EnsembleError("objective must be mse or binary_log_loss")
    if objective == "binary_log_loss":
        if not np.isin(truth, (0.0, 1.0)).all() or np.any(
            (matrix < 0.0) | (matrix > 1.0)
        ):
            raise EnsembleError("binary_log_loss requires binary truth and probabilities")

    if matrix.shape[1] == 1:
        prediction = matrix[:, 0]
        if objective == "mse":
            value = float(np.mean((prediction - truth) ** 2))
        else:
            clipped = np.clip(prediction, 1e-12, 1.0 - 1e-12)
            value = float(
                -np.mean(
                    truth * np.log(clipped) + (1.0 - truth) * np.log(1.0 - clipped)
                )
            )
        return ConvexBlend(
            weights=(1.0,),
            objective=objective,
            training_rows=matrix.shape[0],
            objective_value=value,
        )

    def loss(weights: np.ndarray) -> float:
        prediction = matrix @ weights
        if objective == "mse":
            return float(np.mean((prediction - truth) ** 2))
        prediction = np.clip(prediction, 1e-12, 1.0 - 1e-12)
        return float(
            -np.mean(truth * np.log(prediction) + (1.0 - truth) * np.log(1.0 - prediction))
        )

    initial = np.repeat(1.0 / matrix.shape[1], matrix.shape[1])
    fitted = minimize(
        loss,
        initial,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * matrix.shape[1],
        constraints=[{"type": "eq", "fun": lambda weights: np.sum(weights) - 1.0}],
        options={"ftol": 1e-12, "maxiter": 1_000},
    )
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise EnsembleError(f"convex optimization failed: {fitted.message}")
    weights = np.clip(fitted.x, 0.0, 1.0)
    weights /= weights.sum()
    return ConvexBlend(
        weights=tuple(float(value) for value in weights),
        objective=objective,
        training_rows=matrix.shape[0],
        objective_value=loss(weights),
    )


def _fold_plan(
    fold_ids: np.ndarray,
    training_folds_by_validation_fold: Mapping[Any, Sequence[Any]] | None,
) -> dict[Any, tuple[Any, ...]]:
    folds = tuple(dict.fromkeys(fold_ids.tolist()))
    if len(folds) < 2:
        raise EnsembleError("cross-fitting requires at least two folds")
    if training_folds_by_validation_fold is None:
        return {fold: tuple(other for other in folds if other != fold) for fold in folds}
    if set(training_folds_by_validation_fold) != set(folds):
        raise EnsembleError("cross-fit plan must define every validation fold exactly once")
    plan: dict[Any, tuple[Any, ...]] = {}
    for fold in folds:
        training = tuple(training_folds_by_validation_fold[fold])
        if not training or fold in training or any(item not in folds for item in training):
            raise EnsembleError("cross-fit train folds must be known, non-empty, and disjoint")
        plan[fold] = training
    return plan


@dataclass(frozen=True)
class CrossFittedBlendResult:
    predictions: np.ndarray
    validation_fold_ids: tuple[Any, ...]
    training_folds_by_validation_fold: dict[Any, tuple[Any, ...]]
    weights_by_validation_fold: dict[Any, tuple[float, ...]]
    objective: str


def cross_fitted_convex_blend(
    base_oof_predictions: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[float] | np.ndarray,
    fold_ids: Sequence[Any] | np.ndarray,
    *,
    objective: str = "mse",
    training_folds_by_validation_fold: Mapping[Any, Sequence[Any]] | None = None,
) -> CrossFittedBlendResult:
    """Produce meta-predictions whose own labels never fit their blend weights.

    The optional plan permits a stricter chronological/nested policy.  Regardless of
    policy, overlap between a validation fold and its weight-training folds fails closed.
    """

    matrix = _matrix(base_oof_predictions, label="base_oof_predictions")
    truth = _target(target, matrix.shape[0])
    folds = np.asarray(fold_ids, dtype=object)
    if folds.ndim != 1 or folds.size != matrix.shape[0]:
        raise EnsembleError("fold_ids must align with prediction rows")
    plan = _fold_plan(folds, training_folds_by_validation_fold)
    output = np.full(matrix.shape[0], np.nan, dtype=np.float64)
    weights: dict[Any, tuple[float, ...]] = {}
    for validation_fold, training_folds in plan.items():
        validation_mask = folds == validation_fold
        training_mask = np.isin(folds, np.asarray(training_folds, dtype=object))
        if np.any(validation_mask & training_mask) or not validation_mask.any() or not training_mask.any():
            raise EnsembleError("cross-fit row membership is invalid")
        fitted = fit_convex_blend(
            matrix[training_mask], truth[training_mask], objective=objective
        )
        output[validation_mask] = fitted.predict(matrix[validation_mask])
        weights[validation_fold] = fitted.weights
    if not np.isfinite(output).all():
        raise EnsembleError("not every row received one cross-fitted prediction")
    output.setflags(write=False)
    return CrossFittedBlendResult(
        predictions=output,
        validation_fold_ids=tuple(dict.fromkeys(folds.tolist())),
        training_folds_by_validation_fold=plan,
        weights_by_validation_fold=weights,
        objective=objective,
    )


@dataclass(frozen=True)
class CrossFittedMetaResult:
    predictions: np.ndarray
    training_rows_by_validation_fold: dict[Any, int]
    training_folds_by_validation_fold: dict[Any, tuple[Any, ...]]


def cross_fitted_meta_predictions(
    meta_features: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[float] | np.ndarray,
    fold_ids: Sequence[Any] | np.ndarray,
    *,
    estimator_factory: Callable[[], Any],
    prediction_method: str = "predict",
    training_folds_by_validation_fold: Mapping[Any, Sequence[Any]] | None = None,
) -> CrossFittedMetaResult:
    """Generic genuine cross-fit helper for a bounded second-level stacker.

    A fresh estimator is created for every validation fold. ``predict_proba`` selects
    the positive-class column; other methods must return a one-dimensional vector.
    """

    features = _matrix(meta_features, label="meta_features")
    truth = _target(target, features.shape[0])
    folds = np.asarray(fold_ids, dtype=object)
    if folds.ndim != 1 or folds.size != features.shape[0]:
        raise EnsembleError("fold_ids must align with meta-feature rows")
    plan = _fold_plan(folds, training_folds_by_validation_fold)
    output = np.full(features.shape[0], np.nan, dtype=np.float64)
    counts: dict[Any, int] = {}
    estimators: list[Any] = []
    for validation_fold, training_folds in plan.items():
        validation_mask = folds == validation_fold
        training_mask = np.isin(folds, np.asarray(training_folds, dtype=object))
        if np.any(validation_mask & training_mask):
            raise EnsembleError("stacker training rows overlap validation rows")
        estimator = estimator_factory()
        if any(estimator is previous for previous in estimators):
            raise EnsembleError("estimator_factory must return a fresh estimator per fold")
        estimators.append(estimator)
        estimator.fit(features[training_mask], truth[training_mask])
        method = getattr(estimator, prediction_method, None)
        if not callable(method):
            raise EnsembleError(f"estimator does not provide {prediction_method}")
        prediction = np.asarray(method(features[validation_mask]), dtype=np.float64)
        if prediction_method == "predict_proba":
            if prediction.ndim != 2 or prediction.shape[1] != 2:
                raise EnsembleError("predict_proba must return exactly two class columns")
            prediction = prediction[:, 1]
        if prediction.ndim != 1 or prediction.size != int(validation_mask.sum()):
            raise EnsembleError("stacker returned an invalid prediction shape")
        output[validation_mask] = prediction
        counts[validation_fold] = int(training_mask.sum())
    if not np.isfinite(output).all():
        raise EnsembleError("not every row received one cross-fitted meta-prediction")
    output.setflags(write=False)
    return CrossFittedMetaResult(
        predictions=output,
        training_rows_by_validation_fold=counts,
        training_folds_by_validation_fold=plan,
    )
