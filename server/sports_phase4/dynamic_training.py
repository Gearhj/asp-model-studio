from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.bootstrap import game_cluster_bootstrap
from server.sports_modeling.calibration import fit_temperature_scaling, temperature_scale
from server.sports_modeling.feature_contract import CONTEXT_FEATURES
from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    validate_probability_matrix,
)
from server.sports_modeling.training import (
    DEFAULT_MAX_ITER,
    FoldPredictions,
    MultinomialCandidateModel,
    TrainingArrays,
    TrainingIntegrityError,
    _fit_logistic,
    chronological_date_atomic_split,
)

from .dynamic_contract import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE,
    CANDIDATE_FEATURES,
    CANDIDATE_LABELS,
    CONTRACT_NAME,
    DECISION_ENUM,
    DECISION_TOLERANCE,
    LOGISTIC_C_GRID,
    PHASE3_FOLD_2024_PREDICTION_SHA,
    PHASE3_FOLD_2025_PREDICTION_SHA,
    STATE_KINDS,
    STATE_VALUE_COLUMNS,
)
from .dynamic_state import (
    DynamicStateIntegrityError,
    FrozenDynamicPolicy,
    dynamic_state_table_content_sha,
)


DYNAMIC_TRAINING_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_TRAINING_V1"
DYNAMIC_CALIBRATION_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_CALIBRATION_V1"
DYNAMIC_BOOTSTRAP_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_BOOTSTRAP_V1"
DYNAMIC_COVERAGE_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_COVERAGE_V1"
FOLD_2024_ID = "dynamic-train-2023-validate-2024"
FOLD_2025_ID = "dynamic-train-through-2024-validate-2025"
FIT_HEARTBEAT_SECONDS = 30.0
MAX_MODEL_FIT_SECONDS = 90 * 60
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


class DynamicTrainingIntegrityError(RuntimeError):
    """Raised when Phase 4 training cannot prove its frozen data and evaluation rules."""


@dataclass(frozen=True)
class FrozenD0Fold:
    season: int
    artifact_sha: str
    table: pa.Table


@dataclass(frozen=True)
class DynamicTrainingArrays:
    training: TrainingArrays
    dynamic_content_sha: str

    @property
    def row_count(self) -> int:
        return self.training.row_count


@dataclass
class DynamicTrainingExperiment:
    arrays: DynamicTrainingArrays
    candidates: list[dict[str, Any]]
    selected_candidate_id: str
    selected_rationale: str
    folds: dict[int, FoldPredictions]
    models: dict[tuple[int, str], MultinomialCandidateModel]
    split_evidence: dict[str, Any]
    d0_artifact_shas: dict[int, str]

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        return next(item for item in self.candidates if item["candidateId"] == candidate_id)


@dataclass(frozen=True)
class DynamicEvaluationEvidence:
    calibration: dict[str, Any]
    bootstrap: list[dict[str, Any]]
    coverage: dict[str, Any]
    decision: dict[str, Any]
    scaled_probabilities: dict[int, np.ndarray]
    final_probabilities: dict[int, np.ndarray]


def _emit(progress: Any | None, stage: str, evidence: Mapping[str, Any]) -> None:
    if progress is not None:
        progress(stage, {"stage": stage, **dict(evidence)})


def run_blocking_with_heartbeat(
    operation: Any,
    *,
    stage: str,
    candidate_id: str,
    progress: Any | None,
    heartbeat_seconds: float = FIT_HEARTBEAT_SECONDS,
    max_elapsed_seconds: float = MAX_MODEL_FIT_SECONDS,
) -> Any:
    """Run a synchronous fit while a daemon emits two-argument heartbeats."""

    if not callable(operation):
        raise TypeError("heartbeat operation must be callable")
    if heartbeat_seconds <= 0.0 or heartbeat_seconds > 60.0:
        raise ValueError("fit heartbeat interval must be in (0, 60]")
    if max_elapsed_seconds <= 0.0 or max_elapsed_seconds > MAX_MODEL_FIT_SECONDS:
        raise ValueError("model fit limit must be in (0, 90 minutes]")
    started = time.monotonic()
    stopped = threading.Event()

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            elapsed = time.monotonic() - started
            _emit(
                progress,
                "DYNAMIC_MODEL_FIT_HEARTBEAT",
                {
                    "blockingStage": stage,
                    "candidateId": candidate_id,
                    "elapsedSeconds": round(elapsed, 2),
                    "maxFitSeconds": max_elapsed_seconds,
                    "errors": 0,
                },
            )

    thread = threading.Thread(
        target=heartbeat,
        name=f"dynamic-fit-heartbeat-{candidate_id}",
        daemon=True,
    )
    if progress is not None:
        thread.start()
    try:
        result = operation()
    finally:
        stopped.set()
        if progress is not None:
            thread.join(timeout=min(heartbeat_seconds, 1.0))
    elapsed = time.monotonic() - started
    _emit(
        progress,
        "DYNAMIC_MODEL_FIT_FINISHED",
        {
            "blockingStage": stage,
            "candidateId": candidate_id,
            "elapsedSeconds": round(elapsed, 2),
            "maxFitSeconds": max_elapsed_seconds,
            "errors": 0,
        },
    )
    if elapsed > max_elapsed_seconds:
        raise DynamicTrainingIntegrityError("dynamic model fit exceeded the 90-minute limit")
    return result


def _array(table: pa.Table, name: str, *, dtype: Any) -> np.ndarray:
    if name not in table.column_names:
        raise DynamicTrainingIntegrityError(f"Phase 3 feature view is missing {name}")
    try:
        return np.asarray(table[name].combine_chunks().to_pylist(), dtype=dtype)
    except (TypeError, ValueError) as exc:
        raise DynamicTrainingIntegrityError(f"Phase 3 feature field is incompatible: {name}") from exc


def _state_join(
    feature_view: pa.Table,
    state_table: pa.Table,
    *,
    role: str,
    state_kind: str,
    include_values: bool,
) -> dict[str, np.ndarray]:
    role_lower = role.casefold()
    state_letter = state_kind[0].casefold()
    player_field = f"{role_lower}_canonical_player_uuid"
    mask = pc.and_(
        pc.equal(state_table["role"], role),
        pc.equal(state_table["state_kind"], state_kind),
    )
    selected_columns = [
        "game_date",
        "season",
        "canonical_player_uuid",
        "stateRowId",
        *(STATE_VALUE_COLUMNS if include_values else ()),
    ]
    state = state_table.filter(mask).select(selected_columns)
    state = state.rename_columns(
        [
            "game_date",
            "season",
            player_field,
            "_matched_state_row_id",
            *(
                [f"{role_lower}_{state_letter}_{name}" for name in STATE_VALUE_COLUMNS]
                if include_values
                else []
            ),
        ]
    )
    target_season_type = feature_view.schema.field("season").type
    if state.schema.field("season").type != target_season_type:
        state = state.set_column(
            state.schema.get_field_index("season"),
            "season",
            pc.cast(state["season"], target_type=target_season_type, safe=True),
        )
    keys = feature_view.select(["game_date", "season", player_field]).append_column(
        "_row_ordinal",
        pa.array(np.arange(feature_view.num_rows, dtype=np.int64)),
    )
    joined = keys.join(
        state,
        keys=["game_date", "season", player_field],
        join_type="left outer",
    ).sort_by("_row_ordinal")
    if joined.num_rows != feature_view.num_rows:
        raise DynamicTrainingIntegrityError("dynamic state join is not one-to-one")
    ordinals = np.asarray(joined["_row_ordinal"].combine_chunks().to_numpy(), dtype=np.int64)
    if not np.array_equal(ordinals, np.arange(feature_view.num_rows, dtype=np.int64)):
        raise DynamicTrainingIntegrityError("dynamic state join changed Phase 3 row order")
    if joined["_matched_state_row_id"].null_count:
        raise DynamicTrainingIntegrityError(
            f"dynamic state is missing {role}/{state_kind} rows for Phase 3 targets"
        )
    if not include_values:
        return {}
    result: dict[str, np.ndarray] = {}
    for name in STATE_VALUE_COLUMNS:
        output_name = f"{role_lower}_{state_letter}_{name}"
        column = joined[output_name].combine_chunks()
        if name == "days_since_evidence":
            result[output_name] = np.asarray(column.to_pylist(), dtype=np.float64)
        else:
            result[output_name] = np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)
        if name != "days_since_evidence" and not np.isfinite(result[output_name]).all():
            raise DynamicTrainingIntegrityError(f"dynamic state feature is non-finite: {output_name}")
    return result


def dynamic_training_arrays(
    feature_view: pa.Table,
    state_table: pa.Table,
    *,
    policy: FrozenDynamicPolicy,
    expected_dynamic_content_sha: str,
) -> DynamicTrainingArrays:
    if not isinstance(feature_view, pa.Table) or feature_view.num_rows == 0:
        raise DynamicTrainingIntegrityError("Phase 3 feature view must be non-empty")
    required = {
        "plate_appearance_id",
        "game_id",
        "game_date",
        "season",
        "outcome",
        "batter_canonical_player_uuid",
        "pitcher_canonical_player_uuid",
        *CONTEXT_FEATURES,
    }
    missing = sorted(required - set(feature_view.column_names))
    if missing:
        raise DynamicTrainingIntegrityError(f"Phase 3 feature view is missing fields: {missing}")
    if not isinstance(expected_dynamic_content_sha, str) or not _SHA_RE.fullmatch(
        expected_dynamic_content_sha
    ):
        raise DynamicTrainingIntegrityError("dynamic content SHA must be exact lowercase SHA-256")
    observed_content_sha = dynamic_state_table_content_sha(state_table, policy=policy)
    if observed_content_sha != expected_dynamic_content_sha:
        raise DynamicTrainingIntegrityError("dynamic state semantic content SHA differs")

    plate_ids = _array(feature_view, "plate_appearance_id", dtype=object)
    if len(set(plate_ids.tolist())) != feature_view.num_rows:
        raise DynamicTrainingIntegrityError("Phase 3 plate-appearance identity is duplicated")
    seasons = _array(feature_view, "season", dtype=np.int64)
    if not np.isin(seasons, (2023, 2024, 2025)).all():
        raise DynamicTrainingIntegrityError("Phase 3 targets must contain only 2023-2025")
    labels = _array(feature_view, "outcome", dtype=object)
    encoded = encode_labels(labels)
    feature_values = {
        name: _array(feature_view, name, dtype=np.float64) for name in CONTEXT_FEATURES
    }
    # Validate all three required representations.  A is descriptive evidence;
    # B/C are joined into the four challenger feature sets.
    for role in ("BATTER", "PITCHER"):
        _state_join(
            feature_view,
            state_table,
            role=role,
            state_kind="A_PRESEASON",
            include_values=False,
        )
        feature_values.update(
            _state_join(
                feature_view,
                state_table,
                role=role,
                state_kind="B_CUMULATIVE",
                include_values=True,
            )
        )
        feature_values.update(
            _state_join(
                feature_view,
                state_table,
                role=role,
                state_kind="C_RECENCY",
                include_values=True,
            )
        )
    expected_features = set().union(*CANDIDATE_FEATURES.values())
    if set(feature_values) != expected_features:
        raise DynamicTrainingIntegrityError("dynamic candidate feature matrix differs from contract")
    training = TrainingArrays(
        feature_values=feature_values,
        labels=labels,
        encoded_labels=encoded,
        seasons=seasons,
        game_dates=_array(feature_view, "game_date", dtype=object),
        game_ids=_array(feature_view, "game_id", dtype=object),
        plate_appearance_ids=plate_ids,
    )
    return DynamicTrainingArrays(training=training, dynamic_content_sha=observed_content_sha)


def _validate_d0_fold(
    fold: FrozenD0Fold,
    arrays: TrainingArrays,
    mask: np.ndarray,
    *,
    expected_artifact_sha: str | None,
) -> np.ndarray:
    if fold.season not in (2024, 2025):
        raise DynamicTrainingIntegrityError("D0 prediction fold must be 2024 or 2025")
    if not isinstance(fold.artifact_sha, str) or not _SHA_RE.fullmatch(fold.artifact_sha):
        raise DynamicTrainingIntegrityError("D0 artifact SHA must be lowercase SHA-256")
    if expected_artifact_sha is not None and fold.artifact_sha != expected_artifact_sha:
        raise DynamicTrainingIntegrityError("D0 prediction artifact SHA differs from Phase 3")
    table = fold.table
    required = {
        "plate_appearance_id",
        "game_id",
        "outcome",
        *(f"raw_C4_{class_name}" for class_name in PA_CLASS_ORDER),
    }
    if not isinstance(table, pa.Table) or not required.issubset(table.column_names):
        raise DynamicTrainingIntegrityError("D0 prediction artifact schema differs")
    if table.num_rows != int(mask.sum()):
        raise DynamicTrainingIntegrityError("D0 prediction row count differs from Phase 3 fold")
    for name, expected in (
        ("plate_appearance_id", arrays.plate_appearance_ids[mask]),
        ("game_id", arrays.game_ids[mask]),
        ("outcome", arrays.labels[mask]),
    ):
        observed = np.asarray(table[name].combine_chunks().to_pylist(), dtype=object)
        if not np.array_equal(observed, expected):
            raise DynamicTrainingIntegrityError(f"D0 {name} lineage differs from Phase 3 feature rows")
    probabilities = np.column_stack(
        [
            np.asarray(
                table[f"raw_C4_{class_name}"].combine_chunks().to_numpy(),
                dtype=np.float64,
            )
            for class_name in PA_CLASS_ORDER
        ]
    )
    try:
        return validate_probability_matrix(probabilities)
    except (TypeError, ValueError) as exc:
        raise DynamicTrainingIntegrityError("D0 raw C4 probabilities are invalid") from exc


def _fold_record(
    *,
    fold_id: str,
    training_seasons: Sequence[int],
    validation_season: int,
    training_rows: int | None,
    validation_rows: int,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "foldId": fold_id,
        "status": "COMPLETE",
        "trainingSeasons": list(training_seasons),
        "trainingRows": training_rows,
        "validationSeason": validation_season,
        "validationRows": validation_rows,
        "metrics": dict(metrics),
    }


def run_dynamic_training_experiment(
    feature_view: pa.Table,
    state_table: pa.Table,
    *,
    policy: FrozenDynamicPolicy,
    dynamic_content_sha: str,
    d0_folds: Mapping[int, FrozenD0Fold],
    expected_d0_artifact_shas: Mapping[int, str] | None = None,
    c_grid: Sequence[float] = LOGISTIC_C_GRID,
    max_iter: int = DEFAULT_MAX_ITER,
    progress: Any | None = None,
) -> DynamicTrainingExperiment:
    if tuple(float(value) for value in c_grid) != LOGISTIC_C_GRID:
        raise ValueError(f"c_grid must exactly equal {LOGISTIC_C_GRID}")
    if not isinstance(max_iter, int) or isinstance(max_iter, bool) or max_iter < 10:
        raise ValueError("max_iter must be an integer of at least 10")
    if set(d0_folds) != {2024, 2025}:
        raise DynamicTrainingIntegrityError("exact D0 2024 and 2025 folds are required")
    if expected_d0_artifact_shas is not None and dict(expected_d0_artifact_shas) != {
        2024: PHASE3_FOLD_2024_PREDICTION_SHA,
        2025: PHASE3_FOLD_2025_PREDICTION_SHA,
    }:
        raise DynamicTrainingIntegrityError("governed D0 artifact authority differs")
    built_arrays = dynamic_training_arrays(
        feature_view,
        state_table,
        policy=policy,
        expected_dynamic_content_sha=dynamic_content_sha,
    )
    arrays = built_arrays.training
    masks = {season: arrays.seasons == season for season in (2023, 2024, 2025)}
    if any(not np.any(mask) for mask in masks.values()):
        raise DynamicTrainingIntegrityError("all frozen target seasons must contain rows")
    inner_train, inner_validation, split = chronological_date_atomic_split(
        arrays.game_dates,
        masks[2023],
    )
    expected_2024 = (
        expected_d0_artifact_shas.get(2024) if expected_d0_artifact_shas is not None else None
    )
    d0_2024 = _validate_d0_fold(
        d0_folds[2024], arrays, masks[2024], expected_artifact_sha=expected_2024
    )
    d0_metrics_2024 = evaluate_multiclass(arrays.labels[masks[2024]], d0_2024)
    candidates: list[dict[str, Any]] = [
        {
            "candidateId": "D0",
            "candidateType": "FROZEN_PHASE3_RAW_C4",
            "displayName": CANDIDATE_LABELS["D0"],
            "ordinal": 0,
            "config": {
                "estimator": "FROZEN_PHASE3_RAW_C4",
                "refit": False,
                "relabelled": False,
                "classOrder": list(PA_CLASS_ORDER),
                "sourceArtifactShas": {
                    "2024": d0_folds[2024].artifact_sha,
                    "2025": d0_folds[2025].artifact_sha,
                },
            },
            "foldMetrics": [
                _fold_record(
                    fold_id=FOLD_2024_ID,
                    training_seasons=[2023],
                    validation_season=2024,
                    training_rows=int(masks[2023].sum()),
                    validation_rows=int(masks[2024].sum()),
                    metrics=d0_metrics_2024,
                )
            ],
            "convergence": {"status": "NOT_APPLICABLE", "converged": None},
            "runtimeSeconds": 0.0,
        }
    ]
    models: dict[tuple[int, str], MultinomialCandidateModel] = {}
    probabilities_2024: dict[str, np.ndarray] = {"D0": d0_2024}
    selected_c: dict[str, float] = {}
    for ordinal, candidate_id in enumerate(("D1", "D2", "D3", "D4"), start=1):
        started = time.perf_counter()
        tuning_rows: list[dict[str, Any]] = []
        maximum_iterations = 0
        for c_value in LOGISTIC_C_GRID:
            _emit(
                progress,
                "TUNING_DYNAMIC_LOGISTIC_2023",
                {"candidateId": candidate_id, "C": c_value, "selectionSeasonAccessed": False},
            )
            try:
                model, n_iter, _ = run_blocking_with_heartbeat(
                    lambda: _fit_logistic(
                        arrays,
                        CANDIDATE_FEATURES[candidate_id],
                        inner_train,
                        c_value=c_value,
                        max_iter=max_iter,
                    ),
                    stage="TUNING_DYNAMIC_LOGISTIC_2023",
                    candidate_id=candidate_id,
                    progress=progress,
                )
            except TrainingIntegrityError as exc:
                raise DynamicTrainingIntegrityError(str(exc)) from exc
            probabilities = model.predict_proba(arrays.feature_values, inner_validation)
            metrics = evaluate_multiclass(arrays.labels[inner_validation], probabilities)
            tuning_rows.append(
                {
                    "C": c_value,
                    "trainingRows": int(inner_train.sum()),
                    "validationRows": int(inner_validation.sum()),
                    "metrics": metrics,
                    "nIter": n_iter,
                }
            )
            maximum_iterations = max(maximum_iterations, n_iter)
        winner = min(
            tuning_rows,
            key=lambda item: (item["metrics"]["logLoss"], item["metrics"]["brierScore"], item["C"]),
        )
        selected_c[candidate_id] = float(winner["C"])
        _emit(
            progress,
            "FITTING_DYNAMIC_2023_VALIDATING_2024",
            {"candidateId": candidate_id, "C": winner["C"]},
        )
        try:
            model, n_iter, _ = run_blocking_with_heartbeat(
                lambda: _fit_logistic(
                    arrays,
                    CANDIDATE_FEATURES[candidate_id],
                    masks[2023],
                    c_value=float(winner["C"]),
                    max_iter=max_iter,
                ),
                stage="FITTING_DYNAMIC_2023_VALIDATING_2024",
                candidate_id=candidate_id,
                progress=progress,
            )
        except TrainingIntegrityError as exc:
            raise DynamicTrainingIntegrityError(str(exc)) from exc
        probabilities = model.predict_proba(arrays.feature_values, masks[2024])
        metrics_2024 = evaluate_multiclass(arrays.labels[masks[2024]], probabilities)
        probabilities_2024[candidate_id] = probabilities
        models[(2024, candidate_id)] = model
        maximum_iterations = max(maximum_iterations, n_iter)
        config = {
            "estimator": "sklearn.linear_model.LogisticRegression",
            "multiclass": "TRUE_MULTINOMIAL",
            "penalty": "l2",
            "solver": "lbfgs",
            "CGrid": list(LOGISTIC_C_GRID),
            "selectedC": float(winner["C"]),
            "maxIter": max_iter,
            "featureNames": list(CANDIDATE_FEATURES[candidate_id]),
            "preprocessing": "FOLD_LOCAL_MEAN_IMPUTE_STANDARDIZE_FIXED_ONE_HOT",
        }
        candidates.append(
            {
                "candidateId": candidate_id,
                "candidateType": "MULTINOMIAL_LOGISTIC_L2",
                "displayName": CANDIDATE_LABELS[candidate_id],
                "ordinal": ordinal,
                "config": config,
                "configSha": sha256_bytes(canonical_json_bytes(config)),
                "inner2023Tuning": tuning_rows,
                "foldMetrics": [
                    _fold_record(
                        fold_id=FOLD_2024_ID,
                        training_seasons=[2023],
                        validation_season=2024,
                        training_rows=int(masks[2023].sum()),
                        validation_rows=int(masks[2024].sum()),
                        metrics=metrics_2024,
                    )
                ],
                "convergence": {
                    "status": "CONVERGED",
                    "converged": True,
                    "nIter": maximum_iterations,
                    "maxIter": max_iter,
                    "solver": "lbfgs",
                },
                "runtimeSeconds": round(time.perf_counter() - started, 6),
            }
        )
    selected = min(
        candidates[1:],
        key=lambda item: (
            item["foldMetrics"][0]["metrics"]["logLoss"],
            item["foldMetrics"][0]["metrics"]["brierScore"],
            item["ordinal"],
        ),
    )
    selected_id = str(selected["candidateId"])
    selected_rationale = (
        "Selected among D1-D4 using raw 2024 log loss, then raw 2024 Brier score, "
        "then frozen candidate ordinal; no 2025 probabilities or labels were evaluated first."
    )
    _emit(
        progress,
        "DYNAMIC_CANDIDATE_FROZEN",
        {"candidateId": selected_id, "selectionSeason": 2024, "finalSeasonAccessed": False},
    )

    # Only after the dynamic candidate is frozen do we validate/evaluate D0 2025 and
    # refit every D1-D4 candidate through 2024 for the governing 2025 fold.
    expected_2025 = (
        expected_d0_artifact_shas.get(2025) if expected_d0_artifact_shas is not None else None
    )
    d0_2025 = _validate_d0_fold(
        d0_folds[2025], arrays, masks[2025], expected_artifact_sha=expected_2025
    )
    d0_metrics_2025 = evaluate_multiclass(arrays.labels[masks[2025]], d0_2025)
    candidates[0]["foldMetrics"].append(
        _fold_record(
            fold_id=FOLD_2025_ID,
            training_seasons=[2023, 2024],
            validation_season=2025,
            training_rows=int((masks[2023] | masks[2024]).sum()),
            validation_rows=int(masks[2025].sum()),
            metrics=d0_metrics_2025,
        )
    )
    probabilities_2025: dict[str, np.ndarray] = {"D0": d0_2025}
    final_train = masks[2023] | masks[2024]
    for candidate in candidates[1:]:
        candidate_id = str(candidate["candidateId"])
        started = time.perf_counter()
        _emit(
            progress,
            "REFITTING_DYNAMIC_THROUGH_2024_VALIDATING_2025",
            {"candidateId": candidate_id, "selectedCandidateId": selected_id},
        )
        try:
            model, n_iter, _ = run_blocking_with_heartbeat(
                lambda: _fit_logistic(
                    arrays,
                    CANDIDATE_FEATURES[candidate_id],
                    final_train,
                    c_value=selected_c[candidate_id],
                    max_iter=max_iter,
                ),
                stage="REFITTING_DYNAMIC_THROUGH_2024_VALIDATING_2025",
                candidate_id=candidate_id,
                progress=progress,
            )
        except TrainingIntegrityError as exc:
            raise DynamicTrainingIntegrityError(str(exc)) from exc
        probabilities = model.predict_proba(arrays.feature_values, masks[2025])
        metrics_2025 = evaluate_multiclass(arrays.labels[masks[2025]], probabilities)
        probabilities_2025[candidate_id] = probabilities
        models[(2025, candidate_id)] = model
        candidate["foldMetrics"].append(
            _fold_record(
                fold_id=FOLD_2025_ID,
                training_seasons=[2023, 2024],
                validation_season=2025,
                training_rows=int(final_train.sum()),
                validation_rows=int(masks[2025].sum()),
                metrics=metrics_2025,
            )
        )
        candidate["convergence"]["nIter"] = max(candidate["convergence"]["nIter"], n_iter)
        candidate["runtimeSeconds"] = round(
            float(candidate["runtimeSeconds"]) + time.perf_counter() - started,
            6,
        )
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
    return DynamicTrainingExperiment(
        arrays=built_arrays,
        candidates=candidates,
        selected_candidate_id=selected_id,
        selected_rationale=selected_rationale,
        folds=folds,
        models=models,
        split_evidence=split,
        d0_artifact_shas={season: d0_folds[season].artifact_sha for season in (2024, 2025)},
    )


def _metric_nonworse(scaled: Mapping[str, Any], raw: Mapping[str, Any]) -> bool:
    return (
        float(scaled["logLoss"]) <= float(raw["logLoss"]) + DECISION_TOLERANCE
        and float(scaled["brierScore"]) <= float(raw["brierScore"]) + DECISION_TOLERANCE
    )


def calibrate_dynamic_experiment(
    experiment: DynamicTrainingExperiment,
) -> tuple[dict[str, Any], dict[int, np.ndarray], dict[int, np.ndarray]]:
    selected_id = experiment.selected_candidate_id
    fold_2024 = experiment.folds[2024]
    fold_2025 = experiment.folds[2025]
    raw_2024 = fold_2024.probabilities[selected_id]
    raw_2025 = fold_2025.probabilities[selected_id]
    fit = fit_temperature_scaling(
        fold_2024.labels,
        raw_2024,
        source_seasons=np.full(fold_2024.labels.size, 2024, dtype=np.int64),
    )
    scaled_2024 = fit.scaled_probabilities
    scaled_2025 = temperature_scale(raw_2025, fit.fitted_temperature)
    raw_metrics = {
        2024: fit.raw_evidence,
        2025: evaluate_multiclass(fold_2025.labels, raw_2025),
    }
    scaled_metrics = {
        2024: fit.scaled_evidence,
        2025: evaluate_multiclass(fold_2025.labels, scaled_2025),
    }
    eligible_2024 = bool(fit.retained and _metric_nonworse(scaled_metrics[2024], raw_metrics[2024]))
    nonworse_2025 = _metric_nonworse(scaled_metrics[2025], raw_metrics[2025])
    retained = bool(eligible_2024 and nonworse_2025)
    scaled = {2024: scaled_2024, 2025: scaled_2025}
    final = {
        2024: scaled_2024 if retained else raw_2024,
        2025: scaled_2025 if retained else raw_2025,
    }
    payload = {
        "schemaVersion": DYNAMIC_CALIBRATION_SCHEMA_VERSION,
        "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
        "candidateId": selected_id,
        "fitSeason": 2024,
        "applicationSeason": 2025,
        "fittedTemperature": fit.fitted_temperature,
        "eligibleOn2024": eligible_2024,
        "nonWorseningOn2025": nonworse_2025,
        "retainedAfter2025Gate": retained,
        "finalVariant": "SCALED" if retained else "RAW",
        "raw": {str(season): raw_metrics[season] for season in (2024, 2025)},
        "scaled": {str(season): scaled_metrics[season] for season in (2024, 2025)},
        "final": {
            str(season): evaluate_multiclass(experiment.folds[season].labels, final[season])
            for season in (2024, 2025)
        },
        "retentionRule": (
            "Scaled log loss and summed multiclass Brier must each be non-worse on the 2024 "
            "fit/eligibility fold and again on the governing 2025 fold within 1e-10."
        ),
        "rawAndScaledPreserved": True,
    }
    return payload, scaled, final


def _selected_state_prefixes(candidate_id: str) -> tuple[str, ...]:
    return {
        "D1": ("batter_b",),
        "D2": ("pitcher_b",),
        "D3": ("batter_b", "pitcher_b"),
        "D4": ("batter_c", "pitcher_c"),
    }[candidate_id]


def _coverage(
    experiment: DynamicTrainingExperiment,
    final_probabilities: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    arrays = experiment.arrays.training
    prefixes = _selected_state_prefixes(experiment.selected_candidate_id)
    rows: list[dict[str, Any]] = []
    role_coverage: list[dict[str, Any]] = []
    for season in (2024, 2025):
        season_mask = arrays.seasons == season
        missing_columns = [arrays.feature_values[f"{prefix}_missing_history"] for prefix in prefixes]
        ess_columns = [arrays.feature_values[f"{prefix}_effective_sample_size"] for prefix in prefixes]
        combined_missing = np.logical_or.reduce([column > 0.5 for column in missing_columns])
        combined_ess = np.minimum.reduce(ess_columns)
        for prefix, missing_values, ess_values in zip(
            prefixes, missing_columns, ess_columns, strict=True
        ):
            role_coverage.append(
                {
                    "validationSeason": season,
                    "statePrefix": prefix,
                    "rowCount": int(season_mask.sum()),
                    "missingHistoryRows": int(np.count_nonzero(season_mask & (missing_values > 0.5))),
                    "effectiveSampleSizeMin": float(np.min(ess_values[season_mask])),
                    "effectiveSampleSizeMedian": float(np.median(ess_values[season_mask])),
                    "effectiveSampleSizeMax": float(np.max(ess_values[season_mask])),
                }
            )
        groups = (
            ("MISSING_HISTORY", combined_missing),
            ("HAS_HISTORY_ESS_LT_100", (~combined_missing) & (combined_ess < 100.0)),
            (
                "HAS_HISTORY_ESS_100_TO_299",
                (~combined_missing) & (combined_ess >= 100.0) & (combined_ess < 300.0),
            ),
            ("HAS_HISTORY_ESS_GE_300", (~combined_missing) & (combined_ess >= 300.0)),
        )
        raw = experiment.folds[season].probabilities[experiment.selected_candidate_id]
        final = final_probabilities[season]
        for subgroup, group_all in groups:
            group = group_all[season_mask]
            count = int(group.sum())
            rows.append(
                {
                    "validationSeason": season,
                    "subgroup": subgroup,
                    "rowCount": count,
                    "rawMetrics": (
                        evaluate_multiclass(experiment.folds[season].labels[group], raw[group])
                        if count
                        else None
                    ),
                    "finalMetrics": (
                        evaluate_multiclass(experiment.folds[season].labels[group], final[group])
                        if count
                        else None
                    ),
                }
            )
    return {
        "schemaVersion": DYNAMIC_COVERAGE_SCHEMA_VERSION,
        "selectedCandidateId": experiment.selected_candidate_id,
        "selectedStatePrefixes": list(prefixes),
        "roleStateCoverage": role_coverage,
        "subgroups": rows,
        "missingHistoryDefinition": "any selected role/state has missing_history=true",
        "effectiveSampleSizeDefinition": "minimum ESS across selected role/state inputs",
    }


def dynamic_decision(
    experiment: DynamicTrainingExperiment,
    calibration: Mapping[str, Any],
    bootstrap: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_id = experiment.selected_candidate_id
    selected_candidate = experiment.candidate(selected_id)
    selected_raw = {
        season: selected_candidate["foldMetrics"][season - 2024]["metrics"]
        for season in (2024, 2025)
    }
    d0_metrics = {
        season: experiment.candidate("D0")["foldMetrics"][season - 2024]["metrics"]
        for season in (2024, 2025)
    }
    raw_loss_rule = all(
        selected_raw[season]["logLoss"] < d0_metrics[season]["logLoss"] - DECISION_TOLERANCE
        and selected_raw[season]["brierScore"]
        <= d0_metrics[season]["brierScore"] + DECISION_TOLERANCE
        for season in (2024, 2025)
    )
    calibration_defects = {
        str(season): {
            "topLabelEceExcess": float(selected_raw[season]["topLabelEce"])
            - float(d0_metrics[season]["topLabelEce"]),
            "classwiseEceExcess": {
                class_name: float(selected_raw[season]["classwiseEce"][class_name])
                - float(d0_metrics[season]["classwiseEce"][class_name])
                for class_name in PA_CLASS_ORDER
            },
        }
        for season in (2024, 2025)
    }
    no_meaningful_calibration_defect = all(
        evidence["topLabelEceExcess"] <= CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE
        and all(
            value <= CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE
            for value in evidence["classwiseEceExcess"].values()
        )
        for evidence in calibration_defects.values()
    )
    worse_both_folds = all(
        selected_raw[season]["logLoss"] > d0_metrics[season]["logLoss"] + DECISION_TOLERANCE
        and selected_raw[season]["brierScore"]
        > d0_metrics[season]["brierScore"] + DECISION_TOLERANCE
        for season in (2024, 2025)
    )
    if raw_loss_rule and no_meaningful_calibration_defect:
        value = "DYNAMIC_STATE_RESEARCH_CHALLENGER"
        rationale = "Raw selected dynamic probabilities beat frozen D0 on the governing loss rule in both folds without a meaningful raw calibration defect."
    elif worse_both_folds:
        value = "DYNAMIC_STATE_REJECTED"
        rationale = "Selected dynamic state is worse than frozen D0 on both governing losses in both folds."
    else:
        value = "DYNAMIC_STATE_RESEARCH_BASELINE"
        rationale = "The run is valid, but improvement, uncertainty, or fold consistency does not satisfy the frozen challenger or rejection rule."
    if value not in DECISION_ENUM:
        raise AssertionError("dynamic decision escaped the frozen enum")
    return {
        "decision": value,
        "selectedCandidateId": selected_id,
        "decisionProbabilityVariant": "RAW",
        "rawLossRuleSatisfied": raw_loss_rule,
        "noMeaningfulRawCalibrationDefect": no_meaningful_calibration_defect,
        "calibrationDefectTolerance": CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE,
        "calibrationDefects": calibration_defects,
        "bootstrapUsedAsDecisionGate": False,
        "bootstrapEvidenceRows": len(bootstrap),
        "scaledEvidenceCanEarnChallenger": False,
        "rejectionRuleSatisfied": worse_both_folds,
        "rationale": rationale,
        "researchOnly": True,
        "deploymentAuthorized": False,
    }


def evaluate_dynamic_experiment(
    experiment: DynamicTrainingExperiment,
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    progress: Any | None = None,
) -> DynamicEvaluationEvidence:
    if not isinstance(bootstrap_resamples, int) or isinstance(bootstrap_resamples, bool):
        raise ValueError("bootstrap_resamples must be an integer")
    if bootstrap_resamples < 2:
        raise ValueError("bootstrap_resamples must be at least two")
    calibration, scaled, final = calibrate_dynamic_experiment(experiment)
    bootstrap: list[dict[str, Any]] = []
    selected_id = experiment.selected_candidate_id
    for season in (2024, 2025):
        fold = experiment.folds[season]
        for variant, probabilities in (
            ("RAW", fold.probabilities[selected_id]),
            ("FINAL", final[season]),
        ):
            _emit(
                progress,
                "GAME_CLUSTER_BOOTSTRAP_DYNAMIC_VS_D0",
                {
                    "validationSeason": season,
                    "probabilityVariant": variant,
                    "resamples": bootstrap_resamples,
                },
            )
            evidence = game_cluster_bootstrap(
                fold.labels,
                probabilities,
                fold.probabilities["D0"],
                fold.game_ids,
                n_resamples=bootstrap_resamples,
                seed=bootstrap_seed,
            )
            bootstrap.append(
                {
                    "schemaVersion": DYNAMIC_BOOTSTRAP_SCHEMA_VERSION,
                    "candidateId": selected_id,
                    "baselineCandidateId": "D0",
                    "foldId": fold.fold_id,
                    "validationSeason": season,
                    "probabilityVariant": variant,
                    "clusterUnit": "game_id",
                    "resamples": bootstrap_resamples,
                    "seed": bootstrap_seed,
                    "evidence": evidence,
                }
            )
    coverage = _coverage(experiment, final)
    decision = dynamic_decision(experiment, calibration, bootstrap)
    return DynamicEvaluationEvidence(
        calibration=calibration,
        bootstrap=bootstrap,
        coverage=coverage,
        decision=decision,
        scaled_probabilities=scaled,
        final_probabilities=final,
    )


__all__ = [
    "DYNAMIC_BOOTSTRAP_SCHEMA_VERSION",
    "DYNAMIC_CALIBRATION_SCHEMA_VERSION",
    "DYNAMIC_COVERAGE_SCHEMA_VERSION",
    "DYNAMIC_TRAINING_SCHEMA_VERSION",
    "DynamicEvaluationEvidence",
    "DynamicTrainingExperiment",
    "DynamicTrainingIntegrityError",
    "FrozenD0Fold",
    "dynamic_training_arrays",
    "dynamic_decision",
    "calibrate_dynamic_experiment",
    "evaluate_dynamic_experiment",
    "run_dynamic_training_experiment",
    "run_blocking_with_heartbeat",
]
