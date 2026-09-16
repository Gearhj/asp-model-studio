"""One bounded ordinary-rest availability treatment for the frozen Ridge recipe.

Raw calendar gaps are retained in audit records. Across an excluded offseason,
or outside fitting support, they are not supplied as ordinary-rest covariates.
No score is clipped. Elo and the remaining numerical inputs are untouched.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .models import PointModelError, _numeric_features, _targets, _linear_coefficients
from .recent_features import recent_feature_contract
from .recent_models import FittedReducedPointModel, _orientation, _array_hash

VERSION = "NBA_GEN1_ORDINARY_REST_RIDGE_A100_V1"
CHANGED_COLUMNS = tuple(f"{s}_{n}" for s in ("home", "away")
                        for n in ("rest_days", "rest_known", "back_to_back")) + ("difference_rest_days",)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def feature_contract():
    parent = recent_feature_contract()
    result = {
        "schema": "nba-gen1-ordinary-rest-features-v1", "parentSha256": parent["sha256"],
        "numericFeatures": parent["numericFeatures"], "changedColumns": list(CHANGED_COLUMNS),
        "ordinaryRest": "Known finite calendar gap in [0,fittingSupport.maximumDays] with at least one earlier current-season game. Shared HOME/AWAY support learned from fitting target rows only.",
        "unavailable": "Season opener, missing recorded date, or gap beyond fitting support: rest_days=NaN, rest_known=0, back_to_back=0. Raw gap and reason retained outside model inputs.",
        "difference": "Recompute difference_rest_days before train-only median imputation. When either side is missing, this difference is missing and independently imputed; it is not claimed to equal the difference of separately imputed side values.",
        "semantics": "Spacing of admitted regular games and Cup date-only context; no all-competition physical-rest claim, no learned hiatus effect.",
        "otherInputs": "All other 71 of 78 numeric inputs, chronology and target exclusion remain governed by the parent contract.",
        "probabilities": "Ridge supplies points only. Chronological Elo probabilities remain separate; no shared simulation population.",
    }
    result["sha256"] = _hash(result)
    return result


def _side(frame, side):
    values = {}
    for name in ("rest_days", "rest_known", "season_games_played"):
        key = f"{side}_{name}"
        if key not in frame:
            raise PointModelError(f"Missing rest-support input {key}")
        values[name] = frame[key].to_numpy(dtype=float)
    gap, known, played = (values[n] for n in ("rest_days", "rest_known", "season_games_played"))
    if (not np.isin(known, (0, 1)).all() or not np.isfinite(played).all()
            or (played < 0).any() or (played != np.floor(played)).any()
            or np.isinf(gap).any() or (gap[np.isfinite(gap)] < 0).any()
            or (gap[np.isfinite(gap)] != np.floor(gap[np.isfinite(gap)])).any()
            or ((known == 1) & ~np.isfinite(gap)).any()):
        raise PointModelError("Malformed recorded rest/support values; cannot hide invalid inputs as unavailable")
    return gap, known, played


def learn_rest_support(train):
    _orientation(train, "rest-support fitting rows")
    observed = []
    counts = {}
    for side in ("home", "away"):
        gap, known, played = _side(train, side)
        eligible = (known == 1) & (played > 0) & np.isfinite(gap)
        observed.extend(gap[eligible].tolist())
        counts[side] = int(eligible.sum())
    if not observed:
        raise PointModelError("No observed within-season ordinary-rest fitting support")
    return {"schema": "nba-gen1-fitted-ordinary-rest-support-v1", "minimumDays": 0.0,
            "maximumDays": float(max(observed)), "observedTeamExposures": counts,
            "fittingGames": len(train), "fittingGameIdsSha256": _hash(train.game_id.astype(str).tolist()),
            "derivation": "Pooled HOME/AWAY finite known non-opener fitting inputs only; no outcome optimization."}


def transform_rest(frame, support):
    if not isinstance(support, dict):
        raise PointModelError("Frozen ordinary-rest fitting support is required")
    maximum = support.get("maximumDays")
    if (support.get("schema") != "nba-gen1-fitted-ordinary-rest-support-v1"
            or support.get("minimumDays") != 0 or not isinstance(maximum, (int, float))
            or isinstance(maximum, bool) or not np.isfinite(maximum) or maximum < 0
            or maximum != int(maximum)):
        raise PointModelError("Frozen ordinary-rest fitting support is required")
    treated = frame.copy(deep=True)
    audit = frame[["game_id"]].copy()
    for side in ("home", "away"):
        gap, known, played = _side(frame, side)
        eligible = (known == 1) & (played > 0) & np.isfinite(gap) & (gap <= maximum)
        reasons = np.select([played == 0, known == 0, gap > maximum],
                            ["SEASON_OPENER_NO_ORDINARY_REST", "MISSING_RECORDED_DATE", "OUTSIDE_FITTING_REST_SUPPORT"],
                            default="ORDINARY_REST_SUPPORTED")
        for name in ("rest_days", "rest_known", "back_to_back"):
            audit[f"raw_{side}_{name}"] = frame[f"{side}_{name}"].to_numpy()
        audit[f"{side}_reason"] = reasons
        treated[f"{side}_rest_days"] = np.where(eligible, gap, np.nan)
        treated[f"{side}_rest_known"] = eligible.astype(int)
        treated[f"{side}_back_to_back"] = (eligible & (gap == 0)).astype(int)
        for name in ("rest_days", "rest_known", "back_to_back"):
            audit[f"treated_{side}_{name}"] = treated[f"{side}_{name}"].to_numpy()
    audit["raw_difference_rest_days"] = frame.difference_rest_days.to_numpy()
    treated["difference_rest_days"] = treated.home_rest_days - treated.away_rest_days
    audit["treated_difference_rest_days"] = treated.difference_rest_days.to_numpy()
    audit["both_ordinary_supported"] = ((audit.home_reason == "ORDINARY_REST_SUPPORTED")
                                         & (audit.away_reason == "ORDINARY_REST_SUPPORTED"))
    return treated, audit


@dataclass
class FittedRestPointModel(FittedReducedPointModel):
    rest_support: dict = field(default_factory=dict)
    raw_training_feature_values_sha256: str = ""

    def predict_margin_total(self, features_df):
        treated, _ = transform_rest(features_df, self.rest_support)
        return super().predict_margin_total(treated)

    def support_audit(self, features_df):
        return transform_rest(features_df, self.rest_support)[1]


def fit_rest_model(train, labels):
    """Refit the ONE alpha100 recipe; caller must supply only earlier games."""
    _orientation(train, "features")
    _orientation(labels, "labels")
    targets, ids = _targets(train, labels)
    support = learn_rest_support(train)
    treated, _ = transform_rest(train, support)
    contract = feature_contract()
    names = tuple(contract["numericFeatures"])
    values = _numeric_features(treated, names)
    raw_hash = _array_hash(_numeric_features(train, names))
    value_hash, target_hash = _array_hash(values), _array_hash(targets)
    identity = {"version": VERSION, "featureContractSha256": contract["sha256"],
                "params": {"alpha": 100.0}, "restSupport": support,
                "trainingGameIds": list(ids), "rawTrainingFeaturesSha256": raw_hash,
                "treatedTrainingFeaturesSha256": value_hash, "trainingTargetsSha256": target_hash}
    model = FittedRestPointModel(
        family="ridge", params={"alpha": 100.0}, feature_names=names, training_game_ids=ids,
        training_identity_sha256=_hash(identity), screen_version=VERSION,
        feature_contract=deepcopy(contract), feature_contract_sha256=contract["sha256"],
        training_feature_values_sha256=value_hash, training_target_values_sha256=target_hash,
        rest_support=deepcopy(support), raw_training_feature_values_sha256=raw_hash)
    pipeline = Pipeline([("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                         ("scaler", StandardScaler()), ("model", Ridge(alpha=100.0, solver="svd"))])
    pipeline.fit(values, targets)
    pipeline._nba_observed_counts = np.isfinite(values).sum(axis=0)
    model.estimators["margin_total"] = pipeline
    model.diagnostic_coefficients = _linear_coefficients(pipeline, names)
    model.diagnostic_coefficients.update(restSupport=support, featureContractSha256=contract["sha256"],
                                        probabilitySemantics="Independent Elo channel; no joint simulation fitted.")
    return model
