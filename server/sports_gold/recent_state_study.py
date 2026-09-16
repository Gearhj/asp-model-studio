"""Phase 7B4 recent-state, matchup, and fixed-ensemble research study.

This is the sole orchestration layer for the Phase 7B4 experiment.  It reads
the already verified immutable Gold V1 object, authenticates the frozen Direct
Gold Logistic artifact, performs six development-only rolling-origin fits,
freezes E1--E10 from development OOF evidence, and scores the 2024 matched
population once.  It has no Bronze/Silver build path and no promotion path.

Large predictions, fitted research artifacts, and detailed evidence are
published beneath the external Gold root in a request-addressed directory.
Small review tables, reports, and charts can then be copied into Git without
placing row-level data or model artifacts in the repository.
"""

from __future__ import annotations

import csv
import hashlib
import io
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
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    validate_probability_matrix,
)
from server.sports_modeling.training import FoldPreprocessor

from . import binary_hierarchical as BH
from .contracts import (
    EXPECTED_GOLD_DEVELOPMENT_ROWS,
    EXPECTED_GOLD_SEASON_ROWS,
    EXPECTED_GOLD_TOTAL_ROWS,
    EXPECTED_GOLD_VALIDATION_ROWS,
    GOLD_FEATURES,
)
from .models import FittedFixedModel, LOGISTIC_CONFIG, _aligned_probability_matrix
from .publication import verify_gold
from .recent_state_charts import generate_review_charts
from .recent_state_components import (
    CLUSTER_MATCHUP,
    COMPONENT_ORDER,
    DECAY_180_DAY_STATE,
    DECAY_365_DAY_STATE,
    DIRECT_MODEL,
    EMPIRICAL_COMPONENT_ORDER,
    LONG_TERM_STATE,
    RECENT_14_DAY_STATE,
    RECENT_42_DAY_STATE,
    RECENT_RESIDUAL_FORM,
    SHRUNK_EXACT_BVP,
    StateComponentBundle,
    fit_state_authority,
    score_state_components,
)
from .recent_state_ensemble import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    FIXED_ENSEMBLE_MEMBERS,
    ROLLING_ORIGIN_FOLDS,
    bounded_slice_evaluation,
    build_fixed_ensembles,
    compact_game_bootstrap,
    compact_multiclass_metrics,
    component_disagreement,
    component_leaderboard,
    ensemble_leaderboard,
    fit_convex_blend,
    fit_reliability_gated_stacker,
    fixed_ensemble_definitions,
    rolling_origin_fold_masks,
    select_oof_winner,
)


SCHEMA_VERSION = "MLB_GOLD_RECENT_STATE_MATCHUP_ENSEMBLE_STUDY_V1"
DIRECT_GOLD_REFERENCE_LOG_LOSS = 1.4778808498644482
DEVELOPMENT_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
RANDOM_SEED = 20_260_824
EXPECTED_OOF_FOLD_ROWS: Mapping[str, int] = {
    "FOLD_1": 59_830,
    "FOLD_2": 58_693,
    "FOLD_3": 33_799,
    "FOLD_4": 60_330,
    "FOLD_5": 58_399,
    "FOLD_6": 31_209,
}
EXPECTED_OOF_ROWS = sum(EXPECTED_OOF_FOLD_ROWS.values())
RECOMMENDATIONS: tuple[str, ...] = (
    "A. KEEP_DIRECT_GOLD_ONLY",
    "B. ADD_RECENT_STATE_OVERLAY",
    "C. ADD_CLUSTER_MATCHUP_OVERLAY",
    "D. ADOPT_STATIC_ENSEMBLE",
    "E. ADOPT_RELIABILITY_GATED_ENSEMBLE",
)


class RecentStateStudyError(RuntimeError):
    """Raised when a frozen input, temporal boundary, or result is invalid."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sha_file(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _verified_manifest_sha(verified_gold: Mapping[str, Any]) -> str:
    return hashlib.sha256(Path(verified_gold["manifestPath"]).read_bytes()).hexdigest()


def _artifact_entry(path: Path, *, root: Path) -> dict[str, Any]:
    size, digest = _sha_file(path)
    return {
        "relativePath": path.relative_to(root).as_posix(),
        "bytes": size,
        "sha256": digest,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(_json_safe(value)))


def _implementation_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    relative_paths = (
        "server/sports_gold/recent_state_study.py",
        "server/sports_gold/recent_state_components.py",
        "server/sports_gold/recent_state_ensemble.py",
        "server/sports_gold/recent_state_charts.py",
    )
    files: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = root / relative
        size, digest = _sha_file(path)
        files.append({"relativePath": relative, "bytes": size, "sha256": digest})
    return {
        "files": files,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": __import__("sklearn").__version__,
    }


def _study_request(
    verified_gold: Mapping[str, Any], implementation: Mapping[str, Any]
) -> dict[str, Any]:
    gold_manifest = json.loads(
        Path(verified_gold["manifestPath"]).read_text(encoding="utf-8")
    )
    source_inputs = gold_manifest.get("sourceInputs")
    if not isinstance(source_inputs, Mapping) or not source_inputs:
        raise RecentStateStudyError("Gold source-input authority is missing")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "goldDatasetVersionId": verified_gold["datasetVersionId"],
        "goldLogicalContentSha256": verified_gold["logicalContentSha256"],
        "goldManifestSha256": _verified_manifest_sha(verified_gold),
        "verifiedSourceInputs": dict(source_inputs),
        "sourceDirectExperimentSha256": BH.TRUSTED_MULTICLASS_EXPERIMENT_SHA256,
        "sourceDirectModel": "gold_logistic",
        "directReferenceLogLoss": DIRECT_GOLD_REFERENCE_LOG_LOSS,
        "classOrder": list(PA_CLASS_ORDER),
        "featureOrder": list(GOLD_FEATURES),
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "developmentRows": EXPECTED_GOLD_DEVELOPMENT_ROWS,
        "validationSeason": VALIDATION_SEASON,
        "validationRows": EXPECTED_GOLD_VALIDATION_ROWS,
        "rollingOriginFolds": [item.record() for item in ROLLING_ORIGIN_FOLDS],
        "expectedOofFoldRows": dict(EXPECTED_OOF_FOLD_ROWS),
        "expectedOofRows": EXPECTED_OOF_ROWS,
        "components": list(COMPONENT_ORDER),
        "fixedEnsembles": fixed_ensemble_definitions(),
        "optimizedEnsembles": {
            "E9": "OOF_NONNEGATIVE_CONVEX_BLEND",
            "E10": "OOF_REGULARIZED_MULTINOMIAL_RELIABILITY_STACKER",
        },
        "residualExpectationCrossFit": {
            "folds": 2,
            "assignmentUnit": "game_id",
            "assignment": "SHA256_UTF8_GAME_ID_LOW_BIT",
            "heldOutGameNeverAppearsInItsExpectationModel": True,
            "allFitRowsEarlierThanOuterValidationBlock": True,
        },
        "exactBvpPriorStrength": 50.0,
        "batterArchetypes": 6,
        "pitcherArchetypes": 6,
        "bootstrap": {
            "unit": "game_id",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "paired": True,
        },
        "implementation": dict(implementation),
        "randomSeed": RANDOM_SEED,
        "promotionRequested": False,
        "dataRebuildRequested": False,
        "prohibitedSeasons": [2025, 2026],
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
        *GOLD_FEATURES,
    ]
    frame = pq.read_table(Path(verified_gold["path"]), columns=columns).to_pandas()
    if len(frame) != EXPECTED_GOLD_TOTAL_ROWS:
        raise RecentStateStudyError("Gold row count differs from the frozen contract")
    observed = {
        int(key): int(value)
        for key, value in frame["season"].value_counts().sort_index().items()
    }
    if observed != dict(EXPECTED_GOLD_SEASON_ROWS) or set(observed) != {2021, 2022, 2023, 2024}:
        raise RecentStateStudyError(f"Gold season population differs: {observed}")
    for name in (
        "canonicalPaId",
        "plate_appearance_id",
        "canonicalGameId",
        "game_id",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
    ):
        values = frame[name].astype(str)
        if frame[name].isna().any() or (values.str.strip() == "").any():
            raise RecentStateStudyError(f"Gold identity {name} is missing")
    if frame["canonicalPaId"].duplicated().any() or frame["plate_appearance_id"].duplicated().any():
        raise RecentStateStudyError("Gold PA identities are duplicated")
    dates = pd.to_datetime(frame["game_date"], format="%Y-%m-%d", errors="raise")
    seasons = frame["season"].to_numpy(dtype=np.int64, copy=False)
    if not np.array_equal(dates.dt.year.to_numpy(dtype=np.int64), seasons):
        raise RecentStateStudyError("Gold season and game_date disagree")
    if any(int(value) in {2025, 2026} for value in np.unique(seasons)):
        raise RecentStateStudyError("prohibited 2025/2026 rows entered Phase 7B4")
    roles = frame["datasetRole"].astype(str).to_numpy(dtype=object)
    expected_roles = np.where(seasons == 2024, "VALIDATION", "DEVELOPMENT")
    if not np.array_equal(roles, expected_roles):
        raise RecentStateStudyError("Gold datasetRole differs from frozen split")
    encode_labels(frame["outcome"].to_numpy(copy=False), class_order=PA_CLASS_ORDER)
    return frame


def _fit_fold_direct(
    frame: pd.DataFrame, training_mask: np.ndarray
) -> tuple[FittedFixedModel, dict[str, Any]]:
    values = {name: frame[name].to_numpy(copy=False) for name in GOLD_FEATURES}
    labels = encode_labels(frame["outcome"].to_numpy(copy=False), class_order=PA_CLASS_ORDER)
    preprocessor = FoldPreprocessor.fit(values, tuple(GOLD_FEATURES), training_mask)
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
        warnings.simplefilter("always")
        estimator.fit(matrix, labels[training_mask])
    elapsed = float(time.perf_counter() - started)
    convergence = [item for item in observed if issubclass(item.category, ConvergenceWarning)]
    if convergence:
        raise RecentStateStudyError(
            f"fold Direct Logistic did not converge: {[str(item.message) for item in convergence]}"
        )
    expected_classes = np.arange(len(PA_CLASS_ORDER), dtype=np.int64)
    if not np.array_equal(np.asarray(estimator.classes_, dtype=np.int64), expected_classes):
        raise RecentStateStudyError("fold Direct Logistic class order differs")
    artifact = FittedFixedModel(
        model_id="fold_safe_gold_logistic",
        estimator=estimator,
        preprocessor=preprocessor,
        feature_names=tuple(GOLD_FEATURES),
        effective_config=dict(LOGISTIC_CONFIG),
    )
    return artifact, {
        "fitSeconds": elapsed,
        "trainingRows": int(training_mask.sum()),
        "estimatorIterations": np.asarray(estimator.n_iter_, dtype=np.int64).tolist(),
        "warnings": [
            {"category": item.category.__name__, "message": str(item.message)}
            for item in observed
        ],
    }


def _cross_fitted_history_direct(
    frame: pd.DataFrame, training_mask: np.ndarray
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, FittedFixedModel]]:
    """Return two-fold whole-game OOF Direct expectations for state residuals.

    Every selected historical PA is scored by a Direct model whose fit excludes
    that PA's entire game.  The caller's outer training mask is already bounded
    strictly before its validation block, so no 2024 or outer-validation row can
    enter either cross-fit model.
    """

    if training_mask.dtype != np.bool_ or training_mask.shape != (len(frame),):
        raise TypeError("history cross-fit mask must be aligned boolean data")
    if not training_mask.any():
        raise RecentStateStudyError("history cross-fit has no training rows")
    game_ids = frame["game_id"].astype(str).to_numpy(dtype=object)
    assignments = np.asarray(
        [hashlib.sha256(value.encode("utf-8")).digest()[0] & 1 for value in game_ids],
        dtype=np.int8,
    )
    probabilities = np.full(
        (len(frame), len(PA_CLASS_ORDER)),
        1.0 / len(PA_CLASS_ORDER),
        dtype=np.float64,
    )
    filled = np.zeros(len(frame), dtype=bool)
    records: list[dict[str, Any]] = []
    artifacts: dict[str, FittedFixedModel] = {}
    for held_out_fold in (0, 1):
        held_out = training_mask & (assignments == held_out_fold)
        fit_mask = training_mask & (assignments != held_out_fold)
        if not held_out.any() or not fit_mask.any():
            raise RecentStateStudyError("history Direct cross-fit has an empty fold")
        if set(game_ids[held_out].tolist()).intersection(game_ids[fit_mask].tolist()):
            raise RecentStateStudyError("history Direct cross-fit split one game")
        artifact, fit_record = _fit_fold_direct(frame, fit_mask)
        scored = artifact.predict_proba(frame.loc[held_out].reset_index(drop=True))
        probabilities[held_out] = scored
        filled[held_out] = True
        artifact_id = f"history-crossfit-{held_out_fold}"
        artifacts[artifact_id] = artifact
        records.append(
            {
                "crossFitFold": held_out_fold,
                "assignmentUnit": "game_id",
                "fitRows": int(fit_mask.sum()),
                "fitGames": int(len(set(game_ids[fit_mask].tolist()))),
                "heldOutRows": int(held_out.sum()),
                "heldOutGames": int(len(set(game_ids[held_out].tolist()))),
                "fit": fit_record,
            }
        )
    if not np.array_equal(filled, training_mask):
        raise RecentStateStudyError("history Direct cross-fit did not score every training row")
    validate_probability_matrix(probabilities[training_mask], class_order=PA_CLASS_ORDER)
    return probabilities, records, artifacts


def _append_bundle(
    bundle: StateComponentBundle,
    *,
    component_parts: dict[str, list[np.ndarray]],
    reliability_parts: dict[str, dict[str, list[np.ndarray]]],
    batter_parts: dict[str, list[np.ndarray]],
    pitcher_parts: dict[str, list[np.ndarray]],
) -> None:
    for name, matrix in bundle.probability_matrices.items():
        component_parts[name].append(np.asarray(matrix, dtype=np.float64))
    for component, fields in bundle.reliability.items():
        for field, values in fields.items():
            reliability_parts[component][field].append(np.asarray(values))
    for name, matrix in bundle.batter_only_probabilities.items():
        batter_parts.setdefault(name, []).append(np.asarray(matrix, dtype=np.float64))
    for name, matrix in bundle.pitcher_only_probabilities.items():
        pitcher_parts.setdefault(name, []).append(np.asarray(matrix, dtype=np.float64))


def _concatenate_nested(
    values: Mapping[str, Mapping[str, Sequence[np.ndarray]]]
) -> dict[str, dict[str, np.ndarray]]:
    return {
        component: {
            field: np.concatenate(parts, axis=0)
            for field, parts in fields.items()
        }
        for component, fields in values.items()
    }


def _run_development_oof(
    development: pd.DataFrame,
    *,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    masks = rolling_origin_fold_masks(development["game_date"].to_numpy(copy=False))
    component_parts = {name: [] for name in COMPONENT_ORDER}
    reliability_parts = {
        component: {
            field: []
            for field in (
                "observationCount",
                "effectiveSampleSize",
                "missingHistoryFlag",
                "daysSincePriorAppearance",
                "entropy",
                "deviationFromLongTerm",
            )
        }
        for component in EMPIRICAL_COMPONENT_ORDER
    }
    batter_parts: dict[str, list[np.ndarray]] = {}
    pitcher_parts: dict[str, list[np.ndarray]] = {}
    row_ids: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    games: list[np.ndarray] = []
    dates: list[np.ndarray] = []
    batters: list[np.ndarray] = []
    pitchers: list[np.ndarray] = []
    fold_records: list[dict[str, Any]] = []
    fold_artifacts: dict[str, FittedFixedModel] = {}

    for fold, training_full, validation_full in masks:
        expected = EXPECTED_OOF_FOLD_ROWS[fold.fold_id]
        if int(validation_full.sum()) != expected:
            raise RecentStateStudyError(
                f"{fold.fold_id} validation rows {int(validation_full.sum())} != {expected}"
            )
        selected = training_full | validation_full
        local = development.loc[selected].reset_index(drop=True)
        training = training_full[selected]
        validation = validation_full[selected]
        progress(
            f"{fold.fold_id}: fit Direct/state on {int(training.sum()):,}; "
            f"score {int(validation.sum()):,}"
        )
        direct_artifact, direct_fit = _fit_fold_direct(local, training)
        direct_all = direct_artifact.predict_proba(local)
        history_direct, history_crossfit, history_artifacts = _cross_fitted_history_direct(
            local, training
        )
        authority = fit_state_authority(
            local, history_direct, training_mask=training
        )
        bundle = score_state_components(
            authority, local, direct_all, target_mask=validation
        )
        expected_ids = tuple(
            local.loc[validation, "plate_appearance_id"].astype(str).tolist()
        )
        if bundle.row_ids != expected_ids:
            raise RecentStateStudyError(f"{fold.fold_id} component row order differs")
        _append_bundle(
            bundle,
            component_parts=component_parts,
            reliability_parts=reliability_parts,
            batter_parts=batter_parts,
            pitcher_parts=pitcher_parts,
        )
        row_ids.append(np.asarray(expected_ids, dtype=object))
        labels.append(local.loc[validation, "outcome"].to_numpy(dtype=object))
        games.append(local.loc[validation, "game_id"].astype(str).to_numpy(dtype=object))
        dates.append(local.loc[validation, "game_date"].astype(str).to_numpy(dtype=object))
        batters.append(
            local.loc[validation, "batterCanonicalPlayerId"].astype(str).to_numpy(dtype=object)
        )
        pitchers.append(
            local.loc[validation, "pitcherCanonicalPlayerId"].astype(str).to_numpy(dtype=object)
        )
        fold_artifacts[fold.fold_id] = direct_artifact
        for artifact_id, artifact in history_artifacts.items():
            fold_artifacts[f"{fold.fold_id}-{artifact_id}"] = artifact
        fold_records.append(
            {
                **fold.record(),
                "trainingRows": int(training.sum()),
                "validationRows": int(validation.sum()),
                "stateTrainingEndDay": bundle.training_end_day,
                "stateTargetStartDay": bundle.target_start_day,
                "stateTargetEndDay": bundle.target_end_day,
                "directFit": direct_fit,
                "residualExpectationCrossFit": history_crossfit,
            }
        )

    oof_rows = sum(len(part) for part in row_ids)
    if oof_rows != EXPECTED_OOF_ROWS:
        raise RecentStateStudyError(f"OOF rows {oof_rows} != {EXPECTED_OOF_ROWS}")
    joined_ids = np.concatenate(row_ids)
    if len(set(joined_ids.tolist())) != oof_rows:
        raise RecentStateStudyError("OOF row identities overlap across rolling blocks")
    return {
        "rowIds": joined_ids,
        "labels": np.concatenate(labels),
        "gameIds": np.concatenate(games),
        "gameDates": np.concatenate(dates),
        "batterIds": np.concatenate(batters),
        "pitcherIds": np.concatenate(pitchers),
        "components": {
            name: np.concatenate(parts, axis=0)
            for name, parts in component_parts.items()
        },
        "reliability": _concatenate_nested(reliability_parts),
        "batterDiagnostics": {
            name: np.concatenate(parts, axis=0) for name, parts in batter_parts.items()
        },
        "pitcherDiagnostics": {
            name: np.concatenate(parts, axis=0) for name, parts in pitcher_parts.items()
        },
        "folds": fold_records,
        "foldDirectArtifacts": fold_artifacts,
    }


def _component_coverage(
    components: Mapping[str, Any], reliability: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows = next(iter(components.values())).shape[0]
    output: list[dict[str, Any]] = []
    for name in COMPONENT_ORDER:
        if name == DIRECT_MODEL:
            output.append(
                {
                    "component": name,
                    "rows": rows,
                    "coveredRows": rows,
                    "coverage": 1.0,
                    "missingRows": 0,
                    "observationCountMean": None,
                    "effectiveSampleSizeMean": None,
                    "effectiveSampleSizeMedian": None,
                    "entropyMean": float(
                        np.mean(-np.sum(components[name] * np.log(np.clip(components[name], 1e-15, 1.0)), axis=1))
                    ),
                }
            )
            continue
        values = reliability[name]
        missing = np.asarray(values["missingHistoryFlag"], dtype=bool)
        covered = ~missing
        effective = np.asarray(values["effectiveSampleSize"], dtype=np.float64)
        count = np.asarray(values["observationCount"], dtype=np.float64)
        entropy = np.asarray(values["entropy"], dtype=np.float64)
        output.append(
            {
                "component": name,
                "rows": rows,
                "coveredRows": int(covered.sum()),
                "coverage": float(covered.mean()),
                "missingRows": int(missing.sum()),
                "observationCountMean": float(count[covered].mean()) if covered.any() else None,
                "effectiveSampleSizeMean": float(effective[covered].mean()) if covered.any() else None,
                "effectiveSampleSizeMedian": float(np.median(effective[covered])) if covered.any() else None,
                "entropyMean": float(entropy.mean()),
            }
        )
    return output


def _role_diagnostic_rows(
    labels: Any,
    batter: Mapping[str, np.ndarray],
    pitcher: Mapping[str, np.ndarray],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role, source in (("BATTER_ONLY", batter), ("PITCHER_ONLY", pitcher)):
        for component, probabilities in source.items():
            rows.append(
                {
                    "role": role,
                    "component": component,
                    "metrics": compact_multiclass_metrics(labels, probabilities),
                }
            )
    return sorted(rows, key=lambda row: (row["component"], row["role"]))


def _calibration_curve(labels: Any, probabilities: Any) -> list[dict[str, Any]]:
    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    matrix = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
    confidence = np.max(matrix, axis=1)
    correct = np.argmax(matrix, axis=1) == encoded
    edges = np.linspace(0.0, 1.0, 11)
    rows: list[dict[str, Any]] = []
    for index in range(10):
        mask = (confidence >= edges[index]) & (
            confidence <= edges[index + 1] if index == 9 else confidence < edges[index + 1]
        )
        if not mask.any():
            continue
        rows.append(
            {
                "binLower": float(edges[index]),
                "binUpper": float(edges[index + 1]),
                "meanConfidence": float(confidence[mask].mean()),
                "observedAccuracy": float(correct[mask].mean()),
                "count": int(mask.sum()),
            }
        )
    return rows


def _disagreement_rows(
    labels: Any,
    direct: np.ndarray,
    best: np.ndarray,
    disagreement: np.ndarray,
) -> list[dict[str, Any]]:
    edges = np.quantile(disagreement, np.linspace(0.0, 1.0, 6))
    output: list[dict[str, Any]] = []
    for index in range(5):
        mask = (disagreement >= edges[index]) & (
            disagreement <= edges[index + 1]
            if index == 4
            else disagreement < edges[index + 1]
        )
        if not mask.any():
            continue
        direct_metrics = compact_multiclass_metrics(np.asarray(labels)[mask], direct[mask])
        best_metrics = compact_multiclass_metrics(np.asarray(labels)[mask], best[mask])
        output.append(
            {
                "bin": f"Q{index + 1} [{edges[index]:.4f}, {edges[index + 1]:.4f}]",
                "count": int(mask.sum()),
                "directLogLoss": direct_metrics["logLoss"],
                "bestLogLoss": best_metrics["logLoss"],
                "improvement": float(direct_metrics["logLoss"] - best_metrics["logLoss"]),
            }
        )
    return output


def _candidate_members(candidate_id: str) -> list[str]:
    if candidate_id in COMPONENT_ORDER:
        return [candidate_id]
    if candidate_id in FIXED_ENSEMBLE_MEMBERS:
        return list(FIXED_ENSEMBLE_MEMBERS[candidate_id])
    if candidate_id in {"E9", "E10"}:
        return list(COMPONENT_ORDER)
    raise RecentStateStudyError(f"unknown candidate membership: {candidate_id}")


def _recommendation(
    *, selected_candidate: str, selected_2024: Mapping[str, Any], bootstrap: Mapping[str, Any]
) -> str:
    if selected_candidate == DIRECT_MODEL:
        return RECOMMENDATIONS[0]
    improvement = DIRECT_GOLD_REFERENCE_LOG_LOSS - float(selected_2024["metrics"]["logLoss"])
    interval = bootstrap["logLossDifference"]["confidenceInterval95"]
    if improvement <= 0.0 or float(interval["upper"]) >= 0.0:
        return RECOMMENDATIONS[0]
    if selected_candidate == "E10":
        return RECOMMENDATIONS[4]
    if selected_candidate in {"E9", *FIXED_ENSEMBLE_MEMBERS.keys()}:
        return RECOMMENDATIONS[3]
    if selected_candidate in {CLUSTER_MATCHUP, SHRUNK_EXACT_BVP}:
        return RECOMMENDATIONS[2]
    return RECOMMENDATIONS[1]


def _table_candidate_rows(
    leaderboard: Sequence[Mapping[str, Any]], *, direct_log_loss: float
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in leaderboard:
        metrics = row["metrics"]
        output.append(
            {
                "candidate": row["candidateId"],
                "candidateType": row["candidateType"],
                "components": list(row.get("memberIds") or (row["candidateId"],)),
                **metrics,
                "coverage": row.get("coverage", 1.0),
                "effectiveSampleSizeMean": row.get("effectiveSampleSizeMean"),
                "logLossImprovementVsDirect": float(direct_log_loss - metrics["logLoss"]),
            }
        )
    return output


def _mark_validation_leaderboard(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = _json_safe(raw)
        row["evaluationPopulation"] = "FROZEN_2024_VALIDATION_ONCE"
        row["selectionCriterion"] = "NOT_USED_FOR_SELECTION"
        row["uses2024"] = True
        output.append(row)
    return output


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(_json_safe(value), sort_keys=True)
                    if isinstance(value, (Mapping, list, tuple))
                    else _json_safe(value)
                    for key, value in row.items()
                }
            )


def _write_tables(root: Path, tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for name, rows in tables.items():
        _write_json(root / f"{name}.json", list(rows))
        _write_csv(root / f"{name}.csv", rows)


def _report_markdown(result: Mapping[str, Any]) -> str:
    decision = result["decision"]
    direct = result["direct2024LogLoss"]
    best = result["primaryCandidate"]
    candidate = next(row for row in result["candidate2024"] if row["candidate"] == best)
    bootstrap_candidate = (
        best if best in result["bootstrap2024"] else result["topFourCandidates"][0]
    )
    interval = result["bootstrap2024"][bootstrap_candidate]["logLossDifference"]["confidenceInterval95"]
    return "\n".join(
        (
            "# Phase 7B4 Recent-State, Matchup, and Ensemble Study",
            "",
            f"- Status: `{result['status']}`",
            f"- Recommendation: `{decision}`",
            f"- Frozen Direct Gold Logistic 2024 log loss: `{direct:.16f}`",
            f"- Development-selected primary candidate: `{best}`",
            f"- Primary candidate 2024 log loss: `{candidate['logLoss']:.16f}`",
            f"- Paired whole-game 95% interval ({bootstrap_candidate} minus Direct): "
            f"`[{interval['lower']:.12f}, {interval['upper']:.12f}]`",
            f"- Development OOF rows: `{result['populations']['oofRows']:,}`",
            f"- 2024 validation rows: `{result['populations']['validationRows']:,}`",
            "- Data seasons opened: `2021, 2022, 2023, 2024`",
            "- 2025/2026 opened: `0`",
            "- Promotion requested: `false`",
            "",
            "The full machine-readable tables, models, predictions, bootstrap evidence, "
            "and chart inventory are stored in the external request-addressed artifact root.",
            "",
        )
    )


def _verify_existing(final: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = final / "manifest.json"
    if not manifest_path.is_file():
        raise RecentStateStudyError("existing Phase 7B4 artifact lacks manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("request") != request or manifest.get("studySha256") != final.name:
        raise RecentStateStudyError("existing Phase 7B4 request identity differs")
    for relative, entry in (manifest.get("artifacts") or {}).items():
        path = (final / relative).resolve()
        if final.resolve() not in path.parents or not path.is_file():
            raise RecentStateStudyError(f"existing artifact is unsafe or missing: {relative}")
        size, digest = _sha_file(path)
        if size != entry.get("bytes") or digest != entry.get("sha256"):
            raise RecentStateStudyError(f"existing artifact bytes differ: {relative}")
    results_path = final / "results.json"
    result = json.loads(results_path.read_text(encoding="utf-8"))
    if manifest.get("resultsSha256") != hashlib.sha256(results_path.read_bytes()).hexdigest():
        raise RecentStateStudyError("existing Phase 7B4 results hash differs")
    result["artifactRoot"] = str(final)
    result["reused"] = True
    return result


def run_recent_state_matchup_ensemble_study(
    *,
    gold_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run or verify/reuse the one fixed research-only Phase 7B4 study."""

    announce = progress or (lambda _message: None)
    gold_root = Path(gold_root).resolve()
    verified_before = verify_gold(gold_root)
    if verified_before["logicalContentSha256"] != "56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0":
        raise RecentStateStudyError("Gold logical identity differs from the frozen Phase 7B2 object")
    implementation = _implementation_identity()
    request = _study_request(verified_before, implementation)
    study_sha = sha256_bytes(canonical_json_bytes(request))
    final = gold_root / "recent-state-studies" / "sha256" / study_sha
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return _verify_existing(final, request)

    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        announce("verify and load frozen Gold V1 plus accepted Direct Logistic")
        frame = _prepare_frame(verified_before)
        verified_after_read = verify_gold(gold_root, object_sha=verified_before["logicalContentSha256"])
        gold_manifest_sha_before = _verified_manifest_sha(verified_before)
        gold_manifest_sha_after_read = _verified_manifest_sha(verified_after_read)
        if gold_manifest_sha_after_read != gold_manifest_sha_before:
            raise RecentStateStudyError("Gold changed while the study frame was materialized")
        artifacts, source_direct = BH._verified_multiclass_artifacts(
            gold_root=gold_root, verified_gold=verified_before
        )
        direct_artifact = artifacts["gold_logistic"]

        development_mask = frame["season"].to_numpy(dtype=np.int64) < 2024
        validation_mask = frame["season"].to_numpy(dtype=np.int64) == 2024
        development = frame.loc[development_mask].reset_index(drop=True)
        validation = frame.loc[validation_mask].reset_index(drop=True)
        if len(development) != EXPECTED_GOLD_DEVELOPMENT_ROWS or len(validation) != EXPECTED_GOLD_VALIDATION_ROWS:
            raise RecentStateStudyError("Gold development/validation counts differ")

        announce("run six development-only rolling-origin component fits")
        oof = _run_development_oof(development, progress=announce)
        oof_fixed = build_fixed_ensembles(oof["components"])
        announce("fit E9 convex blend and E10 reliability stacker on development OOF")
        e9 = fit_convex_blend(oof["labels"], oof["components"])
        e10 = fit_reliability_gated_stacker(
            oof["labels"], oof["components"], oof["reliability"]
        )
        oof_ensembles = {
            **oof_fixed,
            "E9": e9.predict_proba(oof["components"]),
            "E10": e10.predict_proba(oof["components"], oof["reliability"]),
        }
        coverage_masks = {DIRECT_MODEL: np.ones(EXPECTED_OOF_ROWS, dtype=bool)}
        effective_sizes: dict[str, np.ndarray] = {}
        for name in EMPIRICAL_COMPONENT_ORDER:
            coverage_masks[name] = ~np.asarray(
                oof["reliability"][name]["missingHistoryFlag"], dtype=bool
            )
            effective_sizes[name] = np.asarray(
                oof["reliability"][name]["effectiveSampleSize"], dtype=np.float64
            )
        oof_components_lb = component_leaderboard(
            oof["labels"],
            oof["components"],
            coverage_masks=coverage_masks,
            effective_sample_sizes=effective_sizes,
        )
        ensemble_definitions = {
            **fixed_ensemble_definitions(), "E9": e9.record(), "E10": e10.record()
        }
        oof_ensembles_lb = ensemble_leaderboard(
            oof["labels"], oof_ensembles, definitions=ensemble_definitions
        )
        best_standalone = select_oof_winner(
            oof_components_lb, exclude_ids=(DIRECT_MODEL,)
        )
        best_simple = select_oof_winner(
            [row for row in oof_ensembles_lb if row["candidateId"] in FIXED_ENSEMBLE_MEMBERS]
        )
        selected_pool_ids = {
            DIRECT_MODEL,
            best_standalone["candidateId"],
            best_simple["candidateId"],
            "E9",
            "E10",
        }
        primary_oof = select_oof_winner(
            [
                *oof_components_lb,
                *oof_ensembles_lb,
            ],
            exclude_ids=tuple(
                set(COMPONENT_ORDER).union(oof_ensembles) - selected_pool_ids
            ),
        )

        announce("refit state authority on 2021-2023 and score frozen 2024 once")
        direct_all = direct_artifact.predict_proba(frame)
        final_history_direct, final_history_crossfit, final_history_artifacts = (
            _cross_fitted_history_direct(frame, development_mask)
        )
        final_authority = fit_state_authority(
            frame, final_history_direct, training_mask=development_mask
        )
        final_bundle = score_state_components(
            final_authority, frame, direct_all, target_mask=validation_mask
        )
        expected_validation_ids = tuple(validation["plate_appearance_id"].astype(str).tolist())
        if final_bundle.row_ids != expected_validation_ids:
            raise RecentStateStudyError("2024 component rows differ from Gold validation order")
        validation_components = final_bundle.probability_matrices
        validation_fixed = build_fixed_ensembles(validation_components)
        validation_ensembles = {
            **validation_fixed,
            "E9": e9.predict_proba(validation_components),
            "E10": e10.predict_proba(validation_components, final_bundle.reliability),
        }
        validation_labels = validation["outcome"].to_numpy(dtype=object)
        direct_metrics = compact_multiclass_metrics(
            validation_labels, validation_components[DIRECT_MODEL]
        )
        if not math.isclose(
            direct_metrics["logLoss"], DIRECT_GOLD_REFERENCE_LOG_LOSS, rel_tol=0.0, abs_tol=1e-12
        ):
            raise RecentStateStudyError(
                f"Direct Gold anchor differs: {direct_metrics['logLoss']!r}"
            )
        validation_components_lb = _mark_validation_leaderboard(component_leaderboard(
            validation_labels,
            validation_components,
            coverage_masks={
                DIRECT_MODEL: np.ones(len(validation), dtype=bool),
                **{
                    name: ~final_bundle.components[name].missing_history
                    for name in EMPIRICAL_COMPONENT_ORDER
                },
            },
            effective_sample_sizes={
                name: final_bundle.components[name].effective_sample_size
                for name in EMPIRICAL_COMPONENT_ORDER
            },
        ))
        validation_ensembles_lb = _mark_validation_leaderboard(ensemble_leaderboard(
            validation_labels,
            validation_ensembles,
            definitions=ensemble_definitions,
        ))
        candidate_predictions = {**validation_components, **validation_ensembles}
        top_candidate_ids = tuple(
            dict.fromkeys(
                (
                    str(best_standalone["candidateId"]),
                    str(best_simple["candidateId"]),
                    "E9",
                    "E10",
                )
            )
        )
        if len(top_candidate_ids) != 4:
            raise RecentStateStudyError("top four OOF-selected alternatives are not unique")
        announce("run four paired 2,000-replicate whole-game bootstraps")
        bootstrap = {
            candidate: compact_game_bootstrap(
                validation_labels,
                candidate_predictions[candidate],
                validation_components[DIRECT_MODEL],
                validation["game_id"].astype(str).to_numpy(dtype=object),
            )
            for candidate in top_candidate_ids
        }
        selected_candidate = str(primary_oof["candidateId"])
        selected_2024_row = next(
            row
            for row in [*validation_components_lb, *validation_ensembles_lb]
            if row["candidateId"] == selected_candidate
        )
        selected_bootstrap = (
            bootstrap[selected_candidate]
            if selected_candidate in bootstrap
            else bootstrap[top_candidate_ids[0]]
        )
        decision = _recommendation(
            selected_candidate=selected_candidate,
            selected_2024=selected_2024_row,
            bootstrap=selected_bootstrap,
        )

        disagreement = component_disagreement(
            validation_components[DIRECT_MODEL],
            validation_components[RECENT_14_DAY_STATE],
        )
        slices = bounded_slice_evaluation(
            labels=validation_labels,
            direct_probabilities=validation_components[DIRECT_MODEL],
            alternative_probabilities={
                candidate: candidate_predictions[candidate]
                for candidate in top_candidate_ids
            },
            game_dates=validation["game_date"].to_numpy(copy=False),
            recent_batter_sample_size=final_bundle.components[
                RECENT_42_DAY_STATE
            ].role_diagnostics["batter_observation_count"],
            recent_pitcher_sample_size=final_bundle.components[
                RECENT_42_DAY_STATE
            ].role_diagnostics["pitcher_observation_count"],
            batter_ids=validation["batterCanonicalPlayerId"].to_numpy(copy=False),
            pitcher_ids=validation["pitcherCanonicalPlayerId"].to_numpy(copy=False),
            development_batter_ids=development["batterCanonicalPlayerId"].to_numpy(copy=False),
            development_pitcher_ids=development["pitcherCanonicalPlayerId"].to_numpy(copy=False),
            disagreement=disagreement,
        )

        standalone_table = _table_candidate_rows(
            validation_components_lb, direct_log_loss=DIRECT_GOLD_REFERENCE_LOG_LOSS
        )
        ensemble_table = _table_candidate_rows(
            validation_ensembles_lb, direct_log_loss=DIRECT_GOLD_REFERENCE_LOG_LOSS
        )
        all_candidate_rows = sorted(
            [*standalone_table, *ensemble_table], key=lambda row: row["logLoss"]
        )
        lift_table = [
            {
                "candidate": row["candidate"],
                "logLoss": row["logLoss"],
                "directLogLoss": DIRECT_GOLD_REFERENCE_LOG_LOSS,
                "improvementVsDirect": row["logLossImprovementVsDirect"],
                "summedBrier": row["summedBrier"],
                "ece": row["ece"],
                "accuracy": row["accuracy"],
                "macroF1": row["macroF1"],
            }
            for row in all_candidate_rows
        ]
        monthly_table: list[dict[str, Any]] = []
        for item in slices:
            if item["sliceGroup"] != "month":
                continue
            for candidate, metrics in item["candidates"].items():
                if candidate == DIRECT_MODEL or candidate in top_candidate_ids:
                    monthly_table.append(
                        {
                            "month": item["slice"],
                            "candidate": candidate,
                            "rows": item["rows"],
                            **metrics,
                        }
                    )
        bootstrap_table = [
            {
                "candidate": candidate,
                "resamples": evidence["resampleCount"],
                "games": evidence["gameCount"],
                "logLossDifferenceVsDirect": evidence["logLossDifference"]["pointEstimate"],
                "logLossCi95Lower": evidence["logLossDifference"]["confidenceInterval95"]["lower"],
                "logLossCi95Upper": evidence["logLossDifference"]["confidenceInterval95"]["upper"],
                "probabilityCandidateBetter": evidence["logLossDifference"]["probabilitySelectedBetter"],
                "summedBrierDifferenceVsDirect": evidence["summedBrierDifference"]["pointEstimate"],
            }
            for candidate, evidence in bootstrap.items()
        ]
        static_weights = dict(e9.record()["weights"])
        gated_raw = dict(e10.coefficient_importance()["componentImportance"])
        gated_total = math.fsum(gated_raw.values())
        if gated_total <= 0.0:
            raise RecentStateStudyError("E10 component importance is empty")
        gated_weights = {name: float(value / gated_total) for name, value in gated_raw.items()}
        weights_table = [
            {
                "component": component,
                "optimizedStatic": float(static_weights[component]),
                "averageGated": float(gated_weights[component]),
                "gatedMeasure": "NORMALIZED_MEAN_ABSOLUTE_MULTINOMIAL_COEFFICIENT_MAGNITUDE",
            }
            for component in COMPONENT_ORDER
        ]
        tables: dict[str, list[dict[str, Any]]] = {
            "standalone-component-leaderboard": standalone_table,
            "ensemble-leaderboard": ensemble_table,
            "incremental-lift-versus-direct": lift_table,
            "component-coverage-reliability": _component_coverage(
                validation_components, final_bundle.reliability
            ),
            "monthly-stability": monthly_table,
            "bootstrap-uncertainty": bootstrap_table,
            "final-ensemble-weights": weights_table,
        }
        candidate_2024 = [
            {
                "candidate": row["candidate"],
                "logLoss": row["logLoss"],
                "components": _candidate_members(row["candidate"]),
            }
            for row in all_candidate_rows
        ]
        best_review_ensemble = str(select_oof_winner(oof_ensembles_lb)["candidateId"])
        calibration = {
            "directCandidate": DIRECT_MODEL,
            "bestCandidate": best_review_ensemble,
            "curves": {
                DIRECT_MODEL: _calibration_curve(
                    validation_labels, validation_components[DIRECT_MODEL]
                ),
                best_review_ensemble: _calibration_curve(
                    validation_labels,
                    candidate_predictions[best_review_ensemble],
                ),
            },
        }
        chart_best = calibration["bestCandidate"]
        disagreement_rows = _disagreement_rows(
            validation_labels,
            validation_components[DIRECT_MODEL],
            candidate_predictions[chart_best],
            disagreement,
        )
        announce("reverify frozen Gold V1 after all fitting and scoring")
        verified_final = verify_gold(
            gold_root, object_sha=verified_before["logicalContentSha256"]
        )
        gold_manifest_sha_final = _verified_manifest_sha(verified_final)
        if gold_manifest_sha_final != gold_manifest_sha_before:
            raise RecentStateStudyError("Gold changed during the Phase 7B4 study")
        result: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "RESEARCH_ONLY_COMPLETE",
            "studySha256": study_sha,
            "request": request,
            "sourceDirectAuthority": source_direct,
            "dataVerification": {
                "goldDatasetVersionId": verified_before["datasetVersionId"],
                "goldLogicalContentSha256": verified_before["logicalContentSha256"],
                "goldManifestSha256Before": gold_manifest_sha_before,
                "goldManifestSha256AfterRead": gold_manifest_sha_after_read,
                "goldManifestSha256AfterStudy": gold_manifest_sha_final,
                "seasonsOpened": [2021, 2022, 2023, 2024],
                "opened2025": False,
                "opened2026": False,
                "bronzeRebuilt": False,
                "silverRebuilt": False,
                "goldAltered": False,
            },
            "populations": {
                "developmentRows": len(development),
                "oofRows": EXPECTED_OOF_ROWS,
                "validationRows": len(validation),
                "seasonRows": dict(EXPECTED_GOLD_SEASON_ROWS),
            },
            "rollingOriginFolds": oof["folds"],
            "developmentOof": {
                "standaloneLeaderboard": oof_components_lb,
                "ensembleLeaderboard": oof_ensembles_lb,
                "roleDiagnostics": _role_diagnostic_rows(
                    oof["labels"], oof["batterDiagnostics"], oof["pitcherDiagnostics"]
                ),
                "selectedBestStandalone": best_standalone,
                "selectedBestSimpleEnsemble": best_simple,
                "selectedPrimary": primary_oof,
                "selectedBestEnsembleForReview": best_review_ensemble,
                "e9": e9.record(),
                "e10": e10.record(),
            },
            "finalResidualExpectationCrossFit": final_history_crossfit,
            "direct2024LogLoss": DIRECT_GOLD_REFERENCE_LOG_LOSS,
            "candidate2024": candidate_2024,
            "primaryCandidate": selected_candidate,
            "bestCandidate": chart_best,
            "topFourCandidates": list(top_candidate_ids),
            "validation2024": {
                "standaloneLeaderboard": validation_components_lb,
                "ensembleLeaderboard": validation_ensembles_lb,
                "roleDiagnostics": _role_diagnostic_rows(
                    validation_labels,
                    final_bundle.batter_only_probabilities,
                    final_bundle.pitcher_only_probabilities,
                ),
            },
            "tables": tables,
            "monthly2024": monthly_table,
            "calibration2024": calibration,
            "ensembleWeights": {
                "optimizedStatic": static_weights,
                "averageGated": gated_weights,
                "averageGatedDefinition": "NORMALIZED_COMPONENT_COEFFICIENT_MAGNITUDE_NOT_PROBABILITY_WEIGHT",
            },
            "disagreement2024": disagreement_rows,
            "bootstrap2024": bootstrap,
            "robustnessSlices2024": slices,
            "decision": decision,
            "promotionRequested": False,
            "limitations": [
                "All empirical state is frozen before each validation block; no within-block updates are permitted.",
                "Recent 14/42-day coverage can decay late in a frozen validation block by design.",
                "E10 chart weights are normalized coefficient-magnitude diagnostics, not per-row probability weights.",
                "The matched Gold population excludes 13,471 fail-closed bridge rows across 2021-2024.",
            ],
            "nextProposedExperiment": "If adopted, repeat this fixed architecture on a future untouched season after it becomes authorized; do not broaden the model family.",
        }

        (staging / "models").mkdir()
        for fold_id, artifact in oof["foldDirectArtifacts"].items():
            joblib.dump(artifact, staging / "models" / f"{fold_id}-direct.joblib", compress=3)
        for artifact_id, artifact in final_history_artifacts.items():
            joblib.dump(
                artifact,
                staging / "models" / f"final-{artifact_id}-direct.joblib",
                compress=3,
            )
        joblib.dump(final_authority, staging / "models" / "final-state-authority.joblib", compress=3)
        joblib.dump(e9, staging / "models" / "e9-convex-blend.joblib", compress=3)
        joblib.dump(e10, staging / "models" / "e10-reliability-stacker.joblib", compress=3)
        (staging / "predictions").mkdir()
        np.savez_compressed(
            staging / "predictions" / "development-oof.npz",
            rowIds=np.asarray(oof["rowIds"], dtype=str),
            labels=np.asarray(oof["labels"], dtype=str),
            **{f"component__{name}": matrix for name, matrix in oof["components"].items()},
            **{f"ensemble__{name}": matrix for name, matrix in oof_ensembles.items()},
        )
        np.savez_compressed(
            staging / "predictions" / "development-oof-reliability.npz",
            **{
                f"{component}__{field}": values
                for component, fields in oof["reliability"].items()
                for field, values in fields.items()
            },
        )
        np.savez_compressed(
            staging / "predictions" / "validation-2024.npz",
            rowIds=np.asarray(expected_validation_ids, dtype=str),
            labels=np.asarray(validation_labels, dtype=str),
            **{f"component__{name}": matrix for name, matrix in validation_components.items()},
            **{f"ensemble__{name}": matrix for name, matrix in validation_ensembles.items()},
        )
        np.savez_compressed(
            staging / "predictions" / "validation-2024-reliability.npz",
            **{
                f"{component}__{field}": values
                for component, fields in final_bundle.reliability.items()
                for field, values in fields.items()
            },
        )
        _write_tables(staging / "tables", tables)
        _write_json(staging / "component-specification.json", request)
        _write_json(staging / "robustness-slices.json", slices)
        _write_json(staging / "bootstrap-evidence.json", bootstrap)
        announce("render six deterministic review charts")
        charts = generate_review_charts(result, staging / "charts", include_svg=True)
        for chart in charts:
            for file_record in chart["files"]:
                chart_path = Path(file_record.pop("path")).resolve()
                file_record["relativePath"] = chart_path.relative_to(staging.resolve()).as_posix()
        result["charts"] = charts
        result["artifactRoot"] = None
        _write_json(staging / "results.json", result)
        (staging / "study-report.md").write_text(_report_markdown(result), encoding="utf-8")

        artifact_inventory: dict[str, Any] = {}
        for path in sorted(
            (item for item in staging.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(staging).as_posix(),
        ):
            artifact_inventory[path.relative_to(staging).as_posix()] = _artifact_entry(
                path, root=staging
            )
        results_sha = artifact_inventory["results.json"]["sha256"]
        _write_json(
            staging / "manifest.json",
            {
                "schemaVersion": SCHEMA_VERSION,
                "studySha256": study_sha,
                "request": request,
                "status": "RESEARCH_ONLY",
                "promotionEligible": False,
                "resultsSha256": results_sha,
                "artifacts": artifact_inventory,
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
    "DIRECT_GOLD_REFERENCE_LOG_LOSS",
    "EXPECTED_OOF_FOLD_ROWS",
    "EXPECTED_OOF_ROWS",
    "RECOMMENDATIONS",
    "RecentStateStudyError",
    "run_recent_state_matchup_ensemble_study",
]
