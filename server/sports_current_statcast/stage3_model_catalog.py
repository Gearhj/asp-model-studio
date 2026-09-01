"""Bounded supervised-model and tuning catalog for Stage 3.

Definitions here are planning/execution contracts, not claims that an
algorithm is scientifically superior.  Anomaly detection is deliberately kept
outside the eight-class leaderboard.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


MODEL_CATALOG_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_CATALOG_V1"
FOLD_COUNT = 5
WARNING_FIT_THRESHOLD = 250
HARD_FIT_LIMIT = 2_500
MAX_RANDOM_DOMAIN = 1_000_000


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _algorithm(
    identifier: str,
    label: str,
    family: str,
    *,
    fixed: Mapping[str, Any],
    compact: Sequence[Mapping[str, Any]],
    full: Mapping[str, Sequence[Any]],
    intensity: str,
    available: bool = True,
    status: str = "AVAILABLE",
    reason: str | None = None,
    probability: str = "NATIVE_PREDICT_PROBA",
    interpretability: Sequence[str] = (),
    compute_guard: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = sorted(set(fixed) | set(full) | {key for item in compact for key in item})
    return {
        "id": identifier,
        "label": label,
        "family": family,
        "available": available,
        "status": status,
        "unavailableReason": reason,
        "supportedTuningModes": ["FIXED", "GRID", "RANDOM"] if identifier != "class_frequency_null" else ["FIXED"],
        "defaultTuningMode": "FIXED" if identifier == "class_frequency_null" else "GRID",
        "defaultGridPreset": "COMPACT",
        "fixedHyperparameters": dict(fixed),
        "compactGrid": [dict(item) for item in compact],
        "fullGrid": {key: list(values) for key, values in full.items()},
        "allowedHyperparameters": allowed,
        "computeIntensity": intensity,
        "probabilityTreatment": probability,
        "interpretabilitySupport": list(interpretability),
        "computeGuard": dict(compute_guard or {}),
        "seeded": True,
        "rankingEligible": identifier != "class_frequency_null" or True,
    }


def model_catalog() -> list[dict[str, Any]]:
    xgb = _installed("xgboost")
    lgbm = _installed("lightgbm")
    cat = _installed("catboost")
    return [
        _algorithm(
            "class_frequency_null", "Class-frequency null", "REFERENCE",
            fixed={}, compact=[{}], full={}, intensity="LOW",
            probability="TRAINING_FOLD_CLASS_FREQUENCY",
            interpretability=["class_prior"],
        ),
        _algorithm(
            "multinomial_logistic", "Multinomial Logistic Regression", "TRANSPARENT_LINEAR",
            fixed={"C": 1.0, "solver": "lbfgs", "max_iter": 1000, "class_weight": None},
            compact=[
                {"C": 0.1, "solver": "lbfgs", "max_iter": 1000, "class_weight": None},
                {"C": 1.0, "solver": "lbfgs", "max_iter": 1000, "class_weight": None},
                {"C": 10.0, "solver": "lbfgs", "max_iter": 1000, "class_weight": None},
            ],
            full={"C": [0.01, 0.1, 1.0, 10.0], "solver": ["lbfgs"], "max_iter": [500, 1000], "class_weight": [None]},
            intensity="MEDIUM", interpretability=["coefficients", "fold_coefficient_stability", "permutation_importance"],
        ),
        _algorithm(
            "elastic_net_logistic", "Elastic-Net Multinomial Logistic", "TRANSPARENT_LINEAR",
            fixed={"C": 1.0, "l1_ratio": 0.5, "solver": "saga", "max_iter": 1000, "class_weight": None},
            compact=[
                {"C": 0.1, "l1_ratio": 0.1, "solver": "saga", "max_iter": 1000, "class_weight": None},
                {"C": 1.0, "l1_ratio": 0.5, "solver": "saga", "max_iter": 1000, "class_weight": None},
                {"C": 10.0, "l1_ratio": 0.9, "solver": "saga", "max_iter": 1000, "class_weight": None},
            ],
            full={"C": [0.01, 0.1, 1.0, 10.0], "l1_ratio": [0.1, 0.5, 0.9], "solver": ["saga"], "max_iter": [500, 1000], "class_weight": [None]},
            intensity="HIGH", interpretability=["coefficients", "fold_coefficient_stability", "permutation_importance"],
        ),
        _algorithm(
            "decision_tree", "Decision Tree", "TREE_ENSEMBLE",
            fixed={"max_depth": 8, "min_samples_split": 10, "min_samples_leaf": 5, "criterion": "log_loss", "class_weight": None},
            compact=[
                {"max_depth": 4, "min_samples_split": 10, "min_samples_leaf": 5, "criterion": "log_loss", "class_weight": None},
                {"max_depth": 8, "min_samples_split": 10, "min_samples_leaf": 5, "criterion": "log_loss", "class_weight": None},
                {"max_depth": 12, "min_samples_split": 50, "min_samples_leaf": 20, "criterion": "log_loss", "class_weight": None},
            ],
            full={"max_depth": [4, 8, 12, None], "min_samples_split": [2, 10, 50], "min_samples_leaf": [1, 5, 20], "criterion": ["gini", "entropy", "log_loss"], "class_weight": [None]},
            intensity="MEDIUM", interpretability=["native_importance", "permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "random_forest", "Random Forest", "TREE_ENSEMBLE",
            fixed={"n_estimators": 300, "max_depth": 24, "min_samples_leaf": 5, "max_features": "sqrt", "bootstrap": True, "class_weight": None, "n_jobs": 1},
            compact=[
                {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "max_features": "sqrt", "bootstrap": True, "class_weight": None, "n_jobs": 1},
                {"n_estimators": 300, "max_depth": 24, "min_samples_leaf": 5, "max_features": "sqrt", "bootstrap": True, "class_weight": None, "n_jobs": 1},
                {"n_estimators": 500, "max_depth": None, "min_samples_leaf": 20, "max_features": 0.5, "bootstrap": True, "class_weight": None, "n_jobs": 1},
            ],
            full={"n_estimators": [200, 500], "max_depth": [None, 12, 24], "min_samples_leaf": [1, 5, 20], "max_features": ["sqrt", 0.5], "bootstrap": [True], "class_weight": [None], "n_jobs": [1]},
            intensity="HIGH", interpretability=["native_importance", "permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "extra_trees", "Extra Trees", "TREE_ENSEMBLE",
            fixed={"n_estimators": 300, "max_depth": 24, "min_samples_leaf": 5, "max_features": "sqrt", "class_weight": None, "n_jobs": 1},
            compact=[
                {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "max_features": "sqrt", "class_weight": None, "n_jobs": 1},
                {"n_estimators": 300, "max_depth": 24, "min_samples_leaf": 5, "max_features": "sqrt", "class_weight": None, "n_jobs": 1},
                {"n_estimators": 500, "max_depth": None, "min_samples_leaf": 20, "max_features": 0.5, "class_weight": None, "n_jobs": 1},
            ],
            full={"n_estimators": [200, 500], "max_depth": [None, 12, 24], "min_samples_leaf": [1, 5, 20], "max_features": ["sqrt", 0.5], "class_weight": [None], "n_jobs": [1]},
            intensity="HIGH", interpretability=["native_importance", "permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "histogram_gradient_boosting", "Histogram Gradient Boosting", "TREE_ENSEMBLE",
            fixed={"learning_rate": 0.07, "max_iter": 300, "max_leaf_nodes": 31, "max_depth": None, "min_samples_leaf": 20, "l2_regularization": 1.0, "early_stopping": False},
            compact=[
                {"learning_rate": 0.03, "max_iter": 500, "max_leaf_nodes": 31, "max_depth": None, "min_samples_leaf": 50, "l2_regularization": 1.0, "early_stopping": False},
                {"learning_rate": 0.07, "max_iter": 300, "max_leaf_nodes": 31, "max_depth": None, "min_samples_leaf": 20, "l2_regularization": 1.0, "early_stopping": False},
                {"learning_rate": 0.1, "max_iter": 200, "max_leaf_nodes": 63, "max_depth": None, "min_samples_leaf": 20, "l2_regularization": 10.0, "early_stopping": False},
            ],
            full={"learning_rate": [0.03, 0.07, 0.1], "max_iter": [200, 500], "max_leaf_nodes": [15, 31, 63], "max_depth": [None], "min_samples_leaf": [20, 50], "l2_regularization": [0.0, 1.0, 10.0], "early_stopping": [False]},
            intensity="HIGH", interpretability=["permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "xgboost", "XGBoost", "TREE_ENSEMBLE",
            fixed={"n_estimators": 300, "learning_rate": 0.07, "max_depth": 5, "min_child_weight": 1, "subsample": 0.8, "colsample_bytree": 0.7, "gamma": 0.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "n_jobs": 1},
            compact=[
                {"n_estimators": 300, "learning_rate": 0.03, "max_depth": 3, "min_child_weight": 1, "subsample": 0.8, "colsample_bytree": 0.7, "gamma": 0.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "n_jobs": 1},
                {"n_estimators": 300, "learning_rate": 0.07, "max_depth": 5, "min_child_weight": 1, "subsample": 0.8, "colsample_bytree": 0.7, "gamma": 0.0, "reg_alpha": 0.0, "reg_lambda": 1.0, "n_jobs": 1},
                {"n_estimators": 600, "learning_rate": 0.03, "max_depth": 5, "min_child_weight": 5, "subsample": 1.0, "colsample_bytree": 1.0, "gamma": 0.0, "reg_alpha": 0.1, "reg_lambda": 5.0, "n_jobs": 1},
                {"n_estimators": 300, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 5, "subsample": 0.8, "colsample_bytree": 1.0, "gamma": 1.0, "reg_alpha": 0.1, "reg_lambda": 5.0, "n_jobs": 1},
                {"n_estimators": 600, "learning_rate": 0.07, "max_depth": 3, "min_child_weight": 1, "subsample": 1.0, "colsample_bytree": 0.7, "gamma": 1.0, "reg_alpha": 0.0, "reg_lambda": 5.0, "n_jobs": 1},
                {"n_estimators": 600, "learning_rate": 0.1, "max_depth": 7, "min_child_weight": 1, "subsample": 1.0, "colsample_bytree": 1.0, "gamma": 0.0, "reg_alpha": 0.1, "reg_lambda": 1.0, "n_jobs": 1},
            ],
            full={"n_estimators": [300, 600], "learning_rate": [0.03, 0.07, 0.1], "max_depth": [3, 5, 7], "min_child_weight": [1, 5], "subsample": [0.8, 1.0], "colsample_bytree": [0.7, 1.0], "gamma": [0.0, 1.0], "reg_alpha": [0.0, 0.1], "reg_lambda": [1.0, 5.0], "n_jobs": [1]},
            intensity="VERY_HIGH", available=xgb,
            status="AVAILABLE" if xgb else "NOT_INSTALLED",
            reason=None if xgb else "XGBoost is not installed; no dependency is added automatically.",
            interpretability=["native_gain", "permutation_importance", "fold_importance_stability", "shap_when_dependency_governed"],
        ),
        _algorithm(
            "lightgbm", "LightGBM", "TREE_ENSEMBLE",
            fixed={"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 31, "max_depth": -1, "min_child_samples": 20, "subsample": 0.9, "colsample_bytree": 0.9, "n_jobs": 1},
            compact=[
                {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 31, "max_depth": -1, "min_child_samples": 20, "subsample": 0.9, "colsample_bytree": 0.9, "n_jobs": 1},
                {"n_estimators": 500, "learning_rate": 0.03, "num_leaves": 63, "max_depth": -1, "min_child_samples": 50, "subsample": 0.8, "colsample_bytree": 0.8, "n_jobs": 1},
            ],
            full={"n_estimators": [300, 500], "learning_rate": [0.03, 0.05, 0.1], "num_leaves": [31, 63], "max_depth": [-1], "min_child_samples": [20, 50], "subsample": [0.8, 1.0], "colsample_bytree": [0.8, 1.0], "n_jobs": [1]},
            intensity="VERY_HIGH", available=lgbm,
            status="AVAILABLE" if lgbm else "NOT_INSTALLED",
            reason=None if lgbm else "LightGBM is optional and is not installed.",
            interpretability=["native_gain", "permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "catboost", "CatBoost", "TREE_ENSEMBLE",
            fixed={"iterations": 300, "learning_rate": 0.05, "depth": 6, "l2_leaf_reg": 3.0, "thread_count": 1, "verbose": False},
            compact=[
                {"iterations": 300, "learning_rate": 0.05, "depth": 6, "l2_leaf_reg": 3.0, "thread_count": 1, "verbose": False},
                {"iterations": 500, "learning_rate": 0.03, "depth": 8, "l2_leaf_reg": 5.0, "thread_count": 1, "verbose": False},
            ],
            full={"iterations": [300, 500], "learning_rate": [0.03, 0.05, 0.1], "depth": [4, 6, 8], "l2_leaf_reg": [3.0, 5.0], "thread_count": [1], "verbose": [False]},
            intensity="VERY_HIGH", available=cat,
            status="AVAILABLE" if cat else "NOT_INSTALLED",
            reason=None if cat else "CatBoost is optional and is not installed.",
            interpretability=["native_importance", "permutation_importance", "fold_importance_stability"],
        ),
        _algorithm(
            "linear_svm", "Linear SVM (fold-local calibrated)", "MARGIN_DISTANCE",
            fixed={"C": 1.0, "loss": "squared_hinge", "class_weight": None, "calibration_cv": 3},
            compact=[
                {"C": 0.1, "loss": "squared_hinge", "class_weight": None, "calibration_cv": 3},
                {"C": 1.0, "loss": "squared_hinge", "class_weight": None, "calibration_cv": 3},
            ],
            full={"C": [0.01, 0.1, 1.0, 10.0], "loss": ["squared_hinge"], "class_weight": [None], "calibration_cv": [3]},
            intensity="VERY_HIGH", probability="TRAINING_FOLD_ONLY_CALIBRATED_CLASSIFIER_CV",
            interpretability=["coefficients", "permutation_importance"],
        ),
        _algorithm(
            "sgd_classifier", "SGD Linear Classifier", "MARGIN_DISTANCE",
            fixed={"loss": "log_loss", "alpha": 0.0001, "penalty": "l2", "l1_ratio": 0.15, "max_iter": 1000, "class_weight": None},
            compact=[
                {"loss": "log_loss", "alpha": 0.00001, "penalty": "l2", "l1_ratio": 0.15, "max_iter": 1000, "class_weight": None},
                {"loss": "log_loss", "alpha": 0.0001, "penalty": "elasticnet", "l1_ratio": 0.15, "max_iter": 1000, "class_weight": None},
                {"loss": "log_loss", "alpha": 0.001, "penalty": "elasticnet", "l1_ratio": 0.5, "max_iter": 1000, "class_weight": None},
            ],
            full={"loss": ["log_loss", "hinge"], "alpha": [0.00001, 0.0001, 0.001], "penalty": ["l2", "elasticnet"], "l1_ratio": [0.15, 0.5], "max_iter": [1000], "class_weight": [None]},
            intensity="MEDIUM", probability="NATIVE_FOR_LOG_LOSS;TRAINING_FOLD_CALIBRATION_REQUIRED_FOR_HINGE",
            interpretability=["coefficients", "fold_coefficient_stability", "permutation_importance"],
        ),
        _algorithm(
            "knn", "k-Nearest Neighbors", "MARGIN_DISTANCE",
            fixed={"n_neighbors": 31, "weights": "distance", "p": 2, "n_jobs": 1},
            compact=[{"n_neighbors": 31, "weights": "distance", "p": 2, "n_jobs": 1}],
            full={"n_neighbors": [5, 15, 31, 61], "weights": ["uniform", "distance"], "p": [1, 2], "n_jobs": [1]},
            intensity="PROHIBITIVE", available=False, status="COMPUTE_GUARDED",
            reason="Full-population KNN is held closed until a separately governed sampling or dimensionality-reduction experiment exists.",
            interpretability=["permutation_importance"],
            compute_guard={"requiresGovernedSamplingOrReduction": True, "fullPopulationAutoExecution": False},
        ),
        _algorithm(
            "gaussian_naive_bayes", "Gaussian Naive Bayes", "PROBABILISTIC",
            fixed={"var_smoothing": 1e-9},
            compact=[{"var_smoothing": 1e-10}, {"var_smoothing": 1e-9}, {"var_smoothing": 1e-8}],
            full={"var_smoothing": [1e-11, 1e-10, 1e-9, 1e-8]},
            intensity="LOW", interpretability=["class_conditional_statistics", "permutation_importance"],
        ),
        _algorithm(
            "mlp", "MLPClassifier", "NEURAL",
            fixed={"hidden_layer_sizes": [128], "activation": "relu", "alpha": 0.0001, "learning_rate_init": 0.001, "batch_size": 512, "max_iter": 100, "early_stopping": True},
            compact=[
                {"hidden_layer_sizes": [128], "activation": "relu", "alpha": 0.0001, "learning_rate_init": 0.001, "batch_size": 512, "max_iter": 100, "early_stopping": True},
                {"hidden_layer_sizes": [128, 64], "activation": "relu", "alpha": 0.001, "learning_rate_init": 0.0005, "batch_size": 512, "max_iter": 100, "early_stopping": True},
            ],
            full={"hidden_layer_sizes": [[128], [256], [128, 64]], "activation": ["relu"], "alpha": [0.00001, 0.0001, 0.001], "learning_rate_init": [0.0005, 0.001], "batch_size": ["auto", 512], "max_iter": [100, 200], "early_stopping": [True]},
            intensity="VERY_HIGH", interpretability=["permutation_importance", "shap_when_dependency_governed"],
        ),
    ]


def anomaly_analytics_catalog() -> dict[str, Any]:
    return {
        "status": "SEPARATE_RESEARCH_CAPABILITY_NOT_MODEL_COMPETITION",
        "rankingMetric": None,
        "algorithms": ["Isolation Forest", "One-Class SVM", "Local Outlier Factor"],
        "purposes": [
            "unusual observation detection",
            "out-of-distribution detection",
            "regime detection",
            "data-quality signals",
            "anomaly-score candidate features",
        ],
    }


def _cartesian_count(grid: Mapping[str, Sequence[Any]]) -> int:
    count = 1
    for values in grid.values():
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
            raise ValueError("Every grid parameter must contain at least one value.")
        count *= len(values)
    return count


def _cartesian(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*(grid[key] for key in keys))]


def _cartesian_at(grid: Mapping[str, Sequence[Any]], index: int) -> dict[str, Any]:
    """Resolve one mixed-radix Cartesian member without materializing the domain."""

    keys = list(grid)
    output: dict[str, Any] = {}
    remaining = index
    for key in reversed(keys):
        values = grid[key]
        remaining, offset = divmod(remaining, len(values))
        output[key] = values[offset]
    return {key: output[key] for key in keys}


def _validate_keys(algorithm: Mapping[str, Any], configuration: Mapping[str, Any]) -> None:
    unknown = sorted(set(configuration) - set(algorithm.get("allowedHyperparameters") or []))
    if unknown:
        raise ValueError("Unsupported hyperparameter(s): " + ", ".join(unknown))


def _validate_configuration_values(
    algorithm: Mapping[str, Any], configuration: Mapping[str, Any]
) -> None:
    """Reject unsafe or estimator-incompatible scientist-edited values at plan time."""

    identifier = str(algorithm.get("id") or "")
    for key, value in configuration.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{key} must be finite.")

    for key in ("n_jobs", "thread_count"):
        if key in configuration and configuration[key] != 1:
            raise ValueError(f"{key} must equal 1 under the safe single-job execution contract.")
    if "class_weight" in configuration and configuration["class_weight"] is not None:
        raise ValueError("class_weight must remain null; balancing is not implicitly authorized.")
    if identifier == "histogram_gradient_boosting" and configuration.get("early_stopping") is not False:
        raise ValueError("Histogram Gradient Boosting early_stopping must remain false to avoid an internal random validation split.")
    if identifier == "mlp" and configuration.get("early_stopping") is not True:
        raise ValueError("MLP early_stopping must remain true inside the training fold.")
    if identifier == "multinomial_logistic" and configuration.get("solver") != "lbfgs":
        raise ValueError("Multinomial Logistic requires the governed lbfgs solver.")
    if identifier == "elastic_net_logistic" and configuration.get("solver") != "saga":
        raise ValueError("Elastic-Net Logistic requires the governed saga solver.")
    if identifier == "decision_tree" and configuration.get("criterion") not in {"gini", "entropy", "log_loss"}:
        raise ValueError("Decision Tree criterion is unsupported.")
    if identifier == "random_forest" and configuration.get("bootstrap") is not True:
        raise ValueError("Random Forest bootstrap must remain true in this catalog version.")
    if identifier == "linear_svm" and configuration.get("loss") != "squared_hinge":
        raise ValueError("Linear SVM supports only squared_hinge in this catalog version.")
    if identifier == "sgd_classifier":
        if configuration.get("loss") not in {"log_loss", "hinge"}:
            raise ValueError("SGD loss must be log_loss or hinge.")
        if configuration.get("penalty") not in {"l2", "elasticnet"}:
            raise ValueError("SGD penalty must be l2 or elasticnet.")
    if identifier == "knn":
        if configuration.get("weights") not in {"uniform", "distance"}:
            raise ValueError("KNN weights must be uniform or distance.")
        if configuration.get("p") not in {1, 2}:
            raise ValueError("KNN p must be 1 or 2.")
    if identifier == "mlp" and configuration.get("activation") != "relu":
        raise ValueError("MLP activation must remain relu in this catalog version.")
    if identifier == "catboost" and configuration.get("verbose") is not False:
        raise ValueError("CatBoost verbose must remain false for bounded job output.")

    positive_integer_limits = {
        "max_iter": 10_000,
        "n_estimators": 5_000,
        "iterations": 5_000,
        "min_samples_split": 1_000_000,
        "min_samples_leaf": 1_000_000,
        "max_leaf_nodes": 4_096,
        "min_child_samples": 1_000_000,
        "n_neighbors": 10_000,
        "calibration_cv": 10,
    }
    for key, limit in positive_integer_limits.items():
        if key not in configuration:
            continue
        value = configuration[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
            raise ValueError(f"{key} must be an integer between 1 and {limit:,}.")
    if "max_depth" in configuration:
        value = configuration["max_depth"]
        if value is not None and not (
            identifier == "lightgbm" and value == -1
        ) and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 64):
            raise ValueError("max_depth must be null, LightGBM -1, or an integer from 1 through 64.")

    strictly_positive = {
        "C", "learning_rate", "alpha", "learning_rate_init", "var_smoothing",
        "min_child_weight", "reg_lambda", "l2_leaf_reg",
    }
    nonnegative = {"gamma", "reg_alpha", "l2_regularization"}
    for key in strictly_positive:
        if key in configuration and (
            isinstance(configuration[key], bool)
            or not isinstance(configuration[key], (int, float))
            or float(configuration[key]) <= 0
        ):
            raise ValueError(f"{key} must be a positive finite number.")
    for key in nonnegative:
        if key in configuration and (
            isinstance(configuration[key], bool)
            or not isinstance(configuration[key], (int, float))
            or float(configuration[key]) < 0
        ):
            raise ValueError(f"{key} must be a nonnegative finite number.")
    for key in ("subsample", "colsample_bytree", "l1_ratio"):
        if key in configuration and (
            isinstance(configuration[key], bool)
            or not isinstance(configuration[key], (int, float))
            or not 0 < float(configuration[key]) <= 1
        ):
            raise ValueError(f"{key} must be greater than 0 and at most 1.")
    if "max_features" in configuration:
        value = configuration["max_features"]
        if value != "sqrt" and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 < float(value) <= 1
        ):
            raise ValueError("max_features must be sqrt or a numeric fraction in (0, 1].")
    if "hidden_layer_sizes" in configuration:
        value = configuration["hidden_layer_sizes"]
        if not isinstance(value, (list, tuple)) or not value or len(value) > 3 or any(
            isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 2_048
            for width in value
        ):
            raise ValueError("hidden_layer_sizes must contain one to three positive widths no larger than 2,048.")
    if "batch_size" in configuration:
        value = configuration["batch_size"]
        if value != "auto" and (
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8_192
        ):
            raise ValueError("batch_size must be auto or an integer from 1 through 8,192.")


def _validate_grid_values(
    algorithm: Mapping[str, Any], grid: Mapping[str, Sequence[Any]]
) -> None:
    baseline = dict(algorithm.get("fixedHyperparameters") or {})
    for key, values in grid.items():
        for value in values:
            candidate = {**baseline, key: value}
            _validate_configuration_values(algorithm, candidate)


def plan_configurations(
    algorithm: Mapping[str, Any], specification: Mapping[str, Any], *, seed: int
) -> dict[str, Any]:
    mode = str(specification.get("tuningMode") or algorithm["defaultTuningMode"]).upper()
    if mode not in set(algorithm.get("supportedTuningModes") or []):
        raise ValueError(f"{algorithm['id']} does not support tuning mode {mode}.")
    preset = str(specification.get("gridPreset") or algorithm.get("defaultGridPreset") or "COMPACT").upper()
    configurations: list[dict[str, Any]] = []
    count = 0
    if mode == "FIXED":
        fixed = dict(algorithm.get("fixedHyperparameters") or {})
        fixed.update(dict(specification.get("fixedHyperparameters") or {}))
        _validate_keys(algorithm, fixed)
        _validate_configuration_values(algorithm, fixed)
        configurations = [fixed]
        count = 1
    else:
        if preset == "COMPACT":
            compact = specification.get("compactGrid") or algorithm.get("compactGrid") or []
            if not isinstance(compact, list) or not compact:
                raise ValueError("Compact Grid requires at least one explicit configuration.")
            configurations = [dict(item) for item in compact if isinstance(item, Mapping)]
            if len(configurations) != len(compact):
                raise ValueError("Every compact-grid entry must be an object.")
            for item in configurations:
                _validate_keys(algorithm, item)
                _validate_configuration_values(algorithm, item)
            count = len(configurations)
        elif preset in {"FULL", "CUSTOM"}:
            grid = (
                dict(specification.get("customGrid") or {})
                if preset == "CUSTOM"
                else dict(algorithm.get("fullGrid") or {})
            )
            if not grid:
                raise ValueError(f"{preset.title()} Grid requires at least one parameter domain.")
            _validate_keys(algorithm, grid)
            _validate_grid_values(algorithm, grid)
            count = _cartesian_count(grid)
            # Huge legal domains remain inspectable, but are not expanded into
            # an accidental in-memory launch plan.
            if count * FOLD_COUNT <= HARD_FIT_LIMIT:
                configurations = _cartesian(grid)
        else:
            raise ValueError("Grid preset must be COMPACT, FULL, or CUSTOM.")
        if mode == "RANDOM":
            iterations = int(specification.get("randomIterations") or min(20, count))
            if iterations < 1 or iterations > count:
                raise ValueError("Random-search iterations must be between 1 and the grid-domain size.")
            domain = configurations
            if not domain:
                grid = (
                    dict(specification.get("customGrid") or {})
                    if preset == "CUSTOM"
                    else dict(algorithm.get("fullGrid") or {})
                )
                if count > MAX_RANDOM_DOMAIN:
                    raise ValueError(
                        f"Random-search domain contains {count:,} configurations, above the planning limit of {MAX_RANDOM_DOMAIN:,}. Reduce the custom grid."
                    )
                sampled = random.Random(seed).sample(range(count), iterations)
                domain = [_cartesian_at(grid, index) for index in sampled]
                configurations = domain
            else:
                configurations = random.Random(seed).sample(domain, iterations)
            count = iterations
    for configuration in configurations:
        _validate_configuration_values(algorithm, configuration)
    total_fits = count * FOLD_COUNT
    return {
        "tuningMode": mode,
        "gridPreset": preset,
        "configurationCount": count,
        "foldCount": FOLD_COUNT,
        "totalFits": total_fits,
        "configurations": configurations,
        "requiresAcknowledgement": total_fits > WARNING_FIT_THRESHOLD,
        "exceedsHardLimit": total_fits > HARD_FIT_LIMIT,
        "warningThresholdFits": WARNING_FIT_THRESHOLD,
        "hardLimitFits": HARD_FIT_LIMIT,
    }


def catalog_public() -> dict[str, Any]:
    algorithms = model_catalog()
    return {
        "schemaVersion": MODEL_CATALOG_SCHEMA_VERSION,
        "algorithms": algorithms,
        "families": [
            {
                "id": family,
                "label": label,
                "algorithms": [item["id"] for item in algorithms if item["family"] == family],
            }
            for family, label in (
                ("REFERENCE", "Reference"),
                ("TRANSPARENT_LINEAR", "Transparent / Linear"),
                ("TREE_ENSEMBLE", "Tree / Ensemble"),
                ("MARGIN_DISTANCE", "Margin / Distance"),
                ("PROBABILISTIC", "Probabilistic"),
                ("NEURAL", "Neural"),
            )
        ],
        "anomalyAnalytics": anomaly_analytics_catalog(),
        "tuning": {
            "modes": ["FIXED", "GRID", "RANDOM"],
            "gridPresets": ["COMPACT", "FULL", "CUSTOM"],
            "defaultMode": "GRID",
            "defaultGridPreset": "COMPACT",
            "warningFitThreshold": WARNING_FIT_THRESHOLD,
            "hardFitLimit": HARD_FIT_LIMIT,
            "foldCount": FOLD_COUNT,
            "bayesianOptuna": "NOT_AVAILABLE_NOT_INSTALLED",
        },
        "interpretabilityRoadmap": {
            "nativeTreeImportanceSoleSelectionAuthority": False,
            "permutationImportance": "SUPPORTED_FOR_EVALUATION",
            "shap": "AVAILABLE_ONLY_WHEN_DEPENDENCY_IS_GOVERNED",
            "rfe": "POST_MODEL_EVIDENCE_ONLY_WHEN_COMPUTATIONALLY_APPROPRIATE",
            "featureFamilyAblation": "SUPPORTED_BY_PRESERVED_PRESETS",
            "coefficientStability": "SUPPORTED_FOR_LINEAR_MODELS",
        },
    }


__all__ = [
    "FOLD_COUNT",
    "HARD_FIT_LIMIT",
    "MAX_RANDOM_DOMAIN",
    "WARNING_FIT_THRESHOLD",
    "anomaly_analytics_catalog",
    "catalog_public",
    "model_catalog",
    "plan_configurations",
]
