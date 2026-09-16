"""Bounded reduced-score NBA models for qualified historical research.

This additive module does not change the original 65-feature models or the
completed historical league/Elo pilot.  Only the supplied earlier-game rows
enter preprocessing and fitting.  Population admission, chronological roles,
and the final-assessment gate remain the runner's responsibility.  These are
margin/total point models, not certified joint simulation distributions.
"""
from __future__ import annotations

from copy import deepcopy
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

from .historical_features import historical_feature_contract
from .models import (FittedPointModel, PointModelError, _linear_coefficients,
                     _numeric_features, _params, _targets)


SCREEN_VERSION = "NBA_GEN1_RECENT_REDUCED_POINT_SCREEN_V1"
SCREEN_CANDIDATES = (
    {"family": "ridge", "params": {"alpha": 10.0}},
    {"family": "ridge", "params": {"alpha": 100.0}},
    {"family": "hgb", "params": {"l2_regularization": 10.0}},
    {"family": "hgb", "params": {"l2_regularization": 50.0}},
)


def _contract(feature_names: tuple[str, ...] | None,
              supplied: dict[str, Any] | None) -> tuple[tuple[str, ...], dict[str, Any]]:
    # The additive recent contract is the default.  The frozen historical
    # declaration remains explicitly supported for reproducibility; arbitrary
    # source columns or ungoverned, outcome-selected feature subsets are not.
    from .recent_features import recent_feature_contract

    recent = recent_feature_contract()
    candidates = (recent, historical_feature_contract())
    contract = deepcopy(recent if supplied is None else supplied)
    if not isinstance(contract, dict) or not any(contract == item for item in candidates):
        raise PointModelError("Feature contract must exactly match a governed reduced NBA declaration")
    declared = tuple(contract["numericFeatures"])
    if feature_names is None:
        feature_names = declared
    if not isinstance(feature_names, tuple) or feature_names != declared:
        raise PointModelError("Feature names must exactly preserve the governed numeric-feature tuple")
    if len(feature_names) != len(set(feature_names)):
        raise PointModelError("Governed feature names must be unique")
    return feature_names, contract


def _orientation(frame: pd.DataFrame, label: str) -> None:
    for side in ("home", "away"):
        key = f"{side}_team_id"
        if key not in frame or frame[key].isna().any() or any(
                not isinstance(value, str) or not value.strip() for value in frame[key]):
            raise PointModelError(f"{label} requires explicit normalized {key}")
    if (frame["home_team_id"] == frame["away_team_id"]).any():
        raise PointModelError(f"{label} home and away identities must differ")
    if "neutral_site" in frame and frame["neutral_site"].fillna(True).astype(bool).any():
        raise PointModelError("Neutral history rows cannot become home/away model targets")
    if "target_eligible" in frame and not frame["target_eligible"].fillna(False).astype(bool).all():
        raise PointModelError("Ineligible history rows cannot become model targets")


def _array_hash(values: np.ndarray) -> str:
    canonical = np.asarray(values, dtype="<f8").copy(order="C")
    canonical[np.isnan(canonical)] = np.nan
    shape = json.dumps(list(canonical.shape), separators=(",", ":")).encode()
    return hashlib.sha256(shape + b"\n" + canonical.tobytes(order="C")).hexdigest()


@dataclass
class FittedReducedPointModel(FittedPointModel):
    """Serializable point model with a copied feature contract and value binding."""

    screen_version: str = SCREEN_VERSION
    feature_contract: dict[str, Any] = field(default_factory=dict)
    feature_contract_sha256: str = ""
    training_feature_values_sha256: str = ""
    training_target_values_sha256: str = ""


def fit_reduced_model(family: str, params: dict[str, Any] | None,
                      train_features: pd.DataFrame, labels: pd.DataFrame, *,
                      feature_names: tuple[str, ...] | None = None,
                      feature_contract: dict[str, Any] | None = None) -> FittedReducedPointModel:
    """Fit one declared Ridge or HGB configuration on intact earlier games.

    Features may retain metadata and targets for joins; only the exact governed
    numeric tuple enters the estimators.  HOME/AWAY target orientation and game
    identity are checked before label alignment.  Training-only medians handle
    missing history.  Columns wholly absent in training are explicitly listed
    and represented by the existing imputer's zero placeholder, not invented
    basketball observations.  Prediction never refits any transformer.
    """
    if family not in ("ridge", "hgb"):
        raise PointModelError("Reduced screen is bounded to Ridge and HGB; reuse frozen league/Elo methods separately")
    effective_params = _params(family, params)
    columns, contract = _contract(feature_names, feature_contract)
    _orientation(train_features, "features")
    _orientation(labels, "labels")
    targets, ids = _targets(train_features, labels)
    values = _numeric_features(train_features, columns)
    feature_hash, target_hash = _array_hash(values), _array_hash(targets)
    identity_payload = {
        "screenVersion": SCREEN_VERSION, "family": family, "params": effective_params,
        "featureNames": list(columns), "featureContractSha256": contract["sha256"],
        "trainingGameIds": list(ids), "trainingFeatureValuesSha256": feature_hash,
        "trainingTargetValuesSha256": target_hash,
    }
    identity = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False).encode()).hexdigest()
    model = FittedReducedPointModel(
        family=family, params=effective_params, feature_names=columns,
        training_game_ids=ids, training_identity_sha256=identity,
        feature_contract=contract, feature_contract_sha256=contract["sha256"],
        training_feature_values_sha256=feature_hash, training_target_values_sha256=target_hash,
    )
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
    else:
        # No random validation split or early stopping: the caller supplies
        # training games only, and selection games never enter these objects.
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
            "interpretation": "No causal or impurity importance claim. Any permutation diagnostic must use a separately declared population.",
            "allMissingTrainingFeatures": [name for name, count in zip(columns, np.isfinite(values).sum(axis=0)) if not count],
            "trainingImputationValues": model.estimators["margin"].named_steps["imputer"].statistics_.tolist(),
        }
    model.diagnostic_coefficients.update(
        featureContractSha256=model.feature_contract_sha256,
        probabilitySemantics="No probability calibrator or joint score distribution is fitted by this point-model module.",
    )
    return model
