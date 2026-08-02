from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import os
import platform
from threading import Event, Lock, Thread
import time
from typing import Any, Tuple
from uuid import uuid4

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import validate_checkpoint_identity
from ..datasets.dataset_identity import assert_expected_active_identity
from ..persistence.service import get_persistence_service
from .candidate_contract import (
    CandidateContractError,
    assert_candidate_contract_intact,
    assert_training_contract_intact,
    build_candidate_contract,
    canonical_contract_hash,
    complete_training_contract,
)
from .trainer import MODEL_CATALOG, selection_sort_key, train_models
from .trainer_service import TRAINER
from .training_job_types import TrainingJobRequest, TrainingPortfolioRequest
from .training_preflight_service import training_preflight


TERMINAL_STATES = {"complete", "failed", "cancelled", "interrupted"}
ACTIVE_STATES = {"queued", "preparing", "running"}
CANCELLED_MESSAGE = "Training stopped by user. Completed model results were preserved; unfinished models were cancelled."

# Stage 4 (ATLAS_MODELING_STATE_ISOLATION_PLAN.md): TRAINING_JOBS project
# isolation and authorization.
#
# Job ownership/scope is made EXPLICIT on the job record itself
# (`owner_user_id`, `project_id`), not derived from ambient context, per
# this stage's requirement that background execution not depend on
# contextvars propagating into worker threads. Verified in Stage 2B/3 (and
# unchanged here): a bare threading.Thread/ThreadPoolExecutor does NOT
# inherit contextvars.Context. TRAINING_JOBS never actually relied on that
# propagation for correctness -- create() already ran entirely on the
# request thread (where authorize_modeling_scope's ContextVar mutation IS
# visible), reading DATASTORE and capturing a RESULTS ResultStore INSTANCE
# (`job["_result_store"] = RESULTS.current()`) before the background thread
# ever starts; the background thread receives only X_train/y_train
# as plain function arguments and writes results through that already-
# captured store INSTANCE, never re-deriving scope from ambient state. This
# stage adds `owner_user_id`/`project_id` as the SAME kind of explicit,
# immutable-once-set, request-thread-captured job-record fields -- not a
# new propagation mechanism, the same one already proven to work.
#
# Storage: `_jobs` stays keyed by `job_id` (already a globally-unique
# uuid4-derived string, addressed directly by the `/model/train/jobs/
# {job_id}` URL) -- re-keying it by (user_id, project_id) would make direct
# job_id lookups ambiguous. Instead, `_project_job_ids` is a SEPARATE,
# explicitly structured `Dict[Tuple[str, str], list[str]]` index (never a
# concatenated string) mapping (owner_user_id, project_id) -> ordered
# job_ids, used for project-scoped listing (`active()`/history). Every
# accessor that takes a job_id (`get`, `cancel`) ALSO requires the caller's
# (owner_user_id, project_id) and checks it against the job record's own
# fields -- authorization is never inferred from job_id possession alone.
ScopeKey = Tuple[str, str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _friendly_error(model: str, error: Any) -> str:
    label = str(MODEL_CATALOG.get(model, {}).get("label") or model)
    detail = str(error or "Model fit failed.").strip().splitlines()[0]
    lowered = detail.lower()
    if "infinity" in lowered or "infinite" in lowered:
        return f"{label} failed because the training matrix contains infinite values."
    if "nan" in lowered or "missing" in lowered:
        return f"{label} failed because unresolved missing values reached an unsupported estimator stage."
    if "class" in lowered and ("one" in lowered or "2" in lowered or "two" in lowered):
        return f"{label} failed because a governed training fold does not contain the required target classes."
    if "memory" in lowered:
        return f"{label} exceeded the available local memory limit. Reduce features, data, or parallel workers."
    if "could not be initialized" in lowered or "unavailable" in lowered or "not installed" in lowered:
        return f"{label} is unavailable in the current Python environment."
    return f"{label} failed: {detail}"


def _record_matches_identity(
    record: dict[str, Any],
    identity: dict[str, Any],
) -> bool:
    if not record or not identity:
        return False
    if any(
        not str(record.get(key) or "").strip()
        or str(record.get(key)) != str(identity.get(key) or "")
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        return False
    legacy = str(record.get("dataset_version") or "").strip()
    return not legacy or legacy == str(identity["dataset_version_id"])


class TrainingJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, Event] = {}
        self._project_job_ids: dict[ScopeKey, list[str]] = {}
        self._idempotency_job_ids: dict[tuple[str, str, str], str] = {}
        self._lock = Lock()

    def preflight(self, request: TrainingJobRequest) -> dict[str, Any]:
        result = training_preflight(request)
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            previous = (
                scoped_store.meta.get("training_preflight")
                if isinstance(
                    scoped_store.meta.get("training_preflight"), dict
                )
                else {}
            )
            if previous and str(previous.get("state_hash") or "") != str(
                result.get("state_hash") or ""
            ):
                core_keys = (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                    "feature_manifest_id",
                    "feature_manifest_version",
                    "validation_design_id",
                    "validation_design_version",
                    "split_id",
                    "canonical_data_revision",
                )
                complete_invalidation = any(
                    str(previous.get(key) or "")
                    != str(result.get(key) or "")
                    for key in core_keys
                )
                result["invalidated_preflight_id"] = previous.get(
                    "preflight_id"
                )
                result["invalidation_scope"] = (
                    "complete_preflight"
                    if complete_invalidation
                    else "algorithm_dependent_checks"
                )
                result["invalidation_reason"] = (
                    "Canonical dataset, feature-manifest, or Validation Design state changed."
                    if complete_invalidation
                    else "The selected algorithm portfolio or algorithm-dependent runtime policy changed."
                )
            else:
                result["invalidated_preflight_id"] = None
                result["invalidation_scope"] = "none"
                result["invalidation_reason"] = None
            scoped_store.meta["training_preflight"] = deepcopy(result)
        schedule_checkpoint_save()
        return result

    @staticmethod
    def _portfolio_state_payload(
        request: TrainingPortfolioRequest,
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        algorithms = list(
            dict.fromkeys(str(key) for key in request.selected_algorithm_ids)
        )
        unknown = [key for key in algorithms if key not in MODEL_CATALOG]
        if unknown:
            raise ValueError(
                "Unknown model algorithms cannot be persisted: "
                + ", ".join(unknown)
            )
        return {
            "project_id": str(identity["project_id"]),
            "dataset_id": str(identity["dataset_id"]),
            "dataset_version_id": str(identity["dataset_version_id"]),
            "selected_algorithm_ids": algorithms,
            "candidate_strategy": str(request.candidate_strategy),
            "problem_type": str(request.problem_type),
            "max_parallel": int(request.max_parallel),
            "calibrate": bool(request.calibrate),
            "grid_search": bool(request.grid_search),
            "grid_search_level": str(request.grid_search_level),
            "primary_metric": str(request.primary_metric),
        }

    def get_portfolio(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> dict[str, Any]:
        identity = assert_expected_active_identity(
            project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            require_expected=True,
        )
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            record = (
                deepcopy(scoped_store.meta.get("training_model_portfolio"))
                if isinstance(
                    scoped_store.meta.get("training_model_portfolio"), dict
                )
                else None
            )
        if record is not None and any(
            str(record.get(key) or "") != str(identity.get(key) or "")
            for key in ("project_id", "dataset_id", "dataset_version_id")
        ):
            raise ValueError(
                "The saved model portfolio belongs to a different canonical dataset identity."
            )
        if record is None:
            payload = {
                **identity,
                "selected_algorithm_ids": [],
                "candidate_strategy": "custom_portfolio",
                "selection_revision": 0,
                "selection_state_hash": canonical_contract_hash(
                    {
                        **identity,
                        "selected_algorithm_ids": [],
                        "candidate_strategy": "custom_portfolio",
                    }
                ),
                "persisted_at": None,
            }
            return payload
        return record

    def save_portfolio(
        self,
        request: TrainingPortfolioRequest,
        *,
        persisted_by: str,
    ) -> dict[str, Any]:
        identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            require_expected=True,
        )
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            result = self._save_portfolio_locked(
                scoped_store,
                request,
                identity=identity,
                persisted_by=persisted_by,
            )
        schedule_checkpoint_save()
        return result

    def _save_portfolio_locked(
        self,
        scoped_store: Any,
        request: TrainingPortfolioRequest,
        *,
        identity: dict[str, Any],
        persisted_by: str,
    ) -> dict[str, Any]:
        """Persist after the caller has locked and revalidated the scope."""
        state_payload = self._portfolio_state_payload(request, identity)
        state_hash = canonical_contract_hash(state_payload)
        current = (
            scoped_store.meta.get("training_model_portfolio")
            if isinstance(
                scoped_store.meta.get("training_model_portfolio"), dict
            )
            else {}
        )
        current_revision = int(current.get("selection_revision") or 0)
        if (
            request.expected_selection_revision
            and request.expected_selection_revision != current_revision
        ):
            raise ValueError(
                "The model portfolio changed before this save completed. Refresh the authoritative selection and retry."
            )
        if str(current.get("selection_state_hash") or "") == state_hash:
            return deepcopy(current)
        record = {
            **state_payload,
            "selection_revision": current_revision + 1,
            "selection_state_hash": state_hash,
            "persisted_at": _now(),
            "persisted_by": str(persisted_by),
            "client_portfolio_revision": int(
                request.client_portfolio_revision
                or request.portfolio_revision
            ),
        }
        scoped_store.meta["training_model_portfolio"] = record
        latest_preflight = scoped_store.meta.get("training_preflight")
        if isinstance(latest_preflight, dict) and list(
            latest_preflight.get("selected_algorithm_ids") or []
        ) != list(record["selected_algorithm_ids"]):
            latest_preflight.update(
                {
                    "stale": True,
                    "stale_reason": "The selected algorithm portfolio changed.",
                    "invalidation_scope": "algorithm_dependent_checks",
                }
            )
        return deepcopy(record)

    def latest_preflight(
        self,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> dict[str, Any] | None:
        identity = assert_expected_active_identity(
            project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            require_expected=True,
        )
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            result = (
                deepcopy(scoped_store.meta.get("training_preflight"))
                if isinstance(scoped_store.meta.get("training_preflight"), dict)
                else None
            )
        if result is not None and any(
            str(result.get(key) or "") != str(identity.get(key) or "")
            for key in ("project_id", "dataset_id", "dataset_version_id")
        ):
            raise ValueError(
                "The stored preflight belongs to a different canonical dataset identity."
            )
        return result

    @staticmethod
    def _creation_response(
        job: dict[str, Any],
        *,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "training_job_id": job["job_id"],
            "training_run_id": job["training_run_id"],
            "status": job["overall_status"],
            "overall_status": job["overall_status"],
            "project_id": job["project_id"],
            "dataset_id": job["dataset_id"],
            "dataset_version_id": job["dataset_version_id"],
            "dataset_version": job["dataset_version_id"],
            "requested_models": list(job["requested_models"]),
            "selected_algorithm_ids": list(job["requested_models"]),
            "created_at": job["created_at"],
            "max_parallel_honored": job["max_parallel_honored"],
            "preflight": deepcopy(job["preflight"]),
            "preflight_id": job["preflight"].get("preflight_id"),
            "preflight_state_hash": job["preflight"].get("state_hash"),
            "idempotent_replay": bool(idempotent_replay),
            "creation_duration_ms": int(job.get("creation_duration_ms") or 0),
        }

    def _find_idempotent_job_locked(
        self,
        *,
        owner_user_id: str,
        project_id: str,
        idempotency_token: str,
        submission_hash: str,
        explicit: bool,
    ) -> dict[str, Any] | None:
        key = (owner_user_id, project_id, idempotency_token)
        job_id = self._idempotency_job_ids.get(key)
        if not job_id:
            return None
        job = self._jobs.get(job_id)
        if not job:
            self._idempotency_job_ids.pop(key, None)
            return None
        if str(job.get("submission_hash") or "") != submission_hash:
            raise ValueError(
                "The idempotency key was already used for a different governed training submission."
            )
        if explicit or str(job.get("overall_status") or "") in ACTIVE_STATES:
            return job
        # Implicit hashes only coalesce concurrently-active jobs. An explicit
        # new user action can intentionally rerun a completed portfolio.
        self._idempotency_job_ids.pop(key, None)
        return None

    def create(self, request: TrainingJobRequest, owner_user_id: str) -> dict[str, Any]:
        create_started = time.perf_counter()
        scoped_store = DATASTORE.current()
        scoped_results = RESULTS.current()
        with scoped_store.state_lock:
            preflight_data_revision = int(scoped_store.data_revision)
        preflight = self.preflight(request)
        if not preflight["ready"]:
            raise ValueError("Training preflight blocked job creation: " + " | ".join(preflight["blocking_errors"]))
        if (
            request.expected_preflight_id
            and request.expected_preflight_id != preflight.get("preflight_id")
        ):
            raise ValueError(
                "The validated preflight is stale because the governed training state changed. Run validation again."
            )
        if (
            request.expected_preflight_state_hash
            and request.expected_preflight_state_hash
            != preflight.get("state_hash")
        ):
            raise ValueError(
                "The validated preflight state hash is stale. Run validation again."
            )
        models = list(dict.fromkeys(request.models))
        if not models:
            raise ValueError("No supported models were selected for training.")
        inherited_folds = int(
            preflight.get("cross_validation_compatibility", {}).get(
                "effective_folds"
            )
            or request.k_folds
        )
        estimated_fits = int(preflight.get("estimated_fits") or 0)
        if (
            bool((preflight.get("large_run") or {}).get("required"))
            and not request.large_job_confirmed
        ):
            raise ValueError(
                f"This plan is a large job ({estimated_fits} estimated fits). "
                "Review the workload and explicitly confirm the run."
            )

        portfolio_request = TrainingPortfolioRequest(
            project_id=request.project_id,
            dataset_id=str(preflight["dataset_id"]),
            dataset_version_id=str(preflight["dataset_version_id"]),
            selected_algorithm_ids=models,
            candidate_strategy=request.candidate_strategy,
            problem_type=str(preflight["problem_type"]),
            max_parallel=request.max_parallel,
            calibrate=request.calibrate,
            grid_search=request.grid_search,
            grid_search_level=request.grid_search_level,
            primary_metric=request.primary_metric,
        )
        preflight["portfolio_persistence_status"] = "pending_atomic_commit"

        submission_hash = canonical_contract_hash(
            {
                "preflight_state_hash": preflight.get("state_hash"),
                "selected_algorithm_ids": models,
                "model_params": request.model_params,
                "random_seed": request.random_seed,
                "grid_search": request.grid_search,
                "grid_search_level": request.grid_search_level,
                "calibrate": request.calibrate,
                "max_parallel": request.max_parallel,
                "candidate_strategy": request.candidate_strategy,
                "primary_metric": request.primary_metric,
                "retry_parent_job_id": request.retry_parent_job_id,
            }
        )
        explicit_idempotency = bool(request.idempotency_key.strip())
        idempotency_token = (
            request.idempotency_key.strip()
            if explicit_idempotency
            else f"submission:{submission_hash}"
        )
        with self._lock:
            replay = self._find_idempotent_job_locked(
                owner_user_id=owner_user_id,
                project_id=request.project_id,
                idempotency_token=idempotency_token,
                submission_hash=submission_hash,
                explicit=explicit_idempotency,
            )
            if replay is not None:
                return self._creation_response(
                    replay, idempotent_replay=True
                )

        X_train, y_train, excluded = TRAINER._get_training_partition(
            inherited_folds
        )
        trained_feature_names = [str(column) for column in X_train.columns]
        requested_parallel = max(1, int(request.max_parallel or 1))
        safe_parallel = min(
            requested_parallel,
            int(preflight.get("recommended_parallelism") or 1),
            len(models),
            max(1, min(4, os.cpu_count() or 1)),
        )
        job_id = f"train-job-{uuid4().hex}"
        training_run_id = f"train-run-{uuid4().hex}"
        created_at = _now()
        queued_status = {
            model: {
                "status": "queued",
                "state": "queued",
                "queued_at": created_at,
                "started_at": None,
                "completed_at": None,
                "runtime_ms": 0,
                "current_stage": "Waiting for local worker",
                "metrics": None,
                "warning": None,
                "user_error": None,
                "technical_error": None,
                "traceback_reference": None,
                "best_parameters": None,
                "search_summary": None,
                "message": "Queued for training.",
            }
            for model in models
        }
        history = {
            model: [{"state": "queued", "at": created_at, "stage": "Waiting for local worker"}]
            for model in models
        }
        manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
        split_record = DATASTORE.meta.get("split_record") if isinstance(DATASTORE.meta.get("split_record"), dict) else {}
        raw_cv_splits = (
            split_record.get("cv_execution_splits")
            if isinstance(split_record.get("cv_execution_splits"), list)
            else []
        )
        governed_cv_splits: list[tuple[list[int], list[int]]] = [
            (
                [int(value) for value in fold.get("train_positions") or []],
                [
                    int(value)
                    for value in fold.get("validation_positions") or []
                ],
            )
            for fold in raw_cv_splits
            if isinstance(fold, dict)
        ]
        job: dict[str, Any] = {
            "job_id": job_id,
            "training_run_id": training_run_id,
            "submission_hash": submission_hash,
            "idempotency_key": (
                request.idempotency_key.strip()
                if explicit_idempotency
                else None
            ),
            "overall_status": "queued",
            "created_at": created_at,
            "started_at": None,
            "completed_at": None,
            "requested_models": models,
            "completed_count": 0,
            "finished_count": 0,
            "total_count": len(models),
            "current_models": [],
            "queued_models": list(models),
            "completed_models": [],
            "per_model_status": queued_status,
            "per_model_history": history,
            "partial_results": [],
            "partial_ranked_results": [],
            "failed_models": [],
            "user_message": "Training job queued.",
            "message": "Training job queued.",
            "developer_details": [],
            "runtime_ms": 0,
            "cancellation_requested": False,
            "max_parallel_requested": requested_parallel,
            "max_parallel_honored": safe_parallel,
            "estimated_fits": estimated_fits,
            "input_feature_names": trained_feature_names,
            "trained_feature_names": trained_feature_names,
            "engineered_feature_names": list(preflight.get("engineered_features") or []),
            "transformed_feature_names": [],
            "feature_count": len(trained_feature_names),
            "n_features": len(trained_feature_names),
            "dataset_id": preflight["dataset_id"],
            "dataset_version_id": preflight["dataset_version_id"],
            # Transitional response compatibility only.
            "dataset_version": preflight["dataset_version_id"],
            "data_revision": preflight_data_revision,
            "feature_manifest_version": preflight["feature_manifest_version"],
            "split_id": preflight["split_id"],
            "training_population_id": preflight["training_population_id"],
            "selection_partition_id": preflight["selection_partition_id"],
            "holdout_population_id": preflight["holdout_population_id"],
            "final_holdout_partition_id": preflight[
                "final_holdout_partition_id"
            ],
            "fold_definition_id": preflight["fold_definition_id"],
            "final_holdout_status": preflight["final_holdout_status"],
            "holdout_isolation_status": preflight[
                "holdout_isolation_status"
            ],
            "selection_resampling_status": preflight[
                "selection_resampling_status"
            ],
            "validation_design_id": preflight.get("validation_design_id"),
            "validation_design_version": preflight.get(
                "validation_design_version"
            ),
            "project_id": request.project_id,
            "owner_user_id": owner_user_id,
            "problem_type": preflight["problem_type"],
            "target": preflight["target"],
            "event_value": preflight["event_value"],
            "non_event_value": preflight["non_event_value"],
            "preflight": preflight,
            "creation_duration_ms": 0,
            "summary": None,
            "contract": {
                "project_id": request.project_id,
                "dataset_id": preflight["dataset_id"],
                "dataset_version_id": preflight["dataset_version_id"],
                "dataset_version": preflight["dataset_version_id"],
                "data_revision": preflight_data_revision,
                "target": preflight["target"],
                "problem_type": preflight["problem_type"],
                "event_value": preflight["event_value"],
                "non_event_value": preflight["non_event_value"],
                "feature_manifest_version": preflight["feature_manifest_version"],
                "selected_original_features": preflight["selected_original_features"],
                "selected_engineered_features": preflight["engineered_features"],
                "preprocessing_pipeline": request.preprocessing_pipeline or manifest.get("pipeline_steps", []),
                "split_id": preflight["split_id"],
                "training_population_id": preflight[
                    "training_population_id"
                ],
                "selection_partition_id": preflight[
                    "selection_partition_id"
                ],
                "holdout_population_id": preflight[
                    "holdout_population_id"
                ],
                "final_holdout_partition_id": preflight[
                    "final_holdout_partition_id"
                ],
                "fold_definition_id": preflight["fold_definition_id"],
                "final_holdout_status": preflight["final_holdout_status"],
                "holdout_isolation_status": preflight[
                    "holdout_isolation_status"
                ],
                "selection_resampling_status": preflight[
                    "selection_resampling_status"
                ],
                "validation_design_id": preflight.get("validation_design_id"),
                "validation_design_version": preflight.get(
                    "validation_design_version"
                ),
                "validation_design": preflight.get("validation_design") or {},
                "cv_design": preflight.get("cv_design") or {},
                "fold_architecture": preflight.get("fold_architecture") or {},
                "cv_execution": {
                    "source": "approved_validation_design",
                    "exact_fold_bindings": bool(governed_cv_splits),
                    "execution_fold_count": len(governed_cv_splits),
                },
                "evaluation_population_role": preflight.get(
                    "evaluation_population_role"
                ),
                "test_reference": preflight.get("test_reference"),
                "oot_reference": preflight.get("oot_reference"),
                "split_configuration": split_record.get("config") or {},
                "balancing_policy": split_record.get("balancing_policy") or {},
                "random_seed": request.random_seed,
                "model_list": models,
                "candidate_strategy": request.candidate_strategy,
                "retry_parent_job_id": request.retry_parent_job_id or None,
                "tuning_configuration": {
                    "grid_search": request.grid_search,
                    "level": request.grid_search_level,
                    "folds": inherited_folds,
                    "source": "approved_validation_design",
                },
                "calibration_configuration": {"requested": request.calibrate, "compatibility": preflight["calibration_compatibility"]},
                "runtime_environment": {
                    "python_version": platform.python_version(),
                    "platform": platform.system(),
                    "cpu_count": os.cpu_count() or 1,
                    "requested_workers": requested_parallel,
                    "honored_workers": safe_parallel,
                    "execution_mode": "local_background_workers",
                },
                "user": request.user,
                "timestamp": request.requested_at or created_at,
            },
            "_result_store": scoped_results,
            "_dataset_store": scoped_store,
            "_artifacts": {},
            "_raw_results": {},
            "_candidate_contracts": {},
            "_excluded_target_features": excluded,
            "_futures": {},
            "_cv_execution_splits": governed_cv_splits,
        }
        job["contract"] = complete_training_contract(
            job["contract"],
            feature_manifest=manifest,
            store_meta={
                key: deepcopy(scoped_store.meta.get(key))
                for key in (
                    "outlier_application",
                    "missing_application",
                    "missing_validation",
                )
            },
            training_job_id=job_id,
            training_run_id=training_run_id,
            created_by=owner_user_id,
            created_at=created_at,
            primary_metric=request.primary_metric,
        )
        for contract_field in (
            "target_contract_id",
            "predictor_manifest_id",
            "predictor_manifest_hash",
            "treatment_manifest_id",
            "treatment_manifest_hash",
            "feature_manifest_id",
            "feature_manifest_hash",
            "materialization_id",
        ):
            job[contract_field] = job["contract"].get(contract_field)
        cancel_event = Event()
        scope_key: ScopeKey = (owner_user_id, request.project_id)
        replay_result: dict[str, Any] | None = None
        with scoped_store.state_lock:
            current, reason = self._scope_matches_job(job)
            if not current:
                raise ValueError(
                    "Training inputs changed during job creation: "
                    + (
                        reason
                        or "run preflight again for the current preparation state."
                    )
                )
            portfolio = self._save_portfolio_locked(
                scoped_store,
                portfolio_request,
                identity={
                    "project_id": request.project_id,
                    "dataset_id": preflight["dataset_id"],
                    "dataset_version_id": preflight[
                        "dataset_version_id"
                    ],
                },
                persisted_by=owner_user_id,
            )
            preflight["selection_revision"] = int(
                portfolio.get("selection_revision") or 0
            )
            preflight["portfolio_persistence_status"] = "persisted"
            with self._lock:
                replay = self._find_idempotent_job_locked(
                    owner_user_id=owner_user_id,
                    project_id=request.project_id,
                    idempotency_token=idempotency_token,
                    submission_hash=submission_hash,
                    explicit=explicit_idempotency,
                )
                if replay is not None:
                    replay_result = self._creation_response(
                        replay, idempotent_replay=True
                    )
                else:
                    job["creation_duration_ms"] = int(
                        (time.perf_counter() - create_started) * 1000
                    )
                    self._jobs[job_id] = job
                    self._cancel_events[job_id] = cancel_event
                    self._project_job_ids.setdefault(scope_key, []).append(job_id)
                    self._idempotency_job_ids[
                        (owner_user_id, request.project_id, idempotency_token)
                    ] = job_id
            if replay_result is None:
                scoped_store.meta["active_training_job_id"] = job_id

        if replay_result is not None:
            return replay_result

        Thread(
            target=self._run,
            args=(job_id, request, X_train.copy(), y_train.copy(), safe_parallel),
            daemon=True,
            name=f"atlas-{job_id}",
        ).start()
        schedule_checkpoint_save()
        return self._creation_response(job, idempotent_replay=False)

    def _owned_job_locked(self, job_id: str, owner_user_id: str, project_id: str) -> dict[str, Any] | None:
        """Look up a job by job_id, requiring it to be locked already, and
        return it ONLY if it belongs to (owner_user_id, project_id) -- never
        infer authorization from job_id possession alone (this stage's
        requirement 9/10). A job that exists but belongs to someone else, or
        to a different project, is indistinguishable from a job that does
        not exist at all: both return None here, both surface as 404 at the
        router. This also defeats job_id guessing/enumeration: a correct
        job_id for the WRONG owner or project is as useless as a random
        string. Caller must hold self._lock.
        """
        job = self._jobs.get(job_id)
        if not job or job["owner_user_id"] != owner_user_id or job["project_id"] != project_id:
            return None
        return job

    @staticmethod
    def _scope_matches_job(job: dict[str, Any]) -> tuple[bool, str]:
        """Validate a background job against its explicitly captured scope.

        Worker threads do not inherit request contextvars, so this must use the
        captured DatasetStore plus explicit owner/project identifiers.
        """
        store = job.get("_dataset_store")
        if store is None:
            return False, "The captured dataset scope is unavailable."
        try:
            assert_training_contract_intact(job.get("contract") or {})
        except CandidateContractError as exc:
            return False, str(exc)
        valid, reason, identity = validate_checkpoint_identity(
            store,
            owner_user_id=str(job.get("owner_user_id") or ""),
            project_id=str(job.get("project_id") or ""),
        )
        if not valid or identity is None:
            return False, reason or "The canonical dataset identity is unresolved."
        if any(
            str(job.get(key) or "") != str(identity.get(key) or "")
            for key in ("project_id", "dataset_id", "dataset_version_id")
        ):
            return False, "The active canonical dataset identity changed."
        if int(store.data_revision) != int(job.get("data_revision", -1)):
            return False, "The governed pre-training data revision changed."

        manifest = (
            store.meta.get("feature_manifest")
            if isinstance(store.meta.get("feature_manifest"), dict)
            else {}
        )
        split_record = (
            store.meta.get("split_record")
            if isinstance(store.meta.get("split_record"), dict)
            else {}
        )
        design = (
            split_record.get("validation_design")
            if isinstance(split_record.get("validation_design"), dict)
            else {}
        )
        if not _record_matches_identity(manifest, identity):
            return False, "The active feature manifest no longer matches the dataset."
        if not _record_matches_identity(split_record, identity):
            return False, "The active split no longer matches the dataset."
        if not _record_matches_identity(design, identity):
            return False, "The active validation design no longer matches the dataset."
        manifest_id = str(
            manifest.get("manifest_hash")
            or manifest.get("manifest_version")
            or ""
        )
        if manifest_id != str(job.get("feature_manifest_version") or ""):
            return False, "The active feature manifest changed."
        if str(split_record.get("split_id") or "") != str(job.get("split_id") or ""):
            return False, "The active split changed."
        if str(design.get("validation_design_id") or "") != str(
            job.get("validation_design_id") or ""
        ):
            return False, "The active validation design changed."
        if str(design.get("design_version") or "") != str(
            job.get("validation_design_version") or ""
        ):
            return False, "The active validation design version changed."
        if str(store.meta.get("split_status") or "") != "current":
            return False, "The active split is stale."
        return True, ""

    def _interrupt_if_scope_changed(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs[job_id]
            if job["overall_status"] == "interrupted":
                return True
            if job["overall_status"] == "cancelled":
                return False
            snapshot = dict(job)
        current, reason = self._scope_matches_job(snapshot)
        if current:
            return False
        with self._lock:
            job = self._jobs[job_id]
            event = self._cancel_events.get(job_id)
            if event:
                event.set()
            job["overall_status"] = "interrupted"
            job["completed_at"] = _now()
            job["user_message"] = (
                "Training interrupted because the governed dataset, feature "
                "manifest, split, or validation design changed. Run preflight again."
            )
            job["message"] = job["user_message"]
            job["developer_details"].append(
                {"stage": "canonical_scope_revalidation", "reason": reason}
            )
            for model, state in job["per_model_status"].items():
                if state.get("status") in ACTIVE_STATES:
                    state.update(
                        {
                            "status": "interrupted",
                            "state": "interrupted",
                            "completed_at": _now(),
                            "message": job["user_message"],
                            "current_stage": "Scope changed",
                        }
                    )
                    job["per_model_history"][model].append(
                        {
                            "state": "interrupted",
                            "at": _now(),
                            "stage": "Scope changed",
                            "message": reason,
                        }
                    )
        return True

    def get(self, job_id: str, owner_user_id: str, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._owned_job_locked(job_id, owner_user_id, project_id)
            if not job:
                return None
            active = job["overall_status"] in ACTIVE_STATES
        if active:
            self._interrupt_if_scope_changed(job_id)
        with self._lock:
            job = self._owned_job_locked(job_id, owner_user_id, project_id)
            if not job:
                return None
            return self._public_job(job)

    def active(self, owner_user_id: str, project_id: str) -> list[dict[str, Any]]:
        scope_key: ScopeKey = (owner_user_id, project_id)
        with self._lock:
            job_ids = list(self._project_job_ids.get(scope_key, []))
            jobs = [
                self._public_job(self._jobs[job_id])
                for job_id in job_ids
                if job_id in self._jobs and self._jobs[job_id]["overall_status"] in ACTIVE_STATES
            ]
        return sorted(jobs, key=lambda row: row["created_at"], reverse=True)

    def latest(
        self, owner_user_id: str, project_id: str
    ) -> dict[str, Any] | None:
        scope_key: ScopeKey = (owner_user_id, project_id)
        with self._lock:
            job_ids = list(self._project_job_ids.get(scope_key, []))
            if not job_ids:
                return None
            for job_id in reversed(job_ids):
                job = self._jobs.get(job_id)
                if job is not None:
                    return self._public_job(job)
        return None

    def cancel(self, job_id: str, owner_user_id: str, project_id: str) -> dict[str, Any] | None:
        public_job: dict[str, Any] | None = None
        with self._lock:
            job = self._owned_job_locked(job_id, owner_user_id, project_id)
            event = self._cancel_events.get(job_id)
            if not job or not event:
                return None
            if job["overall_status"] in TERMINAL_STATES:
                return self._public_job(job)
            event.set()
            job["cancellation_requested"] = True
            completed_at = _now()
            job["completed_at"] = completed_at
            job["overall_status"] = "cancelled"
            job["user_message"] = CANCELLED_MESSAGE
            job["message"] = job["user_message"]
            for model, state in job["per_model_status"].items():
                if state["status"] in ACTIVE_STATES:
                    state.update(
                        {
                            "status": "cancelled",
                            "state": "cancelled",
                            "completed_at": completed_at,
                            "current_stage": "Cancelled",
                            "message": "Cancelled by user before this model produced a persisted result.",
                        }
                    )
                    job["per_model_history"][model].append(
                        {
                            "state": "cancelled",
                            "at": completed_at,
                            "stage": "Cancelled",
                            "message": "Cancelled by user before this model produced a persisted result.",
                        }
                    )
            job["current_models"] = []
            job["queued_models"] = []
            job["finished_count"] = job["total_count"]
            if DATASTORE.meta.get("active_training_job_id") == job_id:
                DATASTORE.meta.pop("active_training_job_id", None)
            public_job = self._public_job(job)
        try:
            schedule_checkpoint_save()
        except Exception:
            pass
        return public_job

    def cancel_queued(
        self,
        job_id: str,
        owner_user_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._owned_job_locked(job_id, owner_user_id, project_id)
            if not job:
                return None
            if job["overall_status"] in TERMINAL_STATES:
                return self._public_job(job)
            cancelled_at = _now()
            cancelled_models: list[str] = []
            futures = job.get("_futures") or {}
            for model, future in futures.items():
                state = job["per_model_status"].get(model) or {}
                if state.get("status") != "queued":
                    continue
                if future.cancel():
                    cancelled_models.append(model)
                    state.update(
                        {
                            "status": "cancelled",
                            "state": "cancelled",
                            "completed_at": cancelled_at,
                            "current_stage": "Queued work cancelled",
                            "message": "Cancelled while queued; no fit was started.",
                        }
                    )
                    job["per_model_history"][model].append(
                        {
                            "state": "cancelled",
                            "at": cancelled_at,
                            "stage": "Queued work cancelled",
                            "message": "Cancelled while queued; no fit was started.",
                        }
                    )
            job["finished_count"] += len(cancelled_models)
            job["queued_models"] = [
                model
                for model in job.get("queued_models") or []
                if model not in cancelled_models
            ]
            job["user_message"] = (
                f"Cancelled {len(cancelled_models)} queued model(s); active fits continue."
                if cancelled_models
                else "No queued model could be cancelled; active fits continue."
            )
            job["message"] = job["user_message"]
            public = self._public_job(job)
        schedule_checkpoint_save()
        return public

    def _transition_model(self, job_id: str, model: str, state: str, message: str, stage: str, **values: Any) -> None:
        at = _now()
        with self._lock:
            job = self._jobs[job_id]
            current = job["per_model_status"][model]
            current.update({"status": state, "state": state, "message": message, "current_stage": stage, **values})
            if state in {"preparing", "running"} and not current.get("started_at"):
                current["started_at"] = at
            if state in TERMINAL_STATES:
                current["completed_at"] = at
            job["per_model_history"][model].append({"state": state, "at": at, "stage": stage, "message": message})
            job["current_models"] = sorted(key for key, status in job["per_model_status"].items() if status["status"] in {"preparing", "running"})
            job["queued_models"] = sorted(key for key, status in job["per_model_status"].items() if status["status"] == "queued")

    def _run(self, job_id: str, request: TrainingJobRequest, X_train, y_train, max_parallel: int) -> None:
        started = time.perf_counter()
        cancel_event = self._cancel_events[job_id]
        with self._lock:
            job = self._jobs[job_id]
            job["overall_status"] = "preparing"
            job["started_at"] = _now()
            job["user_message"] = "Preparing governed matrices and local model workers."
            job["message"] = job["user_message"]
        if self._interrupt_if_scope_changed(job_id):
            dataset_store = self._jobs[job_id].get("_dataset_store")
            if (
                dataset_store is not None
                and dataset_store.meta.get("active_training_job_id") == job_id
            ):
                dataset_store.meta.pop("active_training_job_id", None)
            schedule_checkpoint_save()
            return

        futures: dict[Future, str] = {}
        try:
            with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="atlas-model") as executor:
                with self._lock:
                    if self._jobs[job_id]["overall_status"] != "interrupted":
                        self._jobs[job_id]["overall_status"] = "running"
                        self._jobs[job_id]["user_message"] = f"0 of {self._jobs[job_id]['total_count']} models finished."
                        self._jobs[job_id]["message"] = self._jobs[job_id]["user_message"]
                for model in self._jobs[job_id]["requested_models"]:
                    futures[
                        executor.submit(
                            self._train_one,
                            job_id,
                            model,
                            request,
                            X_train,
                            y_train,
                        )
                    ] = model
                with self._lock:
                    self._jobs[job_id]["_futures"] = {
                        model: future for future, model in futures.items()
                    }
                for future in as_completed(futures):
                    model = futures[future]
                    if future.cancelled():
                        continue
                    if self._interrupt_if_scope_changed(job_id):
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        continue
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc), "model": model, "technical_error": repr(exc)}
                    self._record_result(job_id, model, result)
                    with self._lock:
                        job = self._jobs[job_id]
                        should_publish_partial = job["overall_status"] != "cancelled" and job["completed_count"] > 0
                    if should_publish_partial:
                        try:
                            if self._finalize(
                                job_id,
                                request,
                                X_train,
                                y_train,
                            ):
                                schedule_checkpoint_save()
                        except Exception as exc:
                            with self._lock:
                                job = self._jobs[job_id]
                                job["developer_details"].append({"stage": "partial_result_persistence", "error": repr(exc)})
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["developer_details"].append({"stage": "worker", "error": repr(exc)})
                job["user_message"] = "The background worker stopped unexpectedly. Review technical details and retry."
                job["message"] = job["user_message"]

        with self._lock:
            job = self._jobs[job_id]
            if job["overall_status"] == "cancelled":
                return
            job["runtime_ms"] = int((time.perf_counter() - started) * 1000)
            job["completed_at"] = _now()
            if job["overall_status"] == "interrupted":
                final_status = "interrupted"
                final_message = job["user_message"]
            elif cancel_event.is_set():
                final_status = "cancelled"
                final_message = f"Training cancelled after {job['finished_count']} of {job['total_count']} models finished."
            elif all(
                state.get("status") == "cancelled"
                for state in job["per_model_status"].values()
            ):
                final_status = "cancelled"
                final_message = "All queued models were cancelled before fitting."
            elif job["completed_count"] == 0:
                final_status = "failed"
                final_message = "No selected model completed successfully. Review each model's failure reason."
            else:
                final_status = "complete"
                final_message = f"{job['completed_count']} of {job['total_count']} models completed successfully."
            # Keep the externally visible state non-terminal until metrics,
            # artifacts, and the final summary persist successfully.
            job["overall_status"] = "running"
            job["user_message"] = "Model fitting finished. Persisting metrics and artifacts."
            job["message"] = job["user_message"]
        try:
            if not self._finalize(
                job_id,
                request,
                X_train,
                y_train,
                final_status=final_status,
            ):
                schedule_checkpoint_save()
                return
            with self._lock:
                job = self._jobs[job_id]
                job["overall_status"] = final_status
                job["user_message"] = final_message
                job["message"] = final_message
                if isinstance(job.get("summary"), dict):
                    job["summary"]["status"] = final_status
            schedule_checkpoint_save()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["overall_status"] = "failed"
                job["developer_details"].append({"stage": "result_persistence", "error": repr(exc)})
                job["user_message"] = "Model fitting finished, but ATLAS could not persist the training result. Retry after reviewing technical details."
                job["message"] = job["user_message"]
        finally:
            dataset_store = self._jobs[job_id].get("_dataset_store")
            if (
                dataset_store is not None
                and dataset_store.meta.get("active_training_job_id") == job_id
            ):
                dataset_store.meta.pop("active_training_job_id", None)

    def _train_one(self, job_id: str, model: str, request: TrainingJobRequest, X_train, y_train) -> dict[str, Any]:
        cancel_event = self._cancel_events[job_id]
        if cancel_event.is_set():
            return {"ok": False, "cancelled": True, "model": model, "error": "Cancelled before training started."}
        started = time.perf_counter()
        self._transition_model(job_id, model, "preparing", "Validating the model-specific training contract.", "Preparing matrices")
        if X_train.empty:
            raise ValueError("The governed training feature matrix is empty.")
        if cancel_event.is_set():
            return {"ok": False, "cancelled": True, "model": model, "error": "Cancelled during preparation."}
        effective_folds = int(
            self._jobs[job_id]["preflight"][
                "cross_validation_compatibility"
            ]["effective_folds"]
        )
        candidate_budget = (
            {"quick": 4, "balanced": 8, "thorough": 12}.get(
                str(request.grid_search_level).lower(), 4
            )
            if request.grid_search
            else 1
        )
        self._transition_model(
            job_id,
            model,
            "running",
            (
                "Estimator fit is running inside the approved validation "
                "architecture. The underlying estimator does not expose "
                "per-fold callbacks."
            ),
            f"Fitting estimator · {effective_folds} folds · up to {candidate_budget} tuning candidate(s)",
            current_fold=None,
            current_tuning_candidate=None,
            fold_progress_available=False,
        )
        calibration_info = self._jobs[job_id]["preflight"]["calibration_compatibility"].get(model, {})
        calibration_allowed = bool(request.calibrate and calibration_info.get("compatible"))
        result = train_models(
            X_train=X_train,
            y_train=y_train,
            requested_models=[model],
            grid_search=request.grid_search,
            grid_search_level=request.grid_search_level,
            model_params=request.model_params,
            calibrate=calibration_allowed,
            cv_folds=int(self._jobs[job_id]["preflight"]["cross_validation_compatibility"]["effective_folds"]),
            cv_splits=self._jobs[job_id].get("_cv_execution_splits") or None,
            primary_metric=request.primary_metric,
            positive_class=request.event_value,
            selection_partition_id=str(
                self._jobs[job_id].get("selection_partition_id") or ""
            ),
            fold_definition_id=str(
                self._jobs[job_id].get("fold_definition_id") or ""
            ),
            balancing_status=str(
                self._jobs[job_id].get("selection_resampling_status")
                or "not_applied"
            ),
        )
        result["runtime_ms"] = int((time.perf_counter() - started) * 1000)
        if request.calibrate and not calibration_allowed:
            result["warning"] = calibration_info.get("reason") or "Calibration was disabled for this model."
        return result

    def _record_result(self, job_id: str, model: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if (
                job["overall_status"] in {"cancelled", "interrupted"}
                or job["per_model_status"][model]["status"]
                in {"cancelled", "interrupted"}
            ):
                job["developer_details"].append(
                    {
                        "stage": "late_model_result_ignored",
                        "model": model,
                        "reason": (
                            "Result returned after cancellation or canonical "
                            "scope interruption."
                        ),
                    }
                )
                return
        runtime_ms = int(result.get("runtime_ms") or 0)
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        ranked = summary.get("ranked") if isinstance(summary.get("ranked"), list) else []
        artifacts = summary.pop("_artifacts", {}) if isinstance(summary, dict) else {}
        raw = summary.get("raw") if isinstance(summary.get("raw"), dict) else {}
        if result.get("cancelled"):
            self._transition_model(job_id, model, "cancelled", str(result.get("error")), "Cancelled", runtime_ms=runtime_ms)
        elif result.get("ok") and ranked:
            row = ranked[0]
            with self._lock:
                job = self._jobs[job_id]
                frozen_training_contract = deepcopy(job["contract"])
            try:
                candidate_contract = build_candidate_contract(
                    frozen_training_contract,
                    algorithm_id=model,
                    candidate_metrics=row,
                    artifact=artifacts.get(model),
                    created_at=_now(),
                )
                assert_candidate_contract_intact(candidate_contract)
            except CandidateContractError as exc:
                reference = f"training-contract-{uuid4().hex[:12]}"
                user_error = (
                    "The fitted model could not be bound to an immutable "
                    "governed candidate contract and was quarantined."
                )
                failure = {
                    "key": model,
                    "name": MODEL_CATALOG.get(model, {}).get("label", model),
                    "error": user_error,
                    "technical_error": str(exc),
                    "traceback_reference": reference,
                }
                with self._lock:
                    self._jobs[job_id]["failed_models"].append(failure)
                self._transition_model(
                    job_id,
                    model,
                    "failed",
                    user_error,
                    "Candidate contract rejected",
                    runtime_ms=runtime_ms,
                    user_error=user_error,
                    technical_error=str(exc),
                    traceback_reference=reference,
                )
            else:
                row["runtime_ms"] = runtime_ms
                row["candidate_id"] = candidate_contract["candidate_id"]
                row["training_job_id"] = candidate_contract["training_job_id"]
                row["training_run_id"] = candidate_contract["training_run_id"]
                row["candidate_contract"] = candidate_contract
                for lineage_field in (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                    "training_dataset_id",
                    "training_dataset_version_id",
                    "target_contract_id",
                    "predictor_manifest_id",
                    "predictor_manifest_hash",
                    "treatment_manifest_id",
                    "treatment_manifest_hash",
                    "feature_manifest_id",
                    "feature_manifest_hash",
                    "feature_manifest_version",
                    "materialization_id",
                    "validation_design_id",
                    "validation_design_version",
                    "split_id",
                    "training_population_id",
                    "selection_partition_id",
                    "holdout_population_id",
                    "final_holdout_partition_id",
                    "fold_definition_id",
                    "final_holdout_status",
                    "holdout_isolation_status",
                    "selection_integrity_status",
                ):
                    row[lineage_field] = candidate_contract.get(lineage_field)
                row["candidate_status"] = (
                    "Unsupervised diagnostic, not champion eligible"
                    if not row.get("champion_eligible", True)
                    else "Candidate, not approved"
                )
                self._transition_model(
                    job_id,
                    model,
                    "complete",
                    "Model fit completed and its candidate contract was frozen.",
                    "Candidate contract persisted",
                    runtime_ms=runtime_ms,
                    metrics=row,
                    result=row,
                    warning=result.get("warning"),
                    best_parameters=row.get("best_params"),
                    search_summary={"runtime_ms": row.get("search_runtime_ms"), "parameter_grid": row.get("parameter_grid")},
                )
                with self._lock:
                    job = self._jobs[job_id]
                    job["partial_ranked_results"].extend(ranked)
                    job["partial_results"] = list(job["partial_ranked_results"])
                    job["_artifacts"].update(artifacts)
                    job["_raw_results"].update(raw)
                    job["_candidate_contracts"][candidate_contract["candidate_id"]] = candidate_contract
                    job["completed_count"] += 1
                    job["completed_models"].append(model)
        else:
            failed = summary.get("failed") if isinstance(summary.get("failed"), list) else []
            technical = (failed[0].get("error") if failed else None) or result.get("technical_error") or result.get("error") or "Model fit failed."
            user_error = _friendly_error(model, technical)
            reference = f"training-error-{uuid4().hex[:12]}"
            failure = {"key": model, "name": MODEL_CATALOG.get(model, {}).get("label", model), "error": user_error, "technical_error": str(technical), "traceback_reference": reference}
            with self._lock:
                self._jobs[job_id]["failed_models"].append(failure)
            self._transition_model(job_id, model, "failed", user_error, "Fit failed", runtime_ms=runtime_ms, user_error=user_error, technical_error=str(technical), traceback_reference=reference)
        with self._lock:
            job = self._jobs[job_id]
            job["finished_count"] += 1
            job["user_message"] = f"{job['finished_count']} of {job['total_count']} models finished; {job['completed_count']} successful."
            job["message"] = job["user_message"]

    def _finalize(
        self,
        job_id: str,
        request: TrainingJobRequest,
        X_train,
        y_train,
        final_status: str | None = None,
    ) -> bool:
        if self._interrupt_if_scope_changed(job_id):
            return False
        with self._lock:
            if self._jobs[job_id]["overall_status"] == "cancelled":
                return False
        persistence_started = time.perf_counter()
        with self._lock:
            job = self._jobs[job_id]
            ranked = list(job["partial_ranked_results"])
            frozen_training_contract = deepcopy(job["contract"])
            materialization_id = str(
                job.get("materialization_id")
                or frozen_training_contract.get("materialization_id")
                or ""
            )
        assert_training_contract_intact(frozen_training_contract)
        for row in ranked:
            candidate_contract = row.get("candidate_contract")
            if not isinstance(candidate_contract, dict):
                raise CandidateContractError(
                    "A completed result is missing its frozen candidate contract."
                )
            assert_candidate_contract_intact(candidate_contract)
            if any(
                str(candidate_contract.get(key) or "")
                != str(frozen_training_contract.get(key) or "")
                for key in (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                    "training_dataset_id",
                    "training_dataset_version_id",
                    "target_contract_id",
                    "predictor_manifest_hash",
                    "treatment_manifest_hash",
                    "feature_manifest_hash",
                    "feature_manifest_version",
                    "materialization_id",
                    "validation_design_id",
                    "validation_design_version",
                    "split_id",
                    "training_population_id",
                    "selection_partition_id",
                    "holdout_population_id",
                    "final_holdout_partition_id",
                    "fold_definition_id",
                    "final_holdout_status",
                    "holdout_isolation_status",
                    "training_job_id",
                    "training_run_id",
                )
            ):
                raise CandidateContractError(
                    "A completed result no longer matches the frozen training contract."
                )
        problem_type = str(ranked[0].get("task") if ranked else request.problem_type or "")
        ranked.sort(
            key=lambda row: selection_sort_key(
                row,
                str(frozen_training_contract.get("ranking_metric") or ""),
                problem_type,
            )
        )
        candidate = next((row for row in ranked if row.get("champion_eligible", True)), None)
        if candidate:
            candidate["candidate_champion"] = True
            candidate["candidate_status"] = "Candidate champion, governance approval required"
        for row in ranked:
            if not row.get("champion_eligible", True):
                row["candidate_champion"] = False
                row["candidate_status"] = "Unsupervised diagnostic, not champion eligible"
        summary = {
            "problem_type": problem_type,
            "ranked": ranked,
            "raw": job["_raw_results"],
            "failed": job["failed_models"],
            "project_id": request.project_id,
            "dataset_id": job["dataset_id"],
            "dataset_version_id": job["dataset_version_id"],
            "dataset_version": job["dataset_version_id"],
            "data_revision": job["data_revision"],
            "target": job["target"],
            "event_value": job["event_value"],
            "non_event_value": job["non_event_value"],
            "training_job_id": job["job_id"],
            "training_run_id": job["training_run_id"],
            "requested_models": job["requested_models"],
            "completed_models": list(job["completed_models"]),
            "total_count": int(job["total_count"]),
            "finished_count": int(job["finished_count"]),
            "queued_models": [],
            "current_models": [],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "runtime_ms": job["runtime_ms"],
            "n_train": int(len(y_train)),
            "n_test": int(job["preflight"].get("test_rows") or 0),
            "input_feature_names": job["input_feature_names"],
            "trained_feature_names": job["trained_feature_names"],
            "engineered_feature_names": job["engineered_feature_names"],
            "transformed_feature_names": job["transformed_feature_names"],
            "feature_count": job["feature_count"],
            "n_features": job["feature_count"],
            "feature_manifest_version": job["feature_manifest_version"],
            "feature_manifest_id": job["feature_manifest_id"],
            "feature_manifest_hash": job["feature_manifest_hash"],
            "materialization_id": materialization_id,
            "predictor_manifest_id": job["predictor_manifest_id"],
            "predictor_manifest_hash": job["predictor_manifest_hash"],
            "treatment_manifest_id": job["treatment_manifest_id"],
            "treatment_manifest_hash": job["treatment_manifest_hash"],
            "target_contract_id": job["target_contract_id"],
            "split_id": job["split_id"],
            "training_population_id": job["training_population_id"],
            "selection_partition_id": job["selection_partition_id"],
            "holdout_population_id": job["holdout_population_id"],
            "final_holdout_partition_id": job[
                "final_holdout_partition_id"
            ],
            "fold_definition_id": job["fold_definition_id"],
            "final_holdout_status": job["final_holdout_status"],
            "holdout_isolation_status": job["holdout_isolation_status"],
            "selection_integrity_status": "verified",
            "selection_resampling_status": job[
                "selection_resampling_status"
            ],
            "primary_metric": job["contract"].get("ranking_metric"),
            "validation_design_id": job.get("validation_design_id"),
            "validation_design_version": job.get(
                "validation_design_version"
            ),
            "excluded_target_features": job["_excluded_target_features"],
            "k_folds": int(job["preflight"]["cross_validation_compatibility"]["effective_folds"]),
            "max_parallel": int(job["max_parallel_honored"]),
            "calibrate": bool(request.calibrate),
            "use_pca": False,
            "grid_search": bool(request.grid_search),
            "grid_search_level": request.grid_search_level,
            "model_params": request.model_params,
            "status": final_status or job["overall_status"],
            "contract": job["contract"],
            "candidate_contracts": [
                deepcopy(row["candidate_contract"])
                for row in ranked
            ],
        }
        # Recheck and persist inside the same per-scope state transition lock
        # used by Dataset Library activation and preparation invalidation.
        # Therefore activation either wins before this block (and rejects the
        # job) or runs afterward and clears everything written here.
        dataset_store = job["_dataset_store"]
        with dataset_store.state_lock:
            if self._interrupt_if_scope_changed(job_id):
                return False
            with self._lock:
                if self._jobs[job_id]["overall_status"] in {
                    "cancelled",
                    "interrupted",
                }:
                    return False
            governance_repository = (
                job.get("_governance_repository")
                or get_persistence_service().holdout_governance
            )
            durable_exposure = (
                governance_repository.get_holdout_exposure_for_partition(
                    project_id=str(job.get("project_id") or ""),
                    dataset_id=str(job.get("dataset_id") or ""),
                    dataset_version_id=str(
                        job.get("dataset_version_id") or ""
                    ),
                    validation_design_id=str(
                        job.get("validation_design_id") or ""
                    ),
                    validation_design_version_id=str(
                        job.get("validation_design_version") or ""
                    ),
                    split_id=str(job.get("split_id") or ""),
                    final_holdout_partition_id=str(
                        job.get("final_holdout_partition_id") or ""
                    ),
                )
            )
            if durable_exposure is not None:
                raise CandidateContractError(
                    "The exact final-holdout partition was durably exposed "
                    "after this job began. Its candidate results cannot be "
                    "published as verified selection evidence."
                )
            if ranked:
                candidates_by_algorithm = {
                    str(row["candidate_contract"]["algorithm_id"]): row[
                        "candidate_contract"
                    ]
                    for row in ranked
                }
                metadata = {
                    key: {
                        "project_id": request.project_id,
                        "dataset_id": job["dataset_id"],
                        "dataset_version_id": job["dataset_version_id"],
                        "dataset_version": job["dataset_version_id"],
                        "target": job["target"],
                        "problem_type": problem_type,
                        "model_key": key,
                        "training_run_id": job["training_run_id"],
                        "training_job_id": job["job_id"],
                        "candidate_id": candidates_by_algorithm.get(key, {}).get(
                            "candidate_id"
                        ),
                        "trained_at": job["completed_at"],
                        "input_feature_names": job["input_feature_names"],
                        "trained_feature_names": job["trained_feature_names"],
                        "engineered_feature_names": job["engineered_feature_names"],
                        "feature_manifest_version": job["feature_manifest_version"],
                        "feature_manifest_id": job["feature_manifest_id"],
                        "feature_manifest_hash": job["feature_manifest_hash"],
                        "materialization_id": materialization_id,
                        "predictor_manifest_id": job["predictor_manifest_id"],
                        "predictor_manifest_hash": job["predictor_manifest_hash"],
                        "treatment_manifest_id": job["treatment_manifest_id"],
                        "treatment_manifest_hash": job["treatment_manifest_hash"],
                        "target_contract_id": job["target_contract_id"],
                        "split_id": job["split_id"],
                        "training_population_id": job[
                            "training_population_id"
                        ],
                        "selection_partition_id": job[
                            "selection_partition_id"
                        ],
                        "holdout_population_id": job[
                            "holdout_population_id"
                        ],
                        "final_holdout_partition_id": job[
                            "final_holdout_partition_id"
                        ],
                        "fold_definition_id": job["fold_definition_id"],
                        "final_holdout_status": job[
                            "final_holdout_status"
                        ],
                        "holdout_isolation_status": job[
                            "holdout_isolation_status"
                        ],
                        "selection_integrity_status": "verified",
                        "selection_metric": deepcopy(
                            candidates_by_algorithm.get(key, {}).get(
                                "selection_metric"
                            )
                            or {}
                        ),
                        "class_encoding": deepcopy(
                            candidates_by_algorithm.get(key, {}).get(
                                "class_encoding"
                            )
                            or {}
                        ),
                        "validation_design_id": job.get("validation_design_id"),
                        "validation_design_version": job.get("validation_design_version"),
                        "candidate_contract": deepcopy(
                            candidates_by_algorithm.get(key) or {}
                        ),
                    }
                    for key in job["_artifacts"]
                }
                job["_result_store"].set_model_artifacts(
                    job["_artifacts"],
                    metadata,
                )
                summary["result_persistence_ms"] = int(
                    (time.perf_counter() - persistence_started) * 1000
                )
                job["_result_store"].set_last_summary(json_safe(summary))
            dataset_store.meta["training_execution"] = json_safe(
                {
                    "project_id": job["project_id"],
                    "dataset_id": job["dataset_id"],
                    "dataset_version_id": job["dataset_version_id"],
                    "dataset_version": job["dataset_version_id"],
                    "data_revision": job["data_revision"],
                    "training_job_id": job["job_id"],
                    "training_run_id": job["training_run_id"],
                    "status": final_status or job["overall_status"],
                    "candidate_strategy": request.candidate_strategy,
                    "requested_models": job["requested_models"],
                    "completed_models": job["completed_models"],
                    "failed_models": job["failed_models"],
                    "ranked_candidates": ranked,
                    "candidate_contracts": [
                        deepcopy(row["candidate_contract"])
                        for row in ranked
                    ],
                    "feature_manifest_version": job["feature_manifest_version"],
                    "feature_manifest_id": job["feature_manifest_id"],
                    "feature_manifest_hash": job["feature_manifest_hash"],
                    "materialization_id": materialization_id,
                    "predictor_manifest_id": job["predictor_manifest_id"],
                    "predictor_manifest_hash": job["predictor_manifest_hash"],
                    "treatment_manifest_id": job["treatment_manifest_id"],
                    "treatment_manifest_hash": job["treatment_manifest_hash"],
                    "target_contract_id": job["target_contract_id"],
                    "split_id": job["split_id"],
                    "training_population_id": job[
                        "training_population_id"
                    ],
                    "selection_partition_id": job[
                        "selection_partition_id"
                    ],
                    "holdout_population_id": job[
                        "holdout_population_id"
                    ],
                    "final_holdout_partition_id": job[
                        "final_holdout_partition_id"
                    ],
                    "fold_definition_id": job["fold_definition_id"],
                    "final_holdout_status": job["final_holdout_status"],
                    "holdout_isolation_status": job[
                        "holdout_isolation_status"
                    ],
                    "selection_integrity_status": "verified",
                    "validation_design_id": job.get("validation_design_id"),
                    "validation_design_version": job.get(
                        "validation_design_version"
                    ),
                    "contract": job["contract"],
                    "completed_at": job["completed_at"],
                    "runtime_ms": job["runtime_ms"],
                }
            )
            with self._lock:
                job["summary"] = summary
                job["partial_ranked_results"] = ranked
                job["partial_results"] = ranked
        return True

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return json_safe(
            {
                key: deepcopy(value)
                for key, value in job.items()
                if not key.startswith("_") and key != "idempotency_key"
            }
        )


TRAINING_JOBS = TrainingJobService()
