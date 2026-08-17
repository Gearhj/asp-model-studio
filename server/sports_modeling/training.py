from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from .feature_contract import (
    CANDIDATE_FEATURES,
    CONTEXT_FEATURES,
    C_GRID,
    FEATURE_NAMES,
)
from .metrics import PA_CLASS_ORDER, encode_labels, evaluate_multiclass


TRAINING_SCHEMA_VERSION = "MLB_PA_TRAINING_EXPERIMENT_V1"
FOLD_2024_ID = "train-2023-validate-2024"
FOLD_2025_ID = "train-through-2024-validate-2025"
DEFAULT_MAX_ITER = 2_000
DEFAULT_TOLERANCE = 1e-7

_CATEGORICAL_VALUES: Mapping[str, tuple[int, ...]] = {
    "context_top_bottom": (0, 1),
    "context_outs_before": (0, 1, 2),
    "context_base_mask_before": tuple(range(8)),
}
_DISPLAY_NAMES = {
    "C0": "Global eight-class frequency",
    "C1": "Conditional PA-state context",
    "C2": "PA-state context plus batter prior",
    "C3": "PA-state context plus pitcher prior",
    "C4": "Combined PA-state and batter/pitcher priors",
}


class TrainingIntegrityError(RuntimeError):
    """Raised when a required candidate cannot produce honest frozen-fold evidence."""


@dataclass(frozen=True)
class TrainingArrays:
    feature_values: dict[str, np.ndarray]
    labels: np.ndarray
    encoded_labels: np.ndarray
    seasons: np.ndarray
    game_dates: np.ndarray
    game_ids: np.ndarray
    plate_appearance_ids: np.ndarray

    @property
    def row_count(self) -> int:
        return self.labels.size


@dataclass(frozen=True)
class FoldPreprocessor:
    feature_names: tuple[str, ...]
    numeric_state: dict[str, dict[str, Any]]

    @classmethod
    def fit(
        cls,
        feature_values: Mapping[str, np.ndarray],
        feature_names: Sequence[str],
        row_mask: np.ndarray,
    ) -> FoldPreprocessor:
        state: dict[str, dict[str, Any]] = {}
        if row_mask.dtype != np.bool_ or row_mask.ndim != 1 or not np.any(row_mask):
            raise TrainingIntegrityError("preprocessor training mask must contain rows")
        for name in feature_names:
            values = np.asarray(feature_values[name][row_mask], dtype=np.float64)
            if name in _CATEGORICAL_VALUES:
                allowed = np.asarray(_CATEGORICAL_VALUES[name], dtype=np.float64)
                if not np.isfinite(values).all() or not np.isin(values, allowed).all():
                    raise TrainingIntegrityError(f"categorical feature is out of domain: {name}")
                continue
            finite = np.isfinite(values)
            if np.any(finite):
                imputation = float(values[finite].mean())
                imputed = np.where(finite, values, imputation)
                mean = float(imputed.mean())
                scale = float(imputed.std(ddof=0))
                if not math.isfinite(scale) or scale <= 0.0:
                    scale = 1.0
                empty = False
            else:
                imputation = 0.0
                mean = 0.0
                scale = 1.0
                empty = True
            state[name] = {
                "imputationMean": imputation,
                "standardizationMean": mean,
                "standardizationScale": scale,
                "emptyInTrainingFold": empty,
            }
        return cls(feature_names=tuple(feature_names), numeric_state=state)

    def transform(
        self,
        feature_values: Mapping[str, np.ndarray],
        row_mask: np.ndarray,
    ) -> np.ndarray:
        columns: list[np.ndarray] = []
        for name in self.feature_names:
            values = np.asarray(feature_values[name][row_mask], dtype=np.float64)
            if name in _CATEGORICAL_VALUES:
                allowed = np.asarray(_CATEGORICAL_VALUES[name], dtype=np.float64)
                if not np.isfinite(values).all() or not np.isin(values, allowed).all():
                    raise TrainingIntegrityError(f"categorical feature is out of domain: {name}")
                for category in allowed:
                    columns.append((values == category).astype(np.float64)[:, None])
                continue
            item = self.numeric_state[name]
            imputed = np.where(np.isfinite(values), values, item["imputationMean"])
            standardized = (
                imputed - item["standardizationMean"]
            ) / item["standardizationScale"]
            if not np.isfinite(standardized).all():
                raise TrainingIntegrityError(f"preprocessing produced non-finite values: {name}")
            columns.append(standardized[:, None])
        if not columns:
            return np.empty((int(row_mask.sum()), 0), dtype=np.float64)
        return np.ascontiguousarray(np.concatenate(columns, axis=1), dtype=np.float64)

    def state(self) -> dict[str, Any]:
        expanded: list[str] = []
        for name in self.feature_names:
            if name in _CATEGORICAL_VALUES:
                expanded.extend(f"{name}={value}" for value in _CATEGORICAL_VALUES[name])
            else:
                expanded.append(name)
        return {
            "schemaVersion": "MLB_PA_FOLD_PREPROCESSOR_V1",
            "featureNames": list(self.feature_names),
            "categoricalValues": {
                name: list(_CATEGORICAL_VALUES[name])
                for name in self.feature_names
                if name in _CATEGORICAL_VALUES
            },
            "numericState": self.numeric_state,
            "expandedFeatureNames": expanded,
            "imputationScope": "TRAINING_ROWS_OF_THIS_FIT_ONLY",
        }


@dataclass(frozen=True)
class GlobalFrequencyModel:
    probabilities: np.ndarray

    @classmethod
    def fit(cls, labels: np.ndarray) -> GlobalFrequencyModel:
        encoded = encode_labels(labels)
        counts = np.bincount(encoded, minlength=len(PA_CLASS_ORDER)).astype(np.float64)
        if np.any(counts == 0):
            raise TrainingIntegrityError("every frozen class must occur in each training fold")
        return cls(probabilities=counts / counts.sum())

    def predict_proba(self, row_count: int) -> np.ndarray:
        return np.repeat(self.probabilities[None, :], row_count, axis=0)

    def state(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_PA_GLOBAL_FREQUENCY_MODEL_V1",
            "classOrder": list(PA_CLASS_ORDER),
            "probabilities": self.probabilities.tolist(),
        }


@dataclass(frozen=True)
class MultinomialCandidateModel:
    preprocessor: FoldPreprocessor
    estimator: LogisticRegression
    c_value: float
    max_iter: int

    def predict_proba(
        self,
        feature_values: Mapping[str, np.ndarray],
        row_mask: np.ndarray,
    ) -> np.ndarray:
        matrix = self.preprocessor.transform(feature_values, row_mask)
        probabilities = np.asarray(self.estimator.predict_proba(matrix), dtype=np.float64)
        if not np.array_equal(self.estimator.classes_, np.arange(len(PA_CLASS_ORDER))):
            raise TrainingIntegrityError("logistic probability columns differ from frozen class order")
        return probabilities

    def state(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_PA_MULTINOMIAL_LOGISTIC_MODEL_V1",
            "classOrder": list(PA_CLASS_ORDER),
            "estimator": "sklearn.linear_model.LogisticRegression",
            "solver": "lbfgs",
            "penalty": "l2",
            "multiclass": "multinomial",
            "C": self.c_value,
            "maxIter": self.max_iter,
            "nIter": int(np.max(self.estimator.n_iter_)),
            "classes": self.estimator.classes_.astype(int).tolist(),
            "coefficients": self.estimator.coef_.tolist(),
            "intercepts": self.estimator.intercept_.tolist(),
            "preprocessor": self.preprocessor.state(),
        }


@dataclass(frozen=True)
class FoldPredictions:
    fold_id: str
    validation_season: int
    labels: np.ndarray
    encoded_labels: np.ndarray
    game_ids: np.ndarray
    plate_appearance_ids: np.ndarray
    probabilities: dict[str, np.ndarray]


@dataclass
class TrainingExperimentResult:
    candidates: list[dict[str, Any]]
    selected_candidate_id: str
    selected_rationale: str
    folds: dict[int, FoldPredictions]
    models: dict[tuple[int, str], GlobalFrequencyModel | MultinomialCandidateModel]
    split_evidence: dict[str, Any]

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        return next(item for item in self.candidates if item["candidateId"] == candidate_id)


def _column_as_numpy(table: pa.Table, name: str, *, dtype: Any) -> np.ndarray:
    if name not in table.column_names:
        raise TrainingIntegrityError(f"feature view is missing column: {name}")
    try:
        return np.asarray(table[name].combine_chunks().to_pylist(), dtype=dtype)
    except (TypeError, ValueError) as exc:
        raise TrainingIntegrityError(f"feature-view column has incompatible values: {name}") from exc


def training_arrays(table: pa.Table) -> TrainingArrays:
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        raise TrainingIntegrityError("training requires a non-empty pyarrow feature view")
    missing = [name for name in FEATURE_NAMES if name not in table.column_names]
    if missing:
        raise TrainingIntegrityError(f"feature view is missing frozen features: {missing}")
    feature_values = {
        name: _column_as_numpy(table, name, dtype=np.float64)
        for name in FEATURE_NAMES
    }
    labels = _column_as_numpy(table, "outcome", dtype=object)
    encoded = encode_labels(labels)
    seasons = _column_as_numpy(table, "season", dtype=np.int64)
    if not np.isin(seasons, [2023, 2024, 2025]).all():
        raise TrainingIntegrityError("training feature view contains a season outside 2023-2025")
    return TrainingArrays(
        feature_values=feature_values,
        labels=labels,
        encoded_labels=encoded,
        seasons=seasons,
        game_dates=_column_as_numpy(table, "game_date", dtype=object),
        game_ids=_column_as_numpy(table, "game_id", dtype=object),
        plate_appearance_ids=_column_as_numpy(table, "plate_appearance_id", dtype=object),
    )


def chronological_date_atomic_split(
    game_dates: np.ndarray,
    row_mask: np.ndarray,
    *,
    training_fraction: float = 0.8,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    dates = np.asarray(game_dates[row_mask], dtype=object)
    if dates.size < 2 or not 0.0 < training_fraction < 1.0:
        raise TrainingIntegrityError("chronological split requires rows and a fraction in (0,1)")
    ordered_dates, counts = np.unique(dates, return_counts=True)
    if ordered_dates.size < 2:
        raise TrainingIntegrityError("chronological split requires at least two distinct dates")
    cumulative = np.cumsum(counts)
    crossing = int(np.searchsorted(cumulative, training_fraction * dates.size, side="left"))
    crossing = min(crossing, ordered_dates.size - 2)
    last_training_date = ordered_dates[crossing]
    training = row_mask & (game_dates <= last_training_date)
    validation = row_mask & (game_dates > last_training_date)
    if not np.any(training) or not np.any(validation) or np.any(training & validation):
        raise TrainingIntegrityError("date-atomic split produced an empty or overlapping fold")
    return training, validation, {
        "schemaVersion": "MLB_PA_DATE_ATOMIC_SPLIT_V1",
        "sourceSeason": 2023,
        "targetTrainingFraction": training_fraction,
        "lastTrainingDate": str(last_training_date),
        "firstValidationDate": str(np.min(game_dates[validation])),
        "trainingRows": int(training.sum()),
        "validationRows": int(validation.sum()),
        "realizedTrainingFraction": float(training.sum() / row_mask.sum()),
        "dateAtomic": True,
    }


def _fit_logistic(
    arrays: TrainingArrays,
    feature_names: Sequence[str],
    train_mask: np.ndarray,
    *,
    c_value: float,
    max_iter: int,
) -> tuple[MultinomialCandidateModel, int, float]:
    started = time.perf_counter()
    preprocessor = FoldPreprocessor.fit(arrays.feature_values, feature_names, train_mask)
    matrix = preprocessor.transform(arrays.feature_values, train_mask)
    labels = arrays.encoded_labels[train_mask]
    if np.unique(labels).size != len(PA_CLASS_ORDER):
        raise TrainingIntegrityError("every frozen class must occur in each logistic training fold")
    estimator = LogisticRegression(
        C=float(c_value),
        penalty="l2",
        solver="lbfgs",
        max_iter=max_iter,
        tol=DEFAULT_TOLERANCE,
        fit_intercept=True,
        class_weight=None,
        random_state=None,
    )
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(matrix, labels)
    n_iter = int(np.max(estimator.n_iter_))
    if any(issubclass(item.category, ConvergenceWarning) for item in observed) or n_iter >= max_iter:
        raise TrainingIntegrityError(
            f"multinomial lbfgs did not converge before max_iter={max_iter}"
        )
    if not np.array_equal(estimator.classes_, np.arange(len(PA_CLASS_ORDER))):
        raise TrainingIntegrityError("fitted logistic classes differ from frozen class order")
    elapsed = time.perf_counter() - started
    return (
        MultinomialCandidateModel(preprocessor, estimator, float(c_value), max_iter),
        n_iter,
        elapsed,
    )


def _tune_candidate(
    arrays: TrainingArrays,
    candidate_id: str,
    inner_train: np.ndarray,
    inner_validation: np.ndarray,
    *,
    c_grid: Sequence[float],
    max_iter: int,
    progress: Any | None,
) -> tuple[float, list[dict[str, Any]], int, float]:
    evidence: list[dict[str, Any]] = []
    maximum_iterations = 0
    runtime = 0.0
    for c_value in c_grid:
        if progress is not None:
            progress({"stage": "TUNING_2023", "candidateId": candidate_id, "C": float(c_value)})
        model, n_iter, elapsed = _fit_logistic(
            arrays,
            CANDIDATE_FEATURES[candidate_id],
            inner_train,
            c_value=float(c_value),
            max_iter=max_iter,
        )
        probabilities = model.predict_proba(arrays.feature_values, inner_validation)
        metrics = evaluate_multiclass(arrays.labels[inner_validation], probabilities)
        evidence.append(
            {
                "C": float(c_value),
                "trainingRows": int(inner_train.sum()),
                "validationRows": int(inner_validation.sum()),
                "metrics": metrics,
                "nIter": n_iter,
            }
        )
        maximum_iterations = max(maximum_iterations, n_iter)
        runtime += elapsed
    winner = min(
        evidence,
        key=lambda item: (
            item["metrics"]["logLoss"],
            item["metrics"]["brierScore"],
            item["C"],
        ),
    )
    return float(winner["C"]), evidence, maximum_iterations, runtime


def _fold_record(
    *,
    fold_id: str,
    training_seasons: Sequence[int],
    validation_season: int,
    training_rows: int,
    validation_rows: int,
    metrics: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    if metrics is None and status != "NOT_RUN_BY_POLICY":
        raise TrainingIntegrityError("fold metrics may be null only when not run by policy")
    return {
        "foldId": fold_id,
        "status": status,
        "trainingSeasons": list(training_seasons),
        "validationSeason": validation_season,
        "trainingRows": training_rows,
        "validationRows": validation_rows,
        "metrics": metrics,
    }


def run_training_experiment(
    feature_view: pa.Table,
    *,
    c_grid: Sequence[float] = C_GRID,
    max_iter: int = DEFAULT_MAX_ITER,
    progress: Any | None = None,
) -> TrainingExperimentResult:
    """Execute 2023 tuning, 2024 selection, and frozen rolling-origin 2025 validation."""

    if tuple(float(value) for value in c_grid) != C_GRID:
        raise ValueError(f"c_grid must exactly equal the frozen grid {C_GRID}")
    if not isinstance(max_iter, int) or isinstance(max_iter, bool) or max_iter < 10:
        raise ValueError("max_iter must be an integer of at least 10")
    arrays = training_arrays(feature_view)
    masks = {season: arrays.seasons == season for season in (2023, 2024, 2025)}
    if any(not np.any(mask) for mask in masks.values()):
        raise TrainingIntegrityError("all three frozen seasons must contain rows")
    inner_train, inner_validation, split_evidence = chronological_date_atomic_split(
        arrays.game_dates, masks[2023]
    )

    models: dict[tuple[int, str], GlobalFrequencyModel | MultinomialCandidateModel] = {}
    probabilities_2024: dict[str, np.ndarray] = {}
    candidates: list[dict[str, Any]] = []
    selected_c: dict[str, float] = {}
    tuning: dict[str, list[dict[str, Any]]] = {}

    for ordinal, candidate_id in enumerate(CANDIDATE_FEATURES):
        candidate_started = time.perf_counter()
        if progress is not None:
            progress({"stage": "FITTING_2023_VALIDATING_2024", "candidateId": candidate_id})
        maximum_iterations = 0
        tuning_runtime = 0.0
        if candidate_id == "C0":
            model: GlobalFrequencyModel | MultinomialCandidateModel = GlobalFrequencyModel.fit(
                arrays.labels[masks[2023]]
            )
            probabilities = model.predict_proba(int(masks[2024].sum()))
            config = {
                "estimator": "GLOBAL_TRAINING_CLASS_FREQUENCY",
                "classOrder": list(PA_CLASS_ORDER),
                "featureNames": [],
                "trainingScope": "2023",
            }
            convergence = {
                "status": "NOT_APPLICABLE",
                "converged": None,
                "nIter": None,
                "maxIter": None,
                "solver": None,
            }
            tuning_evidence: list[dict[str, Any]] = []
        else:
            winner_c, tuning_evidence, maximum_iterations, tuning_runtime = _tune_candidate(
                arrays,
                candidate_id,
                inner_train,
                inner_validation,
                c_grid=c_grid,
                max_iter=max_iter,
                progress=progress,
            )
            selected_c[candidate_id] = winner_c
            tuning[candidate_id] = tuning_evidence
            model, n_iter, _elapsed = _fit_logistic(
                arrays,
                CANDIDATE_FEATURES[candidate_id],
                masks[2023],
                c_value=winner_c,
                max_iter=max_iter,
            )
            maximum_iterations = max(maximum_iterations, n_iter)
            probabilities = model.predict_proba(arrays.feature_values, masks[2024])
            config = {
                "estimator": "sklearn.linear_model.LogisticRegression",
                "multiclass": "TRUE_MULTINOMIAL",
                "penalty": "l2",
                "solver": "lbfgs",
                "CGrid": list(C_GRID),
                "selectedC": winner_c,
                "maxIter": max_iter,
                "tolerance": DEFAULT_TOLERANCE,
                "featureNames": list(CANDIDATE_FEATURES[candidate_id]),
                "preprocessing": "FOLD_LOCAL_MEAN_IMPUTE_STANDARDIZE_FIXED_ONE_HOT",
            }
            convergence = {
                "status": "CONVERGED",
                "converged": True,
                "nIter": maximum_iterations,
                "maxIter": max_iter,
                "solver": "lbfgs",
            }
        metrics_2024 = evaluate_multiclass(arrays.labels[masks[2024]], probabilities)
        probabilities_2024[candidate_id] = probabilities
        models[(2024, candidate_id)] = model
        runtime = time.perf_counter() - candidate_started
        candidates.append(
            {
                "candidateId": candidate_id,
                "candidateType": (
                    "GLOBAL_CLASS_FREQUENCY" if candidate_id == "C0" else "MULTINOMIAL_LOGISTIC_L2"
                ),
                "displayName": _DISPLAY_NAMES[candidate_id],
                "ordinal": ordinal,
                "config": config,
                "configSha": sha256_bytes(canonical_json_bytes(config)),
                "foldMetrics": [
                    _fold_record(
                        fold_id=FOLD_2024_ID,
                        training_seasons=[2023],
                        validation_season=2024,
                        training_rows=int(masks[2023].sum()),
                        validation_rows=int(masks[2024].sum()),
                        metrics=metrics_2024,
                        status="COMPLETE",
                    )
                ],
                "aggregateMetrics": {
                    "selection2024": metrics_2024,
                    "inner2023Tuning": tuning_evidence,
                    "final2025": None,
                },
                "eligible": True,
                "rejectionReasons": [],
                "runtimeSeconds": round(runtime, 6),
                "convergence": convergence,
            }
        )

    selected_record = min(
        [item for item in candidates if item["candidateId"] != "C0"],
        key=lambda item: (
            item["foldMetrics"][0]["metrics"]["logLoss"],
            item["foldMetrics"][0]["metrics"]["brierScore"],
            item["ordinal"],
        ),
    )
    selected_id = str(selected_record["candidateId"])
    selected_rationale = (
        "Frozen 2024 selection: minimum multiclass log loss, then summed multiclass "
        "Brier score, then predeclared candidate ordinal. No 2025 evidence was used."
    )

    final_candidate_ids = {"C0", "C1", selected_id}
    final_train = masks[2023] | masks[2024]
    probabilities_2025: dict[str, np.ndarray] = {}
    for candidate in candidates:
        candidate_id = candidate["candidateId"]
        if candidate_id not in final_candidate_ids:
            candidate["foldMetrics"].append(
                _fold_record(
                    fold_id=FOLD_2025_ID,
                    training_seasons=[2023, 2024],
                    validation_season=2025,
                    training_rows=int(final_train.sum()),
                    validation_rows=int(masks[2025].sum()),
                    metrics=None,
                    status="NOT_RUN_BY_POLICY",
                )
            )
            continue
        started = time.perf_counter()
        if progress is not None:
            progress({"stage": "REFITTING_2023_2024_VALIDATING_2025", "candidateId": candidate_id})
        if candidate_id == "C0":
            final_model: GlobalFrequencyModel | MultinomialCandidateModel = GlobalFrequencyModel.fit(
                arrays.labels[final_train]
            )
            probabilities = final_model.predict_proba(int(masks[2025].sum()))
        else:
            final_model, n_iter, _elapsed = _fit_logistic(
                arrays,
                CANDIDATE_FEATURES[candidate_id],
                final_train,
                c_value=selected_c[candidate_id],
                max_iter=max_iter,
            )
            candidate["convergence"]["nIter"] = max(
                int(candidate["convergence"]["nIter"]), n_iter
            )
            probabilities = final_model.predict_proba(arrays.feature_values, masks[2025])
        metrics_2025 = evaluate_multiclass(arrays.labels[masks[2025]], probabilities)
        candidate["runtimeSeconds"] = round(
            float(candidate["runtimeSeconds"]) + (time.perf_counter() - started), 6
        )
        candidate["foldMetrics"].append(
            _fold_record(
                fold_id=FOLD_2025_ID,
                training_seasons=[2023, 2024],
                validation_season=2025,
                training_rows=int(final_train.sum()),
                validation_rows=int(masks[2025].sum()),
                metrics=metrics_2025,
                status="COMPLETE",
            )
        )
        candidate["aggregateMetrics"]["final2025"] = metrics_2025
        probabilities_2025[candidate_id] = probabilities
        models[(2025, candidate_id)] = final_model

    folds = {
        2024: FoldPredictions(
            FOLD_2024_ID,
            2024,
            arrays.labels[masks[2024]],
            arrays.encoded_labels[masks[2024]],
            arrays.game_ids[masks[2024]],
            arrays.plate_appearance_ids[masks[2024]],
            probabilities_2024,
        ),
        2025: FoldPredictions(
            FOLD_2025_ID,
            2025,
            arrays.labels[masks[2025]],
            arrays.encoded_labels[masks[2025]],
            arrays.game_ids[masks[2025]],
            arrays.plate_appearance_ids[masks[2025]],
            probabilities_2025,
        ),
    }
    return TrainingExperimentResult(
        candidates=candidates,
        selected_candidate_id=selected_id,
        selected_rationale=selected_rationale,
        folds=folds,
        models=models,
        split_evidence=split_evidence,
    )


__all__ = [
    "DEFAULT_MAX_ITER",
    "DEFAULT_TOLERANCE",
    "FOLD_2024_ID",
    "FOLD_2025_ID",
    "FoldPredictions",
    "FoldPreprocessor",
    "GlobalFrequencyModel",
    "MultinomialCandidateModel",
    "TRAINING_SCHEMA_VERSION",
    "TrainingArrays",
    "TrainingExperimentResult",
    "TrainingIntegrityError",
    "chronological_date_atomic_split",
    "run_training_experiment",
    "training_arrays",
]
