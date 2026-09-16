"""Bounded chronological candidate screen and assessment for UFC Gen 1."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .core import ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES

EPS = 1e-6
RANDOM_SEED = 20260916
OOF_START_YEAR = 2017

CANDIDATE_GRID: dict[str, list[dict[str, Any]]] = {
    "LOGISTIC": [{"C": 0.1}, {"C": 1.0}],
    "HGB": [
        {"learning_rate": 0.05, "max_iter": 160, "max_leaf_nodes": 15, "l2_regularization": 1.0},
        {"learning_rate": 0.05, "max_iter": 200, "max_leaf_nodes": 31, "l2_regularization": 2.0},
    ],
}


def _clip(values: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), EPS, 1.0 - EPS)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    y, p = np.asarray(y), _clip(p)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    result = 0.0
    for index in range(bins):
        mask = (p >= edges[index]) & (p < edges[index + 1] if index < bins - 1 else p <= edges[index + 1])
        if mask.any():
            result += float(mask.mean()) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return result if total else math.nan


def calibration_intercept_slope(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    p = _clip(p)
    logit = np.log(p / (1.0 - p)).reshape(-1, 1)
    if len(np.unique(y)) < 2:
        return math.nan, math.nan
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000, random_state=RANDOM_SEED)
    model.fit(logit, y)
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = _clip(p)
    intercept, slope = calibration_intercept_slope(y, p)
    return {
        "n": int(len(y)),
        "logLoss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "ece10": float(expected_calibration_error(y, p)),
        "calibrationIntercept": intercept,
        "calibrationSlope": slope,
        "rocAuc": float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else math.nan,
        "accuracy": float(accuracy_score(y, p >= 0.5)),
        "meanProbability": float(p.mean()),
        "observedRate": float(np.asarray(y).mean()),
    }


def reliability_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    p = _clip(p)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for index in range(bins):
        mask = (p >= edges[index]) & (p < edges[index + 1] if index < bins - 1 else p <= edges[index + 1])
        rows.append(
            {
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "n": int(mask.sum()),
                "meanPredicted": float(p[mask].mean()) if mask.any() else None,
                "observed": float(np.asarray(y)[mask].mean()) if mask.any() else None,
            }
        )
    return rows


def _pipeline(kind: str, params: dict[str, Any]) -> Pipeline:
    numeric_steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median", add_indicator=True))]
    if kind == "LOGISTIC":
        numeric_steps.append(("scale", StandardScaler()))
    preprocessor = ColumnTransformer(
        [
            ("numeric", Pipeline(numeric_steps), list(NUMERIC_FEATURES)),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
    )
    if kind == "LOGISTIC":
        estimator: Any = LogisticRegression(
            C=float(params["C"]),
            penalty="l2",
            solver="lbfgs",
            max_iter=2000,
            random_state=RANDOM_SEED,
        )
    elif kind == "HGB":
        estimator = HistGradientBoostingClassifier(
            learning_rate=float(params["learning_rate"]),
            max_iter=int(params["max_iter"]),
            max_leaf_nodes=int(params["max_leaf_nodes"]),
            l2_regularization=float(params["l2_regularization"]),
            random_state=RANDOM_SEED,
        )
    else:
        raise ValueError(f"UNKNOWN_MODEL_KIND:{kind}")
    return Pipeline([("preprocess", preprocessor), ("model", estimator)])


class PlattCalibrator:
    def __init__(self) -> None:
        self.model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000, random_state=RANDOM_SEED)

    def fit(self, probabilities: np.ndarray, y: np.ndarray) -> "PlattCalibrator":
        p = _clip(probabilities)
        self.model.fit(np.log(p / (1.0 - p)).reshape(-1, 1), y)
        return self

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        p = _clip(probabilities)
        return self.model.predict_proba(np.log(p / (1.0 - p)).reshape(-1, 1))[:, 1]


@dataclass
class FittedCandidate:
    kind: str
    params: dict[str, Any]
    pipeline: Pipeline
    calibrator: PlattCalibrator
    oof_metrics_raw: dict[str, float]
    oof_metrics_calibrated: dict[str, float]
    fold_rows: list[dict[str, Any]]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.calibrator.predict(self.pipeline.predict_proba(frame[list(ALL_FEATURES)])[:, 1])


def _chronological_oof(frame: pd.DataFrame, kind: str, params: dict[str, Any], end_year: int) -> tuple[np.ndarray, np.ndarray, list[str], list[dict[str, Any]]]:
    predictions: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    ids: list[str] = []
    folds: list[dict[str, Any]] = []
    for year in range(OOF_START_YEAR, end_year + 1):
        train = frame[frame["event_date"].dt.year < year]
        assessment = frame[frame["event_date"].dt.year == year]
        if len(train) < 1000 or assessment.empty:
            continue
        model = _pipeline(kind, params)
        model.fit(train[list(ALL_FEATURES)], train["target_a_win"].astype(int))
        p = model.predict_proba(assessment[list(ALL_FEATURES)])[:, 1]
        predictions.append(p)
        targets.append(assessment["target_a_win"].astype(int).to_numpy())
        ids.extend(assessment["fight_id"].astype(str).tolist())
        folds.append(
            {
                "assessmentYear": year,
                "trainMaxDate": str(train["event_date"].max().date()),
                "trainRows": int(len(train)),
                "assessmentRows": int(len(assessment)),
                "trainAssessmentOverlap": False,
                "preprocessingFitRows": int(len(train)),
                "calibrationFitRows": 0,
            }
        )
    if not predictions:
        raise ValueError("NO_CHRONOLOGICAL_OOF_FOLDS")
    return np.concatenate(predictions), np.concatenate(targets), ids, folds


def tune_and_fit(frame: pd.DataFrame, kind: str, end_year: int) -> tuple[FittedCandidate, list[dict[str, Any]]]:
    grid_results = []
    cache: dict[str, tuple[np.ndarray, np.ndarray, list[str], list[dict[str, Any]]]] = {}
    for params in CANDIDATE_GRID[kind]:
        key = repr(sorted(params.items()))
        p, y, ids, folds = _chronological_oof(frame, kind, params, end_year)
        result = {"kind": kind, "params": params, "rawOof": metrics(y, p), "folds": folds}
        grid_results.append(result)
        cache[key] = (p, y, ids, folds)
    chosen = min(grid_results, key=lambda value: (value["rawOof"]["logLoss"], value["rawOof"]["brier"], repr(value["params"])))
    key = repr(sorted(chosen["params"].items()))
    p, y, ids, folds = cache[key]
    calibrator = PlattCalibrator().fit(p, y)
    calibrated = calibrator.predict(p)
    model = _pipeline(kind, chosen["params"])
    model.fit(frame[list(ALL_FEATURES)], frame["target_a_win"].astype(int))
    fitted = FittedCandidate(
        kind=kind,
        params=chosen["params"],
        pipeline=model,
        calibrator=calibrator,
        oof_metrics_raw=metrics(y, p),
        oof_metrics_calibrated=metrics(y, calibrated),
        fold_rows=folds,
    )
    return fitted, grid_results


def _candidate_predictions(fitted: dict[str, FittedCandidate], frame: pd.DataFrame) -> dict[str, np.ndarray]:
    values = {kind: candidate.predict(frame) for kind, candidate in fitted.items()}
    values["ENSEMBLE_50_50"] = (values["LOGISTIC"] + values["HGB"]) / 2.0
    return values


def select_finalist(feature_table: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    dev = feature_table[feature_table["event_date"] <= pd.Timestamp("2022-12-31")].copy()
    validation = feature_table[
        (feature_table["event_date"] >= pd.Timestamp("2023-01-01"))
        & (feature_table["event_date"] <= pd.Timestamp("2024-12-31"))
    ].copy()
    if dev.empty or validation.empty or feature_table["event_date"].max() > pd.Timestamp("2024-12-31"):
        raise ValueError("SELECTION_TABLE_ROLE_VIOLATION")
    fitted: dict[str, FittedCandidate] = {}
    grids = {}
    for kind in ("LOGISTIC", "HGB"):
        fitted[kind], grids[kind] = tune_and_fit(dev, kind, 2022)
    y = validation["target_a_win"].astype(int).to_numpy()
    predictions = _candidate_predictions(fitted, validation)
    predictions["ELO"] = validation["elo_probability_a"].to_numpy(dtype=float)
    assessments = {name: metrics(y, p) for name, p in predictions.items()}

    # The ensemble is eligible only for a material win over both components.
    ensemble_ok = (
        assessments["ENSEMBLE_50_50"]["logLoss"]
        <= min(assessments["LOGISTIC"]["logLoss"], assessments["HGB"]["logLoss"]) - 0.003
        and assessments["ENSEMBLE_50_50"]["brier"]
        <= min(assessments["LOGISTIC"]["brier"], assessments["HGB"]["brier"])
    )
    eligible = ["ELO", "LOGISTIC", "HGB"] + (["ENSEMBLE_50_50"] if ensemble_ok else [])
    proper_gate = [
        name
        for name in eligible
        if name == "ELO"
        or (
            assessments[name]["brier"] <= assessments["ELO"]["brier"]
            and assessments[name]["ece10"] <= assessments["ELO"]["ece10"] + 0.005
        )
    ]
    best_loss = min(assessments[name]["logLoss"] for name in proper_gate)
    near_best = [name for name in proper_gate if assessments[name]["logLoss"] <= best_loss + 0.002]
    simplicity = {"ELO": 0, "LOGISTIC": 1, "HGB": 2, "ENSEMBLE_50_50": 3}
    selected = min(near_best, key=lambda name: simplicity[name])

    validation_predictions = validation[
        ["fight_id", "event_id", "event_date", "fighter_a_id", "fighter_b_id", "weight_class", "target_a_win"]
    ].copy()
    for name, p in predictions.items():
        validation_predictions[f"p_{name.lower()}"] = p

    importance = {}
    for kind, candidate in fitted.items():
        result = permutation_importance(
            candidate.pipeline,
            validation[list(ALL_FEATURES)],
            y,
            scoring="neg_log_loss",
            n_repeats=5,
            random_state=RANDOM_SEED,
        )
        importance[kind] = sorted(
            (
                {"feature": feature, "meanDecreaseInNegLogLoss": float(mean), "std": float(std)}
                for feature, mean, std in zip(ALL_FEATURES, result.importances_mean, result.importances_std)
            ),
            key=lambda row: abs(row["meanDecreaseInNegLogLoss"]),
            reverse=True,
        )

    selection = {
        "developmentRows": int(len(dev)),
        "validationRows": int(len(validation)),
        "candidateGrid": grids,
        "validationMetrics": assessments,
        "reliability": {name: reliability_table(y, p) for name, p in predictions.items()},
        "ensembleEligible": ensemble_ok,
        "properScoreEligible": proper_gate,
        "nearBestWithinLogLoss002": near_best,
        "selected": selected,
        "selectionRule": {
            "primary": "lowest Validation log loss",
            "guardrails": "Brier no worse than Elo; ECE no more than 0.005 worse than Elo",
            "simplicityTie": "within 0.002 log loss choose ELO, then LOGISTIC, HGB, ENSEMBLE",
            "ensemble": "requires >=0.003 log-loss gain over both members and no Brier degradation",
        },
        "featureImportance": importance,
    }
    bundle = {"fitted": fitted, "selected": selected, "validationPredictions": validation_predictions}
    return selection, bundle


def refit_selected(feature_table: pd.DataFrame, selected: str, selected_params: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pre_oot = feature_table[feature_table["event_date"] <= pd.Timestamp("2024-12-31")].copy()
    if selected == "ELO":
        return {"selected": selected, "components": {}}
    needed = ("LOGISTIC", "HGB") if selected == "ENSEMBLE_50_50" else (selected,)
    components = {}
    for kind in needed:
        params = selected_params[kind]
        p, y, ids, folds = _chronological_oof(pre_oot, kind, params, 2024)
        calibrator = PlattCalibrator().fit(p, y)
        pipeline = _pipeline(kind, params)
        pipeline.fit(pre_oot[list(ALL_FEATURES)], pre_oot["target_a_win"].astype(int))
        components[kind] = {
            "pipeline": pipeline,
            "calibrator": calibrator,
            "oofMetricsRaw": metrics(y, p),
            "oofMetricsCalibrated": metrics(y, calibrator.predict(p)),
            "folds": folds,
            "oofIds": ids,
        }
    return {"selected": selected, "components": components}


def predict_selected(artifact: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    selected = artifact["selected"]
    if selected == "ELO":
        return frame["elo_probability_a"].to_numpy(dtype=float)
    values = []
    for kind, component in artifact["components"].items():
        raw = component["pipeline"].predict_proba(frame[list(ALL_FEATURES)])[:, 1]
        values.append(component["calibrator"].predict(raw))
    return np.mean(values, axis=0)


def block_bootstrap_difference(frame: pd.DataFrame, candidate: np.ndarray, baseline: np.ndarray, draws: int = 2000) -> dict[str, Any]:
    y = frame["target_a_win"].astype(int).to_numpy()
    blocks = frame["event_date"].dt.to_period("M").astype(str).to_numpy()
    unique = np.unique(blocks)
    rng = np.random.default_rng(RANDOM_SEED)
    ll_delta, brier_delta = [], []
    for _ in range(draws):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(blocks == block) for block in sampled])
        ll_delta.append(log_loss(y[indices], _clip(candidate[indices]), labels=[0, 1]) - log_loss(y[indices], _clip(baseline[indices]), labels=[0, 1]))
        brier_delta.append(brier_score_loss(y[indices], _clip(candidate[indices])) - brier_score_loss(y[indices], _clip(baseline[indices])))
    return {
        "unit": "calendar_month",
        "blocks": int(len(unique)),
        "draws": draws,
        "candidateMinusBaselineLogLoss": {
            "estimate": float(log_loss(y, _clip(candidate), labels=[0, 1]) - log_loss(y, _clip(baseline), labels=[0, 1])),
            "ci95": [float(np.quantile(ll_delta, 0.025)), float(np.quantile(ll_delta, 0.975))],
        },
        "candidateMinusBaselineBrier": {
            "estimate": float(brier_score_loss(y, _clip(candidate)) - brier_score_loss(y, _clip(baseline))),
            "ci95": [float(np.quantile(brier_delta, 0.025)), float(np.quantile(brier_delta, 0.975))],
        },
    }


def _segment_metrics(frame: pd.DataFrame, p: np.ndarray, mask: np.ndarray) -> dict[str, Any] | None:
    if int(mask.sum()) < 25:
        return None
    y = frame.loc[mask, "target_a_win"].astype(int).to_numpy()
    return metrics(y, np.asarray(p)[mask])


def diagnostics(frame: pd.DataFrame, p: np.ndarray) -> dict[str, Any]:
    p = np.asarray(p)
    result: dict[str, Any] = {
        "overall": metrics(frame["target_a_win"].astype(int).to_numpy(), p),
        "reliability": reliability_table(frame["target_a_win"].astype(int).to_numpy(), p),
        "probabilityQuantiles": {str(q): float(np.quantile(p, q)) for q in (0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1)},
        "segments": {},
    }
    segments = result["segments"]
    for year in sorted(frame["event_date"].dt.year.unique()):
        mask = (frame["event_date"].dt.year == year).to_numpy()
        segments[f"year:{year}"] = _segment_metrics(frame, p, mask)
    for weight_class, count in frame["weight_class"].value_counts().items():
        if count >= 25:
            mask = (frame["weight_class"] == weight_class).to_numpy()
            segments[f"weightClass:{weight_class}"] = _segment_metrics(frame, p, mask)
    experience_gap = frame["experience_diff"].abs()
    for label, lower, upper in (("0_2", 0, 2), ("2_6", 2, 6), ("6_plus", 6, math.inf)):
        mask = ((experience_gap >= lower) & (experience_gap < upper)).to_numpy()
        segments[f"experienceGap:{label}"] = _segment_metrics(frame, p, mask)
    layoff_gap = frame["layoff_days_diff"].abs()
    for label, lower, upper in (("0_90", 0, 90), ("90_365", 90, 365), ("365_plus", 365, math.inf)):
        mask = ((layoff_gap >= lower) & (layoff_gap < upper)).to_numpy()
        segments[f"layoffGap:{label}"] = _segment_metrics(frame, p, mask)
    segments["rematch"] = _segment_metrics(frame, p, (frame["rematch_count"] > 0).to_numpy())
    segments["firstMeeting"] = _segment_metrics(frame, p, (frame["rematch_count"] == 0).to_numpy())
    segments["fiveRoundProxy"] = _segment_metrics(frame, p, (frame["five_round_indicator"] == 1).to_numpy())
    segments["threeRound"] = _segment_metrics(frame, p, (frame["five_round_indicator"] == 0).to_numpy())
    missing_mask = ((frame["layoff_missing_a"] == 1) | (frame["layoff_missing_b"] == 1)).to_numpy()
    segments["missingLayoff"] = _segment_metrics(frame, p, missing_mask)
    confidence = np.maximum(p, 1.0 - p)
    picked_win = np.where(p >= 0.5, frame["target_a_win"].to_numpy(), 1 - frame["target_a_win"].to_numpy())
    result["favoriteUnderdog"] = {
        "pickedFavoriteMeanConfidence": float(confidence.mean()),
        "pickedFavoriteObservedWinRate": float(picked_win.mean()),
        "underdogProbabilityMean": float((1.0 - confidence).mean()),
        "denominator": int(len(frame)),
    }
    result["unsupportedDiagnostics"] = {
        "reachHeightMismatch": "excluded because only current-snapshot physical attributes are available",
        "titleVsNonTitle": "true title flag unavailable; five-round status reported only as a proxy",
    }
    return result


def reversal_probability(artifact: dict[str, Any], frame_one_row: pd.DataFrame, requested_first_id: str) -> float:
    canonical_a = str(frame_one_row.iloc[0]["fighter_a_id"])
    p_a = float(predict_selected(artifact, frame_one_row)[0])
    return p_a if requested_first_id == canonical_a else 1.0 - p_a


def save_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path, compress=3)


def load_artifact(path: Path) -> dict[str, Any]:
    return joblib.load(path)

