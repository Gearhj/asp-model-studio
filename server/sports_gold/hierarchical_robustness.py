"""Development-selected hierarchical OUT/NOT_OUT robustness study.

This module consumes the frozen Phase 7B2 Gold V1 object and its already
published probability artifacts.  It never builds Bronze, Silver, or Gold and
never admits a season outside 2021--2024.  Model and calibration selection use
only chronological 2022/2023 out-of-fold predictions; 2024 is scored once
after the selection record is frozen.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import shutil
import sys
import time
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from server.sports_modeling.bootstrap import game_cluster_bootstrap
from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    validate_probability_matrix,
)
from server.sports_modeling.training import FoldPreprocessor

from . import binary_hierarchical as BH
from .contracts import (
    DEVELOPMENT_SEASONS,
    EXPECTED_GOLD_DEVELOPMENT_ROWS,
    EXPECTED_GOLD_SEASON_ROWS,
    EXPECTED_GOLD_TOTAL_ROWS,
    EXPECTED_GOLD_VALIDATION_ROWS,
    GOLD_FEATURES,
    VALIDATION_SEASON,
)
from .models import FittedFixedModel, LOGISTIC_CONFIG, RANDOM_SEED, _aligned_probability_matrix
from .publication import canonical_json_bytes, sha256_bytes, verify_gold


SCHEMA_VERSION = "MLB_GOLD_HIERARCHICAL_ROBUSTNESS_STUDY_V1"
SELECTION_CONTRACT = "MLB_GOLD_HIERARCHICAL_DEVELOPMENT_OOF_SELECTION_V1"
CALIBRATION_CONTRACT = "MLB_GOLD_BINARY_OOF_CALIBRATION_V1"
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = RANDOM_SEED
OOF_VALIDATION_SEASONS = (2022, 2023)
OOF_EXPECTED_ROWS = int(EXPECTED_GOLD_SEASON_ROWS[2022] + EXPECTED_GOLD_SEASON_ROWS[2023])

TRUSTED_INITIAL_BINARY_EXPERIMENT_SHA256 = (
    "feece979e84ef89f4057fd71c4e3be4d20e5042ea28be4fedd4c2223b16f3591"
)
TRUSTED_INITIAL_BINARY_RESULTS_SHA256 = (
    "df121180534ce4396d8b929abea92f66e28b57a5673a676413cb47fb3b6d4cfc"
)
TRUSTED_INITIAL_EXTRA_TREES_SHA256 = (
    "87e8ce1cbaefa3c338e0eb60f00698bef20d64fc3c1909d1530ea269bb251d55"
)
TRUSTED_INITIAL_EXTRA_TREES_BYTES = 16_733_654
INITIAL_HIERARCHY_LOG_LOSS = 1.4776061122808983

GOVERNED_BASE_PROJECT_ID = "a2v4-601151a6c5"
GOVERNED_BASE_RUN_ID = "1399aa0769ad42a39210979e43300860"
GOVERNED_BASE_BUNDLE_SHA256 = (
    "de43485024ca0a6afe6a6bb522eb05c0c18ecbf1c29fb5e594438640075a4ba1"
)
GOVERNED_BASE_DATASET_SHA256 = (
    "b4bc7a0ebb593e919b6eecfa1b10815314e4a917877571c03d05e531bf36bdea"
)
GOVERNED_BASE_PREDICTION_SHA256 = (
    "320868d9ae1b0fbf27f2a19144d52a555dffea5b1ec3a34cb9fd68dd0cfb555d"
)
GOVERNED_BASE_ROW_IDS_SHA256 = (
    "deaa9b9e0ba51d42a7823b8259b87568fe0100d70ce41d7cf1d5132100819214"
)
GOVERNED_BASE_TARGET_SHA256 = (
    "2e0167164c21e1b61a9e81e050f544e4a05633109a99a4a8cab5292d678c2441"
)
GOVERNED_BASE_MODEL_SHA256 = (
    "ed736d47d218d5b1f34adefc5286691af32740ab97d0b6454b0e46c96de1d686"
)
GOVERNED_BASE_LOG_LOSS = 1.4827332596445002
GOVERNED_FULL_VALIDATION_ROWS = 182_449

PLATT_CONFIG: Mapping[str, Any] = {
    "estimator": "sklearn.linear_model.LogisticRegression",
    "penalty": None,
    "solver": "lbfgs",
    "maxIter": 2_000,
    "tolerance": 1e-12,
    "fitIntercept": True,
    "randomState": RANDOM_SEED,
}
ISOTONIC_CONFIG: Mapping[str, Any] = {
    "estimator": "sklearn.isotonic.IsotonicRegression",
    "increasing": True,
    "outOfBounds": "clip",
    "yMin": 0.0,
    "yMax": 1.0,
}


class HierarchicalRobustnessError(RuntimeError):
    """Raised when fixed study inputs, temporal rules, or artifacts diverge."""


@dataclass(frozen=True)
class FoldDefinition:
    fold_id: str
    training_seasons: tuple[int, ...]
    validation_season: int


FOLD_DEFINITIONS: tuple[FoldDefinition, ...] = (
    FoldDefinition("train_2021_validate_2022", (2021,), 2022),
    FoldDefinition("train_2021_2022_validate_2023", (2021, 2022), 2023),
)


@dataclass(frozen=True)
class CandidateSpec:
    model_id: str
    family: str
    label: str
    config: Mapping[str, Any]
    kind: str


@dataclass(frozen=True)
class FittedProbabilityCalibrator:
    method: str
    estimator: Any | None
    configuration: Mapping[str, Any]

    def transform(self, probabilities: Any) -> np.ndarray:
        values = BH._validate_binary_probability(probabilities)
        if self.method == "raw":
            return values
        if self.method == "platt":
            if type(self.estimator) is not LogisticRegression:
                raise HierarchicalRobustnessError("Platt calibrator identity differs")
            logits = _probability_logit(values)
            result = self.estimator.predict_proba(logits[:, None])[:, 1]
            return BH._validate_binary_probability(result, expected_rows=values.size)
        if self.method == "isotonic":
            if type(self.estimator) is not IsotonicRegression:
                raise HierarchicalRobustnessError("isotonic calibrator identity differs")
            result = self.estimator.predict(values)
            return BH._validate_binary_probability(result, expected_rows=values.size)
        raise HierarchicalRobustnessError(f"unknown calibration method {self.method!r}")


def _probability_logit(probabilities: np.ndarray) -> np.ndarray:
    epsilon = np.finfo(np.float64).eps
    clipped = np.clip(np.asarray(probabilities, dtype=np.float64), epsilon, 1.0 - epsilon)
    return np.log(clipped) - np.log1p(-clipped)


def chronological_fold_masks(seasons: Any) -> list[tuple[FoldDefinition, np.ndarray, np.ndarray]]:
    """Return the two fixed expanding-window development folds."""

    values = np.asarray(seasons)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("seasons must be a non-empty one-dimensional vector")
    if values.dtype.kind not in "iu":
        try:
            parsed = values.astype(np.int64)
        except Exception as exc:  # pragma: no cover - defensive conversion path
            raise TypeError("seasons must be integers") from exc
        if not np.array_equal(parsed.astype(object), values.astype(object)):
            raise TypeError("seasons must be canonical integers")
        values = parsed
    else:
        values = values.astype(np.int64, copy=False)
    observed = {int(value) for value in np.unique(values)}
    if not observed.issubset({2021, 2022, 2023, 2024}):
        raise HierarchicalRobustnessError(f"prohibited season in study frame: {sorted(observed)}")

    result: list[tuple[FoldDefinition, np.ndarray, np.ndarray]] = []
    covered = np.zeros(values.size, dtype=np.bool_)
    for definition in FOLD_DEFINITIONS:
        train = np.isin(values, definition.training_seasons)
        validation = values == definition.validation_season
        if not train.any() or not validation.any() or np.any(train & validation):
            raise HierarchicalRobustnessError(f"chronological fold {definition.fold_id} is empty or overlaps")
        if int(values[train].max()) >= definition.validation_season:
            raise HierarchicalRobustnessError(f"chronological fold {definition.fold_id} leaks validation time")
        covered |= validation
        result.append((definition, train, validation))
    expected = np.isin(values, OOF_VALIDATION_SEASONS)
    if not np.array_equal(covered, expected):
        raise HierarchicalRobustnessError("OOF folds do not cover exactly 2022--2023")
    return result


def candidate_specs() -> tuple[CandidateSpec, ...]:
    specs: list[CandidateSpec] = []
    for c_value in (0.01, 0.05, 0.20, 1.00):
        specs.append(CandidateSpec(
            model_id=f"gold_binary_logistic_c_{str(c_value).replace('.', '_')}",
            family="gold_binary_logistic",
            label=f"Gold binary Logistic C={c_value:g}",
            kind="binary_logistic",
            config={
                "C": c_value, "penalty": "l2", "solver": "lbfgs", "maxIter": 2_000,
                "tolerance": 1e-7, "fitIntercept": True, "classWeight": None,
                "randomState": RANDOM_SEED,
            },
        ))
    for max_features in ("sqrt", 0.5):
        for min_leaf in (20, 100):
            max_label = "sqrt" if max_features == "sqrt" else "0_5"
            specs.append(CandidateSpec(
                model_id=f"gold_binary_extra_trees_mf_{max_label}_leaf_{min_leaf}",
                family="gold_binary_extra_trees",
                label=f"Gold binary Extra Trees max_features={max_features}, leaf={min_leaf}",
                kind="binary_extra_trees",
                config={
                    "nEstimators": 300, "maxFeatures": max_features,
                    "minSamplesLeaf": min_leaf, "maxDepth": None, "nJobs": 1,
                    "randomState": RANDOM_SEED,
                },
            ))
    for learning_rate in (0.05, 0.10):
        for max_leaf_nodes in (15, 31):
            specs.append(CandidateSpec(
                model_id=(
                    f"gold_binary_hgb_lr_{str(learning_rate).replace('.', '_')}_leaves_{max_leaf_nodes}"
                ),
                family="gold_binary_hgb",
                label=f"Gold binary HGB learning_rate={learning_rate:g}, leaves={max_leaf_nodes}",
                kind="binary_hgb",
                config={
                    "maxIter": 200, "learningRate": learning_rate,
                    "maxLeafNodes": max_leaf_nodes, "minSamplesLeaf": 50,
                    "earlyStopping": False, "randomState": RANDOM_SEED,
                },
            ))
    specs.append(CandidateSpec(
        model_id="collapsed_direct_gold_logistic",
        family="collapsed_direct_gold_logistic",
        label="Collapsed direct Gold Logistic",
        kind="multiclass_logistic_collapse",
        config=dict(LOGISTIC_CONFIG),
    ))
    if len(specs) != 13 or len({item.model_id for item in specs}) != 13:
        raise AssertionError("fixed candidate suite inventory differs")
    return tuple(specs)


def _binary_estimator(spec: CandidateSpec) -> Any:
    if spec.kind == "binary_logistic":
        return LogisticRegression(
            C=float(spec.config["C"]), penalty="l2", solver="lbfgs", max_iter=2_000,
            tol=1e-7, fit_intercept=True, class_weight=None, random_state=RANDOM_SEED,
        )
    if spec.kind == "binary_extra_trees":
        return ExtraTreesClassifier(
            n_estimators=300, max_features=spec.config["maxFeatures"],
            min_samples_leaf=int(spec.config["minSamplesLeaf"]), max_depth=None,
            n_jobs=1, random_state=RANDOM_SEED,
        )
    if spec.kind == "binary_hgb":
        return HistGradientBoostingClassifier(
            max_iter=200, learning_rate=float(spec.config["learningRate"]),
            max_leaf_nodes=int(spec.config["maxLeafNodes"]), min_samples_leaf=50,
            early_stopping=False, random_state=RANDOM_SEED,
        )
    raise HierarchicalRobustnessError(f"{spec.model_id} is not a dedicated binary candidate")


def _multiclass_logistic() -> LogisticRegression:
    return LogisticRegression(
        C=0.05, penalty="l2", solver="lbfgs", max_iter=2_000, tol=1e-7,
        fit_intercept=True, class_weight=None, random_state=None,
    )


def fit_probability_calibrator(
    method: str, labels: Any, probabilities: Any,
) -> FittedProbabilityCalibrator:
    """Fit one of the three fixed calibration choices on OOF data only."""

    y = np.asarray(labels)
    if y.ndim != 1 or y.size == 0 or set(y.tolist()) != {0, 1}:
        raise ValueError("calibration labels must be a non-empty two-class 0/1 vector")
    y = y.astype(np.int8, copy=False)
    p = BH._validate_binary_probability(probabilities, expected_rows=y.size)
    normalized = str(method).strip().lower()
    if normalized == "raw":
        return FittedProbabilityCalibrator("raw", None, {})
    if normalized == "platt":
        estimator = LogisticRegression(
            penalty=None, solver="lbfgs", max_iter=2_000, tol=1e-12,
            fit_intercept=True, random_state=RANDOM_SEED,
        )
        estimator.fit(_probability_logit(p)[:, None], y)
        if not np.array_equal(estimator.classes_, np.asarray([0, 1])):
            raise HierarchicalRobustnessError("Platt calibrator class order differs")
        return FittedProbabilityCalibrator("platt", estimator, dict(PLATT_CONFIG))
    if normalized == "isotonic":
        estimator = IsotonicRegression(
            increasing=True, out_of_bounds="clip", y_min=0.0, y_max=1.0,
        )
        estimator.fit(p, y)
        return FittedProbabilityCalibrator("isotonic", estimator, dict(ISOTONIC_CONFIG))
    raise ValueError("calibration method must be raw, platt, or isotonic")


def _selection_key(record: Mapping[str, Any]) -> tuple[float, float, float, float, str, str]:
    metrics = record["metrics"]
    intercept = float(metrics["calibrationIntercept"])
    slope_value = metrics.get("calibrationSlope")
    slope_penalty = math.inf if slope_value is None else abs(float(slope_value) - 1.0)
    return (
        float(metrics["binaryLogLoss"]), float(metrics["brierScore"]),
        float(metrics["ece"]), abs(intercept) + slope_penalty,
        str(record["family"]), str(record["calibrationMethod"]),
    )


def select_calibrated_candidate(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    successful = [row for row in records if row.get("status") == "SUCCESS"]
    if not successful:
        raise HierarchicalRobustnessError("no successful calibrated candidates")
    return min(successful, key=_selection_key)


def _fit_one_fold_candidate(
    *, spec: CandidateSpec, training_matrix: Any, validation_matrix: Any,
    training_binary: np.ndarray, validation_rows: int,
    training_multiclass: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    fit_started = time.perf_counter()
    observed: list[warnings.WarningMessage] = []
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        if spec.kind == "multiclass_logistic_collapse":
            estimator = _multiclass_logistic()
            estimator.fit(training_matrix, training_multiclass)
        else:
            estimator = _binary_estimator(spec)
            estimator.fit(training_matrix, training_binary)
    fit_seconds = float(time.perf_counter() - fit_started)

    score_started = time.perf_counter()
    if spec.kind == "multiclass_logistic_collapse":
        probabilities8 = _aligned_probability_matrix(
            estimator, estimator.predict_proba(validation_matrix)
        )
        predicted = BH.collapsed_out_probability(probabilities8)
        expected_classes = np.arange(len(PA_CLASS_ORDER), dtype=np.int64)
    else:
        classes = np.asarray(getattr(estimator, "classes_", ()))
        if not np.array_equal(classes, np.asarray([0, 1])):
            raise HierarchicalRobustnessError(f"{spec.model_id} binary classes differ")
        predicted = BH._validate_binary_probability(
            estimator.predict_proba(validation_matrix)[:, 1], expected_rows=validation_rows
        )
        expected_classes = np.asarray([0, 1], dtype=np.int64)
    score_seconds = float(time.perf_counter() - score_started)
    if not np.array_equal(np.asarray(estimator.classes_), expected_classes):
        raise HierarchicalRobustnessError(f"{spec.model_id} estimator class order differs")
    return predicted, {
        "fitTimeSeconds": fit_seconds,
        "scoreTimeSeconds": score_seconds,
        "warnings": [
            {"category": item.category.__name__, "message": str(item.message)}
            for item in observed
        ],
    }


def generate_chronological_oof(
    frame: pd.DataFrame,
    labels: np.ndarray,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], np.ndarray, list[dict[str, Any]]]:
    """Fit the fixed suite on the two expanding folds and return 2022--23 OOF scores."""

    emit = progress or (lambda _message: None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("frame must be a non-empty pandas DataFrame")
    required = {"season", "outcome", *GOLD_FEATURES}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"OOF frame is missing columns: {missing}")
    binary = np.asarray(labels)
    if binary.ndim != 1 or binary.shape[0] != len(frame) or not np.isin(binary, [0, 1]).all():
        raise ValueError("binary labels must be row-aligned 0/1 values")
    binary = binary.astype(np.int8, copy=False)
    seasons = frame["season"].to_numpy(dtype=np.int64, copy=False)
    folds = chronological_fold_masks(seasons)
    oof_mask = np.isin(seasons, OOF_VALIDATION_SEASONS)
    oof_positions = np.flatnonzero(oof_mask)
    if len(frame) == EXPECTED_GOLD_TOTAL_ROWS and oof_positions.size != OOF_EXPECTED_ROWS:
        raise HierarchicalRobustnessError("full-corpus OOF row count differs")
    oof_lookup = np.full(len(frame), -1, dtype=np.int64)
    oof_lookup[oof_positions] = np.arange(oof_positions.size, dtype=np.int64)
    specs = candidate_specs()
    oof_predictions = {
        spec.model_id: np.full(oof_positions.size, np.nan, dtype=np.float64)
        for spec in specs
    }
    fold_records_by_model: dict[str, list[dict[str, Any]]] = {
        spec.model_id: [] for spec in specs
    }
    fold_inventory: list[dict[str, Any]] = []
    feature_values = {
        name: frame[name].to_numpy(copy=False) for name in GOLD_FEATURES
    }
    encoded_multiclass = encode_labels(frame["outcome"].to_numpy(copy=False))

    for definition, training_mask, validation_mask in folds:
        emit(
            f"OOF {definition.fold_id}: fitting 13 fixed candidates "
            f"({int(training_mask.sum()):,} train / {int(validation_mask.sum()):,} validate)"
        )
        preprocessor_started = time.perf_counter()
        preprocessor = FoldPreprocessor.fit(feature_values, tuple(GOLD_FEATURES), training_mask)
        training_matrix = preprocessor.transform(feature_values, training_mask)
        validation_matrix = preprocessor.transform(feature_values, validation_mask)
        preprocessor_seconds = float(time.perf_counter() - preprocessor_started)
        validation_positions = np.flatnonzero(validation_mask)
        output_positions = oof_lookup[validation_positions]
        if np.any(output_positions < 0):
            raise HierarchicalRobustnessError("OOF validation rows fall outside 2022--2023")
        fold_inventory.append({
            "foldId": definition.fold_id,
            "trainingSeasons": list(definition.training_seasons),
            "validationSeason": definition.validation_season,
            "trainingRows": int(training_mask.sum()),
            "validationRows": int(validation_mask.sum()),
            "preprocessorFitAndTransformSeconds": preprocessor_seconds,
            "selectionSeasonUsed": False,
            "uses2024": False,
        })

        for spec in specs:
            emit(f"OOF {definition.fold_id}: {spec.label}")
            record: dict[str, Any] = {
                "foldId": definition.fold_id,
                "trainingSeasons": list(definition.training_seasons),
                "validationSeason": definition.validation_season,
                "trainingRows": int(training_mask.sum()),
                "validationRows": int(validation_mask.sum()),
                "status": "PENDING",
                "fitTimeSeconds": 0.0,
                "scoreTimeSeconds": 0.0,
                "warnings": [],
                "errors": [],
            }
            try:
                predicted, timing = _fit_one_fold_candidate(
                    spec=spec,
                    training_matrix=training_matrix,
                    validation_matrix=validation_matrix,
                    training_binary=binary[training_mask],
                    validation_rows=int(validation_mask.sum()),
                    training_multiclass=encoded_multiclass[training_mask],
                )
                oof_predictions[spec.model_id][output_positions] = predicted
                record.update(timing)
                record["status"] = "SUCCESS"
            except Exception as exc:
                record["status"] = "FAILED"
                record["errors"] = [{"type": type(exc).__name__, "message": str(exc)}]
            fold_records_by_model[spec.model_id].append(record)
        del training_matrix, validation_matrix, preprocessor

    leaderboard: list[dict[str, Any]] = []
    oof_labels = binary[oof_positions]
    for spec in specs:
        predictions = oof_predictions[spec.model_id]
        fold_records = fold_records_by_model[spec.model_id]
        success = all(item["status"] == "SUCCESS" for item in fold_records)
        record: dict[str, Any] = {
            "modelId": spec.model_id,
            "family": spec.family,
            "label": spec.label,
            "kind": spec.kind,
            "status": "SUCCESS" if success else "FAILED",
            "effectiveConfig": dict(spec.config),
            "featureCount": len(GOLD_FEATURES),
            "oofSeasons": list(OOF_VALIDATION_SEASONS),
            "oofRows": int(oof_positions.size),
            "uses2024": False,
            "folds": fold_records,
            "fitTimeSeconds": float(sum(item["fitTimeSeconds"] for item in fold_records)),
            "scoreTimeSeconds": float(sum(item["scoreTimeSeconds"] for item in fold_records)),
            "warnings": [warning for item in fold_records for warning in item["warnings"]],
            "errors": [error for item in fold_records for error in item["errors"]],
        }
        if success:
            if not np.isfinite(predictions).all():
                raise HierarchicalRobustnessError(f"{spec.model_id} OOF predictions are incomplete")
            metric_started = time.perf_counter()
            record["metrics"] = BH.evaluate_binary(oof_labels, predictions)
            record["metricTimeSeconds"] = float(time.perf_counter() - metric_started)
        else:
            record["metrics"] = None
            record["metricTimeSeconds"] = 0.0
        leaderboard.append(record)
    return leaderboard, oof_predictions, oof_positions, fold_inventory


def calibrate_family_winners(
    *,
    leaderboard: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, np.ndarray],
    oof_labels: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], FittedProbabilityCalibrator]]:
    """Choose one raw candidate per family, then compare the three calibrators."""

    families = (
        "gold_binary_logistic", "gold_binary_extra_trees", "gold_binary_hgb",
        "collapsed_direct_gold_logistic",
    )
    winners: dict[str, Mapping[str, Any]] = {}
    for family in families:
        candidates = [
            row for row in leaderboard
            if row.get("family") == family and row.get("status") == "SUCCESS"
        ]
        if not candidates:
            raise HierarchicalRobustnessError(f"OOF family {family} has no successful candidate")
        winners[family] = min(
            candidates,
            key=lambda row: (
                float(row["metrics"]["binaryLogLoss"]),
                float(row["metrics"]["brierScore"]),
                float(row["metrics"]["ece"]),
                str(row["modelId"]),
            ),
        )

    comparison: list[dict[str, Any]] = []
    calibrators: dict[tuple[str, str], FittedProbabilityCalibrator] = {}
    for family in families:
        winner = winners[family]
        raw = predictions[str(winner["modelId"])]
        for method in ("raw", "platt", "isotonic"):
            started = time.perf_counter()
            try:
                calibrator = fit_probability_calibrator(method, oof_labels, raw)
                calibrated = calibrator.transform(raw)
                metrics = BH.evaluate_binary(oof_labels, calibrated)
                calibrators[(family, method)] = calibrator
                comparison.append({
                    "family": family,
                    "sourceModelId": winner["modelId"],
                    "calibrationMethod": method,
                    "status": "SUCCESS",
                    "calibrationContract": CALIBRATION_CONTRACT,
                    "calibrationFitSeasons": list(OOF_VALIDATION_SEASONS),
                    "calibrationFitRows": int(oof_labels.size),
                    "uses2024": False,
                    "configuration": dict(calibrator.configuration),
                    "metrics": metrics,
                    "fitAndScoreTimeSeconds": float(time.perf_counter() - started),
                    "errors": [],
                })
            except Exception as exc:
                comparison.append({
                    "family": family,
                    "sourceModelId": winner["modelId"],
                    "calibrationMethod": method,
                    "status": "FAILED",
                    "calibrationContract": CALIBRATION_CONTRACT,
                    "calibrationFitSeasons": list(OOF_VALIDATION_SEASONS),
                    "calibrationFitRows": int(oof_labels.size),
                    "uses2024": False,
                    "configuration": {},
                    "metrics": None,
                    "fitAndScoreTimeSeconds": float(time.perf_counter() - started),
                    "errors": [{"type": type(exc).__name__, "message": str(exc)}],
                })
    return comparison, calibrators


def _refit_selected_binary(
    *,
    spec: CandidateSpec,
    frame: pd.DataFrame,
    development_mask: np.ndarray,
    validation_mask: np.ndarray,
    labels: np.ndarray,
    direct_gold_artifact: FittedFixedModel,
) -> tuple[FittedBinaryModel | None, np.ndarray, dict[str, Any]]:
    """Refit the frozen selected underlying model on all matched 2021--23 rows."""

    if spec.kind == "multiclass_logistic_collapse":
        started = time.perf_counter()
        probabilities8 = direct_gold_artifact.predict_proba(
            frame.loc[validation_mask].reset_index(drop=True)
        )
        predicted = BH.collapsed_out_probability(probabilities8)
        return None, predicted, {
            "underlyingModelId": spec.model_id,
            "refitSource": "EXISTING_PERSISTED_DIRECT_GOLD_LOGISTIC_TRAINED_2021_2023",
            "developmentRows": int(development_mask.sum()),
            "scoreRows": int(validation_mask.sum()),
            "fitTimeSeconds": 0.0,
            "scoreTimeSeconds": float(time.perf_counter() - started),
            "uses2024ForFit": False,
        }

    values = {name: frame[name].to_numpy(copy=False) for name in GOLD_FEATURES}
    fit_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        preprocessor = FoldPreprocessor.fit(values, tuple(GOLD_FEATURES), development_mask)
        training_matrix = preprocessor.transform(values, development_mask)
        estimator = _binary_estimator(spec)
        estimator.fit(training_matrix, labels[development_mask])
    fit_seconds = float(time.perf_counter() - fit_started)
    if not np.array_equal(np.asarray(estimator.classes_), np.asarray([0, 1])):
        raise HierarchicalRobustnessError("selected refit binary classes differ")
    fitted = BH.FittedBinaryModel(
        model_id=spec.model_id,
        estimator=estimator,
        preprocessor=preprocessor,
        feature_names=tuple(GOLD_FEATURES),
        effective_config=dict(spec.config),
    )
    score_started = time.perf_counter()
    predicted = fitted.predict_out_probability(frame.loc[validation_mask].reset_index(drop=True))
    score_seconds = float(time.perf_counter() - score_started)
    return fitted, predicted, {
        "underlyingModelId": spec.model_id,
        "refitSource": "REFIT_FIXED_SELECTED_BINARY_ON_ALL_MATCHED_2021_2023",
        "developmentRows": int(development_mask.sum()),
        "scoreRows": int(validation_mask.sum()),
        "fitTimeSeconds": fit_seconds,
        "scoreTimeSeconds": score_seconds,
        "uses2024ForFit": False,
        "warnings": [
            {"category": item.category.__name__, "message": str(item.message)}
            for item in observed
        ],
    }


def _load_initial_extra_trees(gold_root: Path) -> tuple[BH.FittedBinaryModel, dict[str, Any]]:
    root = Path(gold_root).resolve()
    final = root / "binary-experiments" / "sha256" / TRUSTED_INITIAL_BINARY_EXPERIMENT_SHA256
    manifest_path = final / "manifest.json"
    results_path = final / "results.json"
    if not final.is_dir() or not manifest_path.is_file() or not results_path.is_file():
        raise HierarchicalRobustnessError("trusted initial binary experiment is missing")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    results_bytes = results_path.read_bytes()
    if manifest.get("experimentSha256") != TRUSTED_INITIAL_BINARY_EXPERIMENT_SHA256:
        raise HierarchicalRobustnessError("initial binary experiment address differs")
    if manifest.get("resultsSha256") != TRUSTED_INITIAL_BINARY_RESULTS_SHA256 \
            or hashlib.sha256(results_bytes).hexdigest() != TRUSTED_INITIAL_BINARY_RESULTS_SHA256:
        raise HierarchicalRobustnessError("initial binary experiment results differ")
    if manifest.get("status") != "RESEARCH_ONLY" \
            or manifest.get("promotionEligible") is not False \
            or manifest.get("championEligible") is not False:
        raise HierarchicalRobustnessError("initial binary experiment governance differs")
    request = manifest.get("request") or {}
    if request.get("goldLogicalContentSha256") != (
        "56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0"
    ) or request.get("developmentSeasons") != [2021, 2022, 2023] \
            or request.get("validationSeason") != 2024 \
            or request.get("developmentRows") != EXPECTED_GOLD_DEVELOPMENT_ROWS \
            or request.get("validationRows") != EXPECTED_GOLD_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("initial binary experiment population differs")
    model_id = "dedicated_gold_binary_extra_trees"
    entry = (manifest.get("modelArtifacts") or {}).get(model_id)
    if not isinstance(entry, dict) or entry.get("relativePath") != f"models/{model_id}.joblib" \
            or entry.get("bytes") != TRUSTED_INITIAL_EXTRA_TREES_BYTES \
            or entry.get("sha256") != TRUSTED_INITIAL_EXTRA_TREES_SHA256:
        raise HierarchicalRobustnessError("initial Extra Trees inventory differs")
    path = (final / entry["relativePath"]).resolve()
    if final not in path.parents or not path.is_file():
        raise HierarchicalRobustnessError("initial Extra Trees path is unsafe or missing")
    data = path.read_bytes()
    if len(data) != TRUSTED_INITIAL_EXTRA_TREES_BYTES \
            or hashlib.sha256(data).hexdigest() != TRUSTED_INITIAL_EXTRA_TREES_SHA256:
        raise HierarchicalRobustnessError("initial Extra Trees bytes differ")
    artifact = joblib.load(io.BytesIO(data))
    if type(artifact) is not BH.FittedBinaryModel \
            or artifact.model_id != model_id \
            or artifact.feature_names != tuple(GOLD_FEATURES) \
            or type(artifact.estimator) is not ExtraTreesClassifier \
            or type(artifact.preprocessor) is not FoldPreprocessor:
        raise HierarchicalRobustnessError("initial Extra Trees fitted identity differs")
    expected_config = dict((request.get("modelConfigs") or {}).get("extraTrees") or {})
    if dict(artifact.effective_config) != expected_config:
        raise HierarchicalRobustnessError("initial Extra Trees configuration differs")
    parameters = artifact.estimator.get_params(deep=False)
    expected_parameters = {
        "n_estimators": 200, "max_depth": 14, "min_samples_leaf": 50,
        "max_features": "sqrt", "n_jobs": 1, "random_state": RANDOM_SEED,
    }
    if any(parameters.get(key) != value for key, value in expected_parameters.items()):
        raise HierarchicalRobustnessError("initial Extra Trees estimator parameters differ")
    return artifact, {
        "experimentSha256": TRUSTED_INITIAL_BINARY_EXPERIMENT_SHA256,
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "resultsSha256": TRUSTED_INITIAL_BINARY_RESULTS_SHA256,
        "modelId": model_id,
        "modelSha256": TRUSTED_INITIAL_EXTRA_TREES_SHA256,
        "modelBytes": TRUSTED_INITIAL_EXTRA_TREES_BYTES,
    }


def _required_multiclass_metrics(labels: Any, probabilities: Any) -> dict[str, Any]:
    metrics = evaluate_multiclass(labels, probabilities)
    return {
        "rowCount": int(metrics["rowCount"]),
        "logLoss": float(metrics["logLoss"]),
        "brierScore": float(metrics["brierScore"]),
        "ece": float(metrics["topLabelEce"]),
        "accuracy": float(metrics["top1Accuracy"]),
        "macroF1": float(metrics["macroF1"]),
        "classOrder": list(metrics["classOrder"]),
    }


def matched_2024_comparison(
    *, labels: Any, direct: Any, initial: Any, selected: Any,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=object)
    direct8 = validate_probability_matrix(direct)
    initial8 = validate_probability_matrix(initial)
    selected8 = validate_probability_matrix(selected)
    if not (len(y) == len(direct8) == len(initial8) == len(selected8)):
        raise ValueError("matched comparison inputs are not row-aligned")
    binary = BH.binary_labels(y)
    rows: dict[str, Any] = {}
    for model_id, matrix in (
        ("direct_gold_logistic", direct8),
        ("initial_raw_extra_trees_hierarchy", initial8),
        ("development_selected_calibrated_hierarchy", selected8),
    ):
        rows[model_id] = {
            "multiclass": _required_multiclass_metrics(y, matrix),
            "binary": BH.evaluate_binary(binary, BH.collapsed_out_probability(matrix)),
        }
    rows["initial_raw_extra_trees_hierarchy"]["multiclass"][
        "logLossDifferenceVsDirect"
    ] = float(
        rows["initial_raw_extra_trees_hierarchy"]["multiclass"]["logLoss"]
        - rows["direct_gold_logistic"]["multiclass"]["logLoss"]
    )
    rows["development_selected_calibrated_hierarchy"]["multiclass"][
        "logLossDifferenceVsDirect"
    ] = float(
        rows["development_selected_calibrated_hierarchy"]["multiclass"]["logLoss"]
        - rows["direct_gold_logistic"]["multiclass"]["logLoss"]
    )
    return rows


def compact_game_bootstrap(
    *, labels: Any, selected: Any, direct: Any, game_ids: Any,
    n_resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
) -> tuple[dict[str, Any], np.ndarray]:
    evidence = game_cluster_bootstrap(
        labels, selected, direct, game_ids,
        n_resamples=n_resamples, seed=seed,
    )
    log = evidence["logLossDifference"]
    replicates = np.asarray(log["replicateDifferences"], dtype=np.float64)
    if replicates.shape != (n_resamples,) or not np.isfinite(replicates).all():
        raise HierarchicalRobustnessError("game bootstrap replicates are incomplete")
    summary = {
        "schemaVersion": evidence["schemaVersion"],
        "differenceConvention": evidence["differenceConvention"],
        "resamplingUnit": evidence["resamplingUnit"],
        "rowsSampledIndependently": evidence["rowsSampledIndependently"],
        "rowCount": evidence["rowCount"],
        "clusterCount": evidence["clusterCount"],
        "resampleCount": evidence["resampleCount"],
        "seed": evidence["seed"],
        "pointEstimate": float(log["pointEstimate"]),
        "meanDifference": float(log["bootstrapMean"]),
        "medianDifference": float(np.median(replicates)),
        "confidenceInterval95": {
            "lower": float(log["percentileInterval"]["lower"]),
            "upper": float(log["percentileInterval"]["upper"]),
        },
        "percentReplicatesFavorHierarchy": float(100.0 * np.mean(replicates < 0.0)),
        "replicateSha256": hashlib.sha256(
            np.ascontiguousarray(replicates, dtype=np.float64).tobytes()
        ).hexdigest(),
    }
    return summary, replicates


def _slice_metric(
    *, slice_group: str, slice_name: str, mask: np.ndarray,
    labels: np.ndarray, direct: np.ndarray, selected: np.ndarray,
) -> dict[str, Any]:
    count = int(mask.sum())
    if count == 0:
        return {
            "sliceGroup": slice_group, "slice": slice_name, "rows": 0,
            "status": "EMPTY_NOT_ESTIMABLE", "directLogLoss": None,
            "hierarchicalLogLoss": None, "differenceHierarchyMinusDirect": None,
        }
    direct_metrics = _required_multiclass_metrics(labels[mask], direct[mask])
    selected_metrics = _required_multiclass_metrics(labels[mask], selected[mask])
    return {
        "sliceGroup": slice_group,
        "slice": slice_name,
        "rows": count,
        "status": "COMPLETE",
        "directLogLoss": direct_metrics["logLoss"],
        "hierarchicalLogLoss": selected_metrics["logLoss"],
        "differenceHierarchyMinusDirect": float(
            selected_metrics["logLoss"] - direct_metrics["logLoss"]
        ),
    }


def stability_slices(
    *,
    validation: pd.DataFrame,
    development: pd.DataFrame,
    direct: Any,
    selected: Any,
    game_types: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Compute exactly the bounded slice inventory requested by the study."""

    required = {
        "outcome", "game_date", "canonicalGameId", "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId", "batter_last100_pa_count", "pitcher_last250_bf_count",
    }
    missing = sorted(required - set(validation.columns))
    if missing:
        raise ValueError(f"slice frame is missing columns: {missing}")
    labels = validation["outcome"].to_numpy(dtype=object, copy=False)
    direct8 = validate_probability_matrix(direct)
    selected8 = validate_probability_matrix(selected)
    if len(validation) != len(direct8) or len(validation) != len(selected8):
        raise ValueError("slice probabilities are not row-aligned")
    dates = pd.to_datetime(validation["game_date"], format="%Y-%m-%d", errors="raise")
    if not (dates.dt.year == 2024).all():
        raise HierarchicalRobustnessError("slice frame contains a non-2024 date")
    rows: list[dict[str, Any]] = []
    for month in sorted(dates.dt.month.unique().tolist()):
        rows.append(_slice_metric(
            slice_group="month", slice_name=f"2024-{int(month):02d}",
            mask=(dates.dt.month.to_numpy() == month), labels=labels,
            direct=direct8, selected=selected8,
        ))

    mapped_types = np.asarray([
        str(game_types.get(str(game_id), ""))
        for game_id in validation["canonicalGameId"].tolist()
    ], dtype=object)
    if np.any(mapped_types == ""):
        raise HierarchicalRobustnessError("game-type authority is incomplete for validation rows")
    regular = mapped_types == "R"
    rows.append(_slice_metric(
        slice_group="seasonType", slice_name="REGULAR_SEASON", mask=regular,
        labels=labels, direct=direct8, selected=selected8,
    ))
    rows.append(_slice_metric(
        slice_group="seasonType", slice_name="POSTSEASON", mask=~regular,
        labels=labels, direct=direct8, selected=selected8,
    ))

    seen_batters = set(development["batterCanonicalPlayerId"].astype(str).tolist())
    seen_pitchers = set(development["pitcherCanonicalPlayerId"].astype(str).tolist())
    batter_seen = validation["batterCanonicalPlayerId"].astype(str).isin(seen_batters).to_numpy()
    pitcher_seen = validation["pitcherCanonicalPlayerId"].astype(str).isin(seen_pitchers).to_numpy()
    for group, seen in (("batterSeen", batter_seen), ("pitcherSeen", pitcher_seen)):
        rows.append(_slice_metric(
            slice_group=group, slice_name="SEEN_IN_MATCHED_2021_2023", mask=seen,
            labels=labels, direct=direct8, selected=selected8,
        ))
        rows.append(_slice_metric(
            slice_group=group, slice_name="UNSEEN_IN_MATCHED_2021_2023", mask=~seen,
            labels=labels, direct=direct8, selected=selected8,
        ))

    batter_high = validation["batter_last100_pa_count"].to_numpy(dtype=np.float64) >= 100.0
    pitcher_high = validation["pitcher_last250_bf_count"].to_numpy(dtype=np.float64) >= 250.0
    for group, high, threshold in (
        ("batterHistory", batter_high, "100_PRIOR_PA"),
        ("pitcherHistory", pitcher_high, "250_PRIOR_BF"),
    ):
        rows.append(_slice_metric(
            slice_group=group, slice_name=f"LOW_LT_{threshold}", mask=~high,
            labels=labels, direct=direct8, selected=selected8,
        ))
        rows.append(_slice_metric(
            slice_group=group, slice_name=f"HIGH_GE_{threshold}", mask=high,
            labels=labels, direct=direct8, selected=selected8,
        ))
    return rows


def _load_governed_base_2024() -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """Load the immutable accepted Base probabilities for all governed 2024 rows."""

    from server.sports_cockpit import gen3_authority as GA

    verified = GA.verify_canonical_model_run_chain(
        project_id=GOVERNED_BASE_PROJECT_ID,
        run_id=GOVERNED_BASE_RUN_ID,
        require_current_binding=True,
    )
    manifest = verified["manifest"]
    bundle_dir = Path(verified["bundleDir"]).resolve()
    if manifest.get("bundleManifestSha256") not in (None, GOVERNED_BASE_BUNDLE_SHA256):
        raise HierarchicalRobustnessError("governed Base bundle address differs")
    # The verifier returns the address separately on some historical revisions;
    # the directory name is the immutable content address in all revisions.
    if bundle_dir.name != GOVERNED_BASE_BUNDLE_SHA256:
        raise HierarchicalRobustnessError("governed Base bundle directory differs")
    required = {
        "datasetContentSha256": GOVERNED_BASE_DATASET_SHA256,
        "modelFamily": "governed_logistic",
        "validationSeason": 2024,
        "validationRows": GOVERNED_FULL_VALIDATION_ROWS,
        "predictionSha256": GOVERNED_BASE_PREDICTION_SHA256,
        "targetRowIdsSha256": GOVERNED_BASE_ROW_IDS_SHA256,
        "modelSha256": GOVERNED_BASE_MODEL_SHA256,
    }
    for key, value in required.items():
        if manifest.get(key) != value:
            raise HierarchicalRobustnessError(f"governed Base {key} differs")
    if manifest.get("classOrder") != list(PA_CLASS_ORDER) \
            or manifest.get("developmentSeasons") != [2021, 2022, 2023] \
            or set(manifest.get("seasonsInObject") or ()) != {2021, 2022, 2023, 2024}:
        raise HierarchicalRobustnessError("governed Base temporal/class contract differs")
    children = manifest.get("children") or {}
    child_expected = {
        "validation-probabilities.f64": GOVERNED_BASE_PREDICTION_SHA256,
        "validation-row-ids.json": GOVERNED_BASE_ROW_IDS_SHA256,
        "validation-target.json": GOVERNED_BASE_TARGET_SHA256,
    }
    for name, digest in child_expected.items():
        if (children.get(name) or {}).get("sha256") != digest:
            raise HierarchicalRobustnessError(f"governed Base {name} relationship differs")

    probability_bytes = GA._v2_child_bytes(
        bundle_dir, manifest, "validation-probabilities.f64"
    )
    probabilities = np.frombuffer(probability_bytes, dtype=np.float64).reshape(
        GOVERNED_FULL_VALIDATION_ROWS, len(PA_CLASS_ORDER)
    )
    probabilities = validate_probability_matrix(probabilities)
    row_evidence = json.loads(
        GA._v2_child_bytes(bundle_dir, manifest, "validation-row-ids.json").decode("utf-8")
    )
    target_evidence = json.loads(
        GA._v2_child_bytes(bundle_dir, manifest, "validation-target.json").decode("utf-8")
    )
    row_ids = row_evidence.get("rowIds")
    game_ids = row_evidence.get("gameIds")
    game_dates = row_evidence.get("gameDates")
    labels = target_evidence.get("labels")
    encoded = target_evidence.get("encoded")
    if not all(isinstance(values, list) and len(values) == GOVERNED_FULL_VALIDATION_ROWS
               for values in (row_ids, game_ids, game_dates, labels, encoded)):
        raise HierarchicalRobustnessError("governed Base validation evidence shape differs")
    if len(set(str(value) for value in row_ids)) != GOVERNED_FULL_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("governed Base validation row IDs are duplicated")
    if not np.array_equal(encode_labels(np.asarray(labels, dtype=object)), np.asarray(encoded, dtype=np.int64)):
        raise HierarchicalRobustnessError("governed Base validation target encoding differs")
    metrics = _required_multiclass_metrics(np.asarray(labels, dtype=object), probabilities)
    if not math.isclose(metrics["logLoss"], GOVERNED_BASE_LOG_LOSS, rel_tol=0.0, abs_tol=1e-12):
        raise HierarchicalRobustnessError("governed Base validation log loss differs")
    frame = pd.DataFrame({
        "plate_appearance_id": [str(value) for value in row_ids],
        "game_id": [str(value) for value in game_ids],
        "game_date": [str(value) for value in game_dates],
        "outcome": [str(value) for value in labels],
    })
    return frame, probabilities, {
        "projectId": GOVERNED_BASE_PROJECT_ID,
        "runId": GOVERNED_BASE_RUN_ID,
        "bundleManifestSha256": GOVERNED_BASE_BUNDLE_SHA256,
        "datasetContentSha256": GOVERNED_BASE_DATASET_SHA256,
        "predictionSha256": GOVERNED_BASE_PREDICTION_SHA256,
        "targetRowIdsSha256": GOVERNED_BASE_ROW_IDS_SHA256,
        "targetSha256": GOVERNED_BASE_TARGET_SHA256,
        "modelSha256": GOVERNED_BASE_MODEL_SHA256,
        "validationRows": GOVERNED_FULL_VALIDATION_ROWS,
        "metrics": metrics,
        "fitsPerformed": 0,
    }


def full_2024_comparison(
    *,
    governed_frame: pd.DataFrame,
    governed_base: Any,
    matched_row_ids: Sequence[str],
    selected_hierarchy: Any,
    expected_unmatched_row_ids: Sequence[str] | None = None,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    base = validate_probability_matrix(governed_base)
    selected = validate_probability_matrix(selected_hierarchy)
    if len(governed_frame) != GOVERNED_FULL_VALIDATION_ROWS \
            or len(base) != GOVERNED_FULL_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("full governed validation population differs")
    ids = governed_frame["plate_appearance_id"].astype(str)
    if ids.duplicated().any():
        raise HierarchicalRobustnessError("full governed row IDs are duplicated")
    lookup = {value: index for index, value in enumerate(ids.tolist())}
    matched = [str(value) for value in matched_row_ids]
    if len(matched) != EXPECTED_GOLD_VALIDATION_ROWS or len(set(matched)) != len(matched):
        raise HierarchicalRobustnessError("matched Gold validation IDs differ")
    try:
        positions = np.asarray([lookup[value] for value in matched], dtype=np.int64)
    except KeyError as exc:
        raise HierarchicalRobustnessError("a matched Gold ID is absent from governed 2024") from exc
    if np.unique(positions).size != EXPECTED_GOLD_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("matched-to-governed 2024 mapping is not one-to-one")
    if len(selected) != EXPECTED_GOLD_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("selected hierarchy matched row count differs")
    hybrid = np.array(base, dtype=np.float64, order="C", copy=True)
    hybrid[positions] = selected
    hybrid = validate_probability_matrix(hybrid)
    unmatched_mask = np.ones(GOVERNED_FULL_VALIDATION_ROWS, dtype=np.bool_)
    unmatched_mask[positions] = False
    if int(unmatched_mask.sum()) != 1_738:
        raise HierarchicalRobustnessError("full governed unmatched count differs")
    if expected_unmatched_row_ids is not None:
        expected_unmatched = {str(value) for value in expected_unmatched_row_ids}
        observed_unmatched = set(ids.loc[unmatched_mask].tolist())
        if len(expected_unmatched) != 1_738 or observed_unmatched != expected_unmatched:
            raise HierarchicalRobustnessError("governed complement differs from Gold exclusion ledger")
    if not np.array_equal(hybrid[unmatched_mask], base[unmatched_mask]):
        raise HierarchicalRobustnessError("unmatched rows did not retain governed Base probabilities")
    labels = governed_frame["outcome"].to_numpy(dtype=object, copy=False)
    comparison = {
        "rowCount": GOVERNED_FULL_VALIDATION_ROWS,
        "matchedHierarchyRows": EXPECTED_GOLD_VALIDATION_ROWS,
        "unmatchedGovernedBaseRows": 1_738,
        "unmatchedRowsOmitted": 0,
        "governedBaseLogistic": _required_multiclass_metrics(labels, base),
        "hierarchyMatchedPlusBaseUnmatched": _required_multiclass_metrics(labels, hybrid),
    }
    comparison["logLossDifferenceHybridMinusBase"] = float(
        comparison["hierarchyMatchedPlusBaseUnmatched"]["logLoss"]
        - comparison["governedBaseLogistic"]["logLoss"]
    )
    return comparison, hybrid, unmatched_mask


def _load_2024_exclusion_ids(
    *, gold_root: Path, verified_gold: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    logical_sha = str(verified_gold["logicalContentSha256"])
    manifest_path = Path(verified_gold["manifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger_authority = (manifest.get("connectionReport") or {}).get("exclusionLedger") or {}
    path = Path(gold_root).resolve() / "evidence" / logical_sha / "bridge-exclusions.parquet"
    data = path.read_bytes()
    if ledger_authority.get("rows") != 13_471 \
            or ledger_authority.get("sha256") != hashlib.sha256(data).hexdigest():
        raise HierarchicalRobustnessError("Gold exclusion ledger bytes or population differ")
    table = pq.read_table(
        io.BytesIO(data), columns=["plate_appearance_id", "season", "reasonCode", "split"]
    ).to_pandas()
    seasons = pd.to_numeric(table["season"], errors="raise").astype(np.int64)
    validation = table.loc[seasons == 2024].copy()
    ids = validation["plate_appearance_id"].astype(str).tolist()
    if len(ids) != 1_738 or len(set(ids)) != 1_738 \
            or set(validation["reasonCode"].astype(str)) != {"KEY_GROUP_COUNT_MISMATCH"} \
            or set(validation["split"].astype(str)) != {"VALIDATION"}:
        raise HierarchicalRobustnessError("Gold 2024 exclusion ledger reconciliation differs")
    return ids, {
        "relativePath": f"evidence/{logical_sha}/bridge-exclusions.parquet",
        "sha256": hashlib.sha256(data).hexdigest(),
        "totalRows": int(len(table)),
        "validationRows": len(ids),
        "validationReasonCounts": {"KEY_GROUP_COUNT_MISMATCH": len(ids)},
    }


def _load_game_type_authority(
    *, gold_root: Path, gold_manifest: Mapping[str, Any], validation_game_ids: Sequence[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Load evaluation-only game type from Gold's already-bound Silver input."""

    source = (((gold_manifest.get("sourceInputs") or {}).get("currentSilver") or {}).get(
        "fact_statcast_plate_appearance"
    ))
    if not isinstance(source, dict) or source.get("tableName") != "fact_statcast_plate_appearance":
        raise HierarchicalRobustnessError("Gold-bound Statcast PA authority is missing")
    silver_root = Path(gold_root).resolve().parent / "mlb-silver-v1"
    manifest_sha = str(source.get("manifestSha256"))
    object_root = silver_root / "partitioned" / manifest_sha
    manifest_path = object_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha:
        raise HierarchicalRobustnessError("Gold-bound Statcast PA manifest bytes differ")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("tableName") != "fact_statcast_plate_appearance" \
            or manifest.get("manifestSha256") not in (None, manifest_sha) \
            or source.get("datasetVersionId") != f"silver-table:fact_statcast_plate_appearance:sha256:{manifest_sha}":
        raise HierarchicalRobustnessError("Gold-bound Statcast PA manifest identity differs")
    frames: list[pd.DataFrame] = []
    opened_children = 0
    for child in manifest.get("children") or []:
        if 2024 not in [int(value) for value in child.get("seasons") or []]:
            continue
        child_path = object_root / "children" / f"{child['childSha256']}.parquet"
        data = child_path.read_bytes()
        if len(data) != int(child["bytes"]) or hashlib.sha256(data).hexdigest() != child["childSha256"]:
            raise HierarchicalRobustnessError("Gold-bound Statcast PA child bytes differ")
        part = pq.read_table(
            io.BytesIO(data),
            columns=["canonicalPaId", "canonicalGameId", "gameDate", "gameType", "season"],
        ).to_pandas()
        numeric_season = pd.to_numeric(part["season"], errors="raise").astype(np.int64)
        frames.append(part.loc[numeric_season == 2024].copy())
        opened_children += 1
    if not frames:
        raise HierarchicalRobustnessError("Gold-bound Statcast PA has no 2024 partitions")
    rows = pd.concat(frames, ignore_index=True)
    if rows["canonicalPaId"].duplicated().any():
        raise HierarchicalRobustnessError("2024 Statcast PA IDs are duplicated")
    by_game = rows.groupby("canonicalGameId", sort=False)["gameType"].agg(
        lambda values: tuple(sorted(set(str(value) for value in values)))
    )
    if any(len(values) != 1 for values in by_game.tolist()):
        raise HierarchicalRobustnessError("2024 game type is not unique per canonical game")
    mapping = {str(key): values[0] for key, values in by_game.items()}
    required = {str(value) for value in validation_game_ids}
    missing = sorted(required - set(mapping))
    if missing:
        raise HierarchicalRobustnessError(f"Statcast PA authority lacks {len(missing)} validation games")
    return {key: mapping[key] for key in required}, {
        "purpose": "EVALUATION_SLICE_ONLY_NOT_A_MODEL_FEATURE",
        "silverRoot": str(silver_root),
        "tableName": "fact_statcast_plate_appearance",
        "manifestSha256": manifest_sha,
        "registrationSha256": source.get("registrationSha256"),
        "sourceValueDigestSha256": source.get("valueDigestSha256"),
        "sourceRowCount": source.get("rowCount"),
        "opened2024Children": opened_children,
        "rowsReadFor2024": int(len(rows)),
        "seasonsOpened": [2024],
        "modelFeatureUse": False,
    }


def _prepare_study_frame(
    verified_gold: Mapping[str, Any],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    columns = [
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id",
        "game_date", "season", "outcome", "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId", "datasetRole", *GOLD_FEATURES,
    ]
    frame = pq.read_table(Path(verified_gold["path"]), columns=columns).to_pandas()
    if len(frame) != EXPECTED_GOLD_TOTAL_ROWS:
        raise HierarchicalRobustnessError("Gold study row count differs")
    for identity in (
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id",
        "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
    ):
        if frame[identity].isna().any() or (frame[identity].astype(str).str.strip() == "").any():
            raise HierarchicalRobustnessError(f"Gold {identity} is missing")
    if frame["canonicalPaId"].duplicated().any() or frame["plate_appearance_id"].duplicated().any():
        raise HierarchicalRobustnessError("Gold study PA identities are duplicated")
    seasons = frame["season"].to_numpy(dtype=np.int64, copy=False)
    observed = {
        int(key): int(value)
        for key, value in frame["season"].value_counts().sort_index().items()
    }
    if observed != dict(EXPECTED_GOLD_SEASON_ROWS) or set(observed) != {2021, 2022, 2023, 2024}:
        raise HierarchicalRobustnessError(f"Gold study season rows differ: {observed}")
    development = np.isin(seasons, DEVELOPMENT_SEASONS)
    validation = seasons == VALIDATION_SEASON
    if int(development.sum()) != EXPECTED_GOLD_DEVELOPMENT_ROWS \
            or int(validation.sum()) != EXPECTED_GOLD_VALIDATION_ROWS:
        raise HierarchicalRobustnessError("Gold study split rows differ")
    roles = frame["datasetRole"].astype(str).to_numpy(dtype=object)
    expected_roles = np.where(validation, "VALIDATION", "DEVELOPMENT")
    if not np.array_equal(roles, expected_roles):
        raise HierarchicalRobustnessError("Gold study dataset roles differ")
    labels = BH.binary_labels(frame["outcome"].to_numpy(copy=False))
    if set(labels[development].tolist()) != {0, 1} or set(labels[validation].tolist()) != {0, 1}:
        raise HierarchicalRobustnessError("Gold binary classes are absent from a split")
    dates = pd.to_datetime(frame["game_date"], format="%Y-%m-%d", errors="raise")
    if not np.array_equal(dates.dt.year.to_numpy(dtype=np.int64), seasons):
        raise HierarchicalRobustnessError("Gold game_date and season differ")
    return frame, development, validation, labels


def _implementation_identity() -> dict[str, Any]:
    path = Path(__file__).resolve()
    data = path.read_bytes()
    return {
        "relativePath": "server/sports_gold/hierarchical_robustness.py",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": __import__("sklearn").__version__,
    }


def _study_request(
    *, verified_gold: Mapping[str, Any], implementation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "selectionContract": SELECTION_CONTRACT,
        "goldDatasetVersionId": verified_gold["datasetVersionId"],
        "goldLogicalContentSha256": verified_gold["logicalContentSha256"],
        "sourceMulticlassExperimentSha256": BH.TRUSTED_MULTICLASS_EXPERIMENT_SHA256,
        "sourceInitialBinaryExperimentSha256": TRUSTED_INITIAL_BINARY_EXPERIMENT_SHA256,
        "governedBaseProjectId": GOVERNED_BASE_PROJECT_ID,
        "governedBaseRunId": GOVERNED_BASE_RUN_ID,
        "governedBaseBundleSha256": GOVERNED_BASE_BUNDLE_SHA256,
        "targetContract": BH.target_contract(),
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "developmentRows": EXPECTED_GOLD_DEVELOPMENT_ROWS,
        "oofFolds": [
            {
                "foldId": item.fold_id,
                "trainingSeasons": list(item.training_seasons),
                "validationSeason": item.validation_season,
            }
            for item in FOLD_DEFINITIONS
        ],
        "oofSelectionSeasons": list(OOF_VALIDATION_SEASONS),
        "oofRows": OOF_EXPECTED_ROWS,
        "validationSeason": VALIDATION_SEASON,
        "validationRows": EXPECTED_GOLD_VALIDATION_ROWS,
        "governedFullValidationRows": GOVERNED_FULL_VALIDATION_ROWS,
        "candidateSuite": [
            {
                "modelId": item.model_id, "family": item.family, "kind": item.kind,
                "configuration": dict(item.config),
            }
            for item in candidate_specs()
        ],
        "calibrationMethods": [
            {"method": "raw", "configuration": {}},
            {"method": "platt", "configuration": dict(PLATT_CONFIG)},
            {"method": "isotonic", "configuration": dict(ISOTONIC_CONFIG)},
        ],
        "selectionOrder": [
            "OOF_BINARY_LOG_LOSS_ASC", "OOF_BRIER_ASC", "OOF_ECE_ASC",
            "CALIBRATION_INTERCEPT_SLOPE_DISTANCE_ASC", "FAMILY_ASC", "METHOD_ASC",
        ],
        "bootstrap": {
            "unit": "game_id", "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED, "paired": True,
        },
        "slicePolicy": {
            "month": "2024_GAME_DATE_MONTH",
            "seasonType": "GOLD_BOUND_SILVER_STATCAST_GAME_TYPE_R_VS_NON_R",
            "seenBatter": "PLAYER_ID_PRESENT_IN_MATCHED_2021_2023",
            "seenPitcher": "PLAYER_ID_PRESENT_IN_MATCHED_2021_2023",
            "batterHistory": "LOW_LT_100_VS_HIGH_GE_100_LAST100_PA_COUNT",
            "pitcherHistory": "LOW_LT_250_VS_HIGH_GE_250_LAST250_BF_COUNT",
        },
        "featureOrder": list(GOLD_FEATURES),
        "classOrder": list(PA_CLASS_ORDER),
        "implementation": dict(implementation),
        "promotionRequested": False,
        "dataRebuildRequested": False,
        "prohibitedSeasons": [2025, 2026],
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha_file(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(_json_safe(value)))


def _artifact_entry(path: Path, *, root: Path) -> dict[str, Any]:
    size, digest = _sha_file(path)
    return {
        "relativePath": path.relative_to(root).as_posix(),
        "bytes": size,
        "sha256": digest,
    }


def _recommendation(
    *, matched: Mapping[str, Any], bootstrap: Mapping[str, Any],
) -> tuple[str, str]:
    direct_multi = float(matched["direct_gold_logistic"]["multiclass"]["logLoss"])
    selected_multi = float(
        matched["development_selected_calibrated_hierarchy"]["multiclass"]["logLoss"]
    )
    direct_binary = float(matched["direct_gold_logistic"]["binary"]["binaryLogLoss"])
    selected_binary = float(
        matched["development_selected_calibrated_hierarchy"]["binary"]["binaryLogLoss"]
    )
    interval_upper = float(bootstrap["confidenceInterval95"]["upper"])
    bootstrap_supports = (
        float(bootstrap["meanDifference"]) < 0.0
        and interval_upper < 0.0
        and float(bootstrap["percentReplicatesFavorHierarchy"]) > 50.0
    )
    if selected_multi < direct_multi and bootstrap_supports:
        return (
            "C. ADOPT_HIERARCHICAL_RESEARCH_CHALLENGER",
            "The development-selected hierarchy improves 2024 eight-class log loss and the paired whole-game 95% interval favors it.",
        )
    if selected_binary < direct_binary:
        return (
            "B. USE_BINARY_AS_AUXILIARY_CALIBRATION_LAYER",
            "The development-selected OUT/NOT_OUT layer improves binary log loss, but the reconstructed eight-class gain is not supported across the paired whole-game interval.",
        )
    return (
        "A. KEEP_DIRECT_8_CLASS",
        "The development-selected OUT/NOT_OUT layer does not improve the direct Gold Logistic binary projection on 2024.",
    )


def _markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 7B3 hierarchical PA robustness study",
        "",
        f"Status: **{result['status']}**  ",
        f"Gold object: `{result['goldDatasetVersionId']}`  ",
        f"Development: {result['developmentRows']:,} matched rows (2021–2023); validation: {result['validationRows']:,} matched rows (2024).  ",
        "No Bronze, Silver, or Gold rebuild was performed. No 2025 data was opened. No promotion was requested or performed.",
        "",
        "## Development OOF leaderboard",
        "",
        "| Rank | Candidate | Family | OOF log loss | Brier | ECE |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for row in sorted(
        result["developmentOofLeaderboard"], key=lambda item: item.get("rank") or 999
    ):
        metrics = row.get("metrics") or {}
        lines.append(
            f"| {row.get('rank') or '—'} | {row['label']} | {row['family']} | "
            f"{metrics.get('binaryLogLoss', '—')} | {metrics.get('brierScore', '—')} | {metrics.get('ece', '—')} |"
        )
    lines.extend([
        "",
        "## Calibration comparison",
        "",
        "| Rank | Family winner | Calibration | OOF log loss | Brier | Intercept | Slope | ECE |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in sorted(
        result["calibrationComparison"], key=lambda item: item.get("rank") or 999
    ):
        metrics = row.get("metrics") or {}
        lines.append(
            f"| {row.get('rank') or '—'} | {row['sourceModelId']} | {row['calibrationMethod']} | "
            f"{metrics.get('binaryLogLoss', '—')} | {metrics.get('brierScore', '—')} | "
            f"{metrics.get('calibrationIntercept', '—')} | {metrics.get('calibrationSlope', '—')} | "
            f"{metrics.get('ece', '—')} |"
        )
    selected = result["selectedModel"]
    lines.extend([
        "",
        "## Frozen selection",
        "",
        f"- Candidate: `{selected['sourceModelId']}`",
        f"- Family: `{selected['family']}`",
        f"- Calibration: `{selected['calibrationMethod']}`",
        "- Selection evidence: combined chronological 2022–2023 OOF predictions only.",
        "- Frozen before any 2024 selected-model scoring: **yes**.",
        "",
        "## Matched 2024 comparison",
        "",
        "| Model | 8-class log loss | Summed Brier | ECE | Accuracy | Macro-F1 | Binary log loss | Binary Brier | Cal intercept | Cal slope | ROC-AUC | PR-AUC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for key, label in (
        ("direct_gold_logistic", "Direct Gold Logistic"),
        ("initial_raw_extra_trees_hierarchy", "Initial raw Extra Trees hierarchy"),
        ("development_selected_calibrated_hierarchy", "Development-selected calibrated hierarchy"),
    ):
        row = result["matched2024Comparison"][key]
        multi, binary = row["multiclass"], row["binary"]
        lines.append(
            f"| {label} | {multi['logLoss']} | {multi['brierScore']} | {multi['ece']} | "
            f"{multi['accuracy']} | {multi['macroF1']} | {binary['binaryLogLoss']} | "
            f"{binary['brierScore']} | {binary['calibrationIntercept']} | "
            f"{binary['calibrationSlope']} | {binary['rocAuc']} | {binary['prAuc']} |"
        )
    full = result["full2024Comparison"]
    lines.extend([
        "",
        "## Full governed 2024 population",
        "",
        f"All {full['rowCount']:,} rows are included: {full['matchedHierarchyRows']:,} hierarchy rows plus {full['unmatchedGovernedBaseRows']:,} governed Base rows; omitted = {full['unmatchedRowsOmitted']}.",
        "",
        "| Model | Log loss | Summed Brier | ECE | Accuracy | Macro-F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for key, label in (
        ("governedBaseLogistic", "Governed Base Logistic"),
        ("hierarchyMatchedPlusBaseUnmatched", "Hierarchy matched + Base unmatched"),
    ):
        row = full[key]
        lines.append(
            f"| {label} | {row['logLoss']} | {row['brierScore']} | {row['ece']} | "
            f"{row['accuracy']} | {row['macroF1']} |"
        )
    bootstrap = result["gameClusterBootstrap"]
    lines.extend([
        "",
        "## Paired whole-game bootstrap",
        "",
        f"- Replicates: {bootstrap['resampleCount']:,}; clusters: {bootstrap['clusterCount']:,}; individual-PA sampling: **no**.",
        f"- Mean hierarchy-minus-direct log-loss difference: `{bootstrap['meanDifference']}`",
        f"- Median difference: `{bootstrap['medianDifference']}`",
        f"- 95% interval: `[{bootstrap['confidenceInterval95']['lower']}, {bootstrap['confidenceInterval95']['upper']}]`",
        f"- Replicates favoring hierarchy: `{bootstrap['percentReplicatesFavorHierarchy']}%`",
        "",
        "## Stability slices",
        "",
        "| Group | Slice | Rows | Direct LL | Hierarchical LL | Difference |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for row in result["stabilitySlices"]:
        lines.append(
            f"| {row['sliceGroup']} | {row['slice']} | {row['rows']} | "
            f"{row['directLogLoss'] if row['directLogLoss'] is not None else '—'} | "
            f"{row['hierarchicalLogLoss'] if row['hierarchicalLogLoss'] is not None else '—'} | "
            f"{row['differenceHierarchyMinusDirect'] if row['differenceHierarchyMinusDirect'] is not None else '—'} |"
        )
    lines.extend([
        "",
        "## Research decision",
        "",
        f"**{result['recommendation']['decision']}**",
        "",
        result["recommendation"]["reason"],
        "",
        "This is a research-only decision. No champion was promoted.",
        "",
    ])
    return "\n".join(lines)


def _load_existing_study(
    final: Path, *, request: Mapping[str, Any], study_sha: str,
) -> dict[str, Any]:
    manifest_path = final / "manifest.json"
    results_path = final / "results.json"
    if not manifest_path.is_file() or not results_path.is_file():
        raise HierarchicalRobustnessError("existing robustness study is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("studySha256") != study_sha or manifest.get("request") != request \
            or manifest.get("status") != "RESEARCH_ONLY" \
            or manifest.get("promotionEligible") is not False \
            or manifest.get("championEligible") is not False:
        raise HierarchicalRobustnessError("existing robustness study authority differs")
    inventory = manifest.get("artifacts") or {}
    for key, entry in inventory.items():
        if not isinstance(entry, dict) or set(entry) != {"relativePath", "bytes", "sha256"}:
            raise HierarchicalRobustnessError(f"existing artifact inventory differs: {key}")
        path = (final / entry["relativePath"]).resolve()
        if final not in path.parents or not path.is_file():
            raise HierarchicalRobustnessError(f"existing artifact path is unsafe or missing: {key}")
        size, digest = _sha_file(path)
        if size != entry["bytes"] or digest != entry["sha256"]:
            raise HierarchicalRobustnessError(f"existing artifact bytes differ: {key}")
    result_entry = inventory.get("results")
    if not result_entry or result_entry["relativePath"] != "results.json":
        raise HierarchicalRobustnessError("existing results inventory is missing")
    result = json.loads(results_path.read_text(encoding="utf-8"))
    if result.get("studySha256") != study_sha or result.get("requestSha256") != study_sha:
        raise HierarchicalRobustnessError("existing robustness result relationships differ")
    result["artifactRoot"] = str(final)
    return result


def run_hierarchical_robustness_study(
    *,
    gold_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the fixed Phase 7B3 overnight robustness study and persist its evidence."""

    emit = progress or (lambda _message: None)
    root = Path(gold_root).resolve()
    started = time.perf_counter()
    emit("verifying frozen Gold and accepted prediction artifacts")
    verified_gold = verify_gold(root)
    if verified_gold.get("datasetVersionId") != (
        "gold-table:gold_mlb_pa_v1:sha256:"
        "56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0"
    ) or verified_gold.get("logicalContentSha256") != (
        "56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0"
    ) or verified_gold.get("rowCount") != EXPECTED_GOLD_TOTAL_ROWS \
            or set(verified_gold.get("seasons") or ()) != {2021, 2022, 2023, 2024}:
        raise HierarchicalRobustnessError("frozen Gold V1 authority differs")
    implementation = _implementation_identity()
    request = _study_request(verified_gold=verified_gold, implementation=implementation)
    study_sha = sha256_bytes(canonical_json_bytes(request))
    final = root / "hierarchical-studies" / "sha256" / study_sha
    if final.exists():
        emit("verified existing request-addressed robustness study")
        return _load_existing_study(final, request=request, study_sha=study_sha)

    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        multiclass_artifacts, source_multiclass = BH._verified_multiclass_artifacts(
            gold_root=root, verified_gold=verified_gold
        )
        initial_artifact, source_initial = _load_initial_extra_trees(root)
        frame, development_mask, validation_mask, labels = _prepare_study_frame(verified_gold)
        post_read_gold = verify_gold(root, object_sha=str(verified_gold["logicalContentSha256"]))
        if post_read_gold.get("logicalContentSha256") != verified_gold.get("logicalContentSha256") \
                or post_read_gold.get("rowCount") != verified_gold.get("rowCount"):
            raise HierarchicalRobustnessError("Gold identity changed during study materialization")

        emit("generating chronological 2022/2023 OOF predictions")
        oof_leaderboard, oof_predictions, oof_positions, folds = generate_chronological_oof(
            frame, labels, progress=emit
        )
        successful_oof = [row for row in oof_leaderboard if row["status"] == "SUCCESS"]
        ranked_oof = sorted(
            successful_oof,
            key=lambda row: (
                float(row["metrics"]["binaryLogLoss"]),
                float(row["metrics"]["brierScore"]),
                float(row["metrics"]["ece"]),
                str(row["modelId"]),
            ),
        )
        for rank, row in enumerate(ranked_oof, start=1):
            row["rank"] = rank
        for row in oof_leaderboard:
            row.setdefault("rank", None)
        oof_labels = labels[oof_positions]

        emit("fitting raw/Platt/isotonic calibration on development OOF predictions")
        calibration, calibrators = calibrate_family_winners(
            leaderboard=oof_leaderboard,
            predictions=oof_predictions,
            oof_labels=oof_labels,
        )
        ranked_calibration = sorted(
            [row for row in calibration if row["status"] == "SUCCESS"],
            key=_selection_key,
        )
        for rank, row in enumerate(ranked_calibration, start=1):
            row["rank"] = rank
        for row in calibration:
            row.setdefault("rank", None)
        selected = select_calibrated_candidate(calibration)
        selected_model_id = str(selected["sourceModelId"])
        selected_family = str(selected["family"])
        selected_method = str(selected["calibrationMethod"])
        selected_spec = next(
            item for item in candidate_specs() if item.model_id == selected_model_id
        )
        selected_calibrator = calibrators[(selected_family, selected_method)]
        selection_record = {
            "schemaVersion": "MLB_GOLD_HIERARCHICAL_SELECTION_RECORD_V1",
            "selectionContract": SELECTION_CONTRACT,
            "studySha256": study_sha,
            "sourceModelId": selected_model_id,
            "family": selected_family,
            "calibrationMethod": selected_method,
            "underlyingConfiguration": dict(selected_spec.config),
            "calibratorConfiguration": dict(selected_calibrator.configuration),
            "selectionMetrics": dict(selected["metrics"]),
            "selectionOrder": list(request["selectionOrder"]),
            "selectionSeasons": list(OOF_VALIDATION_SEASONS),
            "selectionRows": int(oof_labels.size),
            "folds": folds,
            "uses2024ForModelSelection": False,
            "uses2024ForCalibrationFit": False,
            "frozenBefore2024Scoring": True,
        }
        _write_json(staging / "selected-model-record.json", selection_record)
        selection_sha = hashlib.sha256(
            (staging / "selected-model-record.json").read_bytes()
        ).hexdigest()
        emit(
            f"selection frozen: {selected_model_id} + {selected_method} "
            f"(record {selection_sha[:12]})"
        )

        # No selected-model 2024 score is computed before the freeze above.
        validation = frame.loc[validation_mask].reset_index(drop=True)
        development = frame.loc[development_mask].reset_index(drop=True)
        y_validation = validation["outcome"].to_numpy(dtype=object, copy=False)
        direct_gold8 = multiclass_artifacts["gold_logistic"].predict_proba(validation)
        direct_metrics = _required_multiclass_metrics(y_validation, direct_gold8)
        if not math.isclose(
            direct_metrics["logLoss"], BH.DIRECT_GOLD_LOG_LOSS,
            rel_tol=0.0, abs_tol=1e-12,
        ):
            raise HierarchicalRobustnessError("direct Gold Logistic 2024 log loss differs")

        initial_out = initial_artifact.predict_out_probability(validation)
        initial8, initial_proof = BH.reconstruct_eight_class_probabilities(
            direct_gold8, initial_out
        )
        initial_metrics = _required_multiclass_metrics(y_validation, initial8)
        if not math.isclose(
            initial_metrics["logLoss"], INITIAL_HIERARCHY_LOG_LOSS,
            rel_tol=0.0, abs_tol=1e-12,
        ):
            raise HierarchicalRobustnessError("initial raw Extra Trees hierarchy differs")

        emit("refitting the frozen selected underlying model on all matched 2021--2023 rows")
        selected_artifact, selected_raw_out, selected_refit = _refit_selected_binary(
            spec=selected_spec,
            frame=frame,
            development_mask=development_mask,
            validation_mask=validation_mask,
            labels=labels,
            direct_gold_artifact=multiclass_artifacts["gold_logistic"],
        )
        selected_out = selected_calibrator.transform(selected_raw_out)
        selected8, selected_proof = BH.reconstruct_eight_class_probabilities(
            direct_gold8, selected_out
        )
        matched = matched_2024_comparison(
            labels=y_validation, direct=direct_gold8, initial=initial8, selected=selected8
        )

        emit("running 2,000 paired whole-game bootstrap replicates")
        bootstrap, bootstrap_replicates = compact_game_bootstrap(
            labels=y_validation,
            selected=selected8,
            direct=direct_gold8,
            game_ids=validation["game_id"].to_numpy(dtype=object, copy=False),
        )
        gold_manifest = json.loads(Path(verified_gold["manifestPath"]).read_text(encoding="utf-8"))
        game_types, game_type_authority = _load_game_type_authority(
            gold_root=root,
            gold_manifest=gold_manifest,
            validation_game_ids=validation["canonicalGameId"].astype(str).tolist(),
        )
        slices = stability_slices(
            validation=validation,
            development=development,
            direct=direct_gold8,
            selected=selected8,
            game_types=game_types,
        )

        emit("assembling all 182,449 governed 2024 rows from accepted Base evidence")
        governed_frame, governed_base, governed_authority = _load_governed_base_2024()
        excluded_ids, exclusion_authority = _load_2024_exclusion_ids(
            gold_root=root, verified_gold=verified_gold
        )
        full, full_hybrid, unmatched_mask = full_2024_comparison(
            governed_frame=governed_frame,
            governed_base=governed_base,
            matched_row_ids=validation["plate_appearance_id"].astype(str).tolist(),
            selected_hierarchy=selected8,
            expected_unmatched_row_ids=excluded_ids,
        )
        decision, reason = _recommendation(matched=matched, bootstrap=bootstrap)

        selection_record["recordSha256"] = selection_sha
        result: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "RESEARCH_ONLY_COMPLETE",
            "studySha256": study_sha,
            "requestSha256": study_sha,
            "goldDatasetVersionId": verified_gold["datasetVersionId"],
            "goldLogicalContentSha256": verified_gold["logicalContentSha256"],
            "sourceMulticlassExperiment": source_multiclass,
            "sourceInitialHierarchy": source_initial,
            "governedBaseAuthority": governed_authority,
            "goldExclusionAuthority": exclusion_authority,
            "gameTypeAuthority": game_type_authority,
            "targetContract": BH.target_contract(),
            "classOrder": list(PA_CLASS_ORDER),
            "developmentSeasons": list(DEVELOPMENT_SEASONS),
            "developmentRows": int(development_mask.sum()),
            "oofSelectionSeasons": list(OOF_VALIDATION_SEASONS),
            "oofRows": int(oof_labels.size),
            "validationSeason": VALIDATION_SEASON,
            "validationRows": int(validation_mask.sum()),
            "developmentOofLeaderboard": oof_leaderboard,
            "calibrationComparison": calibration,
            "selectedModel": selection_record,
            "selectedRefit": selected_refit,
            "matched2024Comparison": matched,
            "reconstructionVerification": {
                "initialRawExtraTrees": initial_proof,
                "developmentSelected": selected_proof,
            },
            "full2024Comparison": full,
            "gameClusterBootstrap": bootstrap,
            "stabilitySlices": slices,
            "temporalVerification": {
                "goldSeasons": verified_gold["seasons"],
                "developmentSeasons": list(DEVELOPMENT_SEASONS),
                "oofValidationSeasons": list(OOF_VALIDATION_SEASONS),
                "finalValidationSeason": VALIDATION_SEASON,
                "prohibitedSeasonsOpened": [],
                "selectionUsed2024": False,
                "calibrationUsed2024": False,
                "newFeaturesAdded": False,
                "dataRebuilt": False,
            },
            "recommendation": {"decision": decision, "reason": reason},
            "promotionRequested": False,
            "promotionPerformed": False,
            "elapsedSeconds": float(time.perf_counter() - started),
        }

        # Large row-level predictions and fitted artifacts stay outside Git.
        (staging / "models").mkdir()
        if selected_artifact is not None:
            joblib.dump(selected_artifact, staging / "models" / "selected-underlying.joblib", compress=3)
        joblib.dump(selected_calibrator, staging / "models" / "selected-calibrator.joblib", compress=3)
        (staging / "predictions").mkdir()
        np.savez_compressed(
            staging / "predictions" / "development-oof.npz",
            plate_appearance_id=frame.iloc[oof_positions]["plate_appearance_id"].astype(str).to_numpy(),
            season=frame.iloc[oof_positions]["season"].to_numpy(dtype=np.int16),
            labels=oof_labels.astype(np.int8),
            **{key: value for key, value in sorted(oof_predictions.items())},
        )
        np.savez_compressed(
            staging / "predictions" / "matched-2024.npz",
            plate_appearance_id=validation["plate_appearance_id"].astype(str).to_numpy(),
            direct_gold=direct_gold8,
            initial_raw_extra_trees=initial8,
            selected_hierarchy=selected8,
            selected_out_probability=selected_out,
        )
        np.savez_compressed(
            staging / "predictions" / "full-2024.npz",
            plate_appearance_id=governed_frame["plate_appearance_id"].astype(str).to_numpy(),
            governed_base=governed_base,
            hierarchy_matched_base_unmatched=full_hybrid,
            unmatched_mask=unmatched_mask,
        )
        np.save(
            staging / "predictions" / "game-bootstrap-logloss-differences.f64.npy",
            np.asarray(bootstrap_replicates, dtype=np.float64),
            allow_pickle=False,
        )

        _write_json(staging / "development-oof-leaderboard.json", oof_leaderboard)
        _write_json(staging / "calibration-comparison.json", calibration)
        _write_json(staging / "matched-2024-comparison.json", matched)
        _write_json(staging / "full-2024-comparison.json", full)
        _write_json(staging / "game-bootstrap-report.json", bootstrap)
        _write_json(staging / "stability-slice-report.json", slices)

        large_artifacts: dict[str, Any] = {}
        for path in sorted(
            [item for item in staging.rglob("*") if item.is_file()],
            key=lambda item: item.relative_to(staging).as_posix(),
        ):
            large_artifacts[path.relative_to(staging).as_posix()] = _artifact_entry(
                path, root=staging
            )
        result["persistedEvidence"] = large_artifacts
        result = _json_safe(result)
        _write_json(staging / "results.json", result)
        report_path = staging / "study-report.md"
        report_path.write_text(_markdown(result), encoding="utf-8", newline="\n")

        inventory: dict[str, Any] = {}
        for path in sorted(
            [item for item in staging.rglob("*") if item.is_file()],
            key=lambda item: item.relative_to(staging).as_posix(),
        ):
            key = path.relative_to(staging).as_posix()
            inventory["results" if key == "results.json" else key] = _artifact_entry(
                path, root=staging
            )
        _write_json(staging / "manifest.json", {
            "schemaVersion": "MLB_GOLD_HIERARCHICAL_ROBUSTNESS_MANIFEST_V1",
            "studySha256": study_sha,
            "request": request,
            "artifacts": inventory,
            "status": "RESEARCH_ONLY",
            "promotionEligible": False,
            "championEligible": False,
        })
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            persisted = _load_existing_study(final, request=request, study_sha=study_sha)
        else:
            final.mkdir(parents=False, exist_ok=False)
            for path in sorted(
                [item for item in staging.rglob("*") if item.is_file()
                 and item.name != "manifest.json"],
                key=lambda item: item.relative_to(staging).as_posix(),
            ):
                destination = final / path.relative_to(staging)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            shutil.copy2(staging / "manifest.json", final / "manifest.json")
            persisted = _load_existing_study(final, request=request, study_sha=study_sha)
        shutil.rmtree(staging)
        persisted["artifactRoot"] = str(final)
        emit(f"completed research-only robustness study: {decision}")
        return persisted
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "CALIBRATION_CONTRACT",
    "CandidateSpec",
    "FOLD_DEFINITIONS",
    "FittedProbabilityCalibrator",
    "HierarchicalRobustnessError",
    "OOF_VALIDATION_SEASONS",
    "candidate_specs",
    "calibrate_family_winners",
    "chronological_fold_masks",
    "compact_game_bootstrap",
    "fit_probability_calibrator",
    "full_2024_comparison",
    "generate_chronological_oof",
    "matched_2024_comparison",
    "run_hierarchical_robustness_study",
    "select_calibrated_candidate",
    "stability_slices",
]
