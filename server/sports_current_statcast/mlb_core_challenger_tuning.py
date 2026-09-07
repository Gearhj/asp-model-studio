"""Frozen compact tuning authority and game-clustered uncertainty utilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes
from .stage3_model_laboratory import _runtime_root


PROJECT_ID = "asp-mtlozhdx"
TUNING_SCHEMA_VERSION = "MLB_CORE_CHALLENGER_COMPACT_TUNING_DECISION_V1"
TUNING_BATCH_NAME = "MLB Core Challenger compact leakage-safe tuning"
TUNING_SEED = 20260906
BOOTSTRAP_SEED = 20260907
BOOTSTRAP_REPLICATES = 2_000

HGB_FIRST_SCREEN_FINGERPRINT = (
    "stage3-candidate-spec-14098e08fb874d91048e1388094e69f66e47c6140aeab1e2f0b52f0b619348bc"
)
RF_FIRST_SCREEN_FINGERPRINT = (
    "stage3-candidate-spec-2015b6c4960574ae193ac1835fdf9b0ff620879b21b5a944b45350ffc14fe275"
)

FIRST_SCREEN_BENCHMARKS = {
    "histogram_gradient_boosting": {
        "candidateFingerprint": HGB_FIRST_SCREEN_FINGERPRINT,
        "meanOofLogLoss": 1.4772751225154797,
        "macroOvrRocAuc": 0.5732568080843019,
        "runtimeMs": 2_938_393,
    },
    "random_forest": {
        "candidateFingerprint": RF_FIRST_SCREEN_FINGERPRINT,
        "meanOofLogLoss": 1.4797935540664207,
        "macroOvrRocAuc": 0.5566344390631222,
        "runtimeMs": 1_949_769,
    },
}

NULL_BASELINE = {
    "candidateFingerprint": (
        "stage3-candidate-spec-bb5fefb7a8fa53e12220a52498379eb67992e2da172d48141ac5492f63da29c6"
    ),
    "meanOofLogLoss": 1.4963720811895196,
    "summedBrier": 0.7119314081022192,
    "ece": 0.005744468958516491,
    "macroOvrRocAuc": 0.5005389548301921,
}

HGB_GRID: tuple[dict[str, Any], ...] = (
    {
        "learning_rate": 0.03,
        "max_iter": 500,
        "max_leaf_nodes": 31,
        "max_depth": None,
        "min_samples_leaf": 50,
        "l2_regularization": 1.0,
        "early_stopping": False,
    },
    {
        "learning_rate": 0.07,
        "max_iter": 300,
        "max_leaf_nodes": 31,
        "max_depth": None,
        "min_samples_leaf": 20,
        "l2_regularization": 1.0,
        "early_stopping": False,
    },
    {
        "learning_rate": 0.1,
        "max_iter": 200,
        "max_leaf_nodes": 63,
        "max_depth": None,
        "min_samples_leaf": 20,
        "l2_regularization": 10.0,
        "early_stopping": False,
    },
)

RF_GRID: tuple[dict[str, Any], ...] = (
    {
        "n_estimators": 300,
        "max_depth": 24,
        "min_samples_leaf": 5,
        "max_features": "sqrt",
        "bootstrap": True,
        "class_weight": None,
    },
    {
        "n_estimators": 500,
        "max_depth": None,
        "min_samples_leaf": 20,
        "max_features": 0.5,
        "bootstrap": True,
        "class_weight": None,
    },
)


def exact_grids() -> dict[str, list[dict[str, Any]]]:
    return {
        "histogram_gradient_boosting": [dict(item) for item in HGB_GRID],
        "random_forest": [dict(item) for item in RF_GRID],
    }


def runtime_estimate() -> dict[str, Any]:
    hgb_reference = int(FIRST_SCREEN_BENCHMARKS["histogram_gradient_boosting"]["runtimeMs"])
    rf_reference = int(FIRST_SCREEN_BENCHMARKS["random_forest"]["runtimeMs"])
    hgb_ms = sum(hgb_reference * float(item["max_iter"]) / 300.0 for item in HGB_GRID)
    rf_ms = sum(rf_reference * float(item["n_estimators"]) / 300.0 for item in RF_GRID)
    raw_ms = int(round(hgb_ms + rf_ms))
    contingency_ms = int(round(raw_ms * 1.15))
    ceiling_ms = 5 * 60 * 60 * 1000
    return {
        "method": "FIRST_SCREEN_RUNTIME_SCALED_BY_ITERATIONS_OR_TREE_COUNT",
        "configurationCount": len(HGB_GRID) + len(RF_GRID),
        "officialFoldFits": 5 * (len(HGB_GRID) + len(RF_GRID)),
        "rawEstimateMs": raw_ms,
        "contingencyFactor": 1.15,
        "contingencyEstimateMs": contingency_ms,
        "operationalCeilingMs": ceiling_ms,
        "reductionRequired": contingency_ms > ceiling_ms,
        "deterministicReductionRule": (
            "If the pre-fit contingency estimate exceeds five hours, remove the RF 500-tree "
            "configuration first; if still excessive, remove HGB 500-iteration configuration. "
            "No observed tuning result may influence this rule."
        ),
    }


def tuning_experiments(feature_set_id: str) -> list[dict[str, Any]]:
    estimate = runtime_estimate()
    if estimate["reductionRequired"]:
        raise RuntimeError(
            "The frozen five-configuration grid exceeds its operational ceiling; apply the "
            "declared deterministic reduction in a new reviewed authority before fitting."
        )
    return [
        {
            "algorithmId": "histogram_gradient_boosting",
            "featureUniverseId": feature_set_id,
            "tuningMode": "GRID",
            "gridPreset": "COMPACT",
            "compactGrid": [dict(item) for item in HGB_GRID],
            "parentCandidateFingerprint": HGB_FIRST_SCREEN_FINGERPRINT,
        },
        {
            "algorithmId": "random_forest",
            "featureUniverseId": feature_set_id,
            "tuningMode": "GRID",
            "gridPreset": "COMPACT",
            "compactGrid": [dict(item) for item in RF_GRID],
            "parentCandidateFingerprint": RF_FIRST_SCREEN_FINGERPRINT,
        },
    ]


def _oof_path(attempt: Mapping[str, Any]) -> Path:
    evaluation = attempt.get("evaluationEvidence") or {}
    relative = str(evaluation.get("reloadableArtifactRelativePath") or "")
    if not relative:
        raise RuntimeError("The tuning attempt has no reloadable OOF artifact.")
    path = (_runtime_root() / Path(relative)).resolve()
    root = _runtime_root().resolve()
    if root not in path.parents or not path.is_file():
        raise RuntimeError("The tuning OOF artifact is outside the governed runtime root or missing.")
    return path


def read_oof(attempt: Mapping[str, Any]) -> pd.DataFrame:
    path = _oof_path(attempt)
    expected_sha = str(
        (attempt.get("evaluationEvidence") or {}).get("reloadableArtifactSha256") or ""
    )
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError("The tuning OOF artifact content hash does not reconcile.")
    frame = pq.read_table(path).to_pandas()
    required = {"canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError("The tuning OOF artifact lacks cluster identity: " + ", ".join(missing))
    return frame


def paired_game_cluster_bootstrap(
    left_attempt: Mapping[str, Any],
    right_attempt: Mapping[str, Any],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Estimate left-minus-right log-loss uncertainty by resampling games."""

    if replicates < 200:
        raise ValueError("At least 200 clustered bootstrap replicates are required.")
    left = read_oof(left_attempt)
    right = read_oof(right_attempt)
    identity = ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex"]
    probability_columns = [name for name in left.columns if name.startswith("probability_")]
    if probability_columns != [
        name for name in right.columns if name.startswith("probability_")
    ]:
        raise RuntimeError("The paired tuning artifacts have different probability classes.")
    merged = left.merge(right, on=identity, how="outer", validate="one_to_one", indicator=True, suffixes=("_left", "_right"))
    if not (merged["_merge"] == "both").all() or len(merged) != len(left) or len(left) != len(right):
        raise RuntimeError("The paired tuning OOF artifacts do not align one-to-one.")
    labels = merged["observedClassIndex"].to_numpy(dtype=np.int64)
    row_index = np.arange(len(merged))
    left_probabilities = np.column_stack(
        [merged[f"{name}_left"].to_numpy(dtype=float) for name in probability_columns]
    )
    right_probabilities = np.column_stack(
        [merged[f"{name}_right"].to_numpy(dtype=float) for name in probability_columns]
    )
    epsilon = np.finfo(np.float64).eps
    left_loss = -np.log(np.clip(left_probabilities[row_index, labels], epsilon, 1.0))
    right_loss = -np.log(np.clip(right_probabilities[row_index, labels], epsilon, 1.0))
    working = pd.DataFrame(
        {
            "canonicalGameId": merged["canonicalGameId"].astype(str),
            "lossDifference": left_loss - right_loss,
        }
    )
    grouped = working.groupby("canonicalGameId", sort=True)["lossDifference"].agg(["sum", "count"])
    sums = grouped["sum"].to_numpy(dtype=float)
    counts = grouped["count"].to_numpy(dtype=np.int64)
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=float)
    batch_size = 100
    for start in range(0, replicates, batch_size):
        stop = min(start + batch_size, replicates)
        indices = rng.integers(0, len(grouped), size=(stop - start, len(grouped)))
        draws[start:stop] = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    estimate = float((left_loss - right_loss).mean())
    lower, upper = np.quantile(draws, [0.025, 0.975])
    fold_differences = [
        {
            "foldNumber": int(fold),
            "leftMinusRightLogLoss": float(
                (left_loss[merged["foldNumber"].to_numpy() == fold]
                 - right_loss[merged["foldNumber"].to_numpy() == fold]).mean()
            ),
        }
        for fold in sorted(merged["foldNumber"].unique())
    ]
    return {
        "method": "PAIRED_NONPARAMETRIC_BOOTSTRAP_CLUSTERED_BY_CANONICAL_GAME_ID",
        "estimand": "LEFT_MINUS_RIGHT_MULTICLASS_LOG_LOSS",
        "rowCount": int(len(merged)),
        "gameClusterCount": int(len(grouped)),
        "replicates": int(replicates),
        "seed": int(seed),
        "estimate": estimate,
        "standardError": float(np.std(draws, ddof=1)),
        "confidenceLevel": 0.95,
        "confidenceInterval": {"lower": float(lower), "upper": float(upper)},
        "probabilityLeftBetter": float(np.mean(draws < 0.0)),
        "foldDifferences": fold_differences,
        "consistentDirectionAcrossFolds": (
            all(item["leftMinusRightLogLoss"] < 0.0 for item in fold_differences)
            or all(item["leftMinusRightLogLoss"] > 0.0 for item in fold_differences)
        ),
        "finalOotTargetAccessed": False,
    }


def latest_tuning_decision(project_id: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    directory = _runtime_root() / "tuning-decisions" / "objects" / "sha256"
    for path in directory.glob("*.json") if directory.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schemaVersion") == TUNING_SCHEMA_VERSION
            and payload.get("projectId") == project_id
            and hashlib.sha256(canonical_json_bytes(payload)).hexdigest() == path.stem
        ):
            candidates.append({**payload, "receiptSha256": path.stem})
    static_path = Path(__file__).with_name("mlb_core_challenger_tuning_decision_v1.json")
    if static_path.is_file():
        try:
            payload = json.loads(static_path.read_text(encoding="utf-8"))
            receipt = str(payload.get("receiptSha256") or "") if isinstance(payload, dict) else ""
            content = (
                {key: value for key, value in payload.items() if key != "receiptSha256"}
                if isinstance(payload, dict)
                else {}
            )
            if (
                isinstance(payload, dict)
                and payload.get("schemaVersion") == TUNING_SCHEMA_VERSION
                and payload.get("projectId") == project_id
                and len(receipt) == 64
                and hashlib.sha256(canonical_json_bytes(content)).hexdigest() == receipt
            ):
                candidates.append(payload)
        except (OSError, json.JSONDecodeError):
            pass
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (str(item.get("createdAt") or ""), str(item.get("receiptSha256") or "")),
    )


__all__ = [
    "BOOTSTRAP_REPLICATES",
    "BOOTSTRAP_SEED",
    "FIRST_SCREEN_BENCHMARKS",
    "HGB_GRID",
    "NULL_BASELINE",
    "PROJECT_ID",
    "RF_GRID",
    "TUNING_BATCH_NAME",
    "TUNING_SCHEMA_VERSION",
    "TUNING_SEED",
    "exact_grids",
    "latest_tuning_decision",
    "paired_game_cluster_bootstrap",
    "read_oof",
    "runtime_estimate",
    "tuning_experiments",
]
