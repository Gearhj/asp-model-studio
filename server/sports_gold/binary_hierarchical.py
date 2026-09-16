"""Fixed BATTER_RETIRED and hierarchical probability experiment for Gold V1.

This module is intentionally downstream of the frozen Phase 7B2 Gold object and
its persisted eight-class Base/Gold Logistic artifacts.  It cannot build Bronze,
Silver, or Gold, name 2025, register a model, or promote a candidate.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import shutil
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
import sklearn
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_modeling.feature_contract import FEATURE_NAMES
from ..sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    require_frozen_class_order,
    validate_probability_matrix,
)
from ..sports_modeling.training import FoldPreprocessor
from .contracts import (
    BATTER_HISTORY_FEATURES,
    DEVELOPMENT_SEASONS,
    EXPECTED_GOLD_DEVELOPMENT_ROWS,
    EXPECTED_GOLD_SEASON_ROWS,
    EXPECTED_GOLD_TOTAL_ROWS,
    EXPECTED_GOLD_VALIDATION_ROWS,
    GOLD_FEATURES,
    MATCHUP_FEATURES,
    PITCHER_HISTORY_FEATURES,
    VALIDATION_SEASON,
    gold_contract_bundle,
)
from .models import (
    EXTRA_TREES_CONFIG,
    HGB_CONFIG,
    LOGISTIC_CONFIG,
    RANDOM_SEED,
    FittedFixedModel,
)
from .publication import verify_gold


SCHEMA_VERSION = "MLB_GOLD_BATTER_RETIRED_EXPERIMENT_V1"
TARGET_CONTRACT = "MLB_PA_BATTER_RETIRED_TARGET_V1"
RECONSTRUCTION_CONTRACT = "MLB_PA_HIERARCHICAL_GROUP_MASS_RECONSTRUCTION_V1"
DIRECT_GOLD_LOG_LOSS = 1.4778808498644482
CALIBRATION_BINS = 10
TRUSTED_MULTICLASS_EXPERIMENT_SHA256 = (
    "de7966fba2e6dfd1cde466eadb2b8cd6d737695fd75d89d5fce0938e8060538f"
)
TRUSTED_MULTICLASS_LEADERBOARD_SHA256 = (
    "16155af2889104535ed975d196525e2103795510ca106ab432a9e75aad665ea3"
)
TRUSTED_MULTICLASS_MODELS: Mapping[str, Mapping[str, Any]] = {
    "base_logistic": {
        "bytes": 3_663,
        "sha256": "2cf9faaabaf54b329e2da253457fa4a3046a1f4a7fcb8ad72c7c4a43474d2a71",
    },
    "gold_logistic": {
        "bytes": 5_965,
        "sha256": "1ea82a4a724ccd00913d69fa6e94c8a990c258793465b8da7b064350a44a9f92",
    },
}

OUT_CLASSES: tuple[str, ...] = ("STRIKEOUT", "BIP_OUT")
NOT_OUT_CLASSES: tuple[str, ...] = (
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "OTHER_REACH",
)

# The frozen FD1 source crosswalk maps only Retrosheet ``roe`` and ``fc`` to
# OTHER_REACH.  Both mean that this batter reached; ``othout`` and the general
# field-out/force-out/double-play/sacrifice families map to BIP_OUT instead.
OTHER_REACH_SEMANTICS = {
    "batterRetired": False,
    "sourceTaxonomy": "mlb_gen2_pa_outcome_taxonomy_v1",
    "retrosheetTerminalTokens": ["roe", "fc"],
    "documentedExamples": [
        "reach_on_error",
        "fielders_choice_batter_reaches",
    ],
    "excludedOutSubtypes": [
        "ordinary_out",
        "double_play",
        "force_out",
        "sacrifice_out",
    ],
}

BINARY_LOGISTIC_CONFIG: dict[str, Any] = {
    **LOGISTIC_CONFIG,
    "randomState": RANDOM_SEED,
    "target": "BATTER_RETIRED",
}
BINARY_HGB_CONFIG: dict[str, Any] = {**HGB_CONFIG, "target": "BATTER_RETIRED"}
BINARY_EXTRA_TREES_CONFIG: dict[str, Any] = {
    **EXTRA_TREES_CONFIG,
    "target": "BATTER_RETIRED",
}


class BinaryHierarchicalExperimentError(RuntimeError):
    """Raised when frozen input, target, probability, or artifact identity differs."""


def target_contract() -> dict[str, Any]:
    """Return and mechanically validate the exact binary collapse contract."""

    order = require_frozen_class_order(PA_CLASS_ORDER)
    if tuple(name for name in order if name in OUT_CLASSES) != OUT_CLASSES:
        raise BinaryHierarchicalExperimentError("OUT classes differ from frozen class order")
    if set(OUT_CLASSES) & set(NOT_OUT_CLASSES):
        raise BinaryHierarchicalExperimentError("binary target groups overlap")
    if set(OUT_CLASSES) | set(NOT_OUT_CLASSES) != set(order):
        raise BinaryHierarchicalExperimentError("binary target groups do not cover all classes")
    if OTHER_REACH_SEMANTICS["batterRetired"] is not False:
        raise BinaryHierarchicalExperimentError("OTHER_REACH has mixed batter-retired semantics")
    return {
        "contract": TARGET_CONTRACT,
        "target": "BATTER_RETIRED",
        "operationalDefinition": "OUT_IFF_FROZEN_CLASS_IS_STRIKEOUT_OR_BIP_OUT",
        "positiveLabel": "OUT",
        "negativeLabel": "NOT_OUT",
        "classOrder": list(order),
        "outClasses": list(OUT_CLASSES),
        "notOutClasses": list(NOT_OUT_CLASSES),
        "otherReachSemantics": dict(OTHER_REACH_SEMANTICS),
    }


def binary_labels(labels: Sequence[Any] | np.ndarray) -> np.ndarray:
    """Map frozen eight-class labels to 1=OUT, 0=NOT_OUT."""

    contract = target_contract()
    encoded = encode_labels(labels, class_order=contract["classOrder"])
    indices = np.asarray(
        [PA_CLASS_ORDER.index(name) for name in OUT_CLASSES], dtype=np.int64
    )
    result = np.isin(encoded, indices).astype(np.int8)
    if result.ndim != 1 or result.size == 0:
        raise BinaryHierarchicalExperimentError("binary labels are empty or malformed")
    return result


def collapsed_out_probability(probabilities: Any) -> np.ndarray:
    """Project a validated eight-class matrix onto BATTER_RETIRED without renormalizing."""

    matrix = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
    out_indices = [PA_CLASS_ORDER.index(name) for name in OUT_CLASSES]
    not_out_indices = [PA_CLASS_ORDER.index(name) for name in NOT_OUT_CLASSES]
    out = matrix[:, out_indices].sum(axis=1, dtype=np.float64)
    not_out = matrix[:, not_out_indices].sum(axis=1, dtype=np.float64)
    if not np.allclose(out + not_out, matrix.sum(axis=1), rtol=0.0, atol=1e-12):
        raise BinaryHierarchicalExperimentError("binary group sums do not reconstruct source mass")
    return _validate_binary_probability(out)


def _validate_binary_probability(values: Any, *, expected_rows: int | None = None) -> np.ndarray:
    raw = np.asarray(values)
    if raw.dtype.kind not in "fiu":
        raise TypeError("binary probabilities must be numeric")
    result = np.asarray(raw, dtype=np.float64)
    if result.ndim != 1 or result.size == 0:
        raise ValueError("binary probabilities must be a non-empty vector")
    if expected_rows is not None and result.size != expected_rows:
        raise ValueError("binary probability row count differs")
    if not np.isfinite(result).all() or np.any(result < 0.0) or np.any(result > 1.0):
        raise ValueError("binary probabilities must be finite and within [0, 1]")
    return np.array(result, dtype=np.float64, copy=True)


def _calibration_coefficients(labels: np.ndarray, probabilities: np.ndarray) -> tuple[float, float | None]:
    """Fit the standard logistic recalibration model y ~ a + b*logit(p)."""

    epsilon = np.finfo(np.float64).eps
    logits = np.log(np.clip(probabilities, epsilon, 1.0 - epsilon)) - np.log1p(
        -np.clip(probabilities, epsilon, 1.0 - epsilon)
    )
    # A constant forecast has no identifiable joint slope.  Report the honest
    # calibration-in-the-large offset and an unavailable slope.
    if float(np.ptp(logits)) <= 1e-15:
        observed = float(labels.mean())
        observed_logit = math.log(np.clip(observed, epsilon, 1.0 - epsilon)) - math.log1p(
            -np.clip(observed, epsilon, 1.0 - epsilon)
        )
        return float(observed_logit - logits[0]), None
    model = LogisticRegression(
        penalty=None,
        solver="lbfgs",
        max_iter=2_000,
        tol=1e-12,
        fit_intercept=True,
        random_state=RANDOM_SEED,
    )
    model.fit(logits[:, None], labels)
    if not np.array_equal(model.classes_, np.asarray([0, 1])):
        raise BinaryHierarchicalExperimentError("calibration estimator classes differ")
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def evaluate_binary(labels: Any, probabilities: Any, *, n_bins: int = CALIBRATION_BINS) -> dict[str, Any]:
    """Evaluate a BATTER_RETIRED probability vector with fixed definitions."""

    y = np.asarray(labels)
    if y.ndim != 1 or y.size == 0 or not np.isin(y, [0, 1]).all():
        raise ValueError("binary labels must be a non-empty 0/1 vector")
    y = y.astype(np.int8, copy=False)
    if set(y.tolist()) != {0, 1}:
        raise ValueError("binary evaluation requires both classes")
    p = _validate_binary_probability(probabilities, expected_rows=y.size)
    if not isinstance(n_bins, int) or isinstance(n_bins, bool) or n_bins < 2:
        raise ValueError("n_bins must be an integer >= 2")
    epsilon = np.finfo(np.float64).eps
    clipped = np.clip(p, epsilon, 1.0 - epsilon)
    log_loss = -float(np.mean(y * np.log(clipped) + (1 - y) * np.log1p(-clipped)))
    brier = float(np.mean(np.square(p - y)))
    bin_index = np.minimum(np.floor(p * n_bins).astype(np.int64), n_bins - 1)
    ece = 0.0
    reliability: list[dict[str, Any]] = []
    for index in range(n_bins):
        mask = bin_index == index
        count = int(mask.sum())
        mean_probability = float(p[mask].mean()) if count else None
        realized_frequency = float(y[mask].mean()) if count else None
        gap = (
            float(realized_frequency - mean_probability)
            if count and mean_probability is not None and realized_frequency is not None
            else None
        )
        if gap is not None:
            ece += count * abs(gap) / y.size
        reliability.append(
            {
                "binIndex": index,
                "lowerBound": index / n_bins,
                "upperBound": (index + 1) / n_bins,
                "upperBoundInclusive": index == n_bins - 1,
                "count": count,
                "meanProbability": mean_probability,
                "realizedFrequency": realized_frequency,
                "gap": gap,
            }
        )
    intercept, slope = _calibration_coefficients(y, p)
    predicted = (p >= 0.5).astype(np.int8)
    return {
        "schemaVersion": "MLB_PA_BINARY_METRICS_V1",
        "target": "BATTER_RETIRED",
        "positiveClass": "OUT",
        "rowCount": int(y.size),
        "realizedOutRate": float(y.mean()),
        "meanPredictedOutProbability": float(p.mean()),
        "binaryLogLoss": log_loss,
        "brierScore": brier,
        "calibrationIntercept": intercept,
        "calibrationSlope": slope,
        "ece": float(ece),
        "eceBins": n_bins,
        "rocAuc": float(roc_auc_score(y, p)),
        "prAuc": float(average_precision_score(y, p)),
        "prAucDefinition": "AVERAGE_PRECISION",
        "accuracy": float(np.mean(predicted == y)),
        "reliability": reliability,
    }


def reconstruct_eight_class_probabilities(
    direct_gold_probabilities: Any,
    out_probability: Any,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Replace only OUT/NOT_OUT mass while retaining within-group class ratios."""

    direct = validate_probability_matrix(direct_gold_probabilities)
    binary = _validate_binary_probability(out_probability, expected_rows=direct.shape[0])
    out_indices = np.asarray([PA_CLASS_ORDER.index(name) for name in OUT_CLASSES], dtype=np.int64)
    not_out_indices = np.asarray(
        [PA_CLASS_ORDER.index(name) for name in NOT_OUT_CLASSES], dtype=np.int64
    )
    old_out = direct[:, out_indices].sum(axis=1)
    old_not_out = direct[:, not_out_indices].sum(axis=1)
    if np.any(old_out <= 0.0) or np.any(old_not_out <= 0.0):
        raise BinaryHierarchicalExperimentError("direct Gold has a zero binary-group mass")
    result = np.empty_like(direct)
    result[:, out_indices] = direct[:, out_indices] * (binary / old_out)[:, None]
    result[:, not_out_indices] = direct[:, not_out_indices] * (
        (1.0 - binary) / old_not_out
    )[:, None]
    result = validate_probability_matrix(result)
    result_out_mass = result[:, out_indices].sum(axis=1)
    result_not_mass = result[:, not_out_indices].sum(axis=1)
    positive_out_mass = result_out_mass > 0.0
    positive_not_mass = result_not_mass > 0.0
    out_difference = 0.0
    not_difference = 0.0
    if np.any(positive_out_mass):
        direct_out_ratios = direct[positive_out_mass][:, out_indices] / old_out[positive_out_mass, None]
        result_out_ratios = (
            result[positive_out_mass][:, out_indices] / result_out_mass[positive_out_mass, None]
        )
        out_difference = float(np.max(np.abs(direct_out_ratios - result_out_ratios)))
    if np.any(positive_not_mass):
        direct_not_ratios = direct[positive_not_mass][:, not_out_indices] / old_not_out[positive_not_mass, None]
        result_not_ratios = (
            result[positive_not_mass][:, not_out_indices] / result_not_mass[positive_not_mass, None]
        )
        not_difference = float(np.max(np.abs(direct_not_ratios - result_not_ratios)))
    max_ratio_difference = max(out_difference, not_difference)
    if max_ratio_difference > 2e-15:
        raise BinaryHierarchicalExperimentError("within-group class ratios changed")
    verification = {
        "contract": RECONSTRUCTION_CONTRACT,
        "classOrder": list(PA_CLASS_ORDER),
        "rows": int(result.shape[0]),
        "finite": bool(np.isfinite(result).all()),
        "nonnegative": bool(np.all(result >= 0.0)),
        "maxRowSumError": float(np.max(np.abs(result.sum(axis=1) - 1.0))),
        "maxWithinGroupRatioDifference": max_ratio_difference,
        "zeroOutMassRows": int((~positive_out_mass).sum()),
        "zeroNotOutMassRows": int((~positive_not_mass).sum()),
        "outMassMatchesBinary": bool(
            np.allclose(result[:, out_indices].sum(axis=1), binary, rtol=0.0, atol=1e-12)
        ),
        "notOutMassMatchesComplement": bool(
            np.allclose(
                result[:, not_out_indices].sum(axis=1), 1.0 - binary, rtol=0.0, atol=1e-12
            )
        ),
    }
    if not all(
        verification[key]
        for key in ("finite", "nonnegative", "outMassMatchesBinary", "notOutMassMatchesComplement")
    ):
        raise BinaryHierarchicalExperimentError("reconstructed probability verification failed")
    return result, verification


@dataclass(frozen=True)
class FittedBinaryModel:
    model_id: str
    estimator: Any
    preprocessor: FoldPreprocessor
    feature_names: tuple[str, ...]
    effective_config: Mapping[str, Any]

    def predict_out_probability(self, frame: pd.DataFrame) -> np.ndarray:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("frame must be a non-empty pandas DataFrame")
        missing = [name for name in self.feature_names if name not in frame.columns]
        if missing:
            raise ValueError(f"frame is missing binary model features: {missing}")
        values = {name: frame[name].to_numpy(copy=False) for name in self.feature_names}
        mask = np.ones(len(frame), dtype=np.bool_)
        matrix = self.preprocessor.transform(values, mask)
        classes = np.asarray(getattr(self.estimator, "classes_", ()))
        if not np.array_equal(classes, np.asarray([0, 1])):
            raise BinaryHierarchicalExperimentError("binary estimator class order differs")
        return _validate_binary_probability(self.estimator.predict_proba(matrix)[:, 1], expected_rows=len(frame))


def _logistic_factory() -> LogisticRegression:
    return LogisticRegression(
        C=0.05,
        penalty="l2",
        solver="lbfgs",
        max_iter=2_000,
        tol=1e-7,
        fit_intercept=True,
        class_weight=None,
        random_state=RANDOM_SEED,
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


def _fit_binary_candidate(
    *,
    model_id: str,
    label: str,
    frame: pd.DataFrame,
    development_mask: np.ndarray,
    validation_mask: np.ndarray,
    labels: np.ndarray,
    feature_names: tuple[str, ...],
    config: Mapping[str, Any],
    estimator_factory: Callable[[], Any],
) -> tuple[dict[str, Any], FittedBinaryModel | None, np.ndarray | None]:
    record: dict[str, Any] = {
        "modelId": model_id,
        "label": label,
        "status": "PENDING",
        "featureCount": len(feature_names),
        "features": list(feature_names),
        "effectiveConfig": dict(config),
        "developmentRows": int(development_mask.sum()),
        "validationRows": int(validation_mask.sum()),
        "fitTimeSeconds": 0.0,
        "scoreTimeSeconds": 0.0,
        "warnings": [],
        "errors": [],
    }
    fit_started = time.perf_counter()
    observed: list[warnings.WarningMessage] = []
    try:
        values = {name: frame[name].to_numpy(copy=False) for name in feature_names}
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            preprocessor = FoldPreprocessor.fit(values, feature_names, development_mask)
            development = preprocessor.transform(values, development_mask)
            estimator = estimator_factory()
            estimator.fit(development, labels[development_mask])
        record["fitTimeSeconds"] = float(time.perf_counter() - fit_started)
        if not np.array_equal(np.asarray(estimator.classes_), np.asarray([0, 1])):
            raise BinaryHierarchicalExperimentError("dedicated binary estimator classes differ")
        score_started = time.perf_counter()
        validation = preprocessor.transform(values, validation_mask)
        probabilities = _validate_binary_probability(
            estimator.predict_proba(validation)[:, 1], expected_rows=int(validation_mask.sum())
        )
        record["scoreTimeSeconds"] = float(time.perf_counter() - score_started)
        metric_started = time.perf_counter()
        record["metrics"] = evaluate_binary(labels[validation_mask], probabilities)
        record["metricTimeSeconds"] = float(time.perf_counter() - metric_started)
        record["calibrationFitScope"] = "VALIDATION_DIAGNOSTIC_ONLY_NOT_USED_FOR_PREDICTIONS"
        record["status"] = "SUCCESS"
        artifact = FittedBinaryModel(
            model_id=model_id,
            estimator=estimator,
            preprocessor=preprocessor,
            feature_names=feature_names,
            effective_config=dict(config),
        )
        return record, artifact, probabilities
    except Exception as exc:
        if record["fitTimeSeconds"] == 0.0:
            record["fitTimeSeconds"] = float(time.perf_counter() - fit_started)
        record["status"] = "FAILED"
        record["errors"] = [{"type": type(exc).__name__, "message": str(exc)}]
        return record, None, None
    finally:
        record["warnings"] = [
            {"category": item.category.__name__, "message": str(item.message)} for item in observed
        ]


def _sha_file(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _verified_multiclass_artifacts(
    *, gold_root: Path, verified_gold: Mapping[str, Any]
) -> tuple[dict[str, FittedFixedModel], dict[str, Any]]:
    request = {
        "schemaVersion": "MLB_GOLD_FIXED_EXPERIMENT_REQUEST_V1",
        "goldDatasetVersionId": verified_gold["datasetVersionId"],
        "goldLogicalContentSha256": verified_gold["logicalContentSha256"],
        "includeXgboost": True,
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "validationSeason": VALIDATION_SEASON,
        "featureOrder": list(GOLD_FEATURES),
        "promotionRequested": False,
    }
    experiment_sha = sha256_bytes(canonical_json_bytes(request))
    if experiment_sha != TRUSTED_MULTICLASS_EXPERIMENT_SHA256:
        raise BinaryHierarchicalExperimentError("multiclass experiment address differs from frozen source")
    experiment_root = Path(gold_root).resolve() / "experiments" / "sha256" / experiment_sha
    if not experiment_root.is_dir():
        raise BinaryHierarchicalExperimentError("exact Phase 7B2 multiclass experiment is missing")
    manifest_path = experiment_root / "manifest.json"
    leaderboard_path = experiment_root / "leaderboard.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("experimentSha256") != experiment_sha or manifest.get("request") != request:
        raise BinaryHierarchicalExperimentError("multiclass experiment request identity differs")
    if manifest.get("status") != "RESEARCH_ONLY" or manifest.get("promotionEligible") is not False \
            or manifest.get("championEligible") is not False:
        raise BinaryHierarchicalExperimentError("multiclass experiment governance differs")
    if manifest.get("leaderboardSha256") != TRUSTED_MULTICLASS_LEADERBOARD_SHA256 \
            or hashlib.sha256(leaderboard_path.read_bytes()).hexdigest() != TRUSTED_MULTICLASS_LEADERBOARD_SHA256:
        raise BinaryHierarchicalExperimentError("multiclass leaderboard hash differs")
    artifacts: dict[str, FittedFixedModel] = {}
    inventory: dict[str, Any] = {}
    for model_id, expected_features, expected_config in (
        ("base_logistic", tuple(FEATURE_NAMES), LOGISTIC_CONFIG),
        ("gold_logistic", tuple(GOLD_FEATURES), LOGISTIC_CONFIG),
    ):
        entry = (manifest.get("modelArtifacts") or {}).get(model_id)
        if not isinstance(entry, dict) or entry.get("file") != f"{model_id}.joblib":
            raise BinaryHierarchicalExperimentError(f"{model_id} artifact inventory differs")
        path = (experiment_root / "models" / entry["file"]).resolve()
        if experiment_root not in path.parents or not path.is_file():
            raise BinaryHierarchicalExperimentError(f"{model_id} artifact path is unsafe or missing")
        data = path.read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise BinaryHierarchicalExperimentError(f"{model_id} artifact bytes differ")
        trusted = TRUSTED_MULTICLASS_MODELS[model_id]
        if len(data) != trusted["bytes"] or hashlib.sha256(data).hexdigest() != trusted["sha256"]:
            raise BinaryHierarchicalExperimentError(f"{model_id} differs from frozen accepted bytes")
        artifact = joblib.load(io.BytesIO(data))
        if type(artifact) is not FittedFixedModel or artifact.model_id != model_id \
                or artifact.feature_names != expected_features \
                or dict(artifact.effective_config) != dict(expected_config):
            raise BinaryHierarchicalExperimentError(f"{model_id} fitted identity differs")
        if type(artifact.estimator) is not LogisticRegression \
                or type(artifact.preprocessor) is not FoldPreprocessor \
                or artifact.preprocessor.feature_names != expected_features \
                or not np.array_equal(artifact.estimator.classes_, np.arange(len(PA_CLASS_ORDER))):
            raise BinaryHierarchicalExperimentError(f"{model_id} estimator/preprocessor identity differs")
        estimator_params = artifact.estimator.get_params(deep=False)
        required_params = {
            "C": 0.05, "penalty": "l2", "solver": "lbfgs", "max_iter": 2_000,
            "tol": 1e-7, "fit_intercept": True, "class_weight": None,
        }
        if any(estimator_params.get(key) != value for key, value in required_params.items()):
            raise BinaryHierarchicalExperimentError(f"{model_id} estimator parameters differ")
        artifacts[model_id] = artifact
        inventory[model_id] = {
            "sha256": entry["sha256"], "bytes": entry["bytes"],
            "relativePath": f"models/{entry['file']}",
        }
    return artifacts, {
        "experimentSha256": experiment_sha,
        "leaderboardSha256": manifest["leaderboardSha256"],
        "modelArtifacts": inventory,
    }


def _prepare_frame(verified: Mapping[str, Any]) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    columns = [
        "canonicalPaId", "plate_appearance_id", "game_date", "season", "outcome", "datasetRole",
        *GOLD_FEATURES,
    ]
    frame = pq.read_table(Path(verified["path"]), columns=columns).to_pandas()
    if len(frame) != EXPECTED_GOLD_TOTAL_ROWS:
        raise BinaryHierarchicalExperimentError("Gold experiment row count differs")
    seasons = frame["season"].to_numpy(dtype=np.int64, copy=False)
    observed = {int(key): int(value) for key, value in frame["season"].value_counts().sort_index().items()}
    if observed != dict(EXPECTED_GOLD_SEASON_ROWS) or set(observed) != {2021, 2022, 2023, 2024}:
        raise BinaryHierarchicalExperimentError(f"Gold temporal population differs: {observed}")
    development_mask = np.isin(seasons, DEVELOPMENT_SEASONS)
    validation_mask = seasons == VALIDATION_SEASON
    if int(development_mask.sum()) != EXPECTED_GOLD_DEVELOPMENT_ROWS \
            or int(validation_mask.sum()) != EXPECTED_GOLD_VALIDATION_ROWS:
        raise BinaryHierarchicalExperimentError("Gold development/validation rows differ")
    expected_roles = np.where(validation_mask, "VALIDATION", "DEVELOPMENT")
    if not np.array_equal(frame["datasetRole"].to_numpy(dtype=object), expected_roles):
        raise BinaryHierarchicalExperimentError("Gold dataset roles differ")
    if frame["canonicalPaId"].duplicated().any() or frame["plate_appearance_id"].duplicated().any():
        raise BinaryHierarchicalExperimentError("Gold PA identities are duplicated")
    labels = binary_labels(frame["outcome"].to_numpy(copy=False))
    if set(labels[development_mask].tolist()) != {0, 1} \
            or set(labels[validation_mask].tolist()) != {0, 1}:
        raise BinaryHierarchicalExperimentError("binary classes are absent from a split")
    return frame, development_mask, validation_mask, labels


def _record_existing_projection(
    *, model_id: str, label: str, artifact: FittedFixedModel,
    validation: pd.DataFrame, labels: np.ndarray,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    started = time.perf_counter()
    probabilities8 = artifact.predict_proba(validation)
    probabilities = collapsed_out_probability(probabilities8)
    elapsed = float(time.perf_counter() - started)
    metric_started = time.perf_counter()
    metrics = evaluate_binary(labels, probabilities)
    metric_elapsed = float(time.perf_counter() - metric_started)
    return {
        "modelId": model_id,
        "label": label,
        "status": "SUCCESS",
        "source": "PERSISTED_EIGHT_CLASS_PROBABILITY_COLLAPSE",
        "featureCount": len(artifact.feature_names),
        "fitTimeSeconds": 0.0,
        "fitTimeMeaning": "persisted eight-class model was not refit",
        "scoreTimeSeconds": elapsed,
        "metricTimeSeconds": metric_elapsed,
        "calibrationFitScope": "VALIDATION_DIAGNOSTIC_ONLY_NOT_USED_FOR_PREDICTIONS",
        "metrics": metrics,
        "warnings": [],
        "errors": [],
    }, probabilities, probabilities8


def _recommendation(
    *, direct: Mapping[str, Any], reconstructed: Mapping[str, Any],
    best_binary: Mapping[str, Any], collapsed_gold: Mapping[str, Any],
) -> tuple[str, str]:
    direct_loss = float(direct["logLoss"])
    reconstructed_loss = float(reconstructed["logLoss"])
    dedicated_loss = float(best_binary["binaryLogLoss"])
    collapsed_loss = float(collapsed_gold["binaryLogLoss"])
    if reconstructed_loss < direct_loss and dedicated_loss < collapsed_loss:
        return (
            "C. ADOPT_HIERARCHICAL_8_CLASS_ARCHITECTURE",
            "The best dedicated binary model improves the collapsed Gold binary loss and its group-mass reconstruction improves direct eight-class log loss.",
        )
    if dedicated_loss < collapsed_loss:
        return (
            "B. USE_BINARY_AS_AUXILIARY_CALIBRATION_LAYER",
            "The dedicated binary target improves OUT/NOT_OUT discrimination, but replacing direct Gold group mass does not improve eight-class log loss.",
        )
    return (
        "A. KEEP_DIRECT_8_CLASS",
        "The dedicated binary target does not improve the existing Gold Logistic OUT/NOT_OUT projection.",
    )


def _implementation_identity() -> dict[str, Any]:
    path = Path(__file__).resolve()
    data = path.read_bytes()
    return {
        "relativePath": "server/sports_gold/binary_hierarchical.py",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": sklearn.__version__,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# BATTER_RETIRED binary / hierarchical PA experiment",
        "",
        f"Gold dataset: `{result['goldDatasetVersionId']}`",
        f"Development rows: {result['developmentRows']:,}; validation rows: {result['validationRows']:,}.",
        "",
        "| Model | Binary log loss | Brier | Cal intercept | Cal slope | ECE | ROC-AUC | PR-AUC | Accuracy | Fit s | Score s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["binaryLeaderboard"]:
        metrics = row.get("metrics") or {}
        def value(name: str) -> str:
            raw = metrics.get(name)
            return "—" if raw is None else f"{float(raw):.9f}"
        lines.append(
            f"| {row['label']} | {value('binaryLogLoss')} | {value('brierScore')} | "
            f"{value('calibrationIntercept')} | {value('calibrationSlope')} | {value('ece')} | "
            f"{value('rocAuc')} | {value('prAuc')} | {value('accuracy')} | "
            f"{float(row['fitTimeSeconds']):.3f} | {float(row['scoreTimeSeconds']):.3f} |"
        )
    direct = result["eightClassComparison"]["directGoldLogistic"]
    rebuilt = result["eightClassComparison"]["hierarchicalReconstruction"]
    lines.extend([
        "", "## Eight-class comparison", "",
        "| Variant | Log loss | Summed Brier | ECE | Accuracy | Macro-F1 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Direct Gold Logistic | {direct['logLoss']:.12f} | {direct['brierScore']:.9f} | {direct['topLabelEce']:.9f} | {direct['top1Accuracy']:.9f} | {direct['macroF1']:.9f} |",
        f"| Hierarchical reconstruction | {rebuilt['logLoss']:.12f} | {rebuilt['brierScore']:.9f} | {rebuilt['topLabelEce']:.9f} | {rebuilt['top1Accuracy']:.9f} | {rebuilt['macroF1']:.9f} |",
        "", f"Recommendation: **{result['recommendation']['decision']}**", "",
        result["recommendation"]["reason"], "",
        "No model was promoted; the output is research-only.", "",
    ])
    return "\n".join(lines)


def _load_existing_result(
    final: Path, *, request: Mapping[str, Any], experiment_sha: str
) -> dict[str, Any]:
    """Verify an immutable prior result completely before idempotent reuse."""

    manifest_path = final / "manifest.json"
    results_path = final / "results.json"
    if not manifest_path.is_file() or not results_path.is_file():
        raise BinaryHierarchicalExperimentError("existing binary experiment is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != "MLB_GOLD_BINARY_EXPERIMENT_MANIFEST_V1" \
            or manifest.get("experimentSha256") != experiment_sha \
            or manifest.get("request") != dict(request) \
            or manifest.get("status") != "RESEARCH_ONLY" \
            or manifest.get("promotionEligible") is not False \
            or manifest.get("championEligible") is not False:
        raise BinaryHierarchicalExperimentError("existing binary experiment authority differs")
    results_data = results_path.read_bytes()
    if hashlib.sha256(results_data).hexdigest() != manifest.get("resultsSha256"):
        raise BinaryHierarchicalExperimentError("existing binary result bytes differ")
    report_path = final / "experiment-report.md"
    if not report_path.is_file() \
            or hashlib.sha256(report_path.read_bytes()).hexdigest() != manifest.get("reportSha256"):
        raise BinaryHierarchicalExperimentError("existing binary report bytes differ")
    inventory = manifest.get("modelArtifacts")
    if not isinstance(inventory, dict) or not inventory:
        raise BinaryHierarchicalExperimentError("existing binary model inventory is missing")
    for model_id, item in sorted(inventory.items()):
        if not isinstance(item, dict) or item.get("relativePath") != f"models/{model_id}.joblib":
            raise BinaryHierarchicalExperimentError("existing binary model relationship differs")
        path = (final / item["relativePath"]).resolve()
        if final.resolve() not in path.parents or not path.is_file():
            raise BinaryHierarchicalExperimentError("existing binary model path is unsafe or missing")
        size, digest = _sha_file(path)
        if size != item.get("bytes") or digest != item.get("sha256"):
            raise BinaryHierarchicalExperimentError("existing binary model bytes differ")
    result = json.loads(results_data)
    if result.get("experimentSha256") != experiment_sha \
            or result.get("schemaVersion") != SCHEMA_VERSION \
            or result.get("status") != "RESEARCH_ONLY_COMPLETE" \
            or result.get("modelArtifacts") != inventory \
            or result.get("promotionPerformed") is not False:
        raise BinaryHierarchicalExperimentError("existing binary result relationships differ")
    result["artifactRoot"] = str(final)
    return result


def run_binary_hierarchical_experiment(
    *, gold_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the fixed experiment against existing Gold and persisted multiclass artifacts."""

    emit = progress or (lambda _message: None)
    started = time.perf_counter()
    contract = target_contract()
    emit("verifying frozen Gold and persisted multiclass artifacts")
    verified = verify_gold(Path(gold_root))
    if set(verified["seasons"]) != {2021, 2022, 2023, 2024}:
        raise BinaryHierarchicalExperimentError("verified Gold contains a prohibited season")
    artifacts, source_experiment = _verified_multiclass_artifacts(
        gold_root=Path(gold_root), verified_gold=verified
    )
    frame, development_mask, validation_mask, labels = _prepare_frame(verified)
    post_read_verified = verify_gold(
        Path(gold_root), object_sha=str(verified["logicalContentSha256"])
    )
    if post_read_verified["datasetVersionId"] != verified["datasetVersionId"] \
            or post_read_verified["logicalContentSha256"] != verified["logicalContentSha256"] \
            or post_read_verified["rowCount"] != verified["rowCount"]:
        raise BinaryHierarchicalExperimentError("Gold identity changed during frame materialization")
    validation = frame.loc[validation_mask].reset_index(drop=True)
    y_validation = labels[validation_mask]
    y_development = labels[development_mask]

    records: list[dict[str, Any]] = []
    probabilities: dict[str, np.ndarray] = {}
    fitted: dict[str, FittedBinaryModel] = {}

    fit_started = time.perf_counter()
    frequency = float(y_development.mean())
    fit_elapsed = float(time.perf_counter() - fit_started)
    score_started = time.perf_counter()
    null_probability = np.full(y_validation.size, frequency, dtype=np.float64)
    score_elapsed = float(time.perf_counter() - score_started)
    metric_started = time.perf_counter()
    null_metrics = evaluate_binary(y_validation, null_probability)
    metric_elapsed = float(time.perf_counter() - metric_started)
    records.append({
        "modelId": "binary_null", "label": "Binary class-frequency null", "status": "SUCCESS",
        "source": "DEVELOPMENT_FREQUENCY", "featureCount": 0,
        "fitTimeSeconds": fit_elapsed, "scoreTimeSeconds": score_elapsed,
        "metricTimeSeconds": metric_elapsed,
        "calibrationFitScope": "VALIDATION_DIAGNOSTIC_ONLY_NOT_USED_FOR_PREDICTIONS",
        "metrics": null_metrics, "warnings": [], "errors": [],
    })
    probabilities["binary_null"] = null_probability

    emit("scoring persisted Base and Gold Logistic artifacts")
    base_record, base_collapsed, _base8 = _record_existing_projection(
        model_id="collapsed_base_logistic", label="Collapsed Base Logistic",
        artifact=artifacts["base_logistic"], validation=validation, labels=y_validation,
    )
    gold_record, gold_collapsed, gold8 = _record_existing_projection(
        model_id="collapsed_gold_logistic", label="Collapsed Gold Logistic",
        artifact=artifacts["gold_logistic"], validation=validation, labels=y_validation,
    )
    records.extend([base_record, gold_record])
    probabilities[base_record["modelId"]] = base_collapsed
    probabilities[gold_record["modelId"]] = gold_collapsed

    full_features = tuple(GOLD_FEATURES)
    candidates = (
        ("dedicated_base_binary_logistic", "Dedicated Base binary Logistic", tuple(FEATURE_NAMES), BINARY_LOGISTIC_CONFIG, _logistic_factory),
        ("dedicated_gold_binary_logistic", "Dedicated Gold binary Logistic", full_features, BINARY_LOGISTIC_CONFIG, _logistic_factory),
        ("dedicated_gold_binary_hgb", "Dedicated Gold binary HGB", full_features, BINARY_HGB_CONFIG, _hgb_factory),
        ("dedicated_gold_binary_extra_trees", "Dedicated Gold binary Extra Trees", full_features, BINARY_EXTRA_TREES_CONFIG, _extra_trees_factory),
    )
    for model_id, label, features, config, factory in candidates:
        emit(f"fitting {label}")
        record, artifact, predicted = _fit_binary_candidate(
            model_id=model_id, label=label, frame=frame,
            development_mask=development_mask, validation_mask=validation_mask,
            labels=labels, feature_names=features, config=config, estimator_factory=factory,
        )
        records.append(record)
        if artifact is not None and predicted is not None:
            fitted[model_id] = artifact
            probabilities[model_id] = predicted

    dedicated_records = [row for row in records if row["modelId"].startswith("dedicated_")]
    successful_dedicated = [row for row in dedicated_records if row["status"] == "SUCCESS"]
    if not successful_dedicated:
        raise BinaryHierarchicalExperimentError("all dedicated binary models failed")
    best = min(successful_dedicated, key=lambda row: float(row["metrics"]["binaryLogLoss"]))
    best_id = str(best["modelId"])
    emit(f"reconstructing eight-class probabilities from {best['label']}")
    reconstructed, reconstruction_verification = reconstruct_eight_class_probabilities(
        gold8, probabilities[best_id]
    )
    direct_metrics = evaluate_multiclass(validation["outcome"].to_numpy(copy=False), gold8)
    if not math.isclose(float(direct_metrics["logLoss"]), DIRECT_GOLD_LOG_LOSS, rel_tol=0.0, abs_tol=1e-12):
        raise BinaryHierarchicalExperimentError(
            f"direct Gold Logistic log loss differs: {direct_metrics['logLoss']}"
        )
    reconstructed_metrics = evaluate_multiclass(
        validation["outcome"].to_numpy(copy=False), reconstructed
    )
    decision, reason = _recommendation(
        direct=direct_metrics,
        reconstructed=reconstructed_metrics,
        best_binary=best["metrics"],
        collapsed_gold=gold_record["metrics"],
    )

    implementation = _implementation_identity()
    request = {
        "schemaVersion": SCHEMA_VERSION,
        "goldDatasetVersionId": verified["datasetVersionId"],
        "goldLogicalContentSha256": verified["logicalContentSha256"],
        "sourceMulticlassExperiment": source_experiment,
        "targetContract": contract,
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "validationSeason": VALIDATION_SEASON,
        "developmentRows": int(development_mask.sum()),
        "validationRows": int(validation_mask.sum()),
        "baseFeatures": list(FEATURE_NAMES),
        "goldFeatures": list(GOLD_FEATURES),
        "fixedSeed": RANDOM_SEED,
        "modelConfigs": {
            "logistic": dict(BINARY_LOGISTIC_CONFIG), "hgb": dict(BINARY_HGB_CONFIG),
            "extraTrees": dict(BINARY_EXTRA_TREES_CONFIG),
        },
        "metricDefinitions": {
            "positiveClass": "OUT", "brier": "MEAN_SQUARED_BINARY_ERROR",
            "ece": "10_EQUAL_WIDTH_BINS", "prAuc": "AVERAGE_PRECISION",
            "calibration": "LOGISTIC_Y_ON_INTERCEPT_PLUS_SLOPE_TIMES_LOGIT_P",
        },
        "implementation": implementation,
        "promotionRequested": False,
    }
    experiment_sha = sha256_bytes(canonical_json_bytes(request))
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "RESEARCH_ONLY_COMPLETE",
        "experimentSha256": experiment_sha,
        "goldDatasetVersionId": verified["datasetVersionId"],
        "goldLogicalContentSha256": verified["logicalContentSha256"],
        "sourceMulticlassExperiment": source_experiment,
        "targetContract": contract,
        "classOrder": list(PA_CLASS_ORDER),
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "validationSeason": VALIDATION_SEASON,
        "developmentRows": int(development_mask.sum()),
        "validationRows": int(validation_mask.sum()),
        "seasonRows": {str(key): int(value) for key, value in EXPECTED_GOLD_SEASON_ROWS.items()},
        "binaryLeaderboard": records,
        "bestDedicatedBinaryModelId": best_id,
        "eightClassComparison": {
            "directGoldLogistic": direct_metrics,
            "hierarchicalReconstruction": reconstructed_metrics,
            "logLossDifferenceReconstructedMinusDirect": float(
                reconstructed_metrics["logLoss"] - direct_metrics["logLoss"]
            ),
        },
        "reconstructionVerification": reconstruction_verification,
        "temporalVerification": {
            "goldSeasons": verified["seasons"],
            "developmentSeasons": list(DEVELOPMENT_SEASONS),
            "validationSeason": VALIDATION_SEASON,
            "prohibitedSeasonsPresent": [],
            "goldContractBundleSha256": gold_contract_bundle()["bundleSha256"],
            "featureCutoff": "END_OF_PREVIOUS_COMPLETED_DAY",
            "newFeaturesAdded": False,
            "dataRebuilt": False,
        },
        "recommendation": {"decision": decision, "reason": reason},
        "promotionRequested": False,
        "promotionPerformed": False,
        "elapsedSeconds": float(time.perf_counter() - started),
    }
    result = _json_safe(result)

    final = Path(gold_root).resolve() / "binary-experiments" / "sha256" / experiment_sha
    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    model_inventory: dict[str, Any] = {}
    try:
        models_dir = staging / "models"
        models_dir.mkdir()
        for model_id, artifact in sorted(fitted.items()):
            path = models_dir / f"{model_id}.joblib"
            joblib.dump(artifact, path, compress=3)
            size, digest = _sha_file(path)
            model_inventory[model_id] = {
                "relativePath": f"models/{path.name}", "bytes": size, "sha256": digest,
            }
        result["modelArtifacts"] = model_inventory
        result_bytes = canonical_json_bytes(result)
        (staging / "results.json").write_bytes(result_bytes)
        report_path = staging / "experiment-report.md"
        report_path.write_text(
            _markdown(result), encoding="utf-8", newline="\n"
        )
        (staging / "manifest.json").write_bytes(canonical_json_bytes({
            "schemaVersion": "MLB_GOLD_BINARY_EXPERIMENT_MANIFEST_V1",
            "experimentSha256": experiment_sha,
            "request": request,
            "resultsSha256": hashlib.sha256(result_bytes).hexdigest(),
            "reportSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "modelArtifacts": model_inventory,
            "status": "RESEARCH_ONLY",
            "promotionEligible": False,
            "championEligible": False,
        }))
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            persisted_result = _load_existing_result(
                final, request=request, experiment_sha=experiment_sha
            )
            shutil.rmtree(staging)
        else:
            # Windows can deny directory-to-directory os.replace even when this
            # process owns both paths.  Build the request-addressed result with
            # the manifest copied last; readers accept only a complete, fully
            # hashed manifest and never treat a partial directory as authority.
            final.mkdir(parents=False, exist_ok=False)
            (final / "models").mkdir()
            for model_path in sorted((staging / "models").iterdir()):
                shutil.copy2(model_path, final / "models" / model_path.name)
            shutil.copy2(staging / "results.json", final / "results.json")
            shutil.copy2(staging / "experiment-report.md", final / "experiment-report.md")
            shutil.copy2(staging / "manifest.json", final / "manifest.json")
            persisted_result = _load_existing_result(
                final, request=request, experiment_sha=experiment_sha
            )
            shutil.rmtree(staging)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    persisted_result["artifactRoot"] = str(final)
    return persisted_result


__all__ = [
    "BinaryHierarchicalExperimentError",
    "DIRECT_GOLD_LOG_LOSS",
    "FittedBinaryModel",
    "NOT_OUT_CLASSES",
    "OTHER_REACH_SEMANTICS",
    "OUT_CLASSES",
    "binary_labels",
    "collapsed_out_probability",
    "evaluate_binary",
    "reconstruct_eight_class_probabilities",
    "run_binary_hierarchical_experiment",
    "target_contract",
]
