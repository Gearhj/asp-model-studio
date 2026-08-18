from __future__ import annotations

import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, Ridge

from .participation_contract import (
    BULLPEN_CANDIDATES,
    BULLPEN_CONTRACT_NAME,
    BULLPEN_FEATURES,
    BullpenDecisionEvidence,
    DEFAULT_MAX_ITER,
    DEFAULT_TOLERANCE,
    FINAL_EVALUATION_SEASON,
    HGB_LEARNING_RATE,
    HGB_MAX_DEPTH,
    HGB_MAX_ITER,
    LINEUP_CANDIDATES,
    LINEUP_CONTRACT_NAME,
    LINEUP_FEATURES,
    LOGISTIC_C_GRID,
    LineupDecisionEvidence,
    RANDOM_SEED,
    RIDGE_ALPHA_GRID,
    SELECTION_SEASON,
    STARTER_CANDIDATES,
    STARTER_CONTRACT_NAME,
    STARTER_FEATURES,
    StarterDecisionEvidence,
    bullpen_contract_payload,
    bullpen_decision,
    canonical_sha,
    lineup_contract_payload,
    lineup_decision,
    starter_contract_payload,
    starter_decision,
)
from .participation_features import BuiltParticipationFeatureViews
from .participation_metrics import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    bullpen_metrics,
    game_cluster_bootstrap_difference,
    lineup_metrics,
    per_row_binary_log_loss,
    starter_metrics,
)


TRAINING_SCHEMA_VERSION = "MLB_PARTICIPATION_TRAINING_V1"


class ParticipationTrainingError(RuntimeError):
    """Fail-closed error for a frozen Milestone B experiment."""


@dataclass(frozen=True)
class NumericPreprocessor:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    empty_in_training: tuple[bool, ...]

    @classmethod
    def fit(cls, table: pa.Table, feature_names: Sequence[str]) -> "NumericPreprocessor":
        matrix = _feature_matrix(table, feature_names)
        means: list[float] = []
        scales: list[float] = []
        empty: list[bool] = []
        for column in matrix.T:
            finite = np.isfinite(column)
            is_empty = not bool(np.any(finite))
            mean = float(np.mean(column[finite])) if not is_empty else 0.0
            imputed = np.where(finite, column, mean)
            scale = float(np.std(imputed, ddof=0))
            if not math.isfinite(scale) or scale <= 0.0:
                scale = 1.0
            means.append(mean)
            scales.append(scale)
            empty.append(is_empty)
        return cls(tuple(feature_names), tuple(means), tuple(scales), tuple(empty))

    def transform(self, table: pa.Table) -> np.ndarray:
        values = _feature_matrix(table, self.feature_names)
        means = np.asarray(self.means, dtype=np.float64)
        scales = np.asarray(self.scales, dtype=np.float64)
        output = (np.where(np.isfinite(values), values, means) - means) / scales
        if not np.isfinite(output).all():
            raise ParticipationTrainingError("numeric preprocessing produced non-finite values")
        return np.ascontiguousarray(output, dtype=np.float64)

    def state(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_PARTICIPATION_NUMERIC_PREPROCESSOR_V1",
            "featureNames": list(self.feature_names),
            "imputationMeans": list(self.means),
            "standardizationScales": list(self.scales),
            "emptyInTraining": list(self.empty_in_training),
            "fitScope": "TRAINING_ROWS_OF_THIS_FIT_ONLY",
        }


@dataclass(frozen=True)
class ComponentExperimentResult:
    component_type: str
    contract_name: str
    contract_sha: str
    descriptor: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    selected: dict[str, Any]
    folds: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]
    calibration: dict[str, Any] | None
    bootstrap: dict[str, Any] | None
    coverage: dict[str, Any]
    decision: dict[str, Any]
    predictions: dict[tuple[int, str], dict[str, np.ndarray]]
    model_states: dict[tuple[int, str], dict[str, Any]]


@dataclass(frozen=True)
class ParticipationExperimentResult:
    lineup: ComponentExperimentResult
    starter: ComponentExperimentResult
    bullpen: ComponentExperimentResult

    @property
    def components(self) -> tuple[ComponentExperimentResult, ...]:
        return (self.lineup, self.starter, self.bullpen)


def _values(table: pa.Table, name: str, *, dtype: Any) -> np.ndarray:
    if name not in table.column_names:
        raise ParticipationTrainingError(f"training table is missing column: {name}")
    try:
        raw = table[name].combine_chunks().to_pylist()
        if dtype is np.float64:
            raw = [np.nan if value is None else value for value in raw]
        return np.asarray(raw, dtype=dtype)
    except (TypeError, ValueError) as exc:
        raise ParticipationTrainingError(f"training column has incompatible values: {name}") from exc


def _feature_matrix(table: pa.Table, feature_names: Sequence[str]) -> np.ndarray:
    if not feature_names:
        return np.empty((table.num_rows, 0), dtype=np.float64)
    columns = [_values(table, name, dtype=np.float64)[:, None] for name in feature_names]
    return np.concatenate(columns, axis=1)


def _subset(table: pa.Table, mask: np.ndarray) -> pa.Table:
    if mask.dtype != np.bool_ or mask.ndim != 1 or mask.size != table.num_rows:
        raise ParticipationTrainingError("table mask is invalid")
    return table.filter(pa.array(mask))


def _season(table: pa.Table, season: int) -> pa.Table:
    seasons = _values(table, "season", dtype=np.int64)
    selected = _subset(table, seasons == season)
    if selected.num_rows == 0:
        raise ParticipationTrainingError(f"training table has no rows for season {season}")
    return selected


def _train_through(table: pa.Table, season: int) -> pa.Table:
    seasons = _values(table, "season", dtype=np.int64)
    selected = _subset(table, (seasons >= 2023) & (seasons <= season))
    if selected.num_rows == 0:
        raise ParticipationTrainingError("training fold is empty")
    return selected


def _date_atomic_inner_2023(table: pa.Table) -> tuple[pa.Table, pa.Table, dict[str, Any]]:
    source = _season(table, 2023)
    dates = _values(source, "game_date", dtype=object)
    ordered, counts = np.unique(dates, return_counts=True)
    if ordered.size < 2:
        raise ParticipationTrainingError("inner 2023 tuning requires at least two dates")
    cumulative = np.cumsum(counts)
    crossing = int(np.searchsorted(cumulative, 0.8 * dates.size, side="left"))
    crossing = min(crossing, ordered.size - 2)
    last_train = ordered[crossing]
    train_mask = dates <= last_train
    validation_mask = dates > last_train
    train = _subset(source, train_mask)
    validation = _subset(source, validation_mask)
    return train, validation, {
        "schemaVersion": "MLB_PARTICIPATION_DATE_ATOMIC_INNER_2023_V1",
        "season": 2023,
        "lastTrainingDate": str(last_train),
        "firstValidationDate": str(np.min(dates[validation_mask])),
        "trainingRows": train.num_rows,
        "validationRows": validation.num_rows,
        "dateAtomic": True,
        "selectionUses2024Or2025": False,
    }


def _fit_logistic(
    train: pa.Table,
    features: Sequence[str],
    target: str,
    *,
    c_value: float,
) -> tuple[NumericPreprocessor, LogisticRegression, dict[str, Any]]:
    started = time.monotonic()
    preprocessor = NumericPreprocessor.fit(train, features)
    matrix = preprocessor.transform(train)
    labels = _values(train, target, dtype=np.int64)
    if np.unique(labels).size != 2:
        raise ParticipationTrainingError("binary logistic training requires both classes")
    estimator = LogisticRegression(
        C=c_value,
        penalty="l2",
        solver="lbfgs",
        max_iter=DEFAULT_MAX_ITER,
        tol=DEFAULT_TOLERANCE,
        random_state=RANDOM_SEED,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(matrix, labels)
    converged = not any(issubclass(item.category, ConvergenceWarning) for item in caught)
    if not converged or int(np.max(estimator.n_iter_)) >= DEFAULT_MAX_ITER:
        raise ParticipationTrainingError("regularized logistic failed its convergence gate")
    elapsed = time.monotonic() - started
    if elapsed > 5_400:
        raise ParticipationTrainingError("regularized logistic exceeded the 90-minute fit gate")
    state = {
        "schemaVersion": "MLB_PARTICIPATION_LOGISTIC_MODEL_V1",
        "estimator": "sklearn.linear_model.LogisticRegression",
        "C": c_value,
        "maxIter": DEFAULT_MAX_ITER,
        "tolerance": DEFAULT_TOLERANCE,
        "nIter": int(np.max(estimator.n_iter_)),
        "runtimeSeconds": elapsed,
        "converged": True,
        "classes": estimator.classes_.astype(int).tolist(),
        "coefficients": estimator.coef_.tolist(),
        "intercepts": estimator.intercept_.tolist(),
        "preprocessor": preprocessor.state(),
    }
    return preprocessor, estimator, state


def _predict_logistic(
    preprocessor: NumericPreprocessor,
    estimator: LogisticRegression,
    table: pa.Table,
) -> np.ndarray:
    probabilities = np.asarray(estimator.predict_proba(preprocessor.transform(table)), dtype=np.float64)
    if probabilities.shape != (table.num_rows, 2) or not np.array_equal(estimator.classes_, [0, 1]):
        raise ParticipationTrainingError("binary logistic probability columns differ")
    return probabilities[:, 1]


def _tune_logistic(
    table: pa.Table,
    features: Sequence[str],
    target: str,
) -> tuple[float, dict[str, Any]]:
    train, validation, split = _date_atomic_inner_2023(table)
    labels = _values(validation, target, dtype=np.int64)
    candidates: list[dict[str, Any]] = []
    for ordinal, c_value in enumerate(LOGISTIC_C_GRID):
        preprocessor, estimator, state = _fit_logistic(
            train, features, target, c_value=c_value
        )
        probabilities = _predict_logistic(preprocessor, estimator, validation)
        log_loss = float(np.mean(per_row_binary_log_loss(labels, probabilities)))
        brier = float(np.mean(np.square(probabilities - labels)))
        candidates.append(
            {
                "C": c_value,
                "ordinal": ordinal,
                "logLoss": log_loss,
                "brierScore": brier,
                "convergence": {"converged": True, "nIter": state["nIter"]},
            }
        )
    selected = min(candidates, key=lambda item: (item["logLoss"], item["brierScore"], item["ordinal"]))
    return float(selected["C"]), {
        "schemaVersion": "MLB_PARTICIPATION_LOGISTIC_TUNING_V1",
        "split": split,
        "grid": list(LOGISTIC_C_GRID),
        "candidates": candidates,
        "selectedC": selected["C"],
        "selectionMetric": "LOG_LOSS_THEN_BRIER_THEN_GRID_ORDINAL",
        "selectionUses2024Or2025": False,
    }


def _coverage_for(
    views: BuiltParticipationFeatureViews,
    component: str,
    season: int,
) -> dict[str, Any]:
    return next(dict(item) for item in views.coverage[component] if item["season"] == season)


def _folds(table: pa.Table) -> tuple[dict[str, Any], ...]:
    return (
        {
            "foldId": "train-2023-validate-2024",
            "trainingSeasons": [2023],
            "validationSeason": 2024,
            "trainingRows": _season(table, 2023).num_rows,
            "validationRows": _season(table, 2024).num_rows,
            "status": "COMPLETE",
        },
        {
            "foldId": "train-through-2024-validate-2025",
            "trainingSeasons": [2023, 2024],
            "validationSeason": 2025,
            "trainingRows": _train_through(table, 2024).num_rows,
            "validationRows": _season(table, 2025).num_rows,
            "status": "COMPLETE",
        },
    )


def _candidate_fold_record(
    table: pa.Table,
    *,
    season: int,
    metrics: Mapping[str, Any] | None,
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    training_seasons = [2023] if season == 2024 else [2023, 2024]
    training = _train_through(table, season - 1)
    validation = _season(table, season)
    status = "COMPLETE" if metrics is not None else "NOT_RUN_BY_POLICY"
    runtime = float(state.get("runtimeSeconds", 0.0)) if state is not None else 0.0
    converged = bool(state.get("converged", True)) if state is not None else status == "COMPLETE"
    return {
        "foldId": (
            "train-2023-validate-2024"
            if season == 2024
            else "train-through-2024-validate-2025"
        ),
        "trainingSeasons": training_seasons,
        "validationSeason": season,
        "trainingRows": training.num_rows,
        "validationRows": validation.num_rows,
        "status": status,
        "runtimeSeconds": runtime,
        "convergence": {
            "converged": converged if status == "COMPLETE" else None,
            "nIter": state.get("nIter") if state is not None else None,
            "maxIter": state.get("maxIter") if state is not None else None,
        },
        "metrics": dict(metrics) if metrics is not None else None,
    }


def _lineup_baseline(table: pa.Table) -> np.ndarray:
    starts = _values(table, "prior_starts_30d", dtype=np.float64)
    appearances = _values(table, "prior_appearances_30d", dtype=np.float64)
    probabilities = (np.nan_to_num(starts, nan=0.0) + 1.0) / (
        np.nan_to_num(appearances, nan=0.0) + 2.0
    )
    return np.clip(probabilities, 1e-6, 1.0 - 1e-6)


def _bullpen_baseline(table: pa.Table) -> np.ndarray:
    appearances = np.nan_to_num(_values(table, "appearances_7d", dtype=np.float64), nan=0.0)
    bfp3 = np.nan_to_num(_values(table, "prior_bfp_3d", dtype=np.float64), nan=0.0)
    yesterday = np.nan_to_num(_values(table, "appeared_yesterday", dtype=np.float64), nan=0.0)
    consecutive = np.nan_to_num(
        _values(table, "appeared_on_two_consecutive_prior_days", dtype=np.float64), nan=0.0
    )
    prior_share = np.nan_to_num(_values(table, "prior_team_usage_rate", dtype=np.float64), nan=0.0)
    logits = -1.25 + 0.32 * appearances + 1.2 * prior_share - 0.04 * bfp3 - 0.55 * yesterday - 0.65 * consecutive
    return np.clip(1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0))), 1e-6, 1.0 - 1e-6)


def _duration_heuristic(
    table: pa.Table,
    *,
    training_positive_bfp_mean: float,
    training_positive_outs_mean: float,
) -> tuple[np.ndarray, np.ndarray]:
    appearances = _values(table, "appearances_14d", dtype=np.float64)
    bfp = _values(table, "prior_bfp_14d", dtype=np.float64)
    outs = _values(table, "prior_outs_14d", dtype=np.float64)
    usable = np.isfinite(appearances) & (appearances > 0)
    per_appearance_bfp = np.full(table.num_rows, training_positive_bfp_mean, dtype=np.float64)
    per_appearance_outs = np.full(table.num_rows, training_positive_outs_mean, dtype=np.float64)
    np.divide(bfp, appearances, out=per_appearance_bfp, where=usable)
    np.divide(outs, appearances, out=per_appearance_outs, where=usable)
    predicted_bfp = per_appearance_bfp
    predicted_outs = per_appearance_outs
    return np.maximum(predicted_bfp, 0.0), np.maximum(predicted_outs, 0.0)


def _optional_hgb_classifier(
    train: pa.Table,
    validation: pa.Table,
    features: Sequence[str],
    target: str,
    *,
    runtime_limit_seconds: float = 5_400,
) -> tuple[np.ndarray, dict[str, Any]]:
    started = time.monotonic()
    preprocessor = NumericPreprocessor.fit(train, features)
    labels = _values(train, target, dtype=np.int64)
    estimator = HistGradientBoostingClassifier(
        max_iter=HGB_MAX_ITER,
        max_depth=HGB_MAX_DEPTH,
        learning_rate=HGB_LEARNING_RATE,
        random_state=RANDOM_SEED,
        l2_regularization=1.0,
    )
    estimator.fit(preprocessor.transform(train), labels)
    elapsed = time.monotonic() - started
    if elapsed > runtime_limit_seconds:
        raise ParticipationTrainingError("bounded HGB classifier exceeded its fit gate")
    probabilities = estimator.predict_proba(preprocessor.transform(validation))[:, 1]
    return probabilities, {
        "schemaVersion": "MLB_PARTICIPATION_BOUNDED_HGB_CLASSIFIER_V1",
        "maxIter": HGB_MAX_ITER,
        "maxDepth": HGB_MAX_DEPTH,
        "learningRate": HGB_LEARNING_RATE,
        "randomSeed": RANDOM_SEED,
        "runtimeLimitSeconds": runtime_limit_seconds,
        "runtimeSeconds": elapsed,
        "nIter": int(estimator.n_iter_),
        "converged": True,
        "stoppedByIterationBound": int(estimator.n_iter_) >= HGB_MAX_ITER,
        "preprocessor": preprocessor.state(),
    }


def _run_lineup(
    views: BuiltParticipationFeatureViews,
    *,
    enable_optional_hgb: bool,
    bootstrap_resamples: int,
) -> ComponentExperimentResult:
    table = views.lineup
    selected_c, tuning = _tune_logistic(table, LINEUP_FEATURES, "target_start")
    candidates = {candidate_id: {**dict(config), "foldMetrics": []} for candidate_id, config in LINEUP_CANDIDATES.items()}
    predictions: dict[tuple[int, str], dict[str, np.ndarray]] = {}
    states: dict[tuple[int, str], dict[str, Any]] = {}
    metrics_by_season: dict[int, dict[str, dict[str, Any]]] = {}
    for season in (2024,):
        train = _train_through(table, season - 1)
        validation = _season(table, season)
        coverage = _coverage_for(views, "lineup", season)
        total = int(coverage["actualPositiveRows"])
        uncovered = int(coverage["uncoveredPositiveRows"])
        fold_metrics: dict[str, dict[str, Any]] = {}
        baseline = _lineup_baseline(validation)
        fold_metrics["L0"] = lineup_metrics(validation, baseline, uncovered_positive_count=uncovered, total_actual_positive_count=total)
        predictions[(season, "L0")] = {"probability": baseline}
        states[(season, "L0")] = {"schemaVersion": "MLB_LINEUP_TRAILING_FREQUENCY_V1", "smoothing": [1.0, 2.0]}
        preprocessor, estimator, state = _fit_logistic(train, LINEUP_FEATURES, "target_start", c_value=selected_c)
        l1 = _predict_logistic(preprocessor, estimator, validation)
        fold_metrics["L1"] = lineup_metrics(validation, l1, uncovered_positive_count=uncovered, total_actual_positive_count=total)
        predictions[(season, "L1")] = {"probability": l1}
        states[(season, "L1")] = state
        if enable_optional_hgb:
            l2, state = _optional_hgb_classifier(train, validation, LINEUP_FEATURES, "target_start")
            fold_metrics["L2"] = lineup_metrics(validation, l2, uncovered_positive_count=uncovered, total_actual_positive_count=total)
            predictions[(season, "L2")] = {"probability": l2}
            states[(season, "L2")] = state
        metrics_by_season[season] = fold_metrics
    eligible_2024 = ["L0", "L1", *( ["L2"] if enable_optional_hgb else [])]
    selected_id = min(
        eligible_2024,
        key=lambda candidate_id: (
            metrics_by_season[2024][candidate_id]["binaryLogLoss"],
            metrics_by_season[2024][candidate_id]["brierScore"],
            int(candidate_id[1:]),
        ),
    )
    train_2025 = _train_through(table, 2024)
    validation_2025 = _season(table, 2025)
    coverage_2025 = _coverage_for(views, "lineup", 2025)
    total_2025 = int(coverage_2025["actualPositiveRows"])
    uncovered_2025 = int(coverage_2025["uncoveredPositiveRows"])
    metrics_by_season[2025] = {}
    baseline_2025 = _lineup_baseline(validation_2025)
    metrics_by_season[2025]["L0"] = lineup_metrics(validation_2025, baseline_2025, uncovered_positive_count=uncovered_2025, total_actual_positive_count=total_2025)
    predictions[(2025, "L0")] = {"probability": baseline_2025}
    states[(2025, "L0")] = {"schemaVersion": "MLB_LINEUP_TRAILING_FREQUENCY_V1", "smoothing": [1.0, 2.0]}
    if selected_id == "L1":
        preprocessor, estimator, state = _fit_logistic(train_2025, LINEUP_FEATURES, "target_start", c_value=selected_c)
        selected_2025 = _predict_logistic(preprocessor, estimator, validation_2025)
        states[(2025, "L1")] = state
    elif selected_id == "L2":
        selected_2025, state = _optional_hgb_classifier(train_2025, validation_2025, LINEUP_FEATURES, "target_start")
        states[(2025, "L2")] = state
    else:
        selected_2025 = baseline_2025
    predictions[(2025, selected_id)] = {"probability": selected_2025}
    metrics_by_season[2025][selected_id] = lineup_metrics(validation_2025, selected_2025, uncovered_positive_count=uncovered_2025, total_actual_positive_count=total_2025)
    for candidate_id, record in candidates.items():
        record["candidateId"] = candidate_id
        record["displayName"] = record.pop("displayName")
        record["featureNames"] = list(record.pop("features"))
        record["eligible"] = candidate_id != "L2" or enable_optional_hgb
        record["rejectionReasons"] = [] if record["eligible"] else ["OPTIONAL_HGB_DISABLED_BY_POLICY"]
        for season in (2024, 2025):
            metrics = metrics_by_season[season].get(candidate_id)
            record["foldMetrics"].append(
                _candidate_fold_record(
                    table,
                    season=season,
                    metrics=metrics,
                    state=states.get((season, candidate_id)),
                )
            )
        record["runtimeSeconds"] = float(
            sum(item["runtimeSeconds"] for item in record["foldMetrics"])
        )
        record["convergence"] = {
            "allCompleteFoldsConverged": all(
                item["convergence"]["converged"] is True
                for item in record["foldMetrics"]
                if item["status"] == "COMPLETE"
            )
            if record["eligible"]
            else None
        }
    selected_2024_metrics = metrics_by_season[2024][selected_id]
    selected_2025_metrics = metrics_by_season[2025][selected_id]
    baseline_2024_metrics = metrics_by_season[2024]["L0"]
    baseline_2025_metrics = metrics_by_season[2025]["L0"]
    decision = lineup_decision(
        LineupDecisionEvidence(
            improvement_2024=baseline_2024_metrics["binaryLogLoss"] - selected_2024_metrics["binaryLogLoss"],
            improvement_2025=baseline_2025_metrics["binaryLogLoss"] - selected_2025_metrics["binaryLogLoss"],
            coverage_2024=selected_2024_metrics["poolCoverage"],
            coverage_2025=selected_2025_metrics["poolCoverage"],
        )
    )
    bootstraps: list[dict[str, Any]] = []
    for season, validation in ((2024, _season(table, 2024)), (2025, validation_2025)):
        labels = _values(validation, "target_start", dtype=np.int64)
        selected_p = predictions[(season, selected_id)]["probability"]
        baseline_p = predictions[(season, "L0")]["probability"]
        bootstraps.append(
            {
                "validationSeason": season,
                **game_cluster_bootstrap_difference(
                    _values(validation, "game_id", dtype=object),
                    per_row_binary_log_loss(labels, selected_p),
                    per_row_binary_log_loss(labels, baseline_p),
                    resamples=bootstrap_resamples,
                    seed=BOOTSTRAP_SEED + season,
                ),
            }
        )
    return ComponentExperimentResult(
        component_type="LINEUP_PROJECTION",
        contract_name=LINEUP_CONTRACT_NAME,
        contract_sha=canonical_sha(lineup_contract_payload()),
        descriptor={
            "schemaVersion": "MLB_LINEUP_EXPERIMENT_DESCRIPTOR_V1",
            "featureViewContentSha": views.content_shas["lineup"],
            "inner2023Tuning": tuning,
            "selectionPolicy": "2024_BINARY_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
            "orderEstimator": "DETERMINISTIC_PROBABILITY_WEIGHTED_HISTORICAL_ORDER",
        },
        candidates=tuple(candidates[key] for key in LINEUP_CANDIDATES),
        selected={"candidateId": selected_id, "selectionSeason": 2024, "selectionMetric": "BINARY_LOG_LOSS_THEN_BRIER"},
        folds=_folds(table),
        metrics={"selection2024": selected_2024_metrics, "final2025": selected_2025_metrics},
        calibration={"selection2024": selected_2024_metrics["calibration"], "final2025": selected_2025_metrics["calibration"]},
        bootstrap={"comparisonsToL0": bootstraps},
        coverage={"bySeason": list(views.coverage["lineup"]), "acceptableThreshold": 0.95},
        decision=decision,
        predictions=predictions,
        model_states=states,
    )


def _starter_s0(train: pa.Table, validation: pa.Table) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    bfp = _values(train, "target_bfp", dtype=np.float64)
    outs = _values(train, "target_outs", dtype=np.float64)
    bfp_mean, outs_mean = float(np.mean(bfp)), float(np.mean(outs))
    return (
        np.full(validation.num_rows, bfp_mean),
        np.full(validation.num_rows, outs_mean),
        {
            "schemaVersion": "MLB_STARTER_GLOBAL_LOCATION_V1",
            "bfpMean": bfp_mean,
            "bfpMedian": float(np.median(bfp)),
            "outsMean": outs_mean,
            "outsMedian": float(np.median(outs)),
            "trainingRows": train.num_rows,
        },
    )


def _starter_s1(train: pa.Table, validation: pa.Table) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    fallback_bfp = float(np.mean(_values(train, "target_bfp", dtype=np.float64)))
    fallback_outs = float(np.mean(_values(train, "target_outs", dtype=np.float64)))
    def choose(prefix: str, fallback: float) -> np.ndarray:
        trailing3 = _values(validation, f"trailing_3_start_mean_{prefix}", dtype=np.float64)
        trailing5 = _values(validation, f"trailing_5_start_mean_{prefix}", dtype=np.float64)
        season = _values(validation, f"season_to_date_mean_{prefix}", dtype=np.float64)
        team = _values(validation, f"team_prior_date_mean_{prefix}", dtype=np.float64)
        return np.maximum(
            np.where(
                np.isfinite(trailing3),
                trailing3,
                np.where(np.isfinite(trailing5), trailing5, np.where(np.isfinite(season), season, np.where(np.isfinite(team), team, fallback))),
            ),
            0.0,
        )
    return choose("bfp", fallback_bfp), choose("outs", fallback_outs), {
        "schemaVersion": "MLB_STARTER_PITCHER_ROLLING_V1",
        "fallbackBfp": fallback_bfp,
        "fallbackOuts": fallback_outs,
        "priority": ["trailing3", "trailing5", "seasonToDate", "teamPriorDate", "globalTraining"],
    }


def _fit_ridge_duration(train: pa.Table, validation: pa.Table, alpha: float) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    started = time.monotonic()
    preprocessor = NumericPreprocessor.fit(train, STARTER_FEATURES)
    train_matrix = preprocessor.transform(train)
    validation_matrix = preprocessor.transform(validation)
    bfp_estimator = Ridge(alpha=alpha, random_state=RANDOM_SEED)
    outs_estimator = Ridge(alpha=alpha, random_state=RANDOM_SEED)
    bfp_estimator.fit(train_matrix, _values(train, "target_bfp", dtype=np.float64))
    outs_estimator.fit(train_matrix, _values(train, "target_outs", dtype=np.float64))
    elapsed = time.monotonic() - started
    if elapsed > 5_400:
        raise ParticipationTrainingError("regularized duration fit exceeded the 90-minute gate")
    return (
        np.maximum(bfp_estimator.predict(validation_matrix), 0.0),
        np.maximum(outs_estimator.predict(validation_matrix), 0.0),
        {
            "schemaVersion": "MLB_STARTER_REGULARIZED_LINEAR_V1",
            "alpha": alpha,
            "bfpCoefficients": bfp_estimator.coef_.tolist(),
            "bfpIntercept": float(bfp_estimator.intercept_),
            "outsCoefficients": outs_estimator.coef_.tolist(),
            "outsIntercept": float(outs_estimator.intercept_),
            "runtimeSeconds": elapsed,
            "converged": True,
            "preprocessor": preprocessor.state(),
        },
    )


def _fit_hgb_duration(train: pa.Table, validation: pa.Table) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    started = time.monotonic()
    preprocessor = NumericPreprocessor.fit(train, STARTER_FEATURES)
    matrix = preprocessor.transform(train)
    validation_matrix = preprocessor.transform(validation)
    estimators: list[HistGradientBoostingRegressor] = []
    predictions: list[np.ndarray] = []
    for target in ("target_bfp", "target_outs"):
        estimator = HistGradientBoostingRegressor(
            max_iter=HGB_MAX_ITER,
            max_depth=HGB_MAX_DEPTH,
            learning_rate=HGB_LEARNING_RATE,
            l2_regularization=1.0,
            random_state=RANDOM_SEED,
        )
        estimator.fit(matrix, _values(train, target, dtype=np.float64))
        estimators.append(estimator)
        predictions.append(np.maximum(estimator.predict(validation_matrix), 0.0))
    elapsed = time.monotonic() - started
    if elapsed > 5_400:
        raise ParticipationTrainingError("bounded HGB duration fit exceeded the 90-minute gate")
    return predictions[0], predictions[1], {
        "schemaVersion": "MLB_STARTER_BOUNDED_HGB_V1",
        "maxIter": HGB_MAX_ITER,
        "maxDepth": HGB_MAX_DEPTH,
        "learningRate": HGB_LEARNING_RATE,
        "randomSeed": RANDOM_SEED,
        "runtimeSeconds": elapsed,
        "nIter": [int(estimator.n_iter_) for estimator in estimators],
        "converged": True,
        "stoppedByIterationBound": [
            int(estimator.n_iter_) >= HGB_MAX_ITER for estimator in estimators
        ],
        "preprocessor": preprocessor.state(),
    }


def _tune_ridge(table: pa.Table) -> tuple[float, dict[str, Any]]:
    train, validation, split = _date_atomic_inner_2023(table)
    targets = _values(validation, "target_bfp", dtype=np.float64)
    candidates: list[dict[str, Any]] = []
    for ordinal, alpha in enumerate(RIDGE_ALPHA_GRID):
        predicted, _outs, _state = _fit_ridge_duration(train, validation, alpha)
        errors = predicted - targets
        candidates.append(
            {
                "alpha": alpha,
                "ordinal": ordinal,
                "bfpMae": float(np.mean(np.abs(errors))),
                "bfpRmse": float(np.sqrt(np.mean(np.square(errors)))),
            }
        )
    selected = min(candidates, key=lambda item: (item["bfpMae"], item["bfpRmse"], item["ordinal"]))
    return float(selected["alpha"]), {
        "schemaVersion": "MLB_STARTER_RIDGE_TUNING_V1",
        "split": split,
        "grid": list(RIDGE_ALPHA_GRID),
        "candidates": candidates,
        "selectedAlpha": selected["alpha"],
        "selectionUses2024Or2025": False,
    }


def _reach_probabilities(train: pa.Table, validation: pa.Table, c_value: float) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    preprocessor = NumericPreprocessor.fit(train, STARTER_FEATURES)
    train_matrix = preprocessor.transform(train)
    validation_matrix = preprocessor.transform(validation)
    train_outs = _values(train, "target_outs", dtype=np.float64)
    raw: dict[int, np.ndarray] = {}
    states: dict[str, Any] = {}
    for threshold in (15, 18, 21):
        labels = (train_outs >= threshold).astype(np.int64)
        if np.unique(labels).size == 1:
            probability = float((labels.sum() + 1.0) / (labels.size + 2.0))
            raw[threshold] = np.full(validation.num_rows, probability)
            states[str(threshold)] = {"estimator": "SMOOTHED_CONSTANT", "probability": probability}
            continue
        estimator = LogisticRegression(
            C=c_value,
            penalty="l2",
            solver="lbfgs",
            max_iter=DEFAULT_MAX_ITER,
            tol=DEFAULT_TOLERANCE,
            random_state=RANDOM_SEED,
        )
        estimator.fit(train_matrix, labels)
        raw[threshold] = estimator.predict_proba(validation_matrix)[:, 1]
        states[str(threshold)] = {
            "estimator": "SKLEARN_LOGISTIC_L2",
            "C": c_value,
            "classes": estimator.classes_.astype(int).tolist(),
            "coefficients": estimator.coef_.tolist(),
            "intercepts": estimator.intercept_.tolist(),
            "nIter": int(np.max(estimator.n_iter_)),
        }
    p15 = np.clip(raw[15], 1e-6, 1.0 - 1e-6)
    p18 = np.minimum(np.clip(raw[18], 1e-6, 1.0 - 1e-6), p15)
    p21 = np.minimum(np.clip(raw[21], 1e-6, 1.0 - 1e-6), p18)
    return {15: p15, 18: p18, 21: p21}, {
        "schemaVersion": "MLB_STARTER_INNING_REACH_BOUNDED_LOGISTIC_V1",
        "thresholdOuts": [15, 18, 21],
        "monotonicProjection": "P21_LE_P18_LE_P15",
        "models": states,
        "preprocessor": preprocessor.state(),
    }


def _run_starter(
    views: BuiltParticipationFeatureViews,
    *,
    enable_optional_hgb: bool,
    bootstrap_resamples: int,
) -> ComponentExperimentResult:
    table = views.starter
    selected_alpha, tuning = _tune_ridge(table)
    reach_c = LOGISTIC_C_GRID[1]
    candidates = {candidate_id: {**dict(config), "foldMetrics": []} for candidate_id, config in STARTER_CANDIDATES.items()}
    predictions: dict[tuple[int, str], dict[str, np.ndarray]] = {}
    states: dict[tuple[int, str], dict[str, Any]] = {}
    metrics_by_season: dict[int, dict[str, dict[str, Any]]] = {}
    for season in (2024,):
        train = _train_through(table, season - 1)
        validation = _season(table, season)
        reach, reach_state = _reach_probabilities(train, validation, reach_c)
        fold: dict[str, dict[str, Any]] = {}
        for candidate_id in ("S0", "S1", "S2", *( ["S3"] if enable_optional_hgb else [])):
            if candidate_id == "S0":
                bfp, outs, state = _starter_s0(train, validation)
            elif candidate_id == "S1":
                bfp, outs, state = _starter_s1(train, validation)
            elif candidate_id == "S2":
                bfp, outs, state = _fit_ridge_duration(train, validation, selected_alpha)
            else:
                bfp, outs, state = _fit_hgb_duration(train, validation)
            state["inningReach"] = reach_state
            fold[candidate_id] = starter_metrics(validation, bfp, outs, reach)
            predictions[(season, candidate_id)] = {"bfp": bfp, "outs": outs, **{f"reach{key}": value for key, value in reach.items()}}
            states[(season, candidate_id)] = state
        metrics_by_season[season] = fold
    eligible = ["S0", "S1", "S2", *( ["S3"] if enable_optional_hgb else [])]
    selected_id = min(
        eligible,
        key=lambda candidate_id: (
            metrics_by_season[2024][candidate_id]["bfpMae"],
            metrics_by_season[2024][candidate_id]["bfpRmse"],
            int(candidate_id[1:]),
        ),
    )
    train_2025 = _train_through(table, 2024)
    validation_2025 = _season(table, 2025)
    reach_2025, reach_state_2025 = _reach_probabilities(train_2025, validation_2025, reach_c)
    metrics_by_season[2025] = {}
    for candidate_id in sorted({"S0", "S1", selected_id}):
        if candidate_id == "S0":
            bfp, outs, state = _starter_s0(train_2025, validation_2025)
        elif candidate_id == "S1":
            bfp, outs, state = _starter_s1(train_2025, validation_2025)
        elif candidate_id == "S2":
            bfp, outs, state = _fit_ridge_duration(train_2025, validation_2025, selected_alpha)
        else:
            bfp, outs, state = _fit_hgb_duration(train_2025, validation_2025)
        state["inningReach"] = reach_state_2025
        metrics_by_season[2025][candidate_id] = starter_metrics(validation_2025, bfp, outs, reach_2025)
        predictions[(2025, candidate_id)] = {"bfp": bfp, "outs": outs, **{f"reach{key}": value for key, value in reach_2025.items()}}
        states[(2025, candidate_id)] = state
    for candidate_id, record in candidates.items():
        record["candidateId"] = candidate_id
        record["featureNames"] = list(record.pop("features"))
        record["eligible"] = candidate_id != "S3" or enable_optional_hgb
        record["rejectionReasons"] = [] if record["eligible"] else ["OPTIONAL_HGB_DISABLED_BY_POLICY"]
        for season in (2024, 2025):
            metrics = metrics_by_season[season].get(candidate_id)
            record["foldMetrics"].append(
                _candidate_fold_record(
                    table,
                    season=season,
                    metrics=metrics,
                    state=states.get((season, candidate_id)),
                )
            )
        record["runtimeSeconds"] = float(sum(item["runtimeSeconds"] for item in record["foldMetrics"]))
        record["convergence"] = {
            "allCompleteFoldsConverged": all(
                item["convergence"]["converged"] is True
                for item in record["foldMetrics"]
                if item["status"] == "COMPLETE"
            )
            if record["eligible"]
            else None
        }
    selected_2024 = metrics_by_season[2024][selected_id]
    selected_2025 = metrics_by_season[2025][selected_id]
    evidence_values: dict[str, float] = {}
    for season, selected_metrics in ((2024, selected_2024), (2025, selected_2025)):
        for baseline in ("S0", "S1"):
            baseline_metrics = metrics_by_season[season][baseline]
            evidence_values[f"bfp_{'mae'}_vs_{baseline.casefold()}_{season}"] = baseline_metrics["bfpMae"] - selected_metrics["bfpMae"]
            evidence_values[f"bfp_{'rmse'}_vs_{baseline.casefold()}_{season}"] = baseline_metrics["bfpRmse"] - selected_metrics["bfpRmse"]
    decision = starter_decision(
        StarterDecisionEvidence(
            bfp_mae_vs_s0_2024=evidence_values["bfp_mae_vs_s0_2024"],
            bfp_rmse_vs_s0_2024=evidence_values["bfp_rmse_vs_s0_2024"],
            bfp_mae_vs_s1_2024=evidence_values["bfp_mae_vs_s1_2024"],
            bfp_rmse_vs_s1_2024=evidence_values["bfp_rmse_vs_s1_2024"],
            bfp_mae_vs_s0_2025=evidence_values["bfp_mae_vs_s0_2025"],
            bfp_rmse_vs_s0_2025=evidence_values["bfp_rmse_vs_s0_2025"],
            bfp_mae_vs_s1_2025=evidence_values["bfp_mae_vs_s1_2025"],
            bfp_rmse_vs_s1_2025=evidence_values["bfp_rmse_vs_s1_2025"],
        )
    )
    bootstraps: list[dict[str, Any]] = []
    for season, validation in ((2024, _season(table, 2024)), (2025, validation_2025)):
        target = _values(validation, "target_bfp", dtype=np.float64)
        selected_loss = np.abs(predictions[(season, selected_id)]["bfp"] - target)
        for baseline in ("S0", "S1"):
            baseline_loss = np.abs(predictions[(season, baseline)]["bfp"] - target)
            bootstraps.append(
                {
                    "validationSeason": season,
                    "baselineCandidateId": baseline,
                    **game_cluster_bootstrap_difference(
                        _values(validation, "game_id", dtype=object),
                        selected_loss,
                        baseline_loss,
                        resamples=bootstrap_resamples,
                        seed=BOOTSTRAP_SEED + season + int(baseline[1:]),
                    ),
                }
            )
    return ComponentExperimentResult(
        component_type="STARTER_DURATION",
        contract_name=STARTER_CONTRACT_NAME,
        contract_sha=canonical_sha(starter_contract_payload()),
        descriptor={
            "schemaVersion": "MLB_STARTER_DURATION_EXPERIMENT_DESCRIPTOR_V1",
            "conditioning": "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY",
            "primaryTarget": "stat_p_bfp",
            "secondaryTarget": "stat_p_ipouts",
            "featureViewContentSha": views.content_shas["starter"],
            "inner2023Tuning": tuning,
            "inningReach": {"thresholdOuts": [15, 18, 21], "estimator": "BOUNDED_LOGISTIC_L2", "C": reach_c},
            "selectionPolicy": "2024_BFP_MAE_THEN_RMSE_THEN_ORDINAL",
        },
        candidates=tuple(candidates[key] for key in STARTER_CANDIDATES),
        selected={"candidateId": selected_id, "selectionSeason": 2024, "selectionMetric": "BFP_MAE_THEN_RMSE"},
        folds=_folds(table),
        metrics={"selection2024": selected_2024, "final2025": selected_2025},
        calibration={
            "selection2024": {key: selected_2024[key] for key in ("reach15Calibration", "reach18Calibration", "reach21Calibration")},
            "final2025": {key: selected_2025[key] for key in ("reach15Calibration", "reach18Calibration", "reach21Calibration")},
        },
        bootstrap={"comparisonsToS0AndS1": bootstraps},
        coverage={"bySeason": list(views.coverage["starter"])},
        decision=decision,
        predictions=predictions,
        model_states=states,
    )


def _run_bullpen(
    views: BuiltParticipationFeatureViews,
    *,
    enable_optional_hgb: bool,
    bootstrap_resamples: int,
) -> ComponentExperimentResult:
    table = views.bullpen
    selected_c, tuning = _tune_logistic(table, BULLPEN_FEATURES, "target_appearance")
    candidates = {candidate_id: {**dict(config), "foldMetrics": []} for candidate_id, config in BULLPEN_CANDIDATES.items()}
    predictions: dict[tuple[int, str], dict[str, np.ndarray]] = {}
    states: dict[tuple[int, str], dict[str, Any]] = {}
    metrics_by_season: dict[int, dict[str, dict[str, Any]]] = {}
    for season in (2024,):
        train = _train_through(table, season - 1)
        validation = _season(table, season)
        train_positive = _values(train, "target_appearance", dtype=np.int64) == 1
        train_bfp = _values(train, "target_bfp", dtype=np.float64)
        train_outs = _values(train, "target_outs", dtype=np.float64)
        mean_bfp = float(np.mean(train_bfp[train_positive & np.isfinite(train_bfp)]))
        mean_outs = float(np.mean(train_outs[train_positive & np.isfinite(train_outs)]))
        duration_bfp, duration_outs = _duration_heuristic(validation, training_positive_bfp_mean=mean_bfp, training_positive_outs_mean=mean_outs)
        coverage = _coverage_for(views, "bullpen", season)
        fold: dict[str, dict[str, Any]] = {}
        b0 = _bullpen_baseline(validation)
        fold["B0"] = bullpen_metrics(validation, b0, duration_bfp, duration_outs, coverage_evidence=coverage)
        predictions[(season, "B0")] = {"probability": b0, "bfp": duration_bfp, "outs": duration_outs}
        states[(season, "B0")] = {"schemaVersion": "MLB_BULLPEN_RECENCY_WORKLOAD_HEURISTIC_V1", "coefficients": [-1.25, 0.32, 1.2, -0.04, -0.55, -0.65]}
        preprocessor, estimator, state = _fit_logistic(train, BULLPEN_FEATURES, "target_appearance", c_value=selected_c)
        b1 = _predict_logistic(preprocessor, estimator, validation)
        fold["B1"] = bullpen_metrics(validation, b1, duration_bfp, duration_outs, coverage_evidence=coverage)
        predictions[(season, "B1")] = {"probability": b1, "bfp": duration_bfp, "outs": duration_outs}
        states[(season, "B1")] = state
        if enable_optional_hgb:
            b2, state = _optional_hgb_classifier(
                train,
                validation,
                BULLPEN_FEATURES,
                "target_appearance",
                runtime_limit_seconds=7_200,
            )
            fold["B2"] = bullpen_metrics(validation, b2, duration_bfp, duration_outs, coverage_evidence=coverage)
            predictions[(season, "B2")] = {"probability": b2, "bfp": duration_bfp, "outs": duration_outs}
            states[(season, "B2")] = state
        metrics_by_season[season] = fold
    eligible = ["B0", "B1", *( ["B2"] if enable_optional_hgb else [])]
    selected_id = min(
        eligible,
        key=lambda candidate_id: (
            metrics_by_season[2024][candidate_id]["binaryLogLoss"],
            metrics_by_season[2024][candidate_id]["brierScore"],
            int(candidate_id[1:]),
        ),
    )
    train_2025 = _train_through(table, 2024)
    validation_2025 = _season(table, 2025)
    positive = _values(train_2025, "target_appearance", dtype=np.int64) == 1
    train_bfp = _values(train_2025, "target_bfp", dtype=np.float64)
    train_outs = _values(train_2025, "target_outs", dtype=np.float64)
    duration_bfp_2025, duration_outs_2025 = _duration_heuristic(
        validation_2025,
        training_positive_bfp_mean=float(np.mean(train_bfp[positive & np.isfinite(train_bfp)])),
        training_positive_outs_mean=float(np.mean(train_outs[positive & np.isfinite(train_outs)])),
    )
    coverage_2025 = _coverage_for(views, "bullpen", 2025)
    metrics_by_season[2025] = {}
    b0_2025 = _bullpen_baseline(validation_2025)
    metrics_by_season[2025]["B0"] = bullpen_metrics(validation_2025, b0_2025, duration_bfp_2025, duration_outs_2025, coverage_evidence=coverage_2025)
    predictions[(2025, "B0")] = {"probability": b0_2025, "bfp": duration_bfp_2025, "outs": duration_outs_2025}
    states[(2025, "B0")] = {"schemaVersion": "MLB_BULLPEN_RECENCY_WORKLOAD_HEURISTIC_V1", "coefficients": [-1.25, 0.32, 1.2, -0.04, -0.55, -0.65]}
    if selected_id == "B1":
        preprocessor, estimator, state = _fit_logistic(train_2025, BULLPEN_FEATURES, "target_appearance", c_value=selected_c)
        selected_p = _predict_logistic(preprocessor, estimator, validation_2025)
        states[(2025, "B1")] = state
    elif selected_id == "B2":
        selected_p, state = _optional_hgb_classifier(
            train_2025,
            validation_2025,
            BULLPEN_FEATURES,
            "target_appearance",
            runtime_limit_seconds=7_200,
        )
        states[(2025, "B2")] = state
    else:
        selected_p = b0_2025
    predictions[(2025, selected_id)] = {"probability": selected_p, "bfp": duration_bfp_2025, "outs": duration_outs_2025}
    metrics_by_season[2025][selected_id] = bullpen_metrics(validation_2025, selected_p, duration_bfp_2025, duration_outs_2025, coverage_evidence=coverage_2025)
    for candidate_id, record in candidates.items():
        record["candidateId"] = candidate_id
        record["featureNames"] = list(record.pop("features"))
        record["eligible"] = candidate_id != "B2" or enable_optional_hgb
        record["rejectionReasons"] = [] if record["eligible"] else ["OPTIONAL_HGB_DISABLED_BY_POLICY"]
        for season in (2024, 2025):
            metrics = metrics_by_season[season].get(candidate_id)
            record["foldMetrics"].append(
                _candidate_fold_record(
                    table,
                    season=season,
                    metrics=metrics,
                    state=states.get((season, candidate_id)),
                )
            )
        record["runtimeSeconds"] = float(sum(item["runtimeSeconds"] for item in record["foldMetrics"]))
        record["convergence"] = {
            "allCompleteFoldsConverged": all(
                item["convergence"]["converged"] is True
                for item in record["foldMetrics"]
                if item["status"] == "COMPLETE"
            )
            if record["eligible"]
            else None
        }
    selected_2024 = metrics_by_season[2024][selected_id]
    selected_2025 = metrics_by_season[2025][selected_id]
    b0_2024 = metrics_by_season[2024]["B0"]
    b0_2025_metrics = metrics_by_season[2025]["B0"]
    decision = bullpen_decision(
        BullpenDecisionEvidence(
            logloss_improvement_2024=b0_2024["binaryLogLoss"] - selected_2024["binaryLogLoss"],
            logloss_improvement_2025=b0_2025_metrics["binaryLogLoss"] - selected_2025["binaryLogLoss"],
            brier_improvement_2024=b0_2024["brierScore"] - selected_2024["brierScore"],
            brier_improvement_2025=b0_2025_metrics["brierScore"] - selected_2025["brierScore"],
            coverage_2024=selected_2024["poolCoverage"],
            coverage_2025=selected_2025["poolCoverage"],
            calibration_acceptable_2024=bool(selected_2024["topLabelCalibration"]["acceptable"]),
            calibration_acceptable_2025=bool(selected_2025["topLabelCalibration"]["acceptable"]),
        )
    )
    bootstraps: list[dict[str, Any]] = []
    for season, validation in ((2024, _season(table, 2024)), (2025, validation_2025)):
        labels = _values(validation, "target_appearance", dtype=np.int64)
        bootstraps.append(
            {
                "validationSeason": season,
                **game_cluster_bootstrap_difference(
                    _values(validation, "game_id", dtype=object),
                    per_row_binary_log_loss(labels, predictions[(season, selected_id)]["probability"]),
                    per_row_binary_log_loss(labels, predictions[(season, "B0")]["probability"]),
                    resamples=bootstrap_resamples,
                    seed=BOOTSTRAP_SEED + season,
                ),
            }
        )
    return ComponentExperimentResult(
        component_type="BULLPEN_USAGE",
        contract_name=BULLPEN_CONTRACT_NAME,
        contract_sha=canonical_sha(bullpen_contract_payload()),
        descriptor={
            "schemaVersion": "MLB_BULLPEN_EXPERIMENT_DESCRIPTOR_V1",
            "featureViewContentSha": views.content_shas["bullpen"],
            "inner2023Tuning": tuning,
            "selectionPolicy": "2024_RAW_BINARY_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
            "componentGate": {
                "rawTopLabelEceMaximum": 0.05,
                "allTenReliabilityBinsFiniteAndNonempty": True,
                "rawLogLossStrictlyBetterThanB0BothFolds": True,
                "rawBrierNonWorseThanB0BothFoldsTolerance": 1e-10,
                "coverageMinimum": 0.95,
                "scaledEvidenceCannotSatisfyGate": True,
            },
        },
        candidates=tuple(candidates[key] for key in BULLPEN_CANDIDATES),
        selected={"candidateId": selected_id, "selectionSeason": 2024, "selectionMetric": "RAW_BINARY_LOG_LOSS_THEN_BRIER"},
        folds=_folds(table),
        metrics={"selection2024": selected_2024, "final2025": selected_2025},
        calibration={"selection2024": selected_2024["topLabelCalibration"], "final2025": selected_2025["topLabelCalibration"]},
        bootstrap={"comparisonsToB0": bootstraps},
        coverage={"bySeason": list(views.coverage["bullpen"]), "acceptableThreshold": 0.95},
        decision=decision,
        predictions=predictions,
        model_states=states,
    )


def run_participation_experiments(
    views: BuiltParticipationFeatureViews,
    *,
    enable_optional_hgb: bool = False,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    fixture_mode: bool = False,
    progress: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> ParticipationExperimentResult:
    if not isinstance(views, BuiltParticipationFeatureViews):
        raise TypeError("views must be BuiltParticipationFeatureViews")
    if not fixture_mode and bootstrap_resamples != BOOTSTRAP_RESAMPLES:
        raise ParticipationTrainingError("live research requires exactly 500 bootstrap resamples")
    if type(bootstrap_resamples) is not int or bootstrap_resamples < 2:
        raise ParticipationTrainingError("bootstrap resamples must be at least two")
    started = time.monotonic()
    def emit(stage: str, **values: Any) -> None:
        if progress is not None:
            progress(stage, {"stage": stage, "elapsedSeconds": time.monotonic() - started, **values})

    def fit_with_heartbeat(
        stage: str,
        callback: Callable[[], ComponentExperimentResult],
    ) -> ComponentExperimentResult:
        fit_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="participation-fit") as executor:
            future = executor.submit(callback)
            while True:
                try:
                    result = future.result(timeout=30.0)
                    break
                except FutureTimeoutError:
                    emit(
                        "MODEL_FIT_HEARTBEAT",
                        modelStage=stage,
                        fitElapsedSeconds=time.monotonic() - fit_started,
                    )
        fit_elapsed = time.monotonic() - fit_started
        stage_limit_seconds = (
            7_200 if stage == "TRAINING_BULLPEN_USAGE_COMPONENT" else 5_400
        )
        if fit_elapsed > stage_limit_seconds:
            raise ParticipationTrainingError(
                f"{stage} exceeded its post-fit runtime gate"
            )
        result.descriptor["componentRuntimeSeconds"] = fit_elapsed
        result.descriptor["componentRuntimeLimitSeconds"] = stage_limit_seconds
        result.descriptor["heartbeatMaximumIntervalSeconds"] = 30
        emit(
            "PARTICIPATION_COMPONENT_FIT_FINISHED",
            modelStage=stage,
            fitElapsedSeconds=fit_elapsed,
        )
        return result

    emit("TRAINING_LINEUP_COMPONENT")
    lineup = fit_with_heartbeat(
        "TRAINING_LINEUP_COMPONENT",
        lambda: _run_lineup(
            views,
            enable_optional_hgb=enable_optional_hgb,
            bootstrap_resamples=bootstrap_resamples,
        ),
    )
    emit("TRAINING_STARTER_DURATION_COMPONENT")
    starter = fit_with_heartbeat(
        "TRAINING_STARTER_DURATION_COMPONENT",
        lambda: _run_starter(
            views,
            enable_optional_hgb=enable_optional_hgb,
            bootstrap_resamples=bootstrap_resamples,
        ),
    )
    emit("TRAINING_BULLPEN_USAGE_COMPONENT")
    bullpen = fit_with_heartbeat(
        "TRAINING_BULLPEN_USAGE_COMPONENT",
        lambda: _run_bullpen(
            views,
            enable_optional_hgb=enable_optional_hgb,
            bootstrap_resamples=bootstrap_resamples,
        ),
    )
    emit("PARTICIPATION_EXPERIMENTS_COMPLETE")
    return ParticipationExperimentResult(lineup=lineup, starter=starter, bullpen=bullpen)


__all__ = [
    "ComponentExperimentResult",
    "NumericPreprocessor",
    "ParticipationExperimentResult",
    "ParticipationTrainingError",
    "TRAINING_SCHEMA_VERSION",
    "run_participation_experiments",
]
