"""Reproducible Phase 7B5 recent-data walk-forward research pipeline.

The pipeline reads only the current verified Gold V1 object and independently
verifies the exact Silver plate-appearance authority already bound into Gold.
It freezes the final fourteen active dates and five globally optimized
walk-forward folds in a content-addressed request before the first fit.  All
large predictions and fitted artifacts are written outside Git beneath that
request address.  There is no build, registration, promotion, or post-2024
path in this module.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import time
import uuid
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels
from server.sports_modeling.training import FoldPreprocessor

from .contracts import (
    EXPECTED_GOLD_SEASON_ROWS,
    EXPECTED_GOLD_TOTAL_ROWS,
    GOLD_FEATURES,
)
from .models import FittedFixedModel, LOGISTIC_CONFIG
from .publication import verify_gold
from .silver_inputs import resolve_current_silver
from .walk_forward_charts import generate_walk_forward_charts
from .walk_forward_ensemble import (
    COMPARISON_CANDIDATE_IDS,
    DIRECT_GOLD,
    RELIABILITY_FIELDS,
    WALK_FORWARD_COMPONENT_ORDER,
    WALK_FORWARD_EMPIRICAL_COMPONENTS,
    WALK_FORWARD_ENSEMBLE_IDS,
    FrozenHoldout,
    WalkForwardFold,
    build_fixed_walk_forward_ensembles,
    compact_multiclass_metrics,
    daily_metric_records,
    evaluate_walk_forward_candidates,
    fit_walk_forward_convex_blend,
    fit_walk_forward_stacker,
    five_equal_pa_walk_forward_folds,
    fixed_walk_forward_ensemble_definitions,
    freeze_final_holdout,
)
from .walk_forward_state import (
    ChronologicalDirectLedger,
    WalkForwardBlockBundle,
    fit_walk_forward_state,
    score_walk_forward_block,
)


SCHEMA_VERSION = "MLB_GOLD_RECENT_DATA_WALK_FORWARD_STUDY_V1"
FROZEN_GOLD_SHA256 = "56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0"
EXPECTED_OOF_ROWS = 524_525
EXPECTED_FINAL_TRAINING_ROWS = 703_047
EXPECTED_HOLDOUT_ROWS = 13_766
EXPECTED_HOLDOUT_GAMES = 183
EXPECTED_HOLDOUT_START = "2024-09-16"
EXPECTED_HOLDOUT_END = "2024-09-29"
EXPECTED_HOLDOUT_PA_INVENTORY_SHA256 = (
    "66775f68948c3b650510d8f8ec27727e7b342fe74038730ce9400d914d2d081a"
)
EXPECTED_HOLDOUT_GAME_INVENTORY_SHA256 = (
    "c26f9649a9606ef1ce573d72a6cfcb1dee4cb73744212152d2315e1fe8e96ac9"
)
SILVER_TABLE = "fact_statcast_plate_appearance"
BASE_FEATURES: tuple[str, ...] = tuple(FEATURE_NAMES)
DIRECT_FEATURES: tuple[str, ...] = tuple(GOLD_FEATURES)

EXPECTED_FOLDS: tuple[dict[str, Any], ...] = (
    {
        "foldId": "FOLD_1",
        "trainEnd": "2021-10-03",
        "trainingRows": 178_522,
        "validationStart": "2022-04-07",
        "validationEnd": "2022-07-25",
        "validationRows": 105_063,
    },
    {
        "foldId": "FOLD_2",
        "trainEnd": "2022-07-25",
        "trainingRows": 283_585,
        "validationStart": "2022-07-26",
        "validationEnd": "2023-05-03",
        "validationRows": 105_289,
    },
    {
        "foldId": "FOLD_3",
        "trainEnd": "2023-05-03",
        "trainingRows": 388_874,
        "validationStart": "2023-05-04",
        "validationEnd": "2023-08-19",
        "validationRows": 104_339,
    },
    {
        "foldId": "FOLD_4",
        "trainEnd": "2023-08-19",
        "trainingRows": 493_213,
        "validationStart": "2023-08-20",
        "validationEnd": "2024-05-29",
        "validationRows": 105_172,
    },
    {
        "foldId": "FOLD_5",
        "trainEnd": "2024-05-29",
        "trainingRows": 598_385,
        "validationStart": "2024-05-30",
        "validationEnd": "2024-09-15",
        "validationRows": 104_662,
    },
)

RECOMMENDATIONS: tuple[str, ...] = (
    "A. KEEP_DIRECT_GOLD",
    "B. ADD_14_DAY_STATE",
    "C. ADD_14_AND_42_DAY_STATE",
    "D. USE_LONGER_ROLLING_STATE",
    "E. USE_STATIC_ENSEMBLE",
    "F. USE_RELIABILITY_GATED_ENSEMBLE",
)


class RecentDataWalkForwardError(RuntimeError):
    """Raised when fixed input, chronology, reconciliation, or artifact integrity fails."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(_json_safe(value)))


def _manifest_sha(verified_gold: Mapping[str, Any]) -> str:
    return hashlib.sha256(Path(verified_gold["manifestPath"]).read_bytes()).hexdigest()


def _identity_inventory_sha256(values: Sequence[Any]) -> str:
    normalized = sorted({str(value) for value in values})
    if not normalized or any(not value.strip() for value in normalized):
        raise RecentDataWalkForwardError("frozen identity inventory is empty or blank")
    return hashlib.sha256(("\n".join(normalized) + "\n").encode("utf-8")).hexdigest()


def _implementation_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    relative_paths = (
        "server/sports_gold/recent_data_walk_forward.py",
        "server/sports_gold/walk_forward_state.py",
        "server/sports_gold/walk_forward_ensemble.py",
        "server/sports_gold/walk_forward_charts.py",
    )
    files: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = root / relative
        if not path.is_file():
            raise RecentDataWalkForwardError(f"implementation file missing: {relative}")
        size, digest = _sha_file(path)
        files.append({"relativePath": relative, "bytes": size, "sha256": digest})
    return {
        "files": files,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": sklearn.__version__,
    }


def _prepare_frame(verified_gold: Mapping[str, Any]) -> pd.DataFrame:
    columns = [
        "canonicalPaId",
        "plate_appearance_id",
        "canonicalGameId",
        "game_id",
        "game_date",
        "season",
        "outcome",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
        "datasetRole",
        *DIRECT_FEATURES,
    ]
    frame = pq.read_table(Path(verified_gold["path"]), columns=columns).to_pandas()
    if len(frame) != EXPECTED_GOLD_TOTAL_ROWS:
        raise RecentDataWalkForwardError("Gold row count differs from frozen Gold V1")
    seasons = pd.to_numeric(frame["season"], errors="raise").astype(np.int64)
    observed = {
        int(key): int(value)
        for key, value in seasons.value_counts().sort_index().items()
    }
    if observed != dict(EXPECTED_GOLD_SEASON_ROWS) or set(observed) != {
        2021,
        2022,
        2023,
        2024,
    }:
        raise RecentDataWalkForwardError(f"Gold season population differs: {observed}")
    dates = pd.to_datetime(frame["game_date"], format="%Y-%m-%d", errors="raise")
    if not np.array_equal(dates.dt.year.to_numpy(dtype=np.int64), seasons.to_numpy()):
        raise RecentDataWalkForwardError("Gold game_date and season disagree")
    for column in (
        "canonicalPaId",
        "plate_appearance_id",
        "canonicalGameId",
        "game_id",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
    ):
        if (
            frame[column].isna().any()
            or frame[column].astype(str).str.strip().eq("").any()
        ):
            raise RecentDataWalkForwardError(f"Gold identity is missing: {column}")
    if (
        frame["canonicalPaId"].duplicated().any()
        or frame["plate_appearance_id"].duplicated().any()
    ):
        raise RecentDataWalkForwardError("Gold PA identities are duplicated")
    encode_labels(frame["outcome"].to_numpy(copy=False), class_order=PA_CLASS_ORDER)
    return frame


def _verify_silver_binding(
    *,
    silver_root: Path,
    verified_gold: Mapping[str, Any],
) -> dict[str, Any]:
    gold_manifest = json.loads(
        Path(verified_gold["manifestPath"]).read_text(encoding="utf-8")
    )
    expected = (
        (gold_manifest.get("sourceInputs") or {}).get("currentSilver") or {}
    ).get(SILVER_TABLE)
    if not isinstance(expected, Mapping):
        raise RecentDataWalkForwardError("Gold-bound Silver PA authority is missing")
    current = resolve_current_silver(Path(silver_root), SILVER_TABLE)
    identity = current.identity()
    if identity != dict(expected):
        raise RecentDataWalkForwardError(
            "current Silver PA identity differs from Gold sourceInputs.currentSilver"
        )
    return {
        "identity": identity,
        "quarantine": "QUARANTINED",
        "selectable": False,
        "modelEligible": False,
        "approvedForTraining": False,
        "studyUse": (
            "VERIFIED_CANONICAL_IDENTITY_DATE_SOURCE_AUTHORITY_ALREADY_BOUND_INTO_GOLD"
        ),
        "targetHistory": "EXACT_GOLD_OUTCOME_ROWS_ONLY",
        "unmatchedSilverProjection": False,
        "silver2019To2020PaEventCrosswalkCreated": False,
    }


def _validate_frozen_split(
    holdout: FrozenHoldout,
    folds: Sequence[tuple[WalkForwardFold, np.ndarray, np.ndarray]],
) -> None:
    if (
        holdout.start_date != EXPECTED_HOLDOUT_START
        or holdout.end_date != EXPECTED_HOLDOUT_END
        or holdout.row_count != EXPECTED_HOLDOUT_ROWS
        or holdout.game_count != EXPECTED_HOLDOUT_GAMES
    ):
        raise RecentDataWalkForwardError(f"holdout differs: {holdout.record()}")
    if len(folds) != len(EXPECTED_FOLDS):
        raise RecentDataWalkForwardError("walk-forward fold count differs")
    for (fold, training, validation), expected in zip(
        folds, EXPECTED_FOLDS, strict=True
    ):
        observed = {
            "foldId": fold.fold_id,
            "trainEnd": fold.train_end,
            "trainingRows": int(training.sum()),
            "validationStart": fold.validation_start,
            "validationEnd": fold.validation_end,
            "validationRows": int(validation.sum()),
        }
        if observed != expected:
            raise RecentDataWalkForwardError(
                f"{fold.fold_id} differs: observed={observed}, expected={expected}"
            )
    if sum(int(validation.sum()) for _, _, validation in folds) != EXPECTED_OOF_ROWS:
        raise RecentDataWalkForwardError("walk-forward OOF row reconciliation differs")


def _request(
    *,
    verified_gold: Mapping[str, Any],
    silver_authority: Mapping[str, Any],
    holdout: FrozenHoldout,
    holdout_identity: Mapping[str, Any],
    folds: Sequence[tuple[WalkForwardFold, np.ndarray, np.ndarray]],
    implementation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "goldDatasetVersionId": verified_gold["datasetVersionId"],
        "goldLogicalContentSha256": verified_gold["logicalContentSha256"],
        "goldManifestSha256": _manifest_sha(verified_gold),
        "silverPlateAppearanceAuthority": dict(silver_authority),
        "silverHistoryBoundary": {
            "verifiedAuthorityOnly": True,
            "outcomeHistorySource": "EXACT_GOLD_TARGET_ROWS",
            "unmatchedOr2019To2020PaEventProjection": False,
        },
        "classOrder": list(PA_CLASS_ORDER),
        "base22FeatureOrder": list(BASE_FEATURES),
        "direct48FeatureOrder": list(DIRECT_FEATURES),
        "holdout": holdout.record(),
        "holdoutIdentity": dict(holdout_identity),
        "folds": [fold.record() for fold, _, _ in folds],
        "expectedOofRows": EXPECTED_OOF_ROWS,
        "expectedFinalTrainingRows": EXPECTED_FINAL_TRAINING_ROWS,
        "components": list(WALK_FORWARD_COMPONENT_ORDER),
        "fixedEnsembles": fixed_walk_forward_ensemble_definitions(),
        "optimizedEnsembles": {
            "E9": "ALL_COMPONENT_NONNEGATIVE_CONVEX_OOF_ONLY",
            "E10": "FIXED_RELIABILITY_GATED_MULTINOMIAL_LOGISTIC_OOF_ONLY",
        },
        "residualExpectationLedger": {
            "assignment": "SEQUENTIAL_CHRONOLOGICAL_WALK_FORWARD",
            "randomCrossFit": False,
            "initial2021ResidualAvailability": False,
            "oofCoverageStart": EXPECTED_FOLDS[0]["validationStart"],
            "oofCoverageEnd": EXPECTED_FOLDS[-1]["validationEnd"],
        },
        "recommendations": list(RECOMMENDATIONS),
        "implementation": dict(implementation),
        "promotionRequested": False,
        "bronzeRebuildRequested": False,
        "silverRebuildRequested": False,
        "goldRebuildRequested": False,
        "prohibitedSeasons": [2025, 2026],
    }


def _fit_logistic(
    frame: pd.DataFrame,
    training_mask: np.ndarray,
    *,
    model_id: str,
    feature_names: tuple[str, ...],
) -> tuple[FittedFixedModel, dict[str, Any]]:
    if (
        training_mask.dtype != np.bool_
        or training_mask.shape != (len(frame),)
        or not training_mask.any()
    ):
        raise ValueError("logistic training mask must be non-empty aligned bool data")
    values = {name: frame[name].to_numpy(copy=False) for name in feature_names}
    labels = encode_labels(
        frame["outcome"].to_numpy(copy=False), class_order=PA_CLASS_ORDER
    )
    preprocessor = FoldPreprocessor.fit(values, feature_names, training_mask)
    matrix = preprocessor.transform(values, training_mask)
    estimator = LogisticRegression(
        C=float(LOGISTIC_CONFIG["C"]),
        penalty=str(LOGISTIC_CONFIG["penalty"]),
        solver=str(LOGISTIC_CONFIG["solver"]),
        max_iter=int(LOGISTIC_CONFIG["maxIter"]),
        tol=float(LOGISTIC_CONFIG["tolerance"]),
        fit_intercept=bool(LOGISTIC_CONFIG["fitIntercept"]),
        class_weight=LOGISTIC_CONFIG["classWeight"],
        random_state=LOGISTIC_CONFIG["randomState"],
    )
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(matrix, labels[training_mask])
    elapsed = float(time.perf_counter() - started)
    convergence = [
        item for item in observed if issubclass(item.category, ConvergenceWarning)
    ]
    if convergence or np.any(
        np.asarray(estimator.n_iter_) >= int(LOGISTIC_CONFIG["maxIter"])
    ):
        raise RecentDataWalkForwardError(f"{model_id} failed to converge")
    if not np.array_equal(
        np.asarray(estimator.classes_, dtype=np.int64),
        np.arange(len(PA_CLASS_ORDER), dtype=np.int64),
    ):
        raise RecentDataWalkForwardError(f"{model_id} class order differs")
    artifact = FittedFixedModel(
        model_id=model_id,
        estimator=estimator,
        preprocessor=preprocessor,
        feature_names=feature_names,
        effective_config={**LOGISTIC_CONFIG, "featureCount": len(feature_names)},
    )
    return artifact, {
        "modelId": model_id,
        "featureCount": len(feature_names),
        "trainingRows": int(training_mask.sum()),
        "fitSeconds": elapsed,
        "iterations": np.asarray(estimator.n_iter_, dtype=np.int64).tolist(),
        "warnings": [
            {"category": item.category.__name__, "message": str(item.message)}
            for item in observed
        ],
    }


def _null_probabilities(
    labels: np.ndarray, training: np.ndarray, rows: int
) -> np.ndarray:
    encoded = encode_labels(labels[training], class_order=PA_CLASS_ORDER)
    counts = np.bincount(encoded, minlength=len(PA_CLASS_ORDER)).astype(np.float64)
    frequencies = counts / counts.sum()
    return np.repeat(frequencies[None, :], rows, axis=0)


def _null_fit_record(probabilities: np.ndarray, training_rows: int) -> dict[str, Any]:
    frequencies = np.asarray(probabilities[0], dtype=np.float64)
    return {
        "modelId": "class_frequency_null",
        "trainingRows": int(training_rows),
        "classOrder": list(PA_CLASS_ORDER),
        "classFrequencies": {
            name: float(frequencies[index]) for index, name in enumerate(PA_CLASS_ORDER)
        },
        "fixedWithinScoreBlock": True,
    }


def _float64_array_sha256(values: Any) -> str:
    array = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    if not np.isfinite(array).all():
        raise RecentDataWalkForwardError("frozen meta-model values are non-finite")
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _meta_model_fingerprint(e9: Any, e10: Any) -> dict[str, Any]:
    parts = {
        "e9Weights": np.asarray(e9.weights, dtype=np.float64),
        "e10Coefficients": np.asarray(e10.estimator.coef_, dtype=np.float64),
        "e10Intercept": np.asarray(e10.estimator.intercept_, dtype=np.float64),
        "e10ScalerMean": np.asarray(e10.scaler.mean_, dtype=np.float64),
        "e10ScalerScale": np.asarray(e10.scaler.scale_, dtype=np.float64),
    }
    digests = {name: _float64_array_sha256(value) for name, value in parts.items()}
    combined = hashlib.sha256(
        canonical_json_bytes({name: digests[name] for name in sorted(digests)})
    ).hexdigest()
    return {
        "schemaVersion": "MLB_GOLD_WALK_FORWARD_FROZEN_META_MODEL_FINGERPRINT_V1",
        "parts": digests,
        "combinedSha256": combined,
    }


def _empty_reliability_parts() -> dict[str, dict[str, list[np.ndarray]]]:
    return {
        component: {field: [] for field in RELIABILITY_FIELDS}
        for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
    }


def _append_bundle(
    bundle: WalkForwardBlockBundle,
    *,
    component_parts: dict[str, list[np.ndarray]],
    reliability_parts: dict[str, dict[str, list[np.ndarray]]],
) -> None:
    for component, matrix in bundle.probability_matrices.items():
        component_parts[component].append(np.asarray(matrix, dtype=np.float64))
    for component, fields in bundle.reliability.items():
        for field, values in fields.items():
            reliability_parts[component][field].append(np.asarray(values))


def _join_reliability(
    parts: Mapping[str, Mapping[str, Sequence[np.ndarray]]]
) -> dict[str, dict[str, np.ndarray]]:
    return {
        component: {
            field: np.concatenate(values, axis=0) for field, values in fields.items()
        }
        for component, fields in parts.items()
    }


def _run_oof(
    frame: pd.DataFrame,
    folds: Sequence[tuple[WalkForwardFold, np.ndarray, np.ndarray]],
    *,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    rows = len(frame)
    labels_all = frame["outcome"].to_numpy(dtype=object, copy=False)
    dates = pd.to_datetime(frame["game_date"], format="%Y-%m-%d", errors="raise")
    initial_cutoff = (dates.min() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    ledger_probabilities = np.full(
        (rows, len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER), dtype=np.float64
    )
    ledger_available = np.zeros(rows, dtype=np.bool_)
    ledger_cutoffs = np.full(rows, initial_cutoff, dtype=object)
    component_parts = {name: [] for name in WALK_FORWARD_COMPONENT_ORDER}
    reliability_parts = _empty_reliability_parts()
    null_parts: list[np.ndarray] = []
    base_parts: list[np.ndarray] = []
    row_id_parts: list[np.ndarray] = []
    label_parts: list[np.ndarray] = []
    game_parts: list[np.ndarray] = []
    date_parts: list[np.ndarray] = []
    fold_records: list[dict[str, Any]] = []
    artifacts: dict[str, FittedFixedModel] = {}

    for fold, training, validation in folds:
        progress(
            f"{fold.fold_id}: fit null/Base22/Direct48 on {int(training.sum()):,}; "
            f"score {int(validation.sum()):,} daily"
        )
        available_before = int(ledger_available[training].sum())
        full_ledger = ChronologicalDirectLedger.aligned(
            frame,
            ledger_probabilities,
            ledger_cutoffs,
            availability=ledger_available,
        )
        base, base_fit = _fit_logistic(
            frame,
            training,
            model_id=f"{fold.fold_id.lower()}_base22",
            feature_names=BASE_FEATURES,
        )
        direct, direct_fit = _fit_logistic(
            frame,
            training,
            model_id=f"{fold.fold_id.lower()}_direct48",
            feature_names=DIRECT_FEATURES,
        )
        target = frame.loc[validation].reset_index(drop=True)
        direct_probabilities = direct.predict_proba(target)
        base_probabilities = base.predict_proba(target)
        null_probabilities = _null_probabilities(
            labels_all, training, int(validation.sum())
        )
        target_ledger = ChronologicalDirectLedger.aligned(
            target,
            direct_probabilities,
            fold.train_end,
            availability=np.ones(len(target), dtype=np.bool_),
        )
        engine = fit_walk_forward_state(frame, full_ledger, training_mask=training)
        block = score_walk_forward_block(engine, target, target_ledger)
        expected_ids = tuple(target["plate_appearance_id"].astype(str).tolist())
        if block.row_ids != expected_ids or block.scored_rows != int(validation.sum()):
            raise RecentDataWalkForwardError(
                f"{fold.fold_id} state row reconciliation differs"
            )
        if not np.array_equal(
            block.probability_matrices[DIRECT_GOLD], direct_probabilities
        ):
            raise RecentDataWalkForwardError(
                f"{fold.fold_id} state Direct probabilities differ"
            )
        _append_bundle(
            block,
            component_parts=component_parts,
            reliability_parts=reliability_parts,
        )
        null_parts.append(null_probabilities)
        base_parts.append(base_probabilities)
        row_id_parts.append(target["plate_appearance_id"].astype(str).to_numpy())
        label_parts.append(target["outcome"].to_numpy(dtype=object))
        game_parts.append(target["game_id"].astype(str).to_numpy(dtype=object))
        date_parts.append(target["game_date"].astype(str).to_numpy(dtype=object))

        ledger_probabilities[validation] = direct_probabilities
        ledger_available[validation] = True
        ledger_cutoffs[validation] = fold.train_end
        artifacts[f"{fold.fold_id}-base22"] = base
        artifacts[f"{fold.fold_id}-direct48"] = direct
        fold_records.append(
            {
                **fold.record(),
                "nullFit": _null_fit_record(null_probabilities, int(training.sum())),
                "base22Fit": base_fit,
                "direct48Fit": direct_fit,
                "residualLedger": {
                    "availableTrainingRowsBeforeFold": available_before,
                    "unavailableTrainingRowsBeforeFold": int(training.sum())
                    - available_before,
                    "appendedOofRows": int(validation.sum()),
                    "availableRowsAfterFold": int(ledger_available.sum()),
                    "assignment": "SEQUENTIAL_CHRONOLOGICAL",
                    "randomCrossFit": False,
                },
                "state": {
                    "archetypeFitEndDay": engine.archetype_fit_end_day,
                    "blockReconciliation": block.reconciliation,
                    "residualExpectationSource": block.residual_expectation_source,
                },
            }
        )

    oof_rows = sum(len(values) for values in row_id_parts)
    if (
        oof_rows != EXPECTED_OOF_ROWS
        or int(ledger_available.sum()) != EXPECTED_OOF_ROWS
    ):
        raise RecentDataWalkForwardError("combined OOF ledger row count differs")
    row_ids = np.concatenate(row_id_parts)
    if len(set(row_ids.tolist())) != EXPECTED_OOF_ROWS:
        raise RecentDataWalkForwardError("combined OOF row identities overlap")
    return {
        "rowIds": row_ids,
        "labels": np.concatenate(label_parts),
        "gameIds": np.concatenate(game_parts),
        "gameDates": np.concatenate(date_parts),
        "null": np.concatenate(null_parts, axis=0),
        "base": np.concatenate(base_parts, axis=0),
        "components": {
            component: np.concatenate(parts, axis=0)
            for component, parts in component_parts.items()
        },
        "reliability": _join_reliability(reliability_parts),
        "folds": fold_records,
        "artifacts": artifacts,
        "ledgerProbabilities": ledger_probabilities,
        "ledgerAvailability": ledger_available,
        "ledgerCutoffs": ledger_cutoffs,
        "initialUnavailableRows": int((dates < pd.Timestamp("2022-01-01")).sum()),
    }


def _candidate_mapping(
    *,
    null: np.ndarray,
    base: np.ndarray,
    components: Mapping[str, np.ndarray],
    e9: Any,
    e10: Any,
    reliability: Mapping[str, Mapping[str, np.ndarray]],
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    fixed = build_fixed_walk_forward_ensembles(components)
    ensembles = {
        **fixed,
        "E9": e9.predict_proba(components),
        "E10": e10.predict_proba(components, reliability),
    }
    candidates = {
        "CLASS_FREQUENCY_NULL": null,
        "MATCHED_BASE": base,
        DIRECT_GOLD: components[DIRECT_GOLD],
        **ensembles,
    }
    if tuple(candidates) != COMPARISON_CANDIDATE_IDS:
        raise RecentDataWalkForwardError("candidate inventory/order differs")
    return candidates, ensembles


def _leaderboard_table(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(row["candidateId"]): row for row in records}
    direct = float(by_id[DIRECT_GOLD]["metrics"]["logLoss"])
    null = float(by_id["CLASS_FREQUENCY_NULL"]["metrics"]["logLoss"])
    base = float(by_id["MATCHED_BASE"]["metrics"]["logLoss"])
    output: list[dict[str, Any]] = []
    for row in records:
        metrics = row["metrics"]
        value = float(metrics["logLoss"])
        output.append(
            {
                "candidateId": row["candidateId"],
                "rows": int(metrics["rowCount"]),
                "logLoss": value,
                "summedBrier": float(metrics["summedBrier"]),
                "ece": float(metrics["ece"]),
                "accuracy": float(metrics["accuracy"]),
                "macroF1": float(metrics["macroF1"]),
                "coverage": float(row["coverage"]),
                "effectiveSampleSizeMean": row["effectiveSampleSizeMean"],
                "logLossImprovementVsDirect": float(direct - value),
                "logLossImprovementVsNull": float(null - value),
                "logLossImprovementVsBase": float(base - value),
            }
        )
    return sorted(output, key=lambda row: float(row["logLoss"]))


def _component_table(
    labels: np.ndarray,
    components: Mapping[str, np.ndarray],
    reliability: Mapping[str, Mapping[str, np.ndarray]],
    *,
    benchmark_table: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    direct = compact_multiclass_metrics(labels, components[DIRECT_GOLD])
    benchmarks = {str(row["candidateId"]): row for row in benchmark_table}
    null_log_loss = float(benchmarks["CLASS_FREQUENCY_NULL"]["logLoss"])
    base_log_loss = float(benchmarks["MATCHED_BASE"]["logLoss"])
    rows: list[dict[str, Any]] = []
    for component in WALK_FORWARD_COMPONENT_ORDER:
        metrics = compact_multiclass_metrics(labels, components[component])
        if component == DIRECT_GOLD:
            coverage = 1.0
            covered = len(labels)
            effective_mean = None
            effective_median = None
        else:
            missing = np.asarray(
                reliability[component]["missingHistoryFlag"], dtype=np.bool_
            )
            effective = np.asarray(
                reliability[component]["effectiveSampleSize"], dtype=np.float64
            )
            available = ~missing
            coverage = float(available.mean())
            covered = int(available.sum())
            effective_mean = float(effective[available].mean()) if covered else None
            effective_median = (
                float(np.median(effective[available])) if covered else None
            )
        rows.append(
            {
                "componentId": component,
                "rows": len(labels),
                "coveredRows": covered,
                "coverage": coverage,
                "effectiveSampleSizeMean": effective_mean,
                "effectiveSampleSizeMedian": effective_median,
                "logLoss": metrics["logLoss"],
                "summedBrier": metrics["summedBrier"],
                "ece": metrics["ece"],
                "accuracy": metrics["accuracy"],
                "macroF1": metrics["macroF1"],
                "logLossImprovementVsDirect": float(
                    direct["logLoss"] - metrics["logLoss"]
                ),
                "logLossImprovementVsNull": float(null_log_loss - metrics["logLoss"]),
                "logLossImprovementVsBase": float(base_log_loss - metrics["logLoss"]),
            }
        )
    return sorted(rows, key=lambda row: float(row["logLoss"]))


def _all_method_table(
    candidate_table: Sequence[Mapping[str, Any]],
    component_table: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [
        *(
            dict(row)
            for row in candidate_table
            if row["candidateId"] in {"CLASS_FREQUENCY_NULL", "MATCHED_BASE"}
        ),
        *({**dict(row), "candidateId": row["componentId"]} for row in component_table),
        *(
            dict(row)
            for row in candidate_table
            if row["candidateId"] in WALK_FORWARD_ENSEMBLE_IDS
        ),
    ]
    expected = {
        "CLASS_FREQUENCY_NULL",
        "MATCHED_BASE",
        *WALK_FORWARD_COMPONENT_ORDER,
        *WALK_FORWARD_ENSEMBLE_IDS,
    }
    actual = [str(row["candidateId"]) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RecentDataWalkForwardError(
            "combined holdout method inventory is incomplete or duplicated"
        )
    return sorted(rows, key=lambda row: float(row["logLoss"]))


def _daily_candidate_table(
    labels: np.ndarray,
    dates: np.ndarray,
    candidates: Mapping[str, np.ndarray],
) -> list[dict[str, Any]]:
    return [
        {
            "scoreDate": row["scoreDate"],
            "candidateId": row["candidateId"],
            **row["metrics"],
            "logLossDifferenceVsDirect": row["logLossDifferenceVsDirect"],
        }
        for row in daily_metric_records(labels, dates, candidates)
    ]


def _daily_coverage(bundle: WalkForwardBlockBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in bundle.daily_bundles:
        for component in WALK_FORWARD_EMPIRICAL_COMPONENTS:
            estimate = day.components[component]
            available = ~np.asarray(estimate.missing_history, dtype=np.bool_)
            effective = np.asarray(estimate.effective_sample_size, dtype=np.float64)
            rows.append(
                {
                    "scoreDate": day.score_day,
                    "componentId": component,
                    "rows": len(day.row_ids),
                    "coveredRows": int(available.sum()),
                    "coverage": float(available.mean()),
                    "effectiveSampleSizeMean": (
                        float(effective[available].mean()) if available.any() else 0.0
                    ),
                    "missingRows": int((~available).sum()),
                }
            )
    return rows


def _select_ensemble(oof_table: Sequence[Mapping[str, Any]]) -> str:
    eligible = [
        row for row in oof_table if str(row["candidateId"]) in WALK_FORWARD_ENSEMBLE_IDS
    ]
    if len(eligible) != len(WALK_FORWARD_ENSEMBLE_IDS):
        raise RecentDataWalkForwardError("OOF ensemble inventory is incomplete")
    return str(min(eligible, key=lambda row: float(row["logLoss"]))["candidateId"])


def _recommendation(
    *,
    selected: str,
    oof_table: Sequence[Mapping[str, Any]],
    holdout_table: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    oof = {str(row["candidateId"]): row for row in oof_table}
    final = {str(row["candidateId"]): row for row in holdout_table}
    oof_improvement = float(oof[DIRECT_GOLD]["logLoss"] - oof[selected]["logLoss"])
    holdout_improvement = float(
        final[DIRECT_GOLD]["logLoss"] - final[selected]["logLoss"]
    )
    if oof_improvement <= 0.0 or holdout_improvement <= 0.0:
        decision = RECOMMENDATIONS[0]
    elif selected == "E1":
        decision = RECOMMENDATIONS[1]
    elif selected == "E2":
        decision = RECOMMENDATIONS[2]
    elif selected in {"E3", "E4"}:
        decision = RECOMMENDATIONS[3]
    elif selected in {"E5", "E9"}:
        decision = RECOMMENDATIONS[4]
    elif selected == "E10":
        decision = RECOMMENDATIONS[5]
    else:  # pragma: no cover - inventory assertion above makes this unreachable
        raise RecentDataWalkForwardError(f"unmapped ensemble selection: {selected}")
    return {
        "recommendation": decision,
        "selectedOofEnsemble": selected,
        "selectionCriterion": "MINIMUM_COMBINED_FIVE_FOLD_OOF_LOG_LOSS",
        "oofLogLossImprovementVsDirect": oof_improvement,
        "holdoutLogLossImprovementVsDirect": holdout_improvement,
        "holdoutUsedForWeightsOrSelection": False,
        "holdoutRequiredForAdoptionRecommendation": True,
        "researchOnly": True,
        "promotionRequested": False,
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [_json_safe(row) for row in rows]
    if not materialized:
        raise RecentDataWalkForwardError(f"table is empty: {path.name}")
    fields: list[str] = []
    for row in materialized:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {
                    field: (
                        json.dumps(value, sort_keys=True, separators=(",", ":"))
                        if isinstance(value, (dict, list))
                        else value
                    )
                    for field, value in row.items()
                }
            )


def _artifact_entry(path: Path, root: Path) -> dict[str, Any]:
    size, digest = _sha_file(path)
    return {
        "relativePath": path.relative_to(root).as_posix(),
        "bytes": size,
        "sha256": digest,
    }


def _verify_existing(final: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = final / "manifest.json"
    results_path = final / "results.json"
    if not manifest_path.is_file() or not results_path.is_file():
        raise RecentDataWalkForwardError("existing walk-forward artifact is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("request") != request or manifest.get("studySha256") != final.name:
        raise RecentDataWalkForwardError(
            "existing walk-forward request identity differs"
        )
    if (
        manifest.get("status") != "RESEARCH_ONLY"
        or manifest.get("promotionEligible") is not False
    ):
        raise RecentDataWalkForwardError("existing walk-forward governance differs")
    artifact_inventory = manifest.get("artifacts")
    if not isinstance(artifact_inventory, Mapping) or not artifact_inventory:
        raise RecentDataWalkForwardError("existing artifact inventory is missing")
    expected_files = set(artifact_inventory) | {"manifest.json"}
    actual_files = {
        path.relative_to(final).as_posix()
        for path in final.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise RecentDataWalkForwardError(
            "existing artifact inventory has missing or extra files"
        )
    for relative, entry in artifact_inventory.items():
        path = (final / relative).resolve()
        if final.resolve() not in path.parents or not path.is_file():
            raise RecentDataWalkForwardError(
                f"existing artifact is unsafe/missing: {relative}"
            )
        size, digest = _sha_file(path)
        if size != entry.get("bytes") or digest != entry.get("sha256"):
            raise RecentDataWalkForwardError(
                f"existing artifact bytes differ: {relative}"
            )
    if hashlib.sha256(results_path.read_bytes()).hexdigest() != manifest.get(
        "resultsSha256"
    ):
        raise RecentDataWalkForwardError("existing results hash differs")
    result = json.loads(results_path.read_text(encoding="utf-8"))
    result["artifactRoot"] = str(final)
    result["reused"] = True
    return result


def _report(result: Mapping[str, Any]) -> str:
    decision = result["decision"]
    holdout = result["request"]["holdout"]
    return "\n".join(
        (
            "# Phase 7B5 Recent-Data Walk-Forward Study",
            "",
            f"- Status: `{result['status']}`",
            f"- Holdout: `{holdout['startDate']}` through `{holdout['endDate']}` "
            f"({holdout['rowCount']:,} rows / {holdout['gameCount']:,} games)",
            f"- Combined walk-forward OOF rows: `{result['populations']['oofRows']:,}`",
            f"- OOF-selected ensemble: `{result['selectedOofEnsemble']}`",
            f"- Recommendation: `{decision['recommendation']}`",
            f"- OOF improvement vs Direct: `{decision['oofLogLossImprovementVsDirect']:.12f}`",
            f"- Holdout improvement vs Direct: "
            f"`{decision['holdoutLogLossImprovementVsDirect']:.12f}`",
            "- Promotion: `false`",
            "- 2025/2026 opened: `false`",
            "",
            "Silver supplies only the independently verified canonical identity/date/source "
            "authority already bound into Gold. Outcome history is exclusively the exact "
            "Gold target rows; no unmatched or 2019–2020 paEvent projection was created.",
            "",
            "RECENT_DATA_WALK_FORWARD_STUDY_COMPLETE",
            "",
        )
    )


def run_recent_data_walk_forward_study(
    *,
    gold_root: Path,
    silver_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run or verify/reuse the single fixed Phase 7B5 research study."""

    announce = progress or (lambda _message: None)
    gold_root = Path(gold_root).resolve()
    silver_root = Path(silver_root).resolve()
    announce("verify frozen Gold V1 and its exact current Silver PA authority")
    verified_before = verify_gold(gold_root)
    if verified_before["logicalContentSha256"] != FROZEN_GOLD_SHA256:
        raise RecentDataWalkForwardError(
            "current Gold object differs from frozen Gold V1"
        )
    gold_manifest_sha_before = _manifest_sha(verified_before)
    silver_authority = _verify_silver_binding(
        silver_root=silver_root, verified_gold=verified_before
    )
    frame = _prepare_frame(verified_before)
    verified_after_read = verify_gold(
        gold_root, object_sha=verified_before["logicalContentSha256"]
    )
    if _manifest_sha(verified_after_read) != gold_manifest_sha_before:
        raise RecentDataWalkForwardError(
            "Gold changed while the frame was materialized"
        )

    announce("freeze exact final holdout and five globally optimized PA folds")
    holdout, holdout_mask = freeze_final_holdout(frame)
    folds = five_equal_pa_walk_forward_folds(frame, holdout)
    _validate_frozen_split(holdout, folds)
    holdout_identity = {
        "plateAppearanceIdInventorySha256": _identity_inventory_sha256(
            frame.loc[holdout_mask, "plate_appearance_id"].tolist()
        ),
        "gameIdInventorySha256": _identity_inventory_sha256(
            frame.loc[holdout_mask, "game_id"].tolist()
        ),
        "plateAppearanceIdentityCount": int(holdout_mask.sum()),
        "gameIdentityCount": int(
            frame.loc[holdout_mask, "game_id"].astype(str).nunique()
        ),
    }
    if (
        holdout_identity["plateAppearanceIdInventorySha256"]
        != EXPECTED_HOLDOUT_PA_INVENTORY_SHA256
        or holdout_identity["gameIdInventorySha256"]
        != EXPECTED_HOLDOUT_GAME_INVENTORY_SHA256
    ):
        raise RecentDataWalkForwardError(
            f"frozen holdout identity inventory differs: {holdout_identity}"
        )
    final_training_mask = ~np.asarray(holdout_mask, dtype=np.bool_)
    if int(final_training_mask.sum()) != EXPECTED_FINAL_TRAINING_ROWS:
        raise RecentDataWalkForwardError("final pre-holdout training count differs")
    implementation = _implementation_identity()
    request = _request(
        verified_gold=verified_before,
        silver_authority=silver_authority,
        holdout=holdout,
        holdout_identity=holdout_identity,
        folds=folds,
        implementation=implementation,
    )
    study_sha = sha256_bytes(canonical_json_bytes(request))
    final = gold_root / "recent-data-walk-forward-studies" / "sha256" / study_sha
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return _verify_existing(final, request)

    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        # All fit operations begin only after the complete split is in request.
        _write_json(staging / "request.json", request)
        announce("run five chronological OOF folds with sequential residual ledger")
        oof = _run_oof(frame, folds, progress=announce)
        announce("fit E9 and E10 exactly once on combined five-fold OOF")
        e9 = fit_walk_forward_convex_blend(
            oof["labels"], oof["components"], oof["gameDates"], holdout
        )
        e10 = fit_walk_forward_stacker(
            oof["labels"],
            oof["components"],
            oof["reliability"],
            oof["gameDates"],
            holdout,
        )
        frozen_meta_before_holdout = _meta_model_fingerprint(e9, e10)
        oof_candidates, oof_ensembles = _candidate_mapping(
            null=oof["null"],
            base=oof["base"],
            components=oof["components"],
            e9=e9,
            e10=e10,
            reliability=oof["reliability"],
        )
        oof_records = evaluate_walk_forward_candidates(oof["labels"], oof_candidates)
        oof_table = _leaderboard_table(oof_records)
        selected = _select_ensemble(oof_table)

        announce(
            f"freeze {selected}; refit null/Base22/Direct48/state on all pre-holdout rows"
        )
        final_base, final_base_fit = _fit_logistic(
            frame,
            final_training_mask,
            model_id="final_preholdout_base22",
            feature_names=BASE_FEATURES,
        )
        final_direct, final_direct_fit = _fit_logistic(
            frame,
            final_training_mask,
            model_id="final_preholdout_direct48",
            feature_names=DIRECT_FEATURES,
        )
        holdout_frame = frame.loc[holdout_mask].reset_index(drop=True)
        holdout_labels = holdout_frame["outcome"].to_numpy(dtype=object)
        holdout_dates = holdout_frame["game_date"].astype(str).to_numpy(dtype=object)
        final_direct_probabilities = final_direct.predict_proba(holdout_frame)
        final_base_probabilities = final_base.predict_proba(holdout_frame)
        final_null_probabilities = _null_probabilities(
            frame["outcome"].to_numpy(dtype=object),
            final_training_mask,
            len(holdout_frame),
        )
        full_history_ledger = ChronologicalDirectLedger.aligned(
            frame,
            oof["ledgerProbabilities"],
            oof["ledgerCutoffs"],
            availability=oof["ledgerAvailability"],
        )
        final_engine = fit_walk_forward_state(
            frame, full_history_ledger, training_mask=final_training_mask
        )
        holdout_ledger = ChronologicalDirectLedger.aligned(
            holdout_frame,
            final_direct_probabilities,
            EXPECTED_FOLDS[-1]["validationEnd"],
            availability=np.ones(len(holdout_frame), dtype=np.bool_),
        )
        holdout_bundle = score_walk_forward_block(
            final_engine, holdout_frame, holdout_ledger
        )
        if (
            holdout_bundle.row_ids
            != tuple(holdout_frame["plate_appearance_id"].astype(str).tolist())
            or holdout_bundle.reconciliation["noRowsDropped"] is not True
        ):
            raise RecentDataWalkForwardError(
                "holdout daily state reconciliation differs"
            )
        holdout_components = holdout_bundle.probability_matrices
        holdout_reliability = holdout_bundle.reliability
        if not np.array_equal(
            holdout_components[DIRECT_GOLD], final_direct_probabilities
        ):
            raise RecentDataWalkForwardError("holdout Direct component differs")
        holdout_candidates, holdout_ensembles = _candidate_mapping(
            null=final_null_probabilities,
            base=final_base_probabilities,
            components=holdout_components,
            e9=e9,
            e10=e10,
            reliability=holdout_reliability,
        )
        frozen_meta_after_holdout = _meta_model_fingerprint(e9, e10)
        if frozen_meta_after_holdout != frozen_meta_before_holdout:
            raise RecentDataWalkForwardError(
                "E9/E10 coefficients changed during frozen holdout scoring"
            )
        holdout_records = evaluate_walk_forward_candidates(
            holdout_labels, holdout_candidates
        )
        holdout_table = _leaderboard_table(holdout_records)
        decision = _recommendation(
            selected=selected,
            oof_table=oof_table,
            holdout_table=holdout_table,
        )

        oof_components_table = _component_table(
            oof["labels"],
            oof["components"],
            oof["reliability"],
            benchmark_table=oof_table,
        )
        holdout_components_table = _component_table(
            holdout_labels,
            holdout_components,
            holdout_reliability,
            benchmark_table=holdout_table,
        )
        daily_candidates = _daily_candidate_table(
            holdout_labels, holdout_dates, holdout_candidates
        )
        daily_components = _daily_candidate_table(
            holdout_labels, holdout_dates, holdout_components
        )
        coverage_daily = _daily_coverage(holdout_bundle)
        e9_weights = dict(e9.record()["weights"])
        e10_importance = dict(e10.coefficient_importance()["componentImportance"])
        weights_table = [
            {
                "componentId": component,
                "e9Weight": float(e9_weights[component]),
                "e10CoefficientImportance": float(e10_importance[component]),
            }
            for component in WALK_FORWARD_COMPONENT_ORDER
        ]
        fixed_definitions = fixed_walk_forward_ensemble_definitions()
        component_inclusion_table: list[dict[str, Any]] = []
        for ensemble_id in WALK_FORWARD_ENSEMBLE_IDS:
            if ensemble_id in fixed_definitions:
                definition = fixed_definitions[ensemble_id]
                members = set(definition["memberIds"])
                fixed_weights = definition["weights"]
            else:
                members = set(WALK_FORWARD_COMPONENT_ORDER)
                fixed_weights = {}
            for component in WALK_FORWARD_COMPONENT_ORDER:
                component_inclusion_table.append(
                    {
                        "ensembleId": ensemble_id,
                        "componentId": component,
                        "included": component in members,
                        "fixedEqualWeight": fixed_weights.get(component),
                        "e9OptimizedWeight": (
                            float(e9_weights[component])
                            if ensemble_id == "E9"
                            else None
                        ),
                        "e10CoefficientImportance": (
                            float(e10_importance[component])
                            if ensemble_id == "E10"
                            else None
                        ),
                        "fitPopulation": (
                            "PRE_HOLDOUT_FIVE_FOLD_OOF"
                            if ensemble_id in {"E9", "E10"}
                            else "FIXED_NO_FIT"
                        ),
                    }
                )
        holdout_all_performance = _all_method_table(
            holdout_table, holdout_components_table
        )
        oof_all_performance = _all_method_table(oof_table, oof_components_table)
        tables: dict[str, list[dict[str, Any]]] = {
            "oof-candidate-performance": oof_table,
            "oof-all-method-performance": oof_all_performance,
            "candidate-performance": holdout_all_performance,
            "oof-ensemble-leaderboard": [
                row
                for row in oof_table
                if row["candidateId"] in WALK_FORWARD_ENSEMBLE_IDS
            ],
            "ensemble-leaderboard": [
                row
                for row in holdout_table
                if row["candidateId"] in WALK_FORWARD_ENSEMBLE_IDS
            ],
            "oof-standalone-components": oof_components_table,
            "holdout-standalone-components": holdout_components_table,
            "standalone-leaderboard": holdout_components_table,
            "daily-performance": daily_candidates,
            "daily-component-performance": daily_components,
            "coverage-by-date": coverage_daily,
            "component-inclusion": component_inclusion_table,
            "ensemble-weights-gating": weights_table,
        }

        announce("reverify Gold and current Silver authority after all scoring")
        verified_final = verify_gold(
            gold_root, object_sha=verified_before["logicalContentSha256"]
        )
        gold_manifest_sha_final = _manifest_sha(verified_final)
        if gold_manifest_sha_final != gold_manifest_sha_before:
            raise RecentDataWalkForwardError("Gold changed during walk-forward study")
        if (
            _verify_silver_binding(
                silver_root=silver_root, verified_gold=verified_final
            )
            != silver_authority
        ):
            raise RecentDataWalkForwardError("Silver PA authority changed during study")

        result: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "RESEARCH_ONLY_COMPLETE",
            "studySha256": study_sha,
            "request": request,
            "selectedOofEnsemble": selected,
            "decision": decision,
            "dataVerification": {
                "goldLogicalContentSha256": verified_before["logicalContentSha256"],
                "goldManifestSha256Before": gold_manifest_sha_before,
                "goldManifestSha256After": gold_manifest_sha_final,
                "silverPlateAppearanceAuthority": silver_authority,
                "seasonsOpened": [2021, 2022, 2023, 2024],
                "opened2025": False,
                "opened2026": False,
                "bronzeRebuilt": False,
                "silverRebuilt": False,
                "goldRebuilt": False,
                "goldAltered": False,
            },
            "populations": {
                "goldRows": len(frame),
                "initialPreOofRows": EXPECTED_FOLDS[0]["trainingRows"],
                "oofRows": EXPECTED_OOF_ROWS,
                "finalTrainingRows": int(final_training_mask.sum()),
                "holdoutRows": len(holdout_frame),
                "holdoutGames": holdout.game_count,
            },
            "folds": oof["folds"],
            "residualLedger": {
                "source": "SEQUENTIAL_CHRONOLOGICAL_DIRECT48_OOF",
                "randomCrossFit": False,
                "availablePreHoldoutRows": int(oof["ledgerAvailability"].sum()),
                "unavailableInitialRows": int(
                    final_training_mask.sum() - oof["ledgerAvailability"].sum()
                ),
                "availableRange": {
                    "start": EXPECTED_FOLDS[0]["validationStart"],
                    "end": EXPECTED_FOLDS[-1]["validationEnd"],
                },
            },
            "fitEvidence": {
                "finalNull": _null_fit_record(
                    final_null_probabilities, int(final_training_mask.sum())
                ),
                "finalBase22": final_base_fit,
                "finalDirect48": final_direct_fit,
                "e9": e9.record(),
                "e10": e10.record(),
                "metaModelFingerprintBeforeHoldout": frozen_meta_before_holdout,
                "metaModelFingerprintAfterHoldout": frozen_meta_after_holdout,
                "metaCoefficientsFrozenBeforeHoldout": True,
            },
            "oof": {
                "candidateLeaderboard": oof_table,
                "componentLeaderboard": oof_components_table,
            },
            "holdout": {
                "candidateLeaderboard": holdout_table,
                "componentLeaderboard": holdout_components_table,
                "dailyReconciliation": holdout_bundle.reconciliation,
            },
            "tables": tables,
            "promotionRequested": False,
            "limitations": [
                "The 2021 warm-up rows have no earlier walk-forward Direct48 residual expectation and therefore contribute ordinary state but not residual-form history.",
                "Silver provides verified identity/date/source authority only; labels remain exact Gold target rows.",
                "The final fourteen active dates are a single untouched research holdout, not promotion evidence.",
            ],
            "nextProposedExperiment": "Repeat the frozen daily walk-forward protocol on a future authorized season without changing its candidates.",
        }

        (staging / "models").mkdir()
        for artifact_id, artifact in oof["artifacts"].items():
            joblib.dump(
                artifact, staging / "models" / f"{artifact_id}.joblib", compress=3
            )
        joblib.dump(final_base, staging / "models" / "final-base22.joblib", compress=3)
        joblib.dump(
            final_direct, staging / "models" / "final-direct48.joblib", compress=3
        )
        joblib.dump(e9, staging / "models" / "e9-convex.joblib", compress=3)
        joblib.dump(e10, staging / "models" / "e10-stacker.joblib", compress=3)
        (staging / "predictions").mkdir()
        np.savez_compressed(
            staging / "predictions" / "walk-forward-oof.npz",
            rowIds=np.asarray(oof["rowIds"], dtype=str),
            labels=np.asarray(oof["labels"], dtype=str),
            null=oof["null"],
            base22=oof["base"],
            **{
                f"component__{name}": matrix
                for name, matrix in oof["components"].items()
            },
            **{f"ensemble__{name}": matrix for name, matrix in oof_ensembles.items()},
        )
        np.savez_compressed(
            staging / "predictions" / "walk-forward-oof-reliability.npz",
            **{
                f"{component}__{field}": values
                for component, fields in oof["reliability"].items()
                for field, values in fields.items()
            },
        )
        np.savez_compressed(
            staging / "predictions" / "final-holdout.npz",
            rowIds=holdout_frame["plate_appearance_id"].astype(str).to_numpy(),
            labels=np.asarray(holdout_labels, dtype=str),
            null=final_null_probabilities,
            base22=final_base_probabilities,
            **{
                f"component__{name}": matrix
                for name, matrix in holdout_components.items()
            },
            **{
                f"ensemble__{name}": matrix
                for name, matrix in holdout_ensembles.items()
            },
        )
        np.savez_compressed(
            staging / "predictions" / "final-holdout-reliability.npz",
            **{
                f"{component}__{field}": values
                for component, fields in holdout_reliability.items()
                for field, values in fields.items()
            },
        )
        for name, rows in tables.items():
            _write_csv(staging / "tables" / f"{name}.csv", rows)
        _write_json(staging / "fold-evidence.json", oof["folds"])
        result["artifactRoot"] = None
        announce("render four fixed walk-forward review charts")
        charts = generate_walk_forward_charts(result, staging / "charts")
        for chart in charts:
            for file_record in chart["files"]:
                path = Path(file_record.pop("path")).resolve()
                file_record["relativePath"] = path.relative_to(
                    staging.resolve()
                ).as_posix()
        result["charts"] = charts
        _write_json(staging / "results.json", result)
        (staging / "study-report.md").write_text(_report(result), encoding="utf-8")

        inventory: dict[str, Any] = {}
        for path in sorted(
            (item for item in staging.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(staging).as_posix(),
        ):
            inventory[path.relative_to(staging).as_posix()] = _artifact_entry(
                path, staging
            )
        _write_json(
            staging / "manifest.json",
            {
                "schemaVersion": SCHEMA_VERSION,
                "studySha256": study_sha,
                "request": request,
                "status": "RESEARCH_ONLY",
                "promotionEligible": False,
                "resultsSha256": inventory["results.json"]["sha256"],
                "artifacts": inventory,
            },
        )
        try:
            os.replace(staging, final)
        except OSError:
            final.mkdir(parents=False, exist_ok=False)
            for path in sorted(
                (item for item in staging.rglob("*") if item.is_file()),
                key=lambda item: item.relative_to(staging).as_posix(),
            ):
                destination = final / path.relative_to(staging)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            shutil.rmtree(staging)
        persisted = _verify_existing(final, request)
        persisted["reused"] = False
        return persisted
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


__all__ = [
    "EXPECTED_FINAL_TRAINING_ROWS",
    "EXPECTED_FOLDS",
    "EXPECTED_HOLDOUT_GAMES",
    "EXPECTED_HOLDOUT_ROWS",
    "EXPECTED_OOF_ROWS",
    "RECOMMENDATIONS",
    "RecentDataWalkForwardError",
    "SCHEMA_VERSION",
    "run_recent_data_walk_forward_study",
]
