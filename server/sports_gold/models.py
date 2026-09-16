"""Fixed, research-only model suite for the Phase 7B2 Gold feature view.

This module deliberately has no registry, filesystem, publication, or data-loading
authority.  Callers must supply an already-governed in-memory frame and the exact
ordered feature families.  Every fitted statistic is learned from seasons
2021--2023 and every reported metric is computed only on season 2024.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, TypeAlias

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from ..sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    validate_probability_matrix,
)
from ..sports_modeling.training import FoldPreprocessor, GlobalFrequencyModel


SCHEMA_VERSION = "MLB_GOLD_FIXED_EXPERIMENT_SUITE_V1"
DEVELOPMENT_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
RANDOM_SEED = 20260819
ACCEPTED_REFERENCE_LOG_LOSS = 1.4827332596445002

LOGISTIC_CONFIG: dict[str, Any] = {
    "estimator": "sklearn.linear_model.LogisticRegression",
    "penalty": "l2",
    "C": 0.05,
    "solver": "lbfgs",
    "maxIter": 2_000,
    "tolerance": 1e-7,
    "fitIntercept": True,
    "classWeight": None,
    "randomState": None,
}
HGB_CONFIG: dict[str, Any] = {
    "estimator": "sklearn.ensemble.HistGradientBoostingClassifier",
    "maxIter": 200,
    "learningRate": 0.1,
    "maxDepth": None,
    "earlyStopping": False,
    "randomState": RANDOM_SEED,
}
EXTRA_TREES_CONFIG: dict[str, Any] = {
    "estimator": "sklearn.ensemble.ExtraTreesClassifier",
    "nEstimators": 200,
    "maxDepth": 14,
    "minSamplesLeaf": 50,
    "maxFeatures": "sqrt",
    "nJobs": 1,
    "randomState": RANDOM_SEED,
}
XGBOOST_CONFIG: dict[str, Any] = {
    "estimator": "xgboost.XGBClassifier",
    "nEstimators": 300,
    "maxDepth": 6,
    "learningRate": 0.1,
    "subsample": 0.8,
    "colsampleBytree": 0.8,
    "objective": "multi:softprob",
    "numClass": len(PA_CLASS_ORDER),
    "evalMetric": "mlogloss",
    "treeMethod": "hist",
    "nJobs": 1,
    "randomState": RANDOM_SEED,
}


class FixedExperimentInputError(ValueError):
    """Raised when the supplied in-memory experiment frame violates its contract."""


class _OptionalDependencyUnavailable(RuntimeError):
    """Internal signal used to distinguish an optional-model import failure."""


def _frame_feature_values(
    frame: pd.DataFrame, feature_names: Sequence[str]
) -> dict[str, np.ndarray]:
    """Expose columns in the mapping shape required by ``FoldPreprocessor``."""

    return {
        name: frame[name].to_numpy(copy=False)
        for name in feature_names
    }


def _aligned_probability_matrix(estimator: Any, matrix: Any) -> np.ndarray:
    """Align an estimator's class columns to the immutable PA class order."""

    raw = np.asarray(matrix)
    classes = np.asarray(getattr(estimator, "classes_", ()))
    if raw.ndim != 2 or classes.ndim != 1 or raw.shape[1] != classes.size:
        raise ValueError("estimator probability columns do not match estimator classes")

    seen: set[int] = set()
    aligned = np.zeros((raw.shape[0], len(PA_CLASS_ORDER)), dtype=np.float64)
    for column, raw_class in enumerate(classes.tolist()):
        if not isinstance(raw_class, (int, np.integer)) or isinstance(
            raw_class, (bool, np.bool_)
        ):
            raise TypeError("estimator classes must be frozen-order integer indices")
        class_index = int(raw_class)
        if class_index < 0 or class_index >= len(PA_CLASS_ORDER) or class_index in seen:
            raise ValueError("estimator classes are outside or duplicate frozen-order indices")
        seen.add(class_index)
        aligned[:, class_index] = raw[:, column]

    missing = [
        PA_CLASS_ORDER[index]
        for index in range(len(PA_CLASS_ORDER))
        if index not in seen
    ]
    if missing:
        raise ValueError(f"fitted estimator is missing frozen classes: {missing}")
    return validate_probability_matrix(aligned)


@dataclass(frozen=True)
class FittedFixedModel:
    """A fitted estimator coupled to the exact fold-local preprocessor it used."""

    model_id: str
    estimator: Any
    preprocessor: FoldPreprocessor | None
    feature_names: tuple[str, ...]
    effective_config: Mapping[str, Any]

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        """Score a supplied frame in frozen ``PA_CLASS_ORDER`` column order."""

        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        if len(frame) == 0:
            raise ValueError("frame must contain at least one row")
        if self.preprocessor is None:
            return validate_probability_matrix(
                self.estimator.predict_proba(len(frame))
            )
        missing = [name for name in self.feature_names if name not in frame.columns]
        if missing:
            raise ValueError(f"frame is missing fitted model features: {missing}")
        row_mask = np.ones(len(frame), dtype=np.bool_)
        values = _frame_feature_values(frame, self.feature_names)
        transformed = self.preprocessor.transform(values, row_mask)
        return _aligned_probability_matrix(
            self.estimator, self.estimator.predict_proba(transformed)
        )


@dataclass(frozen=True)
class FixedAveragingEnsemble:
    """Unweighted probability average of successful full-Gold models."""

    model_id: str
    member_ids: tuple[str, ...]
    members: tuple[FittedFixedModel, ...]
    feature_names: tuple[str, ...]

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if not self.members:
            raise RuntimeError("ensemble has no fitted members")
        member_probabilities = [member.predict_proba(frame) for member in self.members]
        return validate_probability_matrix(
            np.mean(np.stack(member_probabilities, axis=0), axis=0)
        )


ModelArtifact: TypeAlias = FittedFixedModel | FixedAveragingEnsemble


@dataclass(frozen=True)
class FixedExperimentSuiteResult:
    """In-memory result; no registry or filesystem publication is performed."""

    schema_version: str
    development_seasons: tuple[int, ...]
    validation_season: int
    development_rows: int
    validation_rows: int
    validation_row_positions: np.ndarray
    class_order: tuple[str, ...]
    leaderboard: list[dict[str, Any]]
    models: dict[str, ModelArtifact]
    probabilities: dict[str, np.ndarray]
    ablations: dict[str, dict[str, Any]]
    failures: dict[str, dict[str, Any]]


def _feature_family(
    values: Sequence[str], *, label: str, allow_empty: bool
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise FixedExperimentInputError(f"{label} must be an ordered sequence of names")
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
            raise FixedExperimentInputError(
                f"{label} must contain non-empty, whitespace-normalized strings"
            )
        if raw in result:
            raise FixedExperimentInputError(f"{label} contains duplicate feature {raw!r}")
        result.append(raw)
    if not allow_empty and not result:
        raise FixedExperimentInputError(f"{label} must contain at least one feature")
    return tuple(result)


def _validate_inputs(
    frame: pd.DataFrame,
    *,
    base_features: Sequence[str],
    batter_features: Sequence[str],
    pitcher_features: Sequence[str],
    matchup_features: Sequence[str],
    target_column: str,
    season_column: str,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    np.ndarray,
]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    if frame.empty:
        raise FixedExperimentInputError("frame must contain at least one row")
    if not frame.columns.is_unique:
        raise FixedExperimentInputError("frame columns must be unique")
    if not isinstance(target_column, str) or not target_column:
        raise FixedExperimentInputError("target_column must be a non-empty string")
    if not isinstance(season_column, str) or not season_column:
        raise FixedExperimentInputError("season_column must be a non-empty string")
    if target_column == season_column:
        raise FixedExperimentInputError("target and season columns must differ")

    base = _feature_family(base_features, label="base_features", allow_empty=False)
    batter = _feature_family(
        batter_features, label="batter_features", allow_empty=True
    )
    pitcher = _feature_family(
        pitcher_features, label="pitcher_features", allow_empty=True
    )
    matchup = _feature_family(
        matchup_features, label="matchup_features", allow_empty=True
    )
    all_features = base + batter + pitcher + matchup
    if len(set(all_features)) != len(all_features):
        raise FixedExperimentInputError("feature families must be mutually disjoint")
    if target_column in all_features or season_column in all_features:
        raise FixedExperimentInputError("target and season columns cannot be model features")

    required = (season_column, target_column) + all_features
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise FixedExperimentInputError(f"frame is missing required columns: {missing}")

    try:
        numeric_seasons = pd.to_numeric(frame[season_column], errors="raise").to_numpy(
            dtype=np.float64
        )
    except (TypeError, ValueError) as exc:
        raise FixedExperimentInputError("season values must be numeric integers") from exc
    if not np.isfinite(numeric_seasons).all() or not np.equal(
        numeric_seasons, np.floor(numeric_seasons)
    ).all():
        raise FixedExperimentInputError("season values must be finite integers")
    seasons = numeric_seasons.astype(np.int64)
    if not np.isin(seasons, DEVELOPMENT_SEASONS).any():
        raise FixedExperimentInputError(
            "frame has no development rows in seasons 2021--2023"
        )
    if not np.equal(seasons, VALIDATION_SEASON).any():
        raise FixedExperimentInputError("frame has no validation rows in season 2024")
    return base, batter, pitcher, matchup, seasons


def _missing_classes(encoded: np.ndarray) -> list[str]:
    observed = set(np.asarray(encoded, dtype=np.int64).tolist())
    return [
        class_name
        for index, class_name in enumerate(PA_CLASS_ORDER)
        if index not in observed
    ]


def _warning_records(observed: Sequence[warnings.WarningMessage]) -> list[dict[str, str]]:
    return [
        {
            "category": item.category.__name__,
            "message": str(item.message),
        }
        for item in observed
    ]


def _base_record(
    *,
    model_id: str,
    label: str,
    family: str,
    feature_set: str,
    features: tuple[str, ...],
    config: Mapping[str, Any],
    development_rows: int,
    validation_rows: int,
    missing_development: Sequence[str],
    missing_validation: Sequence[str],
) -> dict[str, Any]:
    return {
        "modelId": model_id,
        "label": label,
        "modelFamily": family,
        "featureSet": feature_set,
        "features": list(features),
        "feature_count": len(features),
        "effectiveConfig": dict(config),
        "status": "PENDING",
        "fitTimeSeconds": 0.0,
        "scoreTimeSeconds": 0.0,
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "validationSeason": VALIDATION_SEASON,
        "devRows": development_rows,
        "valRows": validation_rows,
        "warnings": [],
        "errors": [],
        "missingClasses": {
            "development": list(missing_development),
            "validation": list(missing_validation),
            "estimator": [],
        },
        "failedClasses": [],
        "probabilityValid": False,
        "metrics": None,
        "logLoss": None,
        "brierScore": None,
        "topLabelEce": None,
        "top1Accuracy": None,
        "macroF1": None,
        "acceptedReferenceLogLoss": ACCEPTED_REFERENCE_LOG_LOSS,
        "improvementVsNullLogLoss": None,
        "improvementVsNullLogLossPercent": None,
        "improvementVsAcceptedLogLoss": None,
        "improvementVsAcceptedLogLossPercent": None,
        "beatsNull": None,
        "beatsAcceptedReference": None,
        "rank": None,
    }


def _logistic_factory() -> LogisticRegression:
    return LogisticRegression(
        C=0.05,
        penalty="l2",
        solver="lbfgs",
        max_iter=2_000,
        tol=1e-7,
        fit_intercept=True,
        class_weight=None,
        random_state=None,
    )


def _hgb_factory() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.1,
        max_depth=None,
        early_stopping=False,
        random_state=RANDOM_SEED,
    )


def _extra_trees_factory() -> ExtraTreesClassifier:
    return ExtraTreesClassifier(
        n_estimators=200,
        max_depth=14,
        min_samples_leaf=50,
        max_features="sqrt",
        n_jobs=1,
        random_state=RANDOM_SEED,
    )


def _xgboost_factory() -> Any:
    try:
        from xgboost import XGBClassifier
    except Exception as exc:  # pragma: no cover - installation is environment-specific
        raise _OptionalDependencyUnavailable("xgboost is not installed or importable") from exc
    return XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=len(PA_CLASS_ORDER),
        eval_metric="mlogloss",
        tree_method="hist",
        n_jobs=1,
        random_state=RANDOM_SEED,
    )


def _fit_candidate(
    *,
    model_id: str,
    label: str,
    family: str,
    feature_set: str,
    features: tuple[str, ...],
    config: Mapping[str, Any],
    estimator_factory: Callable[[], Any] | None,
    labels: np.ndarray,
    encoded_development: np.ndarray,
    development_mask: np.ndarray,
    validation_mask: np.ndarray,
    feature_values: Mapping[str, np.ndarray],
    missing_development: Sequence[str],
    missing_validation: Sequence[str],
) -> tuple[dict[str, Any], FittedFixedModel | None, np.ndarray | None]:
    record = _base_record(
        model_id=model_id,
        label=label,
        family=family,
        feature_set=feature_set,
        features=features,
        config=config,
        development_rows=int(development_mask.sum()),
        validation_rows=int(validation_mask.sum()),
        missing_development=missing_development,
        missing_validation=missing_validation,
    )
    observed_warnings: list[warnings.WarningMessage] = []
    fit_started = time.perf_counter()
    scoring_started: float | None = None
    try:
        if missing_development:
            record["failedClasses"] = list(missing_development)
            raise ValueError(
                "development fold is missing frozen classes: "
                f"{list(missing_development)}"
            )

        with warnings.catch_warnings(record=True) as observed_warnings:
            warnings.simplefilter("always")
            if estimator_factory is None:
                estimator = GlobalFrequencyModel.fit(labels[development_mask])
                preprocessor = None
            else:
                preprocessor = FoldPreprocessor.fit(
                    feature_values, features, development_mask
                )
                development_matrix = preprocessor.transform(
                    feature_values, development_mask
                )
                estimator = estimator_factory()
                estimator.fit(development_matrix, encoded_development)
                estimator_classes = np.asarray(getattr(estimator, "classes_", ()))
                if estimator_classes.ndim != 1:
                    raise ValueError("fitted estimator has invalid classes metadata")
                estimator_indices = {
                    int(item)
                    for item in estimator_classes.tolist()
                    if isinstance(item, (int, np.integer))
                    and not isinstance(item, (bool, np.bool_))
                }
                missing_estimator = [
                    class_name
                    for index, class_name in enumerate(PA_CLASS_ORDER)
                    if index not in estimator_indices
                ]
                record["missingClasses"]["estimator"] = missing_estimator
                if missing_estimator:
                    record["failedClasses"] = missing_estimator
                    raise ValueError(
                        f"fitted estimator is missing frozen classes: {missing_estimator}"
                    )

            record["fitTimeSeconds"] = float(time.perf_counter() - fit_started)
            scoring_started = time.perf_counter()
            if preprocessor is None:
                raw_probabilities = estimator.predict_proba(int(validation_mask.sum()))
                probabilities = validate_probability_matrix(raw_probabilities)
            else:
                validation_matrix = preprocessor.transform(
                    feature_values, validation_mask
                )
                probabilities = _aligned_probability_matrix(
                    estimator, estimator.predict_proba(validation_matrix)
                )
            record["scoreTimeSeconds"] = float(
                time.perf_counter() - scoring_started
            )

        metrics = evaluate_multiclass(labels[validation_mask], probabilities)
        record.update(
            {
                "status": "SUCCESS",
                "probabilityValid": True,
                "metrics": metrics,
                "logLoss": float(metrics["logLoss"]),
                "brierScore": float(metrics["brierScore"]),
                "topLabelEce": float(metrics["topLabelEce"]),
                "top1Accuracy": float(metrics["top1Accuracy"]),
                "macroF1": float(metrics["macroF1"]),
            }
        )
        artifact = FittedFixedModel(
            model_id=model_id,
            estimator=estimator,
            preprocessor=preprocessor,
            feature_names=features,
            effective_config=dict(config),
        )
        probabilities.setflags(write=False)
        return record, artifact, probabilities
    except Exception as exc:
        if record["fitTimeSeconds"] == 0.0:
            record["fitTimeSeconds"] = float(time.perf_counter() - fit_started)
        elif scoring_started is not None and record["scoreTimeSeconds"] == 0.0:
            record["scoreTimeSeconds"] = float(time.perf_counter() - scoring_started)
        record["status"] = (
            "UNAVAILABLE"
            if isinstance(exc, _OptionalDependencyUnavailable)
            else "FAILED"
        )
        record["errors"] = [
            {"type": type(exc).__name__, "message": str(exc)}
        ]
        return record, None, None
    finally:
        record["warnings"] = _warning_records(observed_warnings)


def _skipped_xgboost_record(
    *,
    features: tuple[str, ...],
    development_rows: int,
    validation_rows: int,
    missing_development: Sequence[str],
    missing_validation: Sequence[str],
) -> dict[str, Any]:
    record = _base_record(
        model_id="gold_xgboost",
        label="Gold XGBoost",
        family="xgboost",
        feature_set="full",
        features=features,
        config=XGBOOST_CONFIG,
        development_rows=development_rows,
        validation_rows=validation_rows,
        missing_development=missing_development,
        missing_validation=missing_validation,
    )
    record["status"] = "SKIPPED"
    record["warnings"] = [
        {
            "category": "OptionalModelSkipped",
            "message": "xgboost was disabled by include_xgboost=False",
        }
    ]
    return record


def _ensemble_record(
    *,
    features: tuple[str, ...],
    member_ids: Sequence[str],
    excluded_ids: Sequence[str],
    development_rows: int,
    validation_rows: int,
    missing_development: Sequence[str],
    missing_validation: Sequence[str],
) -> dict[str, Any]:
    return _base_record(
        model_id="gold_ensemble",
        label="Gold unweighted probability ensemble",
        family="unweighted_probability_average",
        feature_set="full",
        features=features,
        config={
            "method": "SIMPLE_UNWEIGHTED_PROBABILITY_AVERAGE",
            "memberIds": list(member_ids),
            "excludedMemberIds": list(excluded_ids),
            "selectionOrTuning": False,
        },
        development_rows=development_rows,
        validation_rows=validation_rows,
        missing_development=missing_development,
        missing_validation=missing_validation,
    )


def _add_comparisons_and_rank(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    null_record = next((row for row in records if row["modelId"] == "null"), None)
    null_log_loss = (
        float(null_record["logLoss"])
        if null_record is not None and null_record["status"] == "SUCCESS"
        else None
    )
    for row in records:
        if row["status"] != "SUCCESS":
            continue
        loss = float(row["logLoss"])
        row["improvementVsAcceptedLogLoss"] = (
            ACCEPTED_REFERENCE_LOG_LOSS - loss
        )
        row["improvementVsAcceptedLogLossPercent"] = (
            100.0 * (ACCEPTED_REFERENCE_LOG_LOSS - loss)
            / ACCEPTED_REFERENCE_LOG_LOSS
        )
        row["beatsAcceptedReference"] = loss < ACCEPTED_REFERENCE_LOG_LOSS
        if null_log_loss is not None:
            row["improvementVsNullLogLoss"] = null_log_loss - loss
            row["improvementVsNullLogLossPercent"] = (
                100.0 * (null_log_loss - loss) / null_log_loss
                if null_log_loss != 0.0
                else None
            )
            row["beatsNull"] = loss < null_log_loss

    order = {id(row): index for index, row in enumerate(records)}
    ranked = sorted(
        records,
        key=lambda row: (
            row["status"] != "SUCCESS",
            float(row["logLoss"]) if row["status"] == "SUCCESS" else float("inf"),
            order[id(row)],
        ),
    )
    rank = 0
    for row in ranked:
        if row["status"] == "SUCCESS":
            rank += 1
            row["rank"] = rank
    return ranked


def _ablation_view(
    *,
    name: str,
    record: Mapping[str, Any],
    base_record: Mapping[str, Any],
) -> dict[str, Any]:
    base_loss = base_record.get("logLoss")
    candidate_loss = record.get("logLoss")
    improvement = (
        float(base_loss) - float(candidate_loss)
        if base_loss is not None and candidate_loss is not None
        else None
    )
    return {
        "name": name,
        "modelId": record["modelId"],
        "status": record["status"],
        "features": list(record["features"]),
        "feature_count": int(record["feature_count"]),
        "devRows": int(record["devRows"]),
        "valRows": int(record["valRows"]),
        "probabilityValid": bool(record["probabilityValid"]),
        "metrics": record["metrics"],
        "improvementVsBaseLogLoss": improvement,
        "warnings": list(record["warnings"]),
        "errors": list(record["errors"]),
    }


def run_fixed_experiment_suite(
    frame: pd.DataFrame,
    *,
    base_features: Sequence[str],
    batter_features: Sequence[str],
    pitcher_features: Sequence[str],
    matchup_features: Sequence[str] = (),
    target_column: str = "outcome",
    season_column: str = "season",
    include_xgboost: bool = True,
) -> FixedExperimentSuiteResult:
    """Run the complete fixed Gold experiment and ablation suite in memory.

    There is no search, tuning, persistence, registry mutation, or fallback to other
    seasons. Rows outside 2021--2024 are excluded before feature or target columns
    are materialized. Individual model failures are recorded and do not abort the
    remaining fixed candidates.
    """

    if not isinstance(include_xgboost, (bool, np.bool_)):
        raise TypeError("include_xgboost must be boolean")
    base, batter, pitcher, matchup, seasons = _validate_inputs(
        frame,
        base_features=base_features,
        batter_features=batter_features,
        pitcher_features=pitcher_features,
        matchup_features=matchup_features,
        target_column=target_column,
        season_column=season_column,
    )

    original_development_mask = np.isin(seasons, DEVELOPMENT_SEASONS)
    original_validation_mask = seasons == VALIDATION_SEASON
    selected_positions = np.flatnonzero(
        original_development_mask | original_validation_mask
    )
    selected = frame.iloc[selected_positions]
    selected_seasons = seasons[selected_positions]
    development_mask = np.isin(selected_seasons, DEVELOPMENT_SEASONS)
    validation_mask = selected_seasons == VALIDATION_SEASON

    labels = selected[target_column].to_numpy(copy=False)
    encoded_development = encode_labels(labels[development_mask])
    encoded_validation = encode_labels(labels[validation_mask])
    missing_development = _missing_classes(encoded_development)
    missing_validation = _missing_classes(encoded_validation)

    full = base + batter + pitcher + matchup
    base_batter = base + batter
    base_pitcher = base + pitcher
    feature_values = _frame_feature_values(selected, full)
    records: list[dict[str, Any]] = []
    models: dict[str, ModelArtifact] = {}
    probabilities: dict[str, np.ndarray] = {}

    def run_candidate(
        *,
        model_id: str,
        label: str,
        family: str,
        feature_set: str,
        features: tuple[str, ...],
        config: Mapping[str, Any],
        estimator_factory: Callable[[], Any] | None,
    ) -> dict[str, Any]:
        record, artifact, predicted = _fit_candidate(
            model_id=model_id,
            label=label,
            family=family,
            feature_set=feature_set,
            features=features,
            config=config,
            estimator_factory=estimator_factory,
            labels=labels,
            encoded_development=encoded_development,
            development_mask=development_mask,
            validation_mask=validation_mask,
            feature_values=feature_values,
            missing_development=missing_development,
            missing_validation=missing_validation,
        )
        records.append(record)
        if artifact is not None and predicted is not None:
            models[model_id] = artifact
            probabilities[model_id] = predicted
        return record

    run_candidate(
        model_id="null",
        label="Development-fold global class frequency",
        family="global_frequency",
        feature_set="null",
        features=(),
        config={
            "estimator": "server.sports_modeling.training.GlobalFrequencyModel",
            "smoothing": None,
        },
        estimator_factory=None,
    )
    base_record = run_candidate(
        model_id="base_logistic",
        label="Base logistic",
        family="multinomial_logistic",
        feature_set="base",
        features=base,
        config=LOGISTIC_CONFIG,
        estimator_factory=_logistic_factory,
    )
    full_record = run_candidate(
        model_id="gold_logistic",
        label="Gold logistic",
        family="multinomial_logistic",
        feature_set="full",
        features=full,
        config=LOGISTIC_CONFIG,
        estimator_factory=_logistic_factory,
    )
    run_candidate(
        model_id="gold_hgb",
        label="Gold histogram gradient boosting",
        family="hist_gradient_boosting",
        feature_set="full",
        features=full,
        config=HGB_CONFIG,
        estimator_factory=_hgb_factory,
    )
    run_candidate(
        model_id="gold_extra_trees",
        label="Gold Extra Trees",
        family="extra_trees",
        feature_set="full",
        features=full,
        config=EXTRA_TREES_CONFIG,
        estimator_factory=_extra_trees_factory,
    )
    if bool(include_xgboost):
        run_candidate(
            model_id="gold_xgboost",
            label="Gold XGBoost",
            family="xgboost",
            feature_set="full",
            features=full,
            config=XGBOOST_CONFIG,
            estimator_factory=_xgboost_factory,
        )
    else:
        records.append(
            _skipped_xgboost_record(
                features=full,
                development_rows=int(development_mask.sum()),
                validation_rows=int(validation_mask.sum()),
                missing_development=missing_development,
                missing_validation=missing_validation,
            )
        )

    base_batter_record = run_candidate(
        model_id="ablation_base_batter_logistic",
        label="Ablation logistic: base + batter",
        family="multinomial_logistic",
        feature_set="base+batter",
        features=base_batter,
        config=LOGISTIC_CONFIG,
        estimator_factory=_logistic_factory,
    )
    base_pitcher_record = run_candidate(
        model_id="ablation_base_pitcher_logistic",
        label="Ablation logistic: base + pitcher",
        family="multinomial_logistic",
        feature_set="base+pitcher",
        features=base_pitcher,
        config=LOGISTIC_CONFIG,
        estimator_factory=_logistic_factory,
    )

    ensemble_candidate_ids = (
        "gold_logistic",
        "gold_hgb",
        "gold_extra_trees",
        "gold_xgboost",
    )
    successful_member_ids = tuple(
        model_id
        for model_id in ensemble_candidate_ids
        if model_id in models and model_id in probabilities
    )
    excluded_member_ids = tuple(
        model_id
        for model_id in ensemble_candidate_ids
        if model_id not in successful_member_ids
    )
    ensemble_record = _ensemble_record(
        features=full,
        member_ids=successful_member_ids,
        excluded_ids=excluded_member_ids,
        development_rows=int(development_mask.sum()),
        validation_rows=int(validation_mask.sum()),
        missing_development=missing_development,
        missing_validation=missing_validation,
    )
    ensemble_started = time.perf_counter()
    try:
        if not successful_member_ids:
            raise RuntimeError("no successful full-Gold models are available to ensemble")
        ensemble_probabilities = validate_probability_matrix(
            np.mean(
                np.stack(
                    [probabilities[model_id] for model_id in successful_member_ids],
                    axis=0,
                ),
                axis=0,
            )
        )
        ensemble_record["scoreTimeSeconds"] = float(
            time.perf_counter() - ensemble_started
        )
        ensemble_metrics = evaluate_multiclass(
            labels[validation_mask], ensemble_probabilities
        )
        ensemble_record.update(
            {
                "status": "SUCCESS",
                "probabilityValid": True,
                "metrics": ensemble_metrics,
                "logLoss": float(ensemble_metrics["logLoss"]),
                "brierScore": float(ensemble_metrics["brierScore"]),
                "topLabelEce": float(ensemble_metrics["topLabelEce"]),
                "top1Accuracy": float(ensemble_metrics["top1Accuracy"]),
                "macroF1": float(ensemble_metrics["macroF1"]),
            }
        )
        ensemble = FixedAveragingEnsemble(
            model_id="gold_ensemble",
            member_ids=successful_member_ids,
            members=tuple(
                models[model_id]  # all ensemble candidates are fitted single models
                for model_id in successful_member_ids
                if isinstance(models[model_id], FittedFixedModel)
            ),
            feature_names=full,
        )
        if len(ensemble.members) != len(successful_member_ids):
            raise RuntimeError("ensemble member artifact type is invalid")
        ensemble_probabilities.setflags(write=False)
        models["gold_ensemble"] = ensemble
        probabilities["gold_ensemble"] = ensemble_probabilities
    except Exception as exc:
        ensemble_record["scoreTimeSeconds"] = float(
            time.perf_counter() - ensemble_started
        )
        ensemble_record["status"] = "FAILED"
        ensemble_record["errors"] = [
            {"type": type(exc).__name__, "message": str(exc)}
        ]
    records.append(ensemble_record)

    leaderboard = _add_comparisons_and_rank(records)
    ablations = {
        "base": _ablation_view(
            name="base", record=base_record, base_record=base_record
        ),
        "base+batter": _ablation_view(
            name="base+batter",
            record=base_batter_record,
            base_record=base_record,
        ),
        "base+pitcher": _ablation_view(
            name="base+pitcher",
            record=base_pitcher_record,
            base_record=base_record,
        ),
        "full": _ablation_view(
            name="full", record=full_record, base_record=base_record
        ),
    }
    failures = {
        row["modelId"]: {
            "status": row["status"],
            "warnings": list(row["warnings"]),
            "errors": list(row["errors"]),
            "failedClasses": list(row["failedClasses"]),
            "missingClasses": dict(row["missingClasses"]),
        }
        for row in records
        if row["status"] not in {"SUCCESS", "SKIPPED"}
    }
    validation_positions = selected_positions[validation_mask].astype(
        np.int64, copy=True
    )
    validation_positions.setflags(write=False)
    return FixedExperimentSuiteResult(
        schema_version=SCHEMA_VERSION,
        development_seasons=DEVELOPMENT_SEASONS,
        validation_season=VALIDATION_SEASON,
        development_rows=int(development_mask.sum()),
        validation_rows=int(validation_mask.sum()),
        validation_row_positions=validation_positions,
        class_order=PA_CLASS_ORDER,
        leaderboard=leaderboard,
        models=models,
        probabilities=probabilities,
        ablations=ablations,
        failures=failures,
    )


# Short alias for callers that do not need the longer evidence-oriented name.
run_fixed_suite = run_fixed_experiment_suite


__all__ = [
    "ACCEPTED_REFERENCE_LOG_LOSS",
    "DEVELOPMENT_SEASONS",
    "EXTRA_TREES_CONFIG",
    "FixedAveragingEnsemble",
    "FixedExperimentInputError",
    "FixedExperimentSuiteResult",
    "FittedFixedModel",
    "HGB_CONFIG",
    "LOGISTIC_CONFIG",
    "RANDOM_SEED",
    "SCHEMA_VERSION",
    "VALIDATION_SEASON",
    "XGBOOST_CONFIG",
    "run_fixed_experiment_suite",
    "run_fixed_suite",
]
