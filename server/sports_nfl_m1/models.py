"""Bounded deterministic statistical candidates for NFL M1."""
from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.special import ndtr
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from .contracts import (
    M1_SCHEMA_VERSION,
    NflM1IntegrityError,
    RANDOM_SEED,
    ScoreModelConfig,
    assert_valid_model_predictors,
    research_only_metadata,
)
from .prediction import GamePredictions
from .preprocessing import FoldLocalPreprocessor


def _validated_weights(sample_weight: Any | None, row_count: int) -> np.ndarray | None:
    if sample_weight is None:
        return None
    values = np.asarray(sample_weight, dtype=np.float64)
    if values.ndim != 1 or values.size != row_count:
        raise NflM1IntegrityError("sample weights must match the training rows")
    if not np.isfinite(values).all() or np.any(values <= 0.0):
        raise NflM1IntegrityError(
            "sample weights must be finite and strictly positive; subset the recency eligible_mask before fit"
        )
    return values


def _validated_scores(values: Any, row_count: int, label: str) -> np.ndarray:
    scores = np.asarray(values, dtype=np.float64)
    if scores.ndim != 1 or scores.size != row_count:
        raise NflM1IntegrityError(f"{label} must match the training rows")
    if not np.isfinite(scores).all() or np.any(scores < 0.0):
        raise NflM1IntegrityError(f"{label} contains invalid score truth")
    return scores


@dataclass
class RegularizedHomeWinModel:
    feature_names: tuple[str, ...]
    categorical_features: tuple[str, ...] | None = None
    c_value: float = 1.0
    seed: int = RANDOM_SEED
    max_iter: int = 2_000
    preprocessor: FoldLocalPreprocessor | None = field(init=False, default=None)
    estimator: LogisticRegression | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.feature_names = assert_valid_model_predictors(self.feature_names)
        if self.c_value <= 0.0 or self.max_iter <= 0:
            raise NflM1IntegrityError("logistic regularization parameters must be positive")

    def fit(
        self,
        frame: pd.DataFrame,
        home_win: Any,
        *,
        sample_weight: Any | None = None,
        training_row_ids: Sequence[object] | None = None,
    ) -> "RegularizedHomeWinModel":
        labels = np.asarray(home_win)
        if labels.ndim != 1 or labels.size != len(frame) or not np.isin(labels, (0, 1)).all():
            raise NflM1IntegrityError("home-win truth must contain one binary label per row")
        if np.unique(labels).size != 2:
            raise NflM1IntegrityError("home-win training truth must contain both classes")
        weights = _validated_weights(sample_weight, len(frame))
        preprocessor = FoldLocalPreprocessor.fit(
            frame,
            self.feature_names,
            categorical_features=self.categorical_features,
            training_row_ids=training_row_ids,
        )
        matrix = preprocessor.transform(frame)
        estimator = LogisticRegression(
            C=self.c_value,
            penalty="l2",
            solver="lbfgs",
            max_iter=self.max_iter,
            random_state=self.seed,
        )
        estimator.fit(matrix, labels.astype(np.int64), sample_weight=weights)
        if not np.array_equal(estimator.classes_, np.asarray([0, 1])):
            raise NflM1IntegrityError("home-win logistic class order is invalid")
        self.preprocessor = preprocessor
        self.estimator = estimator
        return self

    def predict_home_win_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if self.preprocessor is None or self.estimator is None:
            raise NflM1IntegrityError("home-win logistic model has not been fitted")
        probability = np.asarray(
            self.estimator.predict_proba(self.preprocessor.transform(frame))[:, 1],
            dtype=np.float64,
        )
        if not np.isfinite(probability).all() or np.any(probability < 0.0) or np.any(probability > 1.0):
            raise NflM1IntegrityError("home-win logistic produced invalid probabilities")
        return np.clip(probability, 1e-12, 1.0 - 1e-12)

    def state(self) -> dict[str, Any]:
        state = research_only_metadata(f"home-win-logistic-c-{self.c_value:g}")
        state.update(
            {
                "schemaVersion": M1_SCHEMA_VERSION,
                "estimator": "sklearn.linear_model.LogisticRegression",
                "objective": "BINARY_HOME_WIN_LOG_LOSS",
                "C": self.c_value,
                "penalty": "l2",
                "solver": "lbfgs",
                "maxIter": self.max_iter,
                "seed": self.seed,
                "featureNames": list(self.feature_names),
                "preprocessor": None if self.preprocessor is None else self.preprocessor.state(),
            }
        )
        return state


def _score_estimator(
    config: ScoreModelConfig,
    seed: int,
) -> Ridge | HistGradientBoostingRegressor | ExtraTreesRegressor | Any:
    parameters = dict(config.parameters)
    if config.family == "RIDGE":
        return Ridge(alpha=float(parameters["alpha"]))
    if config.family == "HIST_GRADIENT_BOOSTING":
        return HistGradientBoostingRegressor(
            **parameters,
            loss="squared_error",
            early_stopping=False,
            random_state=seed,
        )
    if config.family == "EXTRA_TREES":
        return ExtraTreesRegressor(
            **parameters,
            criterion="squared_error",
            bootstrap=False,
            n_jobs=1,
            random_state=seed,
        )
    if config.family == "XGBOOST":
        capability = xgboost_capability()
        if not capability["available"]:
            raise NflM1IntegrityError("optional XGBoost score challenger is unavailable")
        # Imported only for the one explicitly requested optional candidate.
        # It is used directly (not through sklearn cloning/meta-estimators),
        # avoiding the sklearn 1.6 tag incompatibility handled elsewhere in the repo.
        from xgboost import XGBRegressor

        return XGBRegressor(
            **parameters,
            objective="reg:squarederror",
            tree_method="hist",
            n_jobs=1,
            random_state=seed,
            verbosity=0,
        )
    raise NflM1IntegrityError(f"unsupported M1 score-model family: {config.family}")


@dataclass
class IndependentHomeAwayScoreModel:
    """Fit matched home/away regressors with shared fold-local preprocessing.

    Paired in-sample residuals are retained as diagnostics.  The distribution
    layer must construct its simulation authority from genuine OOF/cross-fitted
    residuals; it must not mistake these diagnostics for calibrated residuals.
    """

    config: ScoreModelConfig
    feature_names: tuple[str, ...]
    categorical_features: tuple[str, ...] | None = None
    seed: int = RANDOM_SEED
    preprocessor: FoldLocalPreprocessor | None = field(init=False, default=None)
    home_estimator: Any | None = field(init=False, default=None)
    away_estimator: Any | None = field(init=False, default=None)
    paired_training_residuals: np.ndarray | None = field(init=False, default=None)
    residual_margin_scale: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.feature_names = assert_valid_model_predictors(self.feature_names)

    def fit(
        self,
        frame: pd.DataFrame,
        home_points: Any,
        away_points: Any,
        *,
        sample_weight: Any | None = None,
        training_row_ids: Sequence[object] | None = None,
    ) -> "IndependentHomeAwayScoreModel":
        home = _validated_scores(home_points, len(frame), "home_points")
        away = _validated_scores(away_points, len(frame), "away_points")
        weights = _validated_weights(sample_weight, len(frame))
        preprocessor = FoldLocalPreprocessor.fit(
            frame,
            self.feature_names,
            categorical_features=self.categorical_features,
            training_row_ids=training_row_ids,
        )
        matrix = preprocessor.transform(frame)
        home_estimator = _score_estimator(self.config, self.seed)
        away_estimator = _score_estimator(self.config, self.seed + 1)
        home_estimator.fit(matrix, home, sample_weight=weights)
        away_estimator.fit(matrix, away, sample_weight=weights)
        fitted_home = np.asarray(home_estimator.predict(matrix), dtype=np.float64)
        fitted_away = np.asarray(away_estimator.predict(matrix), dtype=np.float64)
        residuals = np.column_stack((home - fitted_home, away - fitted_away))
        if not np.isfinite(residuals).all():
            raise NflM1IntegrityError("score-model residuals are invalid")
        margin_scale = float(np.std(residuals[:, 0] - residuals[:, 1], ddof=0))
        self.preprocessor = preprocessor
        self.home_estimator = home_estimator
        self.away_estimator = away_estimator
        self.paired_training_residuals = np.ascontiguousarray(residuals)
        self.residual_margin_scale = max(margin_scale, 1.0)
        return self

    def predict(self, frame: pd.DataFrame) -> GamePredictions:
        if (
            self.preprocessor is None
            or self.home_estimator is None
            or self.away_estimator is None
            or self.residual_margin_scale is None
        ):
            raise NflM1IntegrityError("score model has not been fitted")
        matrix = self.preprocessor.transform(frame)
        home = np.maximum(np.asarray(self.home_estimator.predict(matrix), dtype=np.float64), 0.0)
        away = np.maximum(np.asarray(self.away_estimator.predict(matrix), dtype=np.float64), 0.0)
        probability = np.clip(ndtr((home - away) / self.residual_margin_scale), 1e-6, 1.0 - 1e-6)
        return GamePredictions(home, away, probability).validated()

    @property
    def residual_correlation(self) -> float | None:
        if self.paired_training_residuals is None:
            return None
        first = self.paired_training_residuals[:, 0]
        second = self.paired_training_residuals[:, 1]
        if np.std(first) == 0.0 or np.std(second) == 0.0:
            return 0.0
        return float(np.corrcoef(first, second)[0, 1])

    def state(self) -> dict[str, Any]:
        state = research_only_metadata(self.config.candidate_id)
        state.update(
            {
                "schemaVersion": M1_SCHEMA_VERSION,
                "estimatorFamily": self.config.family,
                "objective": "INDEPENDENT_EXPECTED_HOME_AND_AWAY_POINTS_WITH_PAIRED_RESIDUAL_RETENTION",
                "parameters": dict(self.config.parameters),
                "seedHome": self.seed,
                "seedAway": self.seed + 1,
                "featureNames": list(self.feature_names),
                "pairedResidualsRetained": self.paired_training_residuals is not None,
                "pairedResidualProvenance": "IN_SAMPLE_TRAINING_DIAGNOSTIC_NOT_DISTRIBUTION_AUTHORITY",
                "residualCorrelation": self.residual_correlation,
                "residualMarginScale": self.residual_margin_scale,
                "preprocessor": None if self.preprocessor is None else self.preprocessor.state(),
            }
        )
        return state


def xgboost_capability() -> dict[str, Any]:
    """Detect the optional challenger without importing or instantiating it."""

    available = importlib.util.find_spec("xgboost") is not None
    version: str | None = None
    if available:
        try:
            version = importlib.metadata.version("xgboost")
        except importlib.metadata.PackageNotFoundError:
            available = False
    return {
        "candidate": "XGBOOST_SCORE_MODEL",
        "available": available,
        "version": version,
        "detectionOnly": True,
        "instantiated": False,
        "status": "OPTIONAL_CHALLENGER_AVAILABLE" if available else "OPTIONAL_DEPENDENCY_UNAVAILABLE",
    }


__all__ = [
    "IndependentHomeAwayScoreModel",
    "RegularizedHomeWinModel",
    "xgboost_capability",
]
