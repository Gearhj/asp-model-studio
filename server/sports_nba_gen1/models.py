"""Bounded source-independent point-model screen for NBA Gen 1.

Only the supplied training rows enter fitted imputers, scalers or estimators.
The caller must admit a real, permitted population and establish chronological
roles before calling this module. Tests of these mechanics are not evidence of
NBA performance. No sportsbook or optional player fields enter the fixed screen.
Targets are HOME margin and total; returned point predictions are HOME, AWAY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .features import FEATURE_COLUMNS


SCREEN_VERSION = "NBA_GEN1_BOUNDED_POINT_SCREEN_V1"
SCREEN_CANDIDATES = (
    {"family": "league", "params": {}},
    {"family": "elo", "params": {}},
    {"family": "ridge", "params": {"alpha": 10.0}},
    {"family": "ridge", "params": {"alpha": 100.0}},
    {"family": "hgb", "params": {"l2_regularization": 10.0}},
    {"family": "hgb", "params": {"l2_regularization": 50.0}},
)
_HGB_FIXED = {
    "learning_rate": 0.05, "max_iter": 150, "max_leaf_nodes": 15,
    "min_samples_leaf": 40, "max_bins": 255, "early_stopping": False,
    "random_state": 731001, "loss": "squared_error",
}


class PointModelError(ValueError):
    """Training/prediction contract or the bounded candidate declaration failed."""


def _game_ids(frame: pd.DataFrame, label: str) -> tuple[str, ...]:
    if not isinstance(frame, pd.DataFrame) or "game_id" not in frame:
        raise PointModelError(f"{label} must be a DataFrame with stable game_id")
    ids = frame["game_id"]
    if ids.isna().any() or any(not str(value).strip() for value in ids):
        raise PointModelError(f"{label} contains missing game_id")
    result = tuple(str(value) for value in ids)
    if len(result) != len(set(result)):
        raise PointModelError(f"{label} must contain one intact row per unique game_id")
    return result


def _numeric_features(frame: pd.DataFrame, columns: tuple[str, ...]) -> np.ndarray:
    missing = set(columns).difference(frame.columns)
    if missing:
        raise PointModelError(f"Missing declared numeric features: {sorted(missing)}")
    try:
        values = frame.loc[:, list(columns)].to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PointModelError("Declared features must be numeric or NaN") from exc
    if np.isinf(values).any():
        raise PointModelError("Infinite feature values are not supported")
    return values


def _targets(features: pd.DataFrame, labels: pd.DataFrame) -> tuple[np.ndarray, tuple[str, ...]]:
    ids = _game_ids(features, "features")
    label_ids = _game_ids(labels, "labels")
    if len(ids) < 2 or set(ids) != set(label_ids):
        raise PointModelError("At least two identically bound training game identities are required")
    bound = labels.copy()
    bound["game_id"] = list(label_ids)
    bound = bound.set_index("game_id").loc[list(ids)]
    for side in ("home", "away"):
        key = f"{side}_team_id"
        if key in labels:
            if key not in features or bound[key].isna().any() or features[key].isna().any():
                raise PointModelError(f"Cannot verify {key} orientation")
            if bound[key].astype(str).tolist() != features[key].astype(str).tolist():
                raise PointModelError(f"{key} orientation differs between features and outcomes")
    try:
        scores = bound.loc[:, ["home_score", "away_score"]].to_numpy(dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise PointModelError("Labels require numeric home_score and away_score") from exc
    if (not np.isfinite(scores).all() or (scores < 0).any()
            or (scores != np.floor(scores)).any() or (scores[:, 0] == scores[:, 1]).any()):
        raise PointModelError("Labels must be nonnegative integer, untied full-game NBA final scores")
    return np.column_stack((scores[:, 0] - scores[:, 1], scores[:, 0] + scores[:, 1])), ids


def _params(family: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
    supplied = dict(supplied or {})
    if family in ("league", "elo"):
        if supplied:
            raise PointModelError(f"{family} has no tunable parameters in the frozen screen")
        return {}
    if family == "ridge":
        if set(supplied).difference({"alpha"}) or supplied.get("alpha", 10.0) not in (10, 100):
            raise PointModelError("Ridge screen is bounded to alpha 10 or 100")
        return {"alpha": float(supplied.get("alpha", 10.0))}
    if family == "hgb":
        if (set(supplied).difference({"l2_regularization"})
                or supplied.get("l2_regularization", 10.0) not in (10, 50)):
            raise PointModelError("HGB screen is bounded to l2_regularization 10 or 50")
        return {**_HGB_FIXED, "l2_regularization": float(supplied.get("l2_regularization", 10.0))}
    raise PointModelError(f"Unsupported point-model family {family!r}")


@dataclass
class FittedPointModel:
    """Serializable fitted artifact; no transforms refit during prediction."""

    family: str
    params: dict[str, Any]
    feature_names: tuple[str, ...]
    training_game_ids: tuple[str, ...]
    training_identity_sha256: str
    estimators: dict[str, Any] = field(default_factory=dict)
    diagnostic_coefficients: dict[str, Any] = field(default_factory=dict)
    screen_version: str = SCREEN_VERSION

    def predict_margin_total(self, features_df: pd.DataFrame) -> np.ndarray:
        """Predict HOME-minus-AWAY margin and full-game total without rounding."""
        ids = _game_ids(features_df, "prediction features")
        if not ids:
            return np.empty((0, 2), dtype=np.float64)
        if self.family == "league":
            predicted = np.tile(self.estimators["mean_margin_total"], (len(ids), 1))
        elif self.family == "elo":
            values = _numeric_features(features_df, self.feature_names)
            difference = values[:, 0] - values[:, 1]
            difference = np.where(np.isnan(difference), self.estimators["elo_difference_median"], difference)
            margin = self.estimators["margin_intercept"] + self.estimators["margin_slope"] * difference
            predicted = np.column_stack((margin, np.full(len(ids), self.estimators["mean_total"])))
        elif self.family == "ridge":
            values = _numeric_features(features_df, self.feature_names)
            predicted = self.estimators["margin_total"].predict(values)
        elif self.family == "hgb":
            values = _numeric_features(features_df, self.feature_names)
            with threadpool_limits(limits=1, user_api="openmp"):
                predicted = np.column_stack((self.estimators["margin"].predict(values),
                                             self.estimators["total"].predict(values)))
        else:
            raise PointModelError("Fitted artifact has an unknown family")
        if predicted.shape != (len(ids), 2) or not np.isfinite(predicted).all():
            raise PointModelError("Point model returned nonfinite or misaligned margin/total predictions")
        return np.asarray(predicted, dtype=np.float64)

    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        """Return coherent HOME, AWAY expectations; never clip or round means."""
        margin_total = self.predict_margin_total(features_df)
        margin, total = margin_total[:, 0], margin_total[:, 1]
        scores = np.column_stack(((total + margin) / 2, (total - margin) / 2))
        if not np.isfinite(scores).all():
            raise PointModelError("Derived HOME, AWAY expectations are nonfinite")
        return scores


def _linear_coefficients(pipeline: Pipeline, feature_names: tuple[str, ...]) -> dict[str, Any]:
    scaler, fitted = pipeline.named_steps["scaler"], pipeline.named_steps["model"]
    raw_coefficients = fitted.coef_ / scaler.scale_[None, :]
    raw_intercepts = fitted.intercept_ - raw_coefficients @ scaler.mean_
    return {
        "interpretation": "Associations conditional on other included features; not causal effects. "
                          "Original-unit coefficients apply after training-median imputation.",
        "targetColumns": ["HOME_MINUS_AWAY_MARGIN", "TOTAL"],
        "featureNames": list(feature_names),
        "standardizedCoefficients": fitted.coef_.tolist(),
        "originalUnitCoefficients": raw_coefficients.tolist(),
        "originalUnitIntercepts": raw_intercepts.tolist(),
        "trainingImputationValues": pipeline.named_steps["imputer"].statistics_.tolist(),
        "allMissingTrainingFeatures": [name for name, count in
                                      zip(feature_names, pipeline._nba_observed_counts) if not count],
    }


def fit_model(family: str, params: dict[str, Any] | None, features_df: pd.DataFrame,
              labels_df: pd.DataFrame) -> FittedPointModel:
    """Fit one predeclared configuration using only supplied earlier-game rows.

    The runner owns season-forward cutoffs, final OOT sealing and role selection.
    Game-ID joins prevent accidental row-order label swaps; supplied team IDs are
    checked for HOME/AWAY consistency. Chronology is not inferred from row order.
    """
    effective_params = _params(family, params)
    targets, ids = _targets(features_df, labels_df)
    columns = () if family == "league" else ("home_elo", "away_elo") if family == "elo" else tuple(FEATURE_COLUMNS)
    identity_payload = {"screenVersion": SCREEN_VERSION, "family": family,
                        "params": effective_params, "featureNames": list(columns),
                        "trainingGameIds": list(ids)}
    identity = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False).encode()).hexdigest()
    model = FittedPointModel(family, effective_params, columns, ids, identity)
    if family == "league":
        means = targets.mean(axis=0)
        model.estimators["mean_margin_total"] = means
        model.diagnostic_coefficients = {"meanHomeMargin": float(means[0]), "meanTotal": float(means[1]),
                                         "interpretation": "Earlier-game league scoring and home-court benchmark"}
        return model

    values = _numeric_features(features_df, columns)
    if family == "elo":
        difference = values[:, 0] - values[:, 1]
        median = float(np.nanmedian(difference)) if np.isfinite(difference).any() else 0.0
        difference = np.where(np.isnan(difference), median, difference)
        centered = difference - difference.mean()
        variance_sum = float(centered @ centered)
        slope = float(centered @ (targets[:, 0] - targets[:, 0].mean()) / variance_sum) if variance_sum > 0 else 0.0
        intercept = float(targets[:, 0].mean() - slope * difference.mean())
        model.estimators = {"elo_difference_median": median, "margin_slope": slope,
                            "margin_intercept": intercept, "mean_total": float(targets[:, 1].mean())}
        model.diagnostic_coefficients = {
            "target": "HOME_MINUS_AWAY_MARGIN", "feature": "home_elo_minus_away_elo",
            "coefficient": slope, "intercept": intercept, "constantTotal": float(targets[:, 1].mean()),
            "trainingDifferenceMedian": median,
            "interpretation": "Training-only OLS association; Elo ratings themselves come from earlier games. "
                              "Intercept represents learned league home advantage, not a causal estimate.",
        }
        return model

    if family == "ridge":
        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=effective_params["alpha"], solver="svd")),
        ])
        pipeline.fit(values, targets)
        pipeline._nba_observed_counts = np.isfinite(values).sum(axis=0)
        model.estimators["margin_total"] = pipeline
        model.diagnostic_coefficients = _linear_coefficients(pipeline, columns)
        return model

    # No validation or OOT rows are supplied to the estimators. Early stopping is
    # disabled, so sklearn cannot create a random row-wise validation partition.
    for target_index, target_name in enumerate(("margin", "total")):
        estimator = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", HistGradientBoostingRegressor(**effective_params)),
        ])
        with threadpool_limits(limits=1, user_api="openmp"):
            estimator.fit(values, targets[:, target_index])
        model.estimators[target_name] = estimator
    model.diagnostic_coefficients = {
        "status": "NO_COEFFICIENTS_FOR_NONLINEAR_MODEL",
        "interpretation": "No impurity or causal importance claim. Any later permutation importance "
                          "must use an independently declared Development assessment population.",
        "allMissingTrainingFeatures": [name for name, count in zip(columns, np.isfinite(values).sum(axis=0)) if not count],
    }
    return model
