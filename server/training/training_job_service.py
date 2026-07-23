from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import os
from threading import Event, Lock, Thread
import time
from typing import Any, Tuple
from uuid import uuid4

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.result_store import RESULTS
from ..core.session_checkpoint import save_checkpoint
from .trainer import MODEL_CATALOG, train_models
from .trainer_service import TRAINER
from .training_job_types import TrainingJobRequest
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
# ever starts; the background thread receives X_train/X_test/y_train/y_test
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
        return f"{label} failed because train or holdout does not contain the required target classes."
    if "memory" in lowered:
        return f"{label} exceeded the available local memory limit. Reduce features, data, or parallel workers."
    if "could not be initialized" in lowered or "unavailable" in lowered or "not installed" in lowered:
        return f"{label} is unavailable in the current Python environment."
    return f"{label} failed: {detail}"


class TrainingJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, Event] = {}
        self._project_job_ids: dict[ScopeKey, list[str]] = {}
        self._lock = Lock()

    def preflight(self, request: TrainingJobRequest) -> dict[str, Any]:
        return training_preflight(request)

    def create(self, request: TrainingJobRequest, owner_user_id: str) -> dict[str, Any]:
        create_started = time.perf_counter()
        preflight = self.preflight(request)
        if not preflight["ready"]:
            raise ValueError("Training preflight blocked job creation: " + " | ".join(preflight["blocking_errors"]))
        models = list(dict.fromkeys(request.models))
        if not models:
            raise ValueError("No supported models were selected for training.")
        if request.use_pca:
            raise ValueError("PCA is not implemented by the current training pipeline and cannot be enabled.")

        X_train, X_test, y_train, y_test, excluded = TRAINER._get_or_create_splits(request.k_folds)
        trained_feature_names = [str(column) for column in X_train.columns]
        requested_parallel = max(1, int(request.max_parallel or 1))
        safe_parallel = min(
            requested_parallel,
            int(preflight.get("recommended_parallelism") or 1),
            len(models),
            max(1, min(4, os.cpu_count() or 1)),
        )
        job_id = f"train-job-{uuid4().hex}"
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
        job: dict[str, Any] = {
            "job_id": job_id,
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
            "input_feature_names": trained_feature_names,
            "trained_feature_names": trained_feature_names,
            "engineered_feature_names": list(preflight.get("engineered_features") or []),
            "transformed_feature_names": [],
            "feature_count": len(trained_feature_names),
            "n_features": len(trained_feature_names),
            "dataset_id": preflight["dataset_id"],
            "dataset_version": preflight["dataset_version"],
            "feature_manifest_version": preflight["feature_manifest_version"],
            "split_id": preflight["split_id"],
            "project_id": request.project_id,
            "owner_user_id": owner_user_id,
            "problem_type": preflight["problem_type"],
            "target": preflight["target"],
            "event_value": preflight["event_value"],
            "non_event_value": preflight["non_event_value"],
            "preflight": preflight,
            "summary": None,
            "contract": {
                "project_id": request.project_id,
                "dataset_id": preflight["dataset_id"],
                "dataset_version": preflight["dataset_version"],
                "target": preflight["target"],
                "event_value": preflight["event_value"],
                "non_event_value": preflight["non_event_value"],
                "feature_manifest_version": preflight["feature_manifest_version"],
                "selected_original_features": preflight["selected_original_features"],
                "selected_engineered_features": preflight["engineered_features"],
                "preprocessing_pipeline": request.preprocessing_pipeline or manifest.get("pipeline_steps", []),
                "split_id": preflight["split_id"],
                "split_configuration": split_record.get("config") or {},
                "random_seed": request.random_seed,
                "model_list": models,
                "tuning_configuration": {"grid_search": request.grid_search, "level": request.grid_search_level, "folds": preflight["cross_validation_compatibility"]["effective_folds"]},
                "calibration_configuration": {"requested": request.calibrate, "compatibility": preflight["calibration_compatibility"]},
                "user": request.user,
                "timestamp": request.requested_at or created_at,
            },
            "_result_store": RESULTS.current(),
            "_artifacts": {},
            "_raw_results": {},
            "_excluded_target_features": excluded,
        }
        cancel_event = Event()
        scope_key: ScopeKey = (owner_user_id, request.project_id)
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = cancel_event
            self._project_job_ids.setdefault(scope_key, []).append(job_id)
        DATASTORE.meta["active_training_job_id"] = job_id

        Thread(
            target=self._run,
            args=(job_id, request, X_train.copy(), X_test.copy(), y_train.copy(), y_test.copy(), safe_parallel),
            daemon=True,
            name=f"atlas-{job_id}",
        ).start()
        return {
            "job_id": job_id,
            "status": "queued",
            "overall_status": "queued",
            "requested_models": models,
            "created_at": created_at,
            "max_parallel_honored": safe_parallel,
            "preflight": preflight,
            "creation_duration_ms": int((time.perf_counter() - create_started) * 1000),
        }

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

    def get(self, job_id: str, owner_user_id: str, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._owned_job_locked(job_id, owner_user_id, project_id)
            if not job:
                return None
            if job["overall_status"] in ACTIVE_STATES:
                active_dataset = str(DATASTORE.meta.get("dataset_version") or "in-memory")
                active_split = str((DATASTORE.meta.get("split_record") or {}).get("split_id") or "")
                if active_dataset != job["dataset_version"] or active_split != job["split_id"]:
                    event = self._cancel_events.get(job_id)
                    if event:
                        event.set()
                    job["overall_status"] = "interrupted"
                    job["completed_at"] = _now()
                    job["user_message"] = "Training interrupted because the governed dataset or split changed. Run preflight again."
                    job["message"] = job["user_message"]
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
            save_checkpoint()
        except Exception:
            pass
        return public_job

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

    def _run(self, job_id: str, request: TrainingJobRequest, X_train, X_test, y_train, y_test, max_parallel: int) -> None:
        started = time.perf_counter()
        cancel_event = self._cancel_events[job_id]
        with self._lock:
            job = self._jobs[job_id]
            job["overall_status"] = "preparing"
            job["started_at"] = _now()
            job["user_message"] = "Preparing governed matrices and local model workers."
            job["message"] = job["user_message"]

        futures: dict[Future, str] = {}
        try:
            with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="atlas-model") as executor:
                with self._lock:
                    if self._jobs[job_id]["overall_status"] != "interrupted":
                        self._jobs[job_id]["overall_status"] = "running"
                        self._jobs[job_id]["user_message"] = f"0 of {self._jobs[job_id]['total_count']} models finished."
                        self._jobs[job_id]["message"] = self._jobs[job_id]["user_message"]
                for model in self._jobs[job_id]["requested_models"]:
                    futures[executor.submit(self._train_one, job_id, model, request, X_train, X_test, y_train, y_test)] = model
                for future in as_completed(futures):
                    model = futures[future]
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
                            self._finalize(job_id, request, X_train, X_test, y_train, y_test)
                            save_checkpoint()
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
                pass
            elif cancel_event.is_set():
                job["overall_status"] = "cancelled"
                job["user_message"] = f"Training cancelled after {job['finished_count']} of {job['total_count']} models finished."
            elif job["completed_count"] == 0:
                job["overall_status"] = "failed"
                job["user_message"] = "No selected model completed successfully. Review each model's failure reason."
            else:
                job["overall_status"] = "complete"
                job["user_message"] = f"{job['completed_count']} of {job['total_count']} models completed successfully."
            job["message"] = job["user_message"]
        try:
            self._finalize(job_id, request, X_train, X_test, y_train, y_test)
            save_checkpoint()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["overall_status"] = "failed"
                job["developer_details"].append({"stage": "result_persistence", "error": repr(exc)})
                job["user_message"] = "Model fitting finished, but ATLAS could not persist the training result. Retry after reviewing technical details."
                job["message"] = job["user_message"]
        finally:
            if DATASTORE.meta.get("active_training_job_id") == job_id:
                DATASTORE.meta.pop("active_training_job_id", None)

    def _train_one(self, job_id: str, model: str, request: TrainingJobRequest, X_train, X_test, y_train, y_test) -> dict[str, Any]:
        cancel_event = self._cancel_events[job_id]
        if cancel_event.is_set():
            return {"ok": False, "cancelled": True, "model": model, "error": "Cancelled before training started."}
        started = time.perf_counter()
        self._transition_model(job_id, model, "preparing", "Validating the model-specific training contract.", "Preparing matrices")
        if X_train.empty or X_test.empty:
            raise ValueError("Train or holdout feature matrix is empty.")
        if cancel_event.is_set():
            return {"ok": False, "cancelled": True, "model": model, "error": "Cancelled during preparation."}
        self._transition_model(job_id, model, "running", "Model fit is running.", "Fitting estimator")
        calibration_info = self._jobs[job_id]["preflight"]["calibration_compatibility"].get(model, {})
        calibration_allowed = bool(request.calibrate and calibration_info.get("compatible"))
        result = train_models(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            requested_models=[model],
            grid_search=request.grid_search,
            grid_search_level=request.grid_search_level,
            model_params=request.model_params,
            calibrate=calibration_allowed,
            cv_folds=int(self._jobs[job_id]["preflight"]["cross_validation_compatibility"]["effective_folds"]),
        )
        result["runtime_ms"] = int((time.perf_counter() - started) * 1000)
        if request.calibrate and not calibration_allowed:
            result["warning"] = calibration_info.get("reason") or "Calibration was disabled for this model."
        return result

    def _record_result(self, job_id: str, model: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job["overall_status"] == "cancelled" or job["per_model_status"][model]["status"] == "cancelled":
                job["developer_details"].append(
                    {
                        "stage": "late_model_result_ignored",
                        "model": model,
                        "reason": "Result returned after user cancellation.",
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
            row["runtime_ms"] = runtime_ms
            row["candidate_status"] = (
                "Unsupervised diagnostic, not champion eligible"
                if not row.get("champion_eligible", True)
                else "Candidate, not approved"
            )
            self._transition_model(
                job_id,
                model,
                "complete",
                "Model fit completed.",
                "Metrics persisted",
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

    def _finalize(self, job_id: str, request: TrainingJobRequest, X_train, X_test, y_train, y_test) -> None:
        persistence_started = time.perf_counter()
        with self._lock:
            job = self._jobs[job_id]
            ranked = list(job["partial_ranked_results"])
        problem_type = str(ranked[0].get("task") if ranked else request.problem_type or "")
        ranked.sort(
            key=lambda row: (
                bool(row.get("champion_eligible", True)),
                float((row.get("auc") if problem_type != "regression" else row.get("r2")) or -1),
            ),
            reverse=True,
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
            "dataset_version": job["dataset_version"],
            "target": job["target"],
            "event_value": job["event_value"],
            "non_event_value": job["non_event_value"],
            "training_job_id": job["job_id"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "runtime_ms": job["runtime_ms"],
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "input_feature_names": job["input_feature_names"],
            "trained_feature_names": job["trained_feature_names"],
            "engineered_feature_names": job["engineered_feature_names"],
            "transformed_feature_names": job["transformed_feature_names"],
            "feature_count": job["feature_count"],
            "n_features": job["feature_count"],
            "feature_manifest_version": job["feature_manifest_version"],
            "split_id": job["split_id"],
            "excluded_target_features": job["_excluded_target_features"],
            "k_folds": int(job["preflight"]["cross_validation_compatibility"]["effective_folds"]),
            "max_parallel": int(job["max_parallel_honored"]),
            "calibrate": bool(request.calibrate),
            "use_pca": False,
            "grid_search": bool(request.grid_search),
            "grid_search_level": request.grid_search_level,
            "model_params": request.model_params,
            "status": job["overall_status"],
            "contract": job["contract"],
        }
        if ranked:
            metadata = {
                key: {
                    "project_id": request.project_id,
                    "dataset_id": job["dataset_id"],
                    "dataset_version": job["dataset_version"],
                    "target": job["target"],
                    "problem_type": problem_type,
                    "model_key": key,
                    "training_run_id": job["job_id"],
                    "trained_at": job["completed_at"],
                    "input_feature_names": job["input_feature_names"],
                    "trained_feature_names": job["trained_feature_names"],
                    "engineered_feature_names": job["engineered_feature_names"],
                    "feature_manifest_version": job["feature_manifest_version"],
                    "split_id": job["split_id"],
                }
                for key in job["_artifacts"]
            }
            job["_result_store"].set_model_artifacts(job["_artifacts"], metadata)
            summary["result_persistence_ms"] = int((time.perf_counter() - persistence_started) * 1000)
            job["_result_store"].set_last_summary(json_safe(summary))
        with self._lock:
            job["summary"] = summary
            job["partial_ranked_results"] = ranked
            job["partial_results"] = ranked

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return json_safe({key: deepcopy(value) for key, value in job.items() if not key.startswith("_")})


TRAINING_JOBS = TrainingJobService()
