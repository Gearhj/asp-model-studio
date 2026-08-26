"""Fixed ensemble primitives for the Phase 7B4 recent-state study.

The functions in this module are deliberately data-source agnostic.  They accept
already-governed, row-aligned probability and reliability arrays; they never read
Bronze, Silver, Gold, or model-registry state.  Development OOF fitting is kept
explicit so a caller cannot accidentally present validation labels as an
optimization input.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from ..sports_modeling.bootstrap import game_cluster_bootstrap
from ..sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    require_frozen_class_order,
    validate_probability_matrix,
)


SCHEMA_VERSION = "MLB_GOLD_RECENT_STATE_ENSEMBLE_PRIMITIVES_V1"
RANDOM_SEED = 20_260_824
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 20_260_824
NUMERICAL_EPSILON = 1e-15
STACKER_LOG_EPSILON = 1e-12

DIRECT_MODEL = "DIRECT_MODEL"
LONG_TERM_STATE = "LONG_TERM_STATE"
RECENT_14_DAY_STATE = "RECENT_14_DAY_STATE"
RECENT_42_DAY_STATE = "RECENT_42_DAY_STATE"
DECAY_180_DAY_STATE = "DECAY_180_DAY_STATE"
DECAY_365_DAY_STATE = "DECAY_365_DAY_STATE"
CLUSTER_MATCHUP = "CLUSTER_MATCHUP"
SHRUNK_EXACT_BVP = "SHRUNK_EXACT_BVP"
RECENT_RESIDUAL_FORM = "RECENT_RESIDUAL_FORM"

COMPONENT_ORDER: tuple[str, ...] = (
    DIRECT_MODEL,
    LONG_TERM_STATE,
    RECENT_14_DAY_STATE,
    RECENT_42_DAY_STATE,
    DECAY_180_DAY_STATE,
    DECAY_365_DAY_STATE,
    CLUSTER_MATCHUP,
    SHRUNK_EXACT_BVP,
    RECENT_RESIDUAL_FORM,
)

EMPIRICAL_COMPONENTS: tuple[str, ...] = COMPONENT_ORDER[1:]

FIXED_ENSEMBLE_MEMBERS: Mapping[str, tuple[str, ...]] = {
    "E1": (DIRECT_MODEL, RECENT_14_DAY_STATE),
    "E2": (DIRECT_MODEL, RECENT_14_DAY_STATE, RECENT_42_DAY_STATE),
    "E3": (
        DIRECT_MODEL,
        LONG_TERM_STATE,
        RECENT_14_DAY_STATE,
        RECENT_42_DAY_STATE,
    ),
    "E4": (DIRECT_MODEL, DECAY_180_DAY_STATE, DECAY_365_DAY_STATE),
    "E5": (DIRECT_MODEL, CLUSTER_MATCHUP),
    "E6": (DIRECT_MODEL, CLUSTER_MATCHUP, SHRUNK_EXACT_BVP),
    "E7": (DIRECT_MODEL, RECENT_RESIDUAL_FORM),
    "E8": COMPONENT_ORDER,
}

RELIABILITY_FIELDS: tuple[str, ...] = (
    "observationCount",
    "effectiveSampleSize",
    "missingHistoryFlag",
    "daysSincePriorAppearance",
    "entropy",
    "deviationFromLongTerm",
)

_RELIABILITY_FEATURE_SUFFIX: Mapping[str, str] = {
    "observationCount": "observation_count",
    "effectiveSampleSize": "effective_sample_size",
    "missingHistoryFlag": "missing_history",
    "daysSincePriorAppearance": "days_since_prior_appearance",
    "entropy": "entropy",
    "deviationFromLongTerm": "deviation_from_long_term",
}

STACKER_CONFIG: Mapping[str, Any] = {
    "estimator": "sklearn.linear_model.LogisticRegression",
    "C": 0.1,
    "penalty": "l2",
    "solver": "lbfgs",
    "maxIter": 5_000,
    "tol": 1e-6,
    "fitIntercept": True,
    "randomState": RANDOM_SEED,
    "preprocessing": "StandardScaler",
    "selectionCriterion": "DEVELOPMENT_OOF_LOG_LOSS_ONLY",
}


class RecentStateEnsembleError(RuntimeError):
    """Raised when a fixed temporal, probability, or fitting contract differs."""


@dataclass(frozen=True)
class RollingOriginFold:
    """One immutable development-only rolling-origin block."""

    fold_id: str
    train_end: str
    validation_start: str
    validation_end: str

    def record(self) -> dict[str, Any]:
        return {
            "foldId": self.fold_id,
            "trainRule": f"game_date <= {self.train_end}",
            "trainEnd": self.train_end,
            "validationStart": self.validation_start,
            "validationEnd": self.validation_end,
            "uses2024": False,
        }


ROLLING_ORIGIN_FOLDS: tuple[RollingOriginFold, ...] = (
    RollingOriginFold("FOLD_1", "2022-04-30", "2022-05-01", "2022-06-30"),
    RollingOriginFold("FOLD_2", "2022-06-30", "2022-07-01", "2022-08-31"),
    RollingOriginFold("FOLD_3", "2022-08-31", "2022-09-01", "2022-12-31"),
    RollingOriginFold("FOLD_4", "2023-04-30", "2023-05-01", "2023-06-30"),
    RollingOriginFold("FOLD_5", "2023-06-30", "2023-07-01", "2023-08-31"),
    RollingOriginFold("FOLD_6", "2023-08-31", "2023-09-01", "2023-12-31"),
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def rolling_origin_folds() -> tuple[RollingOriginFold, ...]:
    """Return the six and only six authorized development validation blocks."""

    return ROLLING_ORIGIN_FOLDS


def _dates(values: Any) -> pd.DatetimeIndex:
    source = values
    if isinstance(values, pd.DataFrame):
        if "game_date" not in values.columns:
            raise ValueError("date frame must contain game_date")
        source = values["game_date"]
    elif isinstance(values, pd.Series):
        source = values
    raw = np.asarray(source)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError("game dates must be a non-empty one-dimensional sequence")
    parsed = pd.to_datetime(raw, format="%Y-%m-%d", errors="raise")
    dates = pd.DatetimeIndex(parsed).normalize()
    if dates.hasnans:
        raise ValueError("game dates must not contain missing values")
    years = set(dates.year.tolist())
    if not years.issubset({2021, 2022, 2023}):
        raise RecentStateEnsembleError(
            "rolling-origin fitting accepts development seasons 2021--2023 only"
        )
    return dates


def rolling_origin_fold_masks(
    game_dates: Any,
) -> list[tuple[RollingOriginFold, np.ndarray, np.ndarray]]:
    """Build exact train/validation masks and enforce strict temporal ordering."""

    dates = _dates(game_dates)
    output: list[tuple[RollingOriginFold, np.ndarray, np.ndarray]] = []
    validation_union = np.zeros(len(dates), dtype=bool)
    for fold in ROLLING_ORIGIN_FOLDS:
        train_end = pd.Timestamp(fold.train_end)
        validation_start = pd.Timestamp(fold.validation_start)
        validation_end = pd.Timestamp(fold.validation_end)
        training = np.asarray(dates <= train_end, dtype=bool)
        validation = np.asarray(
            (dates >= validation_start) & (dates <= validation_end), dtype=bool
        )
        if not training.any() or not validation.any():
            raise RecentStateEnsembleError(f"{fold.fold_id} has an empty split")
        if validation_union[validation].any():
            raise RecentStateEnsembleError("rolling validation blocks overlap")
        if dates[training].max() >= dates[validation].min():
            raise RecentStateEnsembleError(
                f"{fold.fold_id} training is not strictly earlier than validation"
            )
        validation_union |= validation
        training.setflags(write=False)
        validation.setflags(write=False)
        output.append((fold, training, validation))
    return output


def fixed_ensemble_definitions() -> dict[str, dict[str, Any]]:
    """Return JSON-safe fixed E1--E8 membership and equal weights."""

    return {
        ensemble_id: {
            "ensembleId": ensemble_id,
            "method": "FIXED_EQUAL_WEIGHT_PROBABILITY_AVERAGE",
            "memberIds": list(members),
            "weights": {member: 1.0 / len(members) for member in members},
            "fitted": False,
        }
        for ensemble_id, members in FIXED_ENSEMBLE_MEMBERS.items()
    }


def _validated_components(
    probabilities: Mapping[str, Any],
    *,
    required: Sequence[str] | None = None,
) -> dict[str, np.ndarray]:
    if not isinstance(probabilities, Mapping) or not probabilities:
        raise TypeError("component probabilities must be a non-empty mapping")
    names = tuple(required) if required is not None else tuple(probabilities)
    missing = [name for name in names if name not in probabilities]
    if missing:
        raise ValueError(f"component probabilities are missing: {missing}")
    unexpected = sorted(set(probabilities) - set(names)) if required is not None else []
    if unexpected:
        raise ValueError(f"unexpected component probabilities: {unexpected}")
    matrices = {
        str(name): validate_probability_matrix(
            probabilities[name], class_order=PA_CLASS_ORDER
        )
        for name in names
    }
    row_counts = {matrix.shape[0] for matrix in matrices.values()}
    if len(row_counts) != 1:
        raise ValueError("component probabilities must be row-aligned")
    return matrices


def equal_weight_probability_ensemble(
    probabilities: Mapping[str, Any],
    members: Sequence[str],
) -> np.ndarray:
    """Average an explicitly ordered non-empty member set without fitting."""

    ordered = tuple(members)
    if not ordered or len(set(ordered)) != len(ordered):
        raise ValueError("ensemble members must be non-empty and unique")
    missing = [name for name in ordered if name not in probabilities]
    if missing:
        raise ValueError(f"ensemble members are missing: {missing}")
    matrices = _validated_components(
        {name: probabilities[name] for name in ordered}, required=ordered
    )
    return _equal_weight_from_validated(matrices, ordered)


def _equal_weight_from_validated(
    matrices: Mapping[str, np.ndarray], members: Sequence[str]
) -> np.ndarray:
    ordered = tuple(members)
    result = np.mean(
        np.stack([matrices[name] for name in ordered], axis=0), axis=0, dtype=np.float64
    )
    result = validate_probability_matrix(result, class_order=PA_CLASS_ORDER)
    result.setflags(write=False)
    return result


def build_fixed_ensembles(probabilities: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Build exactly E1--E8 from all nine fixed component matrices."""

    matrices = _validated_components(probabilities, required=COMPONENT_ORDER)
    return {
        ensemble_id: _equal_weight_from_validated(matrices, members)
        for ensemble_id, members in FIXED_ENSEMBLE_MEMBERS.items()
    }


@dataclass(frozen=True)
class FittedConvexBlend:
    """A development-OOF-fitted static nonnegative probability blend."""

    component_ids: tuple[str, ...]
    weights: tuple[float, ...]
    optimizer_record: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.component_ids or len(set(self.component_ids)) != len(
            self.component_ids
        ):
            raise ValueError("convex blend component IDs must be non-empty and unique")
        weights = np.asarray(self.weights, dtype=np.float64)
        if (
            weights.shape != (len(self.component_ids),)
            or not np.isfinite(weights).all()
        ):
            raise ValueError("convex blend weights are malformed")
        if np.any(weights < -1e-12) or not np.isclose(weights.sum(), 1.0, atol=1e-10):
            raise ValueError("convex blend weights must be nonnegative and sum to one")

    def predict_proba(self, probabilities: Mapping[str, Any]) -> np.ndarray:
        matrices = _validated_components(probabilities, required=self.component_ids)
        stacked = np.stack([matrices[name] for name in self.component_ids], axis=0)
        weights = np.asarray(self.weights, dtype=np.float64)
        result = np.tensordot(weights, stacked, axes=(0, 0))
        result = validate_probability_matrix(result, class_order=PA_CLASS_ORDER)
        result.setflags(write=False)
        return result

    def record(self) -> dict[str, Any]:
        return {
            "ensembleId": "E9",
            "label": "OOF_OPTIMIZED_CONVEX_BLEND",
            "method": "STATIC_NONNEGATIVE_CONVEX_PROBABILITY_BLEND",
            "memberIds": list(self.component_ids),
            "weights": {
                name: float(weight)
                for name, weight in zip(self.component_ids, self.weights, strict=True)
            },
            "weightSum": float(math.fsum(self.weights)),
            "fitPopulation": "DEVELOPMENT_ROLLING_ORIGIN_OOF_ONLY",
            "selectionCriterion": "DEVELOPMENT_OOF_LOG_LOSS_ONLY",
            "uses2024": False,
            "optimizer": _json_safe(self.optimizer_record),
        }


def fit_convex_blend(
    labels: Any,
    oof_probabilities: Mapping[str, Any],
    *,
    component_order: Sequence[str] = COMPONENT_ORDER,
) -> FittedConvexBlend:
    """Fit E9 once by constrained development-OOF multiclass log loss."""

    order = tuple(component_order)
    if not order or len(set(order)) != len(order):
        raise ValueError("component_order must be non-empty and unique")
    matrices = _validated_components(oof_probabilities, required=order)
    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    row_count = next(iter(matrices.values())).shape[0]
    if encoded.size != row_count:
        raise ValueError("OOF labels and component probabilities are not row-aligned")
    truth = np.stack(
        [matrices[name][np.arange(row_count), encoded] for name in order], axis=1
    )

    def objective(weights: np.ndarray) -> float:
        selected = np.clip(truth @ weights, NUMERICAL_EPSILON, 1.0)
        return -float(np.mean(np.log(selected)))

    def gradient(weights: np.ndarray) -> np.ndarray:
        selected = np.clip(truth @ weights, NUMERICAL_EPSILON, 1.0)
        return -np.mean(truth / selected[:, None], axis=0)

    initial = np.full(len(order), 1.0 / len(order), dtype=np.float64)
    fitted = minimize(
        objective,
        initial,
        jac=gradient,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * len(order),
        constraints={
            "type": "eq",
            "fun": lambda weights: weights.sum() - 1.0,
            "jac": lambda weights: np.ones_like(weights),
        },
        options={"ftol": 1e-12, "maxiter": 500, "disp": False},
    )
    if not fitted.success or not np.isfinite(fitted.fun):
        raise RecentStateEnsembleError(
            f"fixed convex optimization failed: {fitted.status} {fitted.message}"
        )
    weights = np.asarray(fitted.x, dtype=np.float64)
    weights[np.abs(weights) < 1e-14] = 0.0
    if np.any(weights < -1e-12) or weights.sum() <= 0.0:
        raise RecentStateEnsembleError(
            "fixed convex optimization returned invalid weights"
        )
    weights = np.maximum(weights, 0.0)
    weights /= weights.sum()
    artifact = FittedConvexBlend(
        component_ids=order,
        weights=tuple(float(value) for value in weights),
        optimizer_record={
            "algorithm": "SCIPY_SLSQP",
            "objective": "MEAN_MULTICLASS_LOG_LOSS",
            "success": True,
            "status": int(fitted.status),
            "iterations": int(fitted.nit),
            "functionEvaluations": int(fitted.nfev),
            "gradientEvaluations": int(fitted.njev),
            "oofRows": int(row_count),
            "objectiveValue": float(objective(weights)),
            "initialWeights": initial.tolist(),
            "bounds": "EACH_WEIGHT_IN_[0,1]",
            "constraint": "SUM_WEIGHTS_EQUALS_ONE",
        },
    )
    # Exercise the full matrix path, not only the true-class optimization slice.
    artifact.predict_proba(matrices)
    return artifact


def _one_dimensional_numeric(
    values: Any, *, label: str, rows: int, allow_missing: bool = False
) -> np.ndarray:
    raw = np.asarray(values)
    if raw.dtype.kind not in "fiub":
        raise TypeError(f"{label} must be numeric or boolean")
    result = np.asarray(raw, dtype=np.float64)
    if result.ndim != 1 or result.size != rows:
        raise ValueError(f"{label} must be one-dimensional and row-aligned")
    if allow_missing:
        if np.isinf(result).any():
            raise ValueError(f"{label} must not contain infinite values")
        result = np.nan_to_num(result, nan=0.0)
    elif not np.isfinite(result).all():
        raise ValueError(f"{label} must contain only finite values")
    return result


def _reliability_frame(
    reliability_inputs: pd.DataFrame | Mapping[str, Any],
    *,
    rows: int,
) -> pd.DataFrame:
    """Canonicalize only the six authorized reliability inputs per component."""

    if isinstance(reliability_inputs, pd.DataFrame):
        frame = reliability_inputs.copy(deep=False)
        if len(frame) != rows:
            raise ValueError("reliability frame is not row-aligned")
        allowed = {
            f"{component}__{field}"
            for component in EMPIRICAL_COMPONENTS
            for field in RELIABILITY_FIELDS
        }
        if set(frame.columns) != allowed:
            missing = sorted(allowed - set(frame.columns))
            unexpected = sorted(set(frame.columns) - allowed)
            raise ValueError(
                "reliability frame differs from the fixed contract; "
                f"missing={missing}, unexpected={unexpected}"
            )
        output = {}
        for component in EMPIRICAL_COMPONENTS:
            for field in RELIABILITY_FIELDS:
                column = f"{component}__{field}"
                output[column] = _one_dimensional_numeric(
                    frame[column].to_numpy(copy=False),
                    label=column,
                    rows=rows,
                    allow_missing=field == "daysSincePriorAppearance",
                )
        return pd.DataFrame(output, copy=False)

    if not isinstance(reliability_inputs, Mapping):
        raise TypeError("reliability inputs must be a DataFrame or mapping")
    output: dict[str, np.ndarray] = {}
    # Accept either a flat canonical mapping or component -> field -> vector.
    if all(isinstance(value, Mapping) for value in reliability_inputs.values()):
        if set(reliability_inputs) != set(EMPIRICAL_COMPONENTS):
            missing = sorted(set(EMPIRICAL_COMPONENTS) - set(reliability_inputs))
            unexpected_components = sorted(
                set(reliability_inputs) - set(EMPIRICAL_COMPONENTS)
            )
            raise ValueError(
                "reliability component set differs from the fixed contract; "
                f"missing={missing}, unexpected={unexpected_components}"
            )
        for component in EMPIRICAL_COMPONENTS:
            fields = reliability_inputs[component]
            if not isinstance(fields, Mapping):
                raise TypeError(f"reliability inputs for {component} must be a mapping")
            if set(fields) != set(RELIABILITY_FIELDS):
                missing = sorted(set(RELIABILITY_FIELDS) - set(fields))
                unexpected_fields = sorted(set(fields) - set(RELIABILITY_FIELDS))
                raise ValueError(
                    f"reliability fields for {component} differ; "
                    f"missing={missing}, unexpected={unexpected_fields}"
                )
            for field in RELIABILITY_FIELDS:
                name = f"{component}__{field}"
                output[name] = _one_dimensional_numeric(
                    fields[field],
                    label=name,
                    rows=rows,
                    allow_missing=field == "daysSincePriorAppearance",
                )
    else:
        allowed = {
            f"{component}__{field}"
            for component in EMPIRICAL_COMPONENTS
            for field in RELIABILITY_FIELDS
        }
        if set(reliability_inputs) != allowed:
            missing = sorted(allowed - set(reliability_inputs))
            unexpected = sorted(set(reliability_inputs) - allowed)
            raise ValueError(
                "reliability fields differ from the fixed contract; "
                f"missing={missing}, unexpected={unexpected}"
            )
        for component in EMPIRICAL_COMPONENTS:
            for field in RELIABILITY_FIELDS:
                name = f"{component}__{field}"
                output[name] = _one_dimensional_numeric(
                    reliability_inputs[name],
                    label=name,
                    rows=rows,
                    allow_missing=field == "daysSincePriorAppearance",
                )
    return pd.DataFrame(output, copy=False)


def probability_entropy(probabilities: Any) -> np.ndarray:
    matrix = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
    clipped = np.clip(matrix, NUMERICAL_EPSILON, 1.0)
    return -np.sum(matrix * np.log(clipped), axis=1)


def component_disagreement(first: Any, second: Any) -> np.ndarray:
    """Return total-variation distance in [0, 1] for each row."""

    left = validate_probability_matrix(first, class_order=PA_CLASS_ORDER)
    right = validate_probability_matrix(second, class_order=PA_CLASS_ORDER)
    if left.shape != right.shape:
        raise ValueError("disagreement matrices are not row-aligned")
    return 0.5 * np.abs(left - right).sum(axis=1)


def build_stacker_features(
    component_probabilities: Mapping[str, Any],
    reliability_inputs: pd.DataFrame | Mapping[str, Any],
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Build the one fixed E10 meta-feature architecture.

    It contains all component log probabilities, the supplied canonical
    reliability fields, component-versus-Direct disagreement magnitude and
    direction, and recent-minus-long-term magnitude and direction.
    """

    matrices = _validated_components(component_probabilities, required=COMPONENT_ORDER)
    rows = matrices[DIRECT_MODEL].shape[0]
    blocks: list[np.ndarray] = []
    names: list[str] = []
    reliability = _reliability_frame(reliability_inputs, rows=rows)
    for component in COMPONENT_ORDER:
        clipped = np.clip(matrices[component], STACKER_LOG_EPSILON, 1.0)
        blocks.append(np.log(clipped))
        names.extend(
            f"{component}__log_probability__{class_name}"
            for class_name in PA_CLASS_ORDER
        )
        if component != DIRECT_MODEL:
            for field in RELIABILITY_FIELDS:
                column = f"{component}__{field}"
                blocks.append(
                    reliability[column].to_numpy(dtype=np.float64, copy=True)[:, None]
                )
                names.append(f"{component}__{_RELIABILITY_FEATURE_SUFFIX[field]}")
            blocks.append(
                component_disagreement(matrices[component], matrices[DIRECT_MODEL])[
                    :, None
                ]
            )
            names.append(f"{component}__direct_total_variation_disagreement")

    long_term = matrices[LONG_TERM_STATE]
    for recent in (
        RECENT_14_DAY_STATE,
        RECENT_42_DAY_STATE,
        RECENT_RESIDUAL_FORM,
    ):
        delta = matrices[recent] - long_term
        blocks.append(delta)
        names.extend(
            f"{recent}__minus_long_term__{class_name}" for class_name in PA_CLASS_ORDER
        )

    matrix = np.concatenate(blocks, axis=1)
    if matrix.shape != (rows, len(names)) or not np.isfinite(matrix).all():
        raise RecentStateEnsembleError("stacker meta-feature matrix is malformed")
    if len(set(names)) != len(names):
        raise RecentStateEnsembleError("stacker meta-feature names are not unique")
    matrix.setflags(write=False)
    return matrix, tuple(names)


@dataclass
class FittedReliabilityGatedStacker:
    """The one fixed regularized multinomial Logistic E10 stacker."""

    scaler: StandardScaler
    estimator: LogisticRegression
    feature_names: tuple[str, ...]
    component_ids: tuple[str, ...] = COMPONENT_ORDER

    def predict_proba(
        self,
        component_probabilities: Mapping[str, Any],
        reliability_inputs: pd.DataFrame | Mapping[str, Any],
    ) -> np.ndarray:
        matrix, names = build_stacker_features(
            component_probabilities, reliability_inputs
        )
        if names != self.feature_names:
            raise RecentStateEnsembleError(
                "stacker score feature contract differs from fit"
            )
        transformed = self.scaler.transform(matrix)
        raw = self.estimator.predict_proba(transformed)
        classes = np.asarray(self.estimator.classes_, dtype=np.int64)
        expected = np.arange(len(PA_CLASS_ORDER), dtype=np.int64)
        if not np.array_equal(classes, expected):
            raise RecentStateEnsembleError("stacker fitted class order differs")
        result = validate_probability_matrix(raw, class_order=PA_CLASS_ORDER)
        result.setflags(write=False)
        return result

    def coefficient_importance(self) -> dict[str, Any]:
        """Return normalized component-level coefficient magnitude for charting."""

        coefficients = np.asarray(self.estimator.coef_, dtype=np.float64)
        if coefficients.shape[1] != len(self.feature_names):
            raise RecentStateEnsembleError("stacker coefficient shape differs")
        feature_importance = np.mean(np.abs(coefficients), axis=0)
        grouped = {name: 0.0 for name in self.component_ids}
        other = 0.0
        for feature, value in zip(self.feature_names, feature_importance, strict=True):
            matched = [name for name in self.component_ids if name in feature]
            if matched:
                share = float(value) / len(matched)
                for component in matched:
                    grouped[component] += share
            else:
                other += float(value)
        denominator = math.fsum(grouped.values()) + other
        normalized = {
            name: (float(value / denominator) if denominator > 0.0 else 0.0)
            for name, value in grouped.items()
        }
        return {
            "definition": "NORMALIZED_MEAN_ABSOLUTE_MULTINOMIAL_COEFFICIENT_MAGNITUDE",
            "notProbabilityWeights": True,
            "componentImportance": normalized,
            "otherFeatureImportance": (
                float(other / denominator) if denominator > 0.0 else 0.0
            ),
            "normalizationSum": float(
                math.fsum(normalized.values())
                + (other / denominator if denominator > 0.0 else 0.0)
            ),
        }

    def record(self) -> dict[str, Any]:
        return {
            "ensembleId": "E10",
            "label": "RELIABILITY_GATED_RESIDUAL_STACKER",
            "method": "REGULARIZED_MULTINOMIAL_LOGISTIC_STACKER",
            "configuration": dict(STACKER_CONFIG),
            "memberIds": list(self.component_ids),
            "featureCount": len(self.feature_names),
            "featureNames": list(self.feature_names),
            "estimatorIterations": np.asarray(
                self.estimator.n_iter_, dtype=np.int64
            ).tolist(),
            "convergenceWarnings": [],
            "converged": True,
            "fitPopulation": "DEVELOPMENT_ROLLING_ORIGIN_OOF_ONLY",
            "selectionCriterion": "DEVELOPMENT_OOF_LOG_LOSS_ONLY",
            "uses2024": False,
            "coefficientImportance": self.coefficient_importance(),
        }


def fit_reliability_gated_stacker(
    labels: Any,
    oof_component_probabilities: Mapping[str, Any],
    oof_reliability_inputs: pd.DataFrame | Mapping[str, Any],
) -> FittedReliabilityGatedStacker:
    """Fit the fixed E10 architecture using development OOF rows only."""

    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    features, names = build_stacker_features(
        oof_component_probabilities, oof_reliability_inputs
    )
    if encoded.size != features.shape[0]:
        raise ValueError("OOF labels and stacker features are not row-aligned")
    if not np.array_equal(np.unique(encoded), np.arange(len(PA_CLASS_ORDER))):
        raise RecentStateEnsembleError(
            "stacker OOF labels do not contain all frozen classes"
        )
    scaler = StandardScaler(copy=True, with_mean=True, with_std=True)
    transformed = scaler.fit_transform(features)
    estimator = LogisticRegression(
        C=float(STACKER_CONFIG["C"]),
        penalty=str(STACKER_CONFIG["penalty"]),
        solver=str(STACKER_CONFIG["solver"]),
        max_iter=int(STACKER_CONFIG["maxIter"]),
        tol=float(STACKER_CONFIG["tol"]),
        fit_intercept=bool(STACKER_CONFIG["fitIntercept"]),
        random_state=int(STACKER_CONFIG["randomState"]),
    )
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        estimator.fit(transformed, encoded)
    convergence = [
        item for item in observed if issubclass(item.category, ConvergenceWarning)
    ]
    if convergence:
        raise RecentStateEnsembleError(
            "stacker failed to converge: "
            + "; ".join(str(item.message) for item in convergence)
        )
    if not np.array_equal(
        np.asarray(estimator.classes_, dtype=np.int64),
        np.arange(len(PA_CLASS_ORDER), dtype=np.int64),
    ):
        raise RecentStateEnsembleError("stacker fitted class order differs")
    artifact = FittedReliabilityGatedStacker(
        scaler=scaler,
        estimator=estimator,
        feature_names=names,
    )
    artifact.predict_proba(oof_component_probabilities, oof_reliability_inputs)
    return artifact


def compact_multiclass_metrics(labels: Any, probabilities: Any) -> dict[str, Any]:
    """Return the fixed leaderboard metric subset as JSON-native scalars."""

    metrics = evaluate_multiclass(
        labels, probabilities, class_order=require_frozen_class_order(PA_CLASS_ORDER)
    )
    return {
        "rowCount": int(metrics["rowCount"]),
        "classOrder": list(metrics["classOrder"]),
        "logLoss": float(metrics["logLoss"]),
        "summedBrier": float(metrics["brierScore"]),
        "ece": float(metrics["topLabelEce"]),
        "accuracy": float(metrics["top1Accuracy"]),
        "macroF1": float(metrics["macroF1"]),
    }


def _coverage_record(
    rows: int,
    coverage_mask: Any | None,
    effective_sample_size: Any | None,
) -> dict[str, Any]:
    if coverage_mask is None:
        mask = np.ones(rows, dtype=bool)
    else:
        raw = np.asarray(coverage_mask)
        if raw.ndim != 1 or raw.size != rows or raw.dtype.kind != "b":
            raise ValueError("coverage mask must be a row-aligned boolean vector")
        mask = raw.astype(bool, copy=False)
    if effective_sample_size is None:
        effective = None
    else:
        effective = _one_dimensional_numeric(
            effective_sample_size, label="effective sample size", rows=rows
        )
        if np.any(effective < 0.0):
            raise ValueError("effective sample size must be nonnegative")
    covered = int(mask.sum())
    observed = effective[mask] if effective is not None and covered else np.asarray([])
    return {
        "coveredRows": covered,
        "coverage": float(covered / rows),
        "effectiveSampleSizeMean": float(observed.mean()) if observed.size else None,
        "effectiveSampleSizeMedian": (
            float(np.median(observed)) if observed.size else None
        ),
    }


def candidate_record(
    candidate_id: str,
    labels: Any,
    probabilities: Any,
    *,
    candidate_type: str,
    members: Sequence[str] | None = None,
    coverage_mask: Any | None = None,
    effective_sample_size: Any | None = None,
) -> dict[str, Any]:
    """Evaluate one OOF component or ensemble with the fixed metric contract."""

    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("candidate_id must be a non-empty string")
    matrix = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
    metrics = compact_multiclass_metrics(labels, matrix)
    reliability = _coverage_record(
        matrix.shape[0], coverage_mask, effective_sample_size
    )
    return {
        "candidateId": candidate_id,
        "candidateType": candidate_type,
        "status": "SUCCESS",
        "evaluationPopulation": "DEVELOPMENT_ROLLING_ORIGIN_OOF",
        "selectionCriterion": "DEVELOPMENT_OOF_LOG_LOSS_ONLY",
        "uses2024": False,
        "memberIds": list(members or (candidate_id,)),
        "metrics": metrics,
        **reliability,
    }


def component_leaderboard(
    labels: Any,
    probabilities: Mapping[str, Any],
    *,
    coverage_masks: Mapping[str, Any] | None = None,
    effective_sample_sizes: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate standalone components and sort by OOF log loss only."""

    matrices = _validated_components(probabilities)
    rows = [
        candidate_record(
            name,
            labels,
            matrix,
            candidate_type="STANDALONE_COMPONENT",
            coverage_mask=(coverage_masks or {}).get(name),
            effective_sample_size=(effective_sample_sizes or {}).get(name),
        )
        for name, matrix in matrices.items()
    ]
    return sorted(rows, key=lambda row: float(row["metrics"]["logLoss"]))


def ensemble_leaderboard(
    labels: Any,
    probabilities: Mapping[str, Any],
    *,
    definitions: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate ensemble predictions and sort by OOF log loss only."""

    matrices = _validated_components(probabilities)
    metadata = definitions or {}
    rows = [
        candidate_record(
            name,
            labels,
            matrix,
            candidate_type="ENSEMBLE",
            members=tuple((metadata.get(name) or {}).get("memberIds") or ()),
        )
        for name, matrix in matrices.items()
    ]
    return sorted(rows, key=lambda row: float(row["metrics"]["logLoss"]))


def select_oof_winner(
    leaderboard: Sequence[Mapping[str, Any]],
    *,
    exclude_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Select strictly by development OOF log loss; stable order resolves exact ties."""

    excluded = set(exclude_ids)
    eligible: list[tuple[int, Mapping[str, Any]]] = []
    for index, row in enumerate(leaderboard):
        if row.get("status") != "SUCCESS" or row.get("candidateId") in excluded:
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        value = metrics.get("logLoss")
        if not isinstance(
            value, (int, float, np.integer, np.floating)
        ) or not math.isfinite(float(value)):
            continue
        eligible.append((index, row))
    if not eligible:
        raise RecentStateEnsembleError("OOF leaderboard has no eligible candidates")
    _, winner = min(
        eligible, key=lambda item: (float(item[1]["metrics"]["logLoss"]), item[0])
    )
    result = _json_safe(winner)
    result["selectedBy"] = "MINIMUM_DEVELOPMENT_OOF_LOG_LOSS_ONLY"
    result["uses2024ForSelection"] = False
    return result


def compact_game_bootstrap(
    labels: Any,
    selected_probabilities: Any,
    direct_probabilities: Any,
    game_ids: Any,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return compact paired whole-game selected-minus-Direct evidence."""

    evidence = game_cluster_bootstrap(
        labels,
        selected_probabilities,
        direct_probabilities,
        game_ids,
        class_order=PA_CLASS_ORDER,
        n_resamples=n_resamples,
        seed=seed,
    )

    def compact(metric: str) -> dict[str, Any]:
        source = evidence[metric]
        replicates = np.asarray(source["replicateDifferences"], dtype=np.float64)
        if replicates.shape != (n_resamples,) or not np.isfinite(replicates).all():
            raise RecentStateEnsembleError("paired game bootstrap is incomplete")
        return {
            "pointEstimate": float(source["pointEstimate"]),
            "bootstrapMean": float(source["bootstrapMean"]),
            "bootstrapMedian": float(np.median(replicates)),
            "bootstrapStandardError": float(source["bootstrapStandardError"]),
            "confidenceInterval95": {
                "lower": float(source["percentileInterval"]["lower"]),
                "upper": float(source["percentileInterval"]["upper"]),
            },
            "probabilitySelectedBetter": float(source["probabilitySelectedBetter"]),
            "replicateSha256": hashlib.sha256(
                np.ascontiguousarray(replicates, dtype=np.float64).tobytes()
            ).hexdigest(),
        }

    return {
        "schemaVersion": evidence["schemaVersion"],
        "differenceConvention": evidence["differenceConvention"],
        "resamplingUnit": evidence["resamplingUnit"],
        "rowsSampledIndependently": evidence["rowsSampledIndependently"],
        "rowCount": int(evidence["rowCount"]),
        "gameCount": int(evidence["clusterCount"]),
        "resampleCount": int(evidence["resampleCount"]),
        "seed": int(evidence["seed"]),
        "logLossDifference": compact("logLossDifference"),
        "summedBrierDifference": compact("brierScoreDifference"),
    }


def _slice_row(
    *,
    group: str,
    name: str,
    mask: np.ndarray,
    labels: np.ndarray,
    direct: np.ndarray,
    alternatives: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    count = int(mask.sum())
    row: dict[str, Any] = {
        "sliceGroup": group,
        "slice": name,
        "rows": count,
        "status": "COMPLETE" if count else "EMPTY_NOT_ESTIMABLE",
        "candidates": {},
    }
    if not count:
        return row
    direct_metrics = compact_multiclass_metrics(labels[mask], direct[mask])
    row["candidates"][DIRECT_MODEL] = {
        **direct_metrics,
        "logLossDifferenceVsDirect": 0.0,
    }
    for candidate_id, matrix in alternatives.items():
        metrics = compact_multiclass_metrics(labels[mask], matrix[mask])
        row["candidates"][candidate_id] = {
            **metrics,
            "logLossDifferenceVsDirect": float(
                metrics["logLoss"] - direct_metrics["logLoss"]
            ),
        }
    return row


def bounded_slice_evaluation(
    *,
    labels: Any,
    direct_probabilities: Any,
    alternative_probabilities: Mapping[str, Any],
    game_dates: Any,
    recent_batter_sample_size: Any,
    recent_pitcher_sample_size: Any,
    batter_ids: Any,
    pitcher_ids: Any,
    development_batter_ids: Any,
    development_pitcher_ids: Any,
    disagreement: Any,
) -> list[dict[str, Any]]:
    """Evaluate exactly the bounded Phase 7B4 robustness slice inventory.

    Numeric low/high groups use a deterministic validation-population median;
    the resulting thresholds are included in every affected slice name.
    """

    direct = validate_probability_matrix(
        direct_probabilities, class_order=PA_CLASS_ORDER
    )
    alternatives = _validated_components(alternative_probabilities)
    rows = direct.shape[0]
    if any(matrix.shape[0] != rows for matrix in alternatives.values()):
        raise ValueError("slice candidate probabilities are not row-aligned")
    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    if encoded.size != rows:
        raise ValueError("slice labels are not row-aligned")
    dates = pd.DatetimeIndex(
        pd.to_datetime(np.asarray(game_dates), errors="raise")
    ).normalize()
    if len(dates) != rows or not np.all(dates.year == 2024):
        raise RecentStateEnsembleError("slice dates must be row-aligned 2024 dates")
    batter_count = _one_dimensional_numeric(
        recent_batter_sample_size, label="recent batter sample size", rows=rows
    )
    pitcher_count = _one_dimensional_numeric(
        recent_pitcher_sample_size, label="recent pitcher sample size", rows=rows
    )
    disagreement_values = _one_dimensional_numeric(
        disagreement, label="component disagreement", rows=rows
    )
    if (
        np.any(batter_count < 0.0)
        or np.any(pitcher_count < 0.0)
        or np.any(disagreement_values < 0.0)
    ):
        raise ValueError("sample sizes and disagreement must be nonnegative")

    batter = np.asarray(batter_ids, dtype=object)
    pitcher = np.asarray(pitcher_ids, dtype=object)
    if batter.shape != (rows,) or pitcher.shape != (rows,):
        raise ValueError("player IDs must be one-dimensional and row-aligned")
    if any(
        value is None or not str(value).strip()
        for value in batter.tolist() + pitcher.tolist()
    ):
        raise ValueError("player IDs must not be missing")
    seen_batters = {str(value) for value in np.asarray(development_batter_ids).tolist()}
    seen_pitchers = {
        str(value) for value in np.asarray(development_pitcher_ids).tolist()
    }
    batter_seen = np.asarray(
        [str(value) in seen_batters for value in batter], dtype=bool
    )
    pitcher_seen = np.asarray(
        [str(value) in seen_pitchers for value in pitcher], dtype=bool
    )

    specifications: list[tuple[str, str, np.ndarray]] = []
    for month in sorted(set(dates.month.tolist())):
        specifications.append(("month", f"2024-{month:02d}", dates.month == month))

    for group, values in (
        ("recentBatterSampleSize", batter_count),
        ("recentPitcherSampleSize", pitcher_count),
        ("componentDisagreement", disagreement_values),
    ):
        threshold = float(np.median(values))
        specifications.extend(
            (
                (group, f"LOW_LE_{threshold:.12g}", values <= threshold),
                (group, f"HIGH_GT_{threshold:.12g}", values > threshold),
            )
        )
    for group, seen in (("batterSeen", batter_seen), ("pitcherSeen", pitcher_seen)):
        specifications.extend(
            (
                (group, "SEEN_IN_DEVELOPMENT", seen),
                (group, "UNSEEN_IN_DEVELOPMENT", ~seen),
            )
        )
    for class_index, class_name in enumerate(PA_CLASS_ORDER):
        specifications.append(("outcomeClass", class_name, encoded == class_index))

    return [
        _slice_row(
            group=group,
            name=name,
            mask=np.asarray(mask, dtype=bool),
            labels=encoded,
            direct=direct,
            alternatives=alternatives,
        )
        for group, name, mask in specifications
    ]


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CLUSTER_MATCHUP",
    "COMPONENT_ORDER",
    "DECAY_180_DAY_STATE",
    "DECAY_365_DAY_STATE",
    "DIRECT_MODEL",
    "EMPIRICAL_COMPONENTS",
    "FIXED_ENSEMBLE_MEMBERS",
    "FittedConvexBlend",
    "FittedReliabilityGatedStacker",
    "LONG_TERM_STATE",
    "RECENT_14_DAY_STATE",
    "RECENT_42_DAY_STATE",
    "RECENT_RESIDUAL_FORM",
    "RELIABILITY_FIELDS",
    "ROLLING_ORIGIN_FOLDS",
    "RollingOriginFold",
    "SCHEMA_VERSION",
    "SHRUNK_EXACT_BVP",
    "STACKER_CONFIG",
    "bounded_slice_evaluation",
    "build_fixed_ensembles",
    "build_stacker_features",
    "candidate_record",
    "compact_game_bootstrap",
    "compact_multiclass_metrics",
    "component_disagreement",
    "component_leaderboard",
    "ensemble_leaderboard",
    "equal_weight_probability_ensemble",
    "fit_convex_blend",
    "fit_reliability_gated_stacker",
    "fixed_ensemble_definitions",
    "probability_entropy",
    "rolling_origin_fold_masks",
    "rolling_origin_folds",
    "select_oof_winner",
]
